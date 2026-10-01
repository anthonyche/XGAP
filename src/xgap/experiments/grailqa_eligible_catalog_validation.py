"""Development-only v2 selection consistency and non-overwriting publication.

This checks the persisted selection, not completeness against the source dump
or semantic accuracy. Historical paper/reachability admissions remain v1-only.
"""

from __future__ import annotations

import json
from itertools import zip_longest
import math
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any, Callable, Mapping

from xgap.experiments.grailqa_catalog import normalized_label, sha256_file
from xgap.experiments.hashing import content_hash


_FILES = frozenset({
    "catalog.sqlite3", "entities.jsonl", "entity_aliases.jsonl", "entity_types.jsonl",
    "terms.jsonl", "type_aliases.jsonl", "relation_aliases.jsonl", "relation_metadata.jsonl",
    "reverse_properties.json", "ontology.yaml", "local_queries.jsonl",
    "query_entity_candidates.jsonl", "selection_diagnostics.json",
})
_COUNT_FIELDS = frozenset({
    "matched_entity_count", "eligible_entity_count", "dropped_without_canonical_count",
    "selected_count", "truncated_eligible_count", "legacy_topk_dropped_count",
    "backfilled_count",
})


def validate_selection(
    root: Path, manifest: Mapping[str, Any], connection: sqlite3.Connection,
) -> None:
    """Reconcile v2 identity, deterministic diagnostics and both persisted views."""

    def require(condition: bool, reason: str) -> None:
        if not condition:
            raise ValueError("Eligibility-first catalog: " + reason)

    policy = "canonical_eligible_topk_v2"
    require((root / "manifest.json").is_file() and not (root / "manifest.json").is_symlink(),
            "unsafe manifest")
    require(manifest.get("candidate_selection") == policy, "selection policy mismatch")
    require(manifest.get("paper_result") is False, "development claim boundary missing")
    hashes = manifest.get("file_hashes", {})
    require(isinstance(hashes, dict) and set(hashes) == _FILES, "artifact set mismatch")
    for name in sorted(_FILES):
        path = root / name
        require(path.is_file() and not path.is_symlink(), "unsafe artifact " + name)
        require(sha256_file(path) == hashes[name], "artifact hash mismatch: " + name)
    anchors = manifest["anchor_extraction"]
    require(isinstance(anchors, dict), "anchor contract missing")
    limit = anchors.get("max_candidates_per_query")
    require(type(limit) is int and 1 <= limit <= 900, "invalid candidate bound")
    require(
        anchors.get("version") == "m13e3b-contiguous-normalized-spans-v1"
        and anchors.get("normalization_version") == "catalog-v2-normalized-label-v1"
        and anchors.get("matching") == ["exact_normalized_name", "exact_normalized_alias"],
        "anchor algorithm mismatch",
    )
    minimum, maximum = anchors.get("min_tokens"), anchors.get("max_tokens")
    require(type(minimum) is int and type(maximum) is int and 1 <= minimum <= maximum,
            "invalid anchor bounds")
    require(type(anchors.get("omit_stopword_only")) is bool, "invalid stopword policy")
    semantic_counts, materialized_entities = _validate_semantic_views(root, connection, require)
    identity = {
        "schema_version": "m13e3b-grailqa-local-catalog-v2",
        "source_manifest_sha256": manifest["sources"]["freebase_archival_parquet"][
            "source_manifest_sha256"
        ],
        "question_text_sha256": manifest["question_text_sha256"],
        "candidate_selection": policy,
        "anchor_extraction": anchors,
        "content_file_hashes": {k: v for k, v in hashes.items() if k != "catalog.sqlite3"},
    }
    require(content_hash(identity) == manifest.get("catalog_hash"), "catalog identity mismatch")
    diagnostics = json.loads((root / "selection_diagnostics.json").read_text(encoding="utf-8"))
    require(set(diagnostics) == {"schema_version", "selection_policy", "gold_inputs", "per_query"},
            "diagnostic fields mismatch")
    require(
        diagnostics["schema_version"] == "m13e3b-canonical-eligible-selection-v2"
        and diagnostics["selection_policy"] == policy and diagnostics["gold_inputs"] is False,
        "diagnostic contract mismatch",
    )
    ids = manifest["question_ids"]
    require(isinstance(ids, list) and all(isinstance(qid, str) and qid for qid in ids)
            and len(ids) == len(set(ids)), "invalid or duplicate question IDs")
    require(content_hash(ids) == manifest.get("question_set_sha256"), "question set hash mismatch")
    require(set(diagnostics["per_query"]) == set(ids), "diagnostic question set mismatch")
    queries = {
        qid: {"question_id": qid, "question_hash": digest, "text": text}
        for qid, digest, text in connection.execute(
            "SELECT question_id, question_hash, question_text FROM local_queries"
        )
    }
    require(set(queries) == set(ids), "database question set mismatch")
    persisted_queries = _rows(root / "local_queries.jsonl")
    require(persisted_queries == [queries[qid] for qid in ids], "query JSONL/DB mismatch")
    from hashlib import sha256

    require(all(row["question_hash"] == sha256(row["text"].encode()).hexdigest()
                for row in queries.values()), "individual question hash mismatch")
    require(content_hash([{"question_id": qid, "text": queries[qid]["text"]} for qid in ids])
            == manifest["question_text_sha256"], "question text hash mismatch")
    from xgap.experiments.grailqa_local_catalog import (
        _existing_lexical_score, extract_query_anchors,
    )

    question_anchors = {
        qid: set(extract_query_anchors(
            queries[qid]["text"], min_tokens=minimum, max_tokens=maximum,
            omit_stopword_only=anchors["omit_stopword_only"],
        )) for qid in ids
    }
    persisted: list[dict[str, Any]] = []
    for qid in ids:
        rows = connection.execute(
            "SELECT entity_id,rank,lexical_score,matched_label,normalized_label,match_type,source_shard "
            "FROM query_entity_candidates WHERE question_id=? ORDER BY rank", (qid,),
        ).fetchall()
        require(len({r[0] for r in rows}) == len(rows), "duplicate selected MID")
        require([r[1] for r in rows] == list(range(1, len(rows) + 1)), "noncontiguous ranks")
        for entity_id, _, score, label, normalized, match_type, shard in rows:
            require(isinstance(label, str) and isinstance(normalized, str)
                    and bool(normalized) and normalized == normalized_label(label),
                    "candidate label normalization mismatch")
            require(normalized in question_anchors[qid], "candidate is not a question anchor")
            require(type(score) in {int, float} and math.isfinite(score)
                    and score == _existing_lexical_score(queries[qid]["text"], normalized),
                    "candidate lexical score mismatch")
            require(match_type in {"exact_normalized_name", "exact_normalized_alias"},
                    "candidate match type mismatch")
            require(isinstance(shard, str), "invalid candidate source shard")
            aliases = connection.execute(
                "SELECT normalized_alias,alias_kind FROM entity_aliases "
                "WHERE entity_id=? AND alias=?", (entity_id, label),
            ).fetchall()
            require(len(aliases) == 1 and aliases[0][0] == normalized,
                    "candidate label absent from materialized entity aliases")
            # Materialization merges identical NAME/ALIAS strings, preserving
            # canonical kind. Thus a name claim must remain canonical, while an
            # alias claim may correspond to that merged canonical row. The
            # original source predicate/shard is not recoverable from this DB.
            require(match_type != "exact_normalized_name" or aliases[0][1] == "canonical",
                    "candidate name claim lacks materialized canonical evidence")
        require(rows == sorted(rows, key=lambda r: (-r[2], r[0], r[3], r[6])), "rank order mismatch")
        counts = diagnostics["per_query"][qid]
        require(set(counts) == _COUNT_FIELDS and all(type(v) is int and v >= 0 for v in counts.values()),
                "invalid diagnostic counts")
        matched, eligible = counts["matched_entity_count"], counts["eligible_entity_count"]
        selected = counts["selected_count"]
        old_dropped = counts["legacy_topk_dropped_count"]
        require(matched == eligible + counts["dropped_without_canonical_count"], "eligibility count mismatch")
        require(selected == len(rows) == min(limit, eligible), "selection count mismatch")
        require(eligible == selected + counts["truncated_eligible_count"], "truncation count mismatch")
        require(old_dropped <= min(limit, matched) and old_dropped <= counts["dropped_without_canonical_count"],
                "legacy truncation count mismatch")
        require(counts["backfilled_count"] == selected - (min(limit, matched) - old_dropped),
                "backfill count mismatch")
        persisted.extend({
            "question_id": qid, "entity_id": r[0], "rank": r[1], "lexical_score": r[2],
            "matched_label": r[3], "normalized_label": r[4], "match_type": r[5], "source_shard": r[6],
        } for r in rows)
    require(_rows(root / "query_entity_candidates.jsonl") == persisted, "candidate JSONL/DB mismatch")
    selected_entities = {row["entity_id"] for row in persisted}
    require(selected_entities == materialized_entities, "materialized/selected entity universe mismatch")
    expected_counts = {
        **semantic_counts, "questions": len(ids),
        "query_anchors": sum(len(values) for values in question_anchors.values()),
        "query_candidate_assignments": len(persisted),
        "unique_candidate_mids": len(selected_entities),
    }
    counts = manifest.get("counts")
    require(isinstance(counts, dict) and set(counts) == set(expected_counts)
            and all(type(value) is int for value in counts.values())
            and counts == expected_counts, "manifest published counts mismatch")


