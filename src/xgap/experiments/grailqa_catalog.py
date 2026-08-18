"""Inference-safe public catalog and deterministic GrailQA retrieval."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import shutil
import unicodedata
from typing import Any, Iterable, Mapping, Sequence

from xgap.experiments.grailqa_audit import load_ontology_resources
from xgap.experiments.grailqa_v2 import normalize_ontology
from xgap.experiments.hashing import content_hash
from xgap.experiments.runtime_alignment import (
    PromptQuerySlot,
    PromptSchemaView,
    RetrievalLimits,
    RetrievedOntologyTerm,
)
from xgap.experiments.semantic import OntologyGraph
from xgap.infrastructure.descriptors import load_yaml_mapping


CATALOG_SCHEMA_VERSION = "m13d-grailqa-inference-catalog-v1"
RETRIEVAL_METHOD = "m13d-deterministic-lexical-v1"
ENTITY_SOURCE_ID = "KGraph/FB15k-237:FB15k_mid2name.txt"
ENTITY_SOURCE_REVISION = "c7368ccc03358758270dbf9e475222444d19926b"
ENTITY_SOURCE_LICENSE = "CC-BY-4.0"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_content_hash(root: str | Path, names: Iterable[str]) -> str:
    base = Path(root)
    return content_hash({name: sha256_file(base / name) for name in sorted(names)})


def normalize_freebase_id(value: str) -> str:
    value = value.strip()
    if value.startswith("/"):
        value = value[1:].replace("/", ".")
    return value


@lru_cache(maxsize=100_000)
def normalized_label(value: str) -> str:
    text = unicodedata.normalize("NFKC", value)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = text.replace("_", " ").replace(".", " ").replace("/", " ")
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _term_labels(term_id: str) -> tuple[str, tuple[str, ...]]:
    parts = term_id.split(".")
    label = normalized_label(parts[-1])
    full = normalized_label(term_id)
    aliases = tuple(item for item in dict.fromkeys((label, full)) if item)
    return label or term_id, aliases


@dataclass(frozen=True)
class CatalogEntry:
    entry_id: str
    label: str
    aliases: tuple[str, ...]
    kind: str
    domain: str | None = None
    range: str | None = None
    reverse_id: str | None = None
    provenance: str = ""

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CatalogEntry":
        return cls(
            entry_id=str(value["id"]),
            label=str(value["label"]),
            aliases=tuple(str(item) for item in value.get("aliases", ())),
            kind=str(value["kind"]),
            domain=str(value["domain"]) if value.get("domain") is not None else None,
            range=str(value["range"]) if value.get("range") is not None else None,
            reverse_id=(
                str(value["reverse_id"]) if value.get("reverse_id") is not None else None
            ),
            provenance=str(value.get("provenance", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.entry_id,
            "label": self.label,
            "aliases": list(self.aliases),
            "kind": self.kind,
            "domain": self.domain,
            "range": self.range,
            "reverse_id": self.reverse_id,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class RetrievalCandidate:
    candidate_id: str
    label: str
    kind: str
    score: float
    rank: int
    matched_label: str
    domain: str | None = None
    range: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.candidate_id,
            "label": self.label,
            "kind": self.kind,
            "score": self.score,
            "rank": self.rank,
            "matched_label": self.matched_label,
            "domain": self.domain,
            "range": self.range,
        }


@dataclass(frozen=True)
class RetrievalResult:
    question_id: str
    question: str
    question_hash: str
    catalog_hash: str
    config: Mapping[str, Any]
    entities: tuple[RetrievalCandidate, ...]
    relations: tuple[RetrievalCandidate, ...]
    types: tuple[RetrievalCandidate, ...]
    properties: tuple[RetrievalCandidate, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "m13d-grailqa-retrieval-v1",
            "question_id": self.question_id,
            "question_hash": self.question_hash,
            "catalog_hash": self.catalog_hash,
            "config": dict(self.config),
            "entity_candidates": [item.to_dict() for item in self.entities],
            "relation_candidates": [item.to_dict() for item in self.relations],
            "type_candidates": [item.to_dict() for item in self.types],
            "property_candidates": [item.to_dict() for item in self.properties],
        }


@dataclass(frozen=True)
class GrailQAInferenceCatalog:
    root: Path
    manifest: Mapping[str, Any]
    ontology: OntologyGraph
    entities: tuple[CatalogEntry, ...]
    relations: tuple[CatalogEntry, ...]
    types: tuple[CatalogEntry, ...]
    properties: tuple[CatalogEntry, ...]

    @classmethod
    def load(cls, root: str | Path) -> "GrailQAInferenceCatalog":
        catalog_root = Path(root)
        manifest = json.loads((catalog_root / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("schema_version") != CATALOG_SCHEMA_VERSION:
            raise ValueError("Unsupported GrailQA inference catalog schema.")
        for name, expected in manifest["file_hashes"].items():
            actual = sha256_file(catalog_root / name)
            if actual != expected:
                raise ValueError(f"Inference catalog hash mismatch for {name}.")
        ontology = OntologyGraph.from_dict(load_yaml_mapping(catalog_root / "ontology.yaml"))
        if ontology.ontology_hash != manifest["ontology_hash"]:
            raise ValueError("Inference catalog ontology hash mismatch.")
        entries = {
            kind: tuple(
                CatalogEntry.from_dict(item)
                for item in _read_jsonl(catalog_root / filename)
            )
            for kind, filename in {
                "entities": "entities.jsonl",
                "relations": "relations.jsonl",
                "types": "types.jsonl",
                "properties": "properties.jsonl",
            }.items()
        }
        instance = cls(
            root=catalog_root,
            manifest=manifest,
            ontology=ontology,
            entities=entries["entities"],
            relations=entries["relations"],
            types=entries["types"],
            properties=entries["properties"],
        )
        if instance.recomputed_catalog_hash != manifest["catalog_hash"]:
            raise ValueError("Inference catalog content hash mismatch.")
        return instance

    @property
    def catalog_hash(self) -> str:
        return str(self.manifest["catalog_hash"])

    @property
    def recomputed_catalog_hash(self) -> str:
        return content_hash(
            {
                "schema_version": CATALOG_SCHEMA_VERSION,
                "source": self.manifest["sources"],
                "ontology_hash": self.ontology.ontology_hash,
                "entities": [item.to_dict() for item in self.entities],
                "relations": [item.to_dict() for item in self.relations],
                "types": [item.to_dict() for item in self.types],
                "properties": [item.to_dict() for item in self.properties],
            }
        )

    def retrieve(self, question_id: str, question: str, *, top_k: int = 20) -> RetrievalResult:
        if top_k <= 0:
            raise ValueError("Retrieval top_k must be positive.")
        config = {
            "method": RETRIEVAL_METHOD,
            "top_k": top_k,
            "tie_break": "score_descending_then_id",
            "llm_used": False,
            "input_fields": ["question"],
        }
        return RetrievalResult(
            question_id=question_id,
            question=question,
            question_hash=hashlib.sha256(question.encode("utf-8")).hexdigest(),
            catalog_hash=self.catalog_hash,
            config=config,
            entities=_rank(question, self.entities, top_k),
            relations=_rank(question, self.relations, top_k),
            types=_rank(question, self.types, top_k),
            properties=_rank(question, self.properties, top_k),
        )

    def prompt_view(
        self,
        result: RetrievalResult,
        *,
        candidates_per_slot: int = 4,
        max_entities: int = 4,
    ) -> PromptSchemaView:
        type_candidates = result.types[:candidates_per_slot]
        relation_candidates = result.relations[:candidates_per_slot]
        if not type_candidates or not relation_candidates:
            raise ValueError("GrailQA prompt context requires type and relation retrieval candidates.")
        selected = (*type_candidates, *relation_candidates)
        terms = tuple(
            RetrievedOntologyTerm(
                term_id=item.candidate_id,
                kind="class" if item.kind == "type" else item.kind,
                label=item.label,
                aliases=(item.matched_label,),
                retrieval_score=item.score,
                retrieval_provenance=(RETRIEVAL_METHOD, f"rank:{item.rank}"),
                domain=item.domain,
                range=item.range,
            )
            for item in selected
        )
        slots = (
            PromptQuerySlot(
                slot_id="retrieved-type",
                mention=result.question,
                kind="class",
                candidate_anchor_ids=tuple(item.candidate_id for item in type_candidates),
                retrieval_provenance=(RETRIEVAL_METHOD, "question_text_only"),
            ),
            PromptQuerySlot(
                slot_id="retrieved-relation",
                mention=result.question,
                kind="relation",
                candidate_anchor_ids=tuple(item.candidate_id for item in relation_candidates),
                retrieval_provenance=(RETRIEVAL_METHOD, "question_text_only"),
            ),
        )
        entities = tuple(
            {
                "entity_id": item.candidate_id,
                "canonical_label": item.label,
                "aliases": [item.matched_label],
                "retrieval_score": item.score,
                "retrieval_rank": item.rank,
            }
            for item in result.entities[:max_entities]
        )
        limits = RetrievalLimits(
            max_slots=2,
            max_candidates_per_slot=candidates_per_slot,
            max_entities=max_entities,
            max_schema_items=len(terms),
        )
        return PromptSchemaView(
            task_id=result.question_id,
            ontology_id=self.ontology.ontology_id,
            ontology_version=self.ontology.version,
            ontology_hash=self.ontology.ontology_hash,
            schema_snapshot_version=CATALOG_SCHEMA_VERSION,
            schema_snapshot_hash=self.catalog_hash,
            terms=terms,
            entities=entities,
            query_slots=slots,
            backend_hints={},
            source_schema_items=tuple(item.candidate_id for item in selected),
            limits=limits,
            retrieval_method=RETRIEVAL_METHOD,
        )


def _rank(
    question: str,
    entries: Sequence[CatalogEntry],
    top_k: int,
) -> tuple[RetrievalCandidate, ...]:
    question_norm = normalized_label(question)
    question_tokens = set(question_norm.split())
    scored: list[tuple[float, str, str, CatalogEntry]] = []
    for entry in entries:
        best_score = -1.0
        best_label = entry.label
        for alias in dict.fromkeys((entry.label, *entry.aliases)):
            alias_norm = normalized_label(alias)
            alias_tokens = set(alias_norm.split())
            overlap = len(question_tokens & alias_tokens)
            score = overlap / max(1, len(question_tokens | alias_tokens))
            if alias_norm and f" {alias_norm} " in f" {question_norm} ":
                score += 2.0 + min(len(alias_tokens), 10) / 100.0
            if score > best_score or (score == best_score and alias_norm < normalized_label(best_label)):
                best_score = score
                best_label = alias
        scored.append((round(best_score, 12), entry.entry_id, best_label, entry))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(
        RetrievalCandidate(
            candidate_id=entry.entry_id,
            label=entry.label,
            kind=entry.kind,
            score=score,
            rank=rank,
            matched_label=matched,
            domain=entry.domain,
            range=entry.range,
        )
        for rank, (score, _, matched, entry) in enumerate(scored[:top_k], start=1)
    )


def build_inference_catalog(
    *,
    entity_names_path: str | Path,
    ontology_root: str | Path,
    output_root: str | Path,
    normalized_ontology_path: str | Path,
) -> dict[str, Any]:
    """Build the frozen catalog from public query-independent sources."""

    entity_source = Path(entity_names_path)
    ontology_source = Path(ontology_root)
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    ontology_resources = load_ontology_resources(ontology_source)
    normalized = normalize_ontology(ontology_resources)
    frozen_graph = OntologyGraph.from_dict(load_yaml_mapping(normalized_ontology_path))
    if normalized.graph.ontology_hash != frozen_graph.ontology_hash:
        raise ValueError("Provided normalized ontology does not match reproducible normalization.")

    entity_by_id: dict[str, CatalogEntry] = {}
    for line in entity_source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw_id, raw_label = line.split("\t", 1)
        entity_id = normalize_freebase_id(raw_id)
        label = raw_label.strip()
        alias = normalized_label(label)
        entity_by_id[entity_id] = CatalogEntry(
            entry_id=entity_id,
            label=label,
            aliases=(alias,) if alias and alias != label else (),
            kind="entity",
            provenance=ENTITY_SOURCE_ID,
        )

    def ontology_entries(kind: str, terms: Sequence[str]) -> tuple[CatalogEntry, ...]:
        result: list[CatalogEntry] = []
        for term in terms:
            label, aliases = _term_labels(term)
            domain_range = frozen_graph.domain_range.get(term, {})
            result.append(
                CatalogEntry(
                    entry_id=term,
                    label=label,
                    aliases=aliases,
                    kind=kind,
                    domain=domain_range.get("domain"),
                    range=domain_range.get("range"),
                    reverse_id=ontology_resources.reverse_relations.get(term),
                    provenance="GrailQA official processed Freebase ontology",
                )
            )
        return tuple(result)

    entities = tuple(entity_by_id[key] for key in sorted(entity_by_id))
    types = ontology_entries("type", frozen_graph.classes)
    relations = ontology_entries("relation", frozen_graph.relations)
    properties = ontology_entries("property", frozen_graph.properties)
    records = {
        "entities.jsonl": entities,
        "types.jsonl": types,
        "relations.jsonl": relations,
        "properties.jsonl": properties,
    }
    for name, values in records.items():
        _write_jsonl(output / name, (item.to_dict() for item in values))
    shutil.copyfile(normalized_ontology_path, output / "ontology.yaml")
    reverse_payload = {
        key: value for key, value in sorted(ontology_resources.reverse_relations.items())
    }
    (output / "reverse_properties.json").write_text(
        json.dumps(reverse_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    source_payload = {
        "entities": {
            "source": ENTITY_SOURCE_ID,
            "revision": ENTITY_SOURCE_REVISION,
            "sha256": sha256_file(entity_source),
            "license": ENTITY_SOURCE_LICENSE,
            "url": "https://huggingface.co/datasets/KGraph/FB15k-237",
            "scope_note": "Public FB15k-237 entity-name subset; not complete Freebase.",
        },
        "ontology": {
            "source": "dki-lab/GrailQA official processed Freebase ontology",
            "revision": "bc15dfec5595427614359745d47bc28661e37115",
            "source_hashes": dict(sorted(ontology_resources.source_hashes.items())),
            "license_note": "GrailQA repository/data terms apply; provenance retained.",
            "url": "https://github.com/dki-lab/GrailQA",
        },
    }
    catalog_hash = content_hash(
        {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "source": source_payload,
            "ontology_hash": frozen_graph.ontology_hash,
            "entities": [item.to_dict() for item in entities],
            "relations": [item.to_dict() for item in relations],
            "types": [item.to_dict() for item in types],
            "properties": [item.to_dict() for item in properties],
        }
    )
    file_names = (*records, "ontology.yaml", "reverse_properties.json")
    manifest = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "catalog_id": "grailqa_inference_catalog_v1",
        "catalog_hash": catalog_hash,
        "ontology_hash": frozen_graph.ontology_hash,
        "sources": source_payload,
        "counts": {
            "entities": len(entities),
            "types": len(types),
            "relations": len(relations),
            "properties": len(properties),
            "reverse_property_entries": len(reverse_payload),
        },
        "construction": {
            "command": (
                "PYTHONPATH=src python -m xgap.experiments.grailqa_catalog build "
                "--entity-names <FB15k_mid2name.txt> --ontology-root <GrailQA/ontology> "
                "--normalized-ontology datasets/grailqa_pilot_v1/ontology.yaml "
                "--output datasets/grailqa_inference_catalog_v1"
            ),
            "query_dependent_inputs": False,
            "gold_inputs": False,
            "normalization": "NFKC casefold; punctuation/dot/underscore token boundaries",
        },
        "file_hashes": {name: sha256_file(output / name) for name in sorted(file_names)},
        "provenance_notes": [
            "Entity coverage is intentionally limited to the public FB15k-237 MID-name subset.",
            "No GrailQA question, logical form, answer, or per-question annotation was used.",
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    GrailQAInferenceCatalog.load(output)
    return manifest


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(dict(item), sort_keys=True, ensure_ascii=True) + "\n" for item in values),
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--entity-names", required=True)
    build.add_argument("--ontology-root", required=True)
    build.add_argument("--normalized-ontology", required=True)
    build.add_argument("--output", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--catalog", required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        manifest = build_inference_catalog(
            entity_names_path=args.entity_names,
            ontology_root=args.ontology_root,
            normalized_ontology_path=args.normalized_ontology,
            output_root=args.output,
        )
        print(json.dumps(manifest["counts"], sort_keys=True))
        print(f"catalog_hash={manifest['catalog_hash']}")
        return 0
    catalog = GrailQAInferenceCatalog.load(args.catalog)
    print(f"catalog_hash={catalog.catalog_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
