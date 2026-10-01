"""Diagnostic coverage policy; never relabel resource cuts as correct answers."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AdmissionBudgets:
    source_timeout_seconds: int = 60
    worker_seconds: int = 120

    def __post_init__(self):
        if (type(self.source_timeout_seconds) is not int
                or type(self.worker_seconds) is not int
                or not 1 <= self.source_timeout_seconds < self.worker_seconds <= 3600):
            raise ValueError('Require 1 <= source timeout < worker timeout <= 3600 seconds')

    def to_dict(self):
        return asdict(self)


CLOSURE_KEYS = ('owned_groups_drained', 'owned_processes_terminal',
                'observer_stopped', 'serving_copy_reclamation_complete')
RESOURCE_GUARDS = {'rss_limit_observed', 'method_rss_limit_observed',
                   'source_rss_limit_observed', 'log_limit_observed',
                   'process_limit_observed'}
CONTINUABLE = {'correct', 'source_timeout', 'worker_timeout', 'resource_censored'}


def classify(row):
    """Use typed counters/status, not text matching or the empty-answer value.

    Admission budgets are harness limits. The evaluation layer must separately
    decide whether a formal method's declared deadline or the study caused a cut.
    Unknown execution errors and incorrect gold-query answers remain blockers.
    """
    guard = row.get('guard') or {}
    observed = row.get('source_observations') or {}
    categories = {k for k, v in observed.get('failure_categories', {}).items() if v}
    if categories - {'source_timeout', 'harness_call_budget', 'harness_request_budget',
                      'harness_response_budget'}:
        return 'infrastructure_or_execution_failure'
    if (observed.get('late_calls') or observed.get('persistence_failures')
            or observed.get('failed_requests', 0) and not categories):
        return 'infrastructure_or_execution_failure'
    status = guard.get('status')
    if status not in {'completed', 'deadline_exceeded'} | RESOURCE_GUARDS:
        return 'infrastructure_or_execution_failure'
    if guard.get('cleanup', {}).get('complete') is not True:
        return 'infrastructure_or_execution_failure'
    if row.get('answer_em') == 0:
        return 'answer_mismatch'
    if categories & {'harness_call_budget', 'harness_request_budget', 'harness_response_budget'}:
        return 'resource_censored'
    if status in RESOURCE_GUARDS:
        return 'resource_censored'
    if status == 'deadline_exceeded':
        return 'worker_timeout'
    if 'source_timeout' in categories:
        return 'source_timeout'
    if row.get('success') is True and row.get('answer_em') == 1 and guard.get('success') is True:
        return 'correct'
    return 'infrastructure_or_execution_failure'


def checked_segment(receipt, requested):
    """A stopped segment may advance only its audited attempted prefix."""
    rows = receipt.get('cases', [])
    count = receipt.get('attempted')
    if (type(count) is not int or not 1 <= count <= len(requested)
            or receipt.get('audited') != count or len(rows) != count
            or [r.get('case_id') for r in rows] != requested[:count]):
        raise ValueError('Unaccounted, reordered or missing attempted cases; do not advance')
    if not all(receipt.get('closure', {}).get(k) is True for k in CLOSURE_KEYS):
        raise ValueError('Unverified owned-source closure; do not continue')
    outcomes = [dict(case_id=r['case_id'], outcome=classify(r),
                     answer_em=r.get('answer_em')) for r in rows]
    # The inner runner is fail-fast: a failure before its last row is corrupt
    # evidence, not authority to skip multiple unresolved cases.
    if any(r['outcome'] != 'correct' for r in outcomes[:-1]):
        raise ValueError('Segment contains work after its first failed case')
    return outcomes
