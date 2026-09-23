#!/usr/bin/env python3
"""Freeze Neo4j and control TDB2 stores from pinned, preprocessed native inputs.

No catalog construction or workload queries. A failed load is retained and never
resumed. Serve copies of successfully sealed stores in the subsequent campaign.
"""
import argparse
from dataclasses import asdict
import hashlib
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

import psutil

from prepare_rdf_tdb import DiskBoundary, GIB, REPO, stream_pin
from xgap.backends.neo4j_client import Neo4jClient
from xgap.experiments.m15_native_services import LoopbackPortReservations, _neo4j_configuration
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.process_guard import ProcessBudget, run_guarded_command
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import QueryArtifact

MAX_BATCHES = 65536
MAX_LINE_BYTES = 2*1024**2


def batches(path):
    """Stream exactly the frozen statements; do not change batch sizes or indexes."""
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rb') as handle:
        index = 0
        while raw := handle.readline(MAX_LINE_BYTES+1):
            if index >= MAX_BATCHES or len(raw) > MAX_LINE_BYTES:
                raise ValueError('Native load exceeds frozen loader bounds')
            batch = json.loads(raw)
            if batch['kind'] not in ('constraint', 'nodes', 'relationships'):
                raise ValueError('Unknown native load batch kind')
            if not isinstance(batch['statement'], str) or not batch['statement'].strip():
                raise ValueError('Native load statement is missing')
            rows = batch.get('parameters', {}).get('rows', [])
            if not isinstance(rows, list):
                raise ValueError('Native load rows must be a list')
            if batch['kind'] == 'constraint' or rows:
                yield index, hashlib.sha256(raw).hexdigest(), batch
            index += 1


def input_sources(doc):
    root = Path(doc['offline']['materialization_root']).resolve()
    sources = {}
    for name in ('load_neo4j_batches.jsonl', 'control.ttl'):
        core = doc['offline'].get('native_load_files')
        expected = core[name] if core is not None else doc['offline']['load_files'][name]
        path = Path(expected['path']).resolve() if core is not None else (root/expected['path']).resolve()
        if core is None and not path.is_relative_to(root):
            raise ValueError('Native input lies outside its frozen materialization')
        pin = stream_pin(path)
        if (pin['sha256'], pin['bytes']) != (expected['sha256'], expected.get('bytes', expected.get('size_bytes'))):
            raise ValueError('Native input changed: '+name)
        sources[name] = pin
    counts = {'nodes': 0, 'relationships': 0, 'load_calls': 0}
    if 'native_bulk_counts' in doc['offline']:
        counts=doc['offline']['native_bulk_counts']
        if set(counts)!={'nodes','relationships','load_calls'} or any(type(v) is not int or v<1 for v in counts.values()):
            raise ValueError('Invalid sealed materialization counts')
        return sources, counts
    for _, _, batch in batches(sources['load_neo4j_batches.jsonl']['path']):
        counts['load_calls'] += 1
        if batch['kind'] in ('nodes', 'relationships'):
            counts[batch['kind']] += len(batch.get('parameters', {}).get('rows', []))
    return sources, counts


def load_batches(client, path, root):
    count = 0
    for index, digest, batch in batches(path):
        intent = {'line_index': index, 'line_sha256': digest, 'kind': batch['kind'],
                  'rows': len(batch.get('parameters', {}).get('rows', [])), 'attempts': 1}
        write_once(root/f'batch-{index:04}-intent.json', intent)
        result = client.execute(QueryArtifact('load-'+str(index), 'cypher', batch['statement'],
            kind='native', parameters=batch.get('parameters', {})))
        write_once(root/f'batch-{index:04}-result.json', result.to_dict())
        if not result.success:
            raise RuntimeError(f'Native batch {index} failed; no retry: {result.error}')
        count += 1
    return count


def verify_counts(client, expected, root):
    observed = {}
    # These two fixed offline integrity reads have no workload anchor or answer.
    for kind, query in (('nodes', 'MATCH (n) RETURN count(n) AS count'),
                        ('relationships', 'MATCH ()-[r]->() RETURN count(r) AS count')):
        artifact = QueryArtifact('integrity-'+kind, 'cypher', query, kind='native')
        write_once(root/('integrity-'+kind+'-intent.json'), artifact.to_dict())
        result = client.execute(artifact)
        write_once(root/('integrity-'+kind+'-result.json'), result.to_dict())
        if not result.success or list(result.rows) != [{'count': expected[kind]}]:
            raise ValueError('Native store count differs from frozen input: '+kind)
        observed[kind] = expected[kind]
    return observed


