"""New provider boundary risks; no live model calls or benchmark work."""
from dataclasses import replace
from functools import partial
import pytest

from test_one_shot_grounding import inputs
from test_practical_planning import prepared, clarification
from test_precision_evidence import model, analytic_weights
from xgap.agent.practical_execution import run_practical_semantic_query
from xgap.agent.practical_planning import BindingAction, BindingState, PracticalMode, program_identity
from xgap.agent.practical_tools import frozen_catalog_acquisition, candidate_acquisition
from xgap.tools import ToolRegistry
from xgap.tools.contracts import FunctionTool, ToolSpec, ToolResult, ToolStatus
from xgap.tools.resolution import ResolutionCandidateResponse, ResolutionProviderFailure

QUESTION = 'Find people known by the requested person, aged at least 30, in the toy graph.'
frozen_catalog_acquisition = partial(frozen_catalog_acquisition, question=QUESTION)
candidate_acquisition = partial(candidate_acquisition, question=QUESTION)


def arguments(program, action):
    return {'action_id': action.action_id, 'slot': action.slot, 'program_sha256': program_identity(program),
        'source_id': action.source_id, 'version': action.version,
        'candidates': [c for _, c in action.outcomes if c is not None]}


@pytest.mark.parametrize('mention,candidate,clarifications', [('Alice','entity:alice',0), ('Alex','entity:bob',1)])
def test_frozen_catalog_runs_only_after_search_and_ambiguity_follows_declared_fallback(model,tmp_path,mention,candidate,clarifications):
    program,kw,calls = prepared(model)
    program = replace(program, holes=tuple(replace(h, mention=mention) if h.hole_id == 'person' else h for h in program.holes))
    state = kw['initial_state']
    kw['initial_state'] = replace(state, evidence=tuple(replace(e, candidate_id=program_identity(program))
        if e.slot == '$structure' else e for e in state.evidence))
    _, _, bundle = inputs()
    action, tool = frozen_catalog_acquisition(program, 'person', ('entity:alice','entity:bob'), bundle.catalog)
    _, registry = clarification(tmp_path, program, candidate)
    registry.register(tool)
    kw['actions'] = (action, *kw['actions'])
    planned = run_practical_semantic_query(program, resolution_tools=registry, execute=False, **kw)
    assert planned['search']['strong'] and not calls
    assert set(planned['search']['policy']['children']) == {'candidate-0','candidate-1','unavailable','error'}
    result = run_practical_semantic_query(program, resolution_tools=registry, **kw)
    assert result['success'], result
    assert result['final_plan_executions'] == 1 and result['clarification_calls'] == clarifications
    assert result['answer_rows'][0]['edge'].endswith('e4' if candidate.endswith('alice') else 'e2')
    observations = [o for o in result['execution_state']['observations'] if o['kind'] == 'tool_result']
    assert observations[0]['source'] == action.tool_name
    assert result['model_calls'] == result['acquisition_remote_calls'] == 0
    assert result['capability_lookup']['live_health_verified'] is False
    assert result['capability_lookup']['semantic_authority'] is False


def test_catalog_unknown_outcome_without_authority_fallback_is_not_strong(model):
    program,kw,calls = prepared(model)
    _,_,bundle = inputs()
    action, tool = frozen_catalog_acquisition(program,'person',('entity:alice','entity:bob'),bundle.catalog)
    registry = ToolRegistry(); registry.register(tool); kw['actions'] = (action,)
    result = run_practical_semantic_query(program,resolution_tools=registry,**kw)
    assert result['status'] == 'no_feasible_plan' and not calls
    assert 'unavailable' in result['search']['action_records'][0]['outcomes']
    with pytest.raises(ValueError, match='schema existence'):
        frozen_catalog_acquisition(program,'predicate',('predicate:knows',),bundle.catalog)


