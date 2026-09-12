"""Offline financial tiny profile publication; no question, gold or live calls.

The schema describes source placement, not an operator-to-source answer template.
The independent request is read only by the ordinary frozen-profile runner.
"""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.catalog.build import freeze_resolution_bundle
from xgap.experiments.finbench_semantic import load_financial_provider
from xgap.experiments.m15_finbench_partition import ENTITY_PLACEMENTS, RELATIONSHIP_PLACEMENTS, NEO4J_BATCH_FILENAME
from xgap.experiments.one_shot_profile import SCHEMA, FrozenOneShotProfile, read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.planning.runtime_work_estimator import frozen_estimator_from_dict


PROFILE = "financial-tiny-nl-v1"
DATASET = {"dataset_id": "financial-binding-tiny", "version": "financial-tiny-v1"}
INPUT_ROOT = Path('/Users/anthonyche/xgap-data/financial-binding-native-20260912-v1/rdf')
MANIFEST_HASH = '5f289b39d057bc704274d496c2262e655946b9af763617934c97ef2eabe0677b'
DEPLOYMENT = Path('/Users/anthonyche/xgap-data/edge-bind-training-native-20260912-v1/financial_frozen_deployment.json')
DEPLOYMENT_HASH = '300587168ef4c774232cc4bd97a79f06e381c393852c0cdb87c0f10ba0cfe3c7'
QUERY_ID = 'FINANCIAL-NL-01'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verified_inputs(root=INPUT_ROOT):
    """Only the previously pinned tiny mapping/load artifacts, never a result."""
    root = Path(root)
    manifest = json.loads(read_pinned(root/'manifest.json', MANIFEST_HASH))
    if (manifest['entity_count'], manifest['relationship_count']) != (8, 16):
        raise ValueError('Financial development profile requires the original tiny snapshot')
    files = {}
    for name in ('mapping.json', NEO4J_BATCH_FILENAME, 'control.ttl'):
        files[name] = read_pinned(root/name, manifest['output_files'][name]['sha256'])
    return manifest, files


def schema_and_catalog(manifest, files):
    mapping = json.loads(files['mapping.json'])
    batches = [json.loads(line) for line in files[NEO4J_BATCH_FILENAME].splitlines()]
    present = manifest['table_rows']
    entities = [e for e in ENTITY_PLACEMENTS if present.get(e.table_id, 0)]
    relations = [e for e in RELATIONSHIP_PLACEMENTS if present.get(e.table_id, 0)]
    schema = {'shared_identity_namespace': mapping['resource_namespace'], 'identity_property': 'xgap_id',
        'identity_semantics': 'Canonical node identity joins across stores; id is a raw string business ID, not canonical identity.',
        'graph': {'description': 'Entity types, business IDs, profile attributes and all stored directed edges; no control attributes.',
            'nodes': {e.neo4j_label: {'properties': ['id', 'xgap_id', *e.neo4j_columns]} for e in entities},
            'edges': [{'label': e.neo4j_type, 'source': 'XGAPFinBench'+e.from_entity.title(),
                'target': 'XGAPFinBench'+e.to_entity.title(), 'properties': ['xgap_id', *e.property_columns]}
                for e in relations]},
        'control': {'description': 'Entity type and identity stubs plus control attributes. No relationship edges or graph profile fields.',
            'nodes': {e.neo4j_label: {'properties': ['id', 'xgap_id', *[p[1] for p in e.fuseki_columns]]} for e in entities},
            'edges': []},
        'scalar_semantics': {'id': 'string', 'isBlocked': 'boolean', 'amount': 'number',
            'createTime': 'calendar string YYYY-MM-DD HH:MM:SS.mmm; order with timestamp_ms',
            'missing_fields': 'Missing nullable properties return null; no implicit lookup in another source.',
            'parallel_edges': 'Each edge has a separate canonical identity, even for equal endpoints and values.'}}
    entries, bindings = [], {}

    def add(kind, key, label, value, aliases=()):
        candidate = kind+':'+key
        entries.append({'candidate_id': candidate, 'kind': kind, 'canonical_label': label,
            'aliases': list(aliases), 'authoritative_mentions': [],
            'provenance': {'snapshot': manifest['source_partition_sha256'],
                'source': 'offline source schema and entity attributes', 'selection': 'prediction, not authority'}})
        bindings[candidate] = {'kind': kind, 'value': value}
        if kind == 'entity': bindings[candidate]['identity_property'] = 'xgap_id'

    plural = {'person': 'people', 'company': 'companies', 'account': 'accounts', 'medium': 'media'}
    for e in entities:
        add('type', e.table_id, e.table_id, e.neo4j_label, (plural[e.table_id], e.neo4j_label))
    relation_aliases = {'OWNS_ACCOUNT': ('owns', 'owned by', 'own', 'owned'),
        'TRANSFERRED_TO': ('transfer', 'transfers', 'sent', 'transferred'),
        'SIGNED_IN_TO': ('sign in', 'signed in', 'sign-in')}
    for label in sorted({e.neo4j_type for e in relations}):
        add('predicate', label, label, label, relation_aliases.get(label, ()))
    for source in ('graph', 'control'):
        add('source', source, source, source)
    # Extract every entity name in this tiny snapshot, without consulting a query.
    name_columns = ('personName', 'companyName', 'nickname')
    scalar_values = {json.dumps(True): True, json.dumps(False): False}
    for batch in batches:
        for row in batch.get('parameters', {}).get('rows', []):
            props = row['props']
            if batch['kind'] == 'nodes':
                label = next((props[n] for n in name_columns if props.get(n)), batch['source_table']+' '+row['id'])
                add('entity', props['xgap_id'], label, props['xgap_id'])
            for name, value in props.items():
                if name != 'xgap_id' and value != '' and isinstance(value, (str, float, int, bool)):
                    scalar_values[json.dumps(value, sort_keys=True)] = value
    for index, (encoded, value) in enumerate(sorted(scalar_values.items())):
        label = str(value).lower() if isinstance(value, bool) else str(value)
        add('constraint', str(index), label, value)
    catalog = {'schema_version': 'm15-e3-resolution-catalog-v1', 'catalog_id': PROFILE,
        'catalog_version': '1', 'entries': entries,
        'metadata': {'offline': True, 'question_reads': 0, 'scalar_domain': 'finite observed graph values plus booleans'}}
    return schema, catalog, bindings, mapping


