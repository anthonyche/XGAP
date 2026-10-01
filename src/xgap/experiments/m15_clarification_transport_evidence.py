"""Independent deterministic audit of an M15-E5C clarification session."""

from __future__ import annotations

import copy
import json
import re
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
CLARIFICATION_TRANSPORT_COMPACT_EVIDENCE_SCHEMA_VERSION = (
    "m15-e5c-local-clarification-transport-evidence-v1"
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


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


def build_m15_clarification_transport_compact_evidence(
    *,
    git_commit: str,
    initial: M15ClarificationTransportSession,
    structurally_bound: M15ClarificationTransportSession,
    ready: M15ClarificationTransportSession,
    unavailable_structures: Mapping[str, M15ClarificationTransportSession],
    audit: M15ClarificationTransportEvidenceAudit,
) -> dict[str, Any]:
    """Build the compact, nonmeasurement E5C mechanism record."""

    if _COMMIT.fullmatch(git_commit) is None:
        raise ValueError("git_commit must be a full lowercase Git commit")
    initial_payload = initial.to_dict()
    structural_payload = structurally_bound.to_dict()
    ready_payload = ready.to_dict()
    audit_payload = audit.to_dict()
    expected_states = (
        (initial_payload, "awaiting_structural_clarification", 0),
        (structural_payload, "awaiting_predicate_base_authority", 1),
        (ready_payload, "ready_for_execution_handoff", 2),
    )
    for payload, status, event_count in expected_states:
        if (
            payload.get("status") != status
            or len(payload.get("authority_events", [])) != event_count
            or payload.get("source_contract") != ready_payload.get("source_contract")
        ):
            raise ValueError("clarification evidence session sequence is invalid")
        if content_hash(
            {
                key: value
                for key, value in payload.items()
                if key != "session_sha256"
            }
        ) != payload.get("session_sha256"):
            raise ValueError("clarification evidence session hash mismatch")
    handoff = ready_payload.get("execution_handoff")
    anchored = ready_payload.get("anchored_state")
    if (
        not isinstance(handoff, Mapping)
        or not isinstance(anchored, Mapping)
        or ready.execution_handoff is None
        or ready.anchored_frontier is None
        or audit_payload.get("success") is not True
        or audit_payload.get("session_sha256") != ready_payload["session_sha256"]
    ):
        raise ValueError("ready session or independent audit is invalid")
    unavailable: dict[str, dict[str, Any]] = {}
    for candidate_id, session in sorted(unavailable_structures.items()):
        payload = session.to_dict()
        if (
            payload.get("status") != "selected_structure_unavailable"
            or payload.get("execution_eligible") is not False
            or payload.get("execution_handoff") is not None
            or len(payload.get("authority_events", [])) != 1
            or payload.get("source_contract") != ready_payload["source_contract"]
            or payload["authority_events"][0].get("candidate_id") != candidate_id
        ):
            raise ValueError("unavailable structure evidence is invalid")
        unavailable[candidate_id] = {
            "status": payload["status"],
            "session_sha256": payload["session_sha256"],
            "execution_eligible": payload["execution_eligible"],
            "execution_handoff": payload["execution_handoff"],
            "active_interpretation_class_ids": payload["hierarchical_state"][
                "active_interpretation_class_ids"
            ],
        }
    structural_event = structural_payload["authority_events"][0]
    predicate_event = ready_payload["authority_events"][1]
    body = {
        "schema_version": CLARIFICATION_TRANSPORT_COMPACT_EVIDENCE_SCHEMA_VERSION,
        "git_commit": git_commit,
        "evidence_class": "controlled_local_nonmeasurement_mechanism",
        "source_contract": copy.deepcopy(ready_payload["source_contract"]),
        "transitions": {
            "initial": {
                "status": initial_payload["status"],
                "session_sha256": initial_payload["session_sha256"],
                "pending_question_sha256": initial_payload["pending_question"][
                    "question_sha256"
                ],
                "bounded_candidate_ids": [
                    item["candidate_id"]
                    for item in initial_payload["pending_question"]["options"]
                ],
                "execution_eligible": initial_payload["execution_eligible"],
            },
            "structural_authority": {
                "authority_event_sha256": structural_event[
                    "authority_event_sha256"
                ],
                "status": structural_payload["status"],
                "session_sha256": structural_payload["session_sha256"],
                "pending_question_sha256": structural_payload[
                    "pending_question"
                ]["question_sha256"],
                "bounded_candidate_ids": [
                    item["candidate_id"]
                    for item in structural_payload["pending_question"]["options"]
                ],
                "execution_eligible": structural_payload["execution_eligible"],
            },
            "predicate_base_authority": {
                "authority_event_sha256": predicate_event[
                    "authority_event_sha256"
                ],
                "status": ready_payload["status"],
                "session_sha256": ready_payload["session_sha256"],
                "session_state_sha256": ready_payload["session_state_sha256"],
                "authority_event_chain_sha256": ready_payload[
                    "authority_event_chain_sha256"
                ],
                "anchored_frontier_sha256": anchored[
                    "anchored_frontier_sha256"
                ],
                "returned_plan_ids": list(handoff["selected_plan_ids"]),
                "execution_handoff_sha256": handoff[
                    "execution_handoff_sha256"
                ],
                "selected_runtime_plan_sha256": {
                    item["plan_id"]: item["runtime_plan_sha256"]
                    for item in handoff["selected_plans"]
                },
                "execution_eligible": ready_payload["execution_eligible"],
            },
            "unavailable_structures": unavailable,
        },
        "audit": {
            "schema_version": audit_payload["schema_version"],
            "success": audit_payload["success"],
            "check_count": audit_payload["check_count"],
            "failed_check_ids": list(audit_payload["failed_check_ids"]),
            "audit_sha256": audit_payload["audit_sha256"],
            "source_session_mutated": audit_payload["source_session_mutated"],
        },
        "claim_boundary": {
            "development_artifacts_only": True,
            "hard_constraints_preserved": True,
            "conversation_text_used_as_authority": False,
            "current_query_profile_calls": 0,
            "backend_calls_made": 0,
            "llm_calls_made": 0,
            "ontology_service_calls_made": 0,
            "native_query_text_emitted": False,
            "automatic_retries": 0,
            "paper_result": False,
        },
        "paper_result": False,
    }
    return {**body, "artifact_sha256": content_hash(body)}
