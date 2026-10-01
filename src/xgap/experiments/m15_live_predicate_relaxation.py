"""Execute the two F2C8 predicate-relaxed classes on live graph backends.

This mechanism gate binds a development predicate mapping to native Neo4j
and Fuseki artifacts.  It deliberately fixes one physical strategy per
semantic class and opens answer oracles only after every plan is constructed.
It is not a physical-plan comparison, ontology evaluation, or paper result.
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
from typing import Any, Mapping, Sequence

from xgap.backends.protocol import BackendClient
from xgap.experiments.m15_live_adaptive import RecordingBackendPlugin
from xgap.experiments.m15_live_semantic_relaxation import (
    FIXED_PHYSICAL_STRATEGY,
)
from xgap.experiments.m15_parameterized_federation import (
    build_m15_parameterized_plan_candidates,
    load_m15_parameterized_contract,
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_parameterized_workload import (
    M15ParameterizedWorkloadBundle,
    load_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_predicate_overlay import (
    M15PredicateMappingSpec,
    M15PredicateOverlayBundle,
    load_m15_predicate_overlay_bundle,
)
from xgap.experiments.m15_semantic_frontier import (
    M15SemanticRelaxationCatalog,
)
from xgap.runtime import FederatedExecutionPlan, FederatedScheduler
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


LIVE_PREDICATE_RELAXATION_SCHEMA_VERSION = (
    "m15-f2c8b-live-semantic-predicate-relaxation-v1"
)
PREDICATE_EXECUTION_CONTRACT_VERSION = (
    "m15-f2c8b-semantic-predicate-execution-contract-v1"
)
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_HARD_SLOT_IDS = (
    "amount-lower-bound",
    "person-identity",
    "time-lower-bound",
)
_EXPECTED_CHANGED_SLOT_SETS = {
    ("transfer-predicate",),
    ("risk-level", "transfer-predicate"),
}


@dataclass(frozen=True)
class M15LivePredicateRelaxationRecord:
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


def _predicate_records(
    overlay: M15PredicateOverlayBundle,
) -> list[dict[str, Any]]:
    records = overlay.manifest.get("overlay_instances")
    if not isinstance(records, list):
        raise ValueError("predicate overlay instances are invalid")
    selected: list[dict[str, Any]] = []
    for raw in records:
        if not isinstance(raw, Mapping):
            raise ValueError("predicate overlay instance is invalid")
        changed = raw.get("changed_slot_ids")
        if not isinstance(changed, list):
            raise ValueError("predicate changed_slot_ids are invalid")
        if "transfer-predicate" in changed:
            selected.append(dict(raw))
    observed = {tuple(item["changed_slot_ids"]) for item in selected}
    if observed != _EXPECTED_CHANGED_SLOT_SETS or len(selected) != 2:
        raise ValueError(
            "F2C8B requires predicate-only and risk-plus-predicate classes"
        )
    return sorted(selected, key=lambda item: str(item["query_id"]))


def build_m15_semantic_predicate_execution_plans(
    *,
    overlay: M15PredicateOverlayBundle,
    base_bundle: M15ParameterizedWorkloadBundle,
) -> tuple[tuple[FederatedExecutionPlan, dict[str, Any]], ...]:
    """Bind both predicate classes to fixed plans without opening oracles."""

    base_query_id = str(overlay.manifest["base_query_id"])
    base_contract = load_m15_parameterized_contract(
        base_bundle,
        base_query_id,
    )["contract"]
    base_bindings = _binding_values(base_contract)
    mapping = overlay.mapping
    if base_bindings["transfer-predicate"] != mapping.source_predicate:
        raise ValueError("base query does not use the mapping source predicate")

    built: list[tuple[FederatedExecutionPlan, dict[str, Any]]] = []
    for record in _predicate_records(overlay):
        query_id = str(record["query_id"])
        relaxed_contract = load_m15_parameterized_contract(
            overlay.workload_bundle,
            query_id,
        )["contract"]
        relaxed_bindings = _binding_values(relaxed_contract)
        changed_slots = sorted(
            slot_id
            for slot_id, value in relaxed_bindings.items()
            if base_bindings.get(slot_id) != value
        )
        if changed_slots != list(record["changed_slot_ids"]):
            raise ValueError("predicate overlay changed-slot record drifted")
        if tuple(changed_slots) not in _EXPECTED_CHANGED_SLOT_SETS:
            raise ValueError("predicate execution class changes unsupported slots")
        if relaxed_bindings["transfer-predicate"] != mapping.target_predicate:
            raise ValueError("predicate class does not use the mapping target")
        if any(
            base_bindings[slot_id] != relaxed_bindings[slot_id]
            for slot_id in _HARD_SLOT_IDS
        ):
            raise ValueError("predicate overlay changed an immutable hard binding")
        if relaxed_bindings["path-shape"] != "direct":
            raise ValueError("F2C8B cannot execute an unbound multihop class")
        if relaxed_bindings["risk-level"] not in {"HIGH", "MEDIUM"}:
            raise ValueError("predicate class uses an unsupported risk value")

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
            raise ValueError("fixed predicate physical plan is unavailable")
        selected = matches[0].plan
        metadata = {
            **dict(selected.metadata),
            "semantic_deviation": float(record["semantic_deviation"]),
            "semantic_class_id": record["semantic_class_id"],
            "semantic_role": "predicate_relaxed_interpretation",
            "predicate_overlay_sha256": overlay.manifest["overlay_sha256"],
            "predicate_mapping_id": mapping.mapping_id,
            "predicate_mapping_sha256": overlay.manifest["predicate_mapping"][
                "mapping_sha256"
            ],
            "base_query_id": base_query_id,
            "base_query_instance_sha256": base_contract[
                "query_instance_sha256"
            ],
            "query_instance_sha256": record["query_instance_sha256"],
            "physical_selection_mode": "fixed_mechanism_gate",
            "answer_oracle_used_for_selection": False,
            "paper_result": False,
        }
        plan = replace(
            selected,
            plan_id=(
                f"m15-f2c8b-{record['semantic_class_id']}-risk-first-bind"
            ),
            metadata=metadata,
        )
        contract = {
            "schema_version": PREDICATE_EXECUTION_CONTRACT_VERSION,
            "semantic_class_id": record["semantic_class_id"],
            "semantic_deviation": float(record["semantic_deviation"]),
            "base_query_id": base_query_id,
            "query_id": query_id,
            "base_query_instance_sha256": base_contract[
                "query_instance_sha256"
            ],
            "query_instance_sha256": record["query_instance_sha256"],
            "binding_sha256": record["binding_sha256"],
            "changed_slot_ids": changed_slots,
            "hard_bindings_preserved": True,
            "path_shape": "direct",
            "risk_transition": {
                "from": base_bindings["risk-level"],
                "to": relaxed_bindings["risk-level"],
            },
            "predicate_transition": {
                "transition_id": mapping.transition_id,
                "from": mapping.source_predicate,
                "to": mapping.target_predicate,
                "transformation": mapping.transformation,
                "evidence": dict(mapping.evidence),
                "backend_id": "neo4j",
                "relationship_type": mapping.relationship_type,
            },
            "physical_strategy": FIXED_PHYSICAL_STRATEGY,
            "physical_selection_mode": "fixed_mechanism_gate",
            "oracle_inputs_to_selection": [],
            "automatic_retries": 0,
            "paper_result": False,
        }
        built.append((plan, contract))
    return tuple(built)


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


def run_m15_live_semantic_predicate_relaxation(
    *,
    predicate_overlay: M15PredicateOverlayBundle | str | Path,
    base_bundle: M15ParameterizedWorkloadBundle | str | Path,
    catalog: M15SemanticRelaxationCatalog | str | Path,
    mapping: M15PredicateMappingSpec | str | Path,
    clients: Mapping[str, BackendClient],
    output_root: str | Path,
    run_id: str = "semantic-predicate-relaxation-run",
    repo_root: str | Path | None = None,
) -> M15LivePredicateRelaxationRecord:
    """Execute exactly two predicate-relaxed plans and validate post hoc."""

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
    overlay = load_m15_predicate_overlay_bundle(
        predicate_overlay.root
        if isinstance(predicate_overlay, M15PredicateOverlayBundle)
        else predicate_overlay,
        base_bundle=selected_base,
        catalog=catalog,
        mapping=mapping,
    )
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("run_id contains unsupported characters")
    if set(clients) != {"neo4j", "fuseki"}:
        raise ValueError(
            "predicate relaxation requires exactly neo4j and fuseki clients"
        )
    destination = Path(output_root)
    if not destination.is_absolute():
        destination = root / destination
    run_root = destination.resolve() / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    status_path = run_root / "run_status.json"
    manifest_path = run_root / "run_manifest.json"
    result_path = run_root / "semantic_results.json"
    started_at = _now()
    _write_json(
        status_path,
        {
            "schema_version": LIVE_PREDICATE_RELAXATION_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "running",
            "started_at": started_at,
        },
    )

    health: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    checks: dict[str, bool] = {}
    built: tuple[tuple[FederatedExecutionPlan, dict[str, Any]], ...] = ()
    results: list[dict[str, Any]] = []
    error: str | None = None
    try:
        # This is the selection boundary: construct every plan before opening
        # expected source or final answer files.
        built = build_m15_semantic_predicate_execution_plans(
            overlay=overlay,
            base_bundle=selected_base,
        )
        _write_json(
            run_root / "execution_contracts.json",
            {"contracts": [contract for _, contract in built]},
        )
        _write_json(
            run_root / "semantic_plans.json",
            {"plans": [plan.to_dict() for plan, _ in built]},
        )
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

        scheduler = FederatedScheduler(_backend_tool(clients, events))
        for plan, contract in built:
            instance = load_m15_parameterized_instance(
                overlay.workload_bundle,
                contract["query_id"],
            )
            result = scheduler.execute(
                plan,
                goal_id=f"{run_id}:execute:{contract['semantic_class_id']}",
            )
            final_rows = [dict(row) for row in result.final_rows]
            results.append(
                {
                    "semantic_class_id": contract["semantic_class_id"],
                    "query_id": contract["query_id"],
                    "semantic_deviation": contract["semantic_deviation"],
                    "changed_slot_ids": list(contract["changed_slot_ids"]),
                    "physical_strategy": contract["physical_strategy"],
                    "expected_final_row_count": len(instance["final_oracle"]),
                    "exact_oracle_answer": final_rows == instance["final_oracle"],
                    "runtime_result": result.to_dict(),
                }
            )
            if not result.success:
                raise RuntimeError(
                    "live predicate relaxation execution failed for "
                    f"{contract['semantic_class_id']}"
                )
        _write_json(result_path, {"results": results})
        result_payloads = [item["runtime_result"] for item in results]
        checks = {
            "two_predicate_classes": len(built) == 2,
            "all_runtime_success": all(
                item["success"] for item in result_payloads
            ),
            "all_exact_oracle_answers": all(
                item["exact_oracle_answer"] for item in results
            ),
            "expected_final_row_counts": [
                item["expected_final_row_count"] for item in results
            ]
            == [6, 9],
            "all_answers_nonempty": all(
                bool(item["runtime_result"]["final_rows"]) for item in results
            ),
            "hard_bindings_preserved": all(
                contract["hard_bindings_preserved"] for _, contract in built
            ),
            "predicate_transition_bound": all(
                contract["predicate_transition"]["to"]
                == overlay.mapping.target_predicate
                for _, contract in built
            ),
            "direct_path_only": all(
                contract["path_shape"] == "direct" for _, contract in built
            ),
            "fixed_physical_strategy": all(
                plan.metadata["physical_strategy"] == FIXED_PHYSICAL_STRATEGY
                for plan, _ in built
            ),
            "selection_used_no_oracle": all(
                not plan.metadata["answer_oracle_used_for_selection"]
                for plan, _ in built
            ),
            "exact_remote_call_count": sum(
                item["total_remote_calls"] for item in result_payloads
            )
            == 4,
            "exact_tool_event_count": len(events) == 4,
            "two_calls_per_backend": len(events) == 4
            and [event["backend_id"] for event in events].count("neo4j") == 2
            and [event["backend_id"] for event in events].count("fuseki") == 2,
            "all_calls_are_execute": len(events) == 4
            and all(event["operation"] == "execute" for event in events),
        }
        _write_json(
            run_root / "validation.json",
            {"passed": all(checks.values()), "checks": checks},
        )
        if not all(checks.values()):
            raise RuntimeError("live predicate relaxation validation failed")
    except Exception as exc:  # Preserve first external failure; never retry.
        error = str(exc)
        if not (run_root / "health.json").exists():
            _write_json(run_root / "health.json", health)
        if not result_path.exists():
            _write_json(result_path, {"results": results})

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
            "schema_version": LIVE_PREDICATE_RELAXATION_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    result_payloads = [item["runtime_result"] for item in results]
    _write_json(
        manifest_path,
        {
            "schema_version": LIVE_PREDICATE_RELAXATION_SCHEMA_VERSION,
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
                "predicate_overlay_manifest": _sha256_file(
                    overlay.root / "overlay_manifest.json"
                ),
            },
            "base_workload_bundle": dict(selected_base.manifest),
            "predicate_overlay": dict(overlay.manifest),
            "predicate_mapping": overlay.mapping.to_dict(),
            "execution_contracts": [contract for _, contract in built],
            "selected_plans": [plan.to_dict() for plan, _ in built],
            "backend_health": health,
            "summary": (
                {
                    "semantic_class_count": len(built),
                    "semantic_deviations": [
                        contract["semantic_deviation"] for _, contract in built
                    ],
                    "physical_plan_run_count": len(results),
                    "total_remote_calls": sum(
                        item["total_remote_calls"] for item in result_payloads
                    ),
                    "total_bytes_moved": sum(
                        item["total_bytes_moved"] for item in result_payloads
                    ),
                    "final_row_counts": [
                        len(item["final_rows"]) for item in result_payloads
                    ],
                }
                if built and results
                else None
            ),
            "validation": {
                "passed": bool(checks) and all(checks.values()),
                "checks": checks,
            },
            "evidence_class": "live_predicate_relaxation_mechanism_gate",
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
    return M15LivePredicateRelaxationRecord(
        run_id=run_id,
        run_root=run_root,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        result_path=result_path,
        error=error,
    )
