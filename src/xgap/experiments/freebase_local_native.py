"""Explicit local development run with owned native services, never a Slurm run."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import signal
import subprocess
import time

from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.experiments.freebase_backend_loading import FactSnapshot, load_fact_snapshot
from xgap.experiments.freebase_native_answers import FactAnswerQuery, ResourceStep, compile_fact_answer, execute_fact_answer
from xgap.experiments.m15_fixture_loader import FusekiGraphStoreFixtureLoader
from xgap.experiments.m15_native_artifacts import load_native_runtime_lock
from xgap.experiments.m15_native_runtime import stage_native_artifact
from xgap.experiments.m15_native_services import (
    LoopbackPortReservations, ServiceSpec, _neo4j_configuration, _fuseki_server_configuration,
    inspect_java_runtime, start_service, stop_service, wait_for_service_health,
)
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.pattern.ast import Direction


def run_local(*, snapshot_root: str, snapshot_sha256: str, cache_root: str,
              output_root: str, java: str, lock_path: str,
              timeout_seconds: int = 1800) -> dict:
    if type(timeout_seconds) is not int or not 0 < timeout_seconds <= 3600:
        raise ValueError("Local experiment requires a finite timeout of at most one hour")
    source = FactSnapshot.load(snapshot_root, expected_manifest_sha256=snapshot_sha256,
                              max_bytes=1024**3, max_part_bytes=64*1024**2)
    root = Path(output_root).resolve()
    if root == source.root or root.is_relative_to(source.root):
        raise ValueError("Owned runtime must be outside the fact snapshot")
    root.mkdir(parents=True, exist_ok=False)
    runtime = root/'runtime'
    runtime.mkdir()
    started = time.perf_counter()
    java_evidence = inspect_java_runtime(java_command=java, required_major=21)
    lock = load_native_runtime_lock(lock_path)
    query = FactAnswerQuery('http://rdf.freebase.com/ns/type.property',
        (ResourceStep('http://rdf.freebase.com/ns/type.object.type', Direction.IN),),
        'http://rdf.freebase.com/ns/type.object.name', 'en')
    program = compile_fact_answer(query, max_rows=100000, max_binding_bytes=16*1024**2)
    record = {'schema_version':'freebase-local-native-v1', 'environment':'local-development',
        'java':java_evidence.to_dict(), 'runtime_lock_sha256':hashlib.sha256(Path(lock_path).read_bytes()).hexdigest(),
        'snapshot_manifest_sha256':snapshot_sha256, 'query':query.to_dict(),
        'timeout_seconds':timeout_seconds, 'automatic_retries':0, 'paper_result':False,
        'success':False, 'staged':[], 'health':[], 'shutdown':[]}
    (root/'request.json').write_text(json.dumps(record, indent=2))
    (root/'plan.json').write_text(json.dumps(program.plan.to_dict(), indent=2))
    (root/'baseline.json').write_text(json.dumps(program.baseline.to_dict(), indent=2))
    running = []
    ports = None
    prior_handler = signal.getsignal(signal.SIGALRM)

    def deadline(_signal, _frame):
        raise TimeoutError("Local native experiment exceeded its wall-clock budget")

    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(timeout_seconds)
    try:
        products = {}
        for artifact in lock.artifacts:
            staged = stage_native_artifact(Path(cache_root)/artifact.filename, artifact, runtime)
            record['staged'].append(staged.to_dict())
            products[artifact.product] = staged.runtime_path
        # Inspect the exact distribution's own command-line interface before startup.
        help_result = subprocess.run([java, '-jar', str(products['fuseki']/'fuseki-server.jar'), '--help'],
            text=True, capture_output=True, timeout=30)
        help_text = help_result.stdout + help_result.stderr
        (root/'fuseki-help.txt').write_text(help_text)
        record['fuseki_help_exit_code'] = help_result.returncode
        # The locked jar prints its help then exits through TerminationException
        # (exit 1). This is CLI help output, not a service-start health check.
        help_exit = help_result.returncode == 0 or (
            help_result.returncode == 1 and 'org.apache.jena.cmd.TerminationException' in help_text)
        if not help_exit or '--tdb2' not in help_text or '--loc=DIR' not in help_text:
            raise ValueError("The exact Fuseki distribution does not advertise the required TDB2 CLI")
        state = root/'state'
        for directory in ('neo4j/data','neo4j/transactions','neo4j/logs','neo4j/run',
                          'neo4j/import','neo4j/plugins','fuseki','fuseki-tdb2'):
            (state/directory).mkdir(parents=True)
        conf = state/'neo4j-conf'
        shutil.copytree(products['neo4j']/'conf', conf)
        ports = LoopbackPortReservations.acquire(3)
        neo_port, bolt_port, rdf_port = ports.ports
        config = _neo4j_configuration(neo4j_root=products['neo4j'], state_root=state,
            http_port=neo_port, bolt_port=bolt_port,
            resource_profile={'heap_initial_size':'256m','heap_max_size':'768m','pagecache_size':'256m'},
            query_timeout_seconds=120).replace('one job-owned XGAP M15 allocation', 'one owned local development run')
        (conf/'neo4j.conf').write_text(config)
        (state/'fuseki/config.ttl').write_text(_fuseki_server_configuration(query_timeout_seconds=120))
        neo_url, rdf_url = f'http://127.0.0.1:{neo_port}', f'http://127.0.0.1:{rdf_port}'
        specs = (
            ServiceSpec('neo4j','neo4j',next(a.version for a in lock.artifacts if a.product=='neo4j'),
                (str(products['neo4j']/'bin/neo4j'),'console'),products['neo4j'],
                {'JAVACMD':java,'NEO4J_CONF':str(conf),'NEO4J_HOME':str(products['neo4j'])},
                neo_url+'/db/neo4j/tx/commit',root/'neo4j.log'),
            ServiceSpec('fuseki','fuseki',next(a.version for a in lock.artifacts if a.product=='fuseki'),
                (str(products['fuseki']/'fuseki-server'),'--localhost','--ping','--port',str(rdf_port),
                 '--update','--tdb2','--loc',str(state/'fuseki-tdb2'),'/xgap'),products['fuseki'],
                {'JAVA':java,'FUSEKI_HOME':str(products['fuseki']),'FUSEKI_BASE':str(state/'fuseki'),
                 'JVM_ARGS':'-Xms256m -Xmx2g'},rdf_url+'/$/ping',root/'fuseki.log'),
        )
        (root/'services.json').write_text(json.dumps([s.to_dict() for s in specs], indent=2))
        for index,spec in enumerate(specs):
            for port_index in ((0,1) if index == 0 else (2,)):
                ports.release(port_index)
            service = start_service(spec)
            running.append(service)
            health = wait_for_service_health(service, timeout_seconds=120)
            record['health'].append(health.to_dict())
            print(json.dumps({'phase':'health','service':spec.service_id,**health.to_dict()}), flush=True)
            if not health.success:
                raise RuntimeError('Owned service failed readiness: '+str(health.last_error))
        neo_descriptor = BackendDescriptor('neo4j','neo4j','cypher','property_graph',runtime={
            'http_url_env':'XGAP_D202_UNUSED_NEO_URL','default_http_url':neo_url,
            'database_env':'XGAP_D202_UNUSED_NEO_DB','default_database':'neo4j','timeout_seconds':120})
        rdf_descriptor = BackendDescriptor('fuseki','fuseki','sparql','rdf',runtime={
            'base_url_env':'XGAP_D202_UNUSED_RDF_URL','default_base_url':rdf_url,
            'dataset_env':'XGAP_D202_UNUSED_RDF_DB','default_dataset':'xgap','timeout_seconds':120})
        neo, rdf = Neo4jClient(neo_descriptor), FusekiClient(rdf_descriptor)
        # Explicit endpoints belong to the processes above, independent of ambient settings.
        neo.http_url, neo.database = neo_url, 'neo4j'
        rdf.base_url, rdf.dataset = rdf_url, 'xgap'
        loader = FusekiGraphStoreFixtureLoader(rdf_descriptor)
        loader.base_url, loader.dataset = rdf_url, 'xgap'
        record['load'] = load_fact_snapshot(source, neo4j=neo, fuseki=rdf, fuseki_loader=loader, output_root=root/'load')
        print(json.dumps({'phase':'load', **record['load']}), flush=True)
        if not record['load']['success']:
            raise RuntimeError(record['load']['error'])
        answer = execute_fact_answer(program, neo4j=neo, fuseki=rdf)
        (root/'answers.json').write_text(json.dumps(answer, sort_keys=True, indent=2, ensure_ascii=False))
        record['answer_success'] = answer['success']
        record['answer_rows'] = len(answer['federated']['root_rows'].get('answer', []))
        record['success'] = answer['success']
        print(json.dumps({'phase':'answer','success':answer['success'],'rows':record['answer_rows']}), flush=True)
    except Exception as error:
        record['error'] = f'{type(error).__name__}: {error}'
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prior_handler)
        for service in reversed(running):
            shutdown = stop_service(service, timeout_seconds=30)
            record['shutdown'].append(shutdown.to_dict())
            if not shutdown.success or shutdown.escalated_to_kill:
                record['success'] = False
        if ports is not None:
            ports.close()
        record['elapsed_seconds'] = time.perf_counter()-started
        (root/'result.json').write_text(json.dumps(record, sort_keys=True, indent=2))
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('snapshot-root','snapshot-sha256','cache-root','output-root','java'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--lock-path', default='services/m15-native-runtime.lock.json')
    parser.add_argument('--timeout-seconds',type=int,default=1800)
    result = run_local(**vars(parser.parse_args()))
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
