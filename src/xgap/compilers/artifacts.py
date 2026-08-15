"""Compiler artifact helpers for M9."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from xgap.backends.capabilities import (
    BackendCapabilityProfile,
    CompilerInputSpec,
    CompilerOutputSpec,
)
from xgap.infrastructure.runtime import QueryArtifact


M9_RESULT_MODEL = "row_bindings"


@dataclass(frozen=True)
class CompilationContext:
    backend_id: str
    language: str
    required_features: tuple[str, ...]
    semantic_assumptions: tuple[str, ...]


def make_compiler_input_spec(
    *,
    plan_kind: str,
    profile: BackendCapabilityProfile,
    required_features: tuple[str, ...],
) -> CompilerInputSpec:
    return CompilerInputSpec(
        logical_plan_id="m9-input",
        logical_plan_kind=plan_kind,
        target_backend_id=profile.backend_id,
        target_language=profile.language,
        expected_result_model=M9_RESULT_MODEL,
        required_features=tuple(sorted(required_features)),
        metadata={"compiler": "m9_minimal_compiler"},
    )


def make_query_artifact(
    *,
    artifact_id: str,
    language: str,
    text: str,
    profile: BackendCapabilityProfile,
    required_features: tuple[str, ...],
    semantic_assumptions: tuple[str, ...],
    extra_parameters: Mapping[str, Any] | None = None,
) -> QueryArtifact:
    parameters = {
        "compiler": "m9_minimal_compiler",
        "target_backend_id": profile.backend_id,
        "result_model": M9_RESULT_MODEL,
        "required_features": list(sorted(required_features)),
        "semantic_assumptions": list(semantic_assumptions),
    }
    parameters.update(dict(extra_parameters or {}))
    return QueryArtifact(
        artifact_id=artifact_id,
        language=language,
        text=text,
        kind="compiled",
        parameters=parameters,
    )


def make_compiler_output_spec(
    *,
    profile: BackendCapabilityProfile,
    artifact: QueryArtifact,
    semantic_assumptions: tuple[str, ...],
) -> CompilerOutputSpec:
    return CompilerOutputSpec(
        target_backend_id=profile.backend_id,
        artifact=artifact,
        result_model=M9_RESULT_MODEL,
        semantic_assumptions=semantic_assumptions,
        metadata={"compiler": "m9_minimal_compiler"},
    )
