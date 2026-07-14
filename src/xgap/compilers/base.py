"""Base compiler interface."""

from __future__ import annotations

from xgap.algebra.ops import AlgebraOp
from xgap.compilers.errors import unsupported_compilation
from xgap.infrastructure.runtime import QueryArtifact
from xgap.pattern.ast import PathPatternQuery


class QueryCompiler:
    target_name = "unknown"

    def compile(self, plan: AlgebraOp | PathPatternQuery) -> QueryArtifact:
        raise unsupported_compilation(
            backend_id=self.target_name,
            language=self.target_name,
            feature_id="compiler.unconfigured",
            message=f"No compiler implementation is configured for {self.target_name!r}.",
        )
