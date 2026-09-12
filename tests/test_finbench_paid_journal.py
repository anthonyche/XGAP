"""Focused persistence accounting; costs and answers here are controlled."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from test_finbench_paid_selection import ControlledScheduler, _orders, prepared, public_workload
from test_m15_finbench_federation import _scheduler

from xgap.experiments import finbench_paid_journal as journal_module
from xgap.experiments import finbench_paid_selection as paid
from xgap.experiments.finbench_paid_journal import PaidSelectionJournal


@pytest.fixture
def first_query(prepared):
    public, _, _ = prepared
    return paid.prepare_finbench_paid_selection(public["root"], query_ids=paid.FIXED_QUERY_IDS[:1])


def _execute(first_query, scheduler, record, journal):
    public, candidates, preparation = first_query
    query_ids = paid.FIXED_QUERY_IDS[:1]
    methods, acquisitions = _orders(candidates, query_ids)
    return paid.run_finbench_paid_selection(
        public_workload=public, candidates_by_query=candidates,
        preparation_receipt=preparation, scheduler=scheduler,
        method_orders=methods, acquisition_orders=acquisitions,
        record=record, on_update=journal, query_ids=query_ids,
    )


def _small_record():
    action = {
        "action_id": "q/paid_selection/acquisition-1", "role": "acquisition",
        "plan_id": "controlled-plan", "physical_strategy": "graph_first_hash",
        "status": "not_attempted", "runtime_result": None,
        "elapsed_ms": None, "call_wall_ms": None,
        "total_remote_calls": None, "total_bytes_moved": None,
    }
    method = {
        "method_id": "paid_selection", "status": "not_attempted", "executions": [action],
        "selection": None, "final_rows": None, "wall_ms": None,
        "total_remote_calls": None, "total_bytes_moved": None,
    }
    return {
        "status": "started", "population": ["q"], "population_count": 1,
        "queries": [{"query_id": "q", "family_id": "f1_direct_transfer_control",
                     "split_role": "controlled", "integration_exposed": False,
                     "selected_for_attempt": True, "methods": [method]}],
    }


def _complete_action(action):
    action.update(
        status="completed", elapsed_ms=1.0, call_wall_ms=1.2,
        total_remote_calls=2, total_bytes_moved=32,
        runtime_result={"success": True, "final_rows": [{
            "company_id": "raw-answer-sentinel", "account_id": "A1", "total_amount": 7,
        }]},
    )


def test_repeated_callbacks_write_results_and_selection_once_without_mutating_seal(tmp_path, monkeypatch):
    record = _small_record()
    method = record["queries"][0]["methods"][0]
    _complete_action(method["executions"][0])
    method.update(status="completed", selection={
        "selected_plan_id": "controlled-plan", "selected_physical_strategy": "graph_first_hash",
        "selection_ms": 0.1, "answer_values_consulted": False,
    })
    record.update(status="completed", executions_sealed_before_evaluation=True)
    record["execution_seal_sha256"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
    before = deepcopy(record)
    journal = PaidSelectionJournal(tmp_path / "journal", record)
    encoded = {"action": 0, "selection": 0}
    original_encode = journal_module._encode

    def encode_once(value):
        if value is method["executions"][0]:
            encoded["action"] += 1
        if value is method["selection"]:
            encoded["selection"] += 1
        return original_encode(value)

    monkeypatch.setattr(journal_module, "_encode", encode_once)
    journal()
    saved = {
        row["path"]: (tmp_path / "journal" / row["path"]).read_bytes()
        for row in journal.receipt()["files"]
    }
    for _ in range(3):
        journal()

    receipt = journal.receipt()
    assert record == before
    assert sorted(row["kind"] for row in receipt["files"]) == ["action", "selection"]
    assert len(saved) == 2
    assert all((tmp_path / "journal" / name).read_bytes() == data for name, data in saved.items())
    assert receipt["callback_count"] == 4
    assert encoded == {"action": 1, "selection": 1}
    assert receipt["success"] is True
    events = (tmp_path / "journal/events.jsonl").read_text()
    assert "raw-answer-sentinel" not in events
    assert '"runtime_result"' not in events
    assert '"final_rows"' not in events


@pytest.mark.parametrize("failure_boundary", ["initial-intent", "winner-seal"])
def test_durability_failure_prevents_next_dispatch_and_poisoned_sink_cannot_retry(
    first_query, tmp_path, monkeypatch, failure_boundary
):
    record = {}
    journal = PaidSelectionJournal(tmp_path / "journal", record)
    original_fsync = journal_module.os.fsync
    fsync_attempts = []

    def fail_at_boundary(fd):
        fsync_attempts.append(fd)
        selection_exists = any(method.get("selection") is not None
                               for query in record.get("queries", []) for method in query["methods"])
        if failure_boundary == "initial-intent" or selection_exists:
            raise OSError("controlled durable write failure")
        return original_fsync(fd)

    monkeypatch.setattr(journal_module.os, "fsync", fail_at_boundary)
    scheduler = ControlledScheduler()
    with pytest.raises(OSError, match="controlled durable write failure"):
        _execute(first_query, scheduler, record, journal)
    assert len(scheduler.calls) == (0 if failure_boundary == "initial-intent" else 4)
    count = len(fsync_attempts)
    with pytest.raises(Exception, match="failed|poison|retry"):
        journal()
    assert len(fsync_attempts) == count
    receipt = journal.receipt()
    assert receipt["success"] is False
    assert receipt["bytes_complete"] is False
    assert receipt["error"] is not None


def test_callback_time_is_charged_online_and_terminal_summaries_are_separate(tmp_path, monkeypatch):
    ticks = iter(index * 0.01 for index in range(20))
    monkeypatch.setattr(journal_module, "time", SimpleNamespace(perf_counter=lambda: next(ticks)))
    record = _small_record()
    method = record["queries"][0]["methods"][0]
    journal = PaidSelectionJournal(tmp_path / "journal", record)
    journal()  # Initial block index.
    method["status"] = "started"
    journal()
    _complete_action(method["executions"][0])
    journal()
    method["status"] = "completed"
    journal()  # Method wall has already been measured by the core.
    record.update(status="completed", executions_sealed_before_evaluation=True)
    journal()

    receipt = journal.receipt()
    assert receipt["included_ms"] == pytest.approx(20)
    assert receipt["excluded_ms"] == pytest.approx(10)
    assert receipt["unattributed_ms"] == pytest.approx(20)
    assert receipt["initialization_ms"] == pytest.approx(10)
    assert receipt["callback_count"] == 5
    assert len(receipt["per_method"]) == 1
    method_cost = receipt["per_method"][0]
    assert (method_cost["query_id"], method_cost["method_id"]) == ("q", "paid_selection")
    assert method_cost["included_ms"] == pytest.approx(20)
    assert method_cost["excluded_ms"] == pytest.approx(10)
    assert method_cost["callback_count"] == 3
    assert method_cost["included_bytes"] == receipt["included_bytes"] > 0
    assert method_cost["excluded_bytes"] == receipt["excluded_bytes"] > 0
    assert receipt["bytes_written"] == sum(receipt[f"{scope}_bytes"] for scope in (
        "included", "excluded", "unattributed"
    ))


def test_tiny_real_coordinator_persists_selection_before_fresh_final(first_query, tmp_path):
    scheduler = _scheduler({
        "neo4j-full": [
            {"company_id": "C1", "account_id": "A1", "total_amount": 7.0},
            {"company_id": "C2", "account_id": "A2", "total_amount": 9.0},
        ],
        "neo4j-bound": [{"company_id": "C1", "account_id": "A1", "total_amount": 7.0}],
        "fuseki-control": [{"account_id": "A1"}],
    })
    record = {}
    journal = PaidSelectionJournal(tmp_path / "journal", record)
    calls = []

    def execute(plan, *, goal_id):
        if len(calls) == 4:
            kinds = [row["kind"] for row in journal.receipt()["files"]]
            assert kinds.count("action") == 4
            assert kinds.count("selection") == 1
        calls.append(plan.plan_id)
        return scheduler.execute(plan, goal_id=goal_id)

    result = _execute(first_query, SimpleNamespace(execute=execute), record, journal)
    methods = result["queries"][0]["methods"]
    expected = [{"company_id": "C1", "account_id": "A1", "total_amount": "7.000"}]
    assert result["success"] is True
    assert len(calls) == 5 and result["total_remote_calls"] == 10
    assert [method["final_rows"] for method in methods] == [expected] * 3
    assert calls[-1] == methods[2]["selection"]["selected_plan_id"]
    receipt = journal.receipt()
    assert sum(row["kind"] == "action" for row in receipt["files"]) == 5
    assert sum(row["kind"] == "selection" for row in receipt["files"]) == 1
    persistence = {row["method_id"]: row for row in receipt["per_method"]}
    assert all(method["wall_ms"] >= persistence[method["method_id"]]["included_ms"]
               for method in methods)
    assert receipt["included_ms"] > 0 and receipt["excluded_ms"] > 0
    assert result["executions_sealed_before_evaluation"] is True