def publish_profile(output, *, endpoints, input_root=INPUT_ROOT, deployment=DEPLOYMENT, syntax_profile="v1",
                    interpretation_profile="semantic-dag-v1"):
    """Publish before inference; endpoints are caller-owned and no service is touched."""
    at = time.perf_counter()
    if interpretation_profile not in ('semantic-dag-v1', 'compact-graph-v1'):
        raise ValueError('Unknown financial interpretation profile')
    compact = interpretation_profile == 'compact-graph-v1'
    if compact and syntax_profile != 'v1':
        raise ValueError('Legacy SGP syntax options do not apply to the compact profile')
    manifest, files = verified_inputs(input_root)
    model_bytes = read_pinned(deployment, DEPLOYMENT_HASH)
    model = frozen_estimator_from_dict(json.loads(model_bytes))
    if QUERY_ID in model.to_dict()['training_provenance']['training_query_ids']:
        raise ValueError('Financial NL request is in estimator training')
    schema, catalog, bindings, mapping = schema_and_catalog(manifest, files)
    root = Path(output); root.mkdir(parents=True, exist_ok=False)
    for name, data in {**files, 'estimator.json': model_bytes}.items():
        with (root/name).open('xb') as stream: stream.write(data)
    write_once(root/'catalog-input.json', catalog); write_once(root/'bindings-input.json', bindings)
    frozen = freeze_resolution_bundle(catalog=root/'catalog-input.json', bindings=root/'bindings-input.json', output=root/'catalog')
    modes = {}
    for mode in ('precision', 'performance'):
        if compact:
            from xgap.experiments.compact_profile import load_compact_graph_provider
            provider = load_compact_graph_provider(mode=mode)
        else:
            provider = load_financial_provider(mode=mode, disable_thinking=True, syntax_profile=syntax_profile)
        path = root/(mode+'.txt'); path.write_text(provider.system_prompt)
        c = provider.config
        modes[mode] = {'policy': asdict(OneShotPolicy.for_mode(mode)), 'provider': {
            'provider_id': c.provider_id, 'base_url': c.base_url, 'model': c.model, 'api_key_env': c.api_key_env,
            'wire_profile': c.safe_dict()['wire_profile'], 'prompt': {'path': path.name, 'sha256': sha(path)},
            'temperature': c.temperature, 'top_p': c.top_p, 'max_tokens': c.max_tokens,
            'timeout_seconds': c.timeout_seconds, 'disable_thinking': True}}
    common = {'resource_namespace': mapping['resource_namespace'], 'identity_property': 'xgap_id'}
    backends = {'neo4j': common, 'fuseki': {**common, 'backend_mapping': mapping['backend_mapping'],
        'rdf_edge_encoding': mapping['rdf_edge_encoding'], 'rdf_node_classes': mapping['rdf_node_classes']}}
    profile_id = PROFILE+':compact-graph-v1' if compact else PROFILE if syntax_profile=='v1' else PROFILE+':binding-'+syntax_profile
    doc = {'schema_version': SCHEMA, 'profile_id': profile_id,
        'dataset': DATASET, 'source_schema': schema,
        'sources': {s.source_id: {'version': s.snapshot_version, 'replicas': [s.backend_id]} for s in model.statistics.entries},
        'backends': {b: {'semantic': s, 'client': {'engine': b, 'url': endpoints[b],
            'database': 'neo4j' if b == 'neo4j' else 'tiny', 'auth': None, 'timeout_seconds': 20}}
            for b, s in backends.items()},
        'catalog': {'path': 'catalog', 'bundle_hash': frozen['bundle_hash']},
        'estimator': {'path': 'estimator.json', 'sha256': DEPLOYMENT_HASH}, 'modes': modes,
        'offline': {'scope': 'one-time tiny profile publication; reused frozen data/model, zero new collection/fit',
            'input_root': str(Path(input_root).resolve()), 'input_manifest_sha256': MANIFEST_HASH,
            'partition_sha256': manifest['source_partition_sha256'], 'deployment_file_sha256': DEPLOYMENT_HASH,
            'publication_before_validation_ms': (time.perf_counter()-at)*1000,
            'snapshot_boundary': 'pinned load bytes into empty owned stores; serving 128-byte width is a work proxy',
            'query_reads': 0, 'answer_reads': 0, 'model_calls': 0, 'backend_calls': 0, 'fit_calls': 0}}
    pin = write_once(root/'profile.json', doc)
    FrozenOneShotProfile.load(root/'profile.json', expected_sha256=pin['sha256'])
    write_once(root/'publication.json', {'profile': pin, 'elapsed_ms': (time.perf_counter()-at)*1000,
        'catalog_entries': len(catalog['entries']), 'question_reads': 0, 'answer_reads': 0, 'external_calls': 0})
    return pin
