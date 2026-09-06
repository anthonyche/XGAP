"""Independent deterministic audit of an M15-E5C clarification session."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_clarification_transport import (
    CLARIFICATION_TRANSPORT_SESSION_SCHEMA_VERSION,
    SELECTED_EXECUTION_HANDOFF_SCHEMA_VERSION,
    M15ClarificationTransportSession,
    compile_m15_clarification_transport_session,
)
from xgap.experiments.m15_direct_family_prediction import (
    M15DirectTrainingMemoryView,
)
from xgap.experiments.m15_direct_semantic_workload import (
    M15DirectSemanticWorkloadBundle,
)
from xgap.experiments.m15_resolution_execution_bridge import (
    M15ResolutionExecutionBridgePlan,
)
from xgap.runtime.tool import FEDERATED_EXECUTION_TOOL


CLARIFICATION_TRANSPORT_AUDIT_SCHEMA_VERSION = (
    "m15-e5c-clarification-transport-evidence-audit-v1"
)


@dataclass(frozen=True)
class M15ClarificationTransportEvidenceCheck:
    check_id: str
    passed: bool
    expected: Any
    observed: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "passed": self.passed,
            "expected": copy.deepcopy(self.expected),
            "observed": copy.deepcopy(self.observed),
        }


@dataclass(frozen=True)
class M15ClarificationTransportEvidenceAudit:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))

    @property
    def success(self) -> bool:
        return bool(self.payload["success"])

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(self.payload["failed_check_ids"])


def _check(
    checks: list[M15ClarificationTransportEvidenceCheck],
    check_id: str,
    expected: Any,
    observed: Any,
) -> None:
    checks.append(
        M15ClarificationTransportEvidenceCheck(
            check_id=check_id,
            passed=observed == expected,
            expected=expected,
            observed=observed,
        )
    )


def _portable_session(value: object) -> dict[str, Any]:
    if isinstance(value, M15ClarificationTransportSession):
        return value.to_dict()
    if not isinstance(value, Mapping):
        raise ValueError("clarification session must be an object")
    return copy.deepcopy(dict(value))


def audit_m15_clarification_transport_session(
    *,
    session: M15ClarificationTransportSession | Mapping[str, Any],
    bridge: M15ResolutionExecutionBridgePlan,
    workload: M15DirectSemanticWorkloadBundle,
    memory: M15DirectTrainingMemoryView,
    predictor_policy: Mapping[str, Any] | str | Path,
    interpretation_policy: Mapping[str, Any] | str | Path,
    ontology_path: str | Path,
    relaxation_policy: Mapping[str, Any] | str | Path,
    transport_policy: Mapping[str, Any] | str | Path,
) -> M15ClarificationTransportEvidenceAudit:
    """Reconstruct a portable session and audit its execution boundary."""

    raw = _portable_session(session)
    checks: list[M15ClarificationTransportEvidenceCheck] = []
    reconstructed: M15ClarificationTransportSession | None = None
    reconstruction_error: str | None = None
    try:
        reconstructed = compile_m15_clarification_transport_session(
            session_id=raw.get("session_id"),
            bridge=bridge,
            workload=workload,
            memory=memory,
            predictor_policy=predictor_policy,
            interpretation_policy=interpretation_policy,
            ontology_path=ontology_path,
            relaxation_policy=relaxation_policy,
            transport_policy=transport_policy,
            authority_events=raw.get("authority_events", []),
        )
    except Exception as exc:  # Audit preserves invalid evidence as a failed check.
        reconstruction_error = f"{type(exc).__name__}: {exc}"

    _check(
        checks,
        "session.schema",
        CLARIFICATION_TRANSPORT_SESSION_SCHEMA_VERSION,
        raw.get("schema_version"),
    )
    observed_session_hash = raw.get("session_sha256")
    computed_session_hash = None
    try:
        computed_session_hash = content_hash(
            {key: value for key, value in raw.items() if key != "session_sha256"}
        )
    except (TypeError, ValueError):
        computed_session_hash = "invalid_json"
    _check(
        checks,
        "session.hash",
        observed_session_hash,
        computed_session_hash,
    )
    _check(checks, "session.reconstruction_error", None, reconstruction_error)
    _check(
        checks,
        "session.exact_reconstruction",
        raw,
        reconstructed.to_dict() if reconstructed is not None else None,
    )

    state_body = {
        key: value
        for key, value in raw.items()
        if key
        not in {"session_sha256", "session_state_sha256", "execution_handoff"}
    }
    computed_state_hash = None
    try:
        computed_state_hash = content_hash(state_body)
    except (TypeError, ValueError):
        computed_state_hash = "invalid_json"
    _check(
        checks,
        "session.state_hash",
        raw.get("session_state_sha256"),
        computed_state_hash,
    )
    events = raw.get("authority_events")
    computed_event_chain = None
    if isinstance(events, list):
        try:
            computed_event_chain = content_hash(events)
        except (TypeError, ValueError):
            computed_event_chain = "invalid_json"
    _check(
        checks,
        "authority.event_chain_hash",
        raw.get("authority_event_chain_sha256"),
        computed_event_chain,
    )

    boundary = raw.get("claim_boundary")
    safe_boundary = isinstance(boundary, Mapping) and all(
        (
            boundary.get("hard_constraints_preserved") is True,
            boundary.get("authority_events_required") is True,
            boundary.get("conversation_text_used_as_authority") is False,
            boundary.get("answer_oracle_used_for_selection") is False,
            boundary.get("post_execution_measurements_used") is False,
            boundary.get("current_query_profile_calls") == 0,
            boundary.get("backend_calls_made") == 0,
            boundary.get("llm_calls_made") == 0,
            boundary.get("ontology_service_calls_made") == 0,
            boundary.get("native_query_text_emitted") is False,
            boundary.get("automatic_retries") == 0,
            boundary.get("paper_result") is False,
        )
    )
    _check(checks, "claim_boundary.zero_call_and_no_text_authority", True, safe_boundary)

    ready = raw.get("status") == "ready_for_execution_handoff"
    handoff = raw.get("execution_handoff")
    _check(
        checks,
        "handoff.presence_matches_ready_state",
        ready,
        isinstance(handoff, Mapping),
    )
    if ready and isinstance(handoff, Mapping):
        _check(
            checks,
            "handoff.schema",
            SELECTED_EXECUTION_HANDOFF_SCHEMA_VERSION,
            handoff.get("schema_version"),
        )
        observed_handoff_hash = handoff.get("execution_handoff_sha256")
        computed_handoff_hash = None
        try:
            computed_handoff_hash = content_hash(
                {
                    key: value
                    for key, value in handoff.items()
                    if key != "execution_handoff_sha256"
                }
            )
        except (TypeError, ValueError):
            computed_handoff_hash = "invalid_json"
        _check(
            checks,
            "handoff.hash",
            observed_handoff_hash,
            computed_handoff_hash,
        )
        anchored = raw.get("anchored_state")
        returned = (
            anchored.get("returned_interpretation_plans", [])
            if isinstance(anchored, Mapping)
            else []
        )
        expected_plan_ids = [
            item.get("plan_id") for item in returned if isinstance(item, Mapping)
        ]
        _check(
            checks,
            "handoff.all_and_only_returned_plan_ids",
            expected_plan_ids,
            handoff.get("selected_plan_ids"),
        )
        execution = handoff.get("execution_contract")
        _check(
            checks,
            "handoff.allowlisted_runtime_tool_only",
            [FEDERATED_EXECUTION_TOOL],
            execution.get("allowed_tools")
            if isinstance(execution, Mapping)
            else None,
        )
        serialized = json.dumps(handoff, sort_keys=True)
        _check(
            checks,
            "handoff.native_query_text_absent",
            False,
            " MATCH " in serialized or "SELECT " in serialized,
        )

    failed = [item.check_id for item in checks if not item.passed]
    body = {
        "schema_version": CLARIFICATION_TRANSPORT_AUDIT_SCHEMA_VERSION,
        "success": not failed,
        "session_id": raw.get("session_id"),
        "session_sha256": raw.get("session_sha256"),
        "bridge_plan_sha256": bridge.plan_hash,
        "check_count": len(checks),
        "failed_check_ids": failed,
        "checks": [item.to_dict() for item in checks],
        "reconstruction_error": reconstruction_error,
        "source_session_mutated": False,
        "paper_result": False,
    }
    return M15ClarificationTransportEvidenceAudit(
        {**body, "audit_sha256": content_hash(body)}
    )
