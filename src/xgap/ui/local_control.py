"""Thread-safe local controller for the XGAP clarification working surface.

The browser never owns semantic authority or remote credentials.  This
controller binds visible actions to a typed E5C session, keeps the authority
source server-side, and delegates the final operation to a typed submitter.
"""

from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable, Mapping, Protocol

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_clarification_transport import (
    M15ClarificationTransportSession,
)
from xgap.experiments.remote_control import (
    SELECTED_SESSION_JOB_ENVIRONMENT_KEYS,
    SELECTED_SESSION_SBATCH_SCRIPT,
)
from xgap.ui.clarification import (
    M15ClarificationUiError,
    build_m15_clarification_selection_event,
    build_m15_clarification_view,
    build_m15_selected_session_submission_preview,
)


LOCAL_UI_STATE_SCHEMA_VERSION = "m15-e6c-local-ui-state-v1"
LOCAL_UI_SUBMISSION_RESULT_SCHEMA_VERSION = (
    "m15-e6c-local-ui-submission-result-v1"
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_JOB_ID = re.compile(r"^[0-9]+$")


class M15LocalControlError(ValueError):
    """Raised before a local UI action when its state binding is invalid."""


class M15SessionAdvance(Protocol):
    def __call__(
        self,
        session: M15ClarificationTransportSession,
        authority_event: Mapping[str, Any],
    ) -> M15ClarificationTransportSession: ...


class M15SessionPersist(Protocol):
    def __call__(self, session: M15ClarificationTransportSession) -> None: ...


class M15RemoteSubmit(Protocol):
    def __call__(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15LocalControlError(f"{name} is not a safe identifier")
    return value


def _sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise M15LocalControlError(f"{name} is not a SHA-256 digest")
    return value


def _remote_submission_observation(value: object) -> dict[str, Any]:
    """Reduce one typed tool result to a credential-free browser view."""

    if not isinstance(value, Mapping) or set(value) != {
        "tool_name",
        "status",
        "value",
        "error",
        "metrics",
        "metadata",
    }:
        raise M15LocalControlError(
            "typed remote submitter returned an invalid observation"
        )
    if value.get("tool_name") != "remote.executor":
        raise M15LocalControlError(
            "typed remote submitter returned the wrong tool observation"
        )
    status = value.get("status")
    if status not in {"success", "error", "unavailable"}:
        raise M15LocalControlError(
            "typed remote submitter returned an invalid status"
        )
    if status != "success":
        return {
            "schema_version": LOCAL_UI_SUBMISSION_RESULT_SCHEMA_VERSION,
            "status": status,
            "message": (
                "remote submission failed; inspect the local control log"
                if status == "error"
                else "remote submission is unavailable"
            ),
        }

    result = value.get("value")
    expected_fields = {
        "executor_id",
        "operation",
        "state",
        "job_id",
        "script",
        "job_environment_keys",
    }
    if not isinstance(result, Mapping) or set(result) != expected_fields:
        raise M15LocalControlError(
            "typed remote submitter returned an invalid success value"
        )
    executor_id = _safe_id(result.get("executor_id"), name="executor_id")
    job_id = result.get("job_id")
    if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
        raise M15LocalControlError(
            "typed remote submitter returned an invalid job id"
        )
    if (
        result.get("operation") != "submit_job"
        or result.get("state") != "submitted"
        or result.get("script") != SELECTED_SESSION_SBATCH_SCRIPT
        or result.get("job_environment_keys")
        != sorted(SELECTED_SESSION_JOB_ENVIRONMENT_KEYS)
    ):
        raise M15LocalControlError(
            "typed remote submitter result differs from the fixed E5D envelope"
        )
    return {
        "schema_version": LOCAL_UI_SUBMISSION_RESULT_SCHEMA_VERSION,
        "status": "success",
        "executor_id": executor_id,
        "job_id": job_id,
        "state": "submitted",
        "script": SELECTED_SESSION_SBATCH_SCRIPT,
    }


def _browser_submission_preview(value: Mapping[str, Any]) -> dict[str, Any]:
    """Hide the server-owned remote payload while retaining its hash seal."""

    preview = copy.deepcopy(dict(value))
    remote_payload = preview.pop("remote_payload", None)
    if not isinstance(remote_payload, Mapping):
        raise M15LocalControlError("submission preview has no typed payload")
    return preview


@dataclass
class M15LocalClarificationController:
    """Own one finite clarification session for a loopback-only UI."""

    session: M15ClarificationTransportSession
    advance_session: M15SessionAdvance
    remote_training_memory_path: str
    expected_training_memory_sha256: str
    authority_source_id: str
    display_query: str
    persist_session: M15SessionPersist | None = None
    submit_job: M15RemoteSubmit | None = None
    _submission_result: dict[str, Any] | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _submission_attempted: bool = field(default=False, init=False, repr=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        _safe_id(self.authority_source_id, name="authority_source_id")
        _sha256(
            self.expected_training_memory_sha256,
            name="expected_training_memory_sha256",
        )
        if (
            not isinstance(self.display_query, str)
            or not self.display_query.strip()
            or len(self.display_query.encode("utf-8")) > 16 * 1024
        ):
            raise M15LocalControlError("display query is invalid")
        build_m15_clarification_view(self.session)

    def snapshot(self) -> dict[str, Any]:
        """Return the complete browser-safe state without credentials."""

        with self._lock:
            view = build_m15_clarification_view(self.session)
            preview = None
            if view["status"] == "ready_for_execution_handoff":
                preview = _browser_submission_preview(
                    build_m15_selected_session_submission_preview(
                        session=self.session,
                        remote_training_memory_path=(
                            self.remote_training_memory_path
                        ),
                        expected_training_memory_sha256=(
                            self.expected_training_memory_sha256
                        ),
                    )
                )
            body = {
                "schema_version": LOCAL_UI_STATE_SCHEMA_VERSION,
                "connected": True,
                "request": {
                    "text": self.display_query,
                    "sha256": hashlib.sha256(
                        self.display_query.encode("utf-8")
                    ).hexdigest(),
                },
                "clarification": view,
                "submission_preview": preview,
                "submission_enabled": (
                    self.submit_job is not None
                    and not self._submission_attempted
                ),
                "submission_attempted": self._submission_attempted,
                "submission_result": copy.deepcopy(self._submission_result),
                "control_boundary": {
                    "bind_address": "127.0.0.1",
                    "authority_source_configured_server_side": True,
                    "free_text_is_authority": False,
                    "generic_environment_editor": False,
                    "credentials_exposed_to_browser": False,
                    "native_query_text_exposed": False,
                    "direct_backend_or_model_access": False,
                    "paper_result": False,
                },
                "paper_result": False,
            }
            return {**body, "state_sha256": content_hash(body)}

    def select_candidate(
        self,
        *,
        expected_session_sha256: str,
        expected_question_sha256: str,
        candidate_id: str,
    ) -> dict[str, Any]:
        """Commit one explicitly confirmed, hash-bound candidate choice."""

        with self._lock:
            view = build_m15_clarification_view(self.session)
            question = view.get("question")
            if not isinstance(question, Mapping):
                raise M15LocalControlError(
                    "clarification session has no pending question"
                )
            if _sha256(
                expected_session_sha256, name="expected_session_sha256"
            ) != view["session_sha256"]:
                raise M15LocalControlError(
                    "clarification session changed before confirmation"
                )
            if _sha256(
                expected_question_sha256, name="expected_question_sha256"
            ) != question["question_sha256"]:
                raise M15LocalControlError(
                    "pending question changed before confirmation"
                )
            event = build_m15_clarification_selection_event(
                session=self.session,
                event_id=(
                    f"{view['session_id']}:ui-authority:q{question['sequence']}"
                ),
                candidate_id=candidate_id,
                authority_source_id=self.authority_source_id,
            )
            try:
                advanced = self.advance_session(self.session, event)
                build_m15_clarification_view(advanced)
            except (M15ClarificationUiError, ValueError) as exc:
                raise M15LocalControlError(str(exc)) from exc
            if self.persist_session is not None:
                self.persist_session(advanced)
            self.session = advanced
            return self.snapshot()

    def submit_selected_session(
        self,
        *,
        expected_submission_preview_sha256: str,
        confirmed: bool,
    ) -> dict[str, Any]:
        """Submit once through the configured typed remote executor."""

        with self._lock:
            if confirmed is not True:
                raise M15LocalControlError(
                    "selected-session submission requires explicit confirmation"
                )
            if self.submit_job is None:
                raise M15LocalControlError(
                    "remote submission is disabled for this local server"
                )
            if self._submission_attempted:
                raise M15LocalControlError(
                    "this clarification session was already submitted"
                )
            preview = build_m15_selected_session_submission_preview(
                session=self.session,
                remote_training_memory_path=self.remote_training_memory_path,
                expected_training_memory_sha256=(
                    self.expected_training_memory_sha256
                ),
            )
            if _sha256(
                expected_submission_preview_sha256,
                name="expected_submission_preview_sha256",
            ) != preview["submission_preview_sha256"]:
                raise M15LocalControlError(
                    "submission preview changed before confirmation"
                )
            self._submission_attempted = True
            try:
                result = self.submit_job(preview["remote_payload"])
                self._submission_result = _remote_submission_observation(result)
            except Exception as exc:
                self._submission_result = {
                    "schema_version": (
                        LOCAL_UI_SUBMISSION_RESULT_SCHEMA_VERSION
                    ),
                    "status": "unknown",
                    "message": (
                        "remote submission outcome is unknown; automatic retry "
                        "is disabled"
                    ),
                }
                if isinstance(exc, M15LocalControlError):
                    raise
                raise M15LocalControlError(
                    "remote submission outcome is unknown; automatic retry is "
                    "disabled"
                ) from exc
            return self.snapshot()
