"""Versioned local catalog and ontology providers for M15 resolution.

Both providers are deterministic, make zero external calls, and return only
candidate identifiers carried by an audited artifact.  The ontology adapter
is restricted to predicate and type holes; entity identity remains a catalog
plus user-clarification responsibility.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from xgap.semantic import SemanticHoleKind, normalize_semantic_mention
from xgap.tools.contracts import ToolContext, ToolEffect
from xgap.tools.resolution import (
    SEMANTIC_CATALOG_LOOKUP_TOOL,
    SEMANTIC_ONTOLOGY_LOOKUP_TOOL,
    USER_CLARIFY_TOOL,
    ResolutionCandidateRequest,
    ResolutionCandidateResponse,
    ResolutionCandidateTool,
    ResolutionProviderFailure,
)


CATALOG_SCHEMA_VERSION = "m15-e3-resolution-catalog-v1"
ONTOLOGY_SCHEMA_VERSION = "m15-e3-resolution-ontology-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#?=&%+-]{0,511}$")
_FORBIDDEN_NATIVE_KEYS = frozenset(
    {"cypher", "sparql", "gql", "native_query", "native_query_text", "query_text"}
)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_mapping(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")

    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError(f"{name} keys must be strings")
                if key.casefold() in _FORBIDDEN_NATIVE_KEYS:
                    raise ValueError("resolution artifacts must not contain native query text")
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    normalized = dict(value)
    visit(normalized)
    try:
        json.dumps(normalized, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain finite JSON") from exc
    return normalized


def _strings(
    value: object,
    *,
    name: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or (not value and not allow_empty):
        qualifier = "an array" if allow_empty else "a nonempty array"
        raise ValueError(f"{name} must be {qualifier}")
    result = tuple(value)
    if not all(isinstance(item, str) and item.strip() for item in result):
        raise ValueError(f"{name} must contain nonempty strings")
    normalized = tuple(normalize_semantic_mention(item) for item in result)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} must be unique after normalization")
    return result


def _load_artifact(
    path: str | Path,
    *,
    expected_sha256: str | None,
    name: str,
) -> tuple[dict[str, Any], str]:
    artifact_path = Path(path)
    if artifact_path.is_symlink() or not artifact_path.is_file():
        raise ValueError(f"{name} must be a regular file")
    if artifact_path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError(f"{name} exceeds 16 MiB")
    with artifact_path.open("rb") as handle:
        data = handle.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise ValueError(f"{name} exceeds 16 MiB")
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None:
        if not _SHA256.fullmatch(expected_sha256):
            raise ValueError("expected_sha256 must be a SHA-256 digest")
        if digest != expected_sha256:
            raise ValueError(f"{name} SHA-256 mismatch")
    try:
        raw = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} is not valid JSON") from exc
    return _safe_mapping(raw, name=name), digest


@dataclass(frozen=True)
class _CatalogEntry:
    candidate_id: str
    kind: SemanticHoleKind
    canonical_label: str
    aliases: tuple[str, ...]
    authoritative_mentions: tuple[str, ...]
    provenance: Mapping[str, Any]

    @property
    def normalized_labels(self) -> tuple[str, ...]:
        return tuple(
            normalize_semantic_mention(item)
            for item in (self.canonical_label, *self.aliases)
        )


class ArtifactCatalogProvider:
    """Exact normalized mention lookup over one immutable local catalog."""

    def __init__(
        self,
        path: str | Path,
        *,
        expected_sha256: str | None = None,
    ) -> None:
        artifact, digest = _load_artifact(
            path,
            expected_sha256=expected_sha256,
            name="resolution catalog artifact",
        )
        required = {
            "schema_version",
            "catalog_id",
            "catalog_version",
            "entries",
            "metadata",
        }
        if set(artifact) != required:
            raise ValueError("resolution catalog fields do not match the v1 contract")
        if artifact["schema_version"] != CATALOG_SCHEMA_VERSION:
            raise ValueError("resolution catalog schema is unsupported")
        for name in ("catalog_id", "catalog_version"):
            if not isinstance(artifact[name], str) or not _SAFE_ID.fullmatch(
                artifact[name]
            ):
                raise ValueError(f"resolution catalog {name} is invalid")
        if not isinstance(artifact["entries"], list) or not artifact["entries"]:
            raise ValueError("resolution catalog entries must be nonempty")
        entries: list[_CatalogEntry] = []
        for raw in artifact["entries"]:
            if not isinstance(raw, Mapping) or set(raw) != {
                "candidate_id",
                "kind",
                "canonical_label",
                "aliases",
                "authoritative_mentions",
                "provenance",
            }:
                raise ValueError("resolution catalog entry fields are invalid")
            candidate_id = raw["candidate_id"]
            canonical_label = raw["canonical_label"]
            if not isinstance(candidate_id, str) or not _SAFE_ID.fullmatch(candidate_id):
                raise ValueError("resolution catalog candidate_id is invalid")
            if not isinstance(canonical_label, str) or not canonical_label.strip():
                raise ValueError("resolution catalog canonical_label is invalid")
            try:
                kind = SemanticHoleKind(raw["kind"])
            except (TypeError, ValueError) as exc:
                raise ValueError("resolution catalog kind is invalid") from exc
            aliases = _strings(
                raw["aliases"],
                name=f"{candidate_id}.aliases",
                allow_empty=True,
            )
            authoritative = _strings(
                raw["authoritative_mentions"],
                name=f"{candidate_id}.authoritative_mentions",
                allow_empty=True,
            )
            known_labels = {
                normalize_semantic_mention(item)
                for item in (canonical_label, *aliases)
            }
            if not {
                normalize_semantic_mention(item) for item in authoritative
            }.issubset(known_labels):
                raise ValueError("authoritative_mentions must be declared labels")
            if kind is not SemanticHoleKind.ENTITY and authoritative:
                raise ValueError("only entity catalog entries may be authoritative")
            entries.append(
                _CatalogEntry(
                    candidate_id=candidate_id,
                    kind=kind,
                    canonical_label=canonical_label,
                    aliases=aliases,
                    authoritative_mentions=authoritative,
                    provenance=_safe_mapping(
                        raw["provenance"],
                        name=f"{candidate_id}.provenance",
                    ),
                )
            )
        if len({item.candidate_id for item in entries}) != len(entries):
            raise ValueError("resolution catalog candidate IDs must be unique")
        _safe_mapping(artifact["metadata"], name="resolution catalog metadata")
        self.catalog_id = artifact["catalog_id"]
        self.catalog_version = artifact["catalog_version"]
        self.artifact_sha256 = digest
        self._entries = tuple(entries)

    @property
    def candidate_kinds(self) -> dict[str, SemanticHoleKind]:
        return {entry.candidate_id: entry.kind for entry in self._entries}

    @property
    def source_id(self) -> str:
        return (
            f"catalog:{self.catalog_id}@{self.catalog_version}:"
            f"{self.artifact_sha256[:16]}"
        )

    def resolve(
        self,
        request: ResolutionCandidateRequest,
        context: ToolContext,
    ) -> ResolutionCandidateResponse:
        del context
        started = time.monotonic()
        mention = normalize_semantic_mention(request.mention)
        matches = [
            entry
            for entry in self._entries
            if entry.kind is request.hole_kind and mention in entry.normalized_labels
        ]
        if len(matches) > request.max_candidates:
            raise ResolutionProviderFailure(
                "catalog match exceeds max_candidates; refusing silent truncation",
                source_id=self.source_id,
                failure_category="candidate_cap_exceeded",
                metadata={
                    "artifact_sha256": self.artifact_sha256,
                    "matched_candidate_count": len(matches),
                    "max_candidates": request.max_candidates,
                },
            )
        candidate_ids = tuple(item.candidate_id for item in matches)
        authoritative = (
            request.hole_kind is SemanticHoleKind.ENTITY
            and len(matches) == 1
            and mention
            in {
                normalize_semantic_mention(item)
                for item in matches[0].authoritative_mentions
            }
        )
        return ResolutionCandidateResponse(
            hole_id=request.hole_id,
            candidate_ids=candidate_ids,
            source_id=self.source_id,
            authoritative=authoritative,
            external_calls=0,
            latency_ms=(time.monotonic() - started) * 1000.0,
            metadata={
                "schema_version": CATALOG_SCHEMA_VERSION,
                "catalog_id": self.catalog_id,
                "catalog_version": self.catalog_version,
                "artifact_sha256": self.artifact_sha256,
                "match_policy": "exact_normalized_mention_v1",
                "normalized_mention": mention,
                "matched_candidate_count": len(matches),
                "matches": [
                    {
                        "candidate_id": item.candidate_id,
                        "canonical_label": item.canonical_label,
                        "provenance": dict(item.provenance),
                    }
                    for item in matches
                ],
                "candidate_set_truncated": False,
            },
        )

    def resolve_bounded(
        self,
        request: ResolutionCandidateRequest,
        context: ToolContext,
    ) -> ResolutionCandidateResponse:
        """Explicit candidate truncation for the opt-in one-shot query path.

        Stable artifact order is a deterministic ranking policy, not a quality
        model. Stop after observing cap+1 matches; nonmatching entries still
        require scanning. An incomplete scan reports only a count lower bound.
        The legacy ``resolve`` retains its original no-truncation behavior.
        """
        del context
        if type(request.max_candidates) is not int or not 1 <= request.max_candidates <= 256:
            raise ValueError("Bounded catalog candidate cap must be from one to 256")
        started = time.monotonic()
        mention = normalize_semantic_mention(request.mention)
        matches, visited = [], 0
        for entry in self._entries:
            visited += 1
            if entry.kind is request.hole_kind and mention in entry.normalized_labels:
                matches.append(entry)
                if len(matches) > request.max_candidates:
                    break
        complete = visited == len(self._entries)
        truncated = len(matches) > request.max_candidates
        returned = matches[:request.max_candidates]
        authoritative = (complete and not truncated and request.hole_kind is SemanticHoleKind.ENTITY
            and len(matches) == 1 and mention in {
                normalize_semantic_mention(item) for item in matches[0].authoritative_mentions})
        return ResolutionCandidateResponse(hole_id=request.hole_id,
            candidate_ids=tuple(item.candidate_id for item in returned), source_id=self.source_id,
            authoritative=authoritative, external_calls=0,
            latency_ms=(time.monotonic() - started) * 1000.0,
            metadata={"schema_version": CATALOG_SCHEMA_VERSION, "catalog_id": self.catalog_id,
                "catalog_version": self.catalog_version, "artifact_sha256": self.artifact_sha256,
                "match_policy": "exact_normalized_mention_v1", "normalized_mention": mention,
                "ranking_policy": "artifact_entry_order_v1", "entries_visited": visited,
                "scan_complete": complete, "matched_candidate_count": len(matches) if complete else None,
                "matched_candidate_count_lower_bound": len(matches),
                "returned_candidate_count": len(returned), "max_candidates": request.max_candidates,
                "truncated": truncated, "candidate_set_truncated": truncated,
                "matches": [{"candidate_id": item.candidate_id, "canonical_label": item.canonical_label,
                             "provenance": dict(item.provenance)} for item in returned]})


@dataclass(frozen=True)
class _OntologyConcept:
    candidate_id: str
    kind: SemanticHoleKind
    labels: tuple[str, ...]
    provenance: Mapping[str, Any]


@dataclass(frozen=True)
class _OntologyRelation:
    source_id: str
    target_id: str
    relation: str
    deviation: float
    bidirectional: bool
    provenance: Mapping[str, Any]


class ArtifactOntologyProvider:
    """One-hop candidate expansion over a versioned predicate/type graph."""

    def __init__(
        self,
        path: str | Path,
        *,
        expected_sha256: str | None = None,
    ) -> None:
        artifact, digest = _load_artifact(
            path,
            expected_sha256=expected_sha256,
            name="resolution ontology artifact",
        )
        required = {
            "schema_version",
            "ontology_id",
            "ontology_version",
            "concepts",
            "relations",
            "metadata",
        }
        if set(artifact) != required:
            raise ValueError("resolution ontology fields do not match the v1 contract")
        if artifact["schema_version"] != ONTOLOGY_SCHEMA_VERSION:
            raise ValueError("resolution ontology schema is unsupported")
        for name in ("ontology_id", "ontology_version"):
            if not isinstance(artifact[name], str) or not _SAFE_ID.fullmatch(
                artifact[name]
            ):
                raise ValueError(f"resolution ontology {name} is invalid")
        if not isinstance(artifact["concepts"], list) or not artifact["concepts"]:
            raise ValueError("resolution ontology concepts must be nonempty")
        concepts: list[_OntologyConcept] = []
        for raw in artifact["concepts"]:
            if not isinstance(raw, Mapping) or set(raw) != {
                "candidate_id",
                "kind",
                "labels",
                "provenance",
            }:
                raise ValueError("resolution ontology concept fields are invalid")
            candidate_id = raw["candidate_id"]
            if not isinstance(candidate_id, str) or not _SAFE_ID.fullmatch(candidate_id):
                raise ValueError("resolution ontology candidate_id is invalid")
            try:
                kind = SemanticHoleKind(raw["kind"])
            except (TypeError, ValueError) as exc:
                raise ValueError("resolution ontology concept kind is invalid") from exc
            if kind not in {SemanticHoleKind.PREDICATE, SemanticHoleKind.TYPE}:
                raise ValueError("resolution ontology may contain only predicate/type concepts")
            concepts.append(
                _OntologyConcept(
                    candidate_id=candidate_id,
                    kind=kind,
                    labels=_strings(raw["labels"], name=f"{candidate_id}.labels"),
                    provenance=_safe_mapping(
                        raw["provenance"],
                        name=f"{candidate_id}.provenance",
                    ),
                )
            )
        concept_map = {item.candidate_id: item for item in concepts}
        if len(concept_map) != len(concepts):
            raise ValueError("resolution ontology candidate IDs must be unique")

        if not isinstance(artifact["relations"], list):
            raise ValueError("resolution ontology relations must be an array")
        relations: list[_OntologyRelation] = []
        for raw in artifact["relations"]:
            if not isinstance(raw, Mapping) or set(raw) != {
                "source_id",
                "target_id",
                "relation",
                "deviation",
                "bidirectional",
                "provenance",
            }:
                raise ValueError("resolution ontology relation fields are invalid")
            source_id = raw["source_id"]
            target_id = raw["target_id"]
            relation = raw["relation"]
            if source_id not in concept_map or target_id not in concept_map:
                raise ValueError("resolution ontology relation references an unknown concept")
            if source_id == target_id:
                raise ValueError("resolution ontology relation cannot be self-referential")
            if concept_map[source_id].kind is not concept_map[target_id].kind:
                raise ValueError("resolution ontology relation crosses hole kinds")
            if not isinstance(relation, str) or not _SAFE_ID.fullmatch(relation):
                raise ValueError("resolution ontology relation name is invalid")
            deviation = raw["deviation"]
            if (
                isinstance(deviation, bool)
                or not isinstance(deviation, (int, float))
                or not 0.0 <= float(deviation) <= 1.0
            ):
                raise ValueError("resolution ontology deviation must be in [0, 1]")
            if not isinstance(raw["bidirectional"], bool):
                raise ValueError("resolution ontology bidirectional must be boolean")
            relations.append(
                _OntologyRelation(
                    source_id=source_id,
                    target_id=target_id,
                    relation=relation,
                    deviation=float(deviation),
                    bidirectional=raw["bidirectional"],
                    provenance=_safe_mapping(
                        raw["provenance"],
                        name=f"{source_id}->{target_id}.provenance",
                    ),
                )
            )
        if len(
            {
                (item.source_id, item.target_id, item.relation, item.bidirectional)
                for item in relations
            }
        ) != len(relations):
            raise ValueError("resolution ontology relations must be unique")
        _safe_mapping(artifact["metadata"], name="resolution ontology metadata")
        self.ontology_id = artifact["ontology_id"]
        self.ontology_version = artifact["ontology_version"]
        self.artifact_sha256 = digest
        self._concepts = tuple(concepts)
        self._concept_map = concept_map
        self._relations = tuple(relations)

    @property
    def candidate_kinds(self) -> dict[str, SemanticHoleKind]:
        return {concept.candidate_id: concept.kind for concept in self._concepts}

    @property
    def source_id(self) -> str:
        return (
            f"ontology:{self.ontology_id}@{self.ontology_version}:"
            f"{self.artifact_sha256[:16]}"
        )

    def resolve(
        self,
        request: ResolutionCandidateRequest,
        context: ToolContext,
    ) -> ResolutionCandidateResponse:
        del context
        if request.hole_kind not in {
            SemanticHoleKind.PREDICATE,
            SemanticHoleKind.TYPE,
        }:
            raise ResolutionProviderFailure(
                "ontology resolution is unavailable for this hole kind",
                source_id=self.source_id,
                failure_category="unsupported_hole_kind",
            )
        started = time.monotonic()
        mention = normalize_semantic_mention(request.mention)
        result: list[str] = list(request.candidate_ids)
        mention_matches = [
            item.candidate_id
            for item in self._concepts
            if item.kind is request.hole_kind
            and mention
            in {normalize_semantic_mention(label) for label in item.labels}
        ]
        for candidate_id in mention_matches:
            if candidate_id not in result:
                result.append(candidate_id)
        seed_ids = tuple(result)
        expansions: list[dict[str, Any]] = []
        for relation in self._relations:
            targets: list[tuple[str, str]] = []
            if relation.source_id in seed_ids:
                targets.append((relation.source_id, relation.target_id))
            if relation.bidirectional and relation.target_id in seed_ids:
                targets.append((relation.target_id, relation.source_id))
            for source_id, target_id in targets:
                target = self._concept_map[target_id]
                if target.kind is not request.hole_kind:
                    continue
                if target_id not in result:
                    result.append(target_id)
                expansions.append(
                    {
                        "source_id": source_id,
                        "target_id": target_id,
                        "relation": relation.relation,
                        "deviation": relation.deviation,
                        "provenance": dict(relation.provenance),
                    }
                )
        if len(result) > request.max_candidates:
            raise ResolutionProviderFailure(
                "ontology expansion exceeds max_candidates; refusing silent truncation",
                source_id=self.source_id,
                failure_category="candidate_cap_exceeded",
                metadata={
                    "artifact_sha256": self.artifact_sha256,
                    "expanded_candidate_count": len(result),
                    "max_candidates": request.max_candidates,
                },
            )
        return ResolutionCandidateResponse(
            hole_id=request.hole_id,
            candidate_ids=tuple(result),
            source_id=self.source_id,
            authoritative=False,
            external_calls=0,
            latency_ms=(time.monotonic() - started) * 1000.0,
            metadata={
                "schema_version": ONTOLOGY_SCHEMA_VERSION,
                "ontology_id": self.ontology_id,
                "ontology_version": self.ontology_version,
                "artifact_sha256": self.artifact_sha256,
                "lookup_policy": "exact_label_plus_one_hop_v1",
                "normalized_mention": mention,
                "request_candidate_ids": list(request.candidate_ids),
                "mention_match_candidate_ids": mention_matches,
                "expansions": expansions,
                "candidate_set_truncated": False,
                "entity_resolution_allowed": False,
            },
        )


class ExplicitUserSelectionProvider:
    """Represent an already-collected user choice as an authoritative tool call."""

    def __init__(self, selections: Mapping[str, str], *, source_id: str) -> None:
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("user-selection source_id must be nonempty")
        normalized = dict(selections)
        if not normalized or not all(
            isinstance(hole_id, str)
            and hole_id.strip()
            and isinstance(candidate_id, str)
            and _SAFE_ID.fullmatch(candidate_id)
            for hole_id, candidate_id in normalized.items()
        ):
            raise ValueError("user selections must map hole IDs to candidate IDs")
        self._selections = normalized
        self.source_id = source_id

    def resolve(
        self,
        request: ResolutionCandidateRequest,
        context: ToolContext,
    ) -> ResolutionCandidateResponse:
        del context
        if request.hole_kind is not SemanticHoleKind.ENTITY:
            raise ResolutionProviderFailure(
                "user identity clarification accepts only entity holes",
                source_id=self.source_id,
                failure_category="unsupported_hole_kind",
            )
        selected = self._selections.get(request.hole_id)
        if selected is None:
            raise ResolutionProviderFailure(
                "no explicit user selection exists for this entity hole",
                source_id=self.source_id,
                failure_category="user_input_unavailable",
            )
        if selected not in request.candidate_ids:
            raise ResolutionProviderFailure(
                "explicit user selection is outside the bounded candidate set",
                source_id=self.source_id,
                failure_category="out_of_set_user_selection",
            )
        return ResolutionCandidateResponse(
            hole_id=request.hole_id,
            candidate_ids=(selected,),
            source_id=self.source_id,
            authoritative=True,
            external_calls=1,
            metadata={
                "selection_authority": "explicit_user_input",
                "candidate_set_size": len(request.candidate_ids),
            },
        )


def artifact_catalog_tool(
    provider: ArtifactCatalogProvider,
) -> ResolutionCandidateTool:
    return ResolutionCandidateTool(
        name=SEMANTIC_CATALOG_LOOKUP_TOOL,
        description="Look up bounded semantic candidate IDs in a versioned local catalog",
        provider=provider,
        may_introduce_candidates=True,
        effect=ToolEffect.READ_ONLY,
        remote=False,
        maximum_external_calls=0,
        tags=("semantic_resolution", "catalog", "artifact_backed", "local"),
    )


def artifact_ontology_tool(
    provider: ArtifactOntologyProvider,
) -> ResolutionCandidateTool:
    return ResolutionCandidateTool(
        name=SEMANTIC_ONTOLOGY_LOOKUP_TOOL,
        description="Expand predicate/type candidate IDs by one audited ontology hop",
        provider=provider,
        may_introduce_candidates=True,
        effect=ToolEffect.READ_ONLY,
        remote=False,
        maximum_external_calls=0,
        tags=("semantic_resolution", "ontology", "artifact_backed", "local"),
    )


def explicit_user_clarification_tool(
    provider: ExplicitUserSelectionProvider,
) -> ResolutionCandidateTool:
    return ResolutionCandidateTool(
        name=USER_CLARIFY_TOOL,
        description="Apply one explicit bounded user identity selection",
        provider=provider,
        may_introduce_candidates=False,
        effect=ToolEffect.EXTERNAL,
        remote=False,
        maximum_external_calls=1,
        tags=("semantic_resolution", "user_clarification", "authoritative"),
    )
