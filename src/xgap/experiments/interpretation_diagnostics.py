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
