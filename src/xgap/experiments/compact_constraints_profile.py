"""Freeze public key constraints from the recognized Chapter 6 materializer.

This verifies small, pinned source-only receipts, not query/answer artifacts or
new backend observations. The proof relies on the admitted fact-index schema
(node primary keys and non-null unique edge IDs) and the v1 materializer's
injective identity encoding. It deliberately excludes replicated scale 4.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

from xgap.experiments.ch6_fact_index import CORES
from xgap.experiments.ch6_materialize import RESOURCE
from xgap.experiments.ch6_profile_revision import revise_schema
from xgap.experiments.one_shot_records import write_once
from xgap.semantic.compact_constraints import PublicCompactConstraints, SCHEMA


PROOF_PROFILE = 'ch6-materialized-public-keys-v1'
MAX_RECEIPT_BYTES = 1024 * 1024


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def _absolute_pin(pin, root):
    # Preserve remote absolute names when inspecting a local evidence mirror;
    # macOS /home may be a symlink unrelated to the server's logical pin path.
    return dict(path=os.path.abspath(Path(root) / pin['path']), sha256=pin['sha256'],
                bytes=pin['bytes'])


def _read(pin, root, mirrors):
    reference = _absolute_pin(pin, root)
    path = Path(reference['path'])
    for old, new in sorted(mirrors, key=lambda pair: -len(str(pair[0]))):
        if path.is_relative_to(Path(old)):
            path = Path(new) / path.relative_to(Path(old))
            break
    if not 0 < reference['bytes'] <= MAX_RECEIPT_BYTES:
        raise ValueError('Public constraint proof exceeds receipt bound')
    if path.stat().st_size != reference['bytes']:
        raise ValueError('Public constraint proof pin changed')
    with path.open('rb') as stream:
        raw = stream.read(MAX_RECEIPT_BYTES + 1)
    if len(raw) != reference['bytes'] or hashlib.sha256(raw).hexdigest() != reference['sha256']:
        raise ValueError('Public constraint proof pin changed')
    return json.loads(raw), reference


def _check_deployment(doc, meta, proof, root, mirrors):
    """Bind logical facts to the actual per-source versions and RDF mappings.

