"""Run an E5C-selected semantic frontier through the bounded agent runtime.

This is the first live E5 data-plane gate.  Explicit authority events and a
historical family-memory view are sealed before service startup.  The live
phase exposes one tool to one finite goal and executes all and only the plans
present in the E5C handoff, in selection-rank order, without retrying.
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

from xgap.agent import (
    AgentEnvironment,
    GoalLoop,
    GoalSpec,
    GoalStatus,
    InMemoryStore,
    PlannedToolCall,
    SequentialToolPolicy,
)
from xgap.backends.protocol import BackendClient
from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_clarification_transport import (
    M15ClarificationTransportSession,
    advance_m15_clarification_transport_session,
    build_m15_clarification_authority_event,
    compile_m15_clarification_transport_session,
)
from xgap.experiments.m15_direct_family_prediction import (
    M15DirectTrainingMemoryView,
    load_m15_direct_training_memory_view,
)
from xgap.experiments.m15_live_adaptive import RecordingBackendPlugin
from xgap.experiments.m15_live_resolution_execution_bridge import (
    M15PreparedResolutionExecutionBridge,
    prepare_m15_resolution_execution_bridge,
)
from xgap.experiments.m15_parameterized_federation import (
    load_m15_parameterized_instance,
)
from xgap.runtime import (
    FEDERATED_EXECUTION_TOOL,
    FederatedExecutionTool,
    FederatedScheduler,
)
from xgap.tools import (
    BackendInvokeTool,
    BackendPluginRegistry,
    NativeBackendPlugin,
    ToolRegistry,
)


LIVE_SELECTED_SESSION_POLICY_SCHEMA_VERSION = (
    "m15-e5d-live-selected-session-policy-v1"
)
LIVE_SELECTED_SESSION_SCHEMA_VERSION = (
    "m15-e5d-live-selected-interpretation-session-v1"
)
SELECTED_SESSION_PREFLIGHT_SCHEMA_VERSION = (
    "m15-e5d-selected-interpretation-session-preflight-v1"
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class M15LiveSelectedInterpretationSessionError(ValueError):
    """Raised before execution when an E5D input or seal drifts."""


@dataclass(frozen=True)
class M15PreparedSelectedInterpretationSession:
    resolution_bridge: M15PreparedResolutionExecutionBridge
    memory: M15DirectTrainingMemoryView
    clarification_session: M15ClarificationTransportSession
    source_paths: Mapping[str, Path]
    expected_memory_view_sha256: str

    def reconstruct_session(self) -> M15ClarificationTransportSession:
        memory = load_m15_direct_training_memory_view(
            self.source_paths["training_memory"],
            workload=self.resolution_bridge.reload_workload(),
            expected_memory_view_sha256=self.expected_memory_view_sha256,
        )
        payload = self.clarification_session.to_dict()
        return compile_m15_clarification_transport_session(
            session_id=payload["session_id"],
            bridge=self.resolution_bridge.bridge,
            workload=self.resolution_bridge.workload,
            memory=memory,
            predictor_policy=self.source_paths["predictor_policy"],
            interpretation_policy=self.source_paths["interpretation_policy"],
            ontology_path=self.source_paths["ontology"],
            relaxation_policy=self.source_paths["relaxation_policy"],
            transport_policy=self.source_paths["transport_policy"],
            authority_events=payload["authority_events"],
        )


@dataclass(frozen=True)
class M15LiveSelectedInterpretationSessionRecord:
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular_file(value: str | Path, *, name: str) -> Path:
    source = Path(value)
    if source.is_symlink() or not source.is_file():
        raise M15LiveSelectedInterpretationSessionError(
            f"{name} must be a regular non-symbolic-link file"
        )
    return source.resolve()


def _json_object(value: str | Path, *, name: str) -> dict[str, Any]:
    path = _regular_file(value, name=name)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise M15LiveSelectedInterpretationSessionError(
            f"{name} is not valid JSON"
        ) from exc
    if not isinstance(raw, Mapping):
        raise M15LiveSelectedInterpretationSessionError(
            f"{name} must be a JSON object"
        )
    return dict(raw)


def _policy(value: str | Path) -> dict[str, Any]:
    raw = _json_object(value, name="E5D live selected-session policy")
    expected = {
        "schema_version",
        "policy_id",
        "purpose",
        "selection_source",
        "prediction_source",
        "authority_source_kind",
        "required_structural_candidate",
        "allowed_predicate_candidates",
        "allowed_tools",
        "one_goal_per_session",
        "execution_order",
        "stop_after_first_failed_plan",
        "backend_timeout_seconds",
        "sealed_before_service_start",
        "answer_oracle_opened_after_all_successful_executions",
        "current_query_profile_calls",
        "llm_calls_made",
        "ontology_service_calls_made",
        "automatic_retries",
        "paper_result",
    }
    if set(raw) != expected:
        raise M15LiveSelectedInterpretationSessionError(
            "E5D policy fields do not match the contract"
        )
    if raw != {
        "schema_version": LIVE_SELECTED_SESSION_POLICY_SCHEMA_VERSION,
        "policy_id": "m15-e5d-r1-family-memory-selected-execution-v1",
        "purpose": "execute_only_user_authorized_semantic_frontier_plans",
        "selection_source": "sealed_e5c_clarification_transport_handoff",
        "prediction_source": "historical_family_memory_only",
        "authority_source_kind": "explicit_user_input",
        "required_structural_candidate": (
            "constraint:single-transfer-at-least-50000"
        ),
        "allowed_predicate_candidates": [
            "predicate:transferred_to",
            "predicate:paid_to",
        ],
        "allowed_tools": [FEDERATED_EXECUTION_TOOL],
        "one_goal_per_session": True,
        "execution_order": "selection_rank",
        "stop_after_first_failed_plan": True,
        "backend_timeout_seconds": 60,
        "sealed_before_service_start": True,
        "answer_oracle_opened_after_all_successful_executions": True,
        "current_query_profile_calls": 0,
        "llm_calls_made": 0,
        "ontology_service_calls_made": 0,
        "automatic_retries": 0,
        "paper_result": False,
    }:
        raise M15LiveSelectedInterpretationSessionError(
            "E5D live selected-session policy changed"
        )
    return raw


def _safe_id(value: str, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15LiveSelectedInterpretationSessionError(
            f"{name} is not a safe identifier"
        )
    return value


def _expected_hash(value: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise M15LiveSelectedInterpretationSessionError(
            "expected training memory hash is not a SHA-256 digest"
        )
    return value


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


def prepare_m15_selected_interpretation_session(
    *,
    resolution_run_path: str | Path,
    bridge_spec_path: str | Path,
    workload_destination: str | Path,
    training_memory_path: str | Path,
    expected_training_memory_sha256: str,
    predictor_policy_path: str | Path,
    interpretation_policy_path: str | Path,
    ontology_path: str | Path,
    relaxation_policy_path: str | Path,
    transport_policy_path: str | Path,
    live_policy_path: str | Path,
    session_id: str,
    structural_candidate_id: str,
    predicate_candidate_id: str,
    authority_source_id: str,
    repo_root: str | Path,
) -> M15PreparedSelectedInterpretationSession:
    """Seal historical memory, explicit authority, and selected plans."""

    root = Path(repo_root).resolve()
    policy = _policy(live_policy_path)
    structural = _safe_id(
        structural_candidate_id, name="structural_candidate_id"
    )
    predicate = _safe_id(predicate_candidate_id, name="predicate_candidate_id")
    authority = _safe_id(authority_source_id, name="authority_source_id")
    if structural != policy["required_structural_candidate"]:
        raise M15LiveSelectedInterpretationSessionError(
            "E5D requires the executable R1 single-transfer structure"
        )
    if predicate not in policy["allowed_predicate_candidates"]:
        raise M15LiveSelectedInterpretationSessionError(
            "predicate candidate is outside the bounded authority set"
        )
    expected_memory = _expected_hash(expected_training_memory_sha256)
    source_paths = {
        "training_memory": _regular_file(
            training_memory_path, name="historical training memory"
        ),
        "predictor_policy": _regular_file(
            predictor_policy_path, name="predictor policy"
        ),
        "interpretation_policy": _regular_file(
            interpretation_policy_path, name="interpretation policy"
        ),
        "ontology": _regular_file(ontology_path, name="resolution ontology"),
        "relaxation_policy": _regular_file(
            relaxation_policy_path, name="relaxation policy"
        ),
        "transport_policy": _regular_file(
            transport_policy_path, name="clarification transport policy"
        ),
        "live_policy": _regular_file(live_policy_path, name="E5D live policy"),
    }
    prepared_bridge = prepare_m15_resolution_execution_bridge(
        resolution_run_path=resolution_run_path,
        bridge_spec_path=bridge_spec_path,
        workload_destination=workload_destination,
        repo_root=root,
    )
    memory = load_m15_direct_training_memory_view(
        source_paths["training_memory"],
        workload=prepared_bridge.workload,
        expected_memory_view_sha256=expected_memory,
    )
    common = {
        "bridge": prepared_bridge.bridge,
        "workload": prepared_bridge.workload,
        "memory": memory,
        "predictor_policy": source_paths["predictor_policy"],
        "interpretation_policy": source_paths["interpretation_policy"],
        "ontology_path": source_paths["ontology"],
        "relaxation_policy": source_paths["relaxation_policy"],
        "transport_policy": source_paths["transport_policy"],
    }
    initial = compile_m15_clarification_transport_session(
        session_id=_safe_id(session_id, name="session_id"),
        **common,
    )
    structural_event = build_m15_clarification_authority_event(
        session=initial,
        event_id=f"{session_id}:authority:relationship-strength",
        candidate_id=structural,
        authority_source_id=authority,
    )
    structurally_bound = advance_m15_clarification_transport_session(
        session=initial,
        authority_event=structural_event,
        **common,
    )
    predicate_event = build_m15_clarification_authority_event(
        session=structurally_bound,
        event_id=f"{session_id}:authority:transfer-predicate",
        candidate_id=predicate,
        authority_source_id=authority,
    )
    ready = advance_m15_clarification_transport_session(
        session=structurally_bound,
        authority_event=predicate_event,
        **common,
    )
    if (
        ready.to_dict()["status"] != "ready_for_execution_handoff"
        or ready.execution_handoff is None
    ):
        raise M15LiveSelectedInterpretationSessionError(
            "explicit authority did not produce an executable E5C handoff"
        )
    return M15PreparedSelectedInterpretationSession(
        resolution_bridge=prepared_bridge,
        memory=memory,
        clarification_session=ready,
        source_paths=source_paths,
        expected_memory_view_sha256=expected_memory,
    )


def build_m15_selected_session_preflight(
    prepared: M15PreparedSelectedInterpretationSession,
) -> dict[str, Any]:
    """Build the immutable service-start preflight record."""

    session = prepared.clarification_session.to_dict()
    handoff = session["execution_handoff"]
    body = {
        "schema_version": SELECTED_SESSION_PREFLIGHT_SCHEMA_VERSION,
        "session_id": session["session_id"],
        "session_sha256": session["session_sha256"],
        "authority_event_chain_sha256": session["authority_event_chain_sha256"],
        "execution_handoff_sha256": handoff["execution_handoff_sha256"],
        "bridge_plan_sha256": handoff["bridge_plan_sha256"],
        "training_memory_view_sha256": prepared.memory.memory_view_hash,
        "selected_plan_ids": list(handoff["selected_plan_ids"]),
        "selected_plan_count": len(handoff["selected_plan_ids"]),
        "expected_remote_calls": handoff["counts"]["expected_remote_calls"],
        "source_file_sha256": {
            key: _sha256_file(path)
            for key, path in sorted(prepared.source_paths.items())
        },
        "sealed_before_service_start": True,
        "backend_calls_before_seal": 0,
        "current_query_profile_calls": 0,
        "answer_oracle_opened_before_seal": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    return {**body, "preflight_sha256": content_hash(body)}


def run_m15_live_selected_interpretation_session(
    *,
    prepared: M15PreparedSelectedInterpretationSession,
    clients: Mapping[str, BackendClient],
    output_root: str | Path,
    run_id: str = "selected-interpretation-session-run",
    repo_root: str | Path | None = None,
) -> M15LiveSelectedInterpretationSessionRecord:
    """Execute the sealed E5C handoff through one finite agent goal."""

    root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else Path(__file__).resolve().parents[3]
    )
    _safe_id(run_id, name="run_id")
    if set(clients) != {"neo4j", "fuseki"}:
        raise M15LiveSelectedInterpretationSessionError(
            "live selected session requires exactly neo4j and fuseki clients"
        )
    reconstructed = prepared.reconstruct_session()
    if reconstructed.to_dict() != prepared.clarification_session.to_dict():
        raise M15LiveSelectedInterpretationSessionError(
            "prepared clarification session does not reconstruct exactly"
        )
    handoff = reconstructed.execution_handoff
    if handoff is None:
        raise M15LiveSelectedInterpretationSessionError(
            "prepared clarification session has no execution handoff"
        )
    handoff_payload = handoff.to_dict()
    selected_ids = list(handoff_payload["selected_plan_ids"])
    if not selected_ids or list(handoff.plans) != selected_ids:
        raise M15LiveSelectedInterpretationSessionError(
            "selected plans differ from the sealed execution order"
        )

    destination = Path(output_root)
    if not destination.is_absolute():
        destination = root / destination
    run_root = destination.resolve() / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    status_path = run_root / "run_status.json"
    manifest_path = run_root / "run_manifest.json"
    result_path = run_root / "execution_results.json"
    started_at = _now()
    _write_json(
        status_path,
        {
            "schema_version": LIVE_SELECTED_SESSION_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "running",
            "started_at": started_at,
        },
    )
    session_payload = reconstructed.to_dict()
    _write_json(run_root / "clarification_session.json", session_payload)
    _write_json(run_root / "authority_events.json", session_payload["authority_events"])
    _write_json(run_root / "execution_handoff.json", handoff_payload)

    events: list[dict[str, Any]] = []
    health: dict[str, Any] = {}
    execution_results: list[dict[str, Any]] = []
    checks: dict[str, bool] = {}
    answer_oracle_opened = False
    error: str | None = None
    goal_state = None
    execution_memory = InMemoryStore()
    try:
        for backend_id in ("neo4j", "fuseki"):
            health[backend_id] = clients[backend_id].healthcheck().to_dict()
        _write_json(run_root / "health.json", health)
        if not all(item["ok"] for item in health.values()):
            raise RuntimeError("selected-session backend healthcheck failed")

        registry = ToolRegistry()
        registry.register(
            FederatedExecutionTool(
                FederatedScheduler(_backend_tool(clients, events))
            )
        )
        environment = AgentEnvironment(
            environment_id="m15-e5d-live-federated-graph-environment",
            tools=registry,
            memory=execution_memory,
            metadata={
                "session_sha256": session_payload["session_sha256"],
                "execution_handoff_sha256": handoff_payload[
                    "execution_handoff_sha256"
                ],
                "selected_plan_ids": selected_ids,
                "selection_source": (
                    "sealed_e5c_clarification_transport_handoff"
                ),
            },
        )
        goal = GoalSpec(
            goal_id=f"{run_id}:execute-selected-semantic-frontier",
            objective=(
                "execute all and only user-authorized semantic frontier plans "
                "over the registered graph backends"
            ),
            success_criteria=(
                "invoke one allowlisted runtime tool call per selected plan",
                "preserve selection-rank order",
                "stop after the first failed plan without retrying",
            ),
            allowed_tools=(FEDERATED_EXECUTION_TOOL,),
            max_steps=len(selected_ids) + 1,
            max_tool_calls=len(selected_ids),
            metadata={
                "session_sha256": session_payload["session_sha256"],
                "execution_handoff_sha256": handoff_payload[
                    "execution_handoff_sha256"
                ],
                "current_query_profile_calls": 0,
                "automatic_retries": 0,
            },
        )
        calls = tuple(
            PlannedToolCall(
                call_id=f"execute-selected-plan-{rank:02d}",
                tool_name=FEDERATED_EXECUTION_TOOL,
                arguments={"plan": handoff.plans[plan_id].to_dict()},
            )
            for rank, plan_id in enumerate(selected_ids, 1)
        )
        _write_json(run_root / "goal_spec.json", goal.to_dict())
        _write_json(
            run_root / "planned_execution.json",
            {
                "selected_plan_ids": selected_ids,
                "call_ids": [call.call_id for call in calls],
                "allowed_tools": [FEDERATED_EXECUTION_TOOL],
                "plan_arguments_persisted": False,
            },
        )
        goal_state = GoalLoop().run(
            goal,
            SequentialToolPolicy(calls),
            environment,
        )
        _write_json(run_root / "goal_state.json", goal_state.to_dict())
        _write_json(
            run_root / "execution_memory.json",
            [record.to_dict() for record in execution_memory.records()],
        )

        tool_observations = [
            item
            for item in goal_state.observations
            if item.kind == "tool_result"
        ]
        for plan_id, observation in zip(selected_ids, tool_observations):
            value = observation.payload.get("value")
            execution_results.append(
                {
                    "plan_id": plan_id,
                    "semantic_class_id": next(
                        item["interpretation_class_id"]
                        for item in handoff_payload["selected_plans"]
                        if item["plan_id"] == plan_id
                    ),
                    "query_id": next(
                        item["query_id"]
                        for item in handoff_payload["selected_plans"]
                        if item["plan_id"] == plan_id
                    ),
                    "physical_strategy": next(
                        item["physical_strategy"]
                        for item in handoff_payload["selected_plans"]
                        if item["plan_id"] == plan_id
                    ),
                    "tool_status": observation.payload["status"],
                    "runtime_result": value,
                    "expected_final_row_count": None,
                    "exact_oracle_answer": None,
                }
            )
        if goal_state.status is not GoalStatus.SUCCEEDED:
            raise RuntimeError(
                "selected-plan agent goal did not succeed: "
                f"{goal_state.status.value}: {goal_state.message}"
            )

        instances = {
            item["query_id"]: load_m15_parameterized_instance(
                prepared.resolution_bridge.workload.workload_bundle,
                item["query_id"],
            )
            for item in handoff_payload["selected_plans"]
        }
        answer_oracle_opened = True
        for item in execution_results:
            oracle = instances[item["query_id"]]["final_oracle"]
            final_rows = item["runtime_result"]["final_rows"]
            item["expected_final_row_count"] = len(oracle)
            item["exact_oracle_answer"] = final_rows == oracle

        memory_records = [record.to_dict() for record in execution_memory.records()]
        portable_text = json.dumps(
            {
                "session": session_payload,
                "handoff": handoff_payload,
            },
            sort_keys=True,
        )
        checks = {
            "session_reconstructed_exactly": reconstructed.to_dict()
            == prepared.clarification_session.to_dict(),
            "handoff_ready": session_payload["status"]
            == "ready_for_execution_handoff",
            "all_and_only_selected_plans_observed": [
                item["plan_id"] for item in execution_results
            ]
            == selected_ids,
            "goal_succeeded": goal_state.status is GoalStatus.SUCCEEDED,
            "one_tool_call_per_selected_plan": goal_state.tool_calls
            == len(selected_ids),
            "allowlisted_runtime_tool_only": all(
                item.tool_name == FEDERATED_EXECUTION_TOOL
                for item in goal_state.trace
                if item.tool_name is not None
            ),
            "execution_memory_complete": len(memory_records)
            == len(selected_ids),
            "all_runtime_success": all(
                item["runtime_result"]["success"]
                for item in execution_results
            ),
            "all_exact_oracle_answers": all(
                item["exact_oracle_answer"] for item in execution_results
            ),
            "two_remote_calls_per_plan": all(
                item["runtime_result"]["total_remote_calls"] == 2
                for item in execution_results
            ),
            "exact_backend_invocation_count": len(events)
            == 2 * len(selected_ids),
            "execute_operations_only": all(
                item["operation"] == "execute" for item in events
            ),
            "no_native_text_in_control_plane": " MATCH " not in portable_text
            and "SELECT " not in portable_text,
            "hard_constraints_preserved": session_payload["claim_boundary"][
                "hard_constraints_preserved"
            ]
            is True,
            "answer_oracle_opened_post_execution": answer_oracle_opened,
            "zero_current_query_profiles": session_payload["claim_boundary"][
                "current_query_profile_calls"
            ]
            == 0,
            "no_automatic_retry": len(events) == 2 * len(execution_results),
        }
        _write_json(
            run_root / "validation.json",
            {"passed": all(checks.values()), "checks": checks},
        )
        if not all(checks.values()):
            raise RuntimeError("live selected-session validation failed")
    except Exception as exc:  # Preserve the first failure; never retry.
        error = str(exc)
        if not (run_root / "health.json").exists():
            _write_json(run_root / "health.json", health)
        if goal_state is not None and not (run_root / "goal_state.json").exists():
            _write_json(run_root / "goal_state.json", goal_state.to_dict())

    _write_json(result_path, {"results": execution_results})
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
            "schema_version": LIVE_SELECTED_SESSION_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    runtime_results = [
        item["runtime_result"]
        for item in execution_results
        if isinstance(item.get("runtime_result"), Mapping)
    ]
    _write_json(
        manifest_path,
        {
            "schema_version": LIVE_SELECTED_SESSION_SCHEMA_VERSION,
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
            "session_sha256": session_payload["session_sha256"],
            "authority_event_chain_sha256": session_payload[
                "authority_event_chain_sha256"
            ],
            "execution_handoff_sha256": handoff_payload[
                "execution_handoff_sha256"
            ],
            "training_memory_view_sha256": prepared.memory.memory_view_hash,
            "selected_plan_ids": selected_ids,
            "summary": {
                "selected_semantic_plan_count": len(selected_ids),
                "physical_plan_run_count": len(execution_results),
                "goal_tool_calls": goal_state.tool_calls if goal_state else 0,
                "total_remote_calls": sum(
                    item.get("total_remote_calls", 0) for item in runtime_results
                ),
                "total_bytes_moved": sum(
                    item.get("total_bytes_moved", 0) for item in runtime_results
                ),
                "final_row_counts": [
                    len(item.get("final_rows", [])) for item in runtime_results
                ],
            },
            "validation": {
                "passed": bool(checks) and all(checks.values()),
                "checks": checks,
            },
            "evidence_class": "live_selected_interpretation_mechanism_gate",
            "selection_sealed_before_live_execution": True,
            "historical_family_memory_only": True,
            "answer_oracle_used_for_selection": False,
            "answer_oracle_opened_after_all_successful_executions": (
                answer_oracle_opened
            ),
            "current_query_profile_calls": 0,
            "llm_calls_made": 0,
            "ontology_service_calls_made": 0,
            "automatic_retries": 0,
            "paper_result": False,
            "artifacts": sorted(path.name for path in run_root.iterdir()),
        },
    )
    return M15LiveSelectedInterpretationSessionRecord(
        run_id=run_id,
        run_root=run_root,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        result_path=result_path,
        error=error,
    )
