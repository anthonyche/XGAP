"""New contribution-grain risks only: no external calls or full-data execution."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from rdflib import Literal, Namespace, URIRef

from test_compact_lowering import inputs, execute, financial_intents, ref
from test_compact_provider import ResponseTransport, request
from test_compact_roles_v2 import PARENT, PIN
from test_global_semantic_sparql import inputs as global_inputs
from xgap.compilers.global_semantic_sparql import compile_global_program
from xgap.experiments.compact_profile import load_compact_graph_provider, derive_compact_contribution_profile
from xgap.experiments.finbench_rdf import SCHEMA, RESOURCE
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.compact_query import SCHEMA_V2, LOWERING_V2, validate_query, compact_schema
from xgap.semantic.interpretation_candidates import interpret_candidate_question


def intent():
    return json.loads(Path('tests/fixtures/compact_contribution_v2.json').read_text())['cases'][0]['gold_compact']


def copy_edge(graph, original, identifier):
    fb=Namespace(SCHEMA); duplicate=URIRef(RESOURCE+identifier)
    for p,value in list(graph.predicate_objects(original)):
        graph.add((duplicate,p,Literal(identifier) if p==fb.xgap_id else value))


def test_multiple_witnesses_parallel_values_and_separate_grains(inputs):
    q=intent();raw=deepcopy(q)
    rows,program,_=execute(q,inputs,version='v2')
    assert rows==[{'company_id':'1','total_amount':56.0,'transfer_count':6}]
    graph=inputs[-1]['graph'];fb=Namespace(SCHEMA)
    copy_edge(graph,next(graph.subjects(fb.edgeLabel,fb.SIGNED_IN_TO)),'another-signin-witness')
    copy_edge(graph,next(graph.subjects(fb.amount,Literal(10.125))),'another-transfer-contributor')
    assert execute(q,inputs,version='v2')[0]==[{'company_id':'1','total_amount':66.125,'transfer_count':7}]
    values=deepcopy(q);values['select']['total_amount']['distinct']=True
    assert execute(values,inputs,version='v2')[0]==[{'company_id':'1','total_amount':56.0,'transfer_count':7}]
    accounts=deepcopy(q);accounts['select']={'company_id':ref('company','id'),
        'account_count':{'aggregate':'count','field':None,'distinct':False}}
    assert execute(accounts,inputs,version='v2')[0]==[{'company_id':'1','account_count':3}]
    assert q==raw and not program.holes
    meta=program.metadata['compact_lowering']
    assert meta['profile']==LOWERING_V2 and not meta['response_repair']
    assert meta['contribution_projection']['retained_identity_variables']==['account','company','transfer']
    assert len(program.operators)<=64


def test_global_shared_query_preserves_contributions(global_inputs):
    doc,_,mapping,graph=global_inputs
    program,_=lower_compact_query(intent(),doc['source_schema'],version='v2')
    artifact=compile_global_program(program,mapping)
    rows=[{str(k):v.toPython() for k,v in row.asdict().items()} for row in graph.query(artifact.text)]
    assert rows==[{'company_id':'1','total_amount':56.0,'transfer_count':6}]
    assert 'SERVICE' not in artifact.text and artifact.parameters['expanded_relations']<=4096


def test_old_failure_stays_invalid_and_new_contract_rejects_unsupported_grains():
    profile=FrozenOneShotProfile.load(PARENT,expected_sha256=PIN)
    schema=json.loads(profile.document_json)['source_schema']
    old=json.loads(Path('tests/fixtures/compact_contribution_failure_v1.json').read_text())['raw_response']['candidates'][0]['query']
    before=deepcopy(old)
    with pytest.raises(ValueError,match='Post-distinct'):lower_compact_query(old,schema)
    with pytest.raises(ValueError):lower_compact_query(old,schema,version='v2')
    with pytest.raises(ValueError):lower_compact_query(intent(),schema)
    assert old==before
    bad=intent();bad['select']['another_grain']={'aggregate':'sum','field':ref('account','balance'),'distinct':False}
    with pytest.raises(ValueError,match='one shared'):lower_compact_query(bad,schema,version='v2')
    bad=intent();bad['contribution_by']=['nonexistent']
    with pytest.raises(ValueError,match='node/edge'):validate_query(bad,version='v2')
    path=financial_intents()[1];path.pop('deduplicate_by');path['contribution_by']=['other']
    program,_=lower_compact_query(path,schema,version='v2')
    assert set(program.metadata['compact_lowering']['contribution_projection']['retained_identity_variables'])=={'start','other','medium'}
    path['select']['distance_sum']={'aggregate':'sum','field':ref('reach','length'),'distinct':False}
    with pytest.raises(ValueError,match='path aggregates'):lower_compact_query(path,schema,version='v2')
    with pytest.raises(ValueError,match='language version'):compact_schema(1,version='unknown')


def test_explicit_profile_and_one_call_wire_preserve_legacy_and_frozen_inputs(tmp_path,monkeypatch):
    parent=FrozenOneShotProfile.load(PARENT,expected_sha256=PIN);before=PARENT.read_bytes()
    old=json.loads(parent.document_json)
    pin=derive_compact_contribution_profile(parent_path=PARENT,parent_sha256=PIN,output=tmp_path/'v2')
    child=FrozenOneShotProfile.load(pin['path'],expected_sha256=pin['sha256'])
    new,_,_,_,_,_,modes=child.materialize()
    for key in ('dataset','source_schema','sources','backends'):
        assert new[key]==old[key]
    for key in ('catalog','estimator'):
        assert new[key]=={**old[key],'path':str((PARENT.parent/old[key]['path']).resolve())}
    old_modes=parent.materialize()[-1]
    changed={'provider_id','wire_profile','prompt_hash','structured_schema_hash','compact_schema','lowering_profile'}
    for mode,(policy,provider) in modes.items():
        assert policy==old_modes[mode][0]
        a,b=provider.config.safe_dict(),old_modes[mode][1].config.safe_dict()
        assert {k:v for k,v in a.items() if k not in changed}=={k:v for k,v in b.items() if k not in changed}
        assert provider.config.language_version=='v2'
        assert b==load_compact_graph_provider(mode=mode).config.safe_dict()
    assert PARENT.read_bytes()==before
    assert hashlib.sha256(before).hexdigest()==PIN
    with pytest.raises(ValueError,match='v1 parent'):
        derive_compact_contribution_profile(parent_path=pin['path'],parent_sha256=pin['sha256'],output=tmp_path/'again')
    monkeypatch.setenv('XGAP_EXTERNAL_LLM_API_KEY','fixture-never-sent')
    provider=modes['performance'][1]
    raw={'schema_version':SCHEMA_V2,'candidates':[{'candidate_id':'contribution','quality_proxy':None,'query':intent()}]}
    original=deepcopy(raw);transport=ResponseTransport(raw);provider.transport=transport
    result=interpret_candidate_question(request(),provider,candidate_cap=1)
    assert result['success'] and result['admitted_count']==1 and len(transport.calls)==1
    assert result['provenance']['raw_compact_response']==original==raw
    assert not result['provenance']['compact_lowering']['response_repair']
    # A v1 envelope arriving at v2 is rejected, never relabelled or repaired.
    from xgap.semantic.compact_query import SCHEMA as OLD_SCHEMA
    transport.payload={**raw,'schema_version':OLD_SCHEMA}
    denied=interpret_candidate_question(request(),provider,candidate_cap=1)
    assert denied['failure_category']=='compact_envelope_invalid' and len(transport.calls)==2