class Proposal:
    def __init__(self, candidate, *, bad=False, failed=False, usage=True):
        self.candidate,self.bad,self.failed,self.usage = candidate,bad,failed,usage
        self.calls = 0
    def resolve(self, request, context):
        self.calls += 1
        if self.failed:
            raise ResolutionProviderFailure('recorded provider failure',source_id='llm:fixture',
                failure_category='transport',external_calls=1,input_tokens=11,output_tokens=3,
                metadata={'usage_reported': self.usage})
        return ResolutionCandidateResponse(request.hole_id,(self.candidate,), 'llm:fixture',
            authoritative=self.bad,external_calls=1,input_tokens=11,output_tokens=3,
            metadata={'usage_reported': self.usage})


@pytest.mark.parametrize('failure,unknown', [(False,False),(True,False),(False,True)])
def test_model_proposal_and_failure_keep_costs_and_only_one_final_execution(model,failure,unknown):
    program,kw,calls = prepared(model,person='bob',mode=PracticalMode('performance',('predicate',)))
    state = kw['initial_state']; candidate = dict(state.choices)['predicate']
    kw['initial_state'] = BindingState(tuple((s,c) for s,c in state.choices if s != 'predicate'),
                                     tuple(e for e in state.evidence if e.slot != 'predicate'))
    provider = Proposal(candidate,failed=failure,usage=not unknown)
    action, tool = candidate_acquisition(program,'predicate',(candidate,),provider,kind='llm',
        source_id='llm:fixture',version='frozen-prompt-v1',token_budget=64)
    # A total local trusted mapping provides continuation when the remote action fails.
    fallback = BindingAction('trusted-predicate','predicate','fixture.mapping',(('known',candidate),),
        'trusted-template','v1','validated_mapping',10)
    registry = ToolRegistry(); registry.register(tool)
    registry.register(FunctionTool(ToolSpec(fallback.tool_name,'Trusted fixed request predicate',{},'binding'),
        lambda args,ctx: ToolResult.success(fallback.tool_name,
            {k:args[k] for k in ('slot','program_sha256','source_id','version')} | {'candidate_id':candidate},
            metrics={'model_calls':0,'tokens':0,'remote_calls':0})))
    kw['actions'] = (action,fallback)
    planned = run_practical_semantic_query(program,resolution_tools=registry,execute=False,**kw)
    assert planned['search']['strong'] and provider.calls == 0 and not calls
    result = run_practical_semantic_query(program,resolution_tools=registry,**kw)
    assert result['success'], result
    assert provider.calls == result['model_calls'] == result['acquisition_remote_calls'] == 1
    assert result['tokens'] == (None if unknown else 14)
    assert result['actual_acquisition_usage_complete'] is (not unknown)
    assert result['final_plan_executions'] == 1
    assert result['execution']['unvalidated_bindings'] == ([] if failure else ['predicate'])
    assert result['answer_rows'][0]['edge'].endswith('e2')


@pytest.mark.parametrize('bad,candidate',[(True,'predicate:knows'),(False,'predicate:outside')])
def test_invalid_paid_model_output_cannot_gain_authority_or_escape_domain(bad,candidate):
    _,program,_ = inputs()
    provider = Proposal(candidate,bad=bad)
    action,tool = candidate_acquisition(program,'predicate',('predicate:knows',),provider,kind='llm',
        source_id='llm:fixture',version='v1')
    result = tool.invoke(arguments(program,action),None)
    assert result.status is ToolStatus.ERROR and result.metrics['model_calls'] == 1 and result.metrics['tokens'] == 14
    with pytest.raises(ValueError,match='entity identity'):
        candidate_acquisition(program,'person',('entity:alice',),provider,kind='llm',source_id='llm:fixture',version='v1')


def test_catalog_response_pin_and_invocation_scope_are_checked_before_validation():
    _,program,bundle = inputs()
    action,tool = frozen_catalog_acquisition(program,'person',('entity:alice',),bundle.catalog)
    args = arguments(program,action); args['version'] = 'wrong'
    result = tool.invoke(args,None)
    assert result.status is ToolStatus.ERROR and result.metrics['model_calls'] == 0
    class WrongPin:
        def resolve(self, request, context):
            return ResolutionCandidateResponse(request.hole_id,('entity:alice',),action.source_id,
                authoritative=True,metadata={'artifact_sha256':'wrong'})
    result = replace(tool,provider=WrongPin()).invoke(arguments(program,action),None)
    assert result.status is ToolStatus.ERROR and 'version mismatch' in result.error


