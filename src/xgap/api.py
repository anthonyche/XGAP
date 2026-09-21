"""Unified fixed-depth entry, with the historical strong-policy API preserved."""
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


def answer(request, provider, *, mode=None, scope_policy, authority, physical_profile,
           sources, backends, backend_clients, epsilon='0', estimator=None,
           information=FamilyInformationPolicy(), limits=StrongSearchLimits(),
           costs=JointCostProfile(), on_user_observation=None,execution_cost_feedback=True,
           unified=None):
    """One attempt, bounded declared semantics, no hidden repair or plan trials."""
    started = time.perf_counter()
    report = dict(schema_version='xgap-bounded-joint-answer-v1', profile_id='bounded-joint-v1',
        success=False, status='preparing', mode=mode, final_plan_executions=0,
        model_calls=0, input_tokens=0, output_tokens=0, scope_confirmation_calls=0,
        clarification_calls=0, total_user_calls=0, probe_calls=0, fit_calls=0,
        automatic_retries=0, answer_rows=None, scope_confirmed=False,
        cost_profile=costs.to_dict(), input_scope='NL and frozen finite slot domains; private queried authority')
    try:
        if unified is not None:
            from xgap.agent.unified_family import UnifiedSettings, run_unified_family
            if (not isinstance(unified, UnifiedSettings) or mode is not None or epsilon != '0'
                    or execution_cost_feedback is not True or limits != StrongSearchLimits()):
                raise ValueError('Unified settings replace mode/epsilon/strong-search controls; do not mix profiles')
            report.update(schema_version='xgap-unified-nl-v1', profile_id='unified-lookahead-v1',
                          mode=None, terminal_settings=dict(epsilon=unified.epsilon, relaxable=list(unified.relaxable)))
        elif mode not in ('exact', 'performance'):
            raise ValueError('Explicit mode and compact-profile hard constraints required')
        if request.required_constraints:
            raise ValueError('This bounded entry requires hard constraints in the compact profile')
        if information.max_calls < 1:
            report['status'] = 'scope_confirmation_budget_exhausted'
            return report
        schema = request.context['source_schema']
        if not isinstance(schema, dict):
            raise ValueError('Frozen source schema required')
        # Public alternatives, never the authority's selected value or query.
        # The compact wire requires complete proposals; an unknown predicate
        # must be represented by one point in its domain rather than omitted.
        proposal_request = replace(request, context={**request.context,
            'public_scope_construction': {
                'policy': scope_policy.to_dict(),
                'instruction': (
                    'These are public alternative domains, not confirmed user values. '
                    'Produce a complete representative query containing every declared coordinate. '
                    'Use any one listed value for each unknown coordinate; the host expands all legal '
                    'alternatives and queries the user for authority. Do not omit an unknown predicate, '
                    'including a required boolean condition whose true/false value is unspecified. '
                    'Infer variable roles from the original question, never from array positions. '
                    'If the question requires each distinct edge to contribute once, name the '
                    'contributing edge variable in contribution_by. Do not invent other constraints.')
            }})
        report['interpretation'] = interpreted = interpret_candidate_question(proposal_request, provider,
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
        report['intent_family']=family.to_dict()
        report['scope_confirmed'] = True
        prepare, execute, capabilities, capability_ms = family_runtime(family, source_schema=schema,
            sources=sources, backends=backends, backend_clients=backend_clients,
            physical_profile=physical_profile, joint_cost=costs, estimator=estimator,
            planning_deadline=time.perf_counter()+limits.planning_ms/1000, seed_only=unified is not None, stepwise=unified is not None and unified.physical_moves)
        report.update(capability_lookup=capabilities, capability_lookup_ms=capability_ms)
        # Same support, information permissions and joint objective for both modes.
        if unified is None:
            core = run_strong_intent(request.question, TerminalContract(family, mode=mode, epsilon=epsilon), user,
                prepare=prepare, execute=execute, joint_cost=costs,
                information=replace(information, max_calls=information.max_calls-1), limits=limits,
                on_observation=on_user_observation,execution_cost_feedback=execution_cost_feedback,include_policy=True)
        else:
            ceiling = unified.limits.resources.user_calls
            online_calls = information.max_calls-1
            online_calls = online_calls if ceiling is None else min(ceiling, online_calls)
            settings = replace(unified, limits=replace(unified.limits,
                resources=replace(unified.limits.resources, user_calls=online_calls)))
            from xgap.runtime.unified_physical import PhysicalMoves
            for target in settings.information_targets:
                source=sources.get(target.source_id)
                if (source is None or source.snapshot_version!=target.version or target.backend not in source.replica_backend_ids
                        or target.backend not in backend_clients):
                    raise ValueError('Registered information target differs from the frozen source snapshot')
            core = run_unified_family(request.question, family, user, prepare_seed=prepare, execute=execute,
                costs=costs, settings=settings, on_observation=on_user_observation, estimator=estimator,
                moves=PhysicalMoves(family,schema,backends,physical_profile,sources) if settings.physical_moves else None,
                backend_clients=backend_clients,sources=sources,information=information)
        report['joint_policy'] = core
        for key in ('success', 'status', 'answer_rows', 'final_plan_executions', 'clarification_calls',
                    'disclosed_coordinates', 'backend_remote_calls', 'planning_cpu_ms', 'planning_ms',
                    'execution_ms', 'certificate_ms', 'strong_plan', 'terminal_certificate',
                    'user_intent_verified', 'root_gap', 'physical_prepare_attempts', 'probe_calls', 'metadata_calls', 'physical_actions'):
            report[key] = core.get(key)
        report['total_user_calls'] = 1 + core['clarification_calls']
        usage = (report['model_calls'], report['input_tokens'], report['output_tokens'])
        common = None if any(v is None for v in usage) else (
            costs.clarification_call + costs.model_call*usage[0] + costs.model_token*(usage[1]+usage[2]))
        remaining = (core['search']['selected_estimated_cost'] if unified is None else
                     core['rounds'][0]['estimated_cost'] if core['rounds'] else None)
        estimate_key = ('estimated_policy_cost_including_common_actions' if unified is None else
                        'initial_decision_estimate_including_common_actions')
        report[estimate_key] = (
            common+remaining if common is not None and remaining is not None else None)
        if unified is not None:
            online=core.get('realized_acquisition_cost_estimate')
            terminal=core.get('selected_execution_cost_estimate',0 if core['final_plan_executions']==0 else None)
            report['realized_trace_work_estimate']=(common+online+terminal
                if all(v is not None for v in (common,online,terminal)) else None)
        report['cost_scope'] = ('common proposal/scope costs plus initial worst-outcome clarification and execution estimates; '
                                'actual planner CPU/LLM tokens/source bytes remain separately measured')
        if unified is not None:
            report['cost_scope']=('declared work units: realized paid proposal/scope/actions plus selected execution estimate; '
                'initial lookahead uses the configured backup; not measured money or an execution-time guarantee')
    except Exception as error:
        report.update(status='bounded_joint_failed', error_type=type(error).__name__, error=str(error))
    finally:
        report['end_to_end_ms'] = (time.perf_counter()-started)*1000
    return report


def answer_unified(request, provider, *, settings=None, **options):
    """Unified fixed-depth decisions over protected seeds, local rewrites and pinned tools."""
    from xgap.agent.unified_family import UnifiedSettings
    return answer(request, provider, unified=settings or UnifiedSettings(), **options)


def answer_controlled(question, family, user, *, initial_observations=(), mode, physical_profile,
                      sources, backends, backend_clients, source_schema, epsilon='0', estimator=None,
                      information=FamilyInformationPolicy(),limits=StrongSearchLimits(),costs=JointCostProfile(),
                      execution_cost_feedback=True,on_user_observation=None):
    """Frozen common-state experiment, explicitly excluding NL and scope acquisition.

    The publisher owns the initial evidence; this entry never opens hidden intent
    to obtain clues. Full family coordinates and weights survive state restriction.
    """
    started=time.perf_counter()
    if not family.coverage_basis:raise ValueError('Controlled state requires frozen authoritative scope evidence')
    if getattr(user,'family',None)!=family:raise ValueError('Controlled user and public family differ')
    family.consistent(initial_observations)
    prepare,execute,capabilities,capability_ms=family_runtime(family,source_schema=source_schema,
        sources=sources,backends=backends,backend_clients=backend_clients,physical_profile=physical_profile,
        joint_cost=costs,estimator=estimator,planning_deadline=time.perf_counter()+limits.planning_ms/1000)
    core=run_strong_intent(question,TerminalContract(family,mode=mode,epsilon=epsilon),user,
        prepare=prepare,execute=execute,information=information,limits=limits,joint_cost=costs,
        initial_observations=initial_observations,execution_cost_feedback=execution_cost_feedback,
        on_observation=on_user_observation,include_policy=True)
    return {**core,'schema_version':'xgap-bounded-joint-controlled-answer-v1',
        'track':'controlled_initial_state','controlled_processing_ms':(time.perf_counter()-started)*1000,
        'intent_family':family.to_dict(),'capability_lookup':capabilities,'capability_lookup_ms':capability_ms,
        'scope_confirmation_calls':0,'scope_confirmed':True,'total_user_calls':core['clarification_calls'],
        'model_calls':0,'input_tokens':0,'output_tokens':0,
        'timing_scope':'frozen state to materialized result; excludes NL and initial authority publication'}


def answer_unified_controlled(question,family,user,*,initial_clues=None,settings=None,physical_profile,
        sources,backends,backend_clients,source_schema,estimator=None,information=FamilyInformationPolicy(),
        costs=JointCostProfile(),on_user_observation=None):
    """Publisher-attested initial state; no model call or online hidden-gold access."""
    from xgap.agent.unified_family import UnifiedSettings,run_unified_family
    from xgap.runtime.unified_physical import PhysicalMoves
    started=time.perf_counter()
    settings=settings or UnifiedSettings()
    if not family.coverage_basis or getattr(user,'family',None)!=family:
        raise ValueError('Controlled entry requires a confirmed family and matching private tool')
    for target in settings.information_targets:
        source=sources.get(target.source_id)
        if (source is None or source.snapshot_version!=target.version or target.backend not in source.replica_backend_ids
                or target.backend not in backend_clients):raise ValueError('Information target snapshot differs')
    prepare,execute,capabilities,capability_ms=family_runtime(family,source_schema=source_schema,
        sources=sources,backends=backends,backend_clients=backend_clients,physical_profile=physical_profile,
        joint_cost=costs,estimator=estimator,seed_only=True,stepwise=settings.physical_moves)
    ceiling=settings.limits.resources.user_calls
    settings=replace(settings,limits=replace(settings.limits,resources=replace(settings.limits.resources,
        user_calls=information.max_calls if ceiling is None else min(ceiling,information.max_calls))))
    core=run_unified_family(question,family,user,prepare_seed=prepare,execute=execute,costs=costs,settings=settings,
        estimator=estimator,moves=PhysicalMoves(family,source_schema,backends,physical_profile,sources) if settings.physical_moves else None,
        backend_clients=backend_clients,sources=sources,information=information,initial_clues=initial_clues,
        on_observation=on_user_observation)
    return {**core,'schema_version':'xgap-unified-controlled-v1','profile_id':'unified-lookahead-v1',
        'track':'controlled_unified_lookahead','intent_family':family.to_dict(),
        'scope_confirmation_calls':0,'total_user_calls':core['clarification_calls'],
        'scope_confirmed':True,'candidate_count':len(family.candidates),'input_tokens':0,'output_tokens':0,
        'capability_lookup':capabilities,'capability_lookup_ms':capability_ms,
        'controlled_processing_ms':(time.perf_counter()-started)*1000}
