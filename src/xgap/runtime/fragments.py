"""Per-backend fragment compilation over the existing M9 compiler boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from xgap.algebra.ops import AlgebraOp
from xgap.backends.capabilities import BackendCapabilityProfile
from xgap.compilers.cypher import compile_cypher
from xgap.compilers.features import default_profile
from xgap.compilers.sparql import compile_sparql
from xgap.infrastructure.runtime import QueryArtifact
from xgap.pattern.ast import PathPatternQuery
from xgap.runtime.contracts import JsonMap, RuntimeNode, RuntimeNodeKind


class FragmentCompilationError(ValueError):
    """Raised when no configured compiler can realize a backend fragment."""


@dataclass(frozen=True)
class SemanticFragment:
    """A bounded semantic/logical sub-plan assigned to one backend."""

    fragment_id: str
    backend_id: str
    plan: AlgebraOp | PathPatternQuery
    semantic_operator_ids: tuple[str, ...]
    output_schema: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.fragment_id.strip() or not self.backend_id.strip():
            raise FragmentCompilationError("fragment_id and backend_id must be nonempty")
        if not self.semantic_operator_ids:
            raise FragmentCompilationError("a fragment must reference semantic operators")


@dataclass(frozen=True)
class CompiledBackendFragment:
    fragment_id: str
    backend_id: str
    artifact: QueryArtifact
    semantic_operator_ids: tuple[str, ...]
    output_schema: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_runtime_node(self, *, node_id: str | None = None) -> RuntimeNode:
        return RuntimeNode(
            node_id=node_id or self.fragment_id,
            kind=RuntimeNodeKind.REMOTE_QUERY,
            parameters={
                "backend_id": self.backend_id,
                "artifact": self.artifact.to_dict(),
                "output_schema": list(self.output_schema),
            },
            semantic_operator_ids=self.semantic_operator_ids,
        )

    def to_dict(self) -> JsonMap:
        return {
            "fragment_id": self.fragment_id,
            "backend_id": self.backend_id,
            "artifact": self.artifact.to_dict(),
            "semantic_operator_ids": list(self.semantic_operator_ids),
            "output_schema": list(self.output_schema),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ExistingM9FragmentCompiler:
    """Compile each assigned fragment independently through existing M9 code."""

    backend_profiles: Mapping[str, BackendCapabilityProfile] = field(default_factory=dict)
    backend_mappings: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def compile(self, fragment: SemanticFragment) -> CompiledBackendFragment:
        profile = self.backend_profiles.get(fragment.backend_id)
        if profile is None:
            profile = default_profile(fragment.backend_id)
        language = profile.language.lower()
        artifact_id = f"m15-fragment-{fragment.fragment_id}-{fragment.backend_id}"
        if language == "cypher":
            artifact = compile_cypher(
                fragment.plan,
                profile=profile,
                artifact_id=artifact_id,
            )
        elif language == "sparql":
            mapping = self.backend_mappings.get(fragment.backend_id)
            if mapping is None:
                raise FragmentCompilationError(
                    f"SPARQL fragment '{fragment.fragment_id}' requires a backend mapping"
                )
            artifact = compile_sparql(
                fragment.plan,
                profile=profile,
                artifact_id=artifact_id,
                backend_mapping=mapping,
            )
        else:
            raise FragmentCompilationError(
                f"no M9 fragment compiler for backend '{fragment.backend_id}' "
                f"language '{profile.language}'"
            )
        return CompiledBackendFragment(
            fragment_id=fragment.fragment_id,
            backend_id=fragment.backend_id,
            artifact=artifact,
            semantic_operator_ids=fragment.semantic_operator_ids,
            output_schema=fragment.output_schema,
            metadata={"compiler": "existing-m9-fragment-compiler-v1"},
        )
