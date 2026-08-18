"""Normalized backend-native term mappings for dataset-aware compilation."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping


_IRI_RE = re.compile(r"^(?:https?://|urn:)[^\s<>]+$")
_EXPECTED_KINDS = {
    "node_labels": "class",
    "edge_labels": "relation",
    "properties": "property",
}


class BackendMappingError(ValueError):
    """Raised when a native backend mapping cannot resolve a compiler token."""


@dataclass(frozen=True)
class MappedNativeTerm:
    logical_token: str
    canonical_term_id: str
    kind: str
    iri: str

    def to_dict(self) -> dict[str, str]:
        return {
            "logical_token": self.logical_token,
            "canonical_term_id": self.canonical_term_id,
            "kind": self.kind,
            "iri": self.iri,
        }


@dataclass(frozen=True)
class RdfBackendMapping:
    """Dataset-owned mapping from XGAP compiler tokens to RDF IRIs."""

    mapping_id: str
    version: str
    backend_id: str
    namespace: str
    prefixes: Mapping[str, str]
    term_mappings: Mapping[str, Mapping[str, Any]]
    compiler_tokens: Mapping[str, Mapping[str, str]]
    mapping_hash: str

    @classmethod
    def from_artifact(
        cls,
        artifact: Mapping[str, Any],
        *,
        backend_id: str = "fuseki",
    ) -> "RdfBackendMapping":
        artifact = normalize_backend_mapping_artifact(
            artifact, backend_id=backend_id
        )
        mapping_id = str(artifact.get("mapping_id", ""))
        version = str(artifact.get("version", ""))
        if not mapping_id or not version:
            raise BackendMappingError("Backend mapping requires mapping_id and version.")
        backends = _mapping(artifact.get("backends"), "backends")
        backend = _mapping(backends.get(backend_id), f"backends.{backend_id}")
        namespace = str(backend.get("namespace", ""))
        if not _IRI_RE.fullmatch(namespace):
            raise BackendMappingError(
                f"Backend mapping '{backend_id}' requires an absolute RDF namespace."
            )
        raw_prefixes = backend.get("prefixes", {"xgap": namespace})
        prefixes = {
            str(name): str(value)
            for name, value in _optional_mapping(
                raw_prefixes, f"backends.{backend_id}.prefixes"
            ).items()
        }
        prefixes.setdefault("xgap", namespace)
        if any(not _IRI_RE.fullmatch(value) for value in prefixes.values()):
            raise BackendMappingError("RDF mapping prefixes must expand to absolute IRIs.")

        all_term_mappings = _mapping(artifact.get("term_mappings"), "term_mappings")
        terms = {
            str(term_id): _mapping(record, f"term_mappings.{backend_id}.{term_id}")
            for term_id, record in _mapping(
                all_term_mappings.get(backend_id), f"term_mappings.{backend_id}"
            ).items()
        }
        raw_tokens = _optional_mapping(
            backend.get("compiler_tokens"),
            f"backends.{backend_id}.compiler_tokens",
        )
        compiler_tokens: dict[str, dict[str, str]] = {}
        for token_kind in _EXPECTED_KINDS:
            compiler_tokens[token_kind] = {
                str(token): str(term_id)
                for token, term_id in _optional_mapping(
                    raw_tokens.get(token_kind),
                    f"backends.{backend_id}.compiler_tokens.{token_kind}",
                ).items()
            }
        mapping_hash = hashlib.sha256(
            json.dumps(
                artifact,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        normalized = cls(
            mapping_id=mapping_id,
            version=version,
            backend_id=backend_id,
            namespace=namespace,
            prefixes=prefixes,
            term_mappings=terms,
            compiler_tokens=compiler_tokens,
            mapping_hash=mapping_hash,
        )
        normalized.validate()
        return normalized

    def validate(self) -> None:
        for token_kind, expected_kind in _EXPECTED_KINDS.items():
            for token in self.compiler_tokens[token_kind]:
                self.resolve(token, token_kind, expected_kind=expected_kind)

    def resolve(
        self,
        logical_token: str,
        token_kind: str,
        *,
        expected_kind: str | None = None,
    ) -> MappedNativeTerm:
        if token_kind not in _EXPECTED_KINDS:
            raise BackendMappingError(f"Unknown compiler token kind '{token_kind}'.")
        required_kind = expected_kind or _EXPECTED_KINDS[token_kind]
        canonical_term_id = self.compiler_tokens[token_kind].get(
            logical_token, logical_token
        )
        record = self.term_mappings.get(canonical_term_id)
        if record is None:
            raise BackendMappingError(
                f"No {self.backend_id} mapping for {token_kind} token "
                f"'{logical_token}' (canonical term '{canonical_term_id}')."
            )
        actual_kind = str(record.get("kind", ""))
        if actual_kind != required_kind:
            raise BackendMappingError(
                f"Mapped term '{canonical_term_id}' has kind '{actual_kind}', "
                f"expected '{required_kind}'."
            )
        iri = self._expand_iri(str(record.get("representation", "")))
        return MappedNativeTerm(
            logical_token=logical_token,
            canonical_term_id=canonical_term_id,
            kind=actual_kind,
            iri=iri,
        )

    def _expand_iri(self, representation: str) -> str:
        value = representation.strip()
        if value.startswith("<") and value.endswith(">"):
            value = value[1:-1]
        if _IRI_RE.fullmatch(value):
            return value
        if ":" in value:
            prefix, local_name = value.split(":", 1)
            namespace = self.prefixes.get(prefix)
            if namespace and local_name and not any(char.isspace() for char in local_name):
                return namespace + local_name
        raise BackendMappingError(
            f"RDF representation '{representation}' is not an absolute or mapped compact IRI."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_id": self.mapping_id,
            "version": self.version,
            "backend_id": self.backend_id,
            "namespace": self.namespace,
            "prefixes": dict(self.prefixes),
            "compiler_tokens": {
                key: dict(value) for key, value in self.compiler_tokens.items()
            },
            "mapping_hash": self.mapping_hash,
        }


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BackendMappingError(f"Backend mapping field '{name}' must be an object.")
    return dict(value)


def _optional_mapping(value: object, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    return _mapping(value, name)


def normalize_backend_mapping_artifact(
    artifact: Mapping[str, Any],
    *,
    backend_id: str = "fuseki",
) -> dict[str, Any]:
    """Canonicalize YAML nulls that denote explicit empty mapping fields."""

    normalized = deepcopy(dict(artifact))
    backends = normalized.get("backends")
    if isinstance(backends, Mapping):
        backends = dict(backends)
        normalized["backends"] = backends
        backend = backends.get(backend_id)
        if isinstance(backend, Mapping):
            backend = dict(backend)
            backends[backend_id] = backend
            if backend.get("prefixes") is None and "prefixes" in backend:
                backend["prefixes"] = {}
            tokens = backend.get("compiler_tokens")
            if tokens is None and "compiler_tokens" in backend:
                backend["compiler_tokens"] = {}
            elif isinstance(tokens, Mapping):
                tokens = dict(tokens)
                backend["compiler_tokens"] = tokens
                for token_kind in _EXPECTED_KINDS:
                    if tokens.get(token_kind) is None and token_kind in tokens:
                        tokens[token_kind] = {}

    term_mappings = normalized.get("term_mappings")
    if isinstance(term_mappings, Mapping):
        term_mappings = dict(term_mappings)
        normalized["term_mappings"] = term_mappings
        if term_mappings.get(backend_id) is None and backend_id in term_mappings:
            term_mappings[backend_id] = {}
    return normalized
