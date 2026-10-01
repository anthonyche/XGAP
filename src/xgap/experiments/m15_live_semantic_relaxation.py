"""Execute one readiness-approved F2C7 semantic relaxation on live backends.

This mechanism gate deliberately fixes the physical strategy.  It validates
that a materialized semantic class reaches the black-box Neo4j and Fuseki
interfaces and returns its independently generated oracle answer.  It does not
compare strategies, learn a policy, or use the answer oracle for selection.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from xgap.backends.protocol import BackendClient
from xgap.experiments.m15_live_adaptive import RecordingBackendPlugin
from xgap.experiments.m15_parameterized_federation import (
    build_m15_parameterized_plan_candidates,
    load_m15_parameterized_contract,
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_parameterized_workload import (
    M15ParameterizedWorkloadBundle,
    load_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_semantic_frontier import M15SemanticRelaxationCatalog
from xgap.experiments.m15_semantic_overlay import (
    M15SemanticOverlayBundle,
    load_m15_semantic_overlay_bundle,
)
from xgap.runtime import FederatedExecutionPlan, FederatedScheduler
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


LIVE_SEMANTIC_RELAXATION_SCHEMA_VERSION = (
    "m15-f2c7b2-live-semantic-risk-relaxation-v1"
)
SEMANTIC_RISK_EXECUTION_CONTRACT_VERSION = (
    "m15-f2c7b2-semantic-risk-execution-contract-v1"
)
FIXED_PHYSICAL_STRATEGY = "risk_first_bind_join"
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class M15LiveSemanticRelaxationRecord:
    run_id: str
    run_root: Path
    success: bool
    status_path: Path
    manifest_path: Path
    result_path: Path
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_root": str(self.run_root),
            "success": self.success,
            "status_path": str(self.status_path),
            "manifest_path": str(self.manifest_path),
            "result_path": str(self.result_path),
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


def _binding_values(contract: Mapping[str, Any]) -> dict[str, Any]:
    bindings = contract.get("bindings")
    if not isinstance(bindings, list):
        raise ValueError("parameterized contract bindings are invalid")
    result: dict[str, Any] = {}
    for item in bindings:
        if not isinstance(item, Mapping):
            raise ValueError("parameterized binding must be an object")
        slot_id = item.get("slot_id")
        if not isinstance(slot_id, str) or slot_id in result:
            raise ValueError("parameterized binding slot IDs are invalid")
        result[slot_id] = item.get("value")
    return result


def _single_relaxation(
    overlay: M15SemanticOverlayBundle,
) -> dict[str, Any]:
    records = overlay.manifest.get("overlay_instances")
    if not isinstance(records, list) or len(records) != 1:
        raise ValueError(
            "F2C7B2 requires exactly one readiness-approved overlay instance"
        )
    record = records[0]
    if not isinstance(record, Mapping):
        raise ValueError("semantic overlay instance is invalid")
    semantic_deviation = record.get("semantic_deviation")
    if (
        isinstance(semantic_deviation, bool)
        or not isinstance(semantic_deviation, (int, float))
        or not 0 < float(semantic_deviation) <= 1
    ):
        raise ValueError("semantic overlay deviation must be in (0, 1]")
    return dict(record)


def build_m15_semantic_risk_execution_plan(
    *,
    overlay: M15SemanticOverlayBundle,
    base_bundle: M15ParameterizedWorkloadBundle,
) -> tuple[FederatedExecutionPlan, dict[str, Any]]:
    """Bind the single risk relaxation to one fixed non-oracle physical plan."""

    record = _single_relaxation(overlay)
    query_id = str(record["query_id"])
    base_query_id = str(overlay.manifest["base_query_id"])
    base_contract = load_m15_parameterized_contract(
        base_bundle, base_query_id
    )["contract"]
    relaxed_contract = load_m15_parameterized_contract(
        overlay.workload_bundle, query_id
    )["contract"]
    base_bindings = _binding_values(base_contract)
    relaxed_bindings = _binding_values(relaxed_contract)
    changed_slots = sorted(
        slot_id
        for slot_id, value in relaxed_bindings.items()
        if base_bindings.get(slot_id) != value
    )
    if changed_slots != ["risk-level"]:
        raise ValueError("F2C7B2 accepts only a risk-level-only relaxation")
    if base_bindings["risk-level"] != "HIGH" or relaxed_bindings[
        "risk-level"
    ] != "MEDIUM":
        raise ValueError("F2C7B2 requires the approved HIGH-to-MEDIUM transition")
    hard_slots = ("person-identity", "time-lower-bound", "amount-lower-bound")
    if any(base_bindings[slot] != relaxed_bindings[slot] for slot in hard_slots):
        raise ValueError("semantic overlay changed an immutable hard binding")
    candidates = build_m15_parameterized_plan_candidates(
        overlay.workload_bundle,
        query_id=query_id,
    )
    matches = [
        candidate
        for candidate in candidates
        if candidate.plan.metadata.get("physical_strategy")
        == FIXED_PHYSICAL_STRATEGY
    ]
    if len(matches) != 1:
        raise ValueError("fixed semantic relaxation physical plan is unavailable")
    selected = matches[0].plan
    metadata = {
        **dict(selected.metadata),
        "semantic_deviation": float(record["semantic_deviation"]),
        "semantic_class_id": record["semantic_class_id"],
        "semantic_role": "relaxed_interpretation",
        "semantic_overlay_sha256": overlay.manifest["overlay_sha256"],
        "base_query_id": base_query_id,
        "base_query_instance_sha256": base_contract["query_instance_sha256"],
        "query_instance_sha256": record["query_instance_sha256"],
        "physical_selection_mode": "fixed_mechanism_gate",
        "answer_oracle_used_for_selection": False,
        "paper_result": False,
    }
    plan = replace(
        selected,
        plan_id=(
            f"m15-f2c7b2-{record['semantic_class_id']}-risk-first-bind"
        ),
        metadata=metadata,
    )
    contract = {
        "schema_version": SEMANTIC_RISK_EXECUTION_CONTRACT_VERSION,
        "semantic_class_id": record["semantic_class_id"],
        "semantic_deviation": float(record["semantic_deviation"]),
        "base_query_id": base_query_id,
        "query_id": query_id,
        "base_query_instance_sha256": base_contract["query_instance_sha256"],
        "query_instance_sha256": record["query_instance_sha256"],
        "binding_sha256": record["binding_sha256"],
        "changed_slot_ids": changed_slots,
        "hard_bindings_preserved": True,
        "risk_transition": {"from": "HIGH", "to": "MEDIUM"},
        "physical_strategy": FIXED_PHYSICAL_STRATEGY,
        "physical_selection_mode": "fixed_mechanism_gate",
        "oracle_inputs_to_selection": [],
        "automatic_retries": 0,
        "paper_result": False,
    }
    return plan, contract


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


def run_m15_live_semantic_risk_relaxation(
    *,
    semantic_overlay: M15SemanticOverlayBundle | str | Path,
    base_bundle: M15ParameterizedWorkloadBundle | str | Path,
    catalog: M15SemanticRelaxationCatalog | str | Path,
    clients: Mapping[str, BackendClient],
    output_root: str | Path,
    run_id: str = "semantic-risk-relaxation-run",
    repo_root: str | Path | None = None,
) -> M15LiveSemanticRelaxationRecord:
    """Execute exactly one approved relaxed plan and validate it post hoc."""

    root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else Path(__file__).resolve().parents[3]
    )
    selected_base = (
        base_bundle
        if isinstance(base_bundle, M15ParameterizedWorkloadBundle)
        else load_m15_parameterized_workload_bundle(base_bundle)
    )
    overlay = load_m15_semantic_overlay_bundle(
        semantic_overlay.root
        if isinstance(semantic_overlay, M15SemanticOverlayBundle)
        else semantic_overlay,
        base_bundle=selected_base,
        catalog=catalog,
    )
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("run_id contains unsupported characters")
    if set(clients) != {"neo4j", "fuseki"}:
        raise ValueError(
            "semantic relaxation requires exactly neo4j and fuseki clients"
        )
    destination = Path(output_root)
    if not destination.is_absolute():
        destination = root / destination
    run_root = destination.resolve() / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    status_path = run_root / "run_status.json"
    manifest_path = run_root / "run_manifest.json"
    result_path = run_root / "semantic_result.json"
    started_at = _now()
    _write_json(
        status_path,
        {
            "schema_version": LIVE_SEMANTIC_RELAXATION_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "running",
            "started_at": started_at,
        },
    )

    health: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    checks: dict[str, bool] = {}
    plan: FederatedExecutionPlan | None = None
    execution_contract: dict[str, Any] | None = None
    result_payload: dict[str, Any] | None = None
    error: str | None = None
    try:
        plan, execution_contract = build_m15_semantic_risk_execution_plan(
            overlay=overlay,
            base_bundle=selected_base,
        )
        _write_json(run_root / "execution_contract.json", execution_contract)
        _write_json(run_root / "semantic_plan.json", plan.to_dict())
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

        instance = load_m15_parameterized_instance(
            overlay.workload_bundle,
            execution_contract["query_id"],
        )
        result = FederatedScheduler(_backend_tool(clients, events)).execute(
            plan,
            goal_id=f"{run_id}:execute-semantic-relaxation",
        )
        result_payload = result.to_dict()
        _write_json(result_path, result_payload)
        final_rows = [dict(row) for row in result.final_rows]
        checks = {
            "runtime_success": result.success,
            "exact_relaxed_oracle_answer": final_rows == instance["final_oracle"],
            "answer_is_nonempty": bool(final_rows),
            "answer_risk_is_medium": bool(final_rows)
            and {row.get("risk") for row in final_rows} == {"MEDIUM"},
            "semantic_deviation_is_positive": float(
                plan.metadata["semantic_deviation"]
            )
            > 0,
            "semantic_class_bound": plan.metadata["semantic_class_id"]
            == execution_contract["semantic_class_id"],
            "hard_bindings_preserved": execution_contract[
                "hard_bindings_preserved"
            ],
            "fixed_physical_strategy": plan.metadata["physical_strategy"]
            == FIXED_PHYSICAL_STRATEGY,
            "selection_used_no_oracle": not plan.metadata[
                "answer_oracle_used_for_selection"
            ],
            "exact_remote_call_count": result.total_remote_calls == 2,
            "exact_tool_event_count": len(events) == 2,
            "one_call_per_backend": len(events) == 2
            and {event["backend_id"] for event in events}
            == {"neo4j", "fuseki"},
            "all_calls_are_execute": len(events) == 2
            and all(event["operation"] == "execute" for event in events),
        }
        _write_json(
            run_root / "validation.json",
            {"passed": all(checks.values()), "checks": checks},
        )
        if not all(checks.values()):
            raise RuntimeError("live semantic relaxation validation failed")
    except Exception as exc:  # Preserve the first external failure; never retry.
        error = str(exc)
        if not (run_root / "health.json").exists():
            _write_json(run_root / "health.json", health)

    _write_json(
        run_root / "backend_invocations.json",
        {
            "events": events,
            "total_tool_invocations": len(events),
            "automatic_retries": 0,
        },
    )
    ended_at = _now()
    success = error is None
    _write_json(
        status_path,
        {
            "schema_version": LIVE_SEMANTIC_RELAXATION_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    _write_json(
        manifest_path,
        {
            "schema_version": LIVE_SEMANTIC_RELAXATION_SCHEMA_VERSION,
            "run_id": run_id,
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
                "base_bundle_manifest": _sha256_file(
                    selected_base.root / "manifest.json"
                ),
                "semantic_overlay_manifest": _sha256_file(
                    overlay.root / "overlay_manifest.json"
                ),
            },
            "base_workload_bundle": dict(selected_base.manifest),
            "semantic_overlay": dict(overlay.manifest),
            "execution_contract": execution_contract,
            "selected_plan": plan.to_dict() if plan is not None else None,
            "backend_health": health,
            "summary": (
                {
                    "semantic_class_count": 1,
                    "semantic_deviation": plan.metadata["semantic_deviation"],
                    "physical_plan_run_count": 1,
                    "total_remote_calls": result_payload["total_remote_calls"],
                    "total_bytes_moved": result_payload["total_bytes_moved"],
                    "final_row_count": len(result_payload["final_rows"]),
                }
                if plan is not None and result_payload is not None
                else None
            ),
            "validation": {
                "passed": bool(checks) and all(checks.values()),
                "checks": checks,
            },
            "evidence_class": "live_semantic_relaxation_mechanism_gate",
            "answer_oracle_used_for_plan_construction_or_selection": False,
            "answer_oracle_used_for_post_execution_validation": True,
            "physical_strategy_comparison_enabled": False,
            "memory_enabled": False,
            "llm_calls_made": 0,
            "ontology_calls_made": 0,
            "automatic_retries": 0,
            "paper_result": False,
            "artifacts": sorted(path.name for path in run_root.iterdir()),
        },
    )
    return M15LiveSemanticRelaxationRecord(
        run_id=run_id,
        run_root=run_root,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        result_path=result_path,
        error=error,
    )
