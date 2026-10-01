"""Recorded-cohort accounting with controlled calls, without models or backends."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from xgap.experiments import toy_recorded_cohort as cohort


def _cases():
    return [{"id": qid} for qid in cohort.QUERY_IDS]


def _outcome(qid, *, correct=True, agent_success=True, calls=3, status="succeeded"):
    observations = ([] if status in {"interpretation_invalid", "provider_failure", "catalog_unavailable"}
                    else [{"kind": "tool_result", "source": cohort.BIND_PLAN_EXECUTE,
                           "payload": {"metrics": {"remote_calls": calls}}}])
    return {"query_id": qid, "success": correct, "actual_rows": [{"observed": qid}],
            "agent_run": {"success": agent_success, "status": status,
                          "backend_remote_calls": calls, "state": {"observations": observations}},
            "candidate_checks": [], "validation_only_extra_remote_calls": 0}


def _controlled(monkeypatch, outcomes, *, consumption_errors=()):
    state = {"loads": [], "executions": [], "consumption_checks": []}

    class Recording:
        def __init__(self, qid):
            self.qid = qid

        def assert_consumed(self):
            state["consumption_checks"].append(self.qid)
            if self.qid in consumption_errors:
                raise ValueError("Unused recording")

    def load(path):
        state["loads"].append(path.stem)
        return Recording(path.stem)

    def execute(case, mapping, **kwargs):
        state["executions"].append({"qid": case["id"], "mapping": mapping, **kwargs})
        result = outcomes[case["id"]]
        if isinstance(result, Exception):
            raise result
        return deepcopy(result)

    monkeypatch.setattr(cohort, "ReplayInterpretationProvider", SimpleNamespace(from_path=load))
    monkeypatch.setattr(cohort, "execute_binding_case", execute)
    return state


def _run(tmp_path):
    record, updates = {}, []
    mapping, clients = object(), object()
    result = cohort.execute_recorded_binding_cohort(
        _cases(), mapping, clients=clients, recording_root=tmp_path,
        request_profile="explicit-output-v1", record=record,
        on_update=lambda: updates.append(deepcopy(record)))
    assert result is record
    return result, updates, mapping, clients


def test_all_five_remain_in_population_when_two_fail_locally(monkeypatch, tmp_path):
    outcomes = {qid: _outcome(qid) for qid in cohort.QUERY_IDS}
    for qid in ("B02", "B03"):
        outcomes[qid] = _outcome(qid, correct=False, agent_success=False, calls=0,
                                 status="interpretation_invalid")
    state = _controlled(monkeypatch, outcomes)
    result, updates, mapping, clients = _run(tmp_path)
    assert result["population"] == list(cohort.QUERY_IDS)
    assert result["completed"] and not result["success"]
    assert result["correct_count"] == 3 and result["attempted_count"] == 5
    assert result["attempted_backend_calls"] == 9 and result["model_calls"] == 0
    assert [q["status"] for q in result["queries"]] == ["completed"] * 5
    assert [q["success"] for q in result["queries"]] == [True, False, False, True, True]
    assert state["loads"] == state["consumption_checks"] == list(cohort.QUERY_IDS)
    assert [entry["qid"] for entry in state["executions"]] == list(cohort.QUERY_IDS)
    assert all(entry["mapping"] is mapping and entry["clients"] is clients
               and entry["request_profile"] == "explicit-output-v1"
               and entry["validate_candidates"] is False for entry in state["executions"])
    assert all(q["status"] == "not_attempted" for q in updates[0]["queries"])


def test_partial_backend_failure_stops_remaining_without_retry(monkeypatch, tmp_path):
    state = _controlled(monkeypatch, {
        "B01": _outcome("B01"),
        "B02": _outcome("B02", correct=False, agent_success=False, calls=1, status="failed"),
    })
    result, _, _, _ = _run(tmp_path)
    assert state["loads"] == state["consumption_checks"] == ["B01", "B02"]
    assert [entry["qid"] for entry in state["executions"]] == ["B01", "B02"]
    assert result["attempted_count"] == 2 and result["correct_count"] == 1
    assert result["attempted_backend_calls"] == 4
    assert not result["completed"] and not result["success"]
    assert result["stop_reason"] == "backend_failure_or_unknown_cost; no retry"
    assert all(q["status"] == "not_attempted" and q["backend_calls"] is None
               for q in result["queries"][2:])


def test_recording_mismatch_retains_received_failure_and_zero_call_cost(monkeypatch, tmp_path):
    received = _outcome("B01", correct=False, agent_success=False, calls=0, status="provider_failure")
    received["agent_run"]["interpretation"] = {
        "failure_category": "replay_mismatch", "external_calls": 0}
    state = _controlled(monkeypatch, {"B01": received}, consumption_errors={"B01"})
    result, updates, _, _ = _run(tmp_path)
    item = result["queries"][0]
    assert item["status"] == "incomplete" and item["backend_calls"] == 0
    assert item["agent_run"] == received["agent_run"] and item["outcome"] == "provider_failure"
    assert result["attempted_backend_calls"] == 0 and result["correct_count"] == 0
    assert state["loads"] == state["consumption_checks"] == ["B01"]
    assert len(state["executions"]) == 1 and result["attempted_count"] == 1
    assert any(update["queries"][0]["status"] == "completed"
               and update["queries"][0]["backend_calls"] == 0 for update in updates)


def test_consumption_failure_preserves_already_received_backend_cost(monkeypatch, tmp_path):
    received = _outcome("B01", calls=4)
    received["agent_run"]["interpretation"] = {
        "external_calls": 0, "provenance": {"recorded_usage": {
            "external_calls": 1, "input_tokens": 100, "output_tokens": 50}}}
    state = _controlled(monkeypatch, {"B01": received}, consumption_errors={"B01"})
    result, updates, _, _ = _run(tmp_path)
    item = result["queries"][0]
    assert item["status"] == "incomplete" and not item["success"]
    assert item["agent_run"] == received["agent_run"] and item["actual_rows"] == received["actual_rows"]
    assert item["backend_calls"] == result["attempted_backend_calls"] == 4
    assert result["model_calls"] == 0 and result["correct_count"] == 0
    assert state["loads"] == state["consumption_checks"] == ["B01"]
    assert len(state["executions"]) == 1 and result["attempted_count"] == 1
    assert any(update["queries"][0]["status"] == "completed"
               and update["queries"][0]["backend_calls"] == 4 for update in updates)


def test_execution_exception_keeps_unknown_cost_and_never_repeats(monkeypatch, tmp_path):
    state = _controlled(monkeypatch, {"B01": RuntimeError("private transport diagnostic")})
    result, _, _, _ = _run(tmp_path)
    item = result["queries"][0]
    assert item["status"] == "incomplete" and item["backend_calls"] is None
    assert result["attempted_backend_calls"] is None and result["correct_count"] == 0
    assert item["error_type"] == "RuntimeError" and "private transport" not in item["error"]
    assert state["loads"] == ["B01"] and len(state["executions"]) == 1
    assert state["consumption_checks"] == [] and result["attempted_count"] == 1
    assert all(q["status"] == "not_attempted" for q in result["queries"][1:])


def test_swallowed_execution_error_with_legacy_zero_has_unknown_cost(monkeypatch, tmp_path):
    received = _outcome("B01", correct=False, agent_success=False, calls=0, status="failed")
    received["agent_run"]["state"]["observations"][0]["payload"] = {
        "status": "error", "error": "controlled timeout", "metrics": {}}
    state = _controlled(monkeypatch, {"B01": received})
    result, _, _, _ = _run(tmp_path)
    item = result["queries"][0]
    assert item["agent_run"]["backend_remote_calls"] == 0
    assert item["backend_calls"] is None and result["attempted_backend_calls"] is None
    assert result["stop_reason"] == "backend_failure_or_unknown_cost; no retry"
    assert result["attempted_count"] == 1 and not result["completed"]
    assert state["loads"] == state["consumption_checks"] == ["B01"]
    assert len(state["executions"]) == 1
    assert all(q["status"] == "not_attempted" for q in result["queries"][1:])


def test_changed_population_or_resume_is_rejected_before_actions(monkeypatch, tmp_path):
    state = _controlled(monkeypatch, {})
    for cases, record in ((_cases()[:-1], {}), (_cases(), {"existing_attempt": True})):
        before = deepcopy(record)
        update = Mock()
        with pytest.raises(ValueError):
            cohort.execute_recorded_binding_cohort(
                cases, {}, clients={}, recording_root=tmp_path, request_profile="explicit-output-v1",
                record=record, on_update=update)
        assert record == before
        update.assert_not_called()
    assert state == {"loads": [], "executions": [], "consumption_checks": []}
