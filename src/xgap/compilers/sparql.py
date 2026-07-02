"""SPARQL compiler interface."""

from __future__ import annotations

from xgap.algebra.ops import AlgebraOp


def compile_sparql(plan: AlgebraOp) -> str:
    raise NotImplementedError(
        "SPARQL compilation is planned for a future compiler milestone and is not implemented yet."
    )
