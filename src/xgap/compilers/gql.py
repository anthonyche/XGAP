"""GQL compiler boundary for M9."""

from __future__ import annotations

from xgap.algebra.ops import AlgebraOp
from xgap.compilers.errors import unsupported_compilation
from xgap.infrastructure.runtime import QueryArtifact
from xgap.pattern.ast import PathPatternQuery


def compile_gql(plan: AlgebraOp | PathPatternQuery) -> QueryArtifact:
    raise unsupported_compilation(
        backend_id="gql",
        language="gql",
        feature_id="native.gql",
        message="GQL compilation remains unsupported in M9.",
        future_milestone_hint="M10+",
    )
