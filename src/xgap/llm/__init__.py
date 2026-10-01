"""LLM-facing planner boundary interfaces."""

from xgap.llm.mock import MockStructuredCandidateProvider
from xgap.llm.openai_compatible import (
    LiveFailureCategory,
    LiveInvocationArtifact,
    LiveProviderError,
    OpenAICompatibleProviderConfig,
    OpenAICompatibleStructuredCandidateProvider,
)
from xgap.llm.parser import (
    PlannerSchemaError,
    parse_path_pattern_query,
    parse_planner_response,
    path_pattern_query_to_dict,
)
from xgap.llm.planner import plan_from_question, plan_response_from_question
from xgap.llm.protocol import StructuredCandidateProvider
from xgap.llm.schemas import (
    CandidateValidationReport,
    PlannerCandidate,
    PlannerRequest,
    PlannerResponse,
)
from xgap.llm.validation import validate_candidate
from xgap.llm.resolution import (
    M15_RESOLUTION_BASE_SCHEMA,
    M15_RESOLUTION_INVOCATION_SCHEMA_VERSION,
    M15_RESOLUTION_PROVIDER_SCHEMA_VERSION,
    M15ResolutionInvocationArtifact,
    OpenAICompatibleResolutionCandidateProvider,
    build_openai_compatible_resolution_provider,
)

__all__ = [
    "CandidateValidationReport",
    "MockStructuredCandidateProvider",
    "LiveFailureCategory",
    "LiveInvocationArtifact",
    "LiveProviderError",
    "OpenAICompatibleProviderConfig",
    "OpenAICompatibleStructuredCandidateProvider",
    "PlannerCandidate",
    "PlannerRequest",
    "PlannerResponse",
    "PlannerSchemaError",
    "StructuredCandidateProvider",
    "parse_path_pattern_query",
    "parse_planner_response",
    "path_pattern_query_to_dict",
    "plan_from_question",
    "plan_response_from_question",
    "validate_candidate",
    "M15_RESOLUTION_BASE_SCHEMA",
    "M15_RESOLUTION_INVOCATION_SCHEMA_VERSION",
    "M15_RESOLUTION_PROVIDER_SCHEMA_VERSION",
    "M15ResolutionInvocationArtifact",
    "OpenAICompatibleResolutionCandidateProvider",
    "build_openai_compatible_resolution_provider",
]