def discovery_ready(process, url):
    started = time.monotonic();attempts = 0;last = None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic()-started < 60:
        if process.poll() is not None:
            raise RuntimeError('Neo4j exited before readiness')
        attempts += 1
        try:
            with opener.open(url, timeout=2) as response:
                data = json.loads(response.read(65537))
                if response.status == 200 and 'transaction' in data:
                    return {'discovery_requests': attempts, 'elapsed_ms': (time.monotonic()-started)*1000,
                            'query_calls': 0, 'database': 'neo4j'}
        except (OSError, ValueError) as error:
            last = str(error)
        time.sleep(.2)
    raise TimeoutError('Neo4j discovery deadline expired: '+str(last))


def graceful_stop(process):
    """Terminate only this worker's captured children; watchdog owns escalation."""
    if process.poll() is not None:
        return {'complete': False, 'reason': 'service exited before requested shutdown', 'exit_code': process.returncode}
    try:
        owner = psutil.Process(process.pid)
        children = owner.children(recursive=True)
    except psutil.NoSuchProcess:
        return {'complete': False, 'reason': 'service disappeared before shutdown'}
    targets = list(reversed(children)) + [owner]
    identities = [{'pid': p.pid, 'created': p.create_time()} for p in targets]
    for child in targets:
        try: child.terminate()
        except psutil.NoSuchProcess: pass
    _, alive = psutil.wait_procs(targets, timeout=45)
    alive = [p.pid for p in alive if p.is_running() and p.status() != psutil.STATUS_ZOMBIE]
    if not alive:
        process.wait(timeout=2)
    return {'complete': not alive, 'live_pids': alive, 'targets': identities,
            'signal': 'SIGTERM', 'exit_code': process.poll(), 'forced_kill': False}


def worker(seal_path, seal_sha256, output):
    root = Path(output);root.mkdir(parents=True, exist_ok=False)
    seal = json.loads(read_pinned(seal_path, seal_sha256))
    receipt = {'success': False, 'load_calls': None, 'integrity_query_calls': None,
               'benchmark_query_calls': 0, 'automatic_retries': 0}
    process = None;ports = None;log = None
    try:
        source = seal['sources']['load_neo4j_batches.jsonl']
        if stream_pin(source['path']) != source:
            raise ValueError('Native batches changed after admission')
        neo = Path(seal['neo4j_root']);state = root/'state'
        for part in ('data', 'transactions', 'logs', 'run', 'import', 'plugins'):
            (state/'neo4j'/part).mkdir(parents=True)
        conf = state/'conf';conf.mkdir()
        ports = LoopbackPortReservations.acquire(2);http_port, bolt_port = ports.ports
        (conf/'neo4j.conf').write_text(_neo4j_configuration(neo4j_root=neo, state_root=state,
            http_port=http_port, bolt_port=bolt_port, resource_profile=seal['neo4j_memory'],
            query_timeout_seconds=120))
        environment = {**os.environ, 'JAVACMD': seal['java']['path'], 'NEO4J_CONF': str(conf), 'NEO4J_HOME': str(neo)}
        bulk=seal.get('native_bulk_files')
        if bulk:
            for expected in bulk.values():
                if stream_pin(expected['path'])!=expected:raise ValueError('Bulk input changed')
            command=[str(neo/'bin/neo4j-admin'),'database','import','full','--id-type=string','--threads=4',
                     '--max-off-heap-memory=2G','--multiline-fields=true','--bad-tolerance=0',
                     '--skip-bad-relationships=false','--skip-duplicate-nodes=false',
                     '--report-file='+str(root/'bulk-report.txt')]
            command += ['--nodes='+ref['path'] for name,ref in sorted(bulk.items()) if name.startswith('nodes-')]
            command += ['--relationships='+bulk['relationships.csv.gz']['path'],'neo4j']
            write_once(root/'bulk-intent.json',{'command':command,'offline':True,'overwrite_destination':False})
            with (root/'bulk-import.log').open('xb') as stream:
                result=subprocess.run(command,cwd=neo,env=environment,stdout=stream,stderr=subprocess.STDOUT,
                                      timeout=seal['process_budget_per_load']['wall_seconds'])
            receipt['bulk_import_exit_code']=result.returncode
            if result.returncode:raise ValueError('Native bulk import failed; no transactional fallback')
        ports.release(0);ports.release(1)
        log = (root/'neo4j-console.log').open('xb')
        # Inherit the private worker process group created by run_guarded_command.
        process = subprocess.Popen([str(neo/'bin/neo4j'), 'console'], cwd=neo, env=environment,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=False)
        write_once(root/'owner.json', {'pid': process.pid, 'process_group': os.getpgid(process.pid),
            'worker_process_group': os.getpgrp(), 'created': psutil.Process(process.pid).create_time()})
        receipt['readiness'] = discovery_ready(process, f'http://127.0.0.1:{http_port}/')
        client = Neo4jClient(BackendDescriptor('neo4j', 'neo4j', 'cypher', 'property_graph',
            runtime={'timeout_seconds': 125}))
        client.http_url = f'http://127.0.0.1:{http_port}';client.database = 'neo4j'
        if bulk:
            constraints=[]
            for _,_,batch in batches(source['path']):
                if batch['kind']!='constraint':break
                constraints.append(batch)
            if not constraints:raise ValueError('No declared identity constraints after bulk load')
            for i,batch in enumerate(constraints):
                result=client.execute(QueryArtifact('constraint-'+str(i),'cypher',batch['statement'],kind='native'))
                write_once(root/('constraint-'+str(i)+'.json'),result.to_dict())
                if not result.success:raise ValueError('Bulk identity constraint failed')
            result=client.execute(QueryArtifact('indexes','cypher','CALL db.awaitIndexes(120)',kind='native'))
            write_once(root/'indexes.json',result.to_dict())
            if not result.success:raise ValueError('Bulk indexes did not become ready')
            receipt['load_calls']=len(constraints)+1
        else:receipt['load_calls'] = load_batches(client, source['path'], root)
        receipt['counts'] = verify_counts(client, seal['expected_counts'], root)
        receipt['integrity_query_calls'] = 2
        receipt['success'] = bool(bulk) or receipt['load_calls'] == seal['expected_counts']['load_calls']
    except Exception as error:
        receipt.update(error_type=type(error).__name__, error=str(error))
    finally:
        if process:
            try: receipt['shutdown'] = graceful_stop(process)
            except Exception as error:
                receipt['shutdown'] = {'complete': False, 'error': str(error)}
            receipt['success'] &= receipt['shutdown']['complete']
        if log: log.close()
        if ports: ports.close()
        write_once(root/'receipt.json', receipt)
    return 0 if receipt['success'] else 1


