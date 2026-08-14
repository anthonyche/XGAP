"""Machine-readable failure categories shared by M12-D runners."""

from __future__ import annotations

from enum import Enum


class ExperimentFailureCategory(str, Enum):
    PROVIDER_ERROR = "provider_error"
    STRUCTURED_OUTPUT_ERROR = "structured_output_error"
    INVALID_CANDIDATE = "invalid_candidate"
    UNRESOLVED_ANCHOR = "unresolved_anchor"
    MISSING_MAPPING = "missing_mapping"
    SEMANTIC_INADMISSIBLE = "semantic_inadmissible"
    REPRESENTATION_UNSUPPORTED = "representation_unsupported"
    COMPILER_UNSUPPORTED = "compiler_unsupported"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    BACKEND_ERROR = "backend_error"
    TIMEOUT = "timeout"
    EXECUTION_SUCCESS_EMPTY = "execution_success_empty"
    ESTIMATOR_UNAVAILABLE = "estimator_unavailable"
    POSTERIOR_UPDATE_ERROR = "posterior_update_error"
    CONFIG_ERROR = "config_error"
    ARTIFACT_HASH_MISMATCH = "artifact_hash_mismatch"
    RESUME_STATE_ERROR = "resume_state_error"

