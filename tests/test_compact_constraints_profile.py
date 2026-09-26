import hashlib
import json
import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest

from xgap.experiments.ch6_fact_index import CORES, pin, write
from xgap.experiments.ch6_materialize import materialize, RESOURCE
from xgap.experiments.ch6_profile_revision import revise_schema
from xgap.experiments.compact_constraints_profile import (
    build_public_compact_constraints, load_public_compact_constraints,
    publish_compact_constraints_profile,
)


def source_profile(tmp_path, monkeypatch, scale='1'):
    monkeypatch.setattr('xgap.experiments.ch6_materialize.shutil.disk_usage',
                        lambda path: type('Free', (), {'free': 64 * 1024**3})())
    source = tmp_path / 'index'; source.mkdir()
    db = sqlite3.connect(source / 'facts.sqlite')
    db.executescript('CREATE TABLE nodes(id TEXT PRIMARY KEY,kind TEXT NOT NULL,props TEXT NOT NULL) WITHOUT ROWID;'
                    'CREATE TABLE edges(ordinal INTEGER PRIMARY KEY,id TEXT UNIQUE NOT NULL,src TEXT NOT NULL,dst TEXT NOT NULL,ts INTEGER NOT NULL,value REAL NOT NULL);')
    db.executemany('INSERT INTO nodes VALUES(?,?,?)', [('person:a', 'Person', '{"firstName":"A","gender":"female"}'),
        ('person:b', 'Person', '{"firstName":"B","gender":"male"}')])
    db.executemany('INSERT INTO edges VALUES(?,?,?,?,?,?)', [(i, 'edge:' + str(i), 'person:a', 'person:b', i, 1.) for i in range(1, 5)])
    db.commit(); db.close()
    write(source / 'receipt.json', dict(schema_version='xgap-ch6-fact-index-v1', success=True,
        dataset='D1', core=CORES['D1'], scope_cut_ms=2, source_archive_rows_complete=True,
        database=pin(source / 'facts.sqlite'), counts=dict(nodes=2, edges=4,
            node_types={'Person': 2}, early_edges=2, late_edges=2)))
    meta = materialize(source / 'receipt.json', tmp_path / 'same-facts', scale=scale)
    assert meta['success']
    mapping = json.loads(Path(meta['mapping']['path']).read_text())
    doc = dict(profile_id='tiny-frozen', dataset=dict(dataset_id='D1-core', version=meta['logical_facts_sha256']),
        source_schema=json.loads(Path(meta['source_schema']['path']).read_text()),
        sources={name: dict(version=p['sha256'], replicas=[name]) for name, p in meta['rdf_loads'].items()},
        backends={name: dict(client=dict(engine='fuseki'), semantic=dict(identity_property='xgap_id',
            resource_namespace=RESOURCE, backend_mapping=mapping['backend_mapping'],
            rdf_edge_encoding=mapping['rdf_edge_encoding'], rdf_node_classes=mapping['rdf_node_classes']))
            for name in meta['rdf_loads']},
        offline=dict(materialization=pin(tmp_path / 'same-facts/receipt.json'), rdf_loads=meta['rdf_loads'],
                     native_load_files={'control.ttl': meta['rdf_loads']['control']}))
    return doc


@pytest.mark.parametrize('scale', ['1', '.25'])
def test_real_materializer_proof_publishes_preserving_current_revision(tmp_path, monkeypatch, scale):
    doc = source_profile(tmp_path, monkeypatch, scale)
    doc['source_schema'] = revise_schema(doc['source_schema'])
    parent = tmp_path / 'parent.json'; write(parent, doc); before = parent.read_bytes()
    result = publish_compact_constraints_profile(parent_path=parent,
        parent_sha256=hashlib.sha256(before).hexdigest(), output=tmp_path / 'published')
    child = json.loads(Path(result['path']).read_text())
    constraints = load_public_compact_constraints(child, profile_root=tmp_path / 'published')
    assert parent.read_bytes() == before
    assert child['source_schema'] == doc['source_schema']
    assert child['offline']['materialization'] == doc['offline']['materialization']
    contract = constraints.to_dict()
    assert contract['scale'] == scale
    assert contract['nodes']['Person']['nonnull'] == ['id', 'xgap_id']
    assert 'gender' in contract['nodes']['Person']['functional']
    assert contract['edges']['KNOWS']['identity_keys'] == ['id', 'xgap_id']
    assert set(contract['edges']['KNOWS']['nonnull']) == {'id', 'xgap_id', 'timestamp', 'value'}
    with pytest.raises(FileExistsError):
        publish_compact_constraints_profile(parent_path=parent,
            parent_sha256=hashlib.sha256(before).hexdigest(), output=tmp_path / 'published')


def test_reject_replication_schema_and_snapshot_without_reading_queries(tmp_path, monkeypatch):
    doc = source_profile(tmp_path, monkeypatch, '4')
    with pytest.raises(ValueError, match='replicated'):
        build_public_compact_constraints(doc, profile_root=tmp_path)
    assert load_public_compact_constraints(doc, profile_root=tmp_path) is None


def test_loader_verifies_pin_and_does_not_accept_extra_constraints(tmp_path, monkeypatch):
    doc = source_profile(tmp_path, monkeypatch)
    contract = build_public_compact_constraints(doc, profile_root=tmp_path)
    contract_path = tmp_path / 'constraints.json'; write(contract_path, contract.to_dict())
    doc['offline']['compact_public_constraints'] = pin(contract_path)
    changed = deepcopy(doc); changed['dataset']['version'] = '0' * 64
    with pytest.raises(ValueError, match='logical facts/dataset'):
        load_public_compact_constraints(changed, profile_root=tmp_path)
    changed = deepcopy(doc); changed['source_schema']['graph']['nodes']['Person']['properties'].append('invented')
    with pytest.raises(ValueError, match='source-schema revision'):
        load_public_compact_constraints(changed, profile_root=tmp_path)
    changed = deepcopy(doc); changed['sources']['graph']['version'] = '0' * 64
    with pytest.raises(ValueError, match='source version'):
        load_public_compact_constraints(changed, profile_root=tmp_path)
    changed = deepcopy(doc)
    changed['backends']['graph']['semantic']['backend_mapping']['term_mappings']['graph']['id']['representation'] += 'wrong'
    with pytest.raises(ValueError, match='RDF mapping'):
        load_public_compact_constraints(changed, profile_root=tmp_path)
    # Even a freshly pinned contract cannot declare an optional scalar total.
    raw = contract.to_dict(); raw['nodes']['Person']['nonnull'].append('firstName')
    other = tmp_path / 'overclaim.json'; write(other, raw)
    changed = deepcopy(doc); changed['offline']['compact_public_constraints'] = pin(other)
    with pytest.raises(ValueError, match='exceed or differ'):
        load_public_compact_constraints(changed, profile_root=tmp_path)
    contract_path.write_text('{}')
    with pytest.raises(ValueError, match='pin changed'):
        load_public_compact_constraints(doc, profile_root=tmp_path)
