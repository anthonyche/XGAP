"""Focused quantified-pattern AST for M6."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
import math
from numbers import Real
from typing import Any

from xgap.pattern.ast import Direction, Var


class ScalarComparator(Enum):
    EQ = "="
    NE = "!="
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="


class QuantifierKind(Enum):
    EXISTS = "EXISTS"
    COUNT = "COUNT"
    RATIO = "RATIO"
    NONE = "NONE"


class QuantifierComparator(Enum):
    EQ = "EQ"
    GE = "GE"


@dataclass(frozen=True)
class PropertyPredicate:
    property_key: str
    comparator: ScalarComparator
    value: Any

    def __post_init__(self) -> None:
        if not isinstance(self.property_key, str):
            raise TypeError("PropertyPredicate property_key must be a string.")
        if not self.property_key:
            raise ValueError("PropertyPredicate property_key must be non-empty.")
        if not isinstance(self.comparator, ScalarComparator):
            raise TypeError("PropertyPredicate comparator must be a ScalarComparator value.")
        _validate_scalar_literal(self.value, self.comparator)


@dataclass(frozen=True)
class FocusedNodePattern:
    var: Var
    label: str | None = None
    predicates: tuple[PropertyPredicate, ...] = ()

    def __post_init__(self) -> None:
        _validate_var(self.var, "FocusedNodePattern var")
        _validate_label(self.label)
        object.__setattr__(self, "predicates", _validate_predicates(self.predicates))


@dataclass(frozen=True)
class FocusedEdgePattern:
    var: Var | None = None
    label: str | None = None
    predicates: tuple[PropertyPredicate, ...] = ()

    def __post_init__(self) -> None:
        if self.var is not None:
            _validate_var(self.var, "FocusedEdgePattern var")
        _validate_label(self.label)
        object.__setattr__(self, "predicates", _validate_predicates(self.predicates))


@dataclass(frozen=True)
class CountingQuantifier:
    kind: QuantifierKind
    comparator: QuantifierComparator | None = None
    threshold: int | Fraction | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, QuantifierKind):
            raise TypeError("CountingQuantifier kind must be a QuantifierKind value.")
        if self.kind is QuantifierKind.EXISTS:
            if self.comparator is not None or self.threshold is not None:
                raise ValueError("EXISTS quantifier does not accept comparator or threshold.")
            return
        if self.kind is QuantifierKind.NONE:
            if self.comparator is not None or self.threshold is not None:
                raise ValueError("NONE quantifier does not accept comparator or threshold.")
            return
        if not isinstance(self.comparator, QuantifierComparator):
            raise ValueError(f"{self.kind.value} quantifier requires a comparator.")
        if self.kind is QuantifierKind.COUNT:
            if not _is_positive_int(self.threshold):
                raise ValueError("COUNT threshold must be a positive integer.")
            return
        if self.kind is QuantifierKind.RATIO:
            if not isinstance(self.threshold, Fraction):
                raise TypeError("RATIO threshold must be an exact Fraction.")
            if self.threshold <= 0 or self.threshold > 1:
                raise ValueError("RATIO threshold must satisfy 0 < r <= 1.")
            return

    def canonical(self) -> CountingQuantifier:
        if (
            self.kind is QuantifierKind.COUNT
            and self.comparator is QuantifierComparator.GE
            and self.threshold == 1
        ):
            return exists()
        if self.kind is QuantifierKind.RATIO and self.threshold == Fraction(1, 1):
            return CountingQuantifier(
                QuantifierKind.RATIO,
                QuantifierComparator.EQ,
                Fraction(1, 1),
            )
        return self

    def is_non_existential(self) -> bool:
        return self.canonical().kind is not QuantifierKind.EXISTS

    def is_none(self) -> bool:
        return self.canonical().kind is QuantifierKind.NONE


def exists() -> CountingQuantifier:
    return CountingQuantifier(QuantifierKind.EXISTS)


def count_eq(k: int) -> CountingQuantifier:
    return CountingQuantifier(QuantifierKind.COUNT, QuantifierComparator.EQ, k).canonical()


def count_ge(k: int) -> CountingQuantifier:
    return CountingQuantifier(QuantifierKind.COUNT, QuantifierComparator.GE, k).canonical()


def ratio_eq(r: int | str | float | Fraction) -> CountingQuantifier:
    return CountingQuantifier(
        QuantifierKind.RATIO,
        QuantifierComparator.EQ,
        _ratio_fraction(r),
    ).canonical()


def ratio_ge(r: int | str | float | Fraction) -> CountingQuantifier:
    return CountingQuantifier(
        QuantifierKind.RATIO,
        QuantifierComparator.GE,
        _ratio_fraction(r),
    ).canonical()


def all_matches() -> CountingQuantifier:
    return ratio_eq(Fraction(1, 1))


def none() -> CountingQuantifier:
    return CountingQuantifier(QuantifierKind.NONE)


@dataclass(frozen=True)
class QuantifiedPatternEdge:
    parent_var: Var
    child_var: Var
    edge: FocusedEdgePattern
    direction: Direction
    quantifier: CountingQuantifier

    def __post_init__(self) -> None:
        _validate_var(self.parent_var, "QuantifiedPatternEdge parent_var")
        _validate_var(self.child_var, "QuantifiedPatternEdge child_var")
        if not isinstance(self.edge, FocusedEdgePattern):
            raise TypeError("QuantifiedPatternEdge edge must be a FocusedEdgePattern.")
        if not isinstance(self.direction, Direction):
            raise TypeError("QuantifiedPatternEdge direction must be a Direction value.")
        if not isinstance(self.quantifier, CountingQuantifier):
            raise TypeError("QuantifiedPatternEdge quantifier must be a CountingQuantifier.")
        object.__setattr__(self, "quantifier", self.quantifier.canonical())


@dataclass(frozen=True)
class FocusedQuantifiedPatternQuery:
    focus: Var
    node_patterns: tuple[FocusedNodePattern, ...]
    edges: tuple[QuantifiedPatternEdge, ...] = ()

    def __post_init__(self) -> None:
        _validate_var(self.focus, "FocusedQuantifiedPatternQuery focus")
        object.__setattr__(self, "node_patterns", tuple(self.node_patterns))
        object.__setattr__(self, "edges", tuple(self.edges))
        for node in self.node_patterns:
            if not isinstance(node, FocusedNodePattern):
                raise TypeError("node_patterns must contain FocusedNodePattern values.")
        for edge in self.edges:
            if not isinstance(edge, QuantifiedPatternEdge):
                raise TypeError("edges must contain QuantifiedPatternEdge values.")


def _validate_var(var: Var, context: str) -> None:
    if not isinstance(var, Var):
        raise TypeError(f"{context} must be a Var.")


def _validate_label(label: str | None) -> None:
    if label is None:
        return
    if not isinstance(label, str):
        raise TypeError("Focused pattern label must be a string or None.")
    if not label:
        raise ValueError("Focused pattern label must be non-empty when provided.")


def _validate_predicates(predicates: tuple[PropertyPredicate, ...]) -> tuple[PropertyPredicate, ...]:
    result = tuple(predicates)
    for predicate in result:
        if not isinstance(predicate, PropertyPredicate):
            raise TypeError("Focused pattern predicates must be PropertyPredicate values.")
    return result


def _validate_scalar_literal(value: object, comparator: ScalarComparator) -> None:
    if value is None:
        raise ValueError("None is not a supported scalar literal in M6.")
    if comparator in {
        ScalarComparator.LT,
        ScalarComparator.LE,
        ScalarComparator.GT,
        ScalarComparator.GE,
    }:
        if not _is_finite_numeric_literal(value):
            raise ValueError("Ordering predicate values must be finite numeric non-bool literals.")
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Scalar float literals must be finite.")


def _is_finite_numeric_literal(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, Real):
        return False
    return math.isfinite(value)


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _ratio_fraction(value: int | str | float | Fraction) -> Fraction:
    if isinstance(value, bool):
        raise TypeError("Ratio thresholds must not be bool values.")
    if isinstance(value, Fraction):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Ratio float thresholds must be finite.")
        return Fraction(str(value))
    return Fraction(value)
