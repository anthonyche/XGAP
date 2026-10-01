"""Five immutable recorded questions, with query failures kept in the denominator."""

from pathlib import Path

from xgap.agent.semantic_execution import BIND_PLAN_EXECUTE
from xgap.experiments.toy_binding import execute_binding_case
from xgap.semantic.interpretation_replay import ReplayInterpretationProvider


QUERY_IDS = ("B01", "B02", "B03", "B04", "B05")


def _observed_backend_calls(run):
    if run.get("status") in {"interpretation_invalid", "provider_failure", "catalog_unavailable"}:
        return 0  # These run_question branches do not enter execution.
    calls = [o.get("payload", {}).get("metrics", {}).get("remote_calls")
             for o in run.get("state", {}).get("observations", [])
             if o.get("kind") == "tool_result" and o.get("source") == BIND_PLAN_EXECUTE]
    # Legacy aggregate counters default missing metrics to zero. Do not use
    # that default to continue after a swallowed execution error or timeout.
    return sum(calls) if calls and all(type(c) is int and c >= 0 for c in calls) else None


def execute_recorded_binding_cohort(cases, mapping, *, clients, recording_root,
                                    request_profile, record, on_update):
    """No model access or retries; stop after external failure or unknown outcome."""
    if tuple(case["id"] for case in cases) != QUERY_IDS:
        raise ValueError("Recorded cohort requires the original five questions in order")
    if record:
        raise ValueError("Recorded cohort cannot resume or replace an existing attempt")
    record.update(schema_version="xgap-toy-recorded-cohort-v1", paper_result=False,
                  request_profile=request_profile, population=list(QUERY_IDS),
                  automatic_retries=0, model_calls=0, completed=False, success=False,
                  queries=[{"query_id": qid, "status": "not_attempted", "success": False,
                            "backend_calls": None} for qid in QUERY_IDS])
    on_update()
    for case, item in zip(cases, record["queries"]):
        item["status"] = "started"
        on_update()
        entered_execution = False
        try:
            provider = ReplayInterpretationProvider.from_path(
                Path(recording_root) / (case["id"] + ".json"))
            entered_execution = True
            result = execute_binding_case(case, mapping, clients=clients,
                interpretation_provider=provider, request_profile=request_profile,
                validate_candidates=False)
            item.update(result)
            run = result["agent_run"]
            item.update(status="completed", outcome=run.get("status"),
                        backend_calls=_observed_backend_calls(run))
            on_update()  # Retain received outcome/cost before checking replay consumption.
            provider.assert_consumed()
            if item["backend_calls"] is None or (not run["success"] and item["backend_calls"] != 0):
                record["stop_reason"] = "backend_failure_or_unknown_cost; no retry"
                break
        except Exception as error:
            item.update(status="incomplete", success=False,
                        error_type=type(error).__name__, error="Recorded cohort action failed; no retry")
            if not entered_execution:
                item["backend_calls"] = 0
            record["stop_reason"] = "recording_or_execution_failure; no retry"
            break
        finally:
            on_update()
    record["completed"] = all(q["status"] == "completed" for q in record["queries"])
    record["correct_count"] = sum(q["success"] for q in record["queries"])
    record["success"] = record["completed"] and record["correct_count"] == len(QUERY_IDS)
    record["attempted_count"] = sum(q["status"] != "not_attempted" for q in record["queries"])
    calls = [q["backend_calls"] for q in record["queries"] if q["status"] != "not_attempted"]
    record["attempted_backend_calls"] = sum(calls) if all(type(c) is int for c in calls) else None
    on_update()
    return record
