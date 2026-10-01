"""Explicit dataset representation options for the directed-row compiler."""

from dataclasses import asdict, dataclass
import hashlib
import json
import re

from xgap.backends.rdf_terms import validate_iri


@dataclass(frozen=True)
class RdfEdgeEncoding:
    """Dataset-owned reified edges: one resource per property-graph edge.

    Source, target and label are functional on each edge resource. Resource
    IRIs, rather than predicate IRIs, are returned in the edge columns. The
    dataset must supply stable IRIs; no identity is synthesized by the compiler.
    """

    encoding_id: str
    edge_class_iri: str
    source_predicate_iri: str
    target_predicate_iri: str
    label_predicate_iri: str
    label_encoding: str = "mapped_iri"
    class_predicate_iri: str = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

    def __post_init__(self) -> None:
        if not isinstance(self.encoding_id, str) or not self.encoding_id.strip():
            raise ValueError("RDF edge encoding requires identity.")
        for value in (self.edge_class_iri, self.source_predicate_iri,
                      self.target_predicate_iri, self.label_predicate_iri,
                      self.class_predicate_iri):
            validate_iri(value)
        if self.label_encoding not in ("mapped_iri", "logical_string"):
            raise ValueError("RDF edge labels require mapped_iri or logical_string encoding.")

    @property
    def identity(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True)
class RdfRowEncoding:
    encoding_id: str
    class_predicate_iri: str
    identity_property: str
    resource_namespace: str

    def __post_init__(self) -> None:
        if not isinstance(self.encoding_id, str) or not self.encoding_id.strip():
            raise ValueError("RDF encoding requires identity.")
        if (
            not isinstance(self.identity_property, str)
            or not self.identity_property.strip()
        ):
            raise ValueError("RDF encoding requires a logical identity property.")
        validate_iri(self.class_predicate_iri)
        validate_iri(self.resource_namespace)

    def resource_iri(self, identifier: object) -> str:
        # Canonical local IDs, not absolute URIs, native text or URI-encoded escapes.
        if not isinstance(identifier, str) or not re.fullmatch(
            r"[A-Za-z0-9_][A-Za-z0-9_.-]*", identifier
        ):
            raise ValueError("Resource identity must be a canonical local identifier.")
        return validate_iri(self.resource_namespace + identifier)

    @property
    def identity(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True)
class RdfResourceTripleEncoding:
    """A snapshot's unique URI triples are its directed logical edges.

    The existing resource mirror stores node IRIs and relationship predicates;
    complete returned triples determine edge identity without changing storage.
    """

    encoding_id: str
    snapshot_id: str
    resource_namespace: str
    identity_property: str = "type.object.id"
    class_predicate_iri: str = "http://rdf.freebase.com/ns/type.object.type"
    max_rows: int = 10000

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip()
               for value in (self.encoding_id, self.snapshot_id)):
            raise ValueError("Resource triple encoding requires encoding and snapshot identities.")
        if type(self.max_rows) is not int or self.max_rows <= 0:
            raise ValueError("Resource triple encoding requires a positive row budget.")
        # Reuse the node identity and IRI validation contract.
        self.rdf

    @property
    def rdf(self) -> RdfRowEncoding:
        return RdfRowEncoding(self.encoding_id, self.class_predicate_iri,
                              self.identity_property, self.resource_namespace)

    @property
    def identity(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
