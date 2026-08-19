"""Query-independent Freebase catalog v2 construction and retrieval.

The builder streams the official Freebase RDF dump into SQLite and emits
canonical JSONL files.  It deliberately accepts no GrailQA question or gold
artifact path.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
from typing import Any, Iterable, Iterator, Mapping, Sequence, TextIO

from xgap.experiments.grailqa_catalog import normalized_label, sha256_file
from xgap.experiments.hashing import content_hash
from xgap.experiments.runtime_alignment import (
    PromptQuerySlot,
    PromptSchemaView,
    RetrievalLimits,
    RetrievedOntologyTerm,
)
from xgap.experiments.semantic import OntologyGraph
from xgap.infrastructure.descriptors import load_yaml_mapping


CATALOG_V2_SCHEMA_VERSION = "m13e1-grailqa-inference-catalog-v2"
RETRIEVAL_V2_SCHEMA_VERSION = "m13e1-grailqa-retrieval-v2"
OFFICIAL_FREEBASE_DUMP_URL = (
    "https://storage.googleapis.com/freebase-public/rdf/freebase-rdf-latest.gz"
)
FREEBASE_NAMESPACE = "http://rdf.freebase.com/ns/"
NAME_PREDICATE = "type.object.name"
ALIAS_PREDICATE = "common.topic.alias"
TYPE_PREDICATE = "type.object.type"
_TRIPLE = re.compile(
    r'^<(?P<subject>[^>]*)> <(?P<predicate>[^>]*)> '
    r'(?:(?:"(?P<literal>(?:[^"\\]|\\.)*)"@(?P<lang>[A-Za-z-]+))|'
    r'(?:<(?P<object>[^>]*)>)) \.\s*$'
)
_ESCAPE = re.compile(r"\\(?:[tbnrf\"\\]|u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8})")
_MID = re.compile(r"^[mg]\.[A-Za-z0-9_-]+$")
SOURCE_MANIFEST_SCHEMA_VERSION = "m13e3-freebase-source-manifest-v1"
INTEGRITY_SCHEMA_VERSION = "m13e3-freebase-catalog-integrity-v1"


@dataclass(frozen=True)
class CatalogV2Candidate:
    candidate_id: str
    label: str
    kind: str
    score: float
    rank: int
    matched_label: str
    evidence: tuple[str, ...]
    domain: str | None = None
    range: str | None = None
    reverse_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.candidate_id,
            "label": self.label,
            "kind": self.kind,
            "score": self.score,
            "rank": self.rank,
            "matched_label": self.matched_label,
            "evidence": list(self.evidence),
            "domain": self.domain,
            "range": self.range,
            "reverse_id": self.reverse_id,
        }


@dataclass(frozen=True)
class CatalogV2Retrieval:
    question_id: str
    question: str
    catalog_hash: str
    entities: tuple[CatalogV2Candidate, ...]
    relations_by_slot: tuple[tuple[CatalogV2Candidate, ...], ...]
    types: tuple[CatalogV2Candidate, ...]
    expanded_types: tuple[str, ...]

    @property
    def relations(self) -> tuple[CatalogV2Candidate, ...]:
        return self.relations_by_slot[0] if self.relations_by_slot else ()

    @property
    def types_for_prompt(self) -> tuple[CatalogV2Candidate, ...]:
        return self.types

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RETRIEVAL_V2_SCHEMA_VERSION,
            "question_id": self.question_id,
            "question_hash": hashlib.sha256(self.question.encode("utf-8")).hexdigest(),
            "catalog_hash": self.catalog_hash,
            "config": {
                "entity_channels": ["exact_alias", "normalized_alias", "bm25"],
                "relation_channels": ["lexical_bm25", "public_metadata"],
                "relation_slots": len(self.relations_by_slot),
                "gold_inputs": False,
                "tie_break": "score_descending_then_id",
            },
            "entity_candidates": [item.to_dict() for item in self.entities],
            "relation_slots": [
                {
                    "slot_id": f"relation-hop-{index}",
                    "candidates": [item.to_dict() for item in values],
                }
                for index, values in enumerate(self.relations_by_slot, start=1)
            ],
            "type_candidates": [item.to_dict() for item in self.types],
            "expanded_type_ids": list(self.expanded_types),
        }


@dataclass(frozen=True)
class _Term:
    term_id: str
    label: str
    kind: str
    aliases: tuple[str, ...]
    domain: str | None
    range: str | None
    reverse_id: str | None


@dataclass(frozen=True)
class GrailQAInferenceCatalogV2:
    root: Path
    manifest: Mapping[str, Any]
    ontology: OntologyGraph
    terms: tuple[_Term, ...]

    @classmethod
    def load(cls, root: str | Path) -> "GrailQAInferenceCatalogV2":
        catalog_root = Path(root)
        manifest_path = catalog_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != CATALOG_V2_SCHEMA_VERSION:
            raise ValueError("Unsupported GrailQA inference catalog v2 schema.")
        if manifest.get("status") != "complete":
            reason = str(manifest.get("blocked_reason", "catalog construction is incomplete"))
            raise ValueError(f"GrailQA inference catalog v2 is not complete: {reason}")
        for name, expected in _mapping(manifest.get("file_hashes"), "file_hashes").items():
            if sha256_file(catalog_root / name) != str(expected):
                raise ValueError(f"Inference catalog v2 hash mismatch for {name}.")
        ontology = OntologyGraph.from_dict(load_yaml_mapping(catalog_root / "ontology.yaml"))
        if ontology.ontology_hash != manifest.get("ontology_hash"):
            raise ValueError("Inference catalog v2 ontology hash mismatch.")
        relation_aliases = _aliases_by_id(catalog_root / "relation_aliases.jsonl")
        type_aliases = _aliases_by_id(catalog_root / "type_aliases.jsonl")
        terms = tuple(
            _Term(
                term_id=str(item["id"]),
                label=str(item["label"]),
                kind=str(item["kind"]),
                aliases=(relation_aliases if item["kind"] == "relation" else type_aliases).get(
                    str(item["id"]), ()
                ),
                domain=_optional_string(item.get("domain")),
                range=_optional_string(item.get("range")),
                reverse_id=_optional_string(item.get("reverse_id")),
            )
            for item in _read_jsonl(catalog_root / "terms.jsonl")
        )
        return cls(catalog_root, manifest, ontology, terms)

    @property
    def catalog_hash(self) -> str:
        return str(self.manifest["catalog_hash"])

    def retrieve(
        self,
        question_id: str,
        question: str,
        *,
        top_k: int = 20,
        relation_slots: int = 3,
        expansion_hops: int = 1,
    ) -> CatalogV2Retrieval:
        if top_k <= 0:
            raise ValueError("top_k must be positive.")
        if relation_slots not in (1, 2, 3):
            raise ValueError("relation_slots must be within the supported bound [1, 3].")
        if expansion_hops not in (0, 1, 2):
            raise ValueError("expansion_hops must be within the supported bound [0, 2].")
        entities = self._retrieve_entities(question, top_k)
        relations = self._retrieve_relation_slots(question, top_k, relation_slots)
        ranked_types = _rank_terms(
            question, (term for term in self.terms if term.kind == "type"), top_k
        )
        expanded = self._expand_types(relations, expansion_hops)
        types = _merge_expanded_types(ranked_types, expanded, self.terms, top_k)
        return CatalogV2Retrieval(
            question_id=str(question_id),
            question=question,
            catalog_hash=self.catalog_hash,
            entities=entities,
            relations_by_slot=relations,
            types=types,
            expanded_types=expanded,
        )

    def prompt_view(
        self,
        result: CatalogV2Retrieval,
        *,
        candidates_per_slot: int = 4,
        max_entities: int = 4,
    ) -> PromptSchemaView:
        type_candidates = result.types[:candidates_per_slot]
        relation_slots = tuple(
            values[:candidates_per_slot] for values in result.relations_by_slot
        )
        if not type_candidates or not relation_slots or not relation_slots[0]:
            raise ValueError("Catalog v2 prompt context requires type and relation candidates.")
        selected: dict[str, CatalogV2Candidate] = {
            item.candidate_id: item
            for item in (*type_candidates, *(item for slot in relation_slots for item in slot))
        }
        terms = tuple(
            RetrievedOntologyTerm(
                term_id=item.candidate_id,
                kind="class" if item.kind == "type" else item.kind,
                label=item.label,
                aliases=(item.matched_label,),
                retrieval_score=item.score,
                retrieval_provenance=(RETRIEVAL_V2_SCHEMA_VERSION, *item.evidence),
                domain=item.domain,
                range=item.range,
            )
            for _, item in sorted(selected.items())
        )
        slots: list[PromptQuerySlot] = [
            PromptQuerySlot(
                slot_id="retrieved-type",
                mention=result.question,
                kind="class",
                candidate_anchor_ids=tuple(item.candidate_id for item in type_candidates),
                retrieval_provenance=(RETRIEVAL_V2_SCHEMA_VERSION, "type_and_domain_range"),
            )
        ]
        slots.extend(
            PromptQuerySlot(
                slot_id=f"relation-hop-{index}",
                mention=result.question,
                kind="relation",
                candidate_anchor_ids=tuple(item.candidate_id for item in values),
                retrieval_provenance=(RETRIEVAL_V2_SCHEMA_VERSION, f"bounded_hop:{index}"),
                required_for_candidate=index == 1,
            )
            for index, values in enumerate(relation_slots, start=1)
        )
        entities = tuple(
            {
                "entity_id": item.candidate_id,
                "canonical_label": item.label,
                "aliases": [item.matched_label],
                "retrieval_score": item.score,
                "retrieval_rank": item.rank,
                "retrieval_evidence": list(item.evidence),
            }
            for item in result.entities[:max_entities]
        )
        limits = RetrievalLimits(
            max_slots=len(slots),
            max_candidates_per_slot=candidates_per_slot,
            max_entities=max_entities,
            max_schema_items=len(terms),
        )
        return PromptSchemaView(
            task_id=result.question_id,
            ontology_id=self.ontology.ontology_id,
            ontology_version=self.ontology.version,
            ontology_hash=self.ontology.ontology_hash,
            schema_snapshot_version=CATALOG_V2_SCHEMA_VERSION,
            schema_snapshot_hash=self.catalog_hash,
            terms=terms,
            entities=entities,
            query_slots=tuple(slots),
            backend_hints={},
            source_schema_items=tuple(sorted(selected)),
            limits=limits,
            retrieval_method=RETRIEVAL_V2_SCHEMA_VERSION,
        )

    def _retrieve_entities(self, question: str, top_k: int) -> tuple[CatalogV2Candidate, ...]:
        normalized = normalized_label(question)
        tokens = tuple(dict.fromkeys(normalized.split()))
        if not tokens:
            return ()
        database = self.root / "catalog.sqlite3"
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            scores: dict[str, tuple[float, str, set[str], str]] = {}
            exact_rows = connection.execute(
                """
                SELECT e.id, e.canonical_name, a.alias, a.normalized_alias
                FROM entity_aliases a JOIN entities e ON e.id = a.entity_id
                WHERE a.normalized_alias = ?
                ORDER BY e.id, a.alias
                """,
                (normalized,),
            )
            for row in exact_rows:
                scores[str(row["id"])] = (
                    100.0,
                    str(row["alias"]),
                    {"exact_alias", "normalized_alias"},
                    str(row["canonical_name"]),
                )
            match_query = " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)
            rows = connection.execute(
                """
                SELECT entity_id, alias, normalized_alias, bm25(entity_search) AS distance
                FROM entity_search WHERE entity_search MATCH ?
                ORDER BY distance, entity_id, alias LIMIT ?
                """,
                (match_query, max(top_k * 20, 100)),
            )
            names = {
                str(row["id"]): str(row["canonical_name"])
                for row in connection.execute(
                    "SELECT id, canonical_name FROM entities WHERE id IN "
                    "(SELECT entity_id FROM entity_search WHERE entity_search MATCH ? LIMIT ?)",
                    (match_query, max(top_k * 20, 100)),
                )
            }
            for row in rows:
                entity_id = str(row["entity_id"])
                alias = str(row["alias"])
                alias_normalized = str(row["normalized_alias"])
                distance = abs(float(row["distance"]))
                score = 10.0 + 1.0 / (1.0 + distance)
                evidence = {"bm25"}
                if alias_normalized in normalized:
                    score += 20.0
                    evidence.add("normalized_alias")
                previous = scores.get(entity_id)
                if previous is None or score > previous[0]:
                    scores[entity_id] = (
                        score,
                        alias,
                        evidence,
                        names.get(entity_id, alias),
                    )
                elif previous is not None and score == previous[0]:
                    previous[2].update(evidence)
            ranked = sorted(scores.items(), key=lambda item: (-item[1][0], item[0]))[:top_k]
            return tuple(
                CatalogV2Candidate(
                    candidate_id=entity_id,
                    label=payload[3],
                    kind="entity",
                    score=round(payload[0], 12),
                    rank=rank,
                    matched_label=payload[1],
                    evidence=tuple(sorted(payload[2])),
                )
                for rank, (entity_id, payload) in enumerate(ranked, start=1)
            )
        finally:
            connection.close()

    def _retrieve_relation_slots(
        self, question: str, top_k: int, slot_count: int
    ) -> tuple[tuple[CatalogV2Candidate, ...], ...]:
        base = _rank_terms(
            question,
            (term for term in self.terms if term.kind == "relation"),
            max(top_k * 4, 40),
        )
        slots: list[tuple[CatalogV2Candidate, ...]] = []
        prior_ranges: set[str] = set()
        for slot_index in range(slot_count):
            reranked: list[CatalogV2Candidate] = []
            for candidate in base:
                coherence = 0.0
                evidence = set(candidate.evidence)
                if slot_index and candidate.domain in prior_ranges:
                    coherence = 0.25
                    evidence.add("domain_range_chain")
                reranked.append(
                    CatalogV2Candidate(
                        **{
                            **candidate.__dict__,
                            "score": round(candidate.score + coherence, 12),
                            "rank": 0,
                            "evidence": tuple(sorted(evidence)),
                        }
                    )
                )
            reranked.sort(key=lambda item: (-item.score, item.candidate_id))
            selected = tuple(
                CatalogV2Candidate(**{**item.__dict__, "rank": rank})
                for rank, item in enumerate(reranked[:top_k], start=1)
            )
            slots.append(selected)
            prior_ranges = {item.range for item in selected if item.range is not None}
        return tuple(slots)

    def _expand_types(
        self,
        relation_slots: tuple[tuple[CatalogV2Candidate, ...], ...],
        hops: int,
    ) -> tuple[str, ...]:
        values = {
            term
            for slot in relation_slots
            for candidate in slot
            for term in (candidate.domain, candidate.range)
            if term is not None
        }
        frontier = set(values)
        for _ in range(hops):
            parents = {
                parent
                for child in frontier
                for parent in self.ontology.parents.get(child, ())
            }
            parents -= values
            values.update(parents)
            frontier = parents
        return tuple(sorted(values))


def build_catalog_v2(
    *,
    freebase_rdf_path: str | Path,
    normalized_ontology_path: str | Path,
    reverse_properties_path: str | Path,
    output_root: str | Path,
    source_url: str = OFFICIAL_FREEBASE_DUMP_URL,
    source_manifest_path: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Build a query-independent v2 catalog from the official Freebase dump."""

    source = Path(freebase_rdf_path)
    ontology_path = Path(normalized_ontology_path)
    reverse_path = Path(reverse_properties_path)
    output = Path(output_root).resolve()
    if not source.is_file() or not ontology_path.is_file() or not reverse_path.is_file():
        raise FileNotFoundError(
            "Freebase RDF dump, normalized ontology, and reverse-property map are required."
        )
    source_hash = sha256_file(source)
    source_metadata = _load_source_metadata(
        source=source,
        source_hash=source_hash,
        source_url=source_url,
        source_manifest_path=source_manifest_path,
    )
    ontology_source_hash = sha256_file(ontology_path)
    reverse_source_hash = sha256_file(reverse_path)
    existing = _complete_manifest(output)
    if existing is not None and not force:
        existing_source = _mapping(
            _mapping(existing.get("sources"), "sources").get("freebase_rdf"),
            "freebase_rdf",
        )
        existing_ontology = _mapping(
            _mapping(existing.get("sources"), "sources").get("ontology"),
            "ontology",
        )
        if (
            existing_source.get("sha256") == source_hash
            and existing_ontology.get("sha256") == ontology_source_hash
            and existing_ontology.get("reverse_properties_sha256") == reverse_source_hash
        ):
            validate_catalog_v2(output)
            return dict(existing)
        raise FileExistsError(
            f"Complete catalog already exists at {output} for different inputs; "
            "pass force=True or --force to replace it."
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(f".{output.name}.building")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    database = staging / "catalog.sqlite3"
    ontology = OntologyGraph.from_dict(load_yaml_mapping(ontology_path))
    reverse_properties = {
        str(key): str(value)
        for key, value in _mapping(
            json.loads(reverse_path.read_text(encoding="utf-8")), "reverse properties"
        ).items()
    }
    try:
        connection = sqlite3.connect(database)
        try:
            _create_database(connection)
            _seed_terms(connection, ontology, reverse_properties)
            ingestion = _ingest_freebase(connection, source)
            _finalize_database(connection)
            counts = _write_catalog_files(connection, staging, ontology)
            integrity = _database_integrity(connection, ontology)
        finally:
            connection.close()
        shutil.copyfile(ontology_path, staging / "ontology.yaml")
    except Exception:
        # Leave the staging directory for diagnosis. A retry safely replaces it.
        raise
    files = (
        "catalog.sqlite3",
        "entities.jsonl",
        "entity_aliases.jsonl",
        "entity_types.jsonl",
        "terms.jsonl",
        "type_aliases.jsonl",
        "relation_aliases.jsonl",
        "relation_metadata.jsonl",
        "reverse_properties.json",
        "ontology.yaml",
    )
    file_hashes = {name: sha256_file(staging / name) for name in files}
    catalog_hash = content_hash(
        {
            "schema_version": CATALOG_V2_SCHEMA_VERSION,
            "source_sha256": source_hash,
            "ontology_hash": ontology.ontology_hash,
            "content_file_hashes": {
                key: value for key, value in file_hashes.items() if key != "catalog.sqlite3"
            },
        }
    )
    manifest = {
        "schema_version": CATALOG_V2_SCHEMA_VERSION,
        "catalog_id": "grailqa_inference_catalog_v2",
        "status": "complete",
        "catalog_hash": catalog_hash,
        "ontology_hash": ontology.ontology_hash,
        "sources": {
            "freebase_rdf": {
                **source_metadata,
                "identity": "Google Freebase RDF dump (final public dump)",
                "revision_date": "2015-08-09",
                "license": "CC-BY-2.5; see official Freebase data-dump terms",
                "compressed_format": source_metadata["compressed_format"],
            },
            "ontology": {
                "identity": "Frozen normalized GrailQA official ontology",
                "sha256": ontology_source_hash,
                "reverse_properties_sha256": reverse_source_hash,
            },
        },
        "counts": {**counts, "parsed_triples": ingestion["parsed_triples"]},
        "ingestion_statistics": ingestion,
        "integrity": integrity,
        "database_size_bytes": database.stat().st_size,
        "hierarchy_statistics": {
            "classes": len(ontology.classes),
            "subsumption_edges": sum(len(values) for values in ontology.parents.values()),
            "relations_with_domain_range": len(ontology.domain_range),
        },
        "construction": {
            "command": (
                "PYTHONPATH=src python -m xgap.experiments.grailqa_catalog_v2 build "
                "--freebase-rdf <freebase-rdf-latest.gz> "
                "--normalized-ontology datasets/grailqa_pilot_v1/ontology.yaml "
                "--reverse-properties datasets/grailqa_inference_catalog_v1/reverse_properties.json "
                "--output datasets/grailqa_inference_catalog_v2"
            ),
            "query_dependent_inputs": False,
            "gold_inputs": False,
            "normalization": "NFKC casefold; Unicode-aware alphanumeric tokenization",
            "language_policy": "English @en names and aliases only; MID identity is language independent",
            "builder_git_commit": _git_commit(),
            "constructed_at": _utc_now(),
            "safe_restart": "complete matching catalogs are verified and reused; new builds publish atomically",
        },
        "file_hashes": file_hashes,
        "provenance_notes": [
            "No GrailQA question, answer, logical form, alignment, or reference plan is read.",
            "Only English type.object.name and common.topic.alias literals are indexed.",
        ],
    }
    manifest_path = staging / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    validate_catalog_v2(staging)
    _publish_catalog(staging, output)
    validate_catalog_v2(output)
    return manifest


def write_source_manifest(
    *,
    freebase_rdf_path: str | Path,
    output_path: str | Path,
    source_url: str = OFFICIAL_FREEBASE_DUMP_URL,
    http_headers_path: str | Path | None = None,
) -> dict[str, Any]:
    """Record the locally retrieved official dump without trusting its filename."""

    source = Path(freebase_rdf_path)
    if not source.is_file() or source.stat().st_size == 0:
        raise FileNotFoundError(f"Freebase RDF dump is missing or empty: {source}")
    headers = _http_metadata(Path(http_headers_path)) if http_headers_path else {}
    manifest = {
        "schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
        "status": "downloaded",
        "source_url": source_url,
        "retrieved_at": _utc_now(),
        "filename": source.name,
        "compressed_format": "gzip" if source.suffix == ".gz" else "plain_ntriples",
        "size_bytes": source.stat().st_size,
        "published_size": "approximately 22 GB gzip / 250 GB uncompressed",
        "sha256": sha256_file(source),
        "http": headers,
        "provenance": "Google Freebase final public RDF dump",
        "license": "CC-BY-2.5; official Freebase data-dump terms apply",
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def verify_source_manifest(
    *, freebase_rdf_path: str | Path, source_manifest_path: str | Path
) -> dict[str, Any]:
    """Verify a raw dump against the checksum frozen immediately after retrieval."""

    source = Path(freebase_rdf_path)
    manifest_path = Path(source_manifest_path)
    if not source.is_file() or not manifest_path.is_file():
        raise FileNotFoundError("Freebase RDF dump and source manifest are required.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SOURCE_MANIFEST_SCHEMA_VERSION:
        raise ValueError("Unsupported Freebase source-manifest schema.")
    actual = sha256_file(source)
    expected = str(manifest.get("sha256", ""))
    if not expected or actual != expected:
        raise ValueError(
            f"Freebase source checksum mismatch: expected {expected or '<missing>'}, got {actual}."
        )
    expected_size = int(manifest.get("size_bytes", -1))
    if source.stat().st_size != expected_size:
        raise ValueError("Freebase source size does not match its source manifest.")
    return {
        "schema_version": "m13e3-freebase-source-verification-v1",
        "status": "ok",
        "sha256": actual,
        "size_bytes": expected_size,
        "source_url": manifest.get("source_url"),
    }


def validate_catalog_v2(root: str | Path) -> dict[str, Any]:
    """Validate hashes, SQLite structure, indexes, and schema membership."""

    catalog = GrailQAInferenceCatalogV2.load(root)
    database = catalog.root / "catalog.sqlite3"
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        report = _database_integrity(connection, catalog.ontology)
    finally:
        connection.close()
    if report["errors"]:
        raise ValueError("Catalog v2 integrity failed: " + "; ".join(report["errors"]))
    return {
        "schema_version": INTEGRITY_SCHEMA_VERSION,
        "status": "ok",
        "catalog_hash": catalog.catalog_hash,
        **report,
    }


def _create_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode=DELETE;
        PRAGMA synchronous=NORMAL;
        CREATE TABLE entities(id TEXT PRIMARY KEY, canonical_name TEXT NOT NULL);
        CREATE TABLE entity_aliases(
          entity_id TEXT NOT NULL, alias TEXT NOT NULL, normalized_alias TEXT NOT NULL,
          alias_kind TEXT NOT NULL, UNIQUE(entity_id, alias)
        );
        CREATE TABLE entity_types(
          entity_id TEXT NOT NULL, type_id TEXT NOT NULL, UNIQUE(entity_id, type_id)
        );
        CREATE TABLE terms(
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, label TEXT NOT NULL,
          domain_id TEXT, range_id TEXT, reverse_id TEXT
        );
        CREATE TABLE term_aliases(
          term_id TEXT NOT NULL, alias TEXT NOT NULL, normalized_alias TEXT NOT NULL,
          UNIQUE(term_id, alias)
        );
        """
    )


def _seed_terms(
    connection: sqlite3.Connection,
    ontology: OntologyGraph,
    reverse_properties: Mapping[str, str],
) -> None:
    rows: list[tuple[str, str, str, str | None, str | None, None]] = []
    for kind, values in (("type", ontology.classes), ("relation", ontology.relations)):
        for term_id in values:
            metadata = ontology.domain_range.get(term_id, {})
            rows.append(
                (
                    term_id,
                    kind,
                    normalized_label(term_id.split(".")[-1]) or term_id,
                    metadata.get("domain"),
                    metadata.get("range"),
                    reverse_properties.get(term_id),
                )
            )
    connection.executemany(
        "INSERT INTO terms(id, kind, label, domain_id, range_id, reverse_id) VALUES(?,?,?,?,?,?)",
        rows,
    )
    connection.executemany(
        "INSERT INTO term_aliases(term_id, alias, normalized_alias) VALUES(?,?,?)",
        (
            (term_id, normalized_label(term_id), normalized_label(term_id))
            for term_id, *_ in rows
        ),
    )
    connection.commit()


def _ingest_freebase(connection: sqlite3.Connection, source: Path) -> dict[str, int]:
    pending_labels: list[tuple[str, str, str, str]] = []
    pending_types: list[tuple[str, str]] = []
    pending_term_labels: list[tuple[str, str, str, str]] = []
    known_terms = {str(row[0]) for row in connection.execute("SELECT id FROM terms")}
    statistics = {
        "input_lines": 0,
        "parsed_triples": 0,
        "unparsed_or_irrelevant_lines": 0,
        "rejected_non_english_literals": 0,
        "rejected_invalid_entity_ids": 0,
    }
    with _open_text(source) as handle:
        for line in handle:
            statistics["input_lines"] += 1
            triple = parse_freebase_triple(line)
            if triple is None:
                statistics["unparsed_or_irrelevant_lines"] += 1
                continue
            subject, predicate, value, language, is_resource = triple
            statistics["parsed_triples"] += 1
            if predicate in (NAME_PREDICATE, ALIAS_PREDICATE) and not is_resource:
                if language != "en":
                    statistics["rejected_non_english_literals"] += 1
                    continue
                alias_kind = "canonical" if predicate == NAME_PREDICATE else "alias"
                if subject in known_terms:
                    pending_term_labels.append(
                        (subject, value, normalized_label(value), alias_kind)
                    )
                elif _MID.fullmatch(subject):
                    pending_labels.append((subject, value, normalized_label(value), alias_kind))
                elif subject.startswith(("m.", "g.")):
                    statistics["rejected_invalid_entity_ids"] += 1
            elif predicate == TYPE_PREDICATE and is_resource:
                if _MID.fullmatch(subject):
                    pending_types.append((subject, value))
                elif subject.startswith(("m.", "g.")):
                    statistics["rejected_invalid_entity_ids"] += 1
            if len(pending_labels) + len(pending_types) + len(pending_term_labels) >= 50_000:
                _flush_ingest(connection, pending_labels, pending_types, pending_term_labels)
    _flush_ingest(connection, pending_labels, pending_types, pending_term_labels)
    return statistics


def _flush_ingest(
    connection: sqlite3.Connection,
    labels: list[tuple[str, str, str, str]],
    types: list[tuple[str, str]],
    term_labels: list[tuple[str, str, str, str]],
) -> None:
    canonical = sorted((entity_id, label) for entity_id, label, _, kind in labels if kind == "canonical")
    connection.executemany(
        "INSERT OR IGNORE INTO entities(id, canonical_name) VALUES(?,?)", canonical
    )
    connection.executemany(
        "INSERT OR IGNORE INTO entity_aliases(entity_id, alias, normalized_alias, alias_kind) "
        "VALUES(?,?,?,?)",
        labels,
    )
    connection.executemany(
        "INSERT OR IGNORE INTO entity_types(entity_id, type_id) VALUES(?,?)", types
    )
    connection.executemany(
        "INSERT OR IGNORE INTO term_aliases(term_id, alias, normalized_alias) VALUES(?,?,?)",
        ((term_id, alias, normalized) for term_id, alias, normalized, _ in term_labels),
    )
    connection.executemany(
        "UPDATE terms SET label=? WHERE id=?",
        (
            (label, term_id)
            for term_id, label, _, kind in term_labels
            if kind == "canonical"
        ),
    )
    connection.commit()
    labels.clear()
    types.clear()
    term_labels.clear()


def _finalize_database(connection: sqlite3.Connection) -> None:
    connection.execute(
        "DELETE FROM entity_aliases WHERE entity_id NOT IN (SELECT id FROM entities)"
    )
    connection.execute(
        "DELETE FROM entity_types WHERE entity_id NOT IN (SELECT id FROM entities)"
    )
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE entity_search USING fts5(entity_id UNINDEXED, alias, normalized_alias)"
        )
    except sqlite3.OperationalError as error:
        raise RuntimeError("SQLite FTS5 support is required for catalog v2 retrieval.") from error
    connection.execute(
        "INSERT INTO entity_search(entity_id, alias, normalized_alias) "
        "SELECT entity_id, alias, normalized_alias FROM entity_aliases ORDER BY entity_id, alias"
    )
    connection.executescript(
        """
        CREATE INDEX entity_alias_normalized_idx ON entity_aliases(normalized_alias, entity_id);
        CREATE INDEX entity_canonical_name_idx ON entities(canonical_name, id);
        CREATE INDEX entity_types_entity_idx ON entity_types(entity_id, type_id);
        CREATE INDEX entity_types_type_idx ON entity_types(type_id, entity_id);
        CREATE INDEX term_alias_term_idx ON term_aliases(term_id, normalized_alias);
        CREATE INDEX term_alias_normalized_idx ON term_aliases(normalized_alias, term_id);
        ANALYZE;
        """
    )
    connection.commit()
    connection.execute("VACUUM")


def _write_catalog_files(
    connection: sqlite3.Connection, output: Path, ontology: OntologyGraph
) -> dict[str, int]:
    _write_rows(
        output / "entities.jsonl",
        ({"id": row[0], "canonical_name": row[1]} for row in connection.execute(
            "SELECT id, canonical_name FROM entities ORDER BY id"
        )),
    )
    _write_rows(
        output / "entity_aliases.jsonl",
        (
            {"entity_id": row[0], "alias": row[1], "normalized_alias": row[2], "kind": row[3]}
            for row in connection.execute(
                "SELECT entity_id, alias, normalized_alias, alias_kind "
                "FROM entity_aliases ORDER BY entity_id, alias"
            )
        ),
    )
    _write_rows(
        output / "entity_types.jsonl",
        ({"entity_id": row[0], "type_id": row[1]} for row in connection.execute(
            "SELECT entity_id, type_id FROM entity_types ORDER BY entity_id, type_id"
        )),
    )
    reverse_map: dict[str, str] = {}
    _write_rows(
        output / "terms.jsonl",
        (
            {
                "id": row[0], "kind": row[1], "label": row[2], "domain": row[3],
                "range": row[4], "reverse_id": row[5],
            }
            for row in connection.execute(
                "SELECT id, kind, label, domain_id, range_id, reverse_id FROM terms ORDER BY id"
            )
        ),
    )
    for kind, filename in (("type", "type_aliases.jsonl"), ("relation", "relation_aliases.jsonl")):
        _write_rows(
            output / filename,
            (
                {"term_id": row[0], "alias": row[1], "normalized_alias": row[2]}
                for row in connection.execute(
                    "SELECT a.term_id, a.alias, a.normalized_alias FROM term_aliases a "
                    "JOIN terms t ON t.id=a.term_id WHERE t.kind=? ORDER BY a.term_id, a.alias",
                    (kind,),
                )
            ),
        )
    relation_rows = list(
        connection.execute(
            "SELECT id, domain_id, range_id, reverse_id FROM terms "
            "WHERE kind='relation' ORDER BY id"
        )
    )
    _write_rows(
        output / "relation_metadata.jsonl",
        (
            {"relation_id": row[0], "domain": row[1], "range": row[2], "reverse_id": row[3]}
            for row in relation_rows
        ),
    )
    reverse_map.update({str(row[0]): str(row[3]) for row in relation_rows if row[3]})
    (output / "reverse_properties.json").write_text(
        json.dumps(reverse_map, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "entities": _count(connection, "entities"),
        "canonical_names": int(
            connection.execute(
                "SELECT count(*) FROM entity_aliases WHERE alias_kind='canonical'"
            ).fetchone()[0]
        ),
        "entity_aliases": _count(connection, "entity_aliases"),
        "entity_types": _count(connection, "entity_types"),
        "types": len(ontology.classes),
        "relations": len(ontology.relations),
        "relation_aliases": int(
            connection.execute(
                "SELECT count(*) FROM term_aliases a JOIN terms t ON t.id=a.term_id "
                "WHERE t.kind='relation'"
            ).fetchone()[0]
        ),
        "reverse_property_entries": len(reverse_map),
    }


def parse_freebase_triple(
    line: str,
) -> tuple[str, str, str, str | None, bool] | None:
    match = _TRIPLE.match(line)
    if match is None:
        return None
    subject = _freebase_id(match.group("subject"))
    predicate = _freebase_id(match.group("predicate"))
    object_uri = match.group("object")
    if object_uri is not None:
        return subject, predicate, _freebase_id(object_uri), None, True
    return (
        subject,
        predicate,
        _decode_ntriples_literal(str(match.group("literal"))),
        str(match.group("lang")).casefold(),
        False,
    )


def _rank_terms(
    question: str, terms: Iterable[_Term], top_k: int
) -> tuple[CatalogV2Candidate, ...]:
    question_norm = normalized_label(question)
    question_tokens = set(question_norm.split())
    scored: list[tuple[float, str, str, _Term, tuple[str, ...]]] = []
    for term in terms:
        best = -1.0
        matched = term.label
        evidence: set[str] = {"public_metadata"}
        descriptors = tuple(
            dict.fromkeys(
                (
                    term.label,
                    *term.aliases,
                    normalized_label(term.term_id),
                    normalized_label(term.domain or ""),
                    normalized_label(term.range or ""),
                    normalized_label(term.reverse_id or ""),
                )
            )
        )
        for descriptor in descriptors:
            value = normalized_label(descriptor)
            tokens = set(value.split())
            if not tokens:
                continue
            overlap = len(question_tokens & tokens)
            score = overlap / max(1, len(tokens))
            if value and f" {value} " in f" {question_norm} ":
                score += 2.0
                evidence.add("normalized_alias")
            if score > best:
                best = score
                matched = descriptor
        scored.append((best, term.term_id, matched, term, tuple(sorted(evidence))))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(
        CatalogV2Candidate(
            candidate_id=term.term_id,
            label=term.label,
            kind=term.kind,
            score=round(score, 12),
            rank=rank,
            matched_label=matched,
            evidence=evidence,
            domain=term.domain,
            range=term.range,
            reverse_id=term.reverse_id,
        )
        for rank, (score, _, matched, term, evidence) in enumerate(scored[:top_k], start=1)
    )


def _merge_expanded_types(
    ranked: tuple[CatalogV2Candidate, ...],
    expanded: tuple[str, ...],
    terms: tuple[_Term, ...],
    top_k: int,
) -> tuple[CatalogV2Candidate, ...]:
    by_id = {term.term_id: term for term in terms if term.kind == "type"}
    merged: dict[str, CatalogV2Candidate] = {item.candidate_id: item for item in ranked}
    for term_id in expanded:
        term = by_id.get(term_id)
        if term is None:
            continue
        existing = merged.get(term_id)
        score = (existing.score if existing is not None else 0.0) + 0.5
        evidence = set(existing.evidence if existing is not None else ())
        evidence.add("relation_domain_range_expansion")
        merged[term_id] = CatalogV2Candidate(
            candidate_id=term_id,
            label=term.label,
            kind="type",
            score=round(score, 12),
            rank=0,
            matched_label=existing.matched_label if existing is not None else term.label,
            evidence=tuple(sorted(evidence)),
            domain=term.domain,
            range=term.range,
            reverse_id=term.reverse_id,
        )
    values = sorted(merged.values(), key=lambda item: (-item.score, item.candidate_id))[:top_k]
    return tuple(
        CatalogV2Candidate(**{**item.__dict__, "rank": rank})
        for rank, item in enumerate(values, start=1)
    )


def _decode_ntriples_literal(value: str) -> str:
    simple = {"t": "\t", "b": "\b", "n": "\n", "r": "\r", "f": "\f", '"': '"', "\\": "\\"}

    def replace(match: re.Match[str]) -> str:
        token = match.group(0)[1:]
        if token in simple:
            return simple[token]
        return chr(int(token[1:], 16))

    return _ESCAPE.sub(replace, value)


def _freebase_id(uri: str) -> str:
    return uri[len(FREEBASE_NAMESPACE):] if uri.startswith(FREEBASE_NAMESPACE) else uri


def _open_text(path: Path) -> TextIO:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="strict")
    return path.open("r", encoding="utf-8")


def _write_rows(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), sort_keys=True, ensure_ascii=True) + "\n")


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _aliases_by_id(path: Path) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for row in _read_jsonl(path):
        result.setdefault(str(row["term_id"]), []).append(str(row["alias"]))
    return {key: tuple(values) for key, values in result.items()}


def _database_integrity(
    connection: sqlite3.Connection, ontology: OntologyGraph
) -> dict[str, Any]:
    quick_check = tuple(str(row[0]) for row in connection.execute("PRAGMA quick_check"))
    tables = frozenset(
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        )
    )
    indexes = frozenset(
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")
    )
    required_tables = {
        "entities",
        "entity_aliases",
        "entity_types",
        "terms",
        "term_aliases",
        "entity_search",
    }
    required_indexes = {
        "entity_canonical_name_idx",
        "entity_alias_normalized_idx",
        "entity_types_entity_idx",
        "entity_types_type_idx",
        "term_alias_term_idx",
        "term_alias_normalized_idx",
    }
    relation_ids = frozenset(
        str(row[0])
        for row in connection.execute("SELECT id FROM terms WHERE kind='relation'")
    )
    type_ids = frozenset(
        str(row[0])
        for row in connection.execute("SELECT id FROM terms WHERE kind='type'")
    )
    unmatched_type_rows = tuple(
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT et.type_id FROM entity_types et LEFT JOIN terms t "
            "ON t.id=et.type_id AND t.kind='type' WHERE t.id IS NULL "
            "ORDER BY et.type_id LIMIT 20"
        )
    )
    checks = {
        "sqlite_quick_check": list(quick_check),
        "missing_tables": sorted(required_tables - tables),
        "missing_indexes": sorted(required_indexes - indexes),
        "invalid_mid_count": int(
            connection.execute(
                "SELECT count(*) FROM entities WHERE "
                "(substr(id,1,2) NOT IN ('m.','g.') OR length(id) < 3 "
                "OR substr(id,3) GLOB '*[^A-Za-z0-9_-]*')"
            ).fetchone()[0]
        ),
        "duplicate_entity_count": int(
            connection.execute(
                "SELECT count(*) FROM (SELECT id FROM entities GROUP BY id HAVING count(*) > 1)"
            ).fetchone()[0]
        ),
        "duplicate_alias_count": int(
            connection.execute(
                "SELECT count(*) FROM (SELECT entity_id, alias FROM entity_aliases "
                "GROUP BY entity_id, alias HAVING count(*) > 1)"
            ).fetchone()[0]
        ),
        "missing_canonical_name_count": int(
            connection.execute(
                "SELECT count(*) FROM entities WHERE trim(canonical_name) = ''"
            ).fetchone()[0]
        ),
        "orphan_alias_count": int(
            connection.execute(
                "SELECT count(*) FROM entity_aliases a LEFT JOIN entities e ON e.id=a.entity_id "
                "WHERE e.id IS NULL"
            ).fetchone()[0]
        ),
        "orphan_type_membership_count": int(
            connection.execute(
                "SELECT count(*) FROM entity_types et LEFT JOIN entities e ON e.id=et.entity_id "
                "WHERE e.id IS NULL"
            ).fetchone()[0]
        ),
        "unmatched_entity_type_membership_count": int(
            connection.execute(
                "SELECT count(*) FROM entity_types et LEFT JOIN terms t "
                "ON t.id=et.type_id AND t.kind='type' WHERE t.id IS NULL"
            ).fetchone()[0]
        ),
        "unmatched_entity_type_ids_sample": list(unmatched_type_rows),
        "fts_row_count": _count(connection, "entity_search"),
        "alias_row_count": _count(connection, "entity_aliases"),
        "relation_term_count": len(relation_ids),
        "type_term_count": len(type_ids),
        "relations_not_in_ontology": sorted(relation_ids - set(ontology.relations)),
        "relations_missing_from_catalog": sorted(set(ontology.relations) - relation_ids),
        "types_not_in_ontology": sorted(type_ids - set(ontology.classes)),
        "types_missing_from_catalog": sorted(set(ontology.classes) - type_ids),
        "invalid_language_rows": 0,
        "language_policy": "only @en name and alias literals are persisted",
    }
    errors: list[str] = []
    if quick_check != ("ok",):
        errors.append("SQLite quick_check did not return ok")
    for field in (
        "missing_tables",
        "missing_indexes",
        "invalid_mid_count",
        "duplicate_entity_count",
        "duplicate_alias_count",
        "missing_canonical_name_count",
        "orphan_alias_count",
        "orphan_type_membership_count",
        "relations_not_in_ontology",
        "relations_missing_from_catalog",
        "types_not_in_ontology",
        "types_missing_from_catalog",
    ):
        if checks[field]:
            errors.append(f"{field}={checks[field]}")
    if checks["fts_row_count"] != checks["alias_row_count"]:
        errors.append("FTS row count differs from entity alias row count")
    if checks["relation_term_count"] != len(ontology.relations):
        errors.append("relation terms differ from the frozen GrailQA ontology")
    if checks["type_term_count"] != len(ontology.classes):
        errors.append("type terms differ from the frozen GrailQA ontology")
    warnings = []
    if checks["unmatched_entity_type_membership_count"]:
        warnings.append(
            "Instance type memberships absent from the frozen GrailQA ontology are retained and reported."
        )
    return {"checks": checks, "errors": errors, "warnings": warnings}


def _complete_manifest(root: Path) -> Mapping[str, Any] | None:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return manifest if manifest.get("status") == "complete" else None


def _publish_catalog(staging: Path, output: Path) -> None:
    backup = output.with_name(f".{output.name}.previous")
    if backup.exists():
        shutil.rmtree(backup)
    if output.exists():
        output.replace(backup)
    try:
        staging.replace(output)
    except Exception:
        if backup.exists() and not output.exists():
            backup.replace(output)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def _load_source_metadata(
    *,
    source: Path,
    source_hash: str,
    source_url: str,
    source_manifest_path: str | Path | None,
) -> dict[str, Any]:
    if source_manifest_path is None:
        return {
            "url": source_url,
            "sha256": source_hash,
            "size_bytes": source.stat().st_size,
            "published_size": "approximately 22 GB gzip / 250 GB uncompressed",
            "retrieved_at": None,
            "http": {},
            "compressed_format": "gzip" if source.suffix == ".gz" else "plain_ntriples",
        }
    verified = verify_source_manifest(
        freebase_rdf_path=source,
        source_manifest_path=source_manifest_path,
    )
    manifest = json.loads(Path(source_manifest_path).read_text(encoding="utf-8"))
    if str(manifest.get("source_url")) != source_url:
        raise ValueError("Freebase source URL differs from the build's canonical source URL.")
    return {
        "url": source_url,
        "sha256": verified["sha256"],
        "size_bytes": verified["size_bytes"],
        "published_size": manifest.get("published_size"),
        "retrieved_at": manifest.get("retrieved_at"),
        "http": manifest.get("http", {}),
        "source_manifest_sha256": sha256_file(Path(source_manifest_path)),
        "compressed_format": manifest.get("compressed_format"),
    }


def _http_metadata(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized = key.strip().casefold()
        if normalized in {"etag", "last-modified", "content-length", "content-type"}:
            values[normalized.replace("-", "_")] = value.strip()
    values["headers_sha256"] = sha256_file(path)
    return values


def _git_commit() -> str | None:
    configured = os.environ.get("XGAP_GIT_COMMIT")
    if configured:
        return configured
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object.")
    return value


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--freebase-rdf", required=True)
    build.add_argument("--normalized-ontology", required=True)
    build.add_argument("--reverse-properties", required=True)
    build.add_argument("--output", required=True)
    build.add_argument("--source-url", default=OFFICIAL_FREEBASE_DUMP_URL)
    build.add_argument("--source-manifest")
    build.add_argument("--force", action="store_true")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--catalog", required=True)
    verify.add_argument("--output")
    source_manifest = subparsers.add_parser("source-manifest")
    source_manifest.add_argument("--freebase-rdf", required=True)
    source_manifest.add_argument("--output", required=True)
    source_manifest.add_argument("--source-url", default=OFFICIAL_FREEBASE_DUMP_URL)
    source_manifest.add_argument("--http-headers")
    verify_source = subparsers.add_parser("verify-source")
    verify_source.add_argument("--freebase-rdf", required=True)
    verify_source.add_argument("--source-manifest", required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        manifest = build_catalog_v2(
            freebase_rdf_path=args.freebase_rdf,
            normalized_ontology_path=args.normalized_ontology,
            reverse_properties_path=args.reverse_properties,
            output_root=args.output,
            source_url=args.source_url,
            source_manifest_path=args.source_manifest,
            force=args.force,
        )
        print(json.dumps(manifest["counts"], sort_keys=True))
        print(f"catalog_hash={manifest['catalog_hash']}")
        return 0
    if args.command == "source-manifest":
        result = write_source_manifest(
            freebase_rdf_path=args.freebase_rdf,
            output_path=args.output,
            source_url=args.source_url,
            http_headers_path=args.http_headers,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "verify-source":
        result = verify_source_manifest(
            freebase_rdf_path=args.freebase_rdf,
            source_manifest_path=args.source_manifest,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    result = validate_catalog_v2(args.catalog)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"catalog_hash={result['catalog_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
