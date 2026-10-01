"""Offline loads and independently owned financial source JVMs.

This boundary serves real stores. It does not select interpretations or queries,
submit jobs, call models, or classify a successful load as a benchmark result.
"""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.request
import zipfile

from prepare_native_stores import discovery_ready, graceful_stop
from prepare_rdf_tdb import DiskBoundary, stream_pin
from run_external_federation_tiny import Processes
from xgap.experiments.campaign_source_observer import CampaignSourceObserver, SourceObservationBudget
from xgap.experiments.ch6_financial_grouped_materialize import PROFILE as GROUPING_PROFILE, grouped_layout
from xgap.experiments.m15_native_services import LoopbackPortReservations, _neo4j_configuration, _fuseki_server_configuration
from xgap.experiments.one_shot_profile import native_clients, read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.owned_resources import OwnedProcess
from xgap.experiments.process_guard import ProcessBudget, _stop_group, _group_sample, run_guarded_command
from xgap.experiments.verified_store_copy import copy_sealed_store
from xgap.infrastructure.runtime import QueryArtifact

GIB = 1024**3
SCHEMA = 'xgap-financial-mixed-stores-v1'
REPO = Path(__file__).resolve().parents[1]
MEMORY = dict(heap_initial_size='256m', heap_max_size='1g', pagecache_size='1g')
FIXED_MEMORY_PROFILE = 'fixed-aggregate-v1'
INDEXES = (
    'CREATE CONSTRAINT account_xgap_id IF NOT EXISTS FOR (n:Account) REQUIRE n.xgap_id IS UNIQUE',
    'CREATE CONSTRAINT account_id IF NOT EXISTS FOR (n:Account) REQUIRE n.id IS UNIQUE',
    'CREATE INDEX account_isblocked IF NOT EXISTS FOR (n:Account) ON (n.isBlocked)',
    'CREATE INDEX transfer_timestamp IF NOT EXISTS FOR ()-[r:TRANSFERRED_TO]-() ON (r.timestamp)',
)


def load_pin(pin):
    return json.loads(read_pinned(pin['path'], pin['sha256']))


def runtime_from_seal(pin):
    """Use the deployed, previously pinned engines; never download substitutes."""
    raw = load_pin(pin)
    runtime = {k: raw[k] for k in ('neo4j_root', 'neo4j_engine_files', 'java', 'fuseki_jar')}
    for expected in runtime['neo4j_engine_files'] + [runtime['java'], runtime['fuseki_jar']]:
        if stream_pin(expected['path']) != expected:
            raise ValueError('Previously pinned source engine changed')
    neo = Path(runtime['neo4j_root'])
    if not (neo/'bin/neo4j').is_file() or not (neo/'bin/neo4j-admin').is_file():
        raise ValueError('Pinned Neo4j commands absent')
    runtime['javac'] = stream_pin(Path(runtime['java']['path']).with_name('javac'))
    return runtime


