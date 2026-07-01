"""Deterministic lowering from path-pattern queries to logical plans."""

from __future__ import annotations

from xgap.algebra.ops import AlgebraOp
from xgap.pattern.ast import PathPatternQuery


def lower_to_logical_plan(query: PathPatternQuery) -> AlgebraOp:
    raise NotImplementedError("Path-pattern lowering is planned for M5 and is not implemented yet.")
