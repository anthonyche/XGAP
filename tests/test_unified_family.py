"""Portable real SPARQL evaluation of the new controller's protected-seed slice."""
import hashlib
import json

import pytest

from test_compact_lowering import EXPECTED
from xgap.api import answer_unified
from xgap.agent.scope_authority import QueryIntentAuthority, private_query_intent
from xgap.agent.unified_family import UnifiedSettings, FamilyDomain, FamilyState
from xgap.agent.unified_contract import UnifiedTerminalContract, ValidationRequirement
from xgap.agent.unified_lookahead import Limits, Resources
from xgap.experiments.bounded_joint_toy import local_runtime, TemplateProposalProvider, toy_scope, QUESTION
from xgap.semantic.interpretation import InterpretationRequest
from xgap.planning.joint_cost import JointCostProfile


def invocation(tmp_path, settings=None, **overrides):
    data, options, calls = local_runtime()
    query = data['query_template']
    path = tmp_path/'private.json'
    path.write_text(json.dumps(private_query_intent(QUESTION, query)))
    user = QueryIntentAuthority(path, hashlib.sha256(path.read_bytes()).hexdigest())
    schema = options.pop('source_schema')
    report = answer_unified(InterpretationRequest(QUESTION, {'source_schema': schema}),
        TemplateProposalProvider(query), settings=settings, scope_policy=toy_scope(), authority=user,
        **{**options, **overrides})
    return report, calls


def test_nl_scope_fixed_depth_clarification_seed_compiler_and_materialized_answer(tmp_path):
    r, calls = invocation(tmp_path)
    assert r['success'], r
    assert r['profile_id'] == 'unified-lookahead-v1' and r['mode'] is None
    assert r['answer_rows'] == EXPECTED[1]
    assert r['scope_confirmation_calls'] == r['clarification_calls'] == r['final_plan_executions'] == 1
    assert r['total_user_calls'] == 2 and r['model_calls'] == 0
    assert not r['strong_plan'] and r['root_gap'] is None
    assert r['terminal_certificate']['missing_validations'] == []
    assert r['backend_remote_calls'] == len(calls) > 0
    assert r['joint_policy']['external_calls_during_search'] == 0
    assert r['joint_policy']['rounds'][0]['reserved_steps'] == 1
    assert r['physical_prepare_attempts'] == r['candidate_count']


def test_optional_search_deadline_uses_completion_without_losing_correctness(tmp_path):
    r, _ = invocation(tmp_path, UnifiedSettings(limits=Limits(optional_ms=0)))
    assert r['success'] and r['answer_rows'] == EXPECTED[1]
    assert r['joint_policy']['rounds'][0]['status'] == 'optional_deadline_or_state_limit'


def test_lambda_and_loss_change_eligibility_without_a_second_controller(tmp_path):
    settings = UnifiedSettings(epsilon='1', relaxable=('hops', 'lower', 'upper'))
    r, calls = invocation(tmp_path, settings)
    assert r['success'] and r['clarification_calls'] == 0 and calls
    assert r['scope_confirmation_calls'] == 1 and r['terminal_certificate']['eligible']
    assert r['terminal_certificate']['validated'] == []
    assert r['final_plan_executions'] == 1


def test_completion_budget_and_unknown_resource_bounds_fail_before_final_execution(tmp_path):
    for bounds in (Resources(user_calls=0, remote_calls=32, bytes=None, peak_bytes=None),
                   Resources(user_calls=8, remote_calls=32, bytes=1_000_000, peak_bytes=None)):
        r, calls = invocation(tmp_path, UnifiedSettings(limits=Limits(resources=bounds)))
        assert not r['success'] and r['status'] == 'completion_witness_unavailable'
        assert not calls and r['clarification_calls'] == r['final_plan_executions'] == 0


def test_mixed_legacy_and_new_settings_rejected_without_proposal_or_backend_calls(tmp_path):
    r, calls = invocation(tmp_path, mode='exact')
    assert not r['success'] and 'mix profiles' in r['error'] and not calls


def test_unavailable_private_authority_is_recorded_and_does_not_execute(tmp_path, monkeypatch):
    from xgap.agent.scope_authority import ScopedQueryUser
    from xgap.tools.contracts import ToolResult
    monkeypatch.setattr(ScopedQueryUser, 'invoke', lambda self, args, context:
                        ToolResult.error_result(self.spec.name, 'unavailable'))
    r, calls = invocation(tmp_path)
    assert not r['success'] and not calls and r['final_plan_executions'] == 0
    assert r['clarification_calls'] == 1 and r['joint_policy']['trace'][0]['failed']
    assert r['joint_policy']['consumed_nonterminal_resources']['user_calls'] == 1


def test_singleton_confirmation_is_not_skipped_by_family_action_generator(tmp_path):
    from test_intent_strong import clustered_family
    f = clustered_family()
    reqs = tuple(ValidationRequirement(s.name, s.path, 'user', f.identity) for s in f.slots)
    contract = UnifiedTerminalContract(f, reqs)
    domain = FamilyDomain(QUESTION, contract, {}, JointCostProfile(), authority_name='user', authority_version=f.identity)
    state = domain.updated(FamilyState(), ('hops',), {'hops': 1})
    assert len(contract.consistent(state.bindings)) == 1
    actions = tuple(domain.actions(state))
    assert actions and all(len(a.outcomes) == 1 for a in actions)
    assert all(a.arguments['slots'] != ['hops'] for a in actions)


def test_empty_lost_or_bad_seed_does_not_shrink_semantic_uncertainty():
    from test_intent_strong import clustered_family
    f = clustered_family()
    contract = UnifiedTerminalContract(f, (), epsilon='1')
    domain = FamilyDomain(QUESTION, contract, {}, JointCostProfile(), authority_name='user', authority_version=f.identity)
    assert domain.completion(FamilyState()) is None
    assert len(contract.consistent()) == len(f.candidates)


def test_small_optional_terminal_cap_cannot_destroy_existing_completion(tmp_path):
    settings=UnifiedSettings(epsilon='1',relaxable=('hops','lower','upper'),
        limits=Limits(max_terminals=1))
    r,calls=invocation(tmp_path,settings)
    assert r['success'] and r['final_plan_executions']==1 and calls
    assert r['joint_policy']['rounds'][0]['status']=='representation_limit'


def test_sequential_barrier_and_public_initial_clues_use_new_controller(tmp_path):
    from dataclasses import replace
    from test_unified_actions import fixture
    from xgap.agent.scope_authority import ScopedQueryUser
    from xgap.api import answer_unified_controlled
    data,options,calls,family,_,_=fixture()
    path=tmp_path/'private.json';path.write_text(json.dumps(private_query_intent(QUESTION,data['query_template'])))
    user=ScopedQueryUser(family,path,hashlib.sha256(path.read_bytes()).hexdigest())
    settings=UnifiedSettings(decision_order='semantic_then_physical',limits=Limits(optional_ms=3000))
    r=answer_unified_controlled(QUESTION,family,user,settings=settings,
        initial_clues={'hops':3,'lower':True,'upper':True},**options)
    assert r['success'] and r['answer_rows']==data['expected']
    assert r['model_calls']==r['clarification_calls']==0 and r['final_plan_executions']==1
    assert all(t['kind']!='binding' for t in r['trace'])
    assert r['terminal_certificate']['missing_validations']==[]
