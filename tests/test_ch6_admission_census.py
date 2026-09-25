"""Classify bounded failures without skipping unknown work or retrying queries."""
from pathlib import Path

import pytest

from xgap.experiments.ch6_admission_policy import AdmissionBudgets, CLOSURE_KEYS, classify
from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.one_shot_records import write_once
import run_ch6_admission_census as subject


def row(name, outcome='correct'):
    value = dict(case_id=name, success=outcome == 'correct',
        answer_em=1 if outcome == 'correct' else 0 if outcome == 'wrong' else None,
        guard=dict(status='completed', success=outcome == 'correct', cleanup=dict(complete=True)),
        source_observations=dict(failure_categories={}, failed_requests=0))
    if outcome == 'timeout':
        value['source_observations'].update(failure_categories={'source_timeout': 1}, failed_requests=1)
    return value


def test_timeout_and_unknown_errors_are_never_correct_empty_answers():
    assert classify(row('a', 'timeout')) == 'source_timeout'
    assert classify(row('a', 'wrong')) == 'answer_mismatch'
    r = row('a', 'timeout'); r['source_observations']['failure_categories']['harness_persistence'] = 1
    assert classify(r) == 'infrastructure_or_execution_failure'
    r = row('a', 'unknown'); r['guard']['status'] = 'deadline_exceeded'
    assert classify(r) == 'worker_timeout'
    r['guard']['cleanup']['complete'] = False
    assert classify(r) == 'infrastructure_or_execution_failure'


@pytest.mark.parametrize('values', [(True,120),(60,60),(300,120),(0,120),(60,3601)])
def test_invalid_budget_pair_rejected(values):
    with pytest.raises(ValueError): AdmissionBudgets(*values)


def fixture(tmp_path, monkeypatch, *, bad_closure=False, mismatch=False):
    bp = write_once(tmp_path/'bundle.json', dict(cases=[dict(case_id=k) for k in 'abcd']))
    calls = []
    def execute(bundle, prepared, target, *, case_ids, **kwargs):
        calls.append(list(case_ids))
        assert kwargs['source_timeout_seconds'] == 300 and kwargs['worker_seconds'] == 660
        assert len(case_ids) <= 4  # bounded by the inner one-hour segment guard
        Path(target).mkdir(parents=True)
        first = len(calls) == 1
        rows = [row('a'), row('b','wrong' if mismatch else 'timeout')] if first else [row(k) for k in case_ids]
        closure = dict.fromkeys(CLOSURE_KEYS, True)
        if bad_closure: closure['owned_groups_drained'] = False
        write_once(Path(target)/'receipt.json', dict(bundle=bundle,
            prepared=prepared, success=not first,
            admission_budgets=AdmissionBudgets(300,660).to_dict(),
            attempted=len(rows), audited=len(rows), cases=rows, closure=closure))
        return 2 if first else 0
    monkeypatch.setattr(subject, 'run', execute)
    return bp, calls


def test_resource_failure_is_recorded_and_only_unattempted_suffix_runs(tmp_path, monkeypatch):
    bp, calls = fixture(tmp_path,monkeypatch)
    result = load_pin(subject.census(bp,{},tmp_path/'census',case_ids=list('abcd'),
        source_timeout_seconds=300,worker_seconds=660,max_census_seconds=10000))
    assert calls == [list('abcd'),list('cd')]
    assert result['census_complete'] and not result['all_answers_correct']
    assert result['counts'] == {'correct':3,'source_timeout':1}
    assert not result['full_bundle_admitted'] and not result['formal_campaign_ready']
    assert not result['remaining'] and result['automatic_retries'] == 0


@pytest.mark.parametrize('problem', ['closure','answer'])
def test_semantic_or_closure_problem_blocks_next_segment(tmp_path, monkeypatch, problem):
    bp,calls = fixture(tmp_path,monkeypatch,bad_closure=problem=='closure',mismatch=problem=='answer')
    result = load_pin(subject.census(bp,{},tmp_path/'census',case_ids=list('abcd'),
        source_timeout_seconds=300,worker_seconds=660,max_census_seconds=10000))
    assert len(calls) == 1 and not result['census_complete'] and not result['remaining_safe_to_dispatch']
    assert result['stop_reason'] == ('unverified_segment' if problem=='closure' else 'correctness_or_infrastructure_blocker')


def test_reordered_selection_and_insufficient_budget_never_execute(tmp_path, monkeypatch):
    bp,calls = fixture(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='frozen bundle order'):
        subject.census(bp,{},tmp_path/'wrong',case_ids=['b','a'])
    result = load_pin(subject.census(bp,{},tmp_path/'short',case_ids=list('abcd'),
        source_timeout_seconds=300,worker_seconds=660,max_census_seconds=1))
    assert not calls and not result['census_complete'] and result['stop_reason']=='census_budget'


def test_admission_budget_defaults_preserve_historical_caps():
    assert AdmissionBudgets().to_dict() == dict(source_timeout_seconds=60,worker_seconds=120)


def test_long_request_budget_reaches_shared_transport_and_engine_configs(tmp_path):
    from xgap.experiments.campaign_source_observer import SourceObservationBudget, CampaignSourceObserver
    from xgap.experiments.m15_native_services import _fuseki_server_configuration, _neo4j_configuration
    budget = SourceObservationBudget(timeout_seconds=300)
    proxy = CampaignSourceObserver({}, tmp_path/'observer', budget=budget)
    try:
        assert proxy.timeout == 300
    finally:
        proxy.close()
    assert '300000' in _fuseki_server_configuration(query_timeout_seconds=budget.timeout_seconds)
    config = _neo4j_configuration(neo4j_root=tmp_path/'engine',state_root=tmp_path,
        http_port=12340,bolt_port=12341,query_timeout_seconds=budget.timeout_seconds,
        resource_profile=dict(heap_initial_size='256m',heap_max_size='768m',pagecache_size='128m'))
    assert 'db.transaction.timeout=300s' in config
    with pytest.raises(ValueError): SourceObservationBudget(timeout_seconds=3601)


def test_typed_failure_category_agrees_with_verified_real_timeout():
    # Minimal structured fields of the archived cq7 timeout, no payload/data dependency.
    r = row('cycle', 'timeout')
    r['guard'].update(exit_code=2,status='completed',success=False)
    r['answer_em']=None
    assert classify(r)=='source_timeout'
