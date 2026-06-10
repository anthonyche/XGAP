"""Path-algebra data structures and logical operators."""

from xgap.algebra.conditions import (
    And,
    EdgeRef,
    LabelEquals,
    LengthEquals,
    NodeRef,
    Not,
    Or,
    PropertyEquals,
)
from xgap.algebra.evaluator import evaluate
from xgap.algebra.graph import PropertyGraph
from xgap.algebra.ops import (
    EdgesOp,
    GroupByOp,
    JoinOp,
    NodesOp,
    OrderByOp,
    ProjectionOp,
    RecursiveMode,
    RecursiveOp,
    SelectionOp,
    UnionOp,
)
from xgap.algebra.types import Path, PathSet, SolutionSpace

__all__ = [
    "And",
    "EdgeRef",
    "EdgesOp",
    "GroupByOp",
    "JoinOp",
    "LabelEquals",
    "LengthEquals",
    "NodeRef",
    "NodesOp",
    "Not",
    "Or",
    "OrderByOp",
    "Path",
    "PathSet",
    "ProjectionOp",
    "PropertyEquals",
    "PropertyGraph",
    "RecursiveMode",
    "RecursiveOp",
    "SelectionOp",
    "SolutionSpace",
    "UnionOp",
    "evaluate",
]