def _validate_semantic_views(
    root: Path, connection: sqlite3.Connection, require: Callable[[bool, str], None],
) -> tuple[dict[str, int], set[str]]:
    """Independently reconstruct the local builder's canonical SQL projections.

    SQLite bytes are deliberately outside the semantic catalog identity. Every
    published semantic projection must therefore agree with the corresponding
    DB rows read by retrieval, not merely have an independently valid file hash.
    Comparisons stream rows rather than duplicating all alias data in memory.
    """

    def compare(filename: str, fields: tuple[str, ...], sql: str) -> None:
        sentinel = object()
        with (root / filename).open(encoding="utf-8") as handle:
            persisted = (json.loads(line) for line in handle if line.strip())
            expected = (dict(zip(fields, row)) for row in connection.execute(sql))
            for actual, reconstructed in zip_longest(persisted, expected, fillvalue=sentinel):
                require(actual == reconstructed, "semantic JSONL/DB mismatch: " + filename)

    compare("entities.jsonl", ("id", "canonical_name"),
            "SELECT id,canonical_name FROM entities ORDER BY id")
    compare("entity_aliases.jsonl", ("entity_id", "alias", "normalized_alias", "kind"),
            "SELECT entity_id,alias,normalized_alias,alias_kind FROM entity_aliases ORDER BY entity_id,alias")
    compare("entity_types.jsonl", ("entity_id", "type_id"),
            "SELECT entity_id,type_id FROM entity_types ORDER BY entity_id,type_id")
    compare("terms.jsonl", ("id", "kind", "label", "domain", "range", "reverse_id"),
            "SELECT id,kind,label,domain_id,range_id,reverse_id FROM terms ORDER BY id")
    for kind, filename in (("type", "type_aliases.jsonl"), ("relation", "relation_aliases.jsonl")):
        compare(filename, ("term_id", "alias", "normalized_alias"),
                "SELECT a.term_id,a.alias,a.normalized_alias FROM term_aliases a "
                f"JOIN terms t ON t.id=a.term_id WHERE t.kind='{kind}' ORDER BY a.term_id,a.alias")
    compare("relation_metadata.jsonl", ("relation_id", "domain", "range", "reverse_id"),
            "SELECT id,domain_id,range_id,reverse_id FROM terms WHERE kind='relation' ORDER BY id")
    reverse = {
        str(relation_id): str(reverse_id)
        for relation_id, reverse_id in connection.execute(
            "SELECT id,reverse_id FROM terms WHERE kind='relation' ORDER BY id"
        ) if reverse_id
    }
    require(json.loads((root / "reverse_properties.json").read_text(encoding="utf-8")) == reverse,
            "reverse metadata JSON/DB mismatch")
    for alias, normalized, kind in connection.execute(
        "SELECT alias,normalized_alias,alias_kind FROM entity_aliases"
    ):
        require(isinstance(alias, str) and normalized == normalized_label(alias)
                and kind in {"canonical", "alias"}, "invalid materialized entity alias")
    for alias, normalized in connection.execute("SELECT alias,normalized_alias FROM term_aliases"):
        require(isinstance(alias, str) and normalized == normalized_label(alias),
                "invalid materialized term alias")
    for entity_id, canonical, minimum_canonical in connection.execute(
        "SELECT e.id,e.canonical_name,min(a.alias) FROM entities e "
        "LEFT JOIN entity_aliases a ON a.entity_id=e.id AND a.alias_kind='canonical' "
        "GROUP BY e.id,e.canonical_name"
    ):
        require(canonical == minimum_canonical, "canonical name is not its materialized canonical alias")
    require(connection.execute(
        "SELECT count(*) FROM terms WHERE kind NOT IN ('type','relation')"
    ).fetchone()[0] == 0, "unexpected materialized schema kind")
    require(connection.execute(
        "SELECT count(*) FROM term_aliases a LEFT JOIN terms t ON t.id=a.term_id WHERE t.id IS NULL"
    ).fetchone()[0] == 0, "orphan materialized term alias")

    def count(sql: str) -> int:
        return int(connection.execute(sql).fetchone()[0])

    counts = {
        "entities": count("SELECT count(*) FROM entities"),
        "canonical_names": count("SELECT count(*) FROM entity_aliases WHERE alias_kind='canonical'"),
        "entity_aliases": count("SELECT count(*) FROM entity_aliases"),
        "entity_types": count("SELECT count(*) FROM entity_types"),
        "types": count("SELECT count(*) FROM terms WHERE kind='type'"),
        "relations": count("SELECT count(*) FROM terms WHERE kind='relation'"),
        "relation_aliases": count("SELECT count(*) FROM term_aliases a JOIN terms t "
                                  "ON t.id=a.term_id WHERE t.kind='relation'"),
        "reverse_property_entries": len(reverse),
    }
    entities = {str(row[0]) for row in connection.execute("SELECT id FROM entities")}
    return counts, entities


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def publish_fresh_catalog(
    staging: Path, output: Path, validate: Callable[[Path], object],
) -> None:
    """Exclusively claim a new output; publish the completion manifest last.

    Partial output is retained on failure. No existing output or unrelated
    publication directory is removed. Hard links use a verified private copy
    on the destination filesystem, not the node-local construction source.
    """

    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Eligibility-first catalog output exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".xgap-eligible-publishing-", dir=output.parent) as tmp:
        publication = Path(tmp) / "catalog"
        shutil.copytree(staging, publication, symlinks=True)
        validate(publication)
        entries = {p.name: p for p in publication.iterdir()}
        if set(entries) != _FILES | {"manifest.json"} or any(
            p.is_symlink() or not p.is_file() for p in entries.values()
        ):
            raise ValueError("Eligibility-first publication contains unsafe or unexpected files.")
        output.mkdir()  # Atomic claim; even an existing empty directory is preserved.
        for name in sorted(_FILES):
            os.link(entries[name], output / name, follow_symlinks=False)
        os.link(entries["manifest.json"], output / "manifest.json", follow_symlinks=False)