def prepare(*, profile, profile_sha256, output, java, fuseki_jar, neo4j_root,
            bulk_import=False,max_store_bytes=10*GIB,load_seconds=900):
    started = time.perf_counter();root = Path(output).resolve();root.mkdir(parents=True, exist_ok=False)
    receipt = {'schema_version': 'xgap-frozen-native-stores-v1', 'success': False, 'stores': {},
        'phase': 'offline_preprocessing', 'benchmark_query_calls': 0, 'model_calls': 0,
        'catalog_builds': 0, 'estimator_fit_calls': 0, 'automatic_retries': 0,
        'formal_campaign_ready': False}
    try:
        if subprocess.check_output(['git', 'status', '--porcelain'], cwd=REPO, text=True):
            raise ValueError('Commit loader before native execution')
        receipt['source_commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()
        doc = json.loads(read_pinned(profile, profile_sha256));sources, counts = input_sources(doc)
        if type(max_store_bytes) is not int or not GIB<=max_store_bytes<=256*GIB or not 60<=load_seconds<=3600:
            raise ValueError('Explicit offline load bounds invalid')
        if shutil.disk_usage(root).free < max_store_bytes+6*GIB:
            raise ValueError('Reserve declared store size plus 6GiB free before starting')
        neo = Path(neo4j_root).resolve()
        engine_files = [stream_pin(p) for directory in ('bin', 'lib') for p in sorted((neo/directory).rglob('*')) if p.is_file()]
        if not engine_files or not (neo/'bin/neo4j').is_file():
            raise ValueError('Pinned Neo4j runtime missing')
        budget = ProcessBudget(wall_seconds=load_seconds, max_group_rss_bytes=(8 if bulk_import else 3)*GIB, max_log_bytes=4*1024**2,
                               sample_seconds=.1, terminate_grace_seconds=5)
        seal = {'profile': {'path': str(Path(profile).resolve()), 'sha256': profile_sha256},
            'sources': sources, 'expected_counts': counts, 'neo4j_root': str(neo), 'neo4j_engine_files': engine_files,
            'java': stream_pin(java), 'fuseki_jar': stream_pin(fuseki_jar), 'process_budget_per_load': asdict(budget),
            'neo4j_memory': {'heap_initial_size': '256m', 'heap_max_size': '2g' if bulk_import else '1g', 'pagecache_size': '256m'},
            'maximum_output_bytes': max_store_bytes, 'minimum_free_disk_bytes': 6*GIB,
            'maximum_integrity_queries': 2, 'benchmark_query_calls': 0, 'catalog_and_estimator_reused': True,
            'store_usage': 'freeze after clean shutdown; serve copies only; preserve failures, no automatic retry'}
        if bulk_import:
            files=doc['offline'].get('native_bulk_files',{})
            if 'relationships.csv.gz' not in files or not any(n.startswith('nodes-') for n in files):
                raise ValueError('Explicit sealed native bulk files required')
            seal['native_bulk_files']={name:stream_pin(ref['path']) for name,ref in files.items()}
            if seal['native_bulk_files']!=files:raise ValueError('Bulk materialization changed')
            seal['maximum_integrity_queries']=3
        receipt.update(dataset=doc['dataset'], profile=seal['profile'], expected_counts=counts)
        receipt['input_seal'] = write_once(root/'input-seal.json', seal)
        disk = DiskBoundary(root,max_store_bytes)
        guard = run_guarded_command([sys.executable, str(Path(__file__).resolve()), '--worker',
            '--input-seal', receipt['input_seal']['path'], '--input-seal-sha256', receipt['input_seal']['sha256'],
            '--output', str(root/'neo4j-load')], cwd=REPO, output=root/'neo4j-guard', budget=budget, resource_monitor=disk)
        receipt['neo4j_guard'] = guard
        worker_path = root/'neo4j-load/receipt.json'
        if worker_path.exists():receipt['neo4j_load'] = stream_pin(worker_path)
        if not guard['success'] or not worker_path.exists() or not json.loads(worker_path.read_text())['success']:
            raise RuntimeError('Neo4j load failed; partial state retained and not frozen for serving')
        state = root/'neo4j-load/state/neo4j'
        files = [stream_pin(p) for part in ('data', 'transactions') for p in sorted((state/part).rglob('*')) if p.is_file()]
        store_seal = write_once(root/'neo4j-store-seal.json', {'store': str(state), 'parts': ['data', 'transactions'],
            'source': sources['load_neo4j_batches.jsonl'], 'files': files})
        receipt['stores']['neo4j'] = {'path': str(state), 'parts': ['data', 'transactions'], 'seal': store_seal,
            'files': len(files), 'bytes': sum(p['bytes'] for p in files)}
        control = root/'control-tdb2'
        args = [seal['java']['path'], '-Xms128m', '-Xmx2g', '-cp', seal['fuseki_jar']['path'],
                'tdb2.tdbloader', '--loc', str(control), sources['control.ttl']['path']]
        guarded = run_guarded_command(args, cwd=REPO, output=root/'control-guard', budget=budget, resource_monitor=disk)
        receipt['control_guard'] = guarded
        if not guarded['success']:
            raise RuntimeError('Control TDB2 load failed; partial state retained')
        files = [stream_pin(p) for p in sorted(control.rglob('*')) if p.is_file()]
        store_seal = write_once(root/'control-store-seal.json', {'store': str(control), 'source': sources['control.ttl'], 'files': files})
        receipt['stores']['control'] = {'path': str(control), 'seal': store_seal,
            'files': len(files), 'bytes': sum(p['bytes'] for p in files)}
        receipt['sources_unchanged'] = all(stream_pin(pin['path']) == pin for pin in [*sources.values(),*seal.get('native_bulk_files',{}).values()])
        receipt['engine_files_unchanged'] = all(stream_pin(pin['path']) == pin for pin in engine_files + [seal['java'], seal['fuseki_jar']])
        receipt.update(success=receipt['sources_unchanged'] and receipt['engine_files_unchanged'],
            sampled_output_peak_bytes=disk.peak, minimum_sampled_free_disk_bytes=disk.minimum_free)
    except Exception as error:
        receipt.update(error_type=type(error).__name__, error=str(error))
    receipt['offline_elapsed_ms_before_receipt'] = (time.perf_counter()-started)*1000
    receipt['cost_scope'] = 'offline pinning, engine load/index, two integrity reads, graceful shutdown and store seals; no serving or workload execution'
    pin = write_once(root/'receipt.json', receipt)
    print(json.dumps({'success': receipt['success'], 'receipt': pin, 'error': receipt.get('error'),
                      'offline_ms': receipt['offline_elapsed_ms_before_receipt']}))
    return 0 if receipt['success'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    if '--worker' in sys.argv:
        parser.add_argument('--worker', action='store_true')
        for name in ('input-seal', 'input-seal-sha256', 'output'):parser.add_argument('--'+name, required=True)
        args = parser.parse_args()
        raise SystemExit(worker(args.input_seal, args.input_seal_sha256, args.output))
    for name in ('profile', 'profile-sha256', 'output', 'java', 'fuseki-jar', 'neo4j-root'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--bulk-import',action='store_true')
    parser.add_argument('--max-store-bytes',type=int,default=10*GIB)
    parser.add_argument('--load-seconds',type=int,default=900)
    raise SystemExit(prepare(**vars(parser.parse_args())))
