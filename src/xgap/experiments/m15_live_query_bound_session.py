"""Execute one M15 session after live bundle query-contract verification.

This F2B3 direct runner consumes the separately versioned query-bound campaign
plan. It recomputes every selected query contract from the actual verified
bundle before creating output or calling a backend, then passes an exact v2
binding to the existing six-method matrix. Native service lifecycle and Slurm
orchestration remain a later gate.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.backends.protocol import BackendClient
from xgap.experiments.m15_live_campaign_session import (
    M15LiveCampaignSessionPreparation,
    prepare_m15_live_campaign_session,
)
from xgap.experiments.m15_live_method_matrix import (
    M15LiveMethodMatrixRecord,
    QUERY_BOUND_CAMPAIGN_BINDING_SCHEMA_VERSION,
    run_m15_live_method_matrix,
)
from xgap.experiments.m15_query_bound_campaign import (
    M15QueryBoundCampaignPlan,
    compile_m15_query_bound_campaign_file,
)
from xgap.experiments.m15_query_contract import (
    M15QueryContract,
    compile_m15_query_contract,
)
from xgap.experiments.m15_workload import (
    M15WorkloadBundle,
    load_m15_workload_bundle,
)


LIVE_QUERY_BOUND_SESSION_SCHEMA_VERSION = "m15-f2-live-query-bound-session-v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class M15LiveQueryBoundSessionPreparation:
    repo_root: Path
    plan: Mapping[str, Any]
    session: Mapping[str, Any]
    bundle: M15WorkloadBundle
    base: M15LiveCampaignSessionPreparation
    query_contracts: Mapping[str, M15QueryContract]
    binding: Mapping[str, Any]


@dataclass(frozen=True)
class M15LiveQueryBoundSessionRecord:
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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _require_sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a SHA-256 digest")
    return value


def _select_session(
    plan: Mapping[str, Any],
    *,
    session_id: str,
) -> dict[str, Any]:
    sessions = plan.get("sessions")
    if not isinstance(sessions, list):
        raise ValueError("query-bound campaign plan has no session array")
    selected = [
        dict(item)
        for item in sessions
        if isinstance(item, Mapping) and item.get("session_id") == session_id
    ]
    if len(selected) != 1:
        raise ValueError("session_id must identify one query-bound session")
    return selected[0]


def _binding_by_key(
    plan: Mapping[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    raw = plan.get("query_bindings")
    if not isinstance(raw, list):
        raise ValueError("query-bound campaign plan has no binding array")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for value in raw:
        if not isinstance(value, Mapping):
            raise ValueError("query-bound campaign binding is invalid")
        item = dict(value)
        key = (str(item.get("workload_label")), str(item.get("query_id")))
        if key in result:
            raise ValueError("query-bound campaign binding keys are not unique")
        result[key] = item
    return result


def prepare_m15_live_query_bound_session(
    *,
    query_bound_registry: str | Path,
    session_id: str,
    expected_registry_spec_sha256: str,
    expected_query_bound_schedule_sha256: str,
    workload_bundle: M15WorkloadBundle | str | Path,
    repo_root: str | Path | None = None,
) -> M15LiveQueryBoundSessionPreparation:
    """Validate schedule and live bundle contracts before any external call."""

    root = Path(repo_root).resolve() if repo_root is not None else _repo_root()
    if not _SAFE_ID.fullmatch(session_id):
        raise ValueError("session_id contains unsupported characters")
    registry_hash = _require_sha256(
        expected_registry_spec_sha256,
        name="expected_registry_spec_sha256",
    )
    schedule_hash = _require_sha256(
        expected_query_bound_schedule_sha256,
        name="expected_query_bound_schedule_sha256",
    )
    compiled: M15QueryBoundCampaignPlan = compile_m15_query_bound_campaign_file(
        query_bound_registry,
        repo_root=root,
    )
    plan = compiled.to_dict()
    if plan.get("registry_spec_sha256") != registry_hash:
        raise ValueError("query-bound registry spec hash disagrees with expected hash")
    if plan.get("query_bound_schedule_sha256") != schedule_hash:
        raise ValueError("query-bound schedule hash disagrees with expected hash")
    session = _select_session(plan, session_id=session_id)
    bundle = load_m15_workload_bundle(
        workload_bundle.root
        if isinstance(workload_bundle, M15WorkloadBundle)
        else workload_bundle
    )
    if session.get("workload_id") != bundle.spec.workload_id:
        raise ValueError("query-bound session workload_id disagrees with bundle")

    base_campaign = plan.get("base_campaign")
    if not isinstance(base_campaign, Mapping):
        raise ValueError("query-bound plan has no base campaign identity")
    base = prepare_m15_live_campaign_session(
        campaign_config=root / str(base_campaign["config_path"]),
        session_id=session_id,
        expected_campaign_spec_sha256=str(base_campaign["campaign_spec_sha256"]),
        expected_schedule_sha256=str(base_campaign["schedule_sha256"]),
        workload_bundle=bundle,
        repo_root=root,
    )
    if session.get("method_order") != base.session.get("method_order"):
        raise ValueError("query-bound and base session method orders disagree")

    label = str(session["workload_label"])
    refs = session.get("query_contract_refs")
    if not isinstance(refs, list) or not refs:
        raise ValueError("query-bound session has no query contract references")
    registry_bindings = _binding_by_key(plan)
    contracts: dict[str, M15QueryContract] = {}
    contract_identities: dict[str, dict[str, Any]] = {}
    for ref_value in refs:
        if not isinstance(ref_value, Mapping):
            raise ValueError("query contract reference is invalid")
        ref = dict(ref_value)
        query_id = str(ref.get("query_id"))
        registry_binding = registry_bindings.get((label, query_id))
        if registry_binding is None:
            raise ValueError("query contract reference has no registry binding")
        if ref.get("expected_query_spec_sha256") != registry_binding.get(
            "expected_query_spec_sha256"
        ) or ref.get("expected_query_contract_sha256") != registry_binding.get(
            "expected_query_contract_sha256"
        ):
            raise ValueError("session and registry query contract references disagree")
        contract = compile_m15_query_contract(
            query_spec=root / str(registry_binding["query_spec_path"]),
            workload_bundle=bundle,
        )
        payload = contract.to_dict()
        if payload.get("query_id") != query_id:
            raise ValueError("compiled query contract query_id disagrees with session")
        if payload.get("query_spec_sha256") != ref.get(
            "expected_query_spec_sha256"
        ):
            raise ValueError("compiled query spec hash disagrees with registry")
        if contract.query_contract_sha256 != ref.get(
            "expected_query_contract_sha256"
        ):
            raise ValueError("live bundle query contract hash disagrees with registry")
        if query_id in contracts:
            raise ValueError("query-bound session contains a duplicate query contract")
        contracts[query_id] = contract
        contract_identities[query_id] = {
            "schema_version": payload["schema_version"],
            "query_spec_sha256": payload["query_spec_sha256"],
            "query_contract_sha256": contract.query_contract_sha256,
            "workload_id": bundle.spec.workload_id,
        }
    if set(contracts) != set(base.binding["query_ids"]):
        raise ValueError("verified query contracts do not cover the base session")

    binding = {
        **dict(base.binding),
        "schema_version": QUERY_BOUND_CAMPAIGN_BINDING_SCHEMA_VERSION,
        "registry_id": plan["registry_id"],
        "query_binding_sha256": plan["query_binding_sha256"],
        "query_bound_schedule_sha256": plan["query_bound_schedule_sha256"],
        "query_contracts": contract_identities,
    }
    return M15LiveQueryBoundSessionPreparation(
        repo_root=root,
        plan=plan,
        session=session,
        bundle=bundle,
        base=base,
        query_contracts=contracts,
        binding=binding,
    )


def run_m15_live_query_bound_session(
    *,
    query_bound_registry: str | Path,
    session_id: str,
    expected_registry_spec_sha256: str,
    expected_query_bound_schedule_sha256: str,
    workload_bundle: M15WorkloadBundle | str | Path,
    output_root: str | Path = "runs",
    run_id: str | None = None,
    repo_root: str | Path | None = None,
    clients: Mapping[str, BackendClient] | None = None,
    bandwidth_bytes_per_ms: float = 1000.0,
    exchange_fixed_ms: float = 0.5,
    coordinator_row_ms: float = 0.001,
) -> M15LiveQueryBoundSessionRecord:
    """Execute one verified query-bound development session without retry."""

    preparation = prepare_m15_live_query_bound_session(
        query_bound_registry=query_bound_registry,
        session_id=session_id,
        expected_registry_spec_sha256=expected_registry_spec_sha256,
        expected_query_bound_schedule_sha256=expected_query_bound_schedule_sha256,
        workload_bundle=workload_bundle,
        repo_root=repo_root,
    )
    root = preparation.repo_root
    selected_run_id = run_id or f"m15-f2-live-query-bound-{_now_slug()}"
    if not _SAFE_ID.fullmatch(selected_run_id):
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
            "schema_version": LIVE_QUERY_BOUND_SESSION_SCHEMA_VERSION,
            "run_id": selected_run_id,
            "status": "running",
            "started_at": started_at,
        },
    )
    _write_json(run_root / "query_bound_campaign_plan.json", preparation.plan)
    _write_json(run_root / "session_plan.json", preparation.session)
    _write_json(run_root / "campaign_binding.json", preparation.binding)
    for query_id, contract in preparation.query_contracts.items():
        _write_json(
            run_root / "query_contracts" / f"{query_id}.json",
            contract.to_dict(),
        )

    matrix: M15LiveMethodMatrixRecord | None = None
    validation: dict[str, Any] | None = None
    error: str | None = None
    try:
        matrix = run_m15_live_method_matrix(
            workload_bundle=preparation.bundle,
            output_root=run_root,
            run_id="method-matrix-run",
            repo_root=root,
            clients=clients,
            bandwidth_bytes_per_ms=bandwidth_bytes_per_ms,
            exchange_fixed_ms=exchange_fixed_ms,
            coordinator_row_ms=coordinator_row_ms,
            method_order=preparation.base.methods,
            campaign_binding=preparation.binding,
        )
        if not matrix.success:
            raise RuntimeError(matrix.error or "query-bound method sequence failed")
        matrix_manifest = json.loads(matrix.manifest_path.read_text(encoding="utf-8"))
        invocations = json.loads(
            (matrix.run_root / "backend_invocations.json").read_text(encoding="utf-8")
        )
        checks = {
            "matrix_method_order_matches_session": (
                matrix_manifest.get("method_order")
                == preparation.session["method_order"]
            ),
            "matrix_query_bound_binding_matches": (
                matrix_manifest.get("campaign_binding") == preparation.binding
            ),
            "matrix_evidence_class_is_query_bound_gate": (
                matrix_manifest.get("evidence_class")
                == "live_backend_query_bound_session_engineering_gate"
            ),
            "matrix_all_methods_exact": all(
                isinstance(result, Mapping) and result.get("exact_answer") is True
                for result in matrix_manifest.get("methods", {}).values()
            ),
            "matrix_call_budget_is_18": (
                invocations.get("total_tool_invocations") == 18
            ),
            "matrix_automatic_retries_are_zero": (
                invocations.get("automatic_retries") == 0
                and matrix_manifest.get("automatic_retries") == 0
            ),
            "query_contracts_are_live_bundle_verified": all(
                contract.to_dict()["workload"]["spec_sha256"]
                == preparation.bundle.manifest["spec_sha256"]
                for contract in preparation.query_contracts.values()
            ),
            "paper_result_is_false": matrix_manifest.get("paper_result") is False,
        }
        validation = {"passed": all(checks.values()), "checks": checks}
        _write_json(run_root / "validation.json", validation)
        if not validation["passed"]:
            raise RuntimeError("live query-bound session validation failed")
    except Exception as exc:  # Persist first failure; never retry a sequence.
        error = str(exc)

    ended_at = _now()
    success = error is None
    _write_json(
        status_path,
        {
            "schema_version": LIVE_QUERY_BOUND_SESSION_SCHEMA_VERSION,
            "run_id": selected_run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    _write_json(
        manifest_path,
        {
            "schema_version": LIVE_QUERY_BOUND_SESSION_SCHEMA_VERSION,
            "run_id": selected_run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
            "registry_id": preparation.plan["registry_id"],
            "registry_spec_sha256": preparation.plan["registry_spec_sha256"],
            "query_binding_sha256": preparation.plan["query_binding_sha256"],
            "query_bound_schedule_sha256": preparation.plan[
                "query_bound_schedule_sha256"
            ],
            "base_campaign": preparation.plan["base_campaign"],
            "session_id": session_id,
            "workload_bundle": dict(preparation.bundle.manifest),
            "query_contracts": {
                query_id: {
                    "query_contract_sha256": contract.query_contract_sha256,
                    "artifact": f"query_contracts/{query_id}.json",
                }
                for query_id, contract in preparation.query_contracts.items()
            },
            "method_order": [method.value for method in preparation.base.methods],
            "matrix": matrix.to_dict() if matrix is not None else None,
            "validation": validation,
            "artifacts": [
                "campaign_binding.json",
                "method-matrix-run",
                "query_bound_campaign_plan.json",
                "query_contracts",
                "run_manifest.json",
                "run_status.json",
                "session_plan.json",
                "validation.json",
            ],
            "automatic_retries": 0,
            "llm_calls": 0,
            "ontology_calls": 0,
            "evidence_class": "development_live_query_bound_session_gate",
            "claim_boundary": {
                "live_bundle_contracts_verified": True,
                "multi_task_memory_stream": False,
                "counterbalance_complete": False,
                "contains_one_campaign_sequence": True,
                "native_service_lifecycle": False,
                "comparative": False,
                "paper_result": False,
                "blocking_conditions": [
                    "native_service_lifecycle_and_read_only_audit_not_yet_wired",
                    "single_query_stream_cannot_measure_cross_task_memory_reuse",
                    "one_session_does_not_complete_the_counterbalanced_campaign",
                    "cost_model_is_uncalibrated",
                ],
            },
            "paper_result": False,
        },
    )
    return M15LiveQueryBoundSessionRecord(
        run_id=selected_run_id,
        run_root=run_root,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        error=error,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query-bound-registry", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--expected-registry-spec-sha256", required=True)
    parser.add_argument("--expected-query-bound-schedule-sha256", required=True)
    parser.add_argument("--workload-bundle", required=True)
    parser.add_argument("--output-root", default="runs")
    parser.add_argument("--run-id")
    parser.add_argument("--repo-root")
    args = parser.parse_args(argv)
    if os.environ.get("XGAP_RUN_M15_LIVE_QUERY_BOUND_SESSION") != "1":
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "error": (
                        "set XGAP_RUN_M15_LIVE_QUERY_BOUND_SESSION=1 only "
                        "inside a verified session-scoped lifecycle"
                    ),
                },
                sort_keys=True,
            )
        )
        return 3
    try:
        record = run_m15_live_query_bound_session(
            query_bound_registry=args.query_bound_registry,
            session_id=args.session_id,
            expected_registry_spec_sha256=args.expected_registry_spec_sha256,
            expected_query_bound_schedule_sha256=(
                args.expected_query_bound_schedule_sha256
            ),
            workload_bundle=args.workload_bundle,
            output_root=args.output_root,
            run_id=args.run_id,
            repo_root=args.repo_root,
        )
    except (FileExistsError, OSError, ValueError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps(record.to_dict(), indent=2, sort_keys=True))
    return 0 if record.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
