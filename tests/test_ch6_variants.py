"""Chapter 6 method contracts, with portable execution and no paid services."""
from dataclasses import replace
import hashlib
import json
import pytest

from test_unified_family import invocation
from test_unified_actions import fixture, target
from xgap.agent.unified_family import UnifiedSettings, FamilyDomain, FamilyState
from xgap.agent.unified_contract import UnifiedTerminalContract, ValidationRequirement
from xgap.agent.unified_lookahead import Limits, Resources, State, choose
from xgap.agent.intent_strong import FamilyInformationPolicy
from xgap.planning.joint_cost import JointCostProfile
from xgap.experiments.unified_contract import configuration, load_configuration, validate_method


def domain_for(settings, costs=JointCostProfile()):
    _,_,calls,family,prepare,_=fixture()
    requirements=tuple(ValidationRequirement(s.name,s.path,'user',family.identity) for s in family.slots)
    contract=UnifiedTerminalContract(family,requirements,epsilon=settings.epsilon,relaxable=settings.relaxable)
    seeds={i:(prepare(c,None),1,Resources(remote_calls=32,bytes=None,peak_bytes=None)) for i,c in enumerate(family.candidates)}
    return FamilyDomain('q',contract,seeds,costs,authority_name='user',authority_version=family.identity,
                        settings=settings,information=FamilyInformationPolicy(additional_scopes=((0,1),(0,2)))),calls


def test_two_stage_stops_at_common_eligibility_without_full_disclosure(tmp_path):
    r,_=invocation(tmp_path,UnifiedSettings(decision_order='two_stage',epsilon='1/3',
        relaxable=('hops','lower','upper'),physical_moves=False,limits=Limits(depth=2,optional_ms=5000)),
        information=FamilyInformationPolicy(additional_scopes=((0,1),(0,2))),
        costs=JointCostProfile(clarification_call=.1,disclosed_field=1))
    assert r['success'],r
    core=r['joint_policy']
    assert core['disclosed_coordinates']==2
    assert core['terminal_certificate']['eligible']
    assert core['rounds'][0]['objective']=='acquisition_only'
    assert core['fixed_candidate'] is not None
    assert core['final_plan_executions']==1


def test_two_stage_candidate_freeze_is_independent_of_execution_prices():
    settings=UnifiedSettings(decision_order='two_stage',epsilon='1',relaxable=('hops','lower','upper'))
    domain,calls=domain_for(settings)
    state=domain.settle(FamilyState())
    expected=min(range(len(domain.contract.family.candidates)),key=lambda i:domain.contract.family.candidates[i].candidate_id)
    assert state.fixed_candidate==expected
    domain.score=lambda state,key:100000 if domain.plans[key][0]==expected else 0
    assert {t.payload['candidate_index'] for t in domain.terminals(state)}=={expected}
    assert len(domain.contract.consistent(state.bindings))==8 and not calls
    assert all(a.kind!='binding' for a in domain.actions(state))


def test_two_stage_semantic_decision_has_no_execution_price_feedback():
    settings=UnifiedSettings(decision_order='two_stage',epsilon='1/3',relaxable=('hops','lower','upper'),
                             limits=Limits(depth=2,optional_ms=5000))
    domain,_=domain_for(settings,JointCostProfile(clarification_call=.1,disclosed_field=1))
    first=choose(State(FamilyState()),domain,limits=settings.limits)
    domain.score=lambda state,key:float((domain.plans[key][0]+1)*100000)
    second=choose(State(FamilyState()),domain,limits=settings.limits)
    assert first['status']==second['status']=='completed'
    assert first['choice'].key==second['choice'].key
    assert first['estimated_cost']==second['estimated_cost']
    assert all(a.kind=='binding' for a in domain.actions(FamilyState()))


def test_no_probe_keeps_metadata_and_estimate_model():
    probe=target();metadata=replace(probe,name='capability',kind='metadata',gates_rule='entity_bind',gate_label='large')
    domain,_=domain_for(UnifiedSettings(information_mode='no_probe',information_targets=(probe,metadata)))
    assert [a.kind for a in domain.information_actions(FamilyState())]==['metadata']
    assert set(domain.targets)=={'graph-size','capability'}


def test_myopic_scores_only_immediate_but_keeps_completion_protection(tmp_path):
    r,_=invocation(tmp_path,UnifiedSettings(action_objective='myopic',physical_moves=False,
         limits=Limits(depth=2,optional_ms=3000)))
    assert r['success'] and r['terminal_certificate']['missing_validations']==[]
    records=r['joint_policy']['rounds'][0]['records']
    assert min(x['estimated_cost'] for x in records if x['status']=='evaluated')==1.25
    failed,calls=invocation(tmp_path,UnifiedSettings(action_objective='myopic',limits=Limits(
        resources=Resources(user_calls=0,remote_calls=32,bytes=None,peak_bytes=None))))
    assert not failed['success'] and not calls and failed['final_plan_executions']==0


def test_versioned_config_legacy_loading_and_variant_identity(tmp_path):
    raw=configuration();raw['schema_version']='xgap-unified-run-config-v1'
    for k in ('information_mode','action_objective'):raw['settings'].pop(k)
    p=tmp_path/'legacy.json';p.write_text(json.dumps(raw))
    _,_,settings,_=load_configuration(p,hashlib.sha256(p.read_bytes()).hexdigest())
    assert settings.information_mode=='all' and settings.action_objective=='continuation'
    validate_method('xgap-unified-two-stage',replace(settings,decision_order='two_stage'))
    with pytest.raises(ValueError):validate_method('xgap-unified-two-stage',settings)
    with pytest.raises(ValueError):validate_method('xgap-unified-shallow',replace(settings,limits=Limits(depth=2)))