Source versions are load-file hashes, not the whole-graph logical-facts hash.
The source-only profile publisher adds ontology labels to control; its pinned
control overlay is shared by native/RDF deployments without changing facts.
Full load-file hashes were sealed by materialization/admission; do not rescan
large graphs each time the small online profile contract is loaded.
"""
    sources = doc['sources']; loads = doc['offline']['rdf_loads']
    if set(sources) != set(meta['rdf_loads']) or set(loads) != set(sources):
        raise ValueError('Deployment source set differs from materialization')
    expected_terms = {}; expected_backends = {}
    mapping, _ = _read(meta['mapping'], Path(proof['path']).parent, mirrors)
    for name, source in sources.items():
        if source['version'] != loads[name]['sha256'] or len(source['replicas']) != 1:
            raise ValueError('Deployment source version or replica proof differs')
        if name != 'control' and _absolute_pin(loads[name], root) != _absolute_pin(
                meta['rdf_loads'][name], Path(proof['path']).parent):
            raise ValueError('Graph load differs from materialization')
        backend = source['replicas'][0]
        if backend in expected_terms or backend not in doc['backends']:
            raise ValueError('Deployment replica ownership differs')
        expected_terms[backend] = mapping['backend_mapping']['term_mappings'][name]
        expected_backends[backend] = mapping['backend_mapping']['backends'][name]
    if set(expected_terms) != set(doc['backends']):
        raise ValueError('Deployment includes an unproved backend')
    # Both loader paths must bind the same overlay, if the control has public labels.
    native_control = doc['offline']['native_load_files']['control.ttl']
    if _absolute_pin(native_control, root) != _absolute_pin(loads['control'], root):
        raise ValueError('Native/RDF control bindings differ')
    expected_mapping = {**mapping['backend_mapping'], 'backends': expected_backends,
                        'term_mappings': expected_terms}
    for backend in doc['backends'].values():
        semantic = backend['semantic']; engine = backend['client']['engine']
        if semantic.get('identity_property') != 'xgap_id' or semantic.get('resource_namespace') != RESOURCE:
            raise ValueError('Backend identity differs from the public key proof')
        if engine == 'fuseki':
            if (semantic.get('backend_mapping') != expected_mapping
                    or semantic.get('rdf_edge_encoding') != mapping['rdf_edge_encoding']
                    or semantic.get('rdf_node_classes') != mapping['rdf_node_classes']):
                raise ValueError('Backend RDF mapping differs from materialization')
        elif engine != 'neo4j':
            raise ValueError('Unproved deployment engine')


def build_public_compact_constraints(profile_document, *, profile_root, pin_mirrors=()):
    """Derive conservative constraints without consulting a query or private intent."""
    doc = profile_document
    meta, proof = _read(doc['offline']['materialization'], profile_root, pin_mirrors)
    if (meta.get('schema_version') != 'xgap-ch6-core-materialization-v1'
            or meta.get('success') is not True or meta.get('index_unchanged') is not True):
        raise ValueError('Successful unchanged Chapter 6 materialization required')
    if meta.get('scale') not in ('1', '.25'):
        raise ValueError('Public key proof excludes replicated scale 4')
    dataset = meta.get('dataset')
    if dataset not in CORES or meta.get('core') != CORES[dataset]:
        raise ValueError('Only the recognized complete D1/D2/D3 source core is proved')
    if doc['dataset'] != dict(dataset_id=dataset + '-core', version=meta['logical_facts_sha256']):
        raise ValueError('Public proof and profile logical facts/dataset differ')
    index, _ = _read(meta['index_receipt'], Path(proof['path']).parent, pin_mirrors)
    if (index.get('schema_version') != 'xgap-ch6-fact-index-v1'
            or index.get('success') is not True or index.get('source_archive_rows_complete') is not True
            or index.get('dataset') != dataset or index.get('core') != meta['core']):
        raise ValueError('Complete same-dataset fact-index proof required')
    counts = index['counts']; materialized = meta['counts']
    edges = counts['edges'] if meta['scale'] == '1' else counts['edges'] // 4
    if (materialized != dict(nodes=counts['nodes'], original_edges=edges, view_edges=2 * edges)
            or sum(counts['node_types'].values()) != counts['nodes']
            or counts['early_edges'] + counts['late_edges'] != counts['edges']
            or meta['scope_cut_ms'] != index['scope_cut_ms']):
        raise ValueError('Materialized counts or temporal source proof differ')
    original, _ = _read(meta['source_schema'], Path(proof['path']).parent, pin_mirrors)
    schema = doc['source_schema']
    if schema != original and schema != revise_schema(original):
        raise ValueError('Unproved source-schema revision')
    if schema.get('identity_property') != 'xgap_id' or schema.get('shared_identity_namespace') != RESOURCE:
        raise ValueError('Unproved materialized identity namespace')
    _check_deployment(doc, meta, proof, profile_root, pin_mirrors)
    nodes = {}; edges_by_label = {}; core = meta['core']
    for view in original.values():
        if not isinstance(view, dict) or 'nodes' not in view or 'edges' not in view:
            continue
        for label, spec in view['nodes'].items():
            nodes.setdefault(label, set()).update(spec['properties'])
        for edge in view['edges']:
            if edge['source'] != core['node_type'] or edge['target'] != core['target_type']:
                raise ValueError('Unproved source endpoint types')
            edges_by_label.setdefault(edge['label'], set()).update(edge['properties'])
    if set(nodes) != set(counts['node_types']) or set(edges_by_label) != {
            core['relation'], core['relation'] + '_EARLY', core['relation'] + '_LATE'}:
        raise ValueError('Source schema does not describe the materialized domains')
    keys = ['id', 'xgap_id']
    # Node optional ordinary/control scalars are functional but not assumed total.
    node_rules = {label: dict(identity_keys=keys[:], nonnull=keys[:], functional=sorted(props))
                  for label, props in sorted(nodes.items())}
    required_edge = {'id', 'xgap_id', 'timestamp', core['measure']}
    if any(props != required_edge for props in edges_by_label.values()):
        raise ValueError('Unproved edge scalar property')
    edge_rules = {label: dict(identity_keys=keys[:], nonnull=sorted(props), functional=sorted(props))
                  for label, props in sorted(edges_by_label.items())}
    schema_hash = _digest(schema)
    contract = PublicCompactConstraints.from_dict(dict(schema_version=SCHEMA,
        contract_id=PROOF_PROFILE + ':' + proof['sha256'][:16] + ':' + schema_hash[:16],
        source_schema_sha256=schema_hash, source_proof=proof, scale=meta['scale'],
        nodes=node_rules, edges=edge_rules))
    return contract.validate_source_schema(schema)


def load_public_compact_constraints(profile_document, *, profile_root, pin_mirrors=()):
    """Return None for legacy profiles; otherwise verify the whole public proof."""
    pin = profile_document['offline'].get('compact_public_constraints')
    if pin is None:
        return None
    value, _ = _read(pin, profile_root, pin_mirrors)
    contract = PublicCompactConstraints.from_dict(value)
    expected = build_public_compact_constraints(profile_document, profile_root=profile_root,
                                                pin_mirrors=pin_mirrors)
    if contract.to_dict() != expected.to_dict():
        raise ValueError('Public constraints exceed or differ from their frozen source proof')
    return contract


def publish_compact_constraints_profile(*, parent_path, parent_sha256, output, pin_mirrors=()):
    """Write a new profile and source-only contract; never alter the parent."""
    parent_path = Path(parent_path).resolve()
    with parent_path.open('rb') as stream:
        raw = stream.read(MAX_RECEIPT_BYTES + 1)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise ValueError('Parent profile exceeds receipt bound')
    if hashlib.sha256(raw).hexdigest() != parent_sha256:
        raise ValueError('Parent profile pin changed')
    doc = json.loads(raw)
    if doc['offline'].get('compact_public_constraints'):
        raise ValueError('Profile already declares a public constraint contract')
    contract = build_public_compact_constraints(doc, profile_root=parent_path.parent,
                                               pin_mirrors=pin_mirrors)
    def absolute(value):
        if isinstance(value, list):
            return [absolute(v) for v in value]
        if isinstance(value, dict):
            return {k: os.path.abspath(parent_path.parent / v) if k == 'path' and isinstance(v, str)
                    else absolute(v) for k, v in value.items()}
        return value
    child = absolute(deepcopy(doc))
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=False)
    child['offline']['compact_public_constraints'] = write_once(root / 'public-constraints.json', contract.to_dict())
    child['profile_id'] += ':' + PROOF_PROFILE
    profile = write_once(root / 'profile.json', child)
    load_public_compact_constraints(child, profile_root=root, pin_mirrors=pin_mirrors)
    return profile
