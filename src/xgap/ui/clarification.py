"""UI-safe projections of the E5C clarification and E5D submission contracts.

This module is deliberately presentation-only.  It does not parse natural
language, rank semantic candidates, compile plans, call backends, or construct
shell commands.  Candidate authority remains an explicit event created by the
E5C transport, and submission remains a typed ``remote.executor`` payload.
"""

from __future__ import annotations

import copy
import re
from pathlib import PurePosixPath
from typing import Any, Mapping

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_clarification_transport import (
    M15ClarificationTransportError,
    M15ClarificationTransportSession,
    build_m15_clarification_authority_event,
)
from xgap.experiments.remote_control import (
    SELECTED_SESSION_JOB_ENVIRONMENT_KEYS,
    SELECTED_SESSION_SBATCH_SCRIPT,
)


CLARIFICATION_VIEW_SCHEMA_VERSION = "m15-e6b-clarification-view-v1"
SELECTED_SESSION_SUBMISSION_PREVIEW_SCHEMA_VERSION = (
    "m15-e6b-selected-session-submission-preview-v1"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REMOTE_VALUE = re.compile(r"^[A-Za-z0-9._/:+-]{1,1024}$")
_SESSION_STATUSES = {
    "awaiting_structural_clarification",
    "awaiting_predicate_base_authority",
    "selected_structure_unavailable",
    "ready_for_execution_handoff",
}


class M15ClarificationUiError(ValueError):
    """Raised before display or submission when the UI contract drifts."""


def _session_payload(
    session: M15ClarificationTransportSession,
) -> dict[str, Any]:
    if not isinstance(session, M15ClarificationTransportSession):
        raise M15ClarificationUiError(
            "clarification UI requires a typed E5C transport session"
        )
    payload = session.to_dict()
    observed_hash = payload.get("session_sha256")
    if (
        not isinstance(observed_hash, str)
        or not _SHA256.fullmatch(observed_hash)
        or content_hash(
            {
                key: value
                for key, value in payload.items()
                if key != "session_sha256"
            }
        )
        != observed_hash
    ):
        raise M15ClarificationUiError("clarification session hash mismatch")
    if payload.get("status") not in _SESSION_STATUSES:
        raise M15ClarificationUiError("clarification session status is unsupported")
    boundary = payload.get("claim_boundary")
    if not isinstance(boundary, Mapping) or (
        boundary.get("conversation_text_used_as_authority") is not False
        or boundary.get("native_query_text_emitted") is not False
        or boundary.get("paper_result") is not False
    ):
        raise M15ClarificationUiError("clarification session boundary changed")
    return payload


def _question_view(
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    question = payload.get("pending_question")
    if question is None:
        return None
    if not isinstance(question, Mapping):
        raise M15ClarificationUiError("pending clarification question is invalid")
    question_payload = copy.deepcopy(dict(question))
    observed_hash = question_payload.get("question_sha256")
    if (
        not isinstance(observed_hash, str)
        or not _SHA256.fullmatch(observed_hash)
        or content_hash(
            {
                key: value
                for key, value in question_payload.items()
                if key != "question_sha256"
            }
        )
        != observed_hash
    ):
        raise M15ClarificationUiError("pending clarification question hash mismatch")
    if (
        question_payload.get("session_id") != payload.get("session_id")
        or question_payload.get("authoritative_response_required") is not True
        or question_payload.get("conversation_text_is_authoritative") is not False
    ):
        raise M15ClarificationUiError("pending question authority boundary changed")
    raw_options = question_payload.get("options")
    if not isinstance(raw_options, list) or not raw_options:
        raise M15ClarificationUiError("pending question has no bounded options")
    options: list[dict[str, str]] = []
    candidate_ids: set[str] = set()
    for raw in raw_options:
        if not isinstance(raw, Mapping) or set(raw) != {"candidate_id", "label"}:
            raise M15ClarificationUiError("clarification option fields changed")
        candidate_id = raw.get("candidate_id")
        label = raw.get("label")
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or candidate_id in candidate_ids
            or not isinstance(label, str)
            or not label
        ):
            raise M15ClarificationUiError("clarification option is invalid")
        candidate_ids.add(candidate_id)
        options.append({"candidate_id": candidate_id, "label": label})
    return {
        "question_id": question_payload["question_id"],
        "question_sha256": observed_hash,
        "sequence": question_payload["sequence"],
        "hole_id": question_payload["hole_id"],
        "role": question_payload["role"],
        "prompt": question_payload["question"],
        "options": options,
        "reason_codes": copy.deepcopy(question_payload["reason_codes"]),
        "varying_structural_dimensions": copy.deepcopy(
            question_payload["varying_structural_dimensions"]
        ),
        "response_contract": "explicit_candidate_id_only",
    }


def _handoff_view(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    handoff = payload.get("execution_handoff")
    if handoff is None:
        return None
    if not isinstance(handoff, Mapping):
        raise M15ClarificationUiError("execution handoff is invalid")
    selected_plan_ids = handoff.get("selected_plan_ids")
    counts = handoff.get("counts")
    if (
        not isinstance(selected_plan_ids, list)
        or not selected_plan_ids
        or not isinstance(counts, Mapping)
    ):
        raise M15ClarificationUiError("execution handoff summary is invalid")
    return {
        "execution_handoff_sha256": handoff["execution_handoff_sha256"],
        "selected_plan_ids": copy.deepcopy(selected_plan_ids),
        "selected_plan_count": counts["selected_runtime_plans"],
        "expected_remote_calls": counts["expected_remote_calls"],
        "current_query_profile_calls": counts["current_query_profile_calls"],
        "execution_order": handoff["execution_contract"]["execution_order"],
    }


def build_m15_clarification_view(
    session: M15ClarificationTransportSession,
) -> dict[str, Any]:
    """Project one E5C state into a bounded, UI-safe view model."""

    payload = _session_payload(session)
    question = _question_view(payload)
    handoff = _handoff_view(payload)
    status = payload["status"]
    if status.startswith("awaiting_") and question is None:
        raise M15ClarificationUiError("awaiting session has no pending question")
    if payload["terminal"] and question is not None:
        raise M15ClarificationUiError("terminal session still has a pending question")
    if status == "ready_for_execution_handoff":
        if payload["execution_eligible"] is not True or handoff is None:
            raise M15ClarificationUiError("ready session has no executable handoff")
    elif handoff is not None:
        raise M15ClarificationUiError("non-ready session exposes an execution handoff")
    body = {
        "schema_version": CLARIFICATION_VIEW_SCHEMA_VERSION,
        "session_id": payload["session_id"],
        "session_sha256": payload["session_sha256"],
        "status": status,
        "terminal": payload["terminal"],
        "execution_eligible": payload["execution_eligible"],
        "authority_event_count": len(payload["authority_events"]),
        "question": question,
        "execution_handoff": handoff,
        "ui_contract": {
            "candidate_selection_by_id": True,
            "free_text_is_authority": False,
            "native_query_text_exposed": False,
            "direct_backend_or_model_access": False,
            "paper_result": False,
        },
        "paper_result": False,
    }
    return {**body, "view_sha256": content_hash(body)}


def build_m15_clarification_selection_event(
    *,
    session: M15ClarificationTransportSession,
    event_id: str,
    candidate_id: str,
    authority_source_id: str,
) -> dict[str, Any]:
    """Translate one button choice into the existing bounded E5C event."""

    _session_payload(session)
    try:
        return build_m15_clarification_authority_event(
            session=session,
            event_id=event_id,
            candidate_id=candidate_id,
            authority_source_id=authority_source_id,
        )
    except M15ClarificationTransportError as exc:
        raise M15ClarificationUiError(str(exc)) from exc


def _remote_memory_path(value: str) -> str:
    if not isinstance(value, str) or not _SAFE_REMOTE_VALUE.fullmatch(value):
        raise M15ClarificationUiError("remote training-memory path is unsafe")
    path = PurePosixPath(value)
    if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        raise M15ClarificationUiError(
            "remote training-memory path must be absolute and normalized"
        )
    return str(path)


def build_m15_selected_session_submission_preview(
    *,
    session: M15ClarificationTransportSession,
    remote_training_memory_path: str,
    expected_training_memory_sha256: str,
) -> dict[str, Any]:
    """Build a typed E5D submit preview from one ready E5C session."""

    payload = _session_payload(session)
    view = build_m15_clarification_view(session)
    if payload["status"] != "ready_for_execution_handoff":
        raise M15ClarificationUiError(
            "only a ready clarification session may be submitted"
        )
    events = payload.get("authority_events")
    if not isinstance(events, list) or len(events) != 2:
        raise M15ClarificationUiError("ready session must have two authority events")
    by_hole = {event.get("hole_id"): event for event in events}
    if set(by_hole) != {"relationship-strength", "transfer-predicate"}:
        raise M15ClarificationUiError("authority event roles changed")
    authority_sources = {event.get("authority_source_id") for event in events}
    if len(authority_sources) != 1 or not all(
        isinstance(item, str) and item for item in authority_sources
    ):
        raise M15ClarificationUiError(
            "E5D requires one shared explicit authority source"
        )
    expected_hash = expected_training_memory_sha256
    if not isinstance(expected_hash, str) or not _SHA256.fullmatch(expected_hash):
        raise M15ClarificationUiError("expected training-memory hash is invalid")
    source_contract = payload.get("source_contract")
    if (
        not isinstance(source_contract, Mapping)
        or source_contract.get("training_memory_view_sha256") != expected_hash
    ):
        raise M15ClarificationUiError(
            "training-memory hash differs from the clarification session"
        )
    environment = {
        "XGAP_M15_SELECTED_TRAINING_MEMORY": _remote_memory_path(
            remote_training_memory_path
        ),
        "XGAP_M15_SELECTED_MEMORY_SHA256": expected_hash,
        "XGAP_M15_SELECTED_SESSION_ID": payload["session_id"],
        "XGAP_M15_SELECTED_STRUCTURAL_CANDIDATE": by_hole[
            "relationship-strength"
        ]["candidate_id"],
        "XGAP_M15_SELECTED_PREDICATE_CANDIDATE": by_hole[
            "transfer-predicate"
        ]["candidate_id"],
        "XGAP_M15_SELECTED_AUTHORITY_SOURCE_ID": next(
            iter(authority_sources)
        ),
    }
    if set(environment) != set(SELECTED_SESSION_JOB_ENVIRONMENT_KEYS) or any(
        not isinstance(value, str) or not _SAFE_REMOTE_VALUE.fullmatch(value)
        for value in environment.values()
    ):
        raise M15ClarificationUiError(
            "selected-session environment is outside the fixed envelope"
        )
    remote_payload = {
        "script": SELECTED_SESSION_SBATCH_SCRIPT,
        "environment": environment,
    }
    body = {
        "schema_version": SELECTED_SESSION_SUBMISSION_PREVIEW_SCHEMA_VERSION,
        "session_id": payload["session_id"],
        "session_sha256": payload["session_sha256"],
        "authority_event_chain_sha256": payload[
            "authority_event_chain_sha256"
        ],
        "execution_handoff_sha256": payload["execution_handoff"][
            "execution_handoff_sha256"
        ],
        "selected_plan_ids": view["execution_handoff"]["selected_plan_ids"],
        "remote_operation": "submit_job",
        "remote_payload": remote_payload,
        "confirmation_required": True,
        "submission_contract": {
            "script_scoped_environment": True,
            "generic_environment_editor": False,
            "shell_command_constructed": False,
            "credentials_in_payload": False,
            "native_query_text_exposed": False,
            "paper_result": False,
        },
        "paper_result": False,
    }
    return {**body, "submission_preview_sha256": content_hash(body)}
