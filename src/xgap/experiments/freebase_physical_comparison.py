"""Small CPU development comparisons with fixed meanings and paired order.

This reuses the actual runtime for both plans. It does not select queries,
consult an answer oracle, change data, call a model, or admit paper results.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import statistics
import time
from typing import Any, Mapping

from xgap.experiments.freebase_native_answers import FactAnswerProgram, _BoundedClient, answer_pairs
from xgap.runtime import FederatedExecutionPlan, FederatedScheduler, RuntimeNode, RuntimeNodeKind
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


STRATEGIES = ("neo4j_then_fuseki", "single_fuseki")


class _ObservedClient(_BoundedClient):
    def __init__(self, client: Any, max_rows: int):
        super().__init__(client, max_rows)
        self.attempts = 0

    def execute(self, artifact):
        self.attempts += 1
        return super().execute(artifact)


def comparison_plans(program: FactAnswerProgram) -> dict[str, FederatedExecutionPlan]:
    """Use the same scheduler/project boundary for the complete Fuseki plan."""
    baseline = FederatedExecutionPlan(program.plan.plan_id + "-single-fuseki", (
        RuntimeNode("query", RuntimeNodeKind.REMOTE_QUERY,
                    parameters={"backend_id": "fuseki", "artifact": program.baseline.to_dict()}),
        RuntimeNode("answer", RuntimeNodeKind.PROJECT, ("query",),
                    parameters={"fields": ["entity", "answer"]}),
    ), ("answer",), max_remote_calls=1, max_parallelism=1)
    return dict(zip(STRATEGIES, (program.plan, baseline)))


def measure_plan(plan: FederatedExecutionPlan, *, max_rows: int,
                 neo4j: Any, fuseki: Any) -> dict[str, Any]:
    """Measure dispatch through typed answer normalization, excluding recording."""
    clients = [_ObservedClient(client, max_rows) for client in (neo4j, fuseki)]
    registry = BackendPluginRegistry()
    for client in clients:
        registry.register(NativeBackendPlugin(client.backend_id, client))
    scheduler = FederatedScheduler(BackendInvokeTool(registry))
    record: dict[str, Any] = {"success": False}
    started = time.perf_counter()
    result = None
    try:
        result = scheduler.execute(plan)
        if result.success:
            record["answers"] = answer_pairs(result.root_rows["answer"])
            record["success"] = True
        else:
            record["error"] = "Runtime plan failed; inspect retained node/backend results"
    except Exception as error:
        record["error"] = f"{type(error).__name__}: {error}"
    record["elapsed_ms"] = (time.perf_counter() - started) * 1000
    # Materializing JSON evidence is deliberately outside both timed intervals.
    record["runtime"] = None if result is None else result.to_dict()
    reports = [report for client in clients for report in client.reports]
    record["backend_calls"] = sum(client.attempts for client in clients)
    record["completed_backend_reports"] = len(reports)
    record["backend_reports"] = [report.to_dict() for report in reports]
    record["backend_result_rows"] = sum(len(report.rows) for report in reports)
    record["backend_rows_json_bytes"] = sum(len(json.dumps(
        report.rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")) for report in reports)
    record["network_bytes"] = None  # JSON row encoding is not transport measurement.
    return record


def _summary(record: Mapping[str, Any]) -> dict[str, Any]:
    measurements = [row for row in record["attempts"] if row["phase"] == "measurement"]
    query_summaries = []
    for query_id in record["query_ids"]:
        methods = {}
        for strategy in STRATEGIES:
            rows = [row for row in measurements if row["query_id"] == query_id
                    and row["strategy"] == strategy]
            good = [row for row in rows if row.get("success")]
            methods[strategy] = {"attempted": len(rows), "successful": len(good),
                "failed_or_incomplete": len(rows) - len(good),
                "planned": record["measurement_rounds"]}
            if good:
                elapsed = [row["elapsed_ms"] for row in good]
                methods[strategy].update(median_ms=statistics.median(elapsed),
                    min_ms=min(elapsed), max_ms=max(elapsed),
                    backend_calls=sorted({row["backend_calls"] for row in good}),
                    backend_result_rows=sorted({row["backend_result_rows"] for row in good}),
                    backend_rows_json_bytes=sorted({row["backend_rows_json_bytes"] for row in good}),
                    answer_counts=sorted({len(row["answers"]) for row in good}))
        pairs = []
        for round_index in range(record["measurement_rounds"]):
            pair = [row for row in measurements if row["query_id"] == query_id
                    and row["round"] == round_index]
            if len(pair) == 2 and all(row.get("success") for row in pair):
                pairs.append(pair[0]["answers"] == pair[1]["answers"])
        complete = (len(pairs) == record["measurement_rounds"] and all(pairs))
        item: dict[str, Any] = {"query_id": query_id, "methods": methods,
            "complete_answer_equal_pairs": sum(pairs), "all_measurement_pairs_equal": complete}
        if complete:
            item["ratio_of_median_elapsed"] = (methods[STRATEGIES[0]]["median_ms"]
                                                  / methods[STRATEGIES[1]]["median_ms"])
        query_summaries.append(item)
    return {"queries": query_summaries, "inference": "descriptive only; repetitions are not independent queries"}


def run_comparison(programs: Mapping[str, FactAnswerProgram], *, neo4j: Any,
                   fuseki: Any, output_root: str | Path, measurement_rounds: int = 8,
                   warmup_rounds: int = 2, timeout_seconds: float = 600) -> dict[str, Any]:
    """Run a predeclared, alternating paired schedule; stop at the first failure.

    Each call remains bounded by the configured backend transport/server limits.
    The experiment deadline is checked between calls, not in-flight cancellation.
    Neither completed failures nor uncertain external calls are retried.
    """
    if not isinstance(programs, Mapping) or not 1 <= len(programs) <= 100:
        raise ValueError("Supply 1 to 100 predeclared programs")
    if any(not isinstance(key, str) or not key or not isinstance(value, FactAnswerProgram)
           for key, value in programs.items()):
        raise ValueError("Every query requires a nonempty ID and a compiled fact program")
    if type(measurement_rounds) is not int or not 2 <= measurement_rounds <= 100 or measurement_rounds % 2:
        raise ValueError("Use an even number of measurement rounds from 2 to 100")
    if type(warmup_rounds) is not int or not 0 <= warmup_rounds <= 10:
        raise ValueError("Warmup rounds must be an integer from 0 to 10")
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 3600:
        raise ValueError("A finite experiment deadline of at most one hour is required")
    frozen = {key: comparison_plans(value) for key, value in programs.items()}
    query_ids = tuple(programs)
    schedule = []
    for phase, count in (("warmup", warmup_rounds), ("measurement", measurement_rounds)):
        for round_index in range(count):
            # Rotate query order and balance AB/BA independently for every query.
            order = query_ids[round_index % len(query_ids):] + query_ids[:round_index % len(query_ids)]
            for query_id in order:
                methods = STRATEGIES if (round_index + query_ids.index(query_id)) % 2 == 0 else STRATEGIES[::-1]
                for strategy in methods:
                    schedule.append({"phase": phase, "round": round_index,
                                     "query_id": query_id, "strategy": strategy})
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=False)
    request = {"query_ids": query_ids, "queries": {k: v.query.to_dict() for k, v in programs.items()},
        "plans": {k: {s: p.to_dict() for s, p in plans.items()} for k, plans in frozen.items()},
        "max_rows": {k: v.max_rows for k, v in programs.items()}, "schedule": schedule,
        "measurement_rounds": measurement_rounds, "warmup_rounds": warmup_rounds,
        "timeout_seconds": timeout_seconds, "automatic_retries": 0, "paper_result": False,
        "timing": "scheduler dispatch through typed answer normalization; compilation, client/tool setup, recording and oracle checks excluded",
        "network_bytes_measured": False}
    request_bytes = (json.dumps(request, indent=2) + "\n").encode()
    (root / "request.json").write_bytes(request_bytes)
    record: dict[str, Any] = {"request_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "query_ids": query_ids, "measurement_rounds": measurement_rounds,
        "warmup_rounds": warmup_rounds, "planned_attempts": len(schedule),
        "success": False, "attempts": [], "paper_result": False}

    def save() -> None:
        (root / "result.json").write_text(json.dumps(record, indent=2) + "\n")

    save()
    started = time.monotonic()
    prior_answers: dict[str, Any] = {}
    for item in schedule:
        if time.monotonic() - started >= timeout_seconds:
            record["error"] = "Experiment deadline reached before next scheduled execution"
            break
        row = {**item, "success": False, "status": "started"}
        record["attempts"].append(row)
        save()  # Record the external action before dispatch; never reuse this root.
        row.update(measure_plan(frozen[item["query_id"]][item["strategy"]],
            max_rows=programs[item["query_id"]].max_rows, neo4j=neo4j, fuseki=fuseki))
        row["status"] = "completed" if row["success"] else "failed"
        if row["success"]:
            expected = prior_answers.setdefault(item["query_id"], row["answers"])
            if row["answers"] != expected:
                row["success"] = False
                row["status"] = "answer_mismatch"
                row["error"] = "Complete answers differ across strategies or repetitions"
        save()
        if not row["success"]:
            record["error"] = "Stopped after a failed execution or answer mismatch; no retries"
            break
    else:
        record["success"] = True
    record["not_run"] = len(schedule) - len(record["attempts"])
    record["summary"] = _summary(record)
    save()
    return record