def validated_source_layout(doc):
    """Validate actual engine groups; a numeric suffix is never an engine proof.

    Existing atom receipts need no new fields. Fewer endpoints require the
    explicit grouping contract and its exact disjoint same-engine atom layout.
    """
    sources = doc.get('sources')
    if not isinstance(sources, list):
        raise ValueError('Financial source records required')
    count = doc.get('source_count', len(sources))
    if type(count) is not int or count not in (2, 4, 8, 16, 32) or len(sources) != count:
        raise ValueError('Financial source count must be 2, 4, 8, 16, or 32')
    profile = doc.get('grouping_profile')
    if profile not in (None, GROUPING_PROFILE) or (count != 32 and profile != GROUPING_PROFILE):
        raise ValueError('Grouped financial sources require the frozen grouping profile')
    if profile == GROUPING_PROFILE:
        nodes = doc.get('logical_nodes')
        if type(nodes) is not int or nodes % 32:
            raise ValueError('Grouped source canonical node count differs')
        layout = grouped_layout(count, nodes_per_bank=nodes // 32)
        if doc.get('layout') != layout:
            raise ValueError('Grouped source layout differs from the frozen atom partition')
    else:
        # Legacy atom receipts have no logical_nodes/layout fields. Only the
        # source identity and one-bank ownership are taken from this template.
        layout = grouped_layout(32, nodes_per_bank=9)
    expected = {s['source_id']: s for s in layout['sources']}
    if (any(not isinstance(s, dict) for s in sources)
            or {s.get('source_id') for s in sources} != set(expected)):
        raise ValueError('Source identities do not cover the frozen 32 atoms')
    for source in sources:
        group = expected[source['source_id']]
        if (source.get('engine') != group['engine'] or source.get('atoms') != group['atoms']
                or any(type(bank) is not int for bank in source.get('atoms', []))
                or type(source.get('materialized_nodes')) is not int or source['materialized_nodes'] < 1
                or type(source.get('logical_edges')) is not int or source['logical_edges'] < 1):
            raise ValueError('Source type/count/ownership mismatch')
        if profile == GROUPING_PROFILE:
            if (source['logical_edges'] != group['logical_edges']
                    or source.get('owned_accounts') != group['accounts']
                    or not group['accounts'] <= source['materialized_nodes'] <= doc['logical_nodes']):
                raise ValueError('Grouped source counts differ from canonical ownership')
            expected_triples = (8*source['logical_edges']+4*source['materialized_nodes']
                if source['engine'] == 'rdf' else 0)
            if type(source.get('rdf_triples')) is not int or source['rdf_triples'] != expected_triples:
                raise ValueError('Grouped RDF triple count differs from the frozen encoding')
    if sum(s['logical_edges'] for s in sources) != doc.get('logical_edges'):
        raise ValueError('Mixed-source edge ownership is incomplete')
    return sources


def materialized_sources(pin):
    doc = load_pin(pin)
    if (doc.get('schema_version') != 'xgap-financial-mixed-loads-v1' or not doc.get('success')
            or 'source_count' not in doc):
        raise ValueError('Successfully materialized financial sources required')
    sources = validated_source_layout(doc)
    for source in sources:
        if source['engine'] == 'neo4j':
            if set(source.get('native_bulk_files', {})) != {'nodes-Account.csv.gz', 'relationships.csv.gz'}:
                raise ValueError('Frozen native bulk input inventory differs')
            files = source['native_bulk_files'].values()
        else:
            files = [source['rdf_load']]
        for expected in files:
            if stream_pin(expected['path']) != expected:
                raise ValueError('Frozen mixed-source input changed')
    return doc


def serving_memory(source_count, profile=None):
    """Configured caps, not measured RSS; shared caches/OS memory are separate."""
    if type(source_count) is not int or source_count not in (2, 4, 8, 16, 32):
        raise ValueError('Invalid financial serving source count')
    if profile not in (None, FIXED_MEMORY_PROFILE):
        raise ValueError('Unknown financial serving memory profile')
    gib = 1 if profile is None else 32 // source_count
    return dict(profile=profile or 'legacy-per-source-v1',
        neo4j=dict(heap_initial_size='256m', heap_max_size=f'{gib}g', pagecache_size=f'{gib}g'),
        rdf_heap_initial='128m' if profile is None else '256m', rdf_heap_max=f'{gib}g',
        aggregate_configured_heap_gib=source_count*gib,
        aggregate_neo4j_pagecache_gib=(source_count//2)*gib)


def compile_overlay(runtime, root):
    """Reuse the admitted Jena Direct/lazy range sources against the exact jar."""
    from ch6_source_runtime import ORIGINALS
    root = Path(root); root.mkdir(parents=True, exist_ok=False)
    source = REPO/'scripts/java/XgapStorageMode.java'
    overlays = [source.parent/'jena_lazy_range'/(name+'.java') for name in ORIGINALS]
    with zipfile.ZipFile(runtime['fuseki_jar']['path']) as jar:
        for name, digest in ORIGINALS.items():
            actual = hashlib.sha256(jar.read('org/apache/jena/dboe/trans/bplustree/'+name+'.class')).hexdigest()
            if actual != digest:
                raise ValueError('Lazy range overlay requires exact admitted Jena classes')
    command = [runtime['javac']['path'], '-J-Xmx128m', '-proc:none', '--release', '21',
               '-cp', runtime['fuseki_jar']['path'], '-d', str(root), str(source), *map(str, overlays)]
    with (root/'compile.stdout').open('xb') as out, (root/'compile.stderr').open('xb') as err:
        subprocess.run(command, stdout=out, stderr=err, check=True, timeout=45)
    write_once(root/'receipt.json', dict(runtime=runtime['fuseki_jar'], originals=ORIGINALS,
        source_files=[stream_pin(p) for p in [source, *overlays]],
        compiled_files=[stream_pin(p) for p in sorted(root.rglob('*.class'))], mode='direct', overlay='lazy-v2'))
    return root


def neo_config(runtime, state, store, http_port, bolt_port, timeout_seconds, *, memory=None):
    text = _neo4j_configuration(neo4j_root=Path(runtime['neo4j_root']), state_root=Path(state),
        data_root=Path(store), http_port=http_port, bolt_port=bolt_port,
        resource_profile=MEMORY if memory is None else memory, query_timeout_seconds=timeout_seconds)
    return text + 'server.jvm.additional=-XX:ActiveProcessorCount=2\n'


def source_commands(source, runtime, state, store, ports, overlay, backend_seconds, *, client_seconds, memory=None):
    """Write private configuration; caller owns all reserved ports and processes."""
    if not 0 < backend_seconds < client_seconds:
        raise ValueError('Source query deadline must precede client transport deadline')
    if source['engine'] not in ('neo4j', 'rdf'):
        raise ValueError('Unsupported financial source engine')
    if len(ports) != (2 if source['engine'] == 'neo4j' else 1) or len(set(ports)) != len(ports):
        raise ValueError('Distinct engine-specific source ports required')
    memory = serving_memory(32) if memory is None else memory
    state, store, overlay = map(Path, (state, store, overlay)); state.mkdir(parents=True, exist_ok=False)
    name = source['source_id']
    if source['engine'] == 'neo4j':
        conf = state/'conf'; conf.mkdir()
        for part in ('logs', 'run', 'import', 'plugins'):
            (state/'neo4j'/part).mkdir(parents=True)
        (conf/'neo4j.conf').write_text(neo_config(runtime, state, store, ports[0], ports[1], backend_seconds,
            memory=memory['neo4j']))
        return dict(command=[str(Path(runtime['neo4j_root'])/'bin/neo4j'), 'console'],
            cwd=runtime['neo4j_root'], env=dict(JAVACMD=runtime['java']['path'],
                NEO4J_CONF=str(conf), NEO4J_HOME=runtime['neo4j_root']),
            route='/'+name+'/db/neo4j/tx/commit', upstream=f'http://127.0.0.1:{ports[0]}/db/neo4j/tx/commit',
            client=dict(engine='neo4j', url=f'http://127.0.0.1:{ports[0]}', database='neo4j', timeout_seconds=client_seconds, auth=None))
    (state/'config.ttl').write_text(_fuseki_server_configuration(query_timeout_seconds=backend_seconds))
    return dict(command=[runtime['java']['path'], '-Xms'+memory['rdf_heap_initial'], '-Xmx'+memory['rdf_heap_max'], '-XX:ActiveProcessorCount=2',
        '-Dxgap.rangeOverlay=lazy-v2', '-cp', str(overlay)+os.pathsep+runtime['fuseki_jar']['path'],
        'XgapStorageMode', 'direct', '--localhost', '--port', str(ports[0]), '--tdb2', '--loc', str(store),
        '--set=tdb2:fileMode=direct', '--timeout='+str(int(backend_seconds*1000)), '/'+name], cwd=str(Path(runtime['fuseki_jar']['path']).parent),
        env=dict(FUSEKI_BASE=str(state)), route='/'+name+'/sparql', upstream=f'http://127.0.0.1:{ports[0]}/{name}/sparql',
        client=dict(engine='fuseki', url=f'http://127.0.0.1:{ports[0]}', database=name, timeout_seconds=client_seconds, auth=None))


def fuseki_ready(process, port, *, seconds=90):
    """HTTP ping only; unlike a socket probe this confirms a live Fuseki server."""
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    started=time.monotonic();last=None
    while time.monotonic()-started < seconds:
        if process.poll() is not None: raise RuntimeError('Fuseki exited before HTTP readiness')
        try:
            with opener.open(f'http://127.0.0.1:{port}/$/ping',timeout=2) as response:
                if response.status==200:
                    response.read(65536)
                    return dict(discovery='GET /$/ping',query_calls=0,elapsed_seconds=time.monotonic()-started)
        except (OSError,ValueError) as error: last=str(error)
        time.sleep(.2)
    raise TimeoutError('Fuseki HTTP readiness expired: '+str(last))


def import_command(source, runtime, store, report):
    if source['engine'] == 'neo4j':
        files = source['native_bulk_files']
        return [str(Path(runtime['neo4j_root'])/'bin/neo4j-admin'), 'database', 'import', 'full', 'neo4j',
            '--id-type=string', '--threads=4', '--max-off-heap-memory=4G', '--multiline-fields=true',
            '--bad-tolerance=0', '--skip-bad-relationships=false', '--skip-duplicate-nodes=false',
            '--report-file='+str(report), '--nodes='+files['nodes-Account.csv.gz']['path'],
            '--relationships='+files['relationships.csv.gz']['path']]
    if source['engine'] != 'rdf':
        raise ValueError('Unsupported financial source engine')
    return [runtime['java']['path'], '-Xms128m', '-Xmx4g', '-XX:ActiveProcessorCount=4',
        '-cp', runtime['fuseki_jar']['path'], 'tdb2.tdbloader', '--loc', str(store), source['rdf_load']['path']]


def integrity(client, source, root):
    neo = source['engine'] == 'neo4j'
    queries = [('nodes', 'MATCH (n) RETURN count(n) AS count', source['materialized_nodes']),
               ('relationships', 'MATCH ()-[r]->() RETURN count(r) AS count', source['logical_edges'])] if neo else [
        ('triples', 'SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }', source['rdf_triples']),
        ('nodes', 'SELECT (COUNT(*) AS ?count) WHERE { ?s a <https://xgap.dev/ch6/schema/Account> }', source['materialized_nodes']),
        ('edges', 'SELECT (COUNT(*) AS ?count) WHERE { ?s a <https://xgap.dev/ch6/schema/Edge> }', source['logical_edges'])]
    observed = {}
    for name, query, expected in queries:
        result = client.execute(QueryArtifact('offline-integrity-'+name, 'cypher' if neo else 'sparql', query, kind='native'))
        write_once(Path(root)/('integrity-'+name+'.json'), result.to_dict())
        if not result.success or len(result.rows) != 1 or int(result.rows[0]['count']) != expected:
            raise ValueError('Loaded source count mismatch: '+source['source_id']+'/'+name)
        observed[name] = expected
    return observed


def completed_loads(receipt):
    """Successful counts/seals also require every loader service to retire."""
    attempts = receipt['source_attempts']
    if 'sources' in receipt:
        try:
            source_doc = dict(receipt)
            if 'logical_edges' not in source_doc:
                source_doc['logical_edges'] = sum(s['logical_edges'] for s in source_doc['sources'])
            expected = {s['source_id'] for s in validated_source_layout(source_doc)}
        except (ValueError, KeyError, TypeError):
            return False
    else:
        # Old callers supplied only the two closure dictionaries, before source
        # counts were explicit; that legacy contract remains exactly 32.
        expected = set(receipt['stores']) if len(receipt['stores']) == 32 else set()
    if not expected or set(receipt['stores']) != expected or set(attempts) != expected:
        return False
    for attempt_pin in attempts.values():
        attempt = load_pin(attempt_pin)
        if not (attempt.get('loaded_and_sealed') and attempt.get('owned_process_terminal')
                and attempt.get('cleanup', {}).get('complete')):
            return False
    return True


def require_live_sources(owned, expected_ids=None):
    """Check again after the last service starts; earlier readiness can expire."""
    expected_count = 32 if expected_ids is None else len(expected_ids)
    names = {service.name for service in owned}
    if (expected_count not in (2, 4, 8, 16, 32) or len(owned) != expected_count or len(names) != expected_count
            or (expected_ids is not None and names != set(expected_ids))):
        raise RuntimeError('Exactly the declared independently owned source services required')
    exited = [service.name for service in owned if service.process.poll() is not None]
    if exited:
        raise RuntimeError('Source exited during session startup: '+', '.join(exited))


def verify_sealed_store(store, source, attempt_root):
    """Read every frozen store byte and reject inventory/identity/count drift."""
    path = Path(store['path'])
    parts = ['data', 'transactions'] if source['engine'] == 'neo4j' else ['.']
    if (not path.is_absolute() or path != path.resolve() or path.is_symlink()
            or path != attempt_root.parent/'stores'/source['source_id']
            or store['parts'] != parts
            or Path(store['seal']['path']) != attempt_root/'store-seal.json'):
        raise ValueError('Previous store seal identity differs')
    seal = load_pin(store['seal'])
    observed = (dict(nodes=source['materialized_nodes'], relationships=source['logical_edges'])
        if source['engine'] == 'neo4j' else dict(triples=source['rdf_triples'],
            nodes=source['materialized_nodes'], edges=source['logical_edges']))
    if (seal.get('store') != str(path) or seal.get('parts') != parts
            or seal.get('source') != source or seal.get('observed') != observed):
        raise ValueError('Previous store source/count/identity differs')
    expected = {}
    for pin in seal['files']:
        member = Path(pin['path'])
        relative = member.relative_to(path)
        if (not member.is_absolute() or '..' in relative.parts or relative in expected
                or type(pin['bytes']) is not int or pin['bytes'] < 0):
            raise ValueError('Invalid previous sealed store member')
        expected[relative] = pin
    actual = {}
    for part in parts:
        base = path/part
        if base.is_symlink() or not base.is_dir():
            raise ValueError('Invalid previous frozen store directory')
        for member in base.rglob('*'):
            if member.is_symlink():
                raise ValueError('Previous frozen store links are not admitted')
            if member.is_file():
                actual[member.relative_to(path)] = member
            elif not member.is_dir():
                raise ValueError('Unsupported previous frozen store member')
    if not expected or set(actual) != set(expected):
        raise ValueError('Previous frozen store file inventory changed')
    if (type(store['files']) is not int or store['files'] != len(expected)
            or type(store['bytes']) is not int or store['bytes'] != sum(p['bytes'] for p in expected.values())):
        raise ValueError('Previous sealed store totals differ')
    for relative, member in sorted(actual.items()):
        if stream_pin(member) != expected[relative]:
            raise ValueError('Previous frozen store content changed')


def verified_resume(resume_pin, materialization_pin, runtime_input_seal_pin, materialized, runtime, root, *, retirement_pin=None, retirement_identity=None):
    """Admit only closed old attempts; leave incomplete stores untouched."""
    previous = load_pin(resume_pin)
    prior_root = Path(resume_pin['path']).parent
    if (prior_root != prior_root.resolve() or Path(resume_pin['path']).name != 'receipt.json'
            or root == prior_root or root in prior_root.parents or prior_root in root.parents
            or previous.get('storage_root') != str(prior_root/'stores')):
        raise ValueError('Previous load receipt/output identity differs')
    if (previous.get('schema_version') != SCHEMA
            or previous.get('materialization') != materialization_pin
            or previous.get('runtime_input_seal') != runtime_input_seal_pin
            or previous.get('runtime') != runtime
            or previous.get('sources') != materialized['sources']
            or previous.get('logical_facts_sha256') != materialized['logical_facts_sha256']
            or previous.get('index_statements') != list(INDEXES)):
        raise ValueError('Previous load source/runtime/materialization identity differs')
    sources = {source['source_id']: source for source in materialized['sources']}
    stores = previous['stores']; attempts = previous['source_attempts']
    inherited = previous.get('reused_source_ids', [])
    if (not set(stores) <= set(attempts) <= set(sources)
            or len(inherited) != len(set(inherited)) or not set(inherited) <= set(stores)
            or previous.get('durable_store_bytes') != sum(store['bytes'] for store in stores.values())):
        raise ValueError('Previous load source inventory/totals differs')
    # A source directory without a closure is an unfinished attempt, even if
    # its importer printed DONE. Never infer closure from store files or logs.
    own = set(attempts) - set(inherited)
    store_root = prior_root/'stores'
    if store_root.is_symlink() or not store_root.is_dir():
        raise ValueError('Previous load storage root is absent or redirected')
    if ({p.name for p in store_root.iterdir()} != own
            or any(p.is_symlink() or not p.is_dir() for p in store_root.iterdir())
            or {p.name for p in prior_root.iterdir() if p.name.startswith(('neo4j-', 'rdf-'))} != own):
        raise ValueError('Previous load has unclosed or unexpected source directories')
    guard_pins = {}; abandoned_imports = {}
    for name, pin in attempts.items():
        attempt_root = Path(pin['path']).parent
        if (Path(pin['path']) != attempt_root/'attempt-closure.json'
                or attempt_root != attempt_root.resolve() or attempt_root.name != name
                or (name not in inherited and attempt_root != prior_root/name)
                or (name in inherited and pin != previous.get('resume_provenance', {}).get('prior_attempts', {}).get(name))):
            raise ValueError('Previous source attempt identity differs')
        attempt = load_pin(pin)
        cleanup = attempt.get('cleanup', {})
        if (attempt.get('owned_process_terminal') is not True or cleanup.get('complete') is not True
                or cleanup.get('live_pids', []) != []
                or attempt.get('loaded_and_sealed') is not (name in stores)):
            raise ValueError('Previous source attempt cleanup is incomplete or seal differs')
        guard_pin = stream_pin(attempt_root/'load-guard/receipt.json')
        if 'loader_guard' in attempt and attempt['loader_guard'] != guard_pin:
            raise ValueError('Previous loader guard identity differs')
        guard = load_pin(guard_pin); retirement = guard.get('cleanup') or {}
        if (guard.get('schema_version') != 'xgap-process-guard-v1'
                or type(guard.get('exit_code')) is not int or retirement.get('complete') is not True
                or retirement.get('live_pids') != []
                or retirement.get('post_stop_reap_returncode') != guard['exit_code']):
            if name in stores or retirement_pin is None or not retirement_identity:
                raise ValueError('Previous loader guard cleanup is incomplete')
            from ch6_financial_import_retirement import validate as validate_retirement
            abandoned_imports[name] = validate_retirement(retirement_pin, previous_loaded_pin=resume_pin,
                guard_pin=guard_pin,process_pin=stream_pin(attempt_root/'load-guard/process.json'),source_id=name,
                expected_job_id=retirement_identity['job_id'],expected_host=retirement_identity['host'])
        guard_pins[name] = guard_pin
        if name in stores:
            if (guard.get('success') is not True or guard.get('status') != 'completed' or guard['exit_code'] != 0
                    or cleanup.get('forced_kill') or 'SIGKILL' in cleanup.get('signals', [])
                    or cleanup.get('signal') == 'SIGKILL'):
                raise ValueError('Previous sealed source did not complete cleanly')
        elif (attempt_root/'store-seal.json').exists():
            raise ValueError('Previous incomplete source has an unrecorded seal')
    # Verify all retirement evidence before expensive store reads or new loads.
    for name, store in stores.items():
        verify_sealed_store(store, sources[name], Path(attempts[name]['path']).parent)
    return previous, dict(prior_receipt=resume_pin, prior_attempts=attempts,
        loader_guards=guard_pins, abandoned_imports=abandoned_imports,
        incomplete_source_ids=sorted(set(attempts)-set(stores)),
        sealed_store_verification='exact inventory and streaming SHA-256 for every file',
        old_artifacts_modified=False)


def filesystem_identity(path):
    """Record the actual Linux mount covering a resolved existing path."""
    path = Path(path).resolve(strict=True)
    records = []
    unescape = lambda value: re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), value)
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.split(); split = fields.index('-'); mount = Path(unescape(fields[4]))
        if path == mount or mount in path.parents:
            records.append((len(mount.parts), dict(path=str(path), device=path.stat().st_dev,
                mount_id=fields[0], mount_point=str(mount), filesystem=fields[split+1],
                mount_source=unescape(fields[split+2]))))
    if not records:
        raise ValueError('Could not identify the loader filesystem')
    return max(records, key=lambda entry: entry[0])[1]


def prepare_rdf_work_root(path, durable_root, maximum, reserve):
    """Require an explicit new directory on a real local, separate filesystem."""
    path, durable_root = Path(path).absolute(), Path(durable_root).resolve()
    if path.is_symlink() or path.exists() or path != path.resolve():
        raise ValueError('RDF loader workspace must be new and have no redirected ancestors')
    if (path == durable_root or path in durable_root.parents or durable_root in path.parents
            or not path.parent.is_dir()):
        raise ValueError('RDF loader workspace must be disjoint with an existing parent')
    local, durable = filesystem_identity(path.parent), filesystem_identity(durable_root)
    if (local['device'] == durable['device']
            or local['filesystem'] not in {'ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'zfs'}):
        raise ValueError('RDF loader requires a separate local disk filesystem')
    free = shutil.disk_usage(path.parent).free
    if free < maximum + reserve:
        raise ValueError('RDF local disk lacks the declared per-source capacity and reserve')
    path.mkdir(mode=0o700)
    return dict(path=str(path), local_filesystem=local, durable_filesystem=durable,
        maximum_bytes=maximum, reserve_bytes=reserve, initial_free_bytes=free,
        scope='one offline RDF import at a time; compressed input, indexes and integrity checks',
        query_contract_changed=False)


class RdfLocalDisk(DiskBoundary):
    def __init__(self, root, maximum, reserve):
        super().__init__(root, maximum); self.reserve = reserve

    def sample(self, members, *, force=False):
        result = super().sample(members, force=force)
        if self.minimum_free is not None and self.minimum_free < self.reserve:
            self.status = 'offline_free_disk_reserve_reached'
        return self.status or result


class LoadDisks:
    """The importer must respect both local scratch and durable evidence bounds."""
    def __init__(self, *disks):
        self.disks = disks

    def sample(self, members, *, force=False):
        results = [disk.sample(members, force=force) for disk in self.disks]
        return next((result for result in results if result), None)


def stage_rdf_input(source, work, maximum, reserve):
    """Copy and verify compressed bytes before the importer can see the file."""
    work = Path(work); work.mkdir(mode=0o700)
    pin = source['rdf_load']; original = Path(pin['path'])
    if original.is_symlink() or not original.is_file():
        raise ValueError('Frozen RDF input may not be redirected')
    if pin['bytes'] > maximum or shutil.disk_usage(work).free < maximum + reserve:
        raise ValueError('RDF local input exceeds the declared capacity')
    destination = work/original.name; digest = hashlib.sha256(); count = 0
    with original.open('rb') as incoming, destination.open('xb') as outgoing:
        for chunk in iter(lambda: incoming.read(1024**2), b''):
            count += len(chunk)
            if count > pin['bytes']:
                raise ValueError('Frozen RDF input grew during staging')
            outgoing.write(chunk); digest.update(chunk)
        outgoing.flush(); os.fsync(outgoing.fileno())
    if count != pin['bytes'] or digest.hexdigest() != pin['sha256']:
        raise ValueError('Frozen RDF input changed during staging')
    staged = stream_pin(destination)
    if (staged['bytes'], staged['sha256']) != (pin['bytes'], pin['sha256']):
        raise ValueError('Staged RDF input readback differs')
    (work/'store').mkdir()
    return {**source, 'rdf_load': staged}


def copy_local_rdf_store(working, durable, maximum, reserve):
    """Copy a closed store and independently verify durable readback before seal."""
    working, durable = Path(working), Path(durable)
    if working.is_symlink() or not working.is_dir() or any(p.is_symlink() for p in working.rglob('*')):
        raise ValueError('Local RDF store contains redirected paths')
    before = [stream_pin(p) for p in sorted(working.rglob('*')) if p.is_file()]
    total = sum(pin['bytes'] for pin in before)
    if not before or total > maximum or shutil.disk_usage(durable.parent).free < total + reserve:
        raise ValueError('Closed RDF store exceeds remaining durable capacity')
    # The loader created this empty placeholder. rmdir refuses to remove any
    # existing contents; no old or partially copied store is overwritten.
    durable.rmdir()
    copied = copy_sealed_store(working, durable, before)
    after = [stream_pin(durable/Path(pin['path']).relative_to(working)) for pin in before]
    if [(p['bytes'], p['sha256']) for p in before] != [(p['bytes'], p['sha256']) for p in after]:
        raise ValueError('Durable RDF store readback differs')
    return after, dict(**copied, local_store=str(working), durable_store=str(durable),
        durable_readback_verified=True)


def load_stores(materialization_pin, runtime_input_seal_pin, output, *, load_seconds=1800,
                max_store_bytes=512*GIB, reserve_bytes=8*GIB, progress=None, resume_pin=None,
                rdf_work_root=None, rdf_work_bytes=64*GIB, retirement_pin=None, retirement_identity=None):
    """Sequential guarded bulk loads, offline index/count checks, then durable seals.

    Neo4j loads into durable output/stores. When explicitly selected, RDF imports
    and integrity checks run on local disk, then closed stores are copied and
    rehashed into durable output/stores. Serving still uses separate verified copies.
    Explicit continuation borrows verified sealed stores and loads the unsealed
    complement into new paths; old incomplete imports are never admitted.
    """
    if type(load_seconds) is not int or not 60 <= load_seconds <= 3600:
        raise ValueError('Loader deadline must be 60..3600 seconds per source')
    if type(max_store_bytes) is not int or max_store_bytes <= 0 or type(reserve_bytes) is not int or reserve_bytes < 6*GIB:
        raise ValueError('Explicit store capacity and free reserve required')
    if type(rdf_work_bytes) is not int or not 1*GIB <= rdf_work_bytes <= 128*GIB:
        raise ValueError('Explicit RDF local workspace bound must be 1..128 GiB')
    root = Path(output).resolve()
    if resume_pin is not None:
        previous = load_pin(resume_pin)
        old_roots = {Path(resume_pin['path']).resolve().parent}
        old_roots.update(Path(pin['path']).resolve().parent.parent
            for pin in previous.get('source_attempts', {}).values())
        if any(root == old or root in old.parents or old in root.parents for old in old_roots):
            raise ValueError('New load output must be disjoint from all previous artifacts')
    root.mkdir(parents=True, exist_ok=False); started = time.perf_counter()
    receipt = dict(schema_version=SCHEMA, success=False, materialization=materialization_pin,
        runtime_input_seal=runtime_input_seal_pin, stores={}, source_attempts={}, model_calls=0, benchmark_query_calls=0,
        automatic_retries=0, maximum_concurrent_loaders=1, index_statements=list(INDEXES),
        loader_heap='4g per loader JVM; Neo4j additionally has 4g off-heap', source_memory=MEMORY,
        max_store_bytes=max_store_bytes, reserve_bytes=reserve_bytes, storage_root=str(root/'stores'),
        resume_pin=resume_pin, reused_source_ids=[], loaded_source_ids=[], reused_store_bytes=0)
    try:
        materialized = materialized_sources(materialization_pin); runtime = runtime_from_seal(runtime_input_seal_pin)
        receipt.update(runtime=runtime, sources=materialized['sources'], source_count=materialized['source_count'],
            logical_edges=materialized['logical_edges'], logical_facts_sha256=materialized['logical_facts_sha256'])
        for key in ('grouping_profile', 'layout', 'logical_nodes'):
            if key in materialized:
                receipt[key] = materialized[key]
        if resume_pin is not None:
            previous, provenance = verified_resume(resume_pin, materialization_pin,
                runtime_input_seal_pin, materialized, runtime, root,
                retirement_pin=retirement_pin,retirement_identity=retirement_identity)
            receipt.update(stores=dict(previous['stores']),
                source_attempts={name: previous['source_attempts'][name] for name in previous['stores']},
                reused_source_ids=sorted(previous['stores']),
                reused_store_bytes=sum(store['bytes'] for store in previous['stores'].values()),
                resume_provenance=provenance)
        borrowed = receipt['reused_store_bytes']
        (root/'stores').mkdir()
        if borrowed >= max_store_bytes:
            raise ValueError('Previous sealed stores exhaust durable store capacity')
        if shutil.disk_usage(root).free < max_store_bytes-borrowed+reserve_bytes:
            raise ValueError('Insufficient durable store capacity plus reserve')
        if rdf_work_root is not None:
            receipt['rdf_workspace'] = prepare_rdf_work_root(rdf_work_root, root, rdf_work_bytes, reserve_bytes)
        overlay = compile_overlay(runtime, root/'overlay')
        class ReservedDisk(DiskBoundary):
            def _tree_bytes(self):
                return borrowed+super()._tree_bytes()

            def sample(self, members, *, force=False):
                result=super().sample(members, force=force)
                if shutil.disk_usage(self.root).free < reserve_bytes:
                    self.status='offline_free_disk_reserve_reached'
                return self.status or result
        disk = ReservedDisk(root, max_store_bytes)
        budget = ProcessBudget(wall_seconds=load_seconds, max_group_rss_bytes=12*GIB,
            max_log_bytes=16*1024**2, sample_seconds=.2, terminate_grace_seconds=5)
        for source in materialized['sources']:
            name = source['source_id']
            if name in receipt['stores']:
                continue
            store = root/'stores'/name; evidence = root/name; evidence.mkdir()
            store.mkdir(); ports = LoopbackPortReservations.acquire(2 if source['engine']=='neo4j' else 1)
            processes = Processes(evidence); process = None; closure = None
            local_work = None; local_disk = None; guard = None; workspace_receipt = None
            try:
                active_store, active_source, monitor = store, source, disk
                if source['engine'] == 'rdf' and rdf_work_root is not None:
                    local_work = Path(receipt['rdf_workspace']['path'])/name
                    workspace_receipt = dict(source_id=name, work=str(local_work),
                        original_input=source['rdf_load'], reclaimed=False, durable_copy_verified=False)
                    active_source = stage_rdf_input(source, local_work, rdf_work_bytes, reserve_bytes)
                    active_store = local_work/'store'
                    local_disk = RdfLocalDisk(local_work, rdf_work_bytes, reserve_bytes)
                    monitor = LoadDisks(disk, local_disk)
                    workspace_receipt.update(staged_input=active_source['rdf_load'],
                        storage=receipt['rdf_workspace'], owned_inode=local_work.stat().st_ino,
                        owned_device=local_work.stat().st_dev)
                    write_once(evidence/'local-workspace-intent.json', workspace_receipt)
                    if monitor.sample(None, force=True):
                        raise ValueError('RDF local staging exceeded disk boundary')
                config = source_commands(source, runtime, evidence/'state', active_store, ports.ports, overlay, 600, client_seconds=610)
                conf_path=evidence/'state/conf/neo4j.conf'
                serving_config=conf_path.read_text() if source['engine']=='neo4j' else None
                if serving_config is not None:
                    conf_path.write_text(serving_config.replace('server.memory.heap.max_size=1g\n', 'server.memory.heap.max_size=4g\n'))
                command = import_command(active_source, runtime, active_store, evidence/'bulk-report.txt')
                write_once(evidence/'load-intent.json', dict(command=command, expected=source, offline=True))
                guard = run_guarded_command(command, cwd=REPO, output=evidence/'load-guard', budget=budget,
                    environment=config['env'], resource_monitor=monitor)
                if not guard['success']: raise RuntimeError('Offline source load failed: '+name)
                if serving_config is not None: conf_path.write_text(serving_config)
                for index in range(len(ports.ports)): ports.release(index)
                process = processes.start(name, config['command'], cwd=config['cwd'], env=config['env'])
                if source['engine']=='neo4j': discovery_ready(process, config['client']['url']+'/')
                else: fuseki_ready(process, ports.ports[0])
                client = native_clients({name: config['client']})[name]
                if source['engine']=='neo4j':
                    for index, query in enumerate((*INDEXES, 'CALL db.awaitIndexes(600)')):
                        result = client.execute(QueryArtifact('offline-index-'+str(index), 'cypher', query, kind='native'))
                        write_once(evidence/('index-'+str(index)+'.json'), result.to_dict())
                        if not result.success: raise RuntimeError('Offline index creation failed: '+str(result.error))
                observed = integrity(client, source, evidence)
                closure = graceful_stop(process)
                write_once(evidence/'shutdown.json', closure)
                if not closure.get('complete') or 'SIGKILL' in closure.get('signals',[]):
                    raise RuntimeError('Offline source shutdown was incomplete or forced: '+name)
                if shutil.disk_usage(root).free < reserve_bytes or monitor.sample(None, force=True):
                    raise ValueError('Offline source store exceeded disk boundary')
                parts = ['data','transactions'] if source['engine']=='neo4j' else ['.']
                if local_work is not None:
                    current_bytes = disk._tree_bytes()
                    files, copy_record = copy_local_rdf_store(active_store, store,
                        max_store_bytes-current_bytes, reserve_bytes)
                    workspace_receipt.update(durable_copy_verified=True, durable_copy=copy_record)
                    write_once(evidence/'local-store-copy.json', copy_record)
                    if disk.sample(None, force=True):
                        raise ValueError('Durable RDF copy exceeded disk boundary')
                else:
                    files = [stream_pin(p) for part in parts for p in sorted((store/part).rglob('*')) if p.is_file()]
                seal = write_once(evidence/'store-seal.json', dict(store=str(store), parts=parts, files=files, source=source, observed=observed))
                receipt['stores'][name] = dict(path=str(store), parts=parts, files=len(files), bytes=sum(p['bytes'] for p in files), seal=seal)
                receipt['loaded_source_ids'].append(name)
                if progress: progress(dict(phase='load', source_id=name, completed=len(receipt['stores']), observed=observed))
            finally:
                retirement=closure
                try:
                    if process is not None and (process.poll() is None or _group_sample(process.pid)):
                        retirement=_stop_group(process, ProcessBudget(terminate_grace_seconds=5))
                    elif process is None:
                        retirement=dict(complete=True,service_not_started=True)
                except Exception as error:
                    retirement=dict(complete=False,error_type=type(error).__name__,error=str(error))
                finally:
                    ports.close()
                    for log in processes.logs: log.close()
                if workspace_receipt is not None:
                    if local_disk is not None:
                        workspace_receipt.update(sampled_peak_bytes=local_disk.peak,
                            minimum_sampled_free_bytes=local_disk.minimum_free,
                            disk_status=local_disk.status)
                    # Reclaim only our exact new subtree, after successful
                    # guard, service shutdown, durable readback and seal.
                    can_reclaim = (name in receipt['stores'] and workspace_receipt['durable_copy_verified']
                        and guard and guard.get('success') and guard.get('cleanup', {}).get('complete')
                        and retirement and retirement.get('complete') and process is not None
                        and process.poll() is not None and not _group_sample(process.pid))
                    if can_reclaim:
                        try:
                            if (local_work.is_symlink() or local_work != local_work.resolve()
                                    or local_work.parent != Path(receipt['rdf_workspace']['path'])
                                    or local_work.stat().st_ino != workspace_receipt['owned_inode']
                                    or local_work.stat().st_dev != workspace_receipt['owned_device']):
                                raise ValueError('Local workspace ownership changed')
                            shutil.rmtree(local_work)
                            workspace_receipt['reclaimed'] = True
                        except Exception as error:
                            workspace_receipt.update(reclamation_error_type=type(error).__name__, reclamation_error=str(error))
                    receipt.setdefault('rdf_workspaces', {})[name] = write_once(evidence/'local-workspace-closure.json', workspace_receipt)
                receipt['source_attempts'][name]=write_once(evidence/'attempt-closure.json',dict(
                    loaded_and_sealed=name in receipt['stores'],cleanup=retirement,
                    owned_process_terminal=process is None or process.poll() is not None,
                    loader_guard=stream_pin(evidence/'load-guard/receipt.json')
                        if (evidence/'load-guard/receipt.json').is_file() else None))
                if workspace_receipt is not None and name in receipt['stores'] and not workspace_receipt['reclaimed']:
                    raise RuntimeError('Verified RDF store retained its local workspace; stop before another load: '+name)
        receipt['success'] = completed_loads(receipt)
        if not receipt['success']:
            raise RuntimeError('Not all loaded source services have complete terminal shutdown receipts')
    except Exception as error:
        receipt.update(error_type=type(error).__name__, error=str(error))
    receipt['offline_seconds'] = time.perf_counter()-started
    receipt['durable_store_bytes'] = sum(s['bytes'] for s in receipt['stores'].values())
    pin = write_once(root/'receipt.json', receipt)
    return pin


class FinancialSourceSession:
    """One independent JVM per actual source, with distinct native routes."""
    def __init__(self, prepared_pin, root, *, budget, serving_root=None, reserve_bytes=8*GIB,
                 backend_seconds=840, client_seconds=860, serving_memory_profile=None):
        if not isinstance(budget, SourceObservationBudget): raise TypeError('Explicit observation budget required')
        if not 0 < backend_seconds < budget.timeout_seconds < client_seconds <= 900:
            raise ValueError('Require backend < observer < client <= 900 second request deadline')
        self.prepared_pin = prepared_pin; self.prepared = load_pin(prepared_pin)
        if self.prepared.get('schema_version') != SCHEMA or not self.prepared.get('success'):
            raise ValueError('Successful complete financial source loads required')
        # Legacy prepared receipts did not repeat total logical_edges; derive
        # that one metadata field without changing the pinned receipt.
        source_doc = dict(self.prepared)
        if 'logical_edges' not in source_doc and isinstance(source_doc.get('sources'), list):
            source_doc['logical_edges'] = sum(s['logical_edges'] for s in source_doc['sources'])
        self.sources = validated_source_layout(source_doc)
        self.source_ids = [source['source_id'] for source in self.sources]
        self.source_count = len(self.sources)
        if set(self.prepared.get('stores', {})) != set(self.source_ids):
            raise ValueError('Prepared stores must cover every declared financial source')
        self.memory = serving_memory(self.source_count, serving_memory_profile)
        self.port_count = sum(2 if source['engine'] == 'neo4j' else 1 for source in self.sources)
        self.root = Path(root).resolve(); self.root.mkdir(parents=True, exist_ok=False)
        self.store_root = self.root/'serving' if serving_root is None else Path(serving_root).resolve()
        if serving_root is not None and (self.store_root==self.root or self.root in self.store_root.parents or self.store_root in self.root.parents):
            raise ValueError('Separate serving workspace must be disjoint from evidence')
        self.store_root.mkdir(parents=True, exist_ok=False)
        self.budget = budget; self.backend_seconds=backend_seconds; self.client_seconds=client_seconds
        self.reserve_bytes=reserve_bytes; self.ports=None; self.observer=None
        self.processes=Processes(self.root); self.owned=[]; self.client_specs={}; self.ready_pin=None

    def start(self):
        began=time.perf_counter()
        try:
            runtime=runtime_from_seal(self.prepared['runtime_input_seal'])
            if runtime != self.prepared['runtime']: raise ValueError('Prepared source runtime changed')
            needed=sum(store['bytes'] for store in self.prepared['stores'].values())
            if shutil.disk_usage(self.store_root).free < needed+self.reserve_bytes: raise ValueError('Serving copies exceed capacity')
            for name, store in self.prepared['stores'].items():
                seal=load_pin(store['seal'])
                if seal['store']!=store['path'] or seal['parts']!=store['parts']: raise ValueError('Store seal identity differs')
                copied=copy_sealed_store(store['path'], self.store_root/name, seal['files'], parts=store['parts'])
                write_once(self.root/('copy-'+name+'.json'), copied)
            overlay=compile_overlay(runtime, self.root/'overlay')
            self.ports=LoopbackPortReservations.acquire(self.port_count); at=0; routes={}
            for source in self.sources:
                name=source['source_id']; count=2 if source['engine']=='neo4j' else 1
                ports=self.ports.ports[at:at+count]
                config=source_commands(source, runtime, self.root/('state-'+name), self.store_root/name, ports, overlay,
                    self.backend_seconds, client_seconds=self.client_seconds, memory=self.memory)
                for index in range(at,at+count): self.ports.release(index)
                at+=count; process=self.processes.start(name, config['command'], cwd=config['cwd'], env=config['env'])
                self.owned.append(OwnedProcess(name, 'source', process))
                if source['engine']=='neo4j': discovery_ready(process, config['client']['url']+'/')
                else: fuseki_ready(process, ports[0])
                routes[config['route']]=config['upstream']; self.client_specs[name]=config['client']
            require_live_sources(self.owned, self.source_ids)
            self.observer=CampaignSourceObserver(routes, self.root/'source-observations', budget=self.budget)
            for name, spec in self.client_specs.items():
                spec['url']=self.observer.base_url+('/'+name if spec['engine']=='neo4j' else '')
            self.ready_pin=write_once(self.root/'ready.json', dict(prepared=self.prepared_pin, client_specs=self.client_specs,
                routes=routes, jvm_processes=self.source_count, logical_sources=self.source_count,
                reserved_ports=self.port_count, source_memory=self.memory['neo4j'],
                serving_memory_profile=self.memory['profile'],
                fuseki_heap_initial=self.memory['rdf_heap_initial'], fuseki_heap_per_source=self.memory['rdf_heap_max'],
                aggregate_configured_heap_gib=self.memory['aggregate_configured_heap_gib'],
                aggregate_neo4j_pagecache_gib=self.memory['aggregate_neo4j_pagecache_gib'],
                active_processor_count_per_jvm=2, allocation_resource_assumption='32 CPU / 128 GiB; actual allocation recorded by caller',
                tdb2_file_mode='direct', range_overlay='lazy-v2', budget=asdict(self.budget),
                backend_query_seconds=self.backend_seconds,client_transport_seconds=self.client_seconds,
                fuseki_timeout_enforcement='Explicit Fuseki --timeout argument, milliseconds',
                offline_fresh_session_ms=(time.perf_counter()-began)*1000, warmup_queries=0,
                source_groups=[dict(name=s.name,pid=s.process.pid) for s in self.owned],
                storage=dict(durable_prepared=self.prepared_pin, serving_root=str(self.store_root), evidence_root=str(self.root))))
            return self
        except BaseException:
            self.close(); raise

    def close(self):
        records=[]
        for name, process in reversed(self.processes.owned):
            try:
                cleanup=_stop_group(process, ProcessBudget(terminate_grace_seconds=5))
                records.append(dict(name=name, pid=process.pid, cleanup=cleanup, terminal=process.poll() is not None))
            except Exception as error:
                records.append(dict(name=name,pid=process.pid,cleanup=dict(complete=False,error=str(error)),terminal=False))
        observer_error=None
        if self.observer:
            try: self.observer.close()
            except Exception as error: observer_error=type(error).__name__+': '+str(error)
        for log in self.processes.logs: log.close()
        if self.ports: self.ports.close()
        result=dict(owned_groups_drained=all(r['cleanup'].get('complete') for r in records),
            owned_processes_terminal=all(r['terminal'] for r in records),
            observer_stopped=observer_error is None and (self.observer is None or (not self.observer.thread.is_alive() and not self.observer.inflight)),
            observer_close_error=observer_error, processes=records, serving_copies_retained=True)
        if not (self.root/'closed.json').exists(): write_once(self.root/'closed.json',result)
        return result
