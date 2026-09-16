"""One NL proposal -> conditional strong planner -> one final execution.

First evaluation profile: K=1 and a common frozen frontend. No fabricated
structure authority, template oracle, clarification answer, retry, or query probe.
This measures NL effectiveness; it is not an acquisition-tradeoff experiment.
"""
from dataclasses import replace
import time

from xgap.agent.one_shot_grounding import ground_interpretation
from xgap.agent.practical_execution import run_practical_semantic_query
from xgap.agent.practical_planning import (BindingEvidence, BindingState, ModelStructureProposal,
    PracticalMode, program_identity)
from xgap.agent.strong_planning import ResourceUsage, StrongSearchLimits
from xgap.semantic.interpretation_candidates import interpret_candidate_question
from xgap.semantic.program import SemanticGraphProgram


NL_STRONG_METHODS = ('xgap-nl-strong-exact', 'xgap-nl-strong-performance')
PROFILE_ID = 'nl-conditional-strong-k1-v1'


def run_nl_strong_question(request, provider, *, mode, policy, bundle, sources, backends,
                           backend_clients, estimator=None):
    started = time.perf_counter()
    r = dict(schema_version='xgap-nl-strong-answer-v1', success=False, status='preparing', mode=mode,
        profile_id=PROFILE_ID, answer_rows=None, user_intent_verified=False, answer_quality_verified=False,
        interpretation=None, grounding=None, model_calls=0, input_tokens=0, output_tokens=0,
        final_plan_executions=0, backend_remote_calls=0, probe_calls=0, fit_calls=0, automatic_retries=0,
        interpretation_ms=0.0, grounding_ms=0.0, planning_ms=0.0, execution_ms=0.0,
        acquisition_policy_scope='common frozen frontend; no live clarification or acquisition comparison',
        semantic_discrepancy_upper_bound=None, discrepancy_status='metric_deferred')
    try:
        if mode not in ('exact', 'performance') or policy.candidate_cap != 1:
            raise ValueError('The first NL strong profile requires an explicit mode and common K=1 frontend')
        config = getattr(provider, 'config', None)
        if config is not None and config.candidate_cap != 1:
            raise ValueError('Wire candidate cap must equal the frozen K=1 profile')
        if policy.retrieval_rows_per_relation is not None:
            raise ValueError('This evaluation does not truncate result retrieval')
        request = replace(request, context={**request.context, 'one_shot_profile': policy.to_dict(),
            'runtime': {'resolution_bundle': bundle.identity, 'sources': {
                k: {'version': s.snapshot_version, 'replicas': list(s.replica_backend_ids)} for k, s in sources.items()}}})
        interpreted = interpret_candidate_question(request, provider, candidate_cap=1)
        usage_known = not interpreted.get('usage_unavailable', False)
        r.update(interpretation=interpreted, interpretation_ms=interpreted.get('elapsed_ms'),
            model_calls=interpreted['external_calls'] if interpreted.get('external_call_count_complete', True) else None,
            input_tokens=interpreted['input_tokens'] if usage_known else None,
            output_tokens=interpreted['output_tokens'] if usage_known else None,
            usage_complete=usage_known and interpreted.get('external_call_count_complete', True))
        if not interpreted['success']:
            r.update(status=interpreted['status'], error=interpreted['error'])
            return r
        candidate = next(c for c in interpreted['candidates'] if c['status'] == 'admitted')
        program = SemanticGraphProgram.from_dict(candidate['program'])
        at = time.perf_counter()
        try:
            # Retain the original holes; the prediction returned by the legacy
            # grounder is NOT substituted into an allegedly validated skeleton.
            _, trace = ground_interpretation(program, candidate['operator_sources'], bundle, request.question,
                max_holes=policy.max_holes, max_candidates_per_hole=policy.max_candidates_per_hole,
                use_ontology=policy.use_ontology, ranking_policy=policy.grounding_ranking)
            r['grounding'] = trace
        finally:
            r['grounding_ms'] = (time.perf_counter() - at) * 1000
        choices, evidence, predictions = {}, [], {}
        for row in trace['candidate_sets']:
            slot, selected = row['hole_id'], row['selected_candidate_id']
            if selected is None:
                continue
            if row['authoritative'] and len(row['candidate_ids']) == 1 and not row['truncated']:
                choices[slot] = selected
                evidence.append(BindingEvidence(slot, selected, 'frozen_catalog', row['source_id'], bundle.bundle_hash))
            else:
                predictions[slot] = selected
        proposal = ModelStructureProposal(program_identity(program), tuple(sorted(candidate['operator_sources'].items())),
            getattr(config, 'provider_id', None) or 'recorded-interpretation-provider')
        # Initial LLM costs are paid before this domain. Its continuation cannot
        # spend another model call. Exact keeps slot validation; performance may
        # use explicitly recorded predictions, without an epsilon guarantee.
        limits = StrongSearchLimits(resources=ResourceUsage(0, 0, 32))
        practical = run_practical_semantic_query(program,
            initial_state=BindingState(tuple(sorted(choices.items())), tuple(evidence)),
            structure_proposal=proposal, operator_sources=candidate['operator_sources'],
            binding_values=bundle.bindings, predictions=predictions,
            mode=PracticalMode(mode, tuple(predictions) if mode == 'performance' else (), improve_physical=mode == 'exact'),
            physical_profile=policy, sources=sources, backends=backends, backend_clients=backend_clients,
            estimator=estimator, limits=limits)
        r['practical'] = practical
        execution = practical.get('execution') or {}
        result = (execution.get('result') or {}).get('value') or {}
        r.update({key: practical.get(key) for key in ('success', 'status', 'answer_rows', 'final_plan_executions',
            'backend_remote_calls', 'strong_scope', 'structure_validation')})
        r.update(planning_ms=practical['search'].get('elapsed_ms'), execution_ms=result.get('elapsed_ms'),
            planning_cpu_ms=practical['planning_cpu_ms'],
            strong_plan=practical['search']['strong'], semantic_validation=execution.get('semantic_validation'),
            unvalidated_bindings=execution.get('unvalidated_bindings'),
            candidate_id=candidate['candidate_id'], structure_provenance=practical['structure_provenance'])
    except Exception as error:
        r.update(success=False, status='nl_strong_failed', error_type=type(error).__name__, error=str(error))
        if hasattr(error, 'trace'):
            r['grounding'] = error.trace
    finally:
        r['end_to_end_ms'] = (time.perf_counter() - started) * 1000
    return r