@pytest.mark.parametrize('usage', [True,False])
def test_existing_openai_provider_uses_one_bounded_wire_request_and_preserves_usage(monkeypatch,usage):
    from test_m15_llm_resolution_provider import _provider, _Transport, _envelope
    from xgap.agent.practical_tools import openai_candidate_acquisition
    monkeypatch.setenv('XGAP_M15_TEST_API_KEY','test-only-placeholder')
    response = _envelope({'hole_id':'predicate','candidate_ids':['predicate:knows']})
    if not usage: response.pop('usage')
    transport = _Transport([response]); provider = _provider(transport)
    _,program,_ = inputs()
    action,tool = openai_candidate_acquisition(program,'predicate',('predicate:knows','predicate:other'),
        provider,question=QUESTION)
    assert not transport.calls
    result = tool.invoke(arguments(program,action),None)
    assert result.status is ToolStatus.SUCCESS and len(transport.calls) == 1
    schema = transport.calls[0]['payload']['response_format']['json_schema']['schema']
    assert schema['properties']['candidate_ids']['maxItems'] == 2
    assert schema['properties']['candidate_ids']['items']['enum'] == ['predicate:knows','predicate:other']
    assert result.metrics['model_calls'] == result.metrics['remote_calls'] == 1
    assert result.metrics.get('tokens') == (51 if usage else None)
    assert action.authority is None and result.metadata['authoritative'] is False


def test_changed_openai_prompt_fails_before_network(monkeypatch):
    from test_m15_llm_resolution_provider import _provider, _Transport
    from xgap.agent.practical_tools import openai_candidate_acquisition
    transport = _Transport(); provider = _provider(transport)
    _,program,_ = inputs()
    action,tool = openai_candidate_acquisition(program,'predicate',('predicate:knows',),provider,question=QUESTION)
    provider.system_prompt += ' altered'
    result = tool.invoke(arguments(program,action),None)
    assert result.status is ToolStatus.ERROR and not transport.calls
    assert result.metrics['model_calls'] == result.metrics['tokens'] == result.metrics['remote_calls'] == 0


def test_multiple_model_candidates_remain_unavailable_instead_of_silently_choosing_first(monkeypatch):
    from test_m15_llm_resolution_provider import _provider, _Transport, _envelope
    from xgap.agent.practical_tools import openai_candidate_acquisition
    monkeypatch.setenv('XGAP_M15_TEST_API_KEY','test-only-placeholder')
    candidates = ('predicate:knows','predicate:other')
    transport = _Transport([_envelope({'hole_id':'predicate','candidate_ids':list(candidates)})])
    _,program,_ = inputs()
    action,tool = openai_candidate_acquisition(program,'predicate',candidates,_provider(transport),question=QUESTION)
    result = tool.invoke(arguments(program,action),None)
    assert result.status is ToolStatus.UNAVAILABLE and result.value is None
    assert len(transport.calls) == 1 and result.metrics['tokens'] == 51


def test_incomplete_authoritative_catalog_response_is_not_validation():
    _,program,bundle = inputs()
    action,tool = frozen_catalog_acquisition(program,'person',('entity:alice',),bundle.catalog)
    class Incomplete:
        def resolve(self, request, context):
            return ResolutionCandidateResponse(request.hole_id,('entity:alice',),action.source_id,
                authoritative=True,metadata={'artifact_sha256':bundle.catalog.artifact_sha256,'scan_complete':False})
    result = replace(tool,provider=Incomplete()).invoke(arguments(program,action),None)
    assert result.status is ToolStatus.UNAVAILABLE and result.value is None
