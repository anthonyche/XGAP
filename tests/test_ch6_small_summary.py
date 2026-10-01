import csv
import json

import pytest

from xgap.experiments.ch6_formal_protocol import METHODS
from xgap.experiments.ch6_small_summary import Reader, extract_cell, summarize, summarize_rows
from xgap.experiments.one_shot_records import write_once


def metadata(method='XGAP'):
    return dict(dataset='D1', deployment='rdf', frame='uniform', workload='W1',
        method=method, case_id='D1-test-uniform-window_edge-000-W1',
        cell_id='D1-test-uniform-window_edge-000-W1-' + method, support='supported')


def sealed(tmp_path, *, method='XGAP', censored=False, comparison_error=None):
    meta = metadata(method)
    d = tmp_path / meta['cell_id']; d.mkdir()
    outcome = write_once(d / 'outcome.json', dict(method=METHODS[method],
        question_id=meta['case_id'], success=not censored,
        status='harness_observation_failure' if censored else 'answered',
        failure_scope='study_budget_censoring_not_method_incorrectness' if censored else None,
        model_calls=3, input_tokens=12, output_tokens=8, decision_e2e_ms=123,
        end_to_end_ms=1,
        source_observations=dict(requests=9, forwarded_requests=7,
            request_body_bytes=10, request_target_bytes=2, response_body_bytes=20),
        resources=dict(sampled_peak_rss_bytes=dict(method=200, source=800),
            sampled_cpu_seconds=dict(method=1, source=3))))
    score = write_once(d / 'score.json', dict(receipt_sha256=outcome['sha256'],
        answer_em=0 if censored else 1, answer_row_multiset_f1=0 if censored else 1,
        comparison_error=comparison_error))
    write_once(d / 'terminal.json', dict(cell_id=meta['cell_id'], outcome=outcome, score=score))
    return meta, d


def test_actual_censoring_retains_cost_but_never_counts_as_wrong_answer(tmp_path):
    meta, d = sealed(tmp_path, method='TS', censored=True)
    row = extract_cell(meta, d, Reader(tmp_path))
    assert row['observation'] == 'study_censored'
    assert row['answer_em'] is row['answer_f1'] is row['answer_returned'] is None
    assert row['input_tokens'] == 12 and row['backend_calls'] == 9
    assert row['backend_forwarded_calls'] == 7 and row['transferred_bytes'] == 32
    assert row['decision_e2e_ms'] == 123  # No substitution with inner 1ms timing.


@pytest.mark.parametrize('status,censored', [('harness_budget_censored', True), ('method_error', False)])
def test_explicit_budget_status_without_optional_scope_retains_null_score(tmp_path,status,censored):
    meta=metadata('GR');directory=tmp_path/meta['cell_id'];directory.mkdir()
    outcome=write_once(directory/'outcome.json',dict(method=METHODS['GR'],question_id=meta['case_id'],
        success=False,status=status,model_calls=1,input_tokens=20,output_tokens=4,probe_calls=0,
        final_plan_executions=1,decision_e2e_ms=200,source_observations=dict(requests=4,forwarded_requests=4,
            failure_categories={'harness_response_budget':1} if censored else {})))
    score=write_once(directory/'score.json',dict(receipt_sha256=outcome['sha256'],answer_em=0.0,
        answer_row_multiset_f1=0.0,comparison_error=None))
    write_once(directory/'terminal.json',dict(cell_id=meta['cell_id'],outcome=outcome,score=score,
        answer_em=None if censored else 0.0,execution_success=False))
    before={p:p.read_bytes() for p in directory.iterdir()}
    row=extract_cell(meta,directory,Reader(tmp_path))
    assert row['status']==status and row['observation']==('study_censored' if censored else 'method_failure')
    assert row['answer_em']==(None if censored else 0.0)
    assert row['answer_returned'] is (None if censored else False)
    assert row['decision_e2e_ms']==200 and row['model_calls']==1 and row['backend_calls']==4
    group=summarize_rows([row],expected_membership_known=True)[0]
    assert group['study_censored']==int(censored) and group['method_failures']==int(not censored)
    assert group['answer_scoring_denominator']==int(not censored)
    assert all(p.read_bytes()==data for p,data in before.items())


def test_missing_and_unrun_are_not_zero_imputed_and_coverage_has_denominator(tmp_path):
    meta, d = sealed(tmp_path)
    reader = Reader(tmp_path)
    good = extract_cell(meta, d, reader)
    missing = dict(good, cell_id='another', input_tokens=None)
    unrun = extract_cell(meta, tmp_path / 'absent', reader)
    rows = [good, missing, unrun]
    group = next(r for r in summarize_rows(rows, expected_membership_known=True)
                 if r['group_level'] == 'detail')
    assert group['expected_supported'] == 3 and group['unattempted'] == 1
    assert group['coverage_over_expected'] == 2 / 3
    assert group['decision_e2e_ms_mean'] == 123 and group['decision_e2e_ms_n'] == 2
    assert group['input_tokens_observed_sum'] == 12 and group['input_tokens_total'] is None
    assert group['input_tokens_missing_attempts'] == 1
    assert group['method_cpu_seconds_total'] == 2
    assert group['method_peak_rss_bytes_mean'] == 200 and group['method_peak_rss_bytes_max'] == 200
    assert 'method_peak_rss_bytes_total' not in group
    observed = summarize_rows(rows[:2], expected_membership_known=False)[0]
    assert observed['expected_supported'] is observed['unattempted'] is None
    assert observed['coverage_over_expected'] is None


def test_score_comparison_failure_is_not_a_method_quality_failure(tmp_path):
    meta, d = sealed(tmp_path, comparison_error='reference unreadable')
    row = extract_cell(meta, d, Reader(tmp_path))
    assert row['observation'] == 'study_censored' and row['answer_em'] is None


def test_immutable_score_and_outcome_hashes_are_verified(tmp_path):
    meta, d = sealed(tmp_path)
    (d / 'score.json').write_text('{}')
    with pytest.raises(ValueError):
        extract_cell(meta, d, Reader(tmp_path))


def test_release_membership_preserves_unsupported_and_unrun_cells(tmp_path):
    case = dict(case_id=metadata()['case_id'], stratum='uniform', workload='W1')
    selection = write_once(tmp_path / 'selection.json', dict(cohorts=[dict(dataset='D1',
        deployment='native', cases=[case])]))
    cells = [dict(cell_id=case['case_id']+'-'+label, method=method)
             for label, method in METHODS.items() if label != 'TS']
    manifest = write_once(tmp_path / 'manifest.json', dict(cells=cells))
    release = write_once(tmp_path / 'release.json', dict(schema_version='xgap-ch6-small-real-release-v1',
        purpose='small_real_evaluation', exposure='development_exposed', heldout_claim=False,
        selection=selection, units=[dict(dataset='D1', deployment='native', unit_id='u1',
        manifest=manifest, cell_cases={c['cell_id']: case['case_id'] for c in cells})]))
    result = summarize(evidence_root=tmp_path / 'runs', output=tmp_path / 'summary', release_pin=release)
    assert result['observations'] == dict(unattempted=4, unsupported=1)
    data = json.loads((tmp_path / 'summary' / 'summary.json').read_text())
    assert not data['scope']['full_800_claim'] and not data['scope']['heldout_claim']
    rows = list(csv.DictReader((tmp_path / 'summary' / 'actual-cells.csv').open()))
    assert len(rows) == 5 and all(row['model_calls'] == '' for row in rows)
    assert result['model_calls'] == result['backend_calls'] == 0
