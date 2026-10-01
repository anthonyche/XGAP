"""Shared AND/OR wiring: all outcomes, no future oracle reads, cheap full action."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace

import pytest

from test_compact_lowering import financial_intents,pred
from xgap.agent.intent_certificate import IntentCandidate,IntentFamily,IntentSlot,TerminalContract
from xgap.agent.intent_strong import FamilyInformationPolicy,run_strong_intent
from xgap.agent.intent_user import ScopedFamilyUser,private_family_intent
from xgap.agent.strong_planning import StrongSearchLimits


QUESTION='For account 1, find reachable accounts and their blocked sign-in media, using the intended path and time conventions.'


def clustered_family(snapshot='tiny-v1',hard=False):
    q=financial_intents()[1];q['nodes'][0]['entity']=None;q['where'].append(pred('start','id','eq','1'))
    slots=(IntentSlot('hops',('path','max_hops'),hard=hard),
        IntentSlot('lower_inclusive',('path','time','lower_inclusive')),
        IntentSlot('upper_inclusive',('path','time','upper_inclusive')),
        IntentSlot('path_semantics',('path','mode')))
    candidates=[IntentCandidate.create('central',q)]
    for name,path,value in [('hops',slots[0].path,1),('lower',slots[1].path,False),
            ('upper',slots[2].path,False),('walk',slots[3].path,'WALK')]:
        changed=deepcopy(q);parent=changed
        for key in path[:-1]:parent=parent[key]
        parent[path[-1]]=value;candidates.append(IntentCandidate.create(name,changed))
    return IntentFamily('clustered-path-conventions-v1',tuple(candidates),slots,snapshot,
        'authored exhaustive five-intent family; no implication of open-NL coverage')


def private_user(tmp_path,f,truth='hops'):
    path=tmp_path/'private-v2.json';path.write_text(json.dumps(private_family_intent(f,QUESTION,truth)))
    return ScopedFamilyUser(f,path,hashlib.sha256(path.read_bytes()).hexdigest())


def control(tmp_path,mode='exact',epsilon='0',calls=9,hard=False,truth='hops',information=None):
    f=clustered_family(hard=hard);user=private_user(tmp_path,f,truth);prepared=[];executed=[]
    def prepare(candidate,cert):
        assert cert['eligible'];prepared.append(candidate.candidate_id)
        return SimpleNamespace(nodes=(),candidate_id=candidate.candidate_id)
    def execute(plan):
        executed.append(plan.candidate_id)
        return dict(success=True,answer_rows=[{'selected':plan.candidate_id}])
    r=run_strong_intent(QUESTION,TerminalContract(f,mode=mode,epsilon=epsilon),user,
        prepare=prepare,execute=execute,information=information or FamilyInformationPolicy(max_calls=calls),
        limits=StrongSearchLimits(improvement_actions=16))
    return r,prepared,executed


@pytest.mark.parametrize('truth',['central','hops','lower','upper','walk'])
def test_full_intent_available_and_early_terminal_avoids_all_acquisition_subtrees(tmp_path,truth):
    exact,ep,ee=control(tmp_path,truth=truth)
    bounded,bp,be=control(tmp_path,'performance','1/4',truth=truth)
    assert exact['success'] and exact['strong_plan'] and bounded['success'] and bounded['strong_plan']
    assert exact['clarification_calls']==1 and len(exact['ledger'][0]['request']['slots'])==4
    assert len(exact['search']['policy']['children'])==5 and len(ep)==5 and ee==[truth]
    assert bounded['clarification_calls']==0 and bp==be==['central']
    assert bounded['search']['expanded_states']==1 and exact['search']['expanded_states']==6
    assert bounded['search']['external_calls_during_search']==exact['search']['external_calls_during_search']==0
    assert exact['user_intent_verified'] and not bounded['user_intent_verified']
    assert bounded['terminal_certificate']['upper_bound']=={'numerator':1,'denominator':4}
    assert any(a['status']=='cannot_improve_incumbent_lower_bound' for a in exact['search']['action_records'])


def test_zero_epsilon_and_hard_constraint_negative_controls(tmp_path):
    exact,_,_=control(tmp_path)
    zero,_,_=control(tmp_path,'performance')
    assert zero['clarification_calls']==exact['clarification_calls']==1
    assert zero['physical_prepare_attempts']==exact['physical_prepare_attempts']==5
    assert zero['answer_rows']==exact['answer_rows']
    hard,_,_=control(tmp_path,'performance','1/4',hard=True)
    assert hard['clarification_calls']==1 and hard['answer_rows']==exact['answer_rows']


def test_budget_coverage_and_no_partial_strong_plan(tmp_path):
    limited,lp,le=control(tmp_path,calls=0)
    covered,cp,ce=control(tmp_path,'performance','1/4',calls=0)
    assert not limited['success'] and not limited['strong_plan'] and not lp and not le
    assert covered['success'] and cp==ce==['central']
    f=clustered_family();user=private_user(tmp_path,f)
    r=run_strong_intent(QUESTION,TerminalContract(f),user,
        prepare=lambda c,cert:SimpleNamespace(nodes=()),execute=lambda _:pytest.fail('no complete policy'),
        limits=StrongSearchLimits(max_states=2,max_actions=1))
    assert not r['strong_plan'] and r['clarification_calls']==r['final_plan_executions']==0


def test_private_pin_nonce_and_scoped_reply_no_intent_identity_leak(tmp_path):
    f=clustered_family();user=private_user(tmp_path,f)
    a=private_family_intent(f,QUESTION,'hops');b=private_family_intent(f,QUESTION,'hops')
    assert a['nonce']!=b['nonce'] and a['candidate_id']==b['candidate_id']
    preflight=user.preflight(QUESTION)
    assert set(preflight)=={'ready','family_sha256','artifact_sha256','scope'}
    result=user.invoke(dict(family_sha256=f.identity,question_sha256=a['question_sha256'],slots=['hops']),None)
    assert result.value['answers']=={'hops':1} and result.metrics['disclosed_coordinates']==1
    assert 'candidate_id' not in result.value and 'nonce' not in result.value
    user.response_path.write_text('{}')
    with pytest.raises(ValueError,match='hash'):user.preflight(QUESTION)


def test_a_failed_counterfactual_outcome_invalidates_the_exact_policy(tmp_path):
    f=clustered_family();user=private_user(tmp_path,f)
    def prepare(candidate,cert):
        if candidate.candidate_id=='upper':raise ValueError('unsupported branch')
        return SimpleNamespace(nodes=())
    r=run_strong_intent(QUESTION,TerminalContract(f),user,prepare=prepare,
        execute=lambda _:pytest.fail('must not execute a partial AND policy'),
        limits=StrongSearchLimits(max_actions=16))
    assert not r['strong_plan'] and not r['success'] and r['clarification_calls']==0
    assert len(r['preparation_failures'])==1


def test_terminal_after_one_scoped_reply_and_cheap_full_negative_control(tmp_path):
    from itertools import product
    base=clustered_family();slots=base.slots[:2];candidates=[]
    for hops,inclusive in product((1,3),(False,True)):
        query=json.loads(base.candidates[0].query_json)
        query['path']['max_hops']=hops;query['path']['time']['lower_inclusive']=inclusive
        candidates.append(IntentCandidate.create(str(len(candidates)),query))
    family=IntentFamily('two-independent-conventions',tuple(candidates),slots,'tiny-v1','exhaustive authored family')
    user=private_user(tmp_path,family,'0')
    def run(mode,basis):
        return run_strong_intent(QUESTION,TerminalContract(family,mode=mode,epsilon='0' if mode=='exact' else '1/2'),user,
            information=FamilyInformationPolicy(cost_basis=basis),
            prepare=lambda c,cert:SimpleNamespace(nodes=()),execute=lambda _:dict(success=True,answer_rows=[]),
            limits=StrongSearchLimits(improvement_actions=16))
    exact=run('exact','disclosed_coordinates');bounded=run('performance','disclosed_coordinates')
    assert exact['success'] and bounded['success']
    assert exact['clarification_calls']==bounded['clarification_calls']==1
    assert exact['disclosed_coordinates']==2 and bounded['disclosed_coordinates']==1
    assert len(bounded['realized_prefixes'])==2 and bounded['terminal_certificate']['upper_bound']=={'numerator':1,'denominator':2}
    assert bounded['search']['selected_estimated_cost']==1 and exact['search']['selected_estimated_cost']==2
    cheap_full=run('performance','interactions')
    assert cheap_full['success'] and cheap_full['disclosed_coordinates']==2
    assert cheap_full['terminal_certificate']['upper_bound']=={'numerator':0,'denominator':1}
