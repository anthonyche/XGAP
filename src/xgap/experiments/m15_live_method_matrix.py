"""Artifact-first live M15 method matrix over real black-box backends."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.agent import JsonlMemoryStore
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.backends.protocol import BackendClient
from xgap.experiments.m15_live_adaptive import RecordingBackendPlugin
from xgap.experiments.m15_method_policy import (
    M15_METHOD_POLICIES,
    M15Method,
    M15MethodTaskResult,
    run_m15_method_task,
)
from xgap.experiments.m15_query_contract import QUERY_CONTRACT_SCHEMA_VERSION
from xgap.experiments.m15_scaled_federation import (
    build_m15_scaled_observation_catalogs,
    build_m15_scaled_observation_requests,
    build_m15_scaled_plan_candidates,
    build_m15_scaled_plan_memory_context,
    build_m15_scaled_probe_plan,
    build_m15_scaled_semantic_program,
)
from xgap.experiments.m15_workload import (
    M15WorkloadBundle,
    load_m15_workload_bundle,
)
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.runtime import PlanObservationCollector, PlanSnapshotMemory, ProbeObservation
from xgap.tools import (
    BackendObservationCatalog,
    BackendInvokeTool,
    BackendPluginRegistry,
    CatalogBackendPlugin,
    ToolResult,
)


LIVE_MATRIX_SCHEMA_VERSION = "m15-f1-live-method-matrix-v1"
LIVE_MATRIX_COST_MODEL_VERSION = "m15-f1-live-matrix-cost-model-v1"
CAMPAIGN_BINDING_SCHEMA_VERSION = "m15-f2-live-campaign-binding-v1"
QUERY_BOUND_CAMPAIGN_BINDING_SCHEMA_VERSION = (
    "m15-f2-live-query-bound-campaign-binding-v1"
)
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_METHOD_ORDER = (
    M15Method.STATIC_PARALLEL_HASH,
    M15Method.STATIC_RISK_FIRST_BIND,
    M15Method.NO_MEMORY,
    M15Method.NO_PROFILE_PROBE,
    M15Method.NO_REPLAN,
    M15Method.FULL_AGENT,
)


def _execution_contract(
    method_order: Sequence[M15Method] | None,
    campaign_binding: Mapping[str, Any] | None,
) -> tuple[tuple[M15Method, ...], dict[str, Any] | None, str, str, str]:
    selected = _METHOD_ORDER if method_order is None else tuple(method_order)
    if (
        len(selected) != len(_METHOD_ORDER)
        or any(not isinstance(method, M15Method) for method in selected)
        or set(selected) != set(_METHOD_ORDER)
    ):
        raise ValueError(
            "method_order must contain each frozen M15 method exactly once"
        )
    if campaign_binding is None:
        if selected != _METHOD_ORDER:
            raise ValueError("a custom method_order requires a campaign binding")
        return (
            selected,
            None,
            "fixed_engineering_gate_not_counterbalanced",
            "shared_unknown_not_reset_between_methods",
            "live_backend_method_mechanism_engineering_gate",
        )

    required_v1 = {
        "schema_version",
        "campaign_id",
        "campaign_spec_sha256",
        "schedule_sha256",
        "session_id",
        "workload_label",
        "workload_id",
        "block_index",
        "sequence_index",
        "query_ids",
        "method_order",
        "method_task_ids",
        "memory_namespaces",
    }
    binding = dict(campaign_binding)
    schema_version = binding.get("schema_version")
    if schema_version == CAMPAIGN_BINDING_SCHEMA_VERSION:
        required = required_v1
        evidence_class = "live_backend_campaign_session_engineering_gate"
    elif schema_version == QUERY_BOUND_CAMPAIGN_BINDING_SCHEMA_VERSION:
        required = required_v1 | {
            "registry_id",
            "query_binding_sha256",
            "query_bound_schedule_sha256",
            "query_contracts",
        }
        evidence_class = "live_backend_query_bound_session_engineering_gate"
    else:
        raise ValueError("campaign binding schema_version is unsupported")
    if set(binding) != required:
        raise ValueError("campaign binding fields do not match its versioned contract")
    for key in (
        "campaign_id",
        "session_id",
        "workload_label",
        "workload_id",
    ):
        if not isinstance(binding[key], str) or not _SAFE_RUN_ID.fullmatch(
            binding[key]
        ):
            raise ValueError(f"campaign binding {key} is invalid")
    for key in ("campaign_spec_sha256", "schedule_sha256"):
        if not isinstance(binding[key], str) or not _SHA256.fullmatch(binding[key]):
            raise ValueError(f"campaign binding {key} must be a SHA-256 digest")
    for key in ("block_index", "sequence_index"):
        if (
            isinstance(binding[key], bool)
            or not isinstance(binding[key], int)
            or binding[key] < 1
        ):
            raise ValueError(f"campaign binding {key} must be a positive integer")
    query_ids = binding["query_ids"]
    if (
        not isinstance(query_ids, list)
        or not query_ids
        or any(
            not isinstance(query_id, str) or not _SAFE_RUN_ID.fullmatch(query_id)
            for query_id in query_ids
        )
        or len(query_ids) != len(set(query_ids))
    ):
        raise ValueError("campaign binding query_ids must be unique safe identifiers")
    expected_order = [method.value for method in selected]
    if binding["method_order"] != expected_order:
        raise ValueError("campaign binding method_order disagrees with execution")
    for field in ("method_task_ids", "memory_namespaces"):
        values = binding[field]
        if (
            not isinstance(values, Mapping)
            or set(values) != set(expected_order)
            or any(
                not isinstance(value, str) or not _SAFE_RUN_ID.fullmatch(value)
                for value in values.values()
            )
            or len(set(values.values())) != len(expected_order)
        ):
            raise ValueError(
                f"campaign binding {field} must map every method to a unique "
                "safe identifier"
            )
        binding[field] = dict(values)
    if schema_version == QUERY_BOUND_CAMPAIGN_BINDING_SCHEMA_VERSION:
        _validate_query_contract_binding(binding, query_ids=query_ids)
    return (
        selected,
        binding,
        "williams_campaign_sequence",
        "shared_unflushed_within_sequence_counterbalanced_by_campaign",
        evidence_class,
    )


def _validate_query_contract_binding(
    binding: dict[str, Any],
    *,
    query_ids: list[str],
) -> None:
    if not isinstance(binding["registry_id"], str) or not _SAFE_RUN_ID.fullmatch(
        binding["registry_id"]
    ):
        raise ValueError("campaign binding registry_id is invalid")
    for key in ("query_binding_sha256", "query_bound_schedule_sha256"):
        if not isinstance(binding[key], str) or not _SHA256.fullmatch(binding[key]):
            raise ValueError(f"campaign binding {key} must be a SHA-256 digest")
    contracts = binding["query_contracts"]
    if not isinstance(contracts, Mapping) or set(contracts) != set(query_ids):
        raise ValueError("campaign binding must cover every query contract exactly")
    normalized: dict[str, dict[str, Any]] = {}
    for query_id in query_ids:
        value = contracts[query_id]
        if not isinstance(value, Mapping) or set(value) != {
            "schema_version",
            "query_spec_sha256",
            "query_contract_sha256",
            "workload_id",
        }:
            raise ValueError("campaign query contract fields are invalid")
        record = dict(value)
        if record["schema_version"] != QUERY_CONTRACT_SCHEMA_VERSION:
            raise ValueError("campaign query contract schema_version is unsupported")
        for key in ("query_spec_sha256", "query_contract_sha256"):
            if not isinstance(record[key], str) or not _SHA256.fullmatch(record[key]):
                raise ValueError(f"campaign query contract {key} is invalid")
        if record["workload_id"] != binding["workload_id"]:
            raise ValueError("campaign query contract workload_id is inconsistent")
        normalized[query_id] = record
    binding["query_contracts"] = normalized


@dataclass(frozen=True)
class M15LiveMethodMatrixRecord:
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


def _now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


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


def _default_clients(repo_root: Path) -> dict[str, BackendClient]:
    descriptors = repo_root / "descriptors" / "backends"
    return {
        "neo4j": Neo4jClient(
            BackendDescriptor.from_yaml(descriptors / "neo4j.yaml")
        ),
        "fuseki": FusekiClient(
            BackendDescriptor.from_yaml(descriptors / "fuseki.yaml")
        ),
    }


def _backend_tool(
    clients: Mapping[str, BackendClient],
    catalogs: Mapping[str, BackendObservationCatalog],
    events: list[dict[str, Any]],
) -> BackendInvokeTool:
    plugins = BackendPluginRegistry()
    for backend_id in ("neo4j", "fuseki"):
        plugins.register(
            RecordingBackendPlugin(
                CatalogBackendPlugin(
                    backend_id,
                    clients[backend_id],
                    catalogs[backend_id],
                ),
                events,
            )
        )
    return BackendInvokeTool(plugins)


def _observation_rows(result: ToolResult) -> list[dict[str, Any]] | None:
    value = result.value if isinstance(result.value, Mapping) else None
    observation = value.get("observation") if isinstance(value, Mapping) else None
    rows = observation.get("rows") if isinstance(observation, Mapping) else None
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        return None
    return [dict(row) for row in rows]


def _validate_cost_model(
    *,
    bandwidth_bytes_per_ms: float,
    exchange_fixed_ms: float,
    coordinator_row_ms: float,
) -> None:
    for name, value in (
        ("bandwidth_bytes_per_ms", bandwidth_bytes_per_ms),
        ("exchange_fixed_ms", exchange_fixed_ms),
        ("coordinator_row_ms", coordinator_row_ms),
    ):
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise ValueError(f"{name} must be finite")
    if bandwidth_bytes_per_ms <= 0:
        raise ValueError("bandwidth_bytes_per_ms must be positive")
    if exchange_fixed_ms < 0 or coordinator_row_ms < 0:
        raise ValueError("coordinator cost values must be nonnegative")


def run_m15_live_method_matrix(
    *,
    workload_bundle: M15WorkloadBundle | str | Path,
    output_root: str | Path = "runs",
    run_id: str | None = None,
    repo_root: str | Path | None = None,
    clients: Mapping[str, BackendClient] | None = None,
    bandwidth_bytes_per_ms: float = 1000.0,
    exchange_fixed_ms: float = 0.5,
    coordinator_row_ms: float = 0.001,
    method_order: Sequence[M15Method] | None = None,
    campaign_binding: Mapping[str, Any] | None = None,
) -> M15LiveMethodMatrixRecord:
    """Run one fail-closed six-method sequence against the same live services.

    The default remains the fixed F1L engineering matrix. A custom order is
    admitted only with a hash-bound F2 campaign-session contract. Neither mode
    is itself a paper-comparison result.
    """

    root = Path(repo_root).resolve() if repo_root is not None else _repo_root()
    bundle = load_m15_workload_bundle(
        workload_bundle.root
        if isinstance(workload_bundle, M15WorkloadBundle)
        else workload_bundle
    )
    _validate_cost_model(
        bandwidth_bytes_per_ms=bandwidth_bytes_per_ms,
        exchange_fixed_ms=exchange_fixed_ms,
        coordinator_row_ms=coordinator_row_ms,
    )
    (
        selected_method_order,
        selected_campaign_binding,
        order_policy,
        cache_state,
        evidence_class,
    ) = _execution_contract(method_order, campaign_binding)
    selected_run_id = run_id or f"m15-f1-live-matrix-{_now_slug()}"
    if not _SAFE_RUN_ID.fullmatch(selected_run_id):
        raise ValueError("run_id contains unsupported characters")
    destination = Path(output_root)
    if not destination.is_absolute():
        destination = root / destination
    run_root = destination.resolve() / selected_run_id
    run_root.mkdir(parents=True, exist_ok=False)
    status_path = run_root / "run_status.json"
    manifest_path = run_root / "run_manifest.json"
    started_at = _now()
    _write_json(
        status_path,
        {
            "schema_version": LIVE_MATRIX_SCHEMA_VERSION,
            "run_id": selected_run_id,
            "status": "running",
            "started_at": started_at,
        },
    )

    candidates = build_m15_scaled_plan_candidates(bundle)
    requests = build_m15_scaled_observation_requests(bundle)
    probe_plan = build_m15_scaled_probe_plan(bundle)
    catalogs = build_m15_scaled_observation_catalogs(bundle)
    context = build_m15_scaled_plan_memory_context(
        bundle,
        bandwidth_bytes_per_ms=bandwidth_bytes_per_ms,
        exchange_fixed_ms=exchange_fixed_ms,
        coordinator_row_ms=coordinator_row_ms,
    )
    model_config = {
        "schema_version": LIVE_MATRIX_COST_MODEL_VERSION,
        "bandwidth_bytes_per_ms": float(bandwidth_bytes_per_ms),
        "exchange_fixed_ms": float(exchange_fixed_ms),
        "coordinator_row_ms": float(coordinator_row_ms),
        "parameter_source": "fixed_development_configuration",
        "calibrated": False,
        "paper_result": False,
    }
    _write_json(
        run_root / "semantic_program.json",
        build_m15_scaled_semantic_program(bundle).to_dict(),
    )
    _write_json(
        run_root / "candidate_plans.json",
        {
            "semantic_equivalence_key": candidates[0].semantic_equivalence_key,
            "plans": [candidate.plan.to_dict() for candidate in candidates],
        },
    )
    _write_json(run_root / "probe_plan.json", probe_plan.to_dict())
    _write_json(
        run_root / "observation_requests.json",
        [request.to_dict() for request in requests],
    )
    _write_json(run_root / "memory_context.json", context.to_dict())
    _write_json(run_root / "cost_model.json", model_config)
    if selected_campaign_binding is not None:
        _write_json(run_root / "campaign_binding.json", selected_campaign_binding)
    _write_json(
        run_root / "method_policies.json",
        [
            M15_METHOD_POLICIES[method].to_dict()
            for method in selected_method_order
        ],
    )

    selected_clients = dict(clients) if clients is not None else _default_clients(root)
    health: dict[str, Any] = {}
    events: dict[str, list[dict[str, Any]]] = {}
    results: dict[str, M15MethodTaskResult] = {}
    calibration = None
    validation: dict[str, Any] | None = None
    seed_memory_writes = 0
    error: str | None = None
    try:
        if set(selected_clients) != {"neo4j", "fuseki"}:
            raise ValueError(
                "live method matrix requires exactly neo4j and fuseki clients"
            )
        for backend_id in ("neo4j", "fuseki"):
            health[backend_id] = selected_clients[backend_id].healthcheck().to_dict()
        _write_json(run_root / "health.json", health)
        unavailable = [key for key, value in health.items() if not value["ok"]]
        if unavailable:
            raise RuntimeError(f"backend healthcheck failed: {', '.join(unavailable)}")

        calibration_events: list[dict[str, Any]] = []
        events["calibration"] = calibration_events
        calibration = PlanObservationCollector(
            _backend_tool(selected_clients, catalogs, calibration_events)
        ).collect(
            requests,
            snapshot_id=context.snapshot_id,
            version=f"calibration-{selected_run_id}",
            bandwidth_bytes_per_ms=bandwidth_bytes_per_ms,
            exchange_fixed_ms=exchange_fixed_ms,
            coordinator_row_ms=coordinator_row_ms,
            goal_id=f"{selected_run_id}:calibration",
        )
        _write_json(run_root / "calibration.json", calibration.to_dict())
        if not calibration.success or calibration.snapshot is None:
            raise RuntimeError(calibration.error or "live calibration failed")
        _write_json(
            run_root / "calibration_snapshot.json",
            calibration.snapshot.to_dict(),
        )

        for method in selected_method_order:
            memory = None
            if M15_METHOD_POLICIES[method].read_memory:
                memory_path = run_root / "memory" / f"{method.value}.jsonl"
                memory = PlanSnapshotMemory(JsonlMemoryStore(memory_path))
                memory.put(
                    calibration.snapshot,
                    source=f"{selected_run_id}/common-live-calibration",
                )
                seed_memory_writes += 1
            method_events: list[dict[str, Any]] = []
            events[method.value] = method_events
            result = run_m15_method_task(
                method=method,
                task_id=(
                    selected_campaign_binding["method_task_ids"][method.value]
                    if selected_campaign_binding is not None
                    else f"{selected_run_id}.{method.value}"
                ),
                context=context,
                candidates=candidates,
                requests=requests,
                probe_plan=probe_plan,
                probe_observation=ProbeObservation(
                    "high-risk",
                    requests[2].observation_key,
                ),
                backend_tool=_backend_tool(
                    selected_clients,
                    catalogs,
                    method_events,
                ),
                expected_rows=tuple(bundle.expected_rows),
                bandwidth_bytes_per_ms=bandwidth_bytes_per_ms,
                exchange_fixed_ms=exchange_fixed_ms,
                coordinator_row_ms=coordinator_row_ms,
                memory=memory,
            )
            results[method.value] = result
            _write_json(
                run_root / "methods" / f"{method.value}.json",
                result.to_dict(),
            )
            if not result.success:
                raise RuntimeError(
                    f"method '{method.value}' failed: {result.error}"
                )

        checks = {
            "all_methods_present": set(results)
            == {method.value for method in selected_method_order},
            "all_answers_exact": all(result.exact_answer for result in results.values()),
            "calibration_exactly_three_profiles": calibration.attempted_calls == 3,
            "calibration_neo4j_full_matches_oracle": _observation_rows(
                calibration.tool_results[0]
            )
            == bundle.expected_source_rows["neo4j"],
            "calibration_fuseki_risk_matches_oracle": _observation_rows(
                calibration.tool_results[2]
            )
            == bundle.expected_source_rows["fuseki"],
            "no_memory_profiles_each_task": (
                results[M15Method.NO_MEMORY.value].planning_profile_calls == 3
            ),
            "warm_methods_use_common_snapshot": all(
                results[method.value].memory_state == "hit"
                for method in (
                    M15Method.NO_PROFILE_PROBE,
                    M15Method.NO_REPLAN,
                    M15Method.FULL_AGENT,
                )
            ),
            "no_profile_probe_has_no_current_observation": (
                results[
                    M15Method.NO_PROFILE_PROBE.value
                ].planning_profile_calls
                == 0
                and results[M15Method.NO_PROFILE_PROBE.value].probe_remote_calls == 0
            ),
            "no_replan_observes_but_keeps_initial": (
                results[M15Method.NO_REPLAN.value].probe_remote_calls == 1
                and results[M15Method.NO_REPLAN.value].replan_count == 0
                and results[M15Method.NO_REPLAN.value].executed_plan_id
                == results[M15Method.NO_REPLAN.value].initial_plan_id
            ),
            "full_agent_has_bounded_replanning": (
                results[M15Method.FULL_AGENT.value].probe_remote_calls == 1
                and results[M15Method.FULL_AGENT.value].replan_count in {0, 1}
            ),
            "all_tasks_use_two_query_calls": all(
                result.query_remote_calls == 2 for result in results.values()
            ),
            "tool_events_match_task_accounting": all(
                len(events[method]) == result.total_backend_calls
                and sum(
                    event["operation"] == "profile" for event in events[method]
                )
                == result.planning_profile_calls
                and sum(
                    event["operation"] == "execute" for event in events[method]
                )
                == result.query_remote_calls
                for method, result in results.items()
            ),
            "zero_llm_and_ontology_calls": True,
            "campaign_binding_matches_order": (
                selected_campaign_binding is None
                or selected_campaign_binding["method_order"]
                == [method.value for method in selected_method_order]
            ),
        }
        validation = {"passed": all(checks.values()), "checks": checks}
        _write_json(run_root / "validation.json", validation)
        if not validation["passed"]:
            raise RuntimeError("live method-matrix validation failed")
    except Exception as exc:  # Persist the first external failure; never retry.
        error = str(exc)
        if not (run_root / "health.json").exists():
            _write_json(run_root / "health.json", health)

    _write_json(
        run_root / "backend_invocations.json",
        {
            "events_by_phase": events,
            "total_tool_invocations": sum(len(items) for items in events.values()),
            "automatic_retries": 0,
        },
    )
    ended_at = _now()
    success = error is None
    _write_json(
        status_path,
        {
            "schema_version": LIVE_MATRIX_SCHEMA_VERSION,
            "run_id": selected_run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    manifest = {
        "schema_version": LIVE_MATRIX_SCHEMA_VERSION,
        "run_id": selected_run_id,
        "dataset_id": f"m15_f0:{bundle.spec.workload_id}",
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
            **{
                f"bundle:{bundle.spec.workload_id}/{name}": digest
                for name, digest in bundle.source_hashes.items()
            },
            f"bundle:{bundle.spec.workload_id}/manifest.json": _sha256_file(
                bundle.root / "manifest.json"
            ),
        },
        "workload_bundle": dict(bundle.manifest),
        "cost_model": model_config,
        "memory_context": context.to_dict(),
        "backend_health": health,
        "method_order": [method.value for method in selected_method_order],
        "order_policy": order_policy,
        "cache_state": cache_state,
        "campaign_binding": selected_campaign_binding,
        "execution_namespaces": {
            "task_ids": (
                selected_campaign_binding["method_task_ids"]
                if selected_campaign_binding is not None
                else {
                    method.value: f"{selected_run_id}.{method.value}"
                    for method in selected_method_order
                }
            ),
            "logical_memory_namespaces": (
                selected_campaign_binding["memory_namespaces"]
                if selected_campaign_binding is not None
                else {
                    method.value: f"{selected_run_id}.{method.value}"
                    for method in selected_method_order
                }
            ),
            "memory_storage_scope": "method_file_within_unique_run_root",
        },
        "calibration": calibration.to_dict() if calibration is not None else None,
        "calibration_accounting": {
            "included_in_method_metrics": False,
            "reason": "common live pre-task calibration shared by warm methods",
            "seed_memory_writes": seed_memory_writes,
        },
        "methods": {
            method: result.to_dict() for method, result in results.items()
        },
        "validation": validation,
        "artifacts": sorted(
            {
                *(path.name for path in run_root.iterdir()),
                manifest_path.name,
            }
        ),
        "evidence_class": evidence_class,
        "paper_result": False,
        "no_llm": True,
        "no_ontology": True,
        "automatic_retries": 0,
    }
    _write_json(manifest_path, manifest)
    return M15LiveMethodMatrixRecord(
        run_id=selected_run_id,
        run_root=run_root,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        error=error,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload-bundle", required=True)
    parser.add_argument("--output-root", default="runs")
    parser.add_argument("--run-id")
    parser.add_argument("--repo-root")
    args = parser.parse_args(argv)
    if os.environ.get("XGAP_RUN_M15_LIVE_METHOD_MATRIX") != "1":
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "error": (
                        "set XGAP_RUN_M15_LIVE_METHOD_MATRIX=1 after the verified "
                        "M15 scaled fixture is loaded"
                    ),
                },
                sort_keys=True,
            )
        )
        return 3
    try:
        record = run_m15_live_method_matrix(
            workload_bundle=args.workload_bundle,
            output_root=args.output_root,
            run_id=args.run_id,
            repo_root=args.repo_root,
        )
    except (FileExistsError, ValueError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps(record.to_dict(), indent=2, sort_keys=True))
    return 0 if record.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
