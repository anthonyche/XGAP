"""Explicit answer projection with RDF term identity, independent of gold data.

This is set-valued term equality, not a benchmark's value-equivalence scorer.
Column selection and property-graph identity mapping are caller-owned inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from xgap.backends.rdf_terms import RdfTerm, RDF_TERMS_V1
from xgap.compilers.rdf_encoding import RdfRowEncoding
from xgap.infrastructure.runtime import ExecutionReport


@dataclass(frozen=True)
class AnswerProjection:
    column: str
    mode: str = RDF_TERMS_V1
    node_encoding: RdfRowEncoding | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.column, str) or not self.column.strip():
            raise ValueError("An explicit answer column is required.")
        if self.mode == "property_graph_nodes_v1":
            if not isinstance(self.node_encoding, RdfRowEncoding):
                raise ValueError(
                    "Property-graph nodes require an explicit identity encoding."
                )
        elif self.mode != RDF_TERMS_V1 or self.node_encoding is not None:
            raise ValueError("Unsupported or conflicting answer projection mode.")

    def project_rows(self, rows: Iterable[Mapping[str, Any]]) -> tuple[RdfTerm, ...]:
        values: dict[str, RdfTerm] = {}
        for row in rows:
            if not isinstance(row, Mapping) or self.column not in row:
                raise ValueError(
                    "Answer column is missing; partial answers are not accepted."
                )
            value = row[self.column]
            if self.mode == RDF_TERMS_V1:
                term = RdfTerm.from_binding(value)
                if term.kind == "bnode":
                    raise ValueError(
                        "Blank nodes have no cross-result answer identity."
                    )
            else:
                if not isinstance(value, Mapping):
                    raise ValueError("Expected a property-graph node property object.")
                encoding = self.node_encoding
                assert encoding is not None
                term = RdfTerm(
                    "uri", encoding.resource_iri(value.get(encoding.identity_property))
                )
            values[term.identity] = term
        return tuple(values[key] for key in sorted(values))

    def project_execution(self, report: ExecutionReport) -> tuple[RdfTerm, ...]:
        if not report.success:
            raise ValueError(
                "Failed execution cannot produce an empty successful answer."
            )
        if (
            self.mode == RDF_TERMS_V1
            and report.metadata.get("rdf_result_encoding") != RDF_TERMS_V1
        ):
            raise ValueError("RDF answer projection requires a typed execution result.")
        return self.project_rows(report.rows)


def exact_answer_match(actual: Iterable[RdfTerm], expected: Iterable[RdfTerm]) -> bool:
    """Compare explicit term sets; numeric lexical/value equivalence is not inferred."""

    def identities(items: Iterable[RdfTerm]) -> set[str]:
        result = set()
        for term in items:
            if not isinstance(term, RdfTerm) or term.kind == "bnode":
                raise ValueError(
                    "Exact answer matching requires globally identified RDF terms."
                )
            result.add(term.identity)
        return result

    return identities(actual) == identities(expected)
