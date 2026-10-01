"""Offline, source-only publication for an entire same-facts FinBench snapshot.

Load files are streamed and left at their immutable materialization paths. The
small profile, model and catalog retain the existing runtime contracts. No
question, reference, model service or graph engine is read/called here.
"""

from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.catalog.build import freeze_resolution_bundle
from xgap.experiments.compact_profile import load_compact_graph_provider
from xgap.experiments.financial_nl_profile import schema_and_catalog
from xgap.experiments.finbench_rdf import local_identity
from xgap.experiments.m15_finbench_partition import (
    ENTITY_PLACEMENTS, NEO4J_BATCH_FILENAME, _canonical_sha256,
)
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, SCHEMA, read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.planning.runtime_estimator import FrozenSourceStatistics, SourceStatistics
from xgap.planning.runtime_work_deployment import FrozenWorkDeployment
from xgap.planning.runtime_work_estimator import FrozenWorkEstimator
from xgap.semantic import normalize_semantic_mention


ASSETS = ('mapping.json', NEO4J_BATCH_FILENAME, 'graph.ttl', 'control.ttl')
CATALOG_FIELDS = {predicate for entity in ENTITY_PLACEMENTS for _, predicate in entity.fuseki_columns}


def verify_asset(path, pin):
    """Hash a large load artifact without the 16-MiB metadata-reader boundary."""
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.name != pin['path']:
        raise ValueError('Load artifact must be the pinned regular file')
    digest = hashlib.sha256(); size = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block); size += len(block)
    if size != pin['size_bytes'] or digest.hexdigest() != pin['sha256']:
        raise ValueError('Load artifact size/hash mismatch: '+path.name)


def _compact_write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        stream.write('\n')


