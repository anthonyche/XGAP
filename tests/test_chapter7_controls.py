"""Only new experimental contracts: frozen clues, feedback, policy and loss."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path

import pytest

from xgap.api import answer_controlled
from xgap.agent.intent_certificate import TerminalContract
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.intent_strong import FamilyInformationPolicy, FamilyStrongDomain, FamilyState
from xgap.agent.scope_authority import private_query_intent, ScopedQueryUser
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.experiments.bounded_joint_toy import local_runtime, toy_scope, QUESTION
from xgap.experiments.bounded_joint_contract import configuration, load_configuration
from xgap.experiments.controlled_state import publish_state, read_state
from xgap.experiments.evidence_store import write_json_evidence
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.query_loss_score import query_loss, score_query_loss
from xgap.planning.joint_cost import JointCostProfile
from xgap.semantic.intent_scope import construct_scope


def inputs(tmp_path,clues=()):
    data,runtime,calls=local_runtime();query=data['query_template']
    family=construct_scope([query],toy_scope(),snapshot_identity(runtime['sources'],runtime['backends'],runtime['source_schema']))
    choices=[dict(name=s.name,type='path_depth' if s.name=='hops' else 'time_boundary',slots=[s.name]) for s in family.slots]
    document=publish_state(QUESTION,family,query,clue_names=clues,semantic_choices=choices)
    family,observations,metadata=read_state(document,QUESTION)
    pin=write_once(tmp_path/'private.json',private_query_intent(QUESTION,query))
    user=ScopedQueryUser(family,Path(pin['path']),pin['sha256'])
    return data,runtime,calls,document,family,observations,metadata,user,pin


def test_initial_clues_preserve_loss_denominator_and_do_not_disclose_other_truth(tmp_path):
    data,runtime,calls,doc,family,observations,meta,user,pin=inputs(tmp_path,('hops',))
    assert meta['initial_candidate_count']==4 and meta['full_family_count']==8
    assert meta['initial_ambiguity']==2 and meta['loss_denominator']==4
    assert set(doc['initial_clues'])=={'hops'} and 'nonce' not in json.dumps(doc)
    assert len(family.slots)==3
    candidate=family.consistent(observations)[0]
    cert=TerminalContract(family,mode='performance',epsilon='1/2').check(candidate,observations)
    assert cert['eligible'] and cert['upper_bound']==dict(numerator=1,denominator=2)
    # Initial authority is a public input; root terminal does not open the private file.
    Path(pin['path']).unlink()
    result=answer_controlled(QUESTION,family,user,initial_observations=observations,
        mode='performance',epsilon='1/2',limits=StrongSearchLimits(planning_ms=10000),**runtime)
    assert result['success'] and result['total_user_calls']==0 and result['model_calls']==0
    assert result['track']=='controlled_initial_state' and result['controlled_processing_ms']>0


@pytest.mark.parametrize('feedback',[True,False])
def test_feedback_ablation_keeps_physical_estimator_and_full_selected_policy(tmp_path,feedback):
    data,runtime,calls,doc,family,observations,meta,user,pin=inputs(tmp_path)
    result=answer_controlled(QUESTION,family,user,mode='exact',epsilon='0',execution_cost_feedback=feedback,
        limits=StrongSearchLimits(planning_ms=10000,improvement_actions=16),**runtime)
    assert result['success'] and result['answer_rows']==data['expected']
    assert result['final_plan_executions']==1 and result['clarification_calls']==1
    evidence=result['policy_evidence'];nodes={n['id']:n for n in evidence['nodes']}
    actions=[n for n in evidence['nodes'] if n['kind']=='AND']
    assert actions
    for action in actions:
        outgoing=[e for e in evidence['edges'] if e['source']==action['id']]
        assert len(outgoing)==action['declared_outcomes']
    leaves=[n for n in evidence['nodes'] if n['kind']=='EXECUTE']
    assert len(leaves)>1 and len(result['observed_policy_state_ids'])==2
    assert all(n['evidence_status']=='planned_until_observed' and 'execution_ms' not in n for n in leaves)
    plans=evidence['physical_plans'].values()
    assert all(p['metadata']['joint_compared_plans']>=1 and p['metadata']['alternative_executions']==0 for p in plans)
    assert all(p['metadata']['joint_execution_cost']>0 for p in plans)
    if not feedback:
        assert 'physical ranking unchanged' in result['search']['cost_objective']
        assert result['search']['selected_estimated_cost']==JointCostProfile().information((0,1,2))


def test_publication_rejects_inconsistent_intent_and_ambiguous_choice_grouping(tmp_path):
    _,_,_,doc,family,_,_,_,_=inputs(tmp_path)
    bad=deepcopy(doc);bad['semantic_choices'][0]['slots'].append('lower')
    with pytest.raises(ValueError,match='exactly one'):read_state(bad,QUESTION)
    bad=deepcopy(doc);bad['initial_clues']['hops']=900
    with pytest.raises(ValueError,match='contradicts'):read_state(bad,QUESTION)
    with pytest.raises(ValueError,match='identity'):read_state(doc,'different NL question')


def test_post_seal_loss_checks_actual_query_not_the_reported_certificate(tmp_path):
    data,runtime,_,doc,family,initial,_,user,oracle=inputs(tmp_path,('hops',))
    core=answer_controlled(QUESTION,family,user,initial_observations=initial,
        mode='performance',epsilon='1/2',limits=StrongSearchLimits(planning_ms=10000),**runtime)
    loss=query_loss(core['selected_query'],data['query_template'],family.to_dict()['slots'])
    assert loss==Fraction(1,2)
    # A dishonest smaller recorded bound must be detected independently.
    core['terminal_certificate']['upper_bound']=dict(numerator=0,denominator=1)
    request=write_once(tmp_path/'request.json',dict(question=QUESTION))
    receipt=write_once(tmp_path/'receipt.json',dict(schema_version='xgap-common-method-trial-v1',
        request_sha256=request['sha256'],oracle_sha256=oracle['sha256'],final_plan_executions=1,
        core=write_json_evidence(tmp_path/'core.json.gz',core)))
    score=score_query_loss(receipt=receipt,request=request,oracle=oracle,output=tmp_path/'loss.json')
    assert score['status']=='measured' and score['loss']==.5 and score['certificate_violation']
    changed=deepcopy(data['query_template']);changed['limit']=1
    assert query_loss(core['selected_query'],changed,family.to_dict()['slots']) is None


def test_v1_configuration_keeps_feedback_and_v2_requires_boolean(tmp_path):
    old=configuration();old.pop('execution_cost_feedback');old['schema_version']='xgap-bounded-joint-run-config-v1'
    pin=write_once(tmp_path/'v1.json',old)
    assert load_configuration(pin['path'],pin['sha256'])[0].get('execution_cost_feedback',True) is True
    new=configuration(execution_cost_feedback='off');pin=write_once(tmp_path/'bad.json',new)
    with pytest.raises(ValueError,match='boolean'):load_configuration(pin['path'],pin['sha256'])
