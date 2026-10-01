"""Thin local UI adapters over XGAP's typed control-plane contracts."""

from xgap.ui.clarification import (
    CLARIFICATION_VIEW_SCHEMA_VERSION,
    SELECTED_SESSION_SUBMISSION_PREVIEW_SCHEMA_VERSION,
    M15ClarificationUiError,
    build_m15_clarification_selection_event,
    build_m15_clarification_view,
    build_m15_selected_session_submission_preview,
)
from xgap.ui.local_control import (
    LOCAL_UI_SUBMISSION_RESULT_SCHEMA_VERSION,
    LOCAL_UI_STATE_SCHEMA_VERSION,
    M15LocalClarificationController,
    M15LocalControlError,
)
from xgap.ui.local_server import (
    DEFAULT_LOCAL_UI_ORIGINS,
    LOCAL_UI_HTTP_SCHEMA_VERSION,
    M15LocalHttpConfig,
    M15LocalHttpServer,
    build_m15_local_http_server,
)

__all__ = [
    "CLARIFICATION_VIEW_SCHEMA_VERSION",
    "SELECTED_SESSION_SUBMISSION_PREVIEW_SCHEMA_VERSION",
    "M15ClarificationUiError",
    "build_m15_clarification_selection_event",
    "build_m15_clarification_view",
    "build_m15_selected_session_submission_preview",
    "LOCAL_UI_STATE_SCHEMA_VERSION",
    "LOCAL_UI_SUBMISSION_RESULT_SCHEMA_VERSION",
    "M15LocalClarificationController",
    "M15LocalControlError",
    "DEFAULT_LOCAL_UI_ORIGINS",
    "LOCAL_UI_HTTP_SCHEMA_VERSION",
    "M15LocalHttpConfig",
    "M15LocalHttpServer",
    "build_m15_local_http_server",
]