def describe_source(root, manifest):
    """Scan all source entities, names and control categories, not query anchors."""
    root = Path(root)
    mapping_bytes = (root/'mapping.json').read_bytes()
    schema, catalog, bindings, mapping = schema_and_catalog(manifest,
        {'mapping.json': mapping_bytes, NEO4J_BATCH_FILENAME: b''})
    # Reuse schema descriptors only; no numeric/timestamp edge-value expansion.
    entries = catalog['entries']; counts = Counter(); logical_bytes = 0
    identities = {}; entity_count = 0
    for entry in entries:
        entry['provenance'] = {'source': 'schema'}
    with (root/NEO4J_BATCH_FILENAME).open() as stream:
        for line in stream:
            batch = json.loads(line); digest = batch.pop('batch_sha256')
            if digest != _canonical_sha256(batch):
                raise ValueError('Materialized batch hash mismatch')
            kind, table = batch['kind'], batch['source_table']
            for row in batch.get('parameters', {}).get('rows', []):
                if kind not in ('nodes', 'relationships'):
                    raise ValueError('Unexpected row-bearing batch')
                counts[table] += 1
                logical_bytes += len(json.dumps(row, ensure_ascii=False, allow_nan=False,
                    separators=(',', ':')).encode())
                if kind != 'nodes':
                    continue
                local = local_identity(table, row['id']); props = row['props']
                if props.get('xgap_id') != local or local in identities:
                    raise ValueError('Noncanonical or duplicate serving entity')
                identities[local] = table; entity_count += 1
                # A typed business-ID label is unambiguous; bare IDs/names may
                # intentionally have several candidates and are never authority.
                label = table+' '+row['id']
                aliases = []; seen = {normalize_semantic_mention(label)}
                for value in (row['id'], *(props.get(k) for k in ('personName', 'companyName', 'nickname'))):
                    if isinstance(value, str) and value.strip():
                        normalized = normalize_semantic_mention(value)
                        if normalized not in seen:
                            aliases.append(value); seen.add(normalized)
                candidate = 'entity:'+local
                entries.append({'candidate_id': candidate, 'kind': 'entity',
                    'canonical_label': label, 'aliases': aliases, 'authoritative_mentions': [],
                    'provenance': {'table': table}})
                bindings[candidate] = {'kind': 'entity', 'value': local, 'identity_property': 'xgap_id'}
    if (dict(counts) != {k:v for k,v in manifest['table_rows'].items() if v}
            or entity_count != manifest['entity_count']
            or sum(counts.values())-entity_count != manifest['relationship_count']):
        raise ValueError('Serving counts differ from materialized snapshot')
    scalars = {json.dumps(False): False, json.dumps(True): True}
    control_subjects = set(); control_bytes = 0; control_triples = 0
    with (root/'control.ttl').open() as stream:
        for line in stream:
            if not line.strip() or line.startswith('@prefix '):
                continue
            subject, predicate, tail = line.rstrip('\n').split(' ', 2)
            if not subject.startswith('<'+mapping['resource_namespace']) or not subject.endswith('>'):
                raise ValueError('Unexpected control identity namespace')
            local = subject[len(mapping['resource_namespace'])+1:-1]
            if local not in identities:
                raise ValueError('Control entity missing from graph')
            control_subjects.add(local); control_triples += 1
            control_bytes += len(line.encode())
            # This publisher consumes the pinned serializer's finite grammar,
            # not arbitrary RDF. Source type/identity triples are not scalars.
            if not predicate.startswith('xgapfb:') or predicate[7:] not in CATALOG_FIELDS:
                continue
            if not tail.endswith(' .'):
                raise ValueError('Changed control serialization')
            value = json.loads(tail[:-2])
            if type(value) not in (str, bool):
                raise ValueError('Unexpected control category type')
            if value != '':
                scalars[json.dumps(value, ensure_ascii=False)] = value
    if len(control_subjects) != manifest['control_identity_entities'] or control_subjects != set(identities):
        raise ValueError('Control and graph entity identity sets differ')
    # Replace the bootstrap booleans with stable value-derived candidate IDs.
    entries[:] = [e for e in entries if e['kind'] != 'constraint']
    bindings = {k:v for k,v in bindings.items() if v['kind'] != 'constraint'}
    for encoded, value in sorted(scalars.items()):
        candidate = 'constraint:'+hashlib.sha256(encoded.encode()).hexdigest()
        entries.append({'candidate_id': candidate, 'kind': 'constraint',
            'canonical_label': str(value).lower() if isinstance(value, bool) else value,
            'aliases': [], 'authoritative_mentions': [], 'provenance': {'source': 'control'}})
        bindings[candidate] = {'kind': 'constraint', 'value': value}
    entries.sort(key=lambda e:e['candidate_id'])
    catalog.update(catalog_id='finbench-serving-v1', catalog_version=manifest['source_partition_sha256'],
        metadata={'offline': True, 'source_partition_sha256': manifest['source_partition_sha256'],
            'question_reads': 0, 'answer_reads': 0, 'entity_scope': 'all source entities; typed IDs, bare IDs and observed names',
            'scalar_scope': 'all observed control categories plus booleans; other typed constants stay query literals',
            'authority': 'all entries are predictions, never authoritative identity'})
    total = sum(counts.values())
    if not total or not control_subjects:
        raise ValueError('Serving snapshot must contain graph and control facts')
    summary = {'table_rows': dict(counts), 'entity_count': entity_count,
        'relationship_count': total-entity_count, 'control_entity_count': len(control_subjects),
        'control_triple_count': control_triples, 'catalog_entry_count': len(entries),
        'catalog_kind_counts': dict(Counter(e['kind'] for e in entries)),
        'graph_logical_row_bytes': logical_bytes, 'control_serialized_bytes': control_bytes,
        'row_width_scope': 'graph compact load-row JSON bytes; control serialized triple bytes per entity; work proxies, not result/wire cardinality'}
    return schema, catalog, bindings, mapping, summary


