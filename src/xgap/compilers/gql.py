"""GQL compiler interface."""

from __future__ import annotations

from xgap.algebra.ops import AlgebraOp


def compile_gql(plan: AlgebraOp) -> str:
    raise NotImplementedError(
        "GQL compilation is planned for a future compiler milestone and is not implemented yet."
    )
