"""New outer-native input boundary, verified before any service is started."""
import json
import socket

from check_practical_worker_native import FIXTURE, prepare_inputs
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.practical_profile import FrozenPracticalProfile
from xgap.experiments.practical_records import run_record
from xgap.semantic.binding import bind_semantic_query
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.program import hard_constraints_sha256


def test_trusted_native_intake_preserves_the_authored_query_and_needs_no_network(tmp_path,monkeypatch):
    monkeypatch.setattr(socket.socket,'connect',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Network during preparation')))
    pins=prepare_inputs(tmp_path/'input');p,q=pins['profile'],pins['request']
    profile,cfg=FrozenPracticalProfile.load_materialized(p['path'],expected_sha256=p['sha256'])
    raw=json.loads(read_pinned(q['path'],q['sha256']))
    prepared=profile.prepare(raw,request_sha256=q['sha256'],request_root=tmp_path,mode='exact',materialized=cfg)
    program=prepared.program
    bound=bind_semantic_query(program,{'program_id':program.program_id,
        'hard_constraints_sha256':hard_constraints_sha256(program),'hard_constraints_preserved':True,
        'candidate_sets':[{'hole_id':'business_id','candidate_ids':['constraint:1'],'authoritative':True}]},
        binding_values=cfg[2].bindings,operator_sources=cfg[0]['operator_sources'])
    parent=cfg[0]['offline']['parent_profile'];original=json.loads(read_pinned(parent['path'],parent['sha256']))
    case=json.loads(FIXTURE.read_text())['cases'][0]
    expected,_=lower_compact_query(case['gold_compact'],original['source_schema'],version='v2')
    assert [o.to_dict() for o in bound.program.operators]==[o.to_dict() for o in expected.operators]
    assert bound.program.roots==expected.roots and not bound.program.holes
    assert cfg[0]['acquisitions']=={} and not prepared.model_providers
    assert 'expected_rows' not in raw and 'gold_compact' not in raw
    result=run_record(profile_path=p['path'],profile_sha256=p['sha256'],request_path=q['path'],
        request_sha256=q['sha256'],mode='exact',output=tmp_path/'preflight')
    assert result['success'],result
    assert result['model_network_calls']==result['source_network_calls']==result['final_plan_executions']==0
