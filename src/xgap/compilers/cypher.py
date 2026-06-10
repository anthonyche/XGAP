"""Cypher compiler interface."""

from __future__ import annotations

from xgap.algebra.ops import AlgebraOp


def compile_cypher(plan: AlgebraOp) -> str:
    raise NotImplementedError("Cypher compilation is planned for M6 and is not implemented yet.")
