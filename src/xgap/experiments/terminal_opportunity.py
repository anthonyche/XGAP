"""Read-only prefix opportunity audit; no oracle/model/backend calls or invented risk.

Future outcomes are used only for suffix COST accounting, never passed to a
terminal assessment. Without a supplied discrepancy certificate, early bounded
eligibility remains unknown. This is an optimistic acquisition ceiling.
"""
from copy import deepcopy
import math

from xgap.agent.simulated_user import PROFILE, identity
from xgap.semantic.compact_query import validate_query


def replay_user_prefixes(core, *, question, epsilon=None, certificate=None):
    if core.get('profile_id') != PROFILE or not core.get('success') or not core.get('user_intent_verified'):
        raise ValueError('Opportunity replay requires a complete authoritative-user Exact trace')
    if core.get('mode') != 'exact' or core.get('final_plan_executions') != 1:
        raise ValueError('Replay requires one observed Exact final execution')
    if certificate is not None and epsilon is None:
        raise ValueError('A supplied certificate requires an explicit epsilon')
    if epsilon is not None and (type(epsilon) not in (float,int) or not math.isfinite(epsilon) or epsilon < 0):
        raise ValueError('Epsilon must be finite and nonnegative or explicitly unknown')
    ledger=core['clarification_ledger']
    if len(ledger) != core['clarification_calls'] or not 1 <= len(ledger) <= 9:
        raise ValueError('Incomplete or unbounded user ledger')
    # No private fixture, reference answers or future observations in this state.
    state={'question':question,'candidates':[deepcopy(c) for c in core['interpretation'].get('candidates',[])
        if c.get('status')=='admitted'],'query':None,'query_sha256':None,'entity_bindings':{},
        'observations':[],'exact_intent_complete':False}
    prefixes=[]

    def record(index):
        assessment={'eligible':None,'reason':'discrepancy_certificate_unavailable'}
        if certificate is not None:
            assessment=certificate(deepcopy(state),epsilon)
            if not isinstance(assessment,dict) or type(assessment.get('eligible')) not in (bool,type(None)):
                raise ValueError('Certificate must explicitly report true/false/unknown eligibility')
        future=ledger[index:]
        # This ceiling does not say which actions can actually be skipped, and
        # never credits the common initial model or the necessary final plan.
        suffix={'clarification_calls':len(future),
            'oracle_processing_ms':sum(o['response']['metrics']['elapsed_ms'] for o in future),
            'model_calls':sum(o['response']['metrics']['model_calls'] for o in future),
            'tokens':sum(o['response']['metrics']['tokens'] for o in future),
            'remote_acquisition_calls':sum(o['response']['metrics']['remote_calls'] for o in future),
            'avoidable_planning_ms':None,'avoidable_execution_ms':None,'avoidable_data_bytes':None}
        prefixes.append({'prefix':index,'state':deepcopy(state),'bounded_terminal':assessment,
            'optimistic_remaining_acquisition_ceiling':suffix})

    record(0)  # the common initial model proposal has already been paid
    for i,item in enumerate(ledger):
        request=item['request'];response=item['response'];value=response['value']
        if response['status']!='success' or value['question_sha256']!=identity(question) or value['scope']!=request['scope']:
            raise ValueError('Incomplete or mismatched scoped observation')
        scope=request['scope']
        if scope=='query_intent':
            query=deepcopy(validate_query(value['answer'],version=value['language_version']))
            if identity(query)!=value['query_sha256']:raise ValueError('Wrong query identity')
            state.update(query=query,query_sha256=value['query_sha256'],entity_bindings={})
        elif scope.startswith('entity:') and state['query'] is not None:
            if value['query_sha256']!=state['query_sha256']:raise ValueError('Stale entity authority')
            required={n['var'] for n in state['query']['nodes'] if n['entity'] is not None}
            if scope[7:] not in required:raise ValueError('Unexpected entity scope')
            state['entity_bindings'][scope[7:]]=value['answer']
        else:
            raise ValueError('This replay version accepts the fixed full-intent policy only')
        state['observations'].append(deepcopy(item))
        required={n['var'] for n in state['query']['nodes'] if n['entity'] is not None}
        state['exact_intent_complete']=required==set(state['entity_bindings'])
        record(i+1)
    if not state['exact_intent_complete']:raise ValueError('Trace ends before authoritative intent is complete')
    eligible=[p['prefix'] for p in prefixes if p['bounded_terminal']['eligible'] is True]
    return {'schema_version':'xgap-terminal-opportunity-v1','epsilon':epsilon,
        'certificate_supplied':certificate is not None,
        'scope':'one observed Exact path; same initial proposal, no alternative execution, no hidden outcome for certificate',
        'prefixes':prefixes,'earliest_certified_prefix':min(eligible) if eligible else None,
        'eligibility_unknown_count':sum(p['bounded_terminal']['eligible'] is None for p in prefixes),
        'root_gap':None,'empirical_discrepancy':None,'coverage_gain':None,
        'initial_model_calls_already_paid':core['model_calls'],
        'final_planning_ms_not_automatically_avoidable':core['planning_ms'],
        'final_execution_ms_not_automatically_avoidable':core['execution_ms'],
        'note':'All-prefix classification and counterfactual timing beyond measured actions require the risk contract and more instrumentation'}
