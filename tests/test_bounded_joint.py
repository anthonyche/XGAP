"""New bounded NL/authority/cost boundary on independent tiny RDF answers."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace

import pytest

from test_compact_lowering import financial_intents, pred, EXPECTED
from test_intent_execution import runtime
from test_intent_strong import clustered_family, private_user, QUESTION
from xgap.api import answer
from xgap.agent.intent_certificate import IntentSlot, TerminalContract
from xgap.agent.intent_strong import FamilyInformationPolicy, run_strong_intent
from xgap.agent.scope_authority import QueryIntentAuthority, private_query_intent
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.planning.joint_cost import JointCostProfile
from xgap.semantic.intent_scope import ScopeDomain, ScopePolicy, construct_scope
from xgap.semantic.interpretation import InterpretationRequest, InterpretationResponse
from xgap.semantic.interpretation_candidates import SCHEMA
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.experiments.bounded_joint_toy import load_inputs


@pytest.fixture
def inputs():
    data, graphs=load_inputs()
    return data['schema'],data['catalog'],data['bindings'],data['mapping'],graphs


def base_query():
    q=financial_intents()[1]
    q['nodes'][0]['entity']=None
    q['where'].append(pred('start','id','eq','1'))
    return q


def scope():
    return ScopePolicy('finite-path-and-window-v1', (
        ScopeDomain(IntentSlot('hops', ('path','max_hops'), weight=2), (1,3)),
        ScopeDomain(IntentSlot('lower', ('path','time','lower_inclusive')), (False,True)),
        ScopeDomain(IntentSlot('upper', ('path','time','upper_inclusive')), (False,True))))


class ControlledCompactProvider:
    provider_id='recorded-compact-test-proposal'
    def __init__(self, query):self.query=query;self.calls=0
    def interpret(self, request):
        self.calls+=1
        assert 'nonce' not in json.dumps(request.to_dict())
        p, assignments=lower_compact_query(self.query, request.context['source_schema'])
        return InterpretationResponse({'schema_version':SCHEMA,'candidates':[
            dict(candidate_id='proposal',quality_proxy=None,program=p.to_dict(),operator_sources=assignments)]},
            provenance={'usage_reported':True,'raw_compact_response':{'candidates':[dict(candidate_id='proposal',query=self.query)]}},
            external_calls=0, input_tokens=0, output_tokens=0)


def user(tmp_path, query):
    path=tmp_path/'private.json';path.write_text(json.dumps(private_query_intent(QUESTION,query)))
    return QueryIntentAuthority(path,hashlib.sha256(path.read_bytes()).hexdigest())


def test_candidate_construction_bounds_and_no_authority_from_proposal():
    draft=construct_scope([base_query()],scope(),'tiny')
    assert len(draft.candidates)==8 and draft.coverage_basis is None
    assert not TerminalContract(draft, mode='performance', epsilon='1').check(0)['eligible']
    with pytest.raises(ValueError,match='before'):
        replace(scope(),max_candidates=4)
    with pytest.raises(ValueError,match='before'):
        construct_scope([base_query()]*8, replace(scope(),max_candidates=32), 'tiny')


def test_public_scope_reaches_proposal_without_private_authority(tmp_path):
    from xgap.experiments.bounded_joint_toy import local_runtime
    data, options, calls = local_runtime()
    query = data['query_template']; schema = options.pop('source_schema')
    provider = ControlledCompactProvider(query)
    observed = []
    original = provider.interpret
    provider.interpret = lambda request: (observed.append(request.to_dict()) or original(request))
    request = InterpretationRequest(QUESTION, {'source_schema': schema})
    result = answer(request, provider, mode='exact', scope_policy=scope(), authority=user(tmp_path, query),
                    limits=StrongSearchLimits(planning_ms=10000), **options)
    assert result['success'] and calls and len(observed) == 1
    public = observed[0]['context']['public_scope_construction']
    assert public['policy'] == json.loads(json.dumps(scope().to_dict()))
    assert set(public) == {'policy', 'instruction'}
    assert 'private' not in json.dumps(observed[0]) and 'nonce' not in json.dumps(observed[0])
    assert set(request.context) == {'source_schema'}


def test_unified_provider_failure_keeps_diagnostics_without_execution(tmp_path):
    from xgap.api import answer_unified
    from xgap.experiments.bounded_joint_toy import local_runtime
    from xgap.semantic.interpretation import InterpretationFailure
    data, options, calls = local_runtime()
    schema = options.pop('source_schema')
    attempts = []
    message = 'External endpoint returned HTTP 401: {"error":"Unauthorized"}'
    class RejectedProvider:
        provider_id = 'controlled-authentication-failure'
        def interpret(self, request):
            attempts.append(request)
            raise InterpretationFailure('provider_error', message,
                usage={'external_calls': 1}, provenance={'usage_reported': False})
    result = answer_unified(InterpretationRequest(QUESTION, {'source_schema': schema}),
        RejectedProvider(), scope_policy=scope(), authority=user(tmp_path, data['query_template']), **options)
    assert result['status'] == 'proposal_failed' and not result['success']
    assert result['error'] == message and result['proposal_failure_category'] == 'provider_error'
    assert result['input_tokens'] is None and result['output_tokens'] is None
    assert len(attempts) == result['model_calls'] == 1
    assert result['total_user_calls'] == result['final_plan_executions'] == result['automatic_retries'] == 0
    assert calls == []


def test_scope_confirmation_does_not_reveal_truth_or_repair_bad_structure(tmp_path):
    q=base_query();auth=user(tmp_path,q);draft=construct_scope([q],scope(),'tiny')
    reply=auth.confirm_scope(QUESTION,draft)
    assert set(reply.value)=={'question_sha256','proposed_scope_sha256','covered'} and reply.value['covered']
    family,oracle=auth.bind(QUESTION,draft,reply)
    assert family.coverage_basis and oracle.preflight(QUESTION)['ready']
    wrong=deepcopy(q);wrong['where'][0]['right']['value']=False
    bad=construct_scope([wrong],scope(),'tiny')
    rejection=auth.confirm_scope(QUESTION,bad)
    assert not rejection.value['covered']
    with pytest.raises(ValueError,match='Positive'):auth.bind(QUESTION,bad,rejection)
    with pytest.raises(ValueError,match='Positive'):auth.bind('different question',draft,reply)


@pytest.mark.parametrize('mode,epsilon',[('exact','0'),('performance','0'),('performance','1/2')])
def test_nl_proposal_scope_query_joint_policy_and_real_rdf_execution(inputs,tmp_path,mode,epsilon):
    options,calls=runtime(inputs);q=base_query();oracle=user(tmp_path,q);provider=ControlledCompactProvider(q)
    schema=options.pop('source_schema');profile=options.pop('physical_profile');observations=[]
    result=answer(InterpretationRequest(QUESTION,{'source_schema':schema}),provider,mode=mode,
        scope_policy=scope(),authority=oracle,physical_profile=profile,epsilon=epsilon,
        limits=StrongSearchLimits(planning_ms=10000,improvement_actions=16),
        on_user_observation=observations.append,**options)
    assert result['success'], result
    assert result['scope_confirmed'] and result['candidate_count']==8 and provider.calls==1
    assert result['scope_confirmation_calls']==1 and result['total_user_calls']==len(observations)
    assert result['final_plan_executions']==1 and result['strong_plan'] and calls
    if epsilon=='0':assert result['answer_rows']==EXPECTED[1]
    assert result['estimated_policy_cost_including_common_actions']>0
    assert result['joint_policy']['search']['external_calls_during_search']==0


def test_wrong_scope_and_no_scope_budget_do_not_reach_backends(inputs,tmp_path):
    options,calls=runtime(inputs);q=base_query();truth=deepcopy(q);truth['where'][0]['right']['value']=False
    oracle=user(tmp_path,truth);provider=ControlledCompactProvider(q)
    schema=options.pop('source_schema');profile=options.pop('physical_profile')
    result=answer(InterpretationRequest(QUESTION,{'source_schema':schema}),provider,mode='exact',
        scope_policy=scope(),authority=oracle,physical_profile=profile,**options)
    assert result['status']=='intent_outside_proposed_scope' and not calls and result['total_user_calls']==1
    result=answer(InterpretationRequest(QUESTION,{'source_schema':schema}),provider,mode='exact',
        scope_policy=scope(),authority=oracle,physical_profile=profile,information=FamilyInformationPolicy(max_calls=0),**options)
    assert result['status']=='scope_confirmation_budget_exhausted' and provider.calls==1 and not calls


def test_single_complete_candidate_requires_scope_but_no_further_clarification(inputs,tmp_path):
    options,calls=runtime(inputs);q=base_query();schema=options.pop('source_schema');profile=options.pop('physical_profile')
    result=answer(InterpretationRequest(QUESTION,{'source_schema':schema}),ControlledCompactProvider(q),
        mode='exact',scope_policy=ScopePolicy('complete-supported-query',()),authority=user(tmp_path,q),
        physical_profile=profile,**options)
    assert result['success'],result
    assert result['total_user_calls']==1 and result['clarification_calls']==0 and result['answer_rows']==EXPECTED[1]


def test_joint_objective_changes_selection_when_execution_dominates(tmp_path):
    family=clustered_family();oracle=private_user(tmp_path,family)
    executed=[]
    def prepare(candidate,cert):
        return SimpleNamespace(nodes=(),metadata={'joint_execution_cost':100 if candidate.candidate_id=='central' else 1},
                               candidate_id=candidate.candidate_id)
    def run(epsilon,cost):
        return run_strong_intent(QUESTION,TerminalContract(family,mode='performance',epsilon=epsilon),oracle,
            prepare=prepare,execute=lambda p:(executed.append(p.candidate_id) or dict(success=True,answer_rows=[])),
            joint_cost=cost,limits=StrongSearchLimits(improvement_actions=16))
    # Both candidates are certified at 1/2; execution estimate selects a cheap one without asking.
    result=run('1/2',JointCostProfile())
    assert result['success'] and result['clarification_calls']==0 and executed==['hops']
    assert result['search']['selected_estimated_cost']==1
    assert result['physical_prepare_attempts']<=len(family.candidates)
    # At 1/4 only central is initially eligible. No look-ahead may treat every
    # possible clarification as cheap: central remains a possible expensive truth.
    result=run('1/4',JointCostProfile(clarification_call=200))
    assert result['success'] and result['clarification_calls']==0 and executed[-1]=='central'


def test_paying_for_information_can_reduce_joint_worst_case_execution(tmp_path):
    from xgap.agent.intent_certificate import IntentCandidate, IntentFamily
    q=base_query()
    slots=(IntentSlot('lower',('path','time','lower_inclusive')),
           IntentSlot('upper',('path','time','upper_inclusive')))
    candidates=[IntentCandidate.create('center',q)]
    for name in ('lower','upper'):
        variant=deepcopy(q);variant['path']['time'][name+'_inclusive']=False
        candidates.append(IntentCandidate.create(name,variant))
    family=IntentFamily('joint-information-test',tuple(candidates),slots,'tiny','independent finite test authority')
    oracle=private_user(tmp_path,family,truth='lower');executed=[]
    result=run_strong_intent(QUESTION,TerminalContract(family,mode='performance',epsilon='1/2'),oracle,
        prepare=lambda c,cert:SimpleNamespace(nodes=(),candidate_id=c.candidate_id,
            metadata={'joint_execution_cost':100 if c.candidate_id=='center' else 1}),
        execute=lambda p:(executed.append(p.candidate_id) or dict(success=True,answer_rows=[])),
        joint_cost=JointCostProfile(),limits=StrongSearchLimits(improvement_actions=16))
    assert result['success'] and result['strong_plan']
    assert result['clarification_calls']==1 and len(result['search']['policy']['children'])==2
    assert result['search']['selected_estimated_cost']==2.25
    assert len(executed)==1 and executed[0]!='center'
    assert result['terminal_certificate']['eligible']


def test_scope_policy_json_roundtrip_and_optional_estimator_failure():
    assert ScopePolicy.from_dict(json.loads(json.dumps(scope().to_dict())))==scope()
    class Unavailable:
        def predict(self,plan):raise ValueError('incompatible deployment')
    value,evidence=JointCostProfile().execution(SimpleNamespace(nodes=()),Unavailable())
    assert value==0 and evidence['basis']=='structural_fallback'
    assert evidence['unavailable_prediction']['reason']=='incompatible deployment'


def test_current_entry_through_real_compact_provider_with_injected_transport(inputs,tmp_path,monkeypatch):
    from test_compact_provider import ResponseTransport, pool
    from xgap.experiments.compact_profile import load_compact_graph_provider
    monkeypatch.setenv('XGAP_EXTERNAL_LLM_API_KEY','fixture-only-not-sent')
    options,calls=runtime(inputs);schema=options.pop('source_schema');physical=options.pop('physical_profile')
    provider=load_compact_graph_provider(mode='performance')
    transport=ResponseTransport(pool(base_query()));provider.transport=transport
    result=answer(InterpretationRequest(QUESTION,{'source_schema':schema}),provider,mode='exact',
        scope_policy=scope(),authority=user(tmp_path,base_query()),physical_profile=physical,**options)
    assert result['success'],result
    assert result['answer_rows']==EXPECTED[1] and result['final_plan_executions']==1
    assert result['model_calls']==1 and result['input_tokens']==10 and result['output_tokens']==20
    assert len(transport.calls)==1
    assert 'nonce' not in json.dumps(transport.calls) and 'private-query-intent' not in json.dumps(transport.calls)


def test_correlated_topk_proposals_keep_support_without_cartesian_invention(inputs,tmp_path,monkeypatch):
    from test_compact_provider import ResponseTransport, pool
    from xgap.experiments.compact_profile import load_compact_graph_provider
    monkeypatch.setenv('XGAP_EXTERNAL_LLM_API_KEY','fixture-only-not-sent')
    proposals=[base_query()]
    for key in ('lower_inclusive','upper_inclusive'):
        q=deepcopy(proposals[0]);q['path']['time'][key]=False;proposals.append(q)
    policy=ScopePolicy('finite-topk-conventions',scope().domains[1:],expansion='proposals_only')
    draft=construct_scope(proposals,policy,'tiny')
    assert len(draft.candidates)==3 and draft.coverage_basis is None
    assert ScopePolicy.from_dict(json.loads(json.dumps(policy.to_dict())))==policy
    options,calls=runtime(inputs);schema=options.pop('source_schema');physical=replace(options.pop('physical_profile'),candidate_cap=3)
    provider=load_compact_graph_provider(mode='precision');provider.transport=ResponseTransport(pool(*proposals))
    result=answer(InterpretationRequest(QUESTION,{'source_schema':schema}),provider,mode='performance',epsilon='1/2',
        scope_policy=policy,authority=user(tmp_path,proposals[1]),physical_profile=physical,**options)
    assert result['success'],result
    assert result['candidate_count']==3 and result['scope_confirmation_calls']==1
    assert result['clarification_calls']==0 and result['final_plan_executions']==1
    assert result['terminal_certificate']['upper_bound']=={'numerator':1,'denominator':2}
    bad=deepcopy(proposals[0]);bad['path']['time']['lower_inclusive']='not-boolean'
    with pytest.raises(ValueError):construct_scope([bad],policy,'tiny')
