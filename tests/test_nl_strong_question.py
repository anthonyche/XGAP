"""New NL/strong boundary only: authority, failure accounting and tiny SPARQL."""
from dataclasses import replace

import pytest

from test_one_shot_grounding import inputs
from test_one_shot_question import CandidateProvider, CASE
from test_semantic_binding_execution import setup
from xgap.agent.nl_strong_question import run_nl_strong_question
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.one_shot_grounding import ground_interpretation
from xgap.agent.practical_planning import (BindingEvidence, BindingState, ModelStructureProposal,
    PracticalSemanticDomain, program_identity)
from xgap.experiments.toy_binding import interpretation_inputs
from xgap.semantic.interpretation import InterpretationResponse
from xgap.semantic.interpretation_candidates import SCHEMA


def run(mode='exact', index=0, provider=None):
    case, program, bundle = inputs(index)
    request, template = interpretation_inputs(case)
    request = replace(request, required_constraints=())
    tool, calls = setup(case)
    class Provider:
        provider_id = 'controlled-tiny-NL-proposal'
        calls = 0
        def interpret(self, request):
            self.calls += 1
            value = template.interpret(request).payload
            if index == 0:
                # Controlled stand-in for a model that states all literals.
                # The live adapter has no access to this fixture or binding map.
                bound, _ = ground_interpretation(program, value['operator_sources'], bundle, request.question)
                value = {**value, 'program': replace(bound.program, metadata={}).to_dict(), 'operator_sources': bound.operator_sources}
            return InterpretationResponse({'schema_version': SCHEMA, 'candidates': [{
                'candidate_id': 'proposal', 'quality_proxy': .9, 'program': value['program'],
                'operator_sources': value['operator_sources']}]}, external_calls=1, input_tokens=11,
                output_tokens=17, provenance={'usage_reported': True})
    provider = provider or Provider()
    result = run_nl_strong_question(request, provider, mode=mode, policy=OneShotPolicy.for_mode('performance'),
        bundle=bundle, sources=tool.sources, backends=tool.backends, backend_clients=tool.backend_clients)
    return result, calls, provider, case


@pytest.mark.parametrize('mode', ['exact', 'performance'])
def test_nl_to_tiny_real_sparql_one_call_one_plan(mode):
    result, calls, provider, case = run(mode)
    assert result['success'], result
    assert result['answer_rows'] == case['expected_rows']
    assert provider.calls == result['model_calls'] == result['final_plan_executions'] == 1
    assert len(calls) == result['backend_remote_calls']
    assert (result['input_tokens'], result['output_tokens']) == (11, 17)
    assert result['structure_validation'] == 'model_proposed_unverified_intent'
    assert result['user_intent_verified'] is False and result['strong_plan'] is True
    assert not any(e['slot'] == '$structure' for e in result['practical']['execution']['validation_records'])
    assert result['planning_ms'] >= 0 and result['execution_ms'] >= 0
    assert result['planning_cpu_ms'] >= 0
    assert result['practical']['search']['external_calls_during_search'] == 0


def test_exact_cannot_promote_ambiguous_catalog_choice_to_authority():
    exact, calls, _, _ = run('exact', 4)
    assert exact['status'] == 'no_feasible_plan' and not calls
    assert exact['final_plan_executions'] == 0 and exact['model_calls'] == 1
    perf, calls, _, _ = run('performance', 4)
    assert perf['success'] and 'person' in perf['unvalidated_bindings'] and calls
    assert perf['semantic_discrepancy_upper_bound'] is None


def test_parse_failure_preserves_model_cost_and_never_executes():
    result, calls, provider, _ = run(provider=CandidateProvider(invalid_first=True))
    assert not result['success'] and not calls and result['final_plan_executions'] == 0
    assert result['model_calls'] == provider.calls == 1 and result['input_tokens'] == 11


def test_explicit_proposal_cannot_relax_trusted_api_or_change_placement():
    case, program, bundle = inputs(0); tool, _ = setup(case)
    kwargs = dict(operator_sources=case['operator_sources'], binding_values=bundle.bindings,
        sources=tool.sources, backends=tool.backends)
    with pytest.raises(ValueError, match='trusted validation'):
        PracticalSemanticDomain(program, **kwargs).validate_state(BindingState())
    proposal = ModelStructureProposal(program_identity(program), tuple(sorted(case['operator_sources'].items())), 'test-model')
    for changed in (replace(proposal, program_sha256='0'*64), replace(proposal, operator_sources=())):
        with pytest.raises(ValueError, match='does not identify'):
            PracticalSemanticDomain(program, structure_proposal=changed, **kwargs)
    domain = PracticalSemanticDomain(program, structure_proposal=proposal, **kwargs)
    domain.validate_state(BindingState())
    with pytest.raises(ValueError, match='cannot also claim'):
        domain.validate_state(BindingState(evidence=(BindingEvidence('$structure', program_identity(program),
            'trusted_request', 'test', 'v1'),)))
