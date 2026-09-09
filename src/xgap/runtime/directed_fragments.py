"""Opt-in native directed compiler connected to the existing runtime contract."""

from dataclasses import dataclass, field
from typing import Any, Mapping

from xgap.backends.capabilities import BackendCapabilityProfile
from xgap.compilers.directed import PROFILE, compile_directed_rows
from xgap.compilers.rdf_encoding import RdfRowEncoding
from xgap.runtime.fragments import (
    CompiledBackendFragment,
    FragmentCompilationError,
    SemanticFragment,
)


@dataclass(frozen=True)
class DirectedRowFragmentCompiler:
    backend_profiles: Mapping[str, BackendCapabilityProfile] = field(
        default_factory=dict
    )
    backend_mappings: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    rdf_encodings: Mapping[str, RdfRowEncoding] = field(default_factory=dict)

    def compile(self, fragment: SemanticFragment) -> CompiledBackendFragment:
        artifact = compile_directed_rows(
            fragment.plan,
            backend_id=fragment.backend_id,
            profile=self.backend_profiles.get(fragment.backend_id),
            backend_mapping=self.backend_mappings.get(fragment.backend_id),
            artifact_id=f"directed-{fragment.fragment_id}-{fragment.backend_id}",
            rdf_encoding=self.rdf_encodings.get(fragment.backend_id),
        )
        columns = tuple(artifact.parameters["output_columns"])
        if fragment.output_schema and fragment.output_schema != columns:
            raise FragmentCompilationError(
                "Declared output schema must equal the directed compiler columns; no implicit projection."
            )
        return CompiledBackendFragment(
            fragment.fragment_id,
            fragment.backend_id,
            artifact,
            fragment.semantic_operator_ids,
            columns,
            {"compiler": PROFILE, "backend_execution_verified": False},
        )
