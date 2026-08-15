"""Adapter from complete physical states to existing M9 compiler boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from xgap.algebra.ops import AlgebraOp
from xgap.algebra.pretty import format_plan
from xgap.backends.capabilities import BackendCapabilityProfile
from xgap.compilers.cypher import compile_cypher
from xgap.compilers.errors import CompilerError, UnsupportedCompilationError
from xgap.compilers.sparql import compile_sparql
from xgap.infrastructure.runtime import QueryArtifact
from xgap.pattern.ast import PathPatternQuery
from xgap.planning.contracts import PhysicalCompilationResult, PhysicalState


@dataclass(frozen=True)
class ExistingCompilerAdapter:
    """Use M9 as-is and make unsupported execution boundaries explicit."""

    compiler_id: str = "m11-existing-m9-compiler-adapter"
    backend_mapping: Mapping[str, Any] | None = None

    def compile(
        self,
        logical_plan: AlgebraOp,
        state: PhysicalState,
        backend_profiles: Mapping[str, BackendCapabilityProfile],
        *,
        pattern_query: PathPatternQuery | None = None,
    ) -> PhysicalCompilationResult:
        if not state.is_complete:
            return PhysicalCompilationResult(
                feasible=False,
                executable=False,
                status="incomplete",
                reason_code="physical_state_incomplete",
                message="Physical compilation requires a complete state.",
            )
        backend_ids = state.selected_backend_ids
        if len(backend_ids) != 1:
            return PhysicalCompilationResult(
                feasible=True,
                executable=False,
                status="unsupported",
                reason_code="distributed_cross_backend_runtime_not_implemented",
                message=(
                    "The physical realization is represented, but M11 does not "
                    "orchestrate multi-backend execution."
                ),
                metadata={"backend_ids": list(backend_ids)},
            )

        backend_id = backend_ids[0]
        profile = backend_profiles[backend_id]
        artifact_id = f"m11-{state.logical_plan_id}-{backend_id}"
        if backend_id == "reference_evaluator" or profile.language.lower() == "xgap_logical":
            artifact = QueryArtifact(
                artifact_id=artifact_id,
                language="xgap_logical",
                text=format_plan(logical_plan),
                kind="logical_reference_plan",
                parameters={"logical_plan_id": state.logical_plan_id},
            )
            return PhysicalCompilationResult(
                feasible=True,
                executable=True,
                status="compiled_reference_plan",
                artifacts=(artifact,),
                metadata={
                    "backend_id": backend_id,
                    "execution_boundary": "in_process_reference_evaluator",
                },
            )

        try:
            compiler_input = pattern_query if pattern_query is not None else logical_plan
            if profile.language.lower() == "cypher":
                artifact = compile_cypher(
                    compiler_input,
                    profile=profile,
                    artifact_id=artifact_id,
                )
            elif profile.language.lower() == "sparql":
                artifact = compile_sparql(
                    compiler_input,
                    profile=profile,
                    artifact_id=artifact_id,
                    backend_mapping=self.backend_mapping,
                )
            else:
                return PhysicalCompilationResult(
                    feasible=True,
                    executable=False,
                    status="unsupported",
                    reason_code="native_compiler_not_available",
                    message=(
                        f"No current compiler is registered for language "
                        f"'{profile.language}'."
                    ),
                    metadata={"backend_id": backend_id, "language": profile.language},
                )
        except UnsupportedCompilationError as error:
            return PhysicalCompilationResult(
                feasible=True,
                executable=False,
                status="unsupported",
                reason_code="m9_unsupported_compilation",
                message=str(error),
                metadata={"compiler_failure": error.failure.to_dict()},
            )
        except CompilerError as error:
            return PhysicalCompilationResult(
                feasible=False,
                executable=False,
                status="compiler_error",
                reason_code="m9_compiler_error",
                message=str(error),
            )
        return PhysicalCompilationResult(
            feasible=True,
            executable=True,
            status="compiled_native_query",
            artifacts=(artifact,),
            metadata={"backend_id": backend_id, "language": profile.language},
        )
