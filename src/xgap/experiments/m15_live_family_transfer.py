"""Execute the F2C5 family-local memory transfer development protocol.

Seed tasks measure both exact physical strategies and may commit only after
successful exact-answer validation.  Held-out instances select from one
reopened, frozen seed snapshot, execute the selected plan first, and may run
the other exact strategy only as a clearly separated evaluation shadow.  The
shadow never affects selection or memory.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from xgap.agent import JsonlMemoryStore
from xgap.backends.protocol import BackendClient
from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_family_memory import (
    M15FamilyPlanMemory,
    M15FamilyPlanOutcome,
    build_m15_family_memory_context,
    build_m15_family_plan_observation,
    build_m15_family_query_features,
    select_m15_family_plan,
)
from xgap.experiments.m15_live_adaptive import RecordingBackendPlugin
from xgap.experiments.m15_parameterized_federation import (
    build_m15_parameterized_plan_candidates,
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_parameterized_workload import (
    M15ParameterizedWorkloadBundle,
    load_m15_parameterized_workload_bundle,
)
from xgap.runtime import FederatedPlanCandidate, FederatedRunResult, FederatedScheduler
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


LIVE_FAMILY_TRANSFER_SCHEMA_VERSION = "m15-f2c5-live-family-transfer-v1"
FAMILY_TRANSFER_TASK_STREAM_SCHEMA_VERSION = (
    "m15-f2c5-family-transfer-task-stream-v1"
)
FAMILY_TRANSFER_METHOD_NAMESPACE = "family_knn_development"
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class M15LiveFamilyTransferRecord:
    run_id: str
    run_root: Path
    success: bool
    status_path: Path
    manifest_path: Path
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_root": str(self.run_root),
            "success": self.success,
            "status_path": str(self.status_path),
            "manifest_path": str(self.manifest_path),
            "error": self.error,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_state(repo_root: Path) -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        return {"commit": commit, "clean": not bool(dirty)}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"commit": None, "clean": None, "error": str(exc)}


def build_m15_family_transfer_task_stream(
    workload: M15ParameterizedWorkloadBundle | str | Path,
) -> dict[str, Any]:
    """Freeze seed commits and held-out read visibility before execution."""

    bundle = load_m15_parameterized_workload_bundle(
        workload.root
        if isinstance(workload, M15ParameterizedWorkloadBundle)
        else workload
    )
    seed_task_ids: list[str] = []
    tasks: list[dict[str, Any]] = []
    for sequence_index, record in enumerate(bundle.manifest["instances"], start=1):
        task_id = f"m15-f2c5-task-{sequence_index:02d}"
        split_role = record["split_role"]
        if split_role == "seed":
            seed_task_ids.append(task_id)
            memory = {
                "read_enabled": False,
                "eligible_predecessor_task_ids": [],
                "write_enabled": True,
                "write_condition": "both_strategies_successful_and_exact",
            }
            execution = "measure_both_exact_strategies"
        else:
            memory = {
                "read_enabled": True,
                "eligible_predecessor_task_ids": list(seed_task_ids),
                "write_enabled": False,
                "write_condition": None,
            }
            execution = "selected_first_then_evaluation_shadow"
        tasks.append(
            {
                "sequence_index": sequence_index,
                "task_id": task_id,
                "query_id": record["query_id"],
                "split_role": split_role,
                "family_compatibility_sha256": bundle.manifest[
                    "family_compatibility_sha256"
                ],
                "query_instance_sha256": record["query_instance_sha256"],
                "semantic_deviation": 0,
                "execution_protocol": execution,
                "memory": memory,
            }
        )
    expected_seed_ids = tuple(
        task["task_id"] for task in tasks if task["split_role"] == "seed"
    )
    heldout = [task for task in tasks if task["split_role"] == "heldout_instance"]
    if not expected_seed_ids or not heldout:
        raise ValueError("family transfer stream requires seed and held-out tasks")
    if any(
        tuple(task["memory"]["eligible_predecessor_task_ids"])
        != expected_seed_ids
        for task in heldout
    ):
        raise ValueError("held-out tasks must share one frozen seed predecessor set")
    identity = {
        "schema_version": FAMILY_TRANSFER_TASK_STREAM_SCHEMA_VERSION,
        "workload_id": bundle.spec.workload_id,
        "bundle_content_sha256": bundle.manifest["bundle_content_sha256"],
        "family_compatibility_sha256": bundle.manifest[
            "family_compatibility_sha256"
        ],
        "method_namespace": FAMILY_TRANSFER_METHOD_NAMESPACE,
        "task_order": "declared_seed_then_heldout_instance",
        "tasks": tasks,
        "heldout_snapshot_policy": "freeze_once_after_all_exact_seed_commits",
        "evaluation_writes_allowed": False,
        "cross_family_reads_allowed": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    return {**identity, "task_stream_sha256": content_hash(identity)}


def _backend_tool(
    clients: Mapping[str, BackendClient],
    events: list[dict[str, Any]],
) -> BackendInvokeTool:
    plugins = BackendPluginRegistry()
    for backend_id in ("neo4j", "fuseki"):
        plugins.register(
            RecordingBackendPlugin(
                NativeBackendPlugin(backend_id, clients[backend_id]),
                events,
            )
        )
    return BackendInvokeTool(plugins)


def _execute_candidate(
    candidate: FederatedPlanCandidate,
    *,
    clients: Mapping[str, BackendClient],
    goal_id: str,
    query_id: str,
    execution_role: str,
) -> tuple[FederatedRunResult, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    result = FederatedScheduler(_backend_tool(clients, events)).execute(
        candidate.plan,
        goal_id=goal_id,
    )
    strategy = str(candidate.plan.metadata["physical_strategy"])
    for sequence, event in enumerate(events, start=1):
        event["sequence"] = sequence
        event["query_id"] = query_id
        event["physical_strategy"] = strategy
        event["execution_role"] = execution_role
    return result, events


def _candidate_by_strategy(
    candidates: tuple[FederatedPlanCandidate, ...],
    strategy_id: str,
) -> FederatedPlanCandidate:
    matches = tuple(
        candidate
        for candidate in candidates
        if candidate.plan.metadata.get("physical_strategy") == strategy_id
    )
    if len(matches) != 1:
        raise ValueError(
            f"expected one parameterized plan for strategy '{strategy_id}'"
        )
    return matches[0]


def _winner(outcomes: Mapping[str, FederatedRunResult]) -> str:
    return min(
        outcomes,
        key=lambda strategy: (
            outcomes[strategy].elapsed_ms,
            outcomes[strategy].total_bytes_moved,
            strategy,
        ),
    )


def run_m15_live_family_transfer(
    *,
    workload_bundle: M15ParameterizedWorkloadBundle | str | Path,
    clients: Mapping[str, BackendClient],
    runtime_compatibility_sha256: str,
    output_root: str | Path,
    run_id: str = "family-transfer-run",
    repo_root: str | Path | None = None,
    evaluate_shadow: bool = True,
) -> M15LiveFamilyTransferRecord:
    """Run seed calibration and held-out family-local plan selection once."""

    root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else Path(__file__).resolve().parents[3]
    )
    bundle = load_m15_parameterized_workload_bundle(
        workload_bundle.root
        if isinstance(workload_bundle, M15ParameterizedWorkloadBundle)
        else workload_bundle
    )
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("run_id contains unsupported characters")
    if set(clients) != {"neo4j", "fuseki"}:
        raise ValueError("family transfer requires exactly neo4j and fuseki clients")
    if not isinstance(evaluate_shadow, bool):
        raise ValueError("evaluate_shadow must be boolean")
    destination = Path(output_root)
    if not destination.is_absolute():
        destination = root / destination
    run_root = destination.resolve() / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    status_path = run_root / "run_status.json"
    manifest_path = run_root / "run_manifest.json"
    started_at = _now()
    _write_json(
        status_path,
        {
            "schema_version": LIVE_FAMILY_TRANSFER_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "running",
            "started_at": started_at,
        },
    )

    stream = build_m15_family_transfer_task_stream(bundle)
    context = build_m15_family_memory_context(
        bundle,
        method_namespace=FAMILY_TRANSFER_METHOD_NAMESPACE,
        runtime_compatibility_sha256=runtime_compatibility_sha256,
    )
    _write_json(run_root / "task_stream.json", stream)
    _write_json(run_root / "memory_context.json", context.to_dict())
    memory_path = run_root / "family_memory.jsonl"
    memory = M15FamilyPlanMemory(JsonlMemoryStore(memory_path), context)
    health: dict[str, Any] = {}
    events_by_execution: dict[str, list[dict[str, Any]]] = {}
    seed_results: dict[str, dict[str, Any]] = {}
    heldout_results: dict[str, dict[str, Any]] = {}
    committed_task_ids: list[str] = []
    memory_view = None
    checks: dict[str, bool] = {}
    error: str | None = None
    seed_plan_runs = 0
    heldout_online_plan_runs = 0
    evaluation_shadow_plan_runs = 0
    try:
        for backend_id in ("neo4j", "fuseki"):
            health[backend_id] = clients[backend_id].healthcheck().to_dict()
        _write_json(run_root / "health.json", health)
        unavailable = [
            backend_id for backend_id, status in health.items() if not status["ok"]
        ]
        if unavailable:
            raise RuntimeError(
                f"backend healthcheck failed: {', '.join(unavailable)}"
            )

        seed_tasks = [
            task for task in stream["tasks"] if task["split_role"] == "seed"
        ]
        heldout_tasks = [
            task
            for task in stream["tasks"]
            if task["split_role"] == "heldout_instance"
        ]
        for task in seed_tasks:
            query_id = task["query_id"]
            features = build_m15_family_query_features(
                bundle,
                query_id=query_id,
                context=context,
            )
            candidates = build_m15_parameterized_plan_candidates(
                bundle,
                query_id=query_id,
            )
            runs: dict[str, FederatedRunResult] = {}
            for candidate in candidates:
                strategy = str(candidate.plan.metadata["physical_strategy"])
                result, events = _execute_candidate(
                    candidate,
                    clients=clients,
                    goal_id=f"{task['task_id']}:seed:{strategy}",
                    query_id=query_id,
                    execution_role="memory_seed_measurement",
                )
                seed_plan_runs += 1
                runs[strategy] = result
                events_by_execution[f"{task['task_id']}:{strategy}"] = events
                _write_json(
                    run_root / "tasks" / query_id / f"seed-{strategy}.json",
                    result.to_dict(),
                )
                if not result.success:
                    raise RuntimeError(
                        f"seed query '{query_id}' strategy '{strategy}' failed"
                    )

            # The oracle becomes visible only after both plans and features exist.
            expected_rows = tuple(
                load_m15_parameterized_instance(bundle, query_id)["final_oracle"]
            )
            exact_by_strategy = {
                strategy: result.final_rows == expected_rows
                for strategy, result in runs.items()
            }
            if not all(exact_by_strategy.values()):
                raise RuntimeError(
                    f"seed query '{query_id}' returned a non-oracle answer"
                )
            outcomes = tuple(
                M15FamilyPlanOutcome.from_run(strategy_id=strategy, run=result)
                for strategy, result in sorted(runs.items())
            )
            observation = build_m15_family_plan_observation(
                context=context,
                features=features,
                task_id=task["task_id"],
                sequence_index=task["sequence_index"],
                query_id=query_id,
                split_role=task["split_role"],
                outcomes=outcomes,
                execution_success=all(result.success for result in runs.values()),
                exact_answer=all(exact_by_strategy.values()),
            )
            memory.commit(
                observation,
                source=f"{task['task_id']}/post-execution-exact-validation",
            )
            committed_task_ids.append(task["task_id"])
            seed_results[query_id] = {
                "task": task,
                "features": features.to_dict(),
                "outcomes": [item.to_dict() for item in outcomes],
                "exact_by_strategy": exact_by_strategy,
                "memory_observation_sha256": observation.observation_sha256,
            }

        # Reopen the append-only store, then freeze once for every held-out task.
        memory = M15FamilyPlanMemory(JsonlMemoryStore(memory_path), context)
        memory_view = memory.freeze(
            current_sequence_index=heldout_tasks[0]["sequence_index"],
            eligible_task_ids=tuple(committed_task_ids),
        )
        _write_json(run_root / "frozen_memory_view.json", memory_view.to_dict())
        checks["memory_reopened_after_seed_commits"] = (
            len(memory_view.observations) == len(seed_tasks)
        )
        checks["one_frozen_view_for_all_heldout_tasks"] = True

        for task in heldout_tasks:
            query_id = task["query_id"]
            features = build_m15_family_query_features(
                bundle,
                query_id=query_id,
                context=context,
            )
            candidates = build_m15_parameterized_plan_candidates(
                bundle,
                query_id=query_id,
            )
            selection = select_m15_family_plan(
                context=context,
                features=features,
                memory_view=memory_view,
            )
            _write_json(
                run_root / "tasks" / query_id / "selection.json",
                selection.to_dict(),
            )
            selected_candidate = _candidate_by_strategy(
                candidates,
                selection.selected_strategy_id,
            )
            selected_run, selected_events = _execute_candidate(
                selected_candidate,
                clients=clients,
                goal_id=f"{task['task_id']}:selected",
                query_id=query_id,
                execution_role="online_selected_plan",
            )
            heldout_online_plan_runs += 1
            events_by_execution[f"{task['task_id']}:selected"] = selected_events
            _write_json(
                run_root / "tasks" / query_id / "selected_run.json",
                selected_run.to_dict(),
            )
            if not selected_run.success:
                raise RuntimeError(f"held-out query '{query_id}' selected plan failed")

            # Correctness validation is post-decision and cannot alter the choice.
            expected_rows = tuple(
                load_m15_parameterized_instance(bundle, query_id)["final_oracle"]
            )
            selected_exact = selected_run.final_rows == expected_rows
            if not selected_exact:
                raise RuntimeError(
                    f"held-out query '{query_id}' selected plan was not exact"
                )

            observed_runs = {selection.selected_strategy_id: selected_run}
            shadow_payload: dict[str, Any] = {}
            if evaluate_shadow:
                for candidate in candidates:
                    strategy = str(candidate.plan.metadata["physical_strategy"])
                    if strategy == selection.selected_strategy_id:
                        continue
                    shadow, shadow_events = _execute_candidate(
                        candidate,
                        clients=clients,
                        goal_id=f"{task['task_id']}:evaluation-shadow:{strategy}",
                        query_id=query_id,
                        execution_role="evaluation_shadow_after_selection",
                    )
                    evaluation_shadow_plan_runs += 1
                    observed_runs[strategy] = shadow
                    shadow_payload[strategy] = shadow.to_dict()
                    events_by_execution[
                        f"{task['task_id']}:evaluation-shadow:{strategy}"
                    ] = shadow_events
                    _write_json(
                        run_root / "tasks" / query_id / f"shadow-{strategy}.json",
                        shadow.to_dict(),
                    )
                    if not shadow.success or shadow.final_rows != expected_rows:
                        raise RuntimeError(
                            f"held-out query '{query_id}' evaluation shadow failed "
                            "exact validation"
                        )
            observed_winner = _winner(observed_runs)
            best_elapsed = min(item.elapsed_ms for item in observed_runs.values())
            best_bytes = min(
                item.total_bytes_moved for item in observed_runs.values()
            )
            heldout_results[query_id] = {
                "task": task,
                "features": features.to_dict(),
                "memory_view_sha256": memory_view.view_sha256,
                "selection": selection.to_dict(),
                "selected_run": selected_run.to_dict(),
                "selected_exact": selected_exact,
                "evaluation_shadow_runs": shadow_payload,
                "evaluation_shadow_influenced_selection": False,
                "memory_write_after_evaluation": False,
                "observed_winner": observed_winner,
                "selected_observed_winner": (
                    selection.selected_strategy_id == observed_winner
                ),
                "observed_elapsed_regret_ms": (
                    selected_run.elapsed_ms - best_elapsed
                ),
                "observed_bytes_regret": (
                    selected_run.total_bytes_moved - best_bytes
                ),
                "order_confounded_development_diagnostic": evaluate_shadow,
            }
            _write_json(
                run_root / "tasks" / query_id / "heldout_result.json",
                heldout_results[query_id],
            )

        checks["all_seed_tasks_committed_once"] = (
            committed_task_ids == [task["task_id"] for task in seed_tasks]
            and len(memory_path.read_text(encoding="utf-8").splitlines())
            == len(seed_tasks)
        )
        checks["heldout_tasks_used_frozen_seed_view"] = all(
            result["memory_view_sha256"] == memory_view.view_sha256
            for result in heldout_results.values()
        )
        checks["heldout_tasks_did_not_write_memory"] = (
            len(memory_path.read_text(encoding="utf-8").splitlines())
            == len(seed_tasks)
        )
        checks["all_selected_answers_exact"] = all(
            result["selected_exact"] for result in heldout_results.values()
        )
        checks["selection_used_no_oracle_input"] = all(
            result["selection"]["oracle_inputs"] == []
            for result in heldout_results.values()
        )
        checks["evaluation_shadow_never_influenced_selection"] = all(
            not result["evaluation_shadow_influenced_selection"]
            for result in heldout_results.values()
        )
        checks["all_plans_zero_semantic_deviation"] = all(
            task["semantic_deviation"] == 0 for task in stream["tasks"]
        )
        validation = {"passed": all(checks.values()), "checks": checks}
        _write_json(run_root / "validation.json", validation)
        if not validation["passed"]:
            raise RuntimeError("live family-transfer validation failed")
    except Exception as exc:  # Preserve the first external failure; never retry.
        error = str(exc)
        if not (run_root / "health.json").exists():
            _write_json(run_root / "health.json", health)

    _write_json(
        run_root / "backend_invocations.json",
        {
            "events_by_execution": events_by_execution,
            "total_tool_invocations": sum(
                len(events) for events in events_by_execution.values()
            ),
            "automatic_retries": 0,
        },
    )
    ended_at = _now()
    success = error is None
    _write_json(
        status_path,
        {
            "schema_version": LIVE_FAMILY_TRANSFER_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    selected_winner_count = sum(
        result["selected_observed_winner"] for result in heldout_results.values()
    )
    _write_json(
        manifest_path,
        {
            "schema_version": LIVE_FAMILY_TRANSFER_SCHEMA_VERSION,
            "run_id": run_id,
            "dataset_id": f"m15_f2c:{bundle.spec.workload_id}",
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
            "git": _git_state(root),
            "environment": {
                "hostname": platform.node(),
                "python": sys.version,
                "platform": platform.platform(),
            },
            "input_sha256": {
                f"bundle:{bundle.spec.workload_id}/manifest.json": _sha256_file(
                    bundle.root / "manifest.json"
                )
            },
            "workload_bundle": dict(bundle.manifest),
            "task_stream": stream,
            "memory_context": context.to_dict(),
            "frozen_memory_view": (
                memory_view.to_dict() if memory_view is not None else None
            ),
            "backend_health": health,
            "seed_results": seed_results,
            "heldout_results": heldout_results,
            "summary": {
                "seed_task_count": len(seed_results),
                "heldout_task_count": len(heldout_results),
                "memory_commit_count": len(committed_task_ids),
                "seed_plan_runs": seed_plan_runs,
                "heldout_online_plan_runs": heldout_online_plan_runs,
                "evaluation_shadow_plan_runs": evaluation_shadow_plan_runs,
                "online_remote_calls": sum(
                    len(events)
                    for key, events in events_by_execution.items()
                    if ":selected" in key
                ),
                "calibration_remote_calls": sum(
                    len(events)
                    for key, events in events_by_execution.items()
                    if ":selected" not in key and ":evaluation-shadow:" not in key
                ),
                "evaluation_shadow_remote_calls": sum(
                    len(events)
                    for key, events in events_by_execution.items()
                    if ":evaluation-shadow:" in key
                ),
                "selected_observed_winner_count": selected_winner_count,
                "observed_selection_count": len(heldout_results),
            },
            "validation": {
                "passed": success and bool(checks) and all(checks.values()),
                "checks": checks,
            },
            "evidence_class": "live_family_local_transfer_development_gate",
            "answer_oracle_used_for_feature_or_selection": False,
            "answer_oracle_used_for_post_execution_validation": True,
            "evaluation_shadow_enabled": evaluate_shadow,
            "evaluation_shadow_influenced_selection": False,
            "memory_enabled": True,
            "memory_transfer_scope": "same_method_same_family_same_runtime",
            "cross_family_transfer_enabled": False,
            "automatic_retries": 0,
            "llm_calls_made": 0,
            "ontology_calls_made": 0,
            "paper_result": False,
            "paper_blockers": [
                "development_knn_model_not_frozen_for_paper",
                "single_query_family_only",
                "four_seed_two_heldout_instances_only",
                "evaluation_shadow_order_is_not_counterbalanced",
                "inferential_analysis_not_preregistered",
            ],
            "artifacts": sorted(path.name for path in run_root.iterdir()),
        },
    )
    return M15LiveFamilyTransferRecord(
        run_id=run_id,
        run_root=run_root,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        error=error,
    )
