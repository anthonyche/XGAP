"""Current research entry: bounded NL -> paid authority -> joint strong policy.

Historical query APIs remain available for replay, not as the default system.
The proposal provider uses the existing compact interpretation wire contract.
"""
from dataclasses import replace
import time

from xgap.agent.intent_certificate import TerminalContract
from xgap.agent.intent_execution import family_runtime, snapshot_identity
from xgap.agent.intent_strong import FamilyInformationPolicy, run_strong_intent
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.planning.joint_cost import JointCostProfile
from xgap.semantic.intent_scope import construct_scope
from xgap.semantic.interpretation_candidates import interpret_candidate_question
from xgap.tools.contracts import ToolStatus


def answer(request, provider, *, mode, scope_policy, authority, physical_profile,
           sources, backends, backend_clients, epsilon='0', estimator=None,
           information=FamilyInformationPolicy(), limits=StrongSearchLimits(),
           costs=JointCostProfile(), on_user_observation=None):
    """One attempt, bounded declared semantics, no hidden repair or plan trials."""
    started = time.perf_counter()
    report = dict(schema_version='xgap-bounded-joint-answer-v1', profile_id='bounded-joint-v1',
        success=False, status='preparing', mode=mode, final_plan_executions=0,
        model_calls=0, input_tokens=0, output_tokens=0, scope_confirmation_calls=0,
        clarification_calls=0, total_user_calls=0, probe_calls=0, fit_calls=0,
        automatic_retries=0, answer_rows=None, scope_confirmed=False,
        cost_profile=costs.to_dict(), input_scope='NL and frozen finite slot domains; private queried authority')
    try:
        if mode not in ('exact', 'performance') or request.required_constraints:
            raise ValueError('Explicit mode and compact-profile hard constraints required')
        if information.max_calls < 1:
            report['status'] = 'scope_confirmation_budget_exhausted'
            return report
        schema = request.context['source_schema']
        if not isinstance(schema, dict):
            raise ValueError('Frozen source schema required')
        report['interpretation'] = interpreted = interpret_candidate_question(request, provider,
            candidate_cap=physical_profile.candidate_cap)
        for key in ('input_tokens', 'output_tokens'):
            report[key] = interpreted[key] if interpreted['token_usage_complete'] else None
        report['model_calls'] = interpreted['external_calls'] if interpreted['external_call_count_complete'] else None
        if not interpreted['success']:
            report['status'] = 'proposal_failed'
            return report
        raw = interpreted.get('provenance', {}).get('raw_compact_response')
        if not isinstance(raw, dict) or not isinstance(raw.get('candidates'), list):
            raise ValueError('Current entry requires compact proposal provenance')
        admitted = {c['candidate_id'] for c in interpreted['candidates'] if c['status'] == 'admitted'}
        proposals = [c['query'] for c in raw['candidates'] if c.get('candidate_id') in admitted]
        draft = construct_scope(proposals, scope_policy, snapshot_identity(sources, backends, schema))
        report['candidate_count'] = len(draft.candidates)
        report['scope_policy_id'] = scope_policy.policy_id
        report['scope_confirmation_calls'] = report['total_user_calls'] = 1
        confirmed = authority.confirm_scope(request.question, draft)
        report['scope_confirmation'] = confirmed.to_dict()
        if on_user_observation is not None:
            on_user_observation(dict(category='required_for_execution', action_id='confirm_scope',
                                     response=confirmed.to_dict()))
        if confirmed.status is not ToolStatus.SUCCESS or not confirmed.value.get('covered'):
            report['status'] = 'intent_outside_proposed_scope' if confirmed.status is ToolStatus.SUCCESS else 'scope_authority_failed'
            return report
        family, user = authority.bind(request.question, draft, confirmed)
        report['scope_confirmed'] = True
        prepare, execute, capabilities, capability_ms = family_runtime(family, source_schema=schema,
            sources=sources, backends=backends, backend_clients=backend_clients,
            physical_profile=physical_profile, joint_cost=costs, estimator=estimator,
            planning_deadline=time.perf_counter()+limits.planning_ms/1000)
        report.update(capability_lookup=capabilities, capability_lookup_ms=capability_ms)
        # Same support, information permissions and joint objective for both modes.
        core = run_strong_intent(request.question, TerminalContract(family, mode=mode, epsilon=epsilon), user,
            prepare=prepare, execute=execute, joint_cost=costs,
            information=replace(information, max_calls=information.max_calls-1), limits=limits,
            on_observation=on_user_observation)
        report['joint_policy'] = core
        for key in ('success', 'status', 'answer_rows', 'final_plan_executions', 'clarification_calls',
                    'disclosed_coordinates', 'backend_remote_calls', 'planning_cpu_ms', 'planning_ms',
                    'execution_ms', 'certificate_ms', 'strong_plan', 'terminal_certificate',
                    'user_intent_verified', 'root_gap', 'physical_prepare_attempts'):
            report[key] = core.get(key)
        report['total_user_calls'] = 1 + core['clarification_calls']
        usage = (report['model_calls'], report['input_tokens'], report['output_tokens'])
        common = None if any(v is None for v in usage) else (
            costs.clarification_call + costs.model_call*usage[0] + costs.model_token*(usage[1]+usage[2]))
        remaining = core['search']['selected_estimated_cost']
        report['estimated_policy_cost_including_common_actions'] = (
            common+remaining if common is not None and remaining is not None else None)
        report['cost_scope'] = ('common proposal/scope costs plus worst-outcome clarification and execution estimates; '
                                'actual planner CPU/LLM tokens/source bytes remain separately measured')
    except Exception as error:
        report.update(status='bounded_joint_failed', error_type=type(error).__name__, error=str(error))
    finally:
        report['end_to_end_ms'] = (time.perf_counter()-started)*1000
    return report
