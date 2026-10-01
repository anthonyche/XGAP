"""Prefix isolation and conservative cost attribution, no risk metric invented."""
from copy import deepcopy

import pytest

from test_simulated_user import oracle_file, invoke, QUESTION
from test_compact_lowering import financial_intents
from xgap.agent.simulated_user import PROFILE, identity
from xgap.experiments.terminal_opportunity import replay_user_prefixes


def trace(tmp_path):
    q=financial_intents()[0];tool=oracle_file(tmp_path,q,{'person':'hidden-entity'})
    ledger=[]
    for scope,query_hash in [('query_intent',None),('entity:person',identity(q))]:
        response=invoke(tool,scope,query_hash=query_hash)
        ledger.append({'request':{'scope':scope},'response':response.to_dict()})
    return {'profile_id':PROFILE,'success':True,'user_intent_verified':True,'mode':'exact',
        'final_plan_executions':1,'clarification_calls':2,'clarification_ledger':ledger,
        'interpretation':{'candidates':[{'status':'admitted','candidate_id':'model'}]},
        'model_calls':1,'planning_ms':100,'execution_ms':1000}


def test_prefix_replay_never_gives_future_outcome_to_terminal_checker(tmp_path):
    core=trace(tmp_path);states=[]
    def observe(state,epsilon):
        states.append(deepcopy(state))
        state['entity_bindings']['poison']='do not mutate replay'
        return {'eligible':None,'reason':'test observer is not a certificate'}
    result=replay_user_prefixes(core,question=QUESTION,epsilon=.1,certificate=observe)
    assert [s['query'] is None for s in states]==[True,False,False]
    assert [s['entity_bindings'] for s in states]==[{}, {}, {'person':'hidden-entity'}]
    assert [len(s['observations']) for s in states]==[0,1,2]
    assert [s['exact_intent_complete'] for s in states]==[False,False,True]
    assert result['earliest_certified_prefix'] is None
    assert 'poison' not in str(result)


def test_unknown_eligibility_and_final_work_are_not_invented_savings(tmp_path):
    core=trace(tmp_path);result=replay_user_prefixes(core,question=QUESTION)
    assert result['eligibility_unknown_count']==3 and result['root_gap'] is None
    ceilings=[p['optimistic_remaining_acquisition_ceiling'] for p in result['prefixes']]
    assert [c['clarification_calls'] for c in ceilings]==[2,1,0]
    assert all(c['model_calls']==c['tokens']==c['remote_acquisition_calls']==0 for c in ceilings)
    assert all(c['avoidable_planning_ms'] is None and c['avoidable_execution_ms'] is None for c in ceilings)
    assert result['initial_model_calls_already_paid']==1
    assert result['final_execution_ms_not_automatically_avoidable']==1000


def test_incomplete_or_mismatched_trace_is_not_a_certified_prefix(tmp_path):
    core=trace(tmp_path)
    core['clarification_ledger'][1]['response']['value']['query_sha256']='stale'
    with pytest.raises(ValueError,match='Stale'):replay_user_prefixes(core,question=QUESTION)
    core['mode']='performance'
    with pytest.raises(ValueError,match='Exact'):replay_user_prefixes(core,question=QUESTION)
