"""Base compiler interface."""

from __future__ import annotations

from xgap.algebra.ops import AlgebraOp


class QueryCompiler:
    target_name = "unknown"

    def compile(self, plan: AlgebraOp) -> str:
        raise NotImplementedError("Query compilation is planned for M6 and is not implemented yet.")
