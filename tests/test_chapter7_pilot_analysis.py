from analyze_chapter7_pilot import summarize


def row(question, mode, *, answered=True, sealed=True, duration=10, empty=False):
    return dict(question_id=question, family_group_id=question, track='nl',
        method=f'xgap-bounded-joint-{mode}', sealed=sealed,
        answered=answered if sealed else None, correct=answered if sealed else None,
        answer_f1=float(answered) if sealed else None,
        total_online_ms=duration, controlled_processing_ms=None,
        clarification_calls=1, backend_response_bytes=None, model_calls=1,
        planning_ms=2, execution_ms=5,
        expected_rows=(0 if empty else 1) if sealed else None,
        worker_peak_rss_bytes=100, source_peak_rss_bytes=200,
        query_loss=0 if answered and sealed else None, certificate_violation=False)


def test_failure_stays_in_quality_denominator_but_not_paired_latency():
    summaries, pairs = summarize([
        row('a', 'exact', duration=10), row('a', 'performance', duration=20),
        row('b', 'exact', answered=False, duration=1),
        row('b', 'performance', duration=100, empty=True),
    ])
    by_mode={s['method'].rsplit('-',1)[-1]:s for s in summaries}
    assert by_mode['exact']['correct_completion_percent']==50
    assert by_mode['performance']['correct_completion_percent']==100
    assert by_mode['exact']['answer_f1_mean_all_requests']==.5
    assert by_mode['performance']['mean_online_ms_common']==20
    assert by_mode['performance']['empty_reference_cases']==1
    assert by_mode['exact']['mean_response_bytes_all'] is None
    assert len(pairs)==1 and pairs[0]['question_id']=='a'


def test_unattempted_cells_do_not_become_failures_or_zero_cost():
    summaries, pairs = summarize([
        row('a', 'exact', sealed=False), row('a', 'performance'),
    ])
    exact=next(s for s in summaries if s['method'].endswith('-exact'))
    assert exact['full_denominator_available'] is False
    assert exact['correct_completion_percent'] is None
    assert exact['mean_model_calls_all'] is None
    assert exact['mean_online_ms_common'] is None
    assert pairs==[]
