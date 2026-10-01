import hashlib
import json
from dataclasses import replace

import pytest

from test_intent_certificate import family
from xgap.agent.intent_certificate import TerminalContract, fingerprint
from xgap.agent.intent_policy import FamilyUserTool, run_intent_policy
from xgap.tools.contracts import ToolResult


QUESTION = 'In the declared family, find account 1 reachability for the intended hop bound and time window.'


def private_oracle(tmp_path, f, truth=3):
    path = tmp_path/'private-intent.json'
    path.write_text(json.dumps(dict(schema_version='xgap-private-family-intent-v1', family_sha256=f.identity,
        question_sha256=fingerprint(QUESTION), candidate_id=f.candidates[truth].candidate_id)))
    return FamilyUserTool(f,path,hashlib.sha256(path.read_bytes()).hexdigest())


def run(tmp_path, *, mode='exact', eps='0', budget=2, truth=3, f=None, prepare_error=False, execute_error=False):
    f = f or family(); oracle = private_oracle(tmp_path,f,truth); prepared=[]; executed=[]
    def prepare(c,cert):
        assert cert['eligible']; prepared.append(c.candidate_id)
        if prepare_error: raise ValueError('missing backend capability')
        return c.candidate_id
    def execute(plan):
        executed.append(plan)
        return {'success':not execute_error, 'answer_rows':[] if execute_error else [{'intent':plan}]}
    r = run_intent_policy(QUESTION,TerminalContract(f,mode=mode,epsilon=eps),oracle,
        prepare=prepare,execute=execute,max_clarifications=budget)
    return r,prepared,executed


@pytest.mark.parametrize('truth', range(4))
def test_same_s0_early_terminal_zero_epsilon_and_budget_coverage(tmp_path,truth):
    exact,p,e = run(tmp_path,truth=truth)
    bounded,pb,eb = run(tmp_path,mode='performance',eps='1/2',truth=truth)
    zero,pz,ez = run(tmp_path,mode='performance',truth=truth)
    limited,pl,el = run(tmp_path,budget=1,truth=truth)
    covered,pc,ec = run(tmp_path,mode='performance',eps='1/2',budget=1,truth=truth)
    assert exact['success'] and bounded['success'] and covered['success'] and zero['success']
    assert exact['clarification_calls'] == zero['clarification_calls'] == 2
    assert bounded['clarification_calls'] == covered['clarification_calls'] == 1
    assert limited['status']=='clarification_budget' and not pl and not el
    assert p == e == pz == ez == [family().candidates[truth].candidate_id]
    assert len(pb)==len(eb)==len(pc)==len(ec)==1
    assert exact['family_sha256']==bounded['family_sha256']==limited['family_sha256']
    assert exact['user_intent_verified'] and not bounded['user_intent_verified']
    # Scoped answer does not reveal candidate identity or the unasked time slot.
    reply = bounded['ledger'][0]['response']['value']
    assert reply['slot']=='depth' and set(reply)=={'family_sha256','question_sha256','slot','answer'}
    assert 'candidate_id' not in reply and 'since' not in reply
    assert bounded['prefixes'][0]['checks'][0]['upper_bound']=={'numerator':1,'denominator':1}


def test_no_action_after_eligible_root_no_prepare_before_certificate(tmp_path):
    r,p,e = run(tmp_path,mode='performance',eps='1',budget=0)
    assert r['success'] and r['clarification_calls']==0 and len(p)==len(e)==1
    r,p,e = run(tmp_path,budget=0)
    assert r['status']=='clarification_budget' and not p and not e
    r,p,e = run(tmp_path,f=family(coverage=None),mode='performance',eps='1')
    assert r['status']=='unknown_coverage' and not p and not e and r['clarification_calls']==0


def test_failures_are_paid_no_execution_retry_or_authority_promotion(tmp_path):
    r,p,e = run(tmp_path,prepare_error=True)
    assert not r['success'] and len(p)==1 and not e and len(r['preparation_failures'])==1
    r,p,e = run(tmp_path,mode='performance',eps='1/2',execute_error=True)
    assert r['status']=='execution_failed' and len(p)==len(e)==r['final_plan_executions']==1
    f=family(); oracle=private_oracle(tmp_path,f)
    oracle.response_path.write_text('{}')
    r=run_intent_policy(QUESTION,TerminalContract(f),oracle,
        prepare=lambda *_:pytest.fail('must not prepare'),execute=lambda *_:pytest.fail('must not execute'))
    assert r['status']=='oracle_failed' and r['clarification_calls']==1 and len(r['ledger'])==1
    class WrongScope:
        def invoke(self,args,context):
            return ToolResult.success('user', {**args,'question_sha256':'other','answer':2})
    r=run_intent_policy(QUESTION,TerminalContract(f),WrongScope(),prepare=None,execute=None)
    assert r['status']=='failed' and 'mismatch' in r['error'] and r['final_plan_executions']==0
