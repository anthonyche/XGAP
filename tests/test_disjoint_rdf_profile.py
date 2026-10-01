"""Only the new disjoint-metadata boundary; reuse accepted tiny inputs, no fit."""
import hashlib
import json
from pathlib import Path
import socket

import pytest
from rdflib import Graph
from rdflib.namespace import RDF

from test_finbench_rdf import parameters, expected_rows, plain_rows
from xgap.compilers.features import default_profile
from xgap.compilers.node_match import compile_node_match
from xgap.experiments.disjoint_rdf_profile import AUX, publish_disjoint_profile, rewrite_control_line
from xgap.experiments.finbench_rdf import FAMILIES, SCHEMA, fixed_semantics_query
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.pattern.ast import NodePattern
from dataclasses import replace

BASE=Path('/Users/anthonyche/xgap-data/rdf-instances-native-20260913-v1/rdf-profile/profile.json')
BASE_SHA='a636cc548c6c11c6181f6a2745fbd9d7903a10417d271c57040fbc63d55bd72a'


@pytest.fixture(scope='module')
def published(tmp_path_factory):
    root=tmp_path_factory.mktemp('disjoint-metadata')
    with pytest.MonkeyPatch.context() as m:
        m.setattr(socket.socket,'connect',lambda *a,**kw:pytest.fail('Network in offline publication'))
        from xgap.planning import runtime_work_estimator
        m.setattr(runtime_work_estimator,'fit_work_estimator',lambda *a,**kw:pytest.fail('Refit in derivative'))
        original=Path.open
        def guarded(path,*a,**kw):
            if any(p in path.parts for p in ('references','gold','requests')):
                pytest.fail('Publication read a query or answer')
            return original(path,*a,**kw)
        m.setattr(Path,'open',guarded)
        pin=publish_disjoint_profile(base_profile=BASE,base_sha256=BASE_SHA,output=root/'v2')
    return FrozenOneShotProfile.load(pin['path'],expected_sha256=pin['sha256'])


def test_disjoint_canonical_equivalence_and_three_unchanged_public_queries(published):
    doc=json.loads(published.document_json);old=Path(doc['offline']['materialization_root'])
    g=Graph().parse(old/'graph.ttl');c=Graph().parse(old/'control.ttl')
    revised=Graph().parse(doc['offline']['rdf_loads']['control']['path'])
    assert len(g)==211 and len(c)==len(revised)==36 and len(set(g)&set(c))==24
    assert not set(g)&set(revised)
    canonical={(s,p,o) for s,p,o in g+revised if not str(p).startswith(AUX)
               and not (p==RDF.type and str(o).startswith(AUX))}
    assert canonical==set(g)|set(c)
    assert len(g+revised)==247
    for family,p,expected in zip(FAMILIES,parameters(),expected_rows()):
        query=fixed_semantics_query(family,p)
        assert AUX not in query and 'SERVICE' not in query
        assert plain_rows((g+revised).query(query))==expected


def test_local_mapping_preserves_frozen_model_and_reaches_control_compiler(published):
    doc,model,_,_,_,_,_=published.materialize()
    old_doc,old_model,_,_,_,_,_=FrozenOneShotProfile.load(BASE,expected_sha256=BASE_SHA).materialize()
    assert model.trained_model.to_dict()==old_model.trained_model.to_dict()
    assert doc['catalog']==old_doc['catalog']
    assert model.reference_backends==old_model.reference_backends
    loads=doc['offline']['rdf_loads']
    assert loads['graph']['path']==str(Path(old_doc['offline']['materialization_root'])/'graph.ttl')
    for s in model.statistics.entries:
        assert s.snapshot_version==loads[s.source_id]['sha256']
        assert hashlib.sha256(Path(loads[s.source_id]['path']).read_bytes()).hexdigest()==s.snapshot_version
    for backend in doc['backends']:
        semantic=doc['backends'][backend]['semantic']
        mapping=semantic['backend_mapping']
        for canonical in ('fuseki','rdf_graph'):
            assert mapping['term_mappings'][canonical]==old_doc['backends'][backend]['semantic']['backend_mapping']['term_mappings'][canonical]
    semantic=doc['backends']['rdf_control']['semantic']
    artifact=compile_node_match(NodePattern(label='XGAPFinBenchAccount',properties={'id':'2'}),
        {'id':'id','blocked':'isBlocked','identity':'xgap_id'},backend_id='rdf_control',
        backend_mapping=semantic['backend_mapping'],rdf_node_classes=tuple(semantic['rdf_node_classes']),
        profile=replace(default_profile('fuseki'),backend_id='rdf_control'))
    assert AUX+'sourceId' in artifact.text and AUX+'Account' in artifact.text and AUX+'xgap_id' in artifact.text
    assert SCHEMA+'isBlocked' in artifact.text
    rows=plain_rows(Graph().parse(loads['control']['path']).query(artifact.text))
    assert len(rows)==1 and {k:rows[0][k] for k in ('id','blocked','identity')}=={'id':'2','blocked':True,'identity':'account_32'}
    receipt=json.loads((published.root/'publication.json').read_text())
    assert all(receipt[k]==0 for k in ('model_calls','backend_calls','query_reads','reference_reads','fit_calls','catalog_builds','graph_copies'))


def test_token_rewrite_preserves_literal_payload_and_rejects_unknown_serialization():
    payload='"xgapfb:sourceId \\"quoted\\" '+SCHEMA+'xgap_id" .\n'
    for before,after in [('xgapfb:sourceId ','xgapaux:sourceId '),('<'+SCHEMA+'xgap_id> ','<'+AUX+'xgap_id> ')]:
        result,_=rewrite_control_line('<urn:entity> '+before+payload,{'Account'})
        assert result=='<urn:entity> '+after+payload
    unchanged='<urn:entity> xgapfb:riskLevel '+payload
    assert rewrite_control_line(unchanged,{'Account'})==(unchanged,None)
    for invalid in ('<urn:entity> rdf:type xgapfb:Unknown .\n','@prefix xgapaux: <urn:bad> .\n',
                    '<urn:entity> other:sourceId "2" .\n','<urn:entity> xgapfb:sourceId "2"\n'):
        with pytest.raises(ValueError):rewrite_control_line(invalid,{'Account'})


def test_incomplete_metadata_derivative_is_not_published(tmp_path,monkeypatch):
    from xgap.experiments import disjoint_rdf_profile as module
    original=module.rewrite_control_line
    def skip_identity(line,classes):
        changed,category=original(line,classes)
        return (line,None) if category=='xgap_id' else (changed,category)
    monkeypatch.setattr(module,'rewrite_control_line',skip_identity)
    with pytest.raises(ValueError,match='metadata counts'):
        publish_disjoint_profile(base_profile=BASE,base_sha256=BASE_SHA,output=tmp_path/'incomplete')
    assert not (tmp_path/'incomplete'/'profile.json').exists()
    assert json.loads((tmp_path/'incomplete'/'failure.json').read_text())['success'] is False
