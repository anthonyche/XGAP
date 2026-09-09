"""Explicit dataset representation options for the directed-row compiler."""

from dataclasses import asdict, dataclass
import hashlib
import json
import re

from xgap.backends.rdf_terms import validate_iri


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
