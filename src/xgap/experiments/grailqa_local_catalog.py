"""Gold-blind query-conditioned Freebase Catalog-v2 construction and audit."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePath
import re
import resource
import shutil
import sqlite3
import sys
import tempfile
import time
from typing import Any, Iterable, Iterator, Mapping, Sequence

from xgap.experiments.freebase_sources import (
    ALIAS_PREDICATE,
    HF_FREEBASE_REPO_ID,
    HF_FREEBASE_REVISION,
    NAME_PREDICATE,
    TYPE_PREDICATE,
    ParquetTripleRecord,
    iter_parquet_triple_records,
    load_parquet_source_manifest,
    verify_parquet_source_manifest,
)
from xgap.experiments.grailqa_catalog import normalized_label, sha256_file
from xgap.experiments.grailqa_catalog_v2 import (
    CATALOG_V2_SCHEMA_VERSION,
    GrailQAInferenceCatalogV2,
    _create_database,
    _database_integrity,
    _finalize_database,
    _flush_ingest,
    _git_commit,
    _seed_terms,
    _write_catalog_files,
    validate_catalog_v2,
)
from xgap.experiments.grailqa_local_diagnostics import (
    ENDPOINT_GROUNDING_COMPARISON_SCHEMA_VERSION,
    LOCAL_CONTRACT_COMPARISON_SCHEMA_VERSION,
    SCHEMA_RANKING_COMPARISON_SCHEMA_VERSION,
    diagnostic_stage_counts,
    diagnostic_rows_v2,
    endpoint_grounding_diagnostics,
    endpoint_grounding_metrics,
    entity_contract_metrics,
    previous_entity_contract_metrics,
    previous_endpoint_grounding_metrics,
    previous_schema_ranking_metrics,
    relation_type_diagnostics,
    schema_ranking_audits,
    schema_ranking_metrics,
)
from xgap.experiments.grailqa_reachability import (
    audit_reachability,
    load_catalog_universe,
    prompt_reachability_gate,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.relation_endpoints import RELATION_ENDPOINT_CONTRACT_VERSION
from xgap.experiments.schema_ranking import ranking_contract
from xgap.experiments.semantic import OntologyGraph
from xgap.infrastructure.descriptors import load_yaml_mapping


LOCAL_CATALOG_SCHEMA_VERSION = "m13e3b-grailqa-local-catalog-v1"
LOCAL_ELIGIBLE_CATALOG_SCHEMA_VERSION = "m13e3b-grailqa-local-catalog-v2"
LEGACY_CANDIDATE_SELECTION = "legacy_topk_v1"
ELIGIBLE_CANDIDATE_SELECTION = "canonical_eligible_topk_v2"
LOCAL_AUDIT_SCHEMA_VERSION = "m13e3b4-grailqa-local-reachability-v2"
ANCHOR_EXTRACTION_VERSION = "m13e3b-contiguous-normalized-spans-v1"
NORMALIZATION_VERSION = "catalog-v2-normalized-label-v1"
DEFAULT_CONFIG = "experiments/specs/grailqa_local_catalog_v1.json"
DEFAULT_K_VALUES = (1, 5, 10, 20)
_MID = re.compile(r"^[mg]\.[A-Za-z0-9_-]+$")
_QUESTION_FIELDS = frozenset(
    {"question_id", "text", "schema_version", "source_benchmark_id", "split"}
)
_FORBIDDEN_INPUT_FIELDS = frozenset(
    {
        "answer",
        "answers",
        "gold",
        "logical_form",
        "pattern_query",
        "reference",
        "reference_interpretation",
        "s_expression",
    }
)
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "did",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whose",
        "why",
        "with",
    }
)


@dataclass(frozen=True)
class InferenceQuestion:
    question_id: str
    text: str

    @property
    def question_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LocalCandidateMatch:
    question_id: str
    entity_id: str
    matched_label: str
    normalized_label: str
    match_type: str
    score: float
    source_shard: str
    rank: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "entity_id": self.entity_id,
            "matched_label": self.matched_label,
            "normalized_label": self.normalized_label,
            "match_type": self.match_type,
            "lexical_score": self.score,
            "source_shard": str(self.source_shard),
            "rank": self.rank,
        }


def extract_query_anchors(
    question: str,
    *,
    min_tokens: int = 1,
    max_tokens: int = 8,
    omit_stopword_only: bool = True,
) -> tuple[str, ...]:
    """Return frozen contiguous normalized spans without semantic supervision."""

    if min_tokens < 1 or max_tokens < min_tokens:
        raise ValueError("Anchor token bounds must satisfy 1 <= min_tokens <= max_tokens.")
    tokens = tuple(normalized_label(question).split())
    anchors: set[str] = set()
    for size in range(min_tokens, min(max_tokens, len(tokens)) + 1):
        for start in range(0, len(tokens) - size + 1):
            span = tokens[start : start + size]
            if omit_stopword_only and all(token in _STOPWORDS for token in span):
                continue
            if size == 1 and len(span[0]) < 2:
                continue
            anchors.add(" ".join(span))
    return tuple(sorted(anchors, key=lambda item: (-len(item.split()), item)))


def select_query_candidates(
    questions: Sequence[InferenceQuestion],
    records: Iterable[ParquetTripleRecord],
    *,
    max_candidates_per_query: int = 50,
    anchor_min_tokens: int = 1,
    anchor_max_tokens: int = 8,
    omit_stopword_only: bool = True,
) -> dict[str, tuple[LocalCandidateMatch, ...]]:
    """Select bounded candidate MIDs independently for every question."""

    if max_candidates_per_query < 1:
        raise ValueError("max_candidates_per_query must be positive.")
    question_by_id = {item.question_id: item for item in questions}
    if len(question_by_id) != len(questions):
        raise ValueError("Inference question IDs must be unique.")
    anchors_by_question = {
        item.question_id: extract_query_anchors(
            item.text,
            min_tokens=anchor_min_tokens,
            max_tokens=anchor_max_tokens,
            omit_stopword_only=omit_stopword_only,
        )
        for item in questions
    }
    questions_by_anchor: dict[str, list[str]] = {}
    for question_id, anchors in anchors_by_question.items():
        for anchor in anchors:
            questions_by_anchor.setdefault(anchor, []).append(question_id)
    selected: dict[str, dict[str, LocalCandidateMatch]] = {
        item.question_id: {} for item in questions
    }
    for record in records:
        subject, predicate, value, language, is_resource = record.triple
        if (
            predicate not in (NAME_PREDICATE, ALIAS_PREDICATE)
            or is_resource
            or language != "en"
            or _MID.fullmatch(subject) is None
        ):
            continue
        candidate_label = normalized_label(value)
        if not candidate_label:
            continue
        for question_id in questions_by_anchor.get(candidate_label, ()):
            question = question_by_id[question_id]
            candidate = LocalCandidateMatch(
                question_id=question_id,
                entity_id=subject,
                matched_label=value,
                normalized_label=candidate_label,
                match_type=(
                    "exact_normalized_name"
                    if predicate == NAME_PREDICATE
                    else "exact_normalized_alias"
                ),
                score=_existing_lexical_score(question.text, candidate_label),
                source_shard=record.source_shard,
            )
            previous = selected[question_id].get(subject)
            if previous is None or _candidate_key(candidate) < _candidate_key(previous):
                selected[question_id][subject] = candidate
            if len(selected[question_id]) > max_candidates_per_query * 2:
                selected[question_id] = {
                    item.entity_id: item
                    for item in _rank_candidates(
                        selected[question_id].values(), max_candidates_per_query
                    )
                }
    return {
        question_id: _rank_candidates(values.values(), max_candidates_per_query)
        for question_id, values in selected.items()
    }


def build_local_catalog(
    *,
    inference_questions_path: str | Path,
    question_ids: Sequence[str],
    workload_name: str,
    artifact_id: str,
    freebase_parquet_root: str | Path,
    source_manifest_path: str | Path,
    normalized_ontology_path: str | Path,
    reverse_properties_path: str | Path,
    output_root: str | Path,
    staging_root: str | Path | None = None,
    max_candidates_per_query: int = 50,
    anchor_min_tokens: int = 1,
    anchor_max_tokens: int = 8,
    omit_stopword_only: bool = True,
    force: bool = False,
    candidate_selection: str = LEGACY_CANDIDATE_SELECTION,
) -> dict[str, Any]:
    """Build one question-only local catalog; no evaluation artifact is accepted."""

    started = time.monotonic()
    if candidate_selection not in {
        LEGACY_CANDIDATE_SELECTION, ELIGIBLE_CANDIDATE_SELECTION
    }:
        raise ValueError("Unsupported local candidate selection policy.")
    eligibility_first = candidate_selection == ELIGIBLE_CANDIDATE_SELECTION
    requested_output = Path(output_root).absolute()
    if eligibility_first:
        # This version is a new construction, never an in-place evidence repair.
        if force:
            raise ValueError("Eligibility-first construction does not permit force.")
        if requested_output.exists() or requested_output.is_symlink():
            raise FileExistsError("Eligibility-first construction requires a fresh output.")
        if any(part.is_symlink() for part in requested_output.parents):
            raise ValueError("Eligibility-first output ancestors must not be symlinks.")
    output = Path(output_root).resolve()
    parquet_root = Path(freebase_parquet_root).resolve()
    source_manifest_file = Path(source_manifest_path).resolve()
    ontology_path = Path(normalized_ontology_path).resolve()
    reverse_path = Path(reverse_properties_path).resolve()
    _guard_output_path(output, parquet_root)
    if not 1 <= max_candidates_per_query <= 900:
        raise ValueError("max_candidates_per_query must be within [1, 900].")
    questions = load_inference_questions(inference_questions_path, question_ids=question_ids)
    if eligibility_first:
        from xgap.experiments.grailqa_eligible_candidates import _validate_questions_and_bounds

        _validate_questions_and_bounds(
            questions, max_candidates_per_query=max_candidates_per_query,
            anchor_min_tokens=anchor_min_tokens, anchor_max_tokens=anchor_max_tokens,
            omit_stopword_only=omit_stopword_only,
        )
    question_set_hash = content_hash([item.question_id for item in questions])
    question_text_hash = content_hash(
        [{"question_id": item.question_id, "text": item.text} for item in questions]
    )
    source_verification = verify_parquet_source_manifest(
        parquet_root=parquet_root,
        source_manifest_path=source_manifest_file,
    )
    source_manifest = load_parquet_source_manifest(source_manifest_file)
    if (
        int(source_verification["shard_count"]) != 964
        or int(source_verification["total_bytes"]) != 32_476_432_840
    ):
        raise ValueError("Verified source differs from the frozen M13-E3A inventory.")
    if not ontology_path.is_file() or not reverse_path.is_file():
        raise FileNotFoundError("Frozen ontology and reverse-property artifacts are required.")
    source_manifest_hash = sha256_file(source_manifest_file)
    anchor_contract = {
        "version": ANCHOR_EXTRACTION_VERSION,
        "normalization_version": NORMALIZATION_VERSION,
        "min_tokens": anchor_min_tokens,
        "max_tokens": anchor_max_tokens,
        "omit_stopword_only": omit_stopword_only,
        "max_candidates_per_query": max_candidates_per_query,
        "matching": ["exact_normalized_name", "exact_normalized_alias"],
    }
    existing = _load_complete_manifest(output)
    if existing is not None and not force:
        existing_source = _mapping(
            _mapping(existing.get("sources"), "sources").get(
                "freebase_archival_parquet"
            ),
            "freebase_archival_parquet",
        )
        existing_ontology = _mapping(
            _mapping(existing.get("sources"), "sources").get("ontology"),
            "ontology",
        )
        if (
            existing.get("local_catalog_schema_version") == LOCAL_CATALOG_SCHEMA_VERSION
            and existing.get("catalog_id") == artifact_id
            and existing.get("question_set_sha256") == question_set_hash
            and existing.get("question_text_sha256") == question_text_hash
            and existing.get("workload_name") == workload_name
            and existing.get("anchor_extraction") == anchor_contract
            and existing_source.get("source_manifest_sha256") == source_manifest_hash
            and existing_ontology.get("sha256") == sha256_file(ontology_path)
            and existing_ontology.get("reverse_properties_sha256")
            == sha256_file(reverse_path)
        ):
            validate_local_catalog(output)
            return existing
        raise FileExistsError(
            f"A different complete local catalog exists at {output}; pass force=True."
        )

    anchors_by_question = {
        item.question_id: extract_query_anchors(
            item.text,
            min_tokens=anchor_min_tokens,
            max_tokens=anchor_max_tokens,
            omit_stopword_only=omit_stopword_only,
        )
        for item in questions
    }
    pass1_statistics: dict[str, int] = {}
    pass1 = iter_parquet_triple_records(
        parquet_root=parquet_root,
        source_manifest_path=source_manifest_file,
        statistics=pass1_statistics,
        predicates=(NAME_PREDICATE, ALIAS_PREDICATE),
    )
    selection_options = {
        "max_candidates_per_query": max_candidates_per_query,
        "anchor_min_tokens": anchor_min_tokens,
        "anchor_max_tokens": anchor_max_tokens,
        "omit_stopword_only": omit_stopword_only,
    }
    selection_diagnostics = None
    selection_resources = None
    if eligibility_first:
        from xgap.experiments.grailqa_eligible_candidates import (
            select_eligible_query_candidates,
        )

        selector_staging = Path(
            staging_root or os.environ.get("TMPDIR") or tempfile.gettempdir()
        ).resolve()
        selector_staging.mkdir(parents=True, exist_ok=True)
        selection = select_eligible_query_candidates(
            questions, pass1, staging_root=selector_staging, **selection_options
        )
        candidates = selection.candidates
        selection_diagnostics = dict(selection.diagnostics)
        selection_resources = selection_diagnostics.pop("resource_usage")
    else:
        candidates = select_query_candidates(questions, pass1, **selection_options)
    candidate_ids = tuple(
        sorted({item.entity_id for values in candidates.values() for item in values})
    )
    pass2_statistics: dict[str, int] = {}
    metadata = _collect_candidate_metadata(
        iter_parquet_triple_records(
            parquet_root=parquet_root,
            source_manifest_path=source_manifest_file,
            statistics=pass2_statistics,
            predicates=(NAME_PREDICATE, ALIAS_PREDICATE, TYPE_PREDICATE),
            subject_ids=candidate_ids,
        ),
        allowed_entity_ids=candidate_ids,
        require_materializable_canonical=eligibility_first,
    )
    if eligibility_first:
        missing = set(candidate_ids) - set(metadata.canonical_names)
        if missing:
            raise ValueError(
                "Selected canonical eligibility changed during metadata enrichment: "
                + ", ".join(sorted(missing)[:5])
            )
    else:
        candidates = _drop_entities_without_canonical_names(candidates, metadata)

    scratch_parent = Path(
        staging_root or os.environ.get("TMPDIR") or tempfile.gettempdir()
    ).resolve()
    scratch_parent.mkdir(parents=True, exist_ok=True)
    if eligibility_first:
        scratch = Path(tempfile.mkdtemp(prefix="xgap-eligible-catalog-", dir=scratch_parent))
    else:
        scratch = scratch_parent / f"xgap-{artifact_id}-{os.getpid()}"
        if scratch.exists():
            raise FileExistsError(f"Local staging path already exists: {scratch}")
        scratch.mkdir()
    try:
        counts, integrity = _materialize_subset(
            output=scratch,
            questions=questions,
            candidates=candidates,
            metadata=metadata,
            ontology_path=ontology_path,
            reverse_path=reverse_path,
        )
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
            "local_queries.jsonl",
            "query_entity_candidates.jsonl",
        )
        if selection_diagnostics is not None:
            _write_json(scratch / "selection_diagnostics.json", selection_diagnostics)
            files += ("selection_diagnostics.json",)
        file_hashes = {name: sha256_file(scratch / name) for name in files}
        local_schema = (
            LOCAL_ELIGIBLE_CATALOG_SCHEMA_VERSION
            if eligibility_first else LOCAL_CATALOG_SCHEMA_VERSION
        )
        catalog_hash = content_hash(
            {
                "schema_version": local_schema,
                "source_manifest_sha256": source_manifest_hash,
                "question_text_sha256": question_text_hash,
                **({"candidate_selection": candidate_selection,
                    "anchor_extraction": anchor_contract} if eligibility_first else {}),
                "content_file_hashes": {
                    key: value
                    for key, value in file_hashes.items()
                    if key != "catalog.sqlite3"
                },
            }
        )
        pass_count = 1 + int(bool(candidate_ids))
        wall_seconds = time.monotonic() - started
        manifest = {
            "schema_version": CATALOG_V2_SCHEMA_VERSION,
            "local_catalog_schema_version": local_schema,
            "catalog_id": artifact_id,
            "status": "complete",
            "catalog_hash": catalog_hash,
            "ontology_hash": OntologyGraph.from_dict(
                load_yaml_mapping(ontology_path)
            ).ontology_hash,
            "requires_query_entity_filter": True,
            "gold_used_for_construction": False,
            "workload_name": workload_name,
            "question_ids": [item.question_id for item in questions],
            "question_set_sha256": question_set_hash,
            "question_text_sha256": question_text_hash,
            "sources": {
                "freebase_archival_parquet": {
                    "repo_id": HF_FREEBASE_REPO_ID,
                    "revision": HF_FREEBASE_REVISION,
                    "resolved_parquet_revision": source_manifest[
                        "resolved_parquet_revision"
                    ],
                    "source_manifest_sha256": source_manifest_hash,
                    "shard_count": source_verification["shard_count"],
                    "size_bytes": source_verification["total_bytes"],
                    "source_mode": "hf_archival_parquet",
                },
                "ontology": {
                    "identity": "Frozen normalized GrailQA official ontology",
                    "sha256": sha256_file(ontology_path),
                    "reverse_properties_sha256": sha256_file(reverse_path),
                },
                "inference_questions": {
                    "sha256": sha256_file(Path(inference_questions_path)),
                    "question_only": True,
                },
            },
            "anchor_extraction": anchor_contract,
            "counts": {
                **counts,
                "questions": len(questions),
                "query_anchors": sum(len(values) for values in anchors_by_question.values()),
                "unique_candidate_mids": len(metadata.canonical_names),
                "query_candidate_assignments": sum(
                    len(values) for values in candidates.values()
                ),
            },
            "scan": {
                "passes": pass_count,
                "pass_1_predicates": [NAME_PREDICATE, ALIAS_PREDICATE],
                "pass_2_predicates": [
                    NAME_PREDICATE,
                    ALIAS_PREDICATE,
                    TYPE_PREDICATE,
                ],
                "projected_columns": [
                    "subject",
                    "predicate",
                    "object",
                    "object_type",
                    "object_language",
                ],
                "pass_1_statistics": pass1_statistics,
                "pass_2_statistics": pass2_statistics,
                "source_size_bytes": source_verification["total_bytes"],
                "source_verification_bytes_read": source_verification["total_bytes"],
                "source_bytes_scanned": source_verification["total_bytes"]
                * pass_count,
                "source_bytes_scanned_definition": (
                    "frozen source inventory bytes multiplied by Parquet pass count; "
                    "column projection may reduce physical I/O"
                ),
                "nominal_source_bytes_scanned": source_verification["total_bytes"]
                * pass_count,
                "nominal_total_source_bytes_read": source_verification["total_bytes"]
                * (pass_count + 1),
            },
            "construction": {
                "constructed_at": _utc_now(),
                "builder_git_commit": _git_commit(),
                "wall_clock_seconds": round(wall_seconds, 6),
                "peak_rss_bytes": _peak_rss_bytes(),
                "staging_policy": "node-local build then output-adjacent atomic publication",
                "batching_semantics": "per-query independent candidate maps",
            },
            "database_size_bytes": (scratch / "catalog.sqlite3").stat().st_size,
            "integrity": integrity,
            "file_hashes": file_hashes,
            "provenance_notes": [
                "Construction accepts only inference question IDs and text.",
                "No gold entity ID, logical form, answer, or reference interpretation is read.",
                "Batched source scans update independent per-question candidate universes.",
                "Only English Freebase names and aliases are eligible lexical evidence.",
                "No factual edges or k-hop backend snapshot are retained.",
            ],
        }
        if eligibility_first:
            manifest["candidate_selection"] = candidate_selection
            manifest["paper_result"] = False
            manifest["construction"]["selection_resource_usage"] = selection_resources
            manifest["construction"]["staging_policy"] = (
                "node-local build; exclusive output claim; manifest-last publication"
            )
            manifest["provenance_notes"].append(
                "English canonical-name eligibility precedes Top-K in a disk-backed scan; "
                "this new catalog is not admitted by historical preflight/paper audits."
            )
        (scratch / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        validate_local_catalog(scratch)
        if eligibility_first:
            from xgap.experiments.grailqa_eligible_catalog_validation import publish_fresh_catalog

            publish_fresh_catalog(scratch, output, validate_local_catalog)
        else:
            _publish_catalog(scratch, output, force=force)
        validate_local_catalog(output)
        return manifest
    finally:
        if scratch.exists():
            shutil.rmtree(scratch)


@dataclass(frozen=True)
class _CandidateMetadata:
    canonical_names: Mapping[str, str]
    aliases: Mapping[str, tuple[tuple[str, str], ...]]
    types: Mapping[str, tuple[str, ...]]


def load_inference_questions(
    path: str | Path, *, question_ids: Sequence[str]
) -> tuple[InferenceQuestion, ...]:
    """Load only the frozen inference-side ID/text contract."""

    records: dict[str, InferenceQuestion] = {}
    for item in _read_jsonl(Path(path)):
        forbidden = _FORBIDDEN_INPUT_FIELDS & set(item)
        unexpected = set(item) - _QUESTION_FIELDS
        if forbidden or unexpected:
            fields = sorted(forbidden | unexpected)
            raise ValueError(
                "Inference question input contains non-inference fields: "
                + ", ".join(fields)
            )
        question_id = str(item.get("question_id", ""))
        text = item.get("text")
        if not question_id or not isinstance(text, str) or not text.strip():
            raise ValueError("Every inference question requires a nonempty ID and text.")
        if question_id in records:
            raise ValueError(f"Duplicate inference question ID: {question_id}")
        records[question_id] = InferenceQuestion(question_id, text)
    ordered_ids = tuple(str(item) for item in question_ids)
    if len(set(ordered_ids)) != len(ordered_ids):
        raise ValueError("Requested question IDs must be unique.")
    missing = [question_id for question_id in ordered_ids if question_id not in records]
    if missing:
        raise ValueError(f"Inference question IDs are missing: {missing[:5]}")
    return tuple(records[question_id] for question_id in ordered_ids)


def validate_local_catalog(root: str | Path) -> dict[str, Any]:
    catalog_root = Path(root)
    report = validate_catalog_v2(catalog_root)
    manifest = json.loads((catalog_root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("local_catalog_schema_version") not in {
        LOCAL_CATALOG_SCHEMA_VERSION, LOCAL_ELIGIBLE_CATALOG_SCHEMA_VERSION
    }:
        raise ValueError("Unsupported query-local catalog schema.")
    if manifest.get("gold_used_for_construction") is not False:
        raise ValueError("Local catalog must attest gold_used_for_construction=false.")
    if manifest.get("requires_query_entity_filter") is not True:
        raise ValueError("Local catalog must enforce per-query candidate filtering.")
    if (manifest["local_catalog_schema_version"] == LOCAL_CATALOG_SCHEMA_VERSION
            and (manifest.get("candidate_selection") == ELIGIBLE_CANDIDATE_SELECTION
                 or "selection_diagnostics.json" in manifest.get("file_hashes", {}))):
        raise ValueError("Eligibility-first artifacts cannot be relabeled as a legacy catalog.")
    connection = sqlite3.connect(
        f"file:{catalog_root / 'catalog.sqlite3'}?mode=ro", uri=True
    )
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = {"local_queries", "query_entity_candidates"} - tables
        if missing:
            raise ValueError(f"Local catalog is missing tables: {sorted(missing)}")
        cross_query_orphans = int(
            connection.execute(
                "SELECT count(*) FROM query_entity_candidates q "
                "LEFT JOIN local_queries l ON l.question_id=q.question_id "
                "LEFT JOIN entities e ON e.id=q.entity_id "
                "WHERE l.question_id IS NULL OR e.id IS NULL"
            ).fetchone()[0]
        )
        if cross_query_orphans:
            raise ValueError("Local query candidate assignments contain orphan rows.")
        if manifest["local_catalog_schema_version"] == LOCAL_ELIGIBLE_CATALOG_SCHEMA_VERSION:
            from xgap.experiments.grailqa_eligible_catalog_validation import validate_selection

            validate_selection(catalog_root, manifest, connection)
    finally:
        connection.close()
    return {**report, "local_query_filter": "ok"}


def run_local_reachability_audit(
    *,
    catalog_root: str | Path,
    inference_questions_path: str | Path,
    question_ids: Sequence[str],
    reference_interpretations_path: str | Path,
    workload_stats_path: str | Path,
    output_root: str | Path,
    minimum_joint_ratio: float = 0.20,
    top_k: int = 20,
    prompt_limit: int = 4,
) -> dict[str, Any]:
    """Evaluate a complete local catalog; reference files are opened only here."""

    catalog_path = Path(catalog_root)
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    previous_metrics = previous_entity_contract_metrics(output)
    previous_schema_metrics = previous_schema_ranking_metrics(output)
    previous_endpoint_metrics = previous_endpoint_grounding_metrics(output)
    prior_artifact_hashes = {
        name: sha256_file(output / name)
        for name in (
            "audit_summary.json",
            "retrieval.jsonl",
            "relation_diagnostics.jsonl",
            "type_diagnostics.jsonl",
        )
        if (output / name).is_file()
    }
    questions = load_inference_questions(
        inference_questions_path, question_ids=question_ids
    )
    question_text_by_id = {item.question_id: item.text for item in questions}
    catalog = GrailQAInferenceCatalogV2.load(catalog_path)
    if catalog.manifest.get("local_catalog_schema_version") != LOCAL_CATALOG_SCHEMA_VERSION:
        raise ValueError("The local reachability audit requires an M13-E3B catalog.")
    retrieval_rows = [
        catalog.retrieve(
            item.question_id,
            item.text,
            top_k=top_k,
            relation_slots=3,
            expansion_hops=1,
        ).to_dict()
        for item in questions
    ]
    _write_jsonl(output / "retrieval.jsonl", retrieval_rows)

    # This is the first point at which evaluation-only artifacts are opened.
    requested = {item.question_id for item in questions}
    references = [
        item
        for item in _read_jsonl(Path(reference_interpretations_path))
        if str(item.get("question_id")) in requested
    ]
    workload = {
        str(item["question_id"]): item
        for item in _read_jsonl(Path(workload_stats_path))
        if str(item.get("question_id")) in requested
    }
    if {str(item.get("question_id")) for item in references} != requested:
        raise ValueError("Evaluation references do not cover the frozen local workload.")
    entities_by_question = _query_entity_ids(catalog_path)
    catalog_universe = load_catalog_universe(catalog_path)
    relation_diagnostics, type_diagnostics = relation_type_diagnostics(
        references=references,
        retrieval_rows=retrieval_rows,
        catalog=catalog_universe,
        prompt_limit=prompt_limit,
    )
    relation_ranking_audit, type_ranking_audit, taxonomy_counts = (
        schema_ranking_audits(
            references=references,
            trace_provider=lambda question_id: catalog.schema_ranking_trace(
                question_id,
                question_text_by_id[question_id],
                top_k=top_k,
                relation_slots=3,
                expansion_hops=1,
            ),
            prompt_limit=prompt_limit,
        )
    )
    relation_diagnostics_v2 = diagnostic_rows_v2(
        relation_diagnostics, relation_ranking_audit, kind="relation"
    )
    type_diagnostics_v2 = diagnostic_rows_v2(
        type_diagnostics, type_ranking_audit, kind="type"
    )
    if not (output / "relation_diagnostics.jsonl").is_file():
        _write_jsonl(output / "relation_diagnostics.jsonl", relation_diagnostics)
    if not (output / "type_diagnostics.jsonl").is_file():
        _write_jsonl(output / "type_diagnostics.jsonl", type_diagnostics)
    _write_jsonl(output / "relation_ranking_audit.jsonl", relation_ranking_audit)
    _write_jsonl(output / "type_ranking_audit.jsonl", type_ranking_audit)
    _write_jsonl(output / "relation_diagnostics_v2.jsonl", relation_diagnostics_v2)
    _write_jsonl(output / "type_diagnostics_v2.jsonl", type_diagnostics_v2)
    diagnostic_counts = {
        "relation": diagnostic_stage_counts(relation_diagnostics),
        "type": diagnostic_stage_counts(type_diagnostics),
    }
    audit = audit_reachability(
        references=references,
        retrieval_rows=retrieval_rows,
        catalog=catalog_universe,
        workload_by_id=workload,
        catalog_entities_by_question=entities_by_question,
        k_values=DEFAULT_K_VALUES,
        prompt_limit=prompt_limit,
    )
    rows = audit.pop("rows")
    endpoint_diagnostics = endpoint_grounding_diagnostics(rows)
    for row in rows:
        if row.get("first_unreachable_stage") == "reference_not_in_catalog":
            row["first_unreachable_stage"] = "reference_not_in_local_catalog"
    stage_counts = _local_stage_failure_counts(rows)
    gate = prompt_reachability_gate(audit, minimum_joint_ratio=minimum_joint_ratio)
    audit.update(
        {
            "schema_version": LOCAL_AUDIT_SCHEMA_VERSION,
            "gate": gate,
            "live_preflight_allowed": gate["passed"],
            "gold_usage": "evaluation_only_after_retrieval_persisted",
            "gold_used_for_construction": False,
            "stage_failure_counts": stage_counts,
            "relation_type_diagnostic_stage_counts": diagnostic_counts,
        }
    )
    _write_jsonl(output / "reachability.jsonl", rows)
    _write_jsonl(output / "relation_endpoint_diagnostics.jsonl", endpoint_diagnostics)
    catalog_coverage = {
        "schema_version": LOCAL_AUDIT_SCHEMA_VERSION,
        "question_count": audit["question_count"],
        "catalog": audit["summary"]["catalog"],
    }
    retrieval_metrics = {
        "schema_version": LOCAL_AUDIT_SCHEMA_VERSION,
        "question_count": audit["question_count"],
        "retrieval": audit["summary"]["retrieval"],
    }
    prompt_reachability = {
        "schema_version": LOCAL_AUDIT_SCHEMA_VERSION,
        "question_count": audit["question_count"],
        "prompt": audit["summary"]["prompt"],
        "deployed_prompt": audit["summary"]["deployed_prompt"],
        "gate": gate,
        "live_preflight_allowed": gate["passed"],
    }
    _write_json(output / "catalog_coverage.json", catalog_coverage)
    _write_json(output / "retrieval_metrics.json", retrieval_metrics)
    _write_json(output / "prompt_reachability.json", prompt_reachability)
    _write_json(output / "stage_failure_counts.json", stage_counts)
    contract_comparison = {
        "schema_version": LOCAL_CONTRACT_COMPARISON_SCHEMA_VERSION,
        "question_count": audit["question_count"],
        "prompt_limit": prompt_limit,
        "before": previous_metrics,
        "after": entity_contract_metrics(audit),
        "interpretation": (
            "The comparison is diagnostic only; candidate generation, prompt bounds, "
            "and the live gate are unchanged."
        ),
    }
    _write_json(
        output / "entity_retrieval_before_after.json", contract_comparison
    )
    schema_comparison = {
        "schema_version": SCHEMA_RANKING_COMPARISON_SCHEMA_VERSION,
        "question_count": audit["question_count"],
        "prompt_limit": prompt_limit,
        "before": previous_schema_metrics,
        "after": schema_ranking_metrics(audit),
        "failure_taxonomy_counts_before": taxonomy_counts,
        "ranking_contract": (
            ranking_contract(catalog.schema_statistics) if questions else None
        ),
        "preserved_before_artifact_hashes": prior_artifact_hashes,
        "gold_usage": "metrics_and_diagnostic_selection_only_after_ranking",
        "interpretation": (
            "The entity contract, Top-50 local universe, prompt limit, and live "
            "gate are unchanged. Missing before values mean no prior real audit "
            "artifact was available."
        ),
    }
    _write_json(output / "schema_ranking_before_after.json", schema_comparison)
    audit["schema_ranking"] = {
        "contract": schema_comparison["ranking_contract"],
        "failure_taxonomy_counts_before": taxonomy_counts,
        "before_metrics_available": previous_schema_metrics is not None,
        "previous_artifacts_preserved_by_hash": prior_artifact_hashes,
    }
    endpoint_comparison = {
        "schema_version": ENDPOINT_GROUNDING_COMPARISON_SCHEMA_VERSION,
        "question_count": audit["question_count"],
        "prompt_limit": prompt_limit,
        "before": previous_endpoint_metrics,
        "after": endpoint_grounding_metrics(audit),
        "contract_version": RELATION_ENDPOINT_CONTRACT_VERSION,
        "gold_usage": "metrics_and_diagnostic_selection_only_after_retrieval",
        "interpretation": (
            "Explicit Type Top-4 metrics remain separate. Effective type and joint "
            "reachability add only exact, role-aware endpoint evidence from selected "
            "prompt-visible relations."
        ),
    }
    _write_json(output / "endpoint_grounding_before_after.json", endpoint_comparison)
    audit["relation_endpoint_grounding"] = {
        "contract_version": RELATION_ENDPOINT_CONTRACT_VERSION,
        "before_metrics_available": previous_endpoint_metrics is not None,
        "comparison_artifact": "endpoint_grounding_before_after.json",
        "diagnostic_artifact": "relation_endpoint_diagnostics.jsonl",
    }
    audit["artifact_hashes"] = {
        name: sha256_file(output / name)
        for name in (
            "retrieval.jsonl",
            "reachability.jsonl",
            "catalog_coverage.json",
            "retrieval_metrics.json",
            "prompt_reachability.json",
            "stage_failure_counts.json",
            "entity_retrieval_before_after.json",
            "relation_diagnostics.jsonl",
            "type_diagnostics.jsonl",
            "schema_ranking_before_after.json",
            "relation_ranking_audit.jsonl",
            "type_ranking_audit.jsonl",
            "relation_diagnostics_v2.jsonl",
            "type_diagnostics_v2.jsonl",
            "endpoint_grounding_before_after.json",
            "relation_endpoint_diagnostics.jsonl",
        )
    }
    audit["audit_hash"] = content_hash(audit)
    _write_json(output / "audit_summary.json", audit)
    return audit


def compare_full_and_local(
    *,
    local_catalog_root: str | Path,
    local_audit_path: str | Path,
    output_path: str | Path,
    full_catalog_root: str | Path | None = None,
    full_audit_path: str | Path | None = None,
) -> dict[str, Any]:
    """Write a same-workload comparison, leaving unavailable full values pending."""

    local_manifest = _read_json(Path(local_catalog_root) / "manifest.json")
    local_audit = _read_json(Path(local_audit_path))
    local = _comparison_column(local_manifest, local_audit)
    full: dict[str, Any] | None = None
    if full_catalog_root is not None or full_audit_path is not None:
        if full_catalog_root is None or full_audit_path is None:
            raise ValueError("Full comparison requires both catalog and audit paths.")
        full = _comparison_column(
            _read_json(Path(full_catalog_root) / "manifest.json"),
            _read_json(Path(full_audit_path)),
        )
    result = {
        "schema_version": "m13e3b-full-vs-local-comparison-v1",
        "full_status": "available" if full is not None else "pending_global_build",
        "metrics": {
            name: {"full": None if full is None else full[name], "local": local[name]}
            for name in local
        },
    }
    _write_json(Path(output_path), result)
    return result


def _collect_candidate_metadata(
    records: Iterable[ParquetTripleRecord],
    *,
    allowed_entity_ids: Iterable[str] | None = None,
    require_materializable_canonical: bool = False,
) -> _CandidateMetadata:
    if require_materializable_canonical:
        from xgap.experiments.grailqa_eligible_candidates import canonical_name_is_materializable

    allowed = None if allowed_entity_ids is None else frozenset(allowed_entity_ids)
    canonical_names: dict[str, str] = {}
    aliases: dict[str, set[tuple[str, str]]] = {}
    types: dict[str, set[str]] = {}
    for record in records:
        subject, predicate, value, language, is_resource = record.triple
        if _MID.fullmatch(subject) is None or (allowed is not None and subject not in allowed):
            continue
        if predicate in (NAME_PREDICATE, ALIAS_PREDICATE) and not is_resource:
            if language != "en":
                continue
            kind = "canonical" if predicate == NAME_PREDICATE else "alias"
            if (require_materializable_canonical and kind == "canonical"
                    and not canonical_name_is_materializable(value)):
                # Match the final SQLite integrity rule before choosing a name.
                # Do not let a blank canonical override a usable later name.
                continue
            aliases.setdefault(subject, set()).add((value, kind))
            if kind == "canonical":
                canonical_names.setdefault(subject, value)
        elif predicate == TYPE_PREDICATE and is_resource:
            types.setdefault(subject, set()).add(value)
    return _CandidateMetadata(
        canonical_names=dict(sorted(canonical_names.items())),
        aliases={
            key: tuple(sorted(values, key=lambda item: (item[0], item[1])))
            for key, values in sorted(aliases.items())
            if key in canonical_names
        },
        types={
            key: tuple(sorted(values))
            for key, values in sorted(types.items())
            if key in canonical_names
        },
    )


def _drop_entities_without_canonical_names(
    candidates: Mapping[str, tuple[LocalCandidateMatch, ...]],
    metadata: _CandidateMetadata,
) -> dict[str, tuple[LocalCandidateMatch, ...]]:
    return {
        question_id: tuple(
            LocalCandidateMatch(**{**item.__dict__, "rank": rank})
            for rank, item in enumerate(
                (
                    item
                    for item in values
                    if item.entity_id in metadata.canonical_names
                ),
                start=1,
            )
        )
        for question_id, values in candidates.items()
    }


def _materialize_subset(
    *,
    output: Path,
    questions: Sequence[InferenceQuestion],
    candidates: Mapping[str, tuple[LocalCandidateMatch, ...]],
    metadata: _CandidateMetadata,
    ontology_path: Path,
    reverse_path: Path,
) -> tuple[dict[str, int], dict[str, Any]]:
    ontology = OntologyGraph.from_dict(load_yaml_mapping(ontology_path))
    reverse_properties = {
        str(key): str(value)
        for key, value in _read_json(reverse_path).items()
    }
    database = output / "catalog.sqlite3"
    connection = sqlite3.connect(database)
    try:
        _create_database(connection)
        _seed_terms(connection, ontology, reverse_properties)
        labels: list[tuple[str, str, str, str]] = []
        for entity_id, values in metadata.aliases.items():
            by_label: dict[str, str] = {}
            for label, kind in values:
                if kind == "canonical" or label not in by_label:
                    by_label[label] = kind
            labels.extend(
                (entity_id, label, normalized_label(label), kind)
                for label, kind in sorted(by_label.items())
            )
        memberships = [
            (entity_id, type_id)
            for entity_id, values in metadata.types.items()
            for type_id in values
        ]
        _flush_ingest(connection, labels, memberships, [])
        connection.executescript(
            """
            CREATE TABLE local_queries(
              question_id TEXT PRIMARY KEY, question_hash TEXT NOT NULL,
              question_text TEXT NOT NULL
            );
            CREATE TABLE query_entity_candidates(
              question_id TEXT NOT NULL, entity_id TEXT NOT NULL,
              rank INTEGER NOT NULL, lexical_score REAL NOT NULL,
              matched_label TEXT NOT NULL, normalized_label TEXT NOT NULL,
              match_type TEXT NOT NULL, source_shard TEXT NOT NULL,
              PRIMARY KEY(question_id, entity_id)
            );
            CREATE INDEX query_entity_candidate_idx
              ON query_entity_candidates(question_id, rank, entity_id);
            """
        )
        connection.executemany(
            "INSERT INTO local_queries(question_id, question_hash, question_text) VALUES(?,?,?)",
            (
                _sqlite_row((item.question_id, item.question_hash, item.text))
                for item in questions
            ),
        )
        connection.executemany(
            "INSERT INTO query_entity_candidates("
            "question_id,entity_id,rank,lexical_score,matched_label,normalized_label,"
            "match_type,source_shard) VALUES(?,?,?,?,?,?,?,?)",
            (
                _sqlite_row(
                    (
                        item.question_id,
                        item.entity_id,
                        item.rank,
                        item.score,
                        item.matched_label,
                        item.normalized_label,
                        item.match_type,
                        item.source_shard,
                    )
                )
                for values in candidates.values()
                for item in values
            ),
        )
        connection.commit()
        _finalize_database(connection)
        counts = _write_catalog_files(connection, output, ontology)
        integrity = _database_integrity(connection, ontology)
    finally:
        connection.close()
    shutil.copyfile(ontology_path, output / "ontology.yaml")
    _write_jsonl(
        output / "local_queries.jsonl",
        (
            {
                "question_id": item.question_id,
                "question_hash": item.question_hash,
                "text": item.text,
            }
            for item in questions
        ),
    )
    _write_jsonl(
        output / "query_entity_candidates.jsonl",
        (
            item.to_dict()
            for question in questions
            for item in candidates[question.question_id]
        ),
    )
    return counts, integrity


SQLiteValue = str | int | float | bytes | None


def _sqlite_value(value: object) -> SQLiteValue:
    """Normalize one SQLite parameter without changing semantic primitives."""

    if isinstance(value, PurePath):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bytes)):
        return value
    raise TypeError(f"Unsupported SQLite parameter type: {type(value).__name__}")


def _sqlite_row(values: Iterable[object]) -> tuple[SQLiteValue, ...]:
    return tuple(_sqlite_value(value) for value in values)


def _existing_lexical_score(question: str, alias_normalized: str) -> float:
    question_normalized = normalized_label(question)
    question_tokens = set(question_normalized.split())
    alias_tokens = set(alias_normalized.split())
    overlap = len(question_tokens & alias_tokens)
    score = overlap / max(1, len(question_tokens | alias_tokens))
    if f" {alias_normalized} " in f" {question_normalized} ":
        score += 2.0 + min(len(alias_tokens), 10) / 100.0
    return round(score, 12)


def _candidate_key(item: LocalCandidateMatch) -> tuple[float, str, str, str]:
    return (-item.score, item.entity_id, item.matched_label, item.source_shard)


def _rank_candidates(
    values: Iterable[LocalCandidateMatch], limit: int
) -> tuple[LocalCandidateMatch, ...]:
    ranked = sorted(values, key=_candidate_key)[:limit]
    return tuple(
        LocalCandidateMatch(**{**item.__dict__, "rank": rank})
        for rank, item in enumerate(ranked, start=1)
    )


def _guard_output_path(output: Path, parquet_root: Path) -> None:
    if output == parquet_root or parquet_root in output.parents:
        raise ValueError("Local catalog output must be separate from the Parquet source.")
    if ".catalog-v2.building" in output.parts:
        raise ValueError("Local catalog must not write into the global build staging path.")
    global_output = os.environ.get("XGAP_FREEBASE_CATALOG_DIR")
    if global_output and output == Path(global_output).expanduser().resolve():
        raise ValueError("Local catalog must not overwrite XGAP_FREEBASE_CATALOG_DIR.")


def _publish_catalog(staging: Path, output: Path, *, force: bool) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    publication = output.with_name(f".{output.name}.publishing-{os.getpid()}")
    if publication.exists():
        shutil.rmtree(publication)
    shutil.copytree(staging, publication)
    validate_local_catalog(publication)
    backup = output.with_name(f".{output.name}.previous-{os.getpid()}")
    if output.exists():
        if not force:
            shutil.rmtree(publication)
            raise FileExistsError(f"Local catalog output exists: {output}")
        output.replace(backup)
    try:
        publication.replace(output)
    except Exception:
        if backup.exists() and not output.exists():
            backup.replace(output)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def _query_entity_ids(root: Path) -> dict[str, tuple[str, ...]]:
    connection = sqlite3.connect(f"file:{root / 'catalog.sqlite3'}?mode=ro", uri=True)
    try:
        result: dict[str, list[str]] = {}
        for question_id, entity_id in connection.execute(
            "SELECT question_id, entity_id FROM query_entity_candidates "
            "ORDER BY question_id, rank, entity_id"
        ):
            result.setdefault(str(question_id), []).append(str(entity_id))
        return {key: tuple(values) for key, values in result.items()}
    finally:
        connection.close()


def _local_stage_failure_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    stages = (
        "reference_not_in_local_catalog",
        "reference_not_retrieved",
        "reference_not_prompt_visible",
        "reachable",
    )
    counts = {stage: 0 for stage in stages}
    for row in rows:
        stage = str(row.get("first_unreachable_stage") or "reachable")
        if stage not in counts:
            raise ValueError(f"Unknown local reachability stage: {stage}")
        counts[stage] += 1
    total = len(rows)
    return {
        "schema_version": LOCAL_AUDIT_SCHEMA_VERSION,
        "question_count": total,
        "counts": counts,
        "ratios": {
            stage: count / total if total else None for stage, count in counts.items()
        },
    }


def _comparison_column(
    manifest: Mapping[str, Any], audit: Mapping[str, Any]
) -> dict[str, Any]:
    summary = _mapping(audit.get("summary"), "summary")
    return {
        "artifact_size_bytes": manifest.get("database_size_bytes"),
        "construction_wall_clock_seconds": _mapping(
            manifest.get("construction"), "construction"
        ).get("wall_clock_seconds"),
        "unique_entities": _mapping(manifest.get("counts"), "counts").get(
            "unique_candidate_mids", _mapping(manifest.get("counts"), "counts").get("entities")
        ),
        "entity_catalog_coverage": _metric_ratio(summary, "catalog", None, "entity"),
        "entity_recall_at_20": _metric_ratio(summary, "retrieval", "20", "entity"),
        "joint_prompt_reachability": _metric_ratio(
            summary, "deployed_prompt", None, "joint"
        ),
    }


def _metric_ratio(
    summary: Mapping[str, Any], stage: str, key: str | None, kind: str
) -> Any:
    value = _mapping(summary.get(stage), stage)
    if key is not None:
        value = _mapping(value.get(key), key)
    return _mapping(value.get(kind), kind).get("ratio")


def _load_complete_manifest(root: Path) -> dict[str, Any] | None:
    path = root / "manifest.json"
    if not path.is_file():
        return None
    manifest = _read_json(path)
    return manifest if manifest.get("status") == "complete" else None


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return _mapping(value, str(path))


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield _mapping(json.loads(line), str(path))


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), sort_keys=True, ensure_ascii=True) + "\n")


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object.")
    return value


def _peak_rss_bytes() -> int | None:
    try:
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (OSError, ValueError):
        return None
    return value if sys.platform == "darwin" else value * 1024


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_config(path: str | Path, workload: str) -> dict[str, Any]:
    config_path = Path(path).resolve()
    config = _read_json(config_path)
    if config.get("schema_version") != "m13e3b-grailqa-local-catalog-config-v1":
        raise ValueError("Unsupported local catalog config schema.")
    workloads = _mapping(config.get("workloads"), "workloads")
    if workload not in workloads:
        raise ValueError(f"Unknown local catalog workload: {workload}")
    selected = _mapping(workloads[workload], workload)
    return {"config_path": config_path, "config": config, "workload": selected}


def _resolve_repo_path(config_path: Path, value: object) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    repo_root = config_path.parents[2]
    return repo_root / path


def _command_context(args: argparse.Namespace) -> dict[str, Any]:
    loaded = _load_config(args.config, args.workload)
    config_path = loaded["config_path"]
    config = loaded["config"]
    workload = loaded["workload"]
    source = _mapping(config.get("source"), "source")
    if (
        source.get("source_mode") != "hf_archival_parquet"
        or source.get("repo_id") != HF_FREEBASE_REPO_ID
        or source.get("revision") != HF_FREEBASE_REVISION
        or int(source.get("expected_shards", -1)) != 964
        or int(source.get("expected_bytes", -1)) != 32_476_432_840
    ):
        raise ValueError("Local catalog config differs from the frozen M13-E3A source.")
    anchors = _mapping(config.get("anchor_extraction"), "anchor_extraction")
    local_root = Path(args.local_root).resolve()
    output = local_root / str(workload["output_subdirectory"])
    questions = _resolve_repo_path(config_path, workload["inference_questions"])
    configured_ids = workload.get("question_ids")
    question_ids = (
        tuple(item.question_id for item in _load_all_inference_questions(questions))
        if configured_ids == "all"
        else tuple(str(item) for item in configured_ids)
    )
    return {
        "config_path": config_path,
        "workload": workload,
        "questions": questions,
        "question_ids": question_ids,
        "artifact_id": str(workload["artifact_id"]),
        "output": output,
        "source_manifest": Path(args.source_manifest).resolve(),
        "parquet_root": Path(args.parquet_root).resolve(),
        "ontology": _resolve_repo_path(config_path, config["normalized_ontology"]),
        "reverse": _resolve_repo_path(config_path, config["reverse_properties"]),
        "max_candidates": int(anchors["max_candidates_per_query"]),
        "anchor_min_tokens": int(anchors["min_tokens"]),
        "anchor_max_tokens": int(anchors["max_tokens"]),
        "omit_stopword_only": bool(anchors["omit_stopword_only"]),
        "source": source,
    }


def _load_all_inference_questions(path: Path) -> tuple[InferenceQuestion, ...]:
    identifiers: list[str] = []
    for item in _read_jsonl(path):
        forbidden = _FORBIDDEN_INPUT_FIELDS & set(item)
        unexpected = set(item) - _QUESTION_FIELDS
        if forbidden or unexpected:
            raise ValueError("Workload question file is not inference-only.")
        identifiers.append(str(item.get("question_id", "")))
    return load_inference_questions(path, question_ids=identifiers)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "audit", "run", "compare"))
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--workload", choices=("preflight18", "pilot150"), default="preflight18")
    parser.add_argument("--parquet-root", default=os.environ.get("XGAP_FREEBASE_PARQUET_ROOT", ""))
    parser.add_argument("--source-manifest", default=os.environ.get("XGAP_FREEBASE_SOURCE_MANIFEST", ""))
    parser.add_argument(
        "--local-root",
        default=os.environ.get(
            "XGAP_GRAILQA_LOCAL_CATALOG_ROOT", "datasets/grailqa_local_catalog_v1"
        ),
    )
    parser.add_argument("--staging-root", default=os.environ.get("TMPDIR"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--candidate-selection",
        choices=(LEGACY_CANDIDATE_SELECTION, ELIGIBLE_CANDIDATE_SELECTION),
        default=LEGACY_CANDIDATE_SELECTION,
        help="v2 is a fresh, build-only development artifact; frozen defaults stay v1",
    )
    parser.add_argument("--full-catalog")
    parser.add_argument("--full-audit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.candidate_selection == ELIGIBLE_CANDIDATE_SELECTION:
        if args.command != "build" or args.force:
            raise ValueError("Eligibility-first v2 permits fresh build only, without force.")
        explicit_args = tuple(sys.argv[1:] if argv is None else argv)
        if not any(arg == "--local-root" or arg.startswith("--local-root=")
                   for arg in explicit_args):
            raise ValueError("Eligibility-first v2 requires an explicit --local-root.")
        requested_root = Path(args.local_root).absolute()
        if any(part.is_symlink() for part in (requested_root, *requested_root.parents)):
            raise ValueError("Eligibility-first local root and ancestors must not be symlinks.")
    context = _command_context(args)
    if args.candidate_selection == ELIGIBLE_CANDIDATE_SELECTION:
        context["artifact_id"] += "-eligible-v2"
        context["output"] = context["output"].with_name(
            context["output"].name + "-eligible-v2"
        )
    if args.command in {"build", "run"}:
        if not args.parquet_root or not args.source_manifest:
            raise ValueError("Parquet root and source manifest are required for construction.")
        build_local_catalog(
            inference_questions_path=context["questions"],
            question_ids=context["question_ids"],
            workload_name=args.workload,
            artifact_id=context["artifact_id"],
            freebase_parquet_root=context["parquet_root"],
            source_manifest_path=context["source_manifest"],
            normalized_ontology_path=context["ontology"],
            reverse_properties_path=context["reverse"],
            output_root=context["output"],
            staging_root=args.staging_root,
            max_candidates_per_query=context["max_candidates"],
            anchor_min_tokens=context["anchor_min_tokens"],
            anchor_max_tokens=context["anchor_max_tokens"],
            omit_stopword_only=context["omit_stopword_only"],
            force=args.force,
            candidate_selection=args.candidate_selection,
        )
        print(f"Local catalog ready: {context['output']}")
    if args.command in {"audit", "run"}:
        pilot_root = Path(context["questions"]).parent
        audit = run_local_reachability_audit(
            catalog_root=context["output"],
            inference_questions_path=context["questions"],
            question_ids=context["question_ids"],
            reference_interpretations_path=pilot_root / "reference_interpretations.jsonl",
            workload_stats_path=pilot_root / "workload_stats.jsonl",
            output_root=context["output"],
            minimum_joint_ratio=0.20,
            top_k=20,
            prompt_limit=4,
        )
        print(
            json.dumps(
                {
                    "live_preflight_allowed": audit["live_preflight_allowed"],
                    "gate": audit["gate"],
                },
                indent=2,
                sort_keys=True,
            )
        )
    if args.command == "compare":
        compare_full_and_local(
            local_catalog_root=context["output"],
            local_audit_path=context["output"] / "audit_summary.json",
            output_path=context["output"] / "full_vs_local_comparison.json",
            full_catalog_root=args.full_catalog,
            full_audit_path=args.full_audit,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
