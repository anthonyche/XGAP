"""Small, post-attempt NL diagnostics, without replaying or repairing a proposal.

Compact lowering records the useful error before candidate admission sees a null
program. Preserve that stage in the ordinary receipt so a batch rejection does not
require another model call or downloading its full compressed core to diagnose.
"""

from xgap.semantic.interpretation_candidates import MAX_CANDIDATES


SCHEMA = 'xgap-interpretation-diagnostics-v1'
MAX_ERROR_CHARS = 2048


def summarize_interpretation(core):
    """Return bounded public diagnostics; no oracle, raw query or prompt values.

These observations do not modify admission, intent authority, usage or scores.
Candidate indices, rather than IDs, associate stages because duplicate IDs are a
possible rejection. Missing original stage information remains explicitly null.
"""
    report = core.get('interpretation')
    if not isinstance(report, dict):
        return None
    provenance = report.get('provenance') or {}
    lowering = provenance.get('compact_lowering') or {}
    records = lowering.get('candidates') or []
    by_index = {item.get('candidate_index'): item for item in records[:MAX_CANDIDATES]
                if isinstance(item, dict) and type(item.get('candidate_index')) is int}
    candidates = []
    admitted = report.get('candidates') or []
    for candidate in admitted[:MAX_CANDIDATES]:
        if not isinstance(candidate, dict):
            continue
        index = candidate.get('candidate_index')
        original = by_index.get(index, {})
        stage = None
        error = None
        if original.get('status') == 'invalid' and original.get('error'):
            stage, error = 'compact_lowering', original['error']
        elif candidate.get('status') == 'invalid':
            stage, error = 'structural_admission', candidate.get('error')
        message = error if isinstance(error, str) else None
        candidates.append(dict(candidate_index=index,
            candidate_id=candidate.get('candidate_id'), status=candidate.get('status'),
            failure_stage=stage, error=message[:MAX_ERROR_CHARS] if message else None,
            error_truncated=bool(message and len(message) > MAX_ERROR_CHARS)))
    confirmation = core.get('scope_confirmation') or {}
    value = confirmation.get('value') or {}
    return dict(schema_version=SCHEMA, status=report.get('status'),
        failure_category=report.get('failure_category'),
        admitted_count=report.get('admitted_count'),
        candidate_count=len(admitted), candidates=candidates,
        candidates_truncated=len(admitted) > MAX_CANDIDATES,
        scope_confirmation_status=confirmation.get('status'),
        scope_covered=value.get('covered'),
        token_usage_complete=report.get('token_usage_complete'))


def batch_cell_summary(cell_id, outcome, answer_em):
    """Expose already recorded failure stages in the ordinary batch log.

No oracle, raw query, prompt, response body or environment is copied. This is
observability only: it neither changes failure classification nor retries work.
"""
    result = dict(cell_id=cell_id, status=outcome['status'], answer_em=answer_em)
    for key in ('model_calls', 'final_plan_executions', 'probe_calls',
                'clarification_calls', 'error_type', 'proposal_failure_category',
                'failure_scope', 'guard_status', 'method_error_type'):
        if outcome.get(key) is not None:
            result[key] = outcome[key]
    if isinstance(outcome.get('error'), str):
        result['error'] = outcome['error'][:MAX_ERROR_CHARS]
    diagnostic = outcome.get('interpretation_diagnostics')
    if isinstance(diagnostic, dict):
        result['interpretation'] = {k: diagnostic.get(k) for k in (
            'admitted_count', 'scope_confirmation_status', 'scope_covered')}
        failures = []
        for item in (diagnostic.get('candidates') or [])[:MAX_CANDIDATES]:
            if isinstance(item, dict) and item.get('failure_stage'):
                failures.append({
                    'candidate_index': item.get('candidate_index'),
                    'stage': item['failure_stage'],
                    'error': str(item.get('error') or '')[:MAX_ERROR_CHARS],
                })
        if failures:
            result['interpretation']['candidate_failures'] = failures
    observations = outcome.get('observations') or {}
    source = outcome.get('source_observations') or observations.get('source') or {}
    if source:
        result['source_requests'] = source.get('requests')
        result['source_forwarded'] = source.get('forwarded_requests')
    failures = {}
    for face, observation in observations.items():
        if isinstance(observation, dict) and observation.get('failure_categories'):
            failures[face] = observation['failure_categories']
    if source.get('failure_categories'):
        failures['source'] = source['failure_categories']
    if failures:
        result['observation_failures'] = failures
    if outcome.get('harness_failures'):
        result['harness_failures'] = outcome['harness_failures']
    return result
