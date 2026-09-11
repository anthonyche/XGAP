"""Prepared-plan FinBench baselines with paid, answer-blind strategy selection.

Compilation is shared offline preparation. Method wall time starts from the
prepared pair and includes acquisition, bounded bookkeeping, selection and a
fresh final execution. This is neither semantic Interpretation nor P1/A3.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Sequence

from xgap.experiments.m15_finbench_federation import (
    build_finbench_plan_candidates, canonicalize_finbench_rows,
)
from xgap.experiments.m15_finbench_workload import load_finbench_primary_public_workload
from xgap.runtime.contracts import FederatedRunResult
from xgap.runtime.planning import FederatedPlanCandidate
from xgap.runtime.scheduler import FederatedScheduler


SCHEMA_VERSION = "xgap-finbench-paid-selection-v1"
METHODS = ("fixed_hash", "fixed_bind", "paid_selection")
FIXED_QUERY_IDS = tuple(f"m15-fb-confirmatory-48-f{family}-01" for family in (1, 2, 3))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _population(public_workload: Mapping[str, Any], query_ids: Sequence[str]):
    instances = public_workload["public_instances"]["instances"]
    manifest = public_workload["manifest"]
    ids = [item["query_id"] for item in instances]
    selected = tuple(query_ids)
    if (not ids or len(ids) != len(set(ids)) or len(ids) != manifest["instance_count"]
            or not selected or len(selected) != len(set(selected)) or not set(selected) <= set(ids)):
        raise ValueError("Paid selection requires the complete public population and unique admitted query IDs")
    if any({"oracle", "final_rows", "expected_rows", "sealed_oracles"}.intersection(item) for item in instances):
        raise ValueError("Paid selection accepts public instances only")
    return instances, selected


def _catalog(candidates_by_query, instances, query_ids, workload_sha256):
    by_id = {item["query_id"]: item for item in instances}
    if set(candidates_by_query) != set(query_ids):
        raise ValueError("Prepared candidate coverage differs from the selected query IDs")
    catalog, pairs = [], {}
    for query_id in query_ids:
        candidates = candidates_by_query[query_id]
        if (len(candidates) != 2 or any(not isinstance(c, FederatedPlanCandidate) for c in candidates)
                or len({c.semantic_equivalence_key for c in candidates}) != 1):
            raise ValueError("Each query requires two equivalent prepared FinBench plans")
        pair = {}
        for candidate in candidates:
            plan, instance = candidate.plan, by_id[query_id]
            metadata = plan.metadata
            strategy = metadata.get("physical_strategy")
            if (not isinstance(strategy, str) or strategy in pair or plan.max_remote_calls != 2
                    or any(metadata.get(key) != instance[key] for key in ("query_id", "family_id", "split_role"))
                    or metadata.get("workload_sha256") != workload_sha256):
                raise ValueError("Prepared FinBench plan identity or call budget changed")
            pair[strategy] = candidate
            catalog.append({"query_id": query_id, "physical_strategy": strategy,
                            "semantic_equivalence_key": candidate.semantic_equivalence_key,
                            "plan": plan.to_dict()})
        if sum(s.endswith("_hash") for s in pair) != 1 or sum(s.startswith("control_first_") for s in pair) != 1:
            raise ValueError("Prepared pair must contain one hash and one control-first strategy")
        if len({c.plan.plan_id for c in candidates}) != 2:
            raise ValueError("Prepared pair plan IDs must differ")
        pairs[query_id] = pair
    return catalog, pairs


def prepare_finbench_paid_selection(workload_root: str | Path, *, query_ids=FIXED_QUERY_IDS):
    """Verify public files and compile the supplied IDs; never parse oracle JSON."""
    started, started_at = time.perf_counter(), _now()
    public = load_finbench_primary_public_workload(workload_root)
    instances, selected = _population(public, query_ids)
    candidates = {qid: build_finbench_plan_candidates(workload_root, query_id=qid) for qid in selected}
    catalog, _ = _catalog(candidates, instances, selected, public["manifest"]["workload_sha256"])
    receipt = {"schema_version": SCHEMA_VERSION + "/preparation", "started_at": started_at,
        "ended_at": _now(), "workload_sha256": public["manifest"]["workload_sha256"],
        "source_archive_sha256": public["manifest"]["source_archive_sha256"],
        "population_id": public["manifest"]["population_id"],
        "population": [item["query_id"] for item in instances], "selected_query_ids": list(selected),
        "public_inputs_sha256": _digest(public["public_instances"]), "plan_catalog": catalog,
        "plan_catalog_sha256": _digest(catalog), "compilation_ms": (time.perf_counter() - started) * 1000,
        "cost_scope": "shared offline public-file validation and candidate compilation; excluded from method wall",
        "backend_calls": 0, "model_calls": 0, "oracle_content_parsed": False,
        "oracle_bytes_hashed_for_identity": True, "automatic_retries": 0}
    receipt["preparation_sha256"] = _digest(receipt)
    return public, candidates, receipt


def _action(query_id, method_id, role, index, strategy=None, plan_id=None):
    return {"action_id": f"{query_id}/{method_id}/{role}-{index}", "role": role,
            "physical_strategy": strategy, "plan_id": plan_id, "status": "not_attempted",
            "runtime_result": None, "elapsed_ms": None, "call_wall_ms": None,
            "total_remote_calls": None, "total_bytes_moved": None}


def _run_plan(scheduler, candidate, action, record, on_update):
    action.update(status="started", started_at=_now(), plan_id=candidate.plan.plan_id,
                  physical_strategy=candidate.plan.metadata["physical_strategy"])
    on_update()  # Durable dispatch intent precedes the only scheduler call.
    started = time.perf_counter()
    record["attempted_plan_runs"] += 1
    try:
        result = scheduler.execute(candidate.plan, goal_id=action["action_id"])
        action["call_wall_ms"] = (time.perf_counter() - started) * 1000
        if not isinstance(result, FederatedRunResult):
            raise ValueError("Scheduler did not return a typed federated result")
        raw = result.to_dict()
        try:
            _digest(raw)
        except (TypeError, ValueError):
            action["unserializable_runtime_result"] = repr(raw)
            raise ValueError("Runtime result cannot be retained as finite JSON") from None
        action["runtime_result"] = raw
        if (result.plan_id != candidate.plan.plan_id or type(result.success) is not bool
                or not _finite(result.elapsed_ms)
                or type(result.total_remote_calls) is not int or not 0 <= result.total_remote_calls <= 2
                or type(result.total_bytes_moved) is not int or result.total_bytes_moved < 0):
            raise ValueError("Runtime result identity or cost is unknown/invalid")
        action.update(status="completed" if result.success else "failed", elapsed_ms=result.elapsed_ms,
                      total_remote_calls=result.total_remote_calls, total_bytes_moved=result.total_bytes_moved)
    except Exception as error:
        action.update(status="unknown", error_type=type(error).__name__, error=str(error))
    action.update(ended_at=_now(), call_wall_ms=(time.perf_counter() - started) * 1000)
    on_update()  # Received outcome and cost are retained before any selection.
    return action["status"] == "completed"


def _selection(costs):
    # Same measured (latency, logical exchange bytes, strategy) rule as the
    # legacy FinBench _profile_selection; this view contains no answer rows.
    chosen = min(costs, key=lambda c: (c["elapsed_ms"], c["total_bytes_moved"], c["physical_strategy"]))
    return {"cost_inputs": costs, "selected_plan_id": chosen["plan_id"],
            "selected_physical_strategy": chosen["physical_strategy"],
            "source_action_id": chosen["action_id"], "answer_values_consulted": False,
            "sampled_answer_reused": False, "sealed_at": _now()}


def run_finbench_paid_selection(*, public_workload, candidates_by_query, preparation_receipt,
        scheduler: FederatedScheduler, method_orders: Mapping[str, Sequence[str]],
        acquisition_orders: Mapping[str, Sequence[str]], record: dict[str, Any],
        on_update: Callable[[], None], query_ids=FIXED_QUERY_IDS, max_elapsed_seconds=600.0) -> dict:
    """Execute a predeclared subset while retaining the complete public ledger.

    ``on_update`` must persist ``record`` synchronously; a persistence exception
    aborts dispatch. Native query deadlines and service cleanup belong to the
    caller. This function checks its elapsed budget between actions only.
    Returned records are sealed before any independent answer evaluation.
    """
    started = time.perf_counter()
    if record or not callable(on_update) or not _finite(max_elapsed_seconds) or max_elapsed_seconds == 0:
        raise ValueError("A fresh record, synchronous persistence and a finite positive time budget are required")
    instances, selected = _population(public_workload, query_ids)
    manifest = public_workload["manifest"]
    catalog, pairs = _catalog(candidates_by_query, instances, selected, manifest["workload_sha256"])
    preparation = dict(preparation_receipt)
    claimed = preparation.pop("preparation_sha256", None)
    if (claimed != _digest(preparation) or preparation.get("plan_catalog") != catalog
            or preparation.get("plan_catalog_sha256") != _digest(catalog)
            or preparation.get("public_inputs_sha256") != _digest(public_workload["public_instances"])
            or preparation.get("workload_sha256") != manifest["workload_sha256"]
            or preparation.get("source_archive_sha256") != manifest["source_archive_sha256"]
            or preparation.get("population") != [i["query_id"] for i in instances]
            or preparation.get("selected_query_ids") != list(selected)
            or not _finite(preparation.get("compilation_ms"))
            or preparation.get("backend_calls") != 0 or preparation.get("oracle_content_parsed") is not False):
        raise ValueError("Prepared plans/public identities or preparation cost receipt changed")
    if set(method_orders) != set(selected) or set(acquisition_orders) != set(selected):
        raise ValueError("Both frozen orders must cover exactly the selected query IDs")
    for qid in selected:
        if (len(method_orders[qid]) != 3 or set(method_orders[qid]) != set(METHODS)
                or len(acquisition_orders[qid]) != 2 or set(acquisition_orders[qid]) != set(pairs[qid])):
            raise ValueError("Frozen orders must contain each method/strategy exactly once")
    frozen_orders = {"query_ids": list(selected),
        "method_orders": {qid: list(method_orders[qid]) for qid in selected},
        "acquisition_orders": {qid: list(acquisition_orders[qid]) for qid in selected}}
    record.update(schema_version=SCHEMA_VERSION, track="prepared_plan_decision_time_baseline",
        paper_result=False, p1_exercised=False, a3_exercised=False, interpretation_exercised=False,
        population_id=manifest["population_id"], population=[i["query_id"] for i in instances],
        population_count=len(instances), split_counts=dict(Counter(i["split_role"] for i in instances)),
        workload_sha256=manifest["workload_sha256"], source_archive_sha256=manifest["source_archive_sha256"],
        preparation_receipt=preparation_receipt, compilation_cost_in_method_wall=False,
        method_wall_scope="method intent through action/selection persistence and final normalization; terminal summary write excluded",
        frozen_orders=frozen_orders, order_sha256=_digest(frozen_orders),
        max_plan_runs=5 * len(selected), max_query_calls=10 * len(selected),
        max_elapsed_seconds=max_elapsed_seconds, timeout_semantics="between-action checks; caller owns native/global deadlines",
        started_at=_now(), status="started", completed=False, success=False, stop_reason=None,
        attempted_plan_runs=0, model_calls=0, automatic_retries=0, oracle_content_parsed=False,
        answers_evaluated=False, executions_sealed_before_evaluation=False, queries=[])
    for instance in instances:
        qid = instance["query_id"]
        methods = []
        for method_id in METHODS:
            actions = []
            if qid in pairs:
                pair = pairs[qid]
                if method_id == "paid_selection":
                    actions = [_action(qid, method_id, "acquisition", index, strategy, pair[strategy].plan.plan_id)
                               for index, strategy in enumerate(frozen_orders["acquisition_orders"][qid], 1)]
                    actions.append(_action(qid, method_id, "final", 1))
                else:
                    strategy = next(s for s in pair if s.endswith("_hash") == (method_id == "fixed_hash"))
                    actions = [_action(qid, method_id, "final", 1, strategy, pair[strategy].plan.plan_id)]
            methods.append({"method_id": method_id, "status": "not_attempted", "executions": actions,
                "selection": None, "final_rows": None, "wall_ms": None,
                "total_remote_calls": None, "total_bytes_moved": None})
        record["queries"].append({"query_id": qid, "family_id": instance["family_id"],
            "split_role": instance["split_role"], "integration_exposed": qid in FIXED_QUERY_IDS,
            "selected_for_attempt": qid in selected, "methods": methods})
    on_update()
    by_query = {q["query_id"]: q for q in record["queries"]}
    for qid in selected:
        methods = {m["method_id"]: m for m in by_query[qid]["methods"]}
        for method_id in frozen_orders["method_orders"][qid]:
            if time.perf_counter() - started >= max_elapsed_seconds:
                record["stop_reason"] = "elapsed_budget_exhausted_before_method"
                break
            method, method_at = methods[method_id], time.perf_counter()
            method.update(status="started", started_at=_now())
            on_update()
            for action in method["executions"]:
                if time.perf_counter() - started >= max_elapsed_seconds:
                    method["status"] = "budget_exhausted"
                    record["stop_reason"] = "elapsed_budget_exhausted_before_action"
                    break
                if method_id == "paid_selection" and action["role"] == "final":
                    select_at = time.perf_counter()
                    costs = [{key: sample[key] for key in ("action_id", "plan_id", "physical_strategy",
                              "elapsed_ms", "total_bytes_moved")} for sample in method["executions"][:2]]
                    method["selection"] = _selection(costs)
                    method["selection"]["selection_ms"] = (time.perf_counter() - select_at) * 1000
                    action["physical_strategy"] = method["selection"]["selected_physical_strategy"]
                    action["plan_id"] = method["selection"]["selected_plan_id"]
                    on_update()  # Winner seal must succeed before final execution.
                    if time.perf_counter() - started >= max_elapsed_seconds:
                        method["status"] = "budget_exhausted"
                        record["stop_reason"] = "elapsed_budget_exhausted_after_selection"
                        break
                candidate = pairs[qid][action["physical_strategy"]]
                if not _run_plan(scheduler, candidate, action, record, on_update):
                    method["status"] = action["status"]
                    record["stop_reason"] = "external_failure_or_unknown_cost; no retry"
                    break
                if action["role"] == "final":
                    try:
                        method["final_rows"] = canonicalize_finbench_rows(
                            by_query[qid]["family_id"], action["runtime_result"]["final_rows"])
                    except (TypeError, ValueError, KeyError) as error:
                        method.update(status="failed", error_type=type(error).__name__, error=str(error))
                        record["stop_reason"] = "final_result_contract_failure; no retry"
                        break
            if method["status"] == "started":
                method["status"] = "completed"
            attempted = [a for a in method["executions"] if a["status"] != "not_attempted"]
            for field in ("total_remote_calls", "total_bytes_moved"):
                method[field] = sum(a[field] for a in attempted) if all(type(a[field]) is int for a in attempted) else None
            method.update(wall_ms=(time.perf_counter() - method_at) * 1000, ended_at=_now())
            on_update()
            if record["stop_reason"]:
                break
        if record["stop_reason"]:
            break
    selected_methods = [m for q in record["queries"] if q["selected_for_attempt"] for m in q["methods"]]
    actions = [a for m in selected_methods for a in m["executions"] if a["status"] != "not_attempted"]
    record["completed"] = all(m["status"] == "completed" for m in selected_methods)
    record.update(success=record["completed"], status="completed" if record["completed"] else "stopped",
        success_semantics="selected methods executed with valid result schemas; independent exact answers not yet evaluated",
        attempted_method_count=sum(m["status"] != "not_attempted" for m in selected_methods),
        completed_method_count=sum(m["status"] == "completed" for m in selected_methods),
        ended_at=_now(), elapsed_ms=(time.perf_counter() - started) * 1000)
    for field in ("total_remote_calls", "total_bytes_moved"):
        record[field] = sum(a[field] for a in actions) if all(type(a[field]) is int for a in actions) else None
    record["known_remote_calls"] = sum(a["total_remote_calls"] for a in actions if type(a["total_remote_calls"]) is int)
    record["known_exchange_bytes"] = sum(a["total_bytes_moved"] for a in actions if type(a["total_bytes_moved"]) is int)
    record["bytes_semantics"] = "runtime logical exchange bytes; not HTTP wire bytes"
    record["executions_sealed_before_evaluation"] = True
    record["execution_seal_sha256"] = _digest(record)
    on_update()
    return record
