"""RDF term identity and strict SELECT results, without an RDF dependency."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Mapping


RDF_TERMS_V1 = "rdf_terms_v1"
XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"
RDF_LANG_STRING = "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"


def validate_iri(value: str) -> str:
    if not isinstance(value, str) or not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value):
        raise ValueError("RDF IRI must be absolute.")
    if any(
        c in '<>"{}|^`\\' or ord(c) <= 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF
        for c in value
    ):
        raise ValueError("RDF IRI contains unsafe characters.")
    return value


@dataclass(frozen=True)
class RdfTerm:
    kind: str
    value: str
    datatype: str | None = None
    language: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or any(
            0xD800 <= ord(c) <= 0xDFFF for c in self.value
        ):
            raise ValueError("RDF term needs a Unicode scalar string.")
        if self.kind == "uri":
            validate_iri(self.value)
        elif self.kind == "bnode":
            if not re.fullmatch(
                r"[A-Za-z0-9_][A-Za-z0-9_.-]*", self.value
            ) or self.value.endswith("."):
                raise ValueError("Unsupported blank-node identifier.")
        elif self.kind != "literal":
            raise ValueError("Unsupported RDF term kind.")
        if self.kind != "literal":
            if self.datatype is not None or self.language is not None:
                raise ValueError("Only literals have datatype/language.")
            return
        if self.language is not None:
            if not isinstance(self.language, str) or not re.fullmatch(
                r"[A-Za-z]+(?:-[A-Za-z0-9]+)*", self.language
            ):
                raise ValueError("Invalid RDF language tag.")
            if self.datatype not in (None, RDF_LANG_STRING):
                raise ValueError("Language and datatype disagree.")
            object.__setattr__(self, "language", self.language.lower())
            object.__setattr__(self, "datatype", RDF_LANG_STRING)
        else:
            if self.datatype == RDF_LANG_STRING:
                raise ValueError("rdf:langString requires a language tag.")
            object.__setattr__(
                self,
                "datatype",
                validate_iri(XSD_STRING if self.datatype is None else self.datatype),
            )

    @classmethod
    def from_binding(cls, value: Mapping[str, Any]) -> "RdfTerm":
        if not isinstance(value, Mapping) or set(value) - {
            "type",
            "value",
            "datatype",
            "xml:lang",
        }:
            raise ValueError("Invalid SPARQL term binding.")
        kind = value.get("type")
        if kind == "typed-literal":
            if not value.get("datatype"):
                raise ValueError("typed-literal requires datatype.")
            kind = "literal"
        return cls(
            kind, value.get("value"), value.get("datatype"), value.get("xml:lang")
        )

    def to_binding(self) -> dict[str, str]:
        result = {"type": self.kind, "value": self.value}
        if self.language is not None:
            result["xml:lang"] = self.language
        elif self.datatype is not None:
            result["datatype"] = self.datatype
        return result

    def ntriples(self) -> str:
        if self.kind == "uri":
            return f"<{self.value}>"
        if self.kind == "bnode":
            return "_:" + self.value
        # N-Triples does not accept JSON's \b/\f escapes or UTF-16 surrogates.
        text = (
            '"'
            + "".join(
                {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}.get(
                    c, f"\\u{ord(c):04X}" if ord(c) < 32 or ord(c) == 127 else c
                )
                for c in self.value
            )
            + '"'
        )
        return text + (
            "@" + self.language if self.language else "^^<" + self.datatype + ">"
        )

    @property
    def identity(self) -> str:
        return json.dumps(
            self.to_binding(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )


def parse_select_results(
    payload: object, *, expected_columns: tuple[str, ...] | None = None
) -> list[dict[str, Any]]:
    """Keep RDF term kinds; missing/malformed result envelopes are not empty success."""
    if not isinstance(payload, Mapping) or "boolean" in payload:
        raise ValueError("RDF term mode requires a SELECT result object.")
    head, results = payload.get("head"), payload.get("results")
    if not isinstance(head, Mapping) or not isinstance(results, Mapping):
        raise ValueError("SELECT result requires head and results.")
    columns = head.get("vars")
    if (
        not isinstance(columns, list)
        or not all(isinstance(c, str) and c for c in columns)
        or len(set(columns)) != len(columns)
    ):
        raise ValueError("SELECT columns must be unique variable names.")
    if expected_columns is not None and set(columns) != set(expected_columns):
        raise ValueError("SELECT columns differ from the compiled contract.")
    bindings = results.get("bindings")
    if not isinstance(bindings, list):
        raise ValueError("SELECT result requires a bindings array.")
    rows = []
    for row in bindings:
        if not isinstance(row, Mapping) or set(row) - set(columns):
            raise ValueError("SELECT row contains invalid variables.")
        terms = {name: RdfTerm.from_binding(value) for name, value in row.items()}
        # Blank-node labels are scoped to one response, never cross-source IDs.
        # Until the runtime carries that scope, fail explicitly instead of
        # allowing coordinator equality to join unrelated response-local labels.
        if any(term.kind == "bnode" for term in terms.values()):
            raise ValueError(
                "Blank-node federation requires result-scoped identity; unsupported in rdf_terms_v1."
            )
        rows.append({name: term.to_binding() for name, term in terms.items()})
    return rows
