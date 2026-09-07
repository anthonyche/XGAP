"""Thin local UI adapters over XGAP's typed control-plane contracts."""

from xgap.ui.clarification import (
    CLARIFICATION_VIEW_SCHEMA_VERSION,
    SELECTED_SESSION_SUBMISSION_PREVIEW_SCHEMA_VERSION,
    M15ClarificationUiError,
    build_m15_clarification_selection_event,
    build_m15_clarification_view,
    build_m15_selected_session_submission_preview,
)

__all__ = [
    "CLARIFICATION_VIEW_SCHEMA_VERSION",
    "SELECTED_SESSION_SUBMISSION_PREVIEW_SCHEMA_VERSION",
    "M15ClarificationUiError",
    "build_m15_clarification_selection_event",
    "build_m15_clarification_view",
    "build_m15_selected_session_submission_preview",
]
