"""Query-independent Freebase catalog v2 construction and retrieval.

The builder streams the official Freebase RDF dump into SQLite and emits
canonical JSONL files.  It deliberately accepts no GrailQA question or gold
artifact path.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
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
) -> dict[str, Any]:
    """Build a query-independent v2 catalog from the official Freebase dump."""

    source = Path(freebase_rdf_path)
    ontology_path = Path(normalized_ontology_path)
    reverse_path = Path(reverse_properties_path)
    output = Path(output_root)
    if not source.is_file() or not ontology_path.is_file() or not reverse_path.is_file():
        raise FileNotFoundError(
            "Freebase RDF dump, normalized ontology, and reverse-property map are required."
        )
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()
    database = output / "catalog.sqlite3"
    if database.exists():
        database.unlink()
    ontology = OntologyGraph.from_dict(load_yaml_mapping(ontology_path))
    reverse_properties = {
        str(key): str(value)
        for key, value in _mapping(
            json.loads(reverse_path.read_text(encoding="utf-8")), "reverse properties"
        ).items()
    }
    connection = sqlite3.connect(database)
    try:
        _create_database(connection)
        _seed_terms(connection, ontology, reverse_properties)
        triple_counts = _ingest_freebase(connection, source)
        _finalize_database(connection)
        counts = _write_catalog_files(connection, output, ontology)
    finally:
        connection.close()
    shutil.copyfile(ontology_path, output / "ontology.yaml")
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
    file_hashes = {name: sha256_file(output / name) for name in files}
    source_hash = sha256_file(source)
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
                "url": source_url,
                "identity": "Google Freebase RDF dump (final public dump)",
                "revision_date": "2015-08-09",
                "sha256": source_hash,
                "license": "CC-BY-2.5; see official Freebase data-dump terms",
            },
            "ontology": {
                "identity": "Frozen normalized GrailQA official ontology",
                "sha256": sha256_file(ontology_path),
                "reverse_properties_sha256": sha256_file(reverse_path),
            },
        },
        "counts": {**counts, "parsed_triples": triple_counts},
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
        },
        "file_hashes": file_hashes,
        "provenance_notes": [
            "No GrailQA question, answer, logical form, alignment, or reference plan is read.",
            "Only English type.object.name and common.topic.alias literals are indexed.",
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    GrailQAInferenceCatalogV2.load(output)
    return manifest


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


def _ingest_freebase(connection: sqlite3.Connection, source: Path) -> int:
    pending_labels: list[tuple[str, str, str, str]] = []
    pending_types: list[tuple[str, str]] = []
    pending_term_labels: list[tuple[str, str, str, str]] = []
    known_terms = {str(row[0]) for row in connection.execute("SELECT id FROM terms")}
    parsed = 0
    with _open_text(source) as handle:
        for line in handle:
            triple = parse_freebase_triple(line)
            if triple is None:
                continue
            subject, predicate, value, language, is_resource = triple
            parsed += 1
            if predicate in (NAME_PREDICATE, ALIAS_PREDICATE) and not is_resource:
                if language != "en":
                    continue
                alias_kind = "canonical" if predicate == NAME_PREDICATE else "alias"
                if subject in known_terms:
                    pending_term_labels.append(
                        (subject, value, normalized_label(value), alias_kind)
                    )
                elif subject.startswith(("m.", "g.")):
                    pending_labels.append((subject, value, normalized_label(value), alias_kind))
            elif predicate == TYPE_PREDICATE and is_resource and subject.startswith(("m.", "g.")):
                pending_types.append((subject, value))
            if len(pending_labels) + len(pending_types) + len(pending_term_labels) >= 50_000:
                _flush_ingest(connection, pending_labels, pending_types, pending_term_labels)
    _flush_ingest(connection, pending_labels, pending_types, pending_term_labels)
    return parsed


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
        CREATE INDEX entity_types_entity_idx ON entity_types(entity_id, type_id);
        CREATE INDEX term_alias_term_idx ON term_aliases(term_id, normalized_alias);
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
    verify = subparsers.add_parser("verify")
    verify.add_argument("--catalog", required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        manifest = build_catalog_v2(
            freebase_rdf_path=args.freebase_rdf,
            normalized_ontology_path=args.normalized_ontology,
            reverse_properties_path=args.reverse_properties,
            output_root=args.output,
            source_url=args.source_url,
        )
        print(json.dumps(manifest["counts"], sort_keys=True))
        print(f"catalog_hash={manifest['catalog_hash']}")
        return 0
    catalog = GrailQAInferenceCatalogV2.load(args.catalog)
    print(f"catalog_hash={catalog.catalog_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
