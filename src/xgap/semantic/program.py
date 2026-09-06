"""Typed semantic graph program contracts for the agentic XGAP mainline.

These operators describe backend-independent query intent.  They are not new
members of the audited path algebra in :mod:`xgap.algebra`.  A later lowering
stage may realize a semantic operator with the existing path algebra, a native
backend fragment, or a coordinator operation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


JsonMap = dict[str, Any]


class SemanticProgramError(ValueError):
    """Raised when a semantic program is structurally or type invalid."""


class SemanticOperatorKind(str, Enum):
    MATCH = "match"
    TRAVERSE = "traverse"
    FILTER = "filter"
    JOIN = "join"
    UNION = "union"
    AGGREGATE = "aggregate"
    ORDER_LIMIT = "order_limit"
    PROJECT = "project"
    ALIGN = "align"


class SemanticValueKind(str, Enum):
    BINDING_SET = "binding_set"
    PATH_SET = "path_set"
    GROUPED_BINDINGS = "grouped_bindings"
    SCALAR = "scalar"


class SemanticHoleKind(str, Enum):
    ENTITY = "entity"
    PREDICATE = "predicate"
    TYPE = "type"
    SOURCE = "source"
    CONSTRAINT = "constraint"


class ConstraintPolicy(str, Enum):
    HARD = "hard"
    RELAXABLE = "relaxable"


_ARITY: dict[SemanticOperatorKind, tuple[int, int]] = {
    SemanticOperatorKind.MATCH: (0, 0),
    SemanticOperatorKind.TRAVERSE: (0, 1),
    SemanticOperatorKind.FILTER: (1, 1),
    SemanticOperatorKind.JOIN: (2, 2),
    SemanticOperatorKind.UNION: (2, 2),
    SemanticOperatorKind.AGGREGATE: (1, 1),
    SemanticOperatorKind.ORDER_LIMIT: (1, 1),
    SemanticOperatorKind.PROJECT: (1, 1),
    SemanticOperatorKind.ALIGN: (1, 1),
}


@dataclass(frozen=True)
class SemanticConstraint:
    """A named semantic requirement and its relaxation policy."""

    constraint_id: str
    expression: str
    policy: ConstraintPolicy = ConstraintPolicy.HARD

    def __post_init__(self) -> None:
        if not self.constraint_id.strip():
            raise SemanticProgramError("constraint_id must be nonempty")
        if not self.expression.strip():
            raise SemanticProgramError("constraint expression must be nonempty")

    def to_dict(self) -> JsonMap:
        return {
            "constraint_id": self.constraint_id,
            "expression": self.expression,
            "policy": self.policy.value,
        }


@dataclass(frozen=True)
class SemanticHole:
    """An unresolved binding in a partially bound semantic program."""

    hole_id: str
    kind: SemanticHoleKind
    mention: str
    required: bool = True
    candidates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.hole_id.strip():
            raise SemanticProgramError("hole_id must be nonempty")
        if not self.mention.strip():
            raise SemanticProgramError("hole mention must be nonempty")
        if len(set(self.candidates)) != len(self.candidates):
            raise SemanticProgramError(f"hole '{self.hole_id}' has duplicate candidates")

    @property
    def is_resolved(self) -> bool:
        return len(self.candidates) == 1

    def to_dict(self) -> JsonMap:
        return {
            "hole_id": self.hole_id,
            "kind": self.kind.value,
            "mention": self.mention,
            "required": self.required,
            "candidates": list(self.candidates),
            "is_resolved": self.is_resolved,
        }


@dataclass(frozen=True)
class SemanticOperator:
    """One typed node in a backend-independent semantic query DAG."""

    operator_id: str
    kind: SemanticOperatorKind
    input_ids: tuple[str, ...]
    input_kinds: tuple[SemanticValueKind, ...]
    output_kind: SemanticValueKind
    parameters: Mapping[str, Any] = field(default_factory=dict)
    constraints: tuple[SemanticConstraint, ...] = ()
    required_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.operator_id.strip():
            raise SemanticProgramError("operator_id must be nonempty")
        if len(self.input_ids) != len(self.input_kinds):
            raise SemanticProgramError(
                f"operator '{self.operator_id}' must declare one input kind per input"
            )
        minimum, maximum = _ARITY[self.kind]
        if not minimum <= len(self.input_ids) <= maximum:
            expected = str(minimum) if minimum == maximum else f"{minimum}..{maximum}"
            raise SemanticProgramError(
                f"operator '{self.operator_id}' kind '{self.kind.value}' expects "
                f"{expected} inputs, got {len(self.input_ids)}"
            )
        if len(set(self.required_capabilities)) != len(self.required_capabilities):
            raise SemanticProgramError(
                f"operator '{self.operator_id}' has duplicate capability requirements"
            )

    def to_dict(self) -> JsonMap:
        return {
            "operator_id": self.operator_id,
            "kind": self.kind.value,
            "input_ids": list(self.input_ids),
            "input_kinds": [kind.value for kind in self.input_kinds],
            "output_kind": self.output_kind.value,
            "parameters": dict(self.parameters),
            "constraints": [constraint.to_dict() for constraint in self.constraints],
            "required_capabilities": list(self.required_capabilities),
        }


@dataclass(frozen=True)
class SemanticGraphProgram:
    """A typed DAG plus unresolved semantic bindings.

    Construction validates identity, references, edge types, roots, and DAG
    acyclicity.  It deliberately does not pick a backend or invoke a resolver.
    """

    program_id: str
    operators: tuple[SemanticOperator, ...]
    roots: tuple[str, ...]
    holes: tuple[SemanticHole, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.program_id.strip():
            raise SemanticProgramError("program_id must be nonempty")
        if not self.operators:
            raise SemanticProgramError("a semantic program requires at least one operator")
        if not self.roots:
            raise SemanticProgramError("a semantic program requires at least one root")

        operators = {operator.operator_id: operator for operator in self.operators}
        if len(operators) != len(self.operators):
            raise SemanticProgramError("semantic operator ids must be unique")
        if len({hole.hole_id for hole in self.holes}) != len(self.holes):
            raise SemanticProgramError("semantic hole ids must be unique")
        if len(set(self.roots)) != len(self.roots):
            raise SemanticProgramError("semantic roots must be unique")
        for root in self.roots:
            if root not in operators:
                raise SemanticProgramError(f"unknown semantic root '{root}'")

        for operator in self.operators:
            for input_id, expected_kind in zip(operator.input_ids, operator.input_kinds):
                source = operators.get(input_id)
                if source is None:
                    raise SemanticProgramError(
                        f"operator '{operator.operator_id}' references unknown input '{input_id}'"
                    )
                if source.output_kind != expected_kind:
                    raise SemanticProgramError(
                        f"operator '{operator.operator_id}' expects '{input_id}' to produce "
                        f"'{expected_kind.value}', got '{source.output_kind.value}'"
                    )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(operator_id: str) -> None:
            if operator_id in visiting:
                raise SemanticProgramError("semantic program must be acyclic")
            if operator_id in visited:
                return
            visiting.add(operator_id)
            for input_id in operators[operator_id].input_ids:
                visit(input_id)
            visiting.remove(operator_id)
            visited.add(operator_id)

        for operator_id in operators:
            visit(operator_id)

    @property
    def unresolved_required_holes(self) -> tuple[SemanticHole, ...]:
        return tuple(hole for hole in self.holes if hole.required and not hole.is_resolved)

    def to_dict(self) -> JsonMap:
        return {
            "program_id": self.program_id,
            "operators": [operator.to_dict() for operator in self.operators],
            "roots": list(self.roots),
            "holes": [hole.to_dict() for hole in self.holes],
            "metadata": dict(self.metadata),
        }
