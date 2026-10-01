"""Execute one hash-bound M15-F2 development campaign session.

The v1 session executor deliberately supports only the existing single exact
financial-risk query. It proves that a compiled Williams order controls the
real six-method runner; it does not yet implement a multi-task memory stream or
paper campaign orchestration.
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
from xgap.experiments.m15_campaign import compile_m15_campaign_file
from xgap.experiments.m15_live_method_matrix import (
    CAMPAIGN_BINDING_SCHEMA_VERSION,
    M15LiveMethodMatrixRecord,
    run_m15_live_method_matrix,
)
from xgap.experiments.m15_method_policy import M15Method
from xgap.experiments.m15_workload import (
    M15WorkloadBundle,
    load_m15_workload_bundle,
)


LIVE_CAMPAIGN_SESSION_SCHEMA_VERSION = "m15-f2-live-campaign-session-v1"
SUPPORTED_QUERY_ID = "financial-risk-alice-high-risk"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class M15LiveCampaignSessionRecord:
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


@dataclass(frozen=True)
class M15LiveCampaignSessionPreparation:
    repo_root: Path
    plan: Mapping[str, Any]
    session: Mapping[str, Any]
    workload_input: Mapping[str, Any]
    bundle: M15WorkloadBundle
    methods: tuple[M15Method, ...]
    binding: Mapping[str, Any]


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
) -> tuple[dict[str, Any], dict[str, Any]]:
    sessions = plan.get("sessions")
    if not isinstance(sessions, list):
        raise ValueError("compiled campaign plan has no session array")
    selected = [
        dict(item)
        for item in sessions
        if isinstance(item, Mapping) and item.get("session_id") == session_id
    ]
    if len(selected) != 1:
        raise ValueError("campaign session_id must identify exactly one session")
    session = selected[0]
    workload_inputs = plan.get("workload_inputs")
    if not isinstance(workload_inputs, list):
        raise ValueError("compiled campaign plan has no workload input array")
    inputs = [
        dict(item)
        for item in workload_inputs
        if isinstance(item, Mapping)
        and item.get("label") == session.get("workload_label")
    ]
    if len(inputs) != 1:
        raise ValueError("campaign session has no unique workload input")
    return session, inputs[0]


def _validate_development_session(
    *,
    plan: Mapping[str, Any],
    session: Mapping[str, Any],
    workload_input: Mapping[str, Any],
    bundle: M15WorkloadBundle,
    expected_campaign_spec_sha256: str,
    expected_schedule_sha256: str,
) -> tuple[tuple[M15Method, ...], dict[str, Any]]:
    if plan.get("experiment_mode") != "development":
        raise ValueError("the v1 live campaign session accepts development mode only")
    if plan.get("paper_result") is not False:
        raise ValueError("compiled campaign plan must remain paper_result=false")
    if plan.get("campaign_spec_sha256") != expected_campaign_spec_sha256:
        raise ValueError("compiled campaign spec hash disagrees with the expected hash")
    if plan.get("schedule_sha256") != expected_schedule_sha256:
        raise ValueError("compiled campaign schedule hash disagrees with the expected hash")
    if session.get("workload_id") != bundle.spec.workload_id:
        raise ValueError("campaign session workload_id disagrees with the bundle")
    if workload_input.get("workload_id") != bundle.spec.workload_id:
        raise ValueError("campaign workload input disagrees with the bundle workload_id")
    if workload_input.get("bundle_spec_sha256") != bundle.manifest.get(
        "spec_sha256"
    ):
        raise ValueError("campaign workload spec hash disagrees with the bundle")

    streams = session.get("method_streams")
    order = session.get("method_order")
    if not isinstance(streams, list) or not isinstance(order, list):
        raise ValueError("campaign session method schedule is invalid")
    if [item.get("method") for item in streams if isinstance(item, Mapping)] != order:
        raise ValueError("campaign method streams disagree with the declared order")
    try:
        methods = tuple(M15Method(item) for item in order)
    except (TypeError, ValueError) as exc:
        raise ValueError("campaign method order contains an unknown method") from exc
    if len(methods) != len(M15Method) or set(methods) != set(M15Method):
        raise ValueError("campaign session must contain all six methods exactly once")

    query_streams = {
        tuple(item.get("query_ids", []))
        for item in streams
        if isinstance(item, Mapping)
        and isinstance(item.get("query_ids"), list)
    }
    if query_streams != {(SUPPORTED_QUERY_ID,)}:
        raise ValueError(
            "the v1 live campaign session supports exactly one frozen "
            f"query: {SUPPORTED_QUERY_ID}"
        )
    stream_by_method = {
        str(item["method"]): dict(item)
        for item in streams
        if isinstance(item, Mapping) and isinstance(item.get("method"), str)
    }
    if any(stream_by_method[method.value].get("warmup_run_ids") != [] for method in methods):
        raise ValueError("the v1 live campaign session requires zero warmup runs")
    measured_ids = {
        method.value: stream_by_method[method.value].get("measured_run_ids")
        for method in methods
    }
    if any(
        not isinstance(values, list)
        or len(values) != 1
        or not isinstance(values[0], str)
        or not _SAFE_ID.fullmatch(values[0])
        for values in measured_ids.values()
    ):
        raise ValueError("each campaign method requires one safe measured run ID")
    method_task_ids = {
        method: values[0] for method, values in measured_ids.items()
    }
    if len(set(method_task_ids.values())) != len(method_task_ids):
        raise ValueError("campaign measured run IDs must be unique")
    memory_namespaces = {
        method.value: stream_by_method[method.value].get("memory_namespace")
        for method in methods
    }
    if any(
        not isinstance(value, str) or not _SAFE_ID.fullmatch(value)
        for value in memory_namespaces.values()
    ) or len(set(memory_namespaces.values())) != len(memory_namespaces):
        raise ValueError("campaign memory namespaces must be unique safe identifiers")
    if session.get("automatic_retries") != 0:
        raise ValueError("campaign session must disable automatic retries")
    if session.get("failure_policy") != "stop_sequence_no_retry":
        raise ValueError("campaign session failure policy must stop without retry")

    binding = {
        "schema_version": CAMPAIGN_BINDING_SCHEMA_VERSION,
        "campaign_id": plan["campaign_id"],
        "campaign_spec_sha256": expected_campaign_spec_sha256,
        "schedule_sha256": expected_schedule_sha256,
        "session_id": session["session_id"],
        "workload_label": session["workload_label"],
        "workload_id": session["workload_id"],
        "block_index": session["block_index"],
        "sequence_index": session["sequence_index"],
        "query_ids": [SUPPORTED_QUERY_ID],
        "method_order": list(order),
        "method_task_ids": method_task_ids,
        "memory_namespaces": memory_namespaces,
    }
    return methods, binding


def prepare_m15_live_campaign_session(
    *,
    campaign_config: str | Path,
    session_id: str,
    expected_campaign_spec_sha256: str,
    expected_schedule_sha256: str,
    workload_bundle: M15WorkloadBundle | str | Path,
    repo_root: str | Path | None = None,
) -> M15LiveCampaignSessionPreparation:
    """Validate a complete session binding without making an external call."""

    root = Path(repo_root).resolve() if repo_root is not None else _repo_root()
    if not _SAFE_ID.fullmatch(session_id):
        raise ValueError("session_id contains unsupported characters")
    spec_hash = _require_sha256(
        expected_campaign_spec_sha256,
        name="expected_campaign_spec_sha256",
    )
    schedule_hash = _require_sha256(
        expected_schedule_sha256,
        name="expected_schedule_sha256",
    )
    plan = compile_m15_campaign_file(campaign_config, repo_root=root).to_dict()
    session, workload_input = _select_session(plan, session_id=session_id)
    bundle = load_m15_workload_bundle(
        workload_bundle.root
        if isinstance(workload_bundle, M15WorkloadBundle)
        else workload_bundle
    )
    methods, binding = _validate_development_session(
        plan=plan,
        session=session,
        workload_input=workload_input,
        bundle=bundle,
        expected_campaign_spec_sha256=spec_hash,
        expected_schedule_sha256=schedule_hash,
    )
    return M15LiveCampaignSessionPreparation(
        repo_root=root,
        plan=plan,
        session=session,
        workload_input=workload_input,
        bundle=bundle,
        methods=methods,
        binding=binding,
    )


def run_m15_live_campaign_session(
    *,
    campaign_config: str | Path,
    session_id: str,
    expected_campaign_spec_sha256: str,
    expected_schedule_sha256: str,
    workload_bundle: M15WorkloadBundle | str | Path,
    output_root: str | Path = "runs",
    run_id: str | None = None,
    repo_root: str | Path | None = None,
    clients: Mapping[str, BackendClient] | None = None,
    bandwidth_bytes_per_ms: float = 1000.0,
    exchange_fixed_ms: float = 0.5,
    coordinator_row_ms: float = 0.001,
) -> M15LiveCampaignSessionRecord:
    """Execute one compiled development session with no automatic retry."""

    preparation = prepare_m15_live_campaign_session(
        campaign_config=campaign_config,
        session_id=session_id,
        expected_campaign_spec_sha256=expected_campaign_spec_sha256,
        expected_schedule_sha256=expected_schedule_sha256,
        workload_bundle=workload_bundle,
        repo_root=repo_root,
    )
    root = preparation.repo_root
    plan = preparation.plan
    session = preparation.session
    workload_input = preparation.workload_input
    bundle = preparation.bundle
    methods = preparation.methods
    binding = preparation.binding
    spec_hash = str(binding["campaign_spec_sha256"])
    schedule_hash = str(binding["schedule_sha256"])

    selected_run_id = run_id or f"m15-f2-live-session-{_now_slug()}"
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
            "schema_version": LIVE_CAMPAIGN_SESSION_SCHEMA_VERSION,
            "run_id": selected_run_id,
            "status": "running",
            "started_at": started_at,
        },
    )
    _write_json(run_root / "campaign_plan.json", plan)
    _write_json(run_root / "session_plan.json", session)
    _write_json(run_root / "campaign_binding.json", binding)

    matrix: M15LiveMethodMatrixRecord | None = None
    validation: dict[str, Any] | None = None
    error: str | None = None
    try:
        matrix = run_m15_live_method_matrix(
            workload_bundle=bundle,
            output_root=run_root,
            run_id="method-matrix-run",
            repo_root=root,
            clients=clients,
            bandwidth_bytes_per_ms=bandwidth_bytes_per_ms,
            exchange_fixed_ms=exchange_fixed_ms,
            coordinator_row_ms=coordinator_row_ms,
            method_order=methods,
            campaign_binding=binding,
        )
        if not matrix.success:
            raise RuntimeError(matrix.error or "campaign method sequence failed")
        matrix_manifest = json.loads(
            matrix.manifest_path.read_text(encoding="utf-8")
        )
        checks = {
            "matrix_method_order_matches_session": (
                matrix_manifest.get("method_order") == session["method_order"]
            ),
            "matrix_campaign_binding_matches": (
                matrix_manifest.get("campaign_binding") == binding
            ),
            "matrix_evidence_class_is_session_gate": (
                matrix_manifest.get("evidence_class")
                == "live_backend_campaign_session_engineering_gate"
            ),
            "matrix_all_methods_exact": all(
                isinstance(result, Mapping) and result.get("exact_answer") is True
                for result in matrix_manifest.get("methods", {}).values()
            ),
            "matrix_task_ids_match_compiled_measurements": all(
                result.get("task_id") == binding["method_task_ids"].get(method)
                for method, result in matrix_manifest.get("methods", {}).items()
                if isinstance(result, Mapping)
            ),
            "matrix_memory_namespaces_match_binding": (
                matrix_manifest.get("execution_namespaces", {}).get(
                    "logical_memory_namespaces"
                )
                == binding["memory_namespaces"]
            ),
            "matrix_call_budget_is_18": (
                json.loads(
                    (matrix.run_root / "backend_invocations.json").read_text(
                        encoding="utf-8"
                    )
                ).get("total_tool_invocations")
                == 18
            ),
            "paper_result_is_false": matrix_manifest.get("paper_result") is False,
            "automatic_retries_are_zero": (
                matrix_manifest.get("automatic_retries") == 0
            ),
        }
        validation = {"passed": all(checks.values()), "checks": checks}
        _write_json(run_root / "validation.json", validation)
        if not validation["passed"]:
            raise RuntimeError("live campaign-session validation failed")
    except Exception as exc:  # Persist first failure; never retry a session.
        error = str(exc)

    ended_at = _now()
    success = error is None
    _write_json(
        status_path,
        {
            "schema_version": LIVE_CAMPAIGN_SESSION_SCHEMA_VERSION,
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
            "schema_version": LIVE_CAMPAIGN_SESSION_SCHEMA_VERSION,
            "run_id": selected_run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
            "campaign_id": plan["campaign_id"],
            "campaign_spec_sha256": spec_hash,
            "schedule_sha256": schedule_hash,
            "session_id": session_id,
            "workload_input": workload_input,
            "workload_bundle": dict(bundle.manifest),
            "query_ids": [SUPPORTED_QUERY_ID],
            "method_order": [method.value for method in methods],
            "matrix": matrix.to_dict() if matrix is not None else None,
            "validation": validation,
            "artifacts": [
                "campaign_binding.json",
                "campaign_plan.json",
                "method-matrix-run",
                "run_manifest.json",
                "run_status.json",
                "session_plan.json",
                "validation.json",
            ],
            "automatic_retries": 0,
            "llm_calls": 0,
            "ontology_calls": 0,
            "evidence_class": "development_campaign_session_engineering_gate",
            "claim_boundary": {
                "multi_task_memory_stream": False,
                "counterbalance_complete": False,
                "contains_one_campaign_sequence": True,
                "comparative": False,
                "paper_result": False,
                "blocking_conditions": [
                    "single_query_stream_cannot_measure_cross_task_memory_reuse",
                    "one_session_does_not_complete_the_counterbalanced_campaign",
                    "query_id_is_not_yet_a_hash_bound_query_artifact",
                    "cost_model_is_uncalibrated",
                ],
            },
            "paper_result": False,
        },
    )
    return M15LiveCampaignSessionRecord(
        run_id=selected_run_id,
        run_root=run_root,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        error=error,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-config", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--expected-campaign-spec-sha256", required=True)
    parser.add_argument("--expected-schedule-sha256", required=True)
    parser.add_argument("--workload-bundle", required=True)
    parser.add_argument("--output-root", default="runs")
    parser.add_argument("--run-id")
    parser.add_argument("--repo-root")
    args = parser.parse_args(argv)
    if os.environ.get("XGAP_RUN_M15_LIVE_CAMPAIGN_SESSION") != "1":
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "error": (
                        "set XGAP_RUN_M15_LIVE_CAMPAIGN_SESSION=1 only inside "
                        "a verified session-scoped service lifecycle"
                    ),
                },
                sort_keys=True,
            )
        )
        return 3
    try:
        record = run_m15_live_campaign_session(
            campaign_config=args.campaign_config,
            session_id=args.session_id,
            expected_campaign_spec_sha256=args.expected_campaign_spec_sha256,
            expected_schedule_sha256=args.expected_schedule_sha256,
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