def publish_serving_profile(*, rdf_root, manifest_sha256, model_path, model_sha256,
                            output, dataset_id, endpoints, fuseki_dataset='finbench'):
    started = time.perf_counter(); rdf_root = Path(rdf_root).resolve(); output = Path(output)
    manifest = json.loads(read_pinned(rdf_root/'manifest.json', manifest_sha256))
    if manifest.get('schema_version') != 'xgap-finbench-same-facts-rdf-v1' or manifest.get('success') is not True:
        raise ValueError('A successful same-facts materialization is required')
    if set(manifest['output_files']) != set(ASSETS):
        raise ValueError('Unexpected same-facts load manifest')
    for name in ASSETS:
        verify_asset(rdf_root/name, manifest['output_files'][name])
    model = FrozenWorkEstimator.from_dict(json.loads(read_pinned(model_path, model_sha256)))
    schema, catalog, bindings, mapping, summary = describe_source(rdf_root, manifest)
    output.mkdir(parents=True, exist_ok=False)
    summary_pin = write_once(output/'source_summary.json', summary)
    statistics = FrozenSourceStatistics('finbench-serving-source-statistics-v1', manifest_sha256, (
        SourceStatistics('neo4j', 'graph', manifest['output_files'][NEO4J_BATCH_FILENAME]['sha256'],
            summary['entity_count']+summary['relationship_count'],
            summary['graph_logical_row_bytes']/(summary['entity_count']+summary['relationship_count']), summary_pin['sha256']),
        SourceStatistics('fuseki', 'control', manifest['output_files']['control.ttl']['sha256'],
            summary['control_entity_count'], summary['control_serialized_bytes']/summary['control_entity_count'], summary_pin['sha256'])))
    deployed = FrozenWorkDeployment('finbench-serving-toy-transfer-v1', model, statistics,
        'offline-source-summary:'+summary_pin['sha256'])
    deployed.save(output/'estimator.json')
    _compact_write(output/'catalog-input.json', catalog); _compact_write(output/'bindings-input.json', bindings)
    frozen = freeze_resolution_bundle(catalog=output/'catalog-input.json', bindings=output/'bindings-input.json', output=output/'catalog')
    modes = {}
    for mode in ('precision', 'performance'):
        provider = load_compact_graph_provider(mode=mode); config = provider.config
        prompt = output/(mode+'.txt'); prompt.write_text(provider.system_prompt)
        modes[mode] = {'policy': asdict(OneShotPolicy.for_mode(mode)), 'provider': {
            'provider_id': config.provider_id, 'base_url': config.base_url, 'model': config.model,
            'api_key_env': config.api_key_env, 'wire_profile': config.safe_dict()['wire_profile'],
            'prompt': {'path': prompt.name, 'sha256': hashlib.sha256(prompt.read_bytes()).hexdigest()},
            'temperature': config.temperature, 'top_p': config.top_p, 'max_tokens': config.max_tokens,
            'timeout_seconds': config.timeout_seconds, 'disable_thinking': True}}
    common = {'resource_namespace': mapping['resource_namespace'], 'identity_property': 'xgap_id'}
    semantic = {'neo4j': common, 'fuseki': {**common, **{k:mapping[k] for k in
        ('backend_mapping', 'rdf_edge_encoding', 'rdf_node_classes')}}}
    doc = {'schema_version': SCHEMA, 'profile_id': dataset_id+':compact-graph-v1',
        'dataset': {'dataset_id': dataset_id, 'version': manifest['source_archive']['sha256']},
        'source_schema': schema,
        'sources': {s.source_id: {'version': s.snapshot_version, 'replicas': [s.backend_id]} for s in statistics.entries},
        'backends': {b: {'semantic': spec, 'client': {'engine': b, 'url': endpoints[b],
            'database': 'neo4j' if b=='neo4j' else fuseki_dataset, 'timeout_seconds': 20, 'auth': None}}
            for b,spec in semantic.items()},
        'catalog': {'path': 'catalog', 'bundle_hash': frozen['bundle_hash']},
        'estimator': {'path': 'estimator.json', 'sha256': hashlib.sha256((output/'estimator.json').read_bytes()).hexdigest()},
        'modes': modes, 'offline': {'scope': 'source-only serving publication; full same-facts data, uncalibrated toy-model transfer',
            'materialization_root': str(rdf_root), 'manifest_sha256': manifest_sha256,
            'load_files': manifest['output_files'], 'source_summary': summary_pin,
            'trained_model_file_sha256': model_sha256, 'trained_model_content_sha256': model.model_sha256,
            'weights_changed': False, 'transfer_calibrated': False,
            'query_reads': 0, 'answer_reads': 0, 'model_calls': 0, 'backend_calls': 0, 'fit_calls': 0,
            'serving_services_started': False, 'formal_campaign_ready': False,
            'runtime_watchdog_and_common_external_interface': 'pending before campaign'}}
    pin = write_once(output/'profile.json', doc)
    at = time.perf_counter()
    FrozenOneShotProfile.load(pin['path'], expected_sha256=pin['sha256'])
    load_ms = (time.perf_counter()-at)*1000
    # Detect source changes across the complete publication, including large assets.
    for name in ASSETS:
        verify_asset(rdf_root/name, manifest['output_files'][name])
    read_pinned(rdf_root/'manifest.json', manifest_sha256)
    write_once(output/'publication.json', {'success': True, 'profile': pin,
        'offline_publication_ms': (time.perf_counter()-started)*1000,
        'profile_load_validation_ms': load_ms, 'source_summary': summary_pin,
        'catalog_bytes': (output/'catalog-input.json').stat().st_size,
        'bindings_bytes': (output/'bindings-input.json').stat().st_size,
        'model_calls': 0, 'backend_calls': 0, 'fit_calls': 0, 'question_reads': 0, 'answer_reads': 0,
        'formal_campaign_ready': False})
    return pin
