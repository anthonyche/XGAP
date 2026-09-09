"""Gold-free, disk-spooled canonical eligibility before local entity Top-K.

The legacy span extraction, score and materialization eligibility are retained.
Unlike the legacy selector, unmaterializable alias hits cannot consume Top-K
positions. All canonical MID identities and all per-query/MID best matches are
spooled to SQLite; neither corpus-wide collection is held in Python memory.
This module does not change the frozen selector or any experiment entrypoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePath
import sqlite3
import tempfile
import time
from typing import Any, Iterable, Sequence

from xgap.experiments.freebase_sources import (
    ALIAS_PREDICATE, NAME_PREDICATE, ParquetTripleRecord,
)
from xgap.experiments.grailqa_local_catalog import (
    _MID, _existing_lexical_score, extract_query_anchors,
)
from xgap.experiments.grailqa_local_catalog_types import (
    InferenceQuestion, LocalCandidateMatch,
)
from xgap.experiments.grailqa_catalog import normalized_label


ELIGIBLE_SELECTION_SCHEMA_VERSION = "m13e3b-canonical-eligible-selection-v2"
ELIGIBLE_SELECTION_POLICY = "canonical_eligible_topk_v2"
_BATCH_ROWS = 4096
_CACHE_KIB = 16 * 1024


@dataclass(frozen=True)
class EligibleCandidateSelection:
    candidates: dict[str, tuple[LocalCandidateMatch, ...]]
    diagnostics: dict[str, Any]


_UPSERT_MATCH = """
INSERT INTO matches(
    question_id,entity_id,matched_label,normalized_label,match_type,
    lexical_score,source_shard,match_priority
) VALUES(?,?,?,?,?,?,?,?)
ON CONFLICT(question_id,entity_id) DO UPDATE SET
    matched_label=excluded.matched_label,
    normalized_label=excluded.normalized_label,
    match_type=excluded.match_type,
    lexical_score=excluded.lexical_score,
    source_shard=excluded.source_shard,
    match_priority=excluded.match_priority
WHERE (-excluded.lexical_score,excluded.matched_label,
       excluded.source_shard,excluded.match_priority)
    < (-matches.lexical_score,matches.matched_label,
       matches.source_shard,matches.match_priority)
"""
_ORDER = "m.lexical_score DESC,m.entity_id,m.matched_label,m.source_shard,m.match_priority"


def canonical_name_is_materializable(value: str) -> bool:
    """Match the final Catalog-v2 ``trim(canonical_name) != ''`` rule.

    SQLite's default trim removes U+0020 only. Do not broaden this predicate
    to Python's Unicode-whitespace stripping or rewrite the stored name.
    English/literal/NAME-predicate eligibility is checked by the caller.
    """
    return bool(value.strip(" "))


def _validate_questions_and_bounds(
    questions: Sequence[InferenceQuestion], *, max_candidates_per_query: int,
    anchor_min_tokens: int, anchor_max_tokens: int, omit_stopword_only: bool,
) -> None:
    if type(max_candidates_per_query) is not int or not 1 <= max_candidates_per_query <= 900:
        raise ValueError("max_candidates_per_query must be an integer within [1, 900].")
    if (
        type(anchor_min_tokens) is not int or type(anchor_max_tokens) is not int
        or not 1 <= anchor_min_tokens <= anchor_max_tokens
    ):
        raise ValueError("Anchor token bounds must be integers satisfying 1 <= min <= max.")
    if type(omit_stopword_only) is not bool:
        raise ValueError("omit_stopword_only must be a boolean.")
    seen: set[str] = set()
    for question in questions:
        if (
            not isinstance(question, InferenceQuestion)
            or not isinstance(question.question_id, str) or not question.question_id
            or not isinstance(question.text, str) or not question.text.strip()
        ):
            raise ValueError("Each inference question needs a nonempty string ID and text.")
        if question.question_id in seen:
            raise ValueError("Inference question IDs must be unique.")
        seen.add(question.question_id)


def select_eligible_query_candidates(
    questions: Sequence[InferenceQuestion], records: Iterable[ParquetTripleRecord], *,
    staging_root: str | Path | None = None,
    max_candidates_per_query: int = 50, anchor_min_tokens: int = 1,
    anchor_max_tokens: int = 8, omit_stopword_only: bool = True,
) -> EligibleCandidateSelection:
    """Scan once, retain each MID's best lexical hit, qualify, then take Top-K.

    ``staging_root`` must be an existing directory if supplied. Only the owned
    TemporaryDirectory is removed, including on iterator/SQLite errors. Such
    errors propagate without a partial result. An English canonical name must
    pass the final Catalog-v2 SQLite-trim nonempty rule to establish eligibility;
    non-English or resource-valued names do not. Any qualifying canonical name
    suffices for a MID even if that MID also has empty canonical-name records.

    Name beats alias only after an otherwise identical score/MID/label/shard
    tie. Diagnostic legacy counts model lexical-Top-K-then-filter with this
    deterministic tie rule, not historical source-order-dependent tie replay.
    Resource measurements are separate from deterministic selection evidence.
    """
    started = time.monotonic()
    _validate_questions_and_bounds(
        questions, max_candidates_per_query=max_candidates_per_query,
        anchor_min_tokens=anchor_min_tokens, anchor_max_tokens=anchor_max_tokens,
        omit_stopword_only=omit_stopword_only,
    )
    question_by_id = {question.question_id: question for question in questions}
    questions_by_anchor: dict[str, list[str]] = {}
    for question in questions:
        for anchor in extract_query_anchors(
            question.text, min_tokens=anchor_min_tokens, max_tokens=anchor_max_tokens,
            omit_stopword_only=omit_stopword_only,
        ):
            questions_by_anchor.setdefault(anchor, []).append(question.question_id)
    candidates: dict[str, tuple[LocalCandidateMatch, ...]] = {}
    per_query: dict[str, dict[str, int]] = {}
    input_records = canonical_name_records = matched_label_records = 0
    flush_count = maximum_batch_rows = 0
    pending_canonical: list[tuple[str]] = []
    pending_matches: list[tuple[Any, ...]] = []

    with tempfile.TemporaryDirectory(prefix="xgap-eligible-candidates-", dir=staging_root) as scratch:
        database = Path(scratch) / "candidates.sqlite3"
        connection = sqlite3.connect(database)
        try:
            connection.execute(f"PRAGMA cache_size=-{_CACHE_KIB}")
            connection.execute("PRAGMA temp_store=FILE")
            connection.execute("PRAGMA mmap_size=0")
            cache_size_kib = int(connection.execute("PRAGMA cache_size").fetchone()[0])
            temp_store = int(connection.execute("PRAGMA temp_store").fetchone()[0])
            mmap_size = int(connection.execute("PRAGMA mmap_size").fetchone()[0])
            connection.executescript("""
                CREATE TABLE canonical_entities(
                    entity_id TEXT PRIMARY KEY
                ) WITHOUT ROWID;
                CREATE TABLE matches(
                    question_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    matched_label TEXT NOT NULL,
                    normalized_label TEXT NOT NULL,
                    match_type TEXT NOT NULL,
                    lexical_score REAL NOT NULL,
                    source_shard TEXT NOT NULL,
                    match_priority INTEGER NOT NULL,
                    PRIMARY KEY(question_id,entity_id)
                ) WITHOUT ROWID;
            """)

            def flush_if_needed(*, force: bool = False) -> None:
                nonlocal flush_count, maximum_batch_rows
                buffered = len(pending_canonical) + len(pending_matches)
                maximum_batch_rows = max(maximum_batch_rows, buffered)
                if not buffered or (not force and buffered < _BATCH_ROWS):
                    return
                connection.executemany(
                    "INSERT OR IGNORE INTO canonical_entities(entity_id) VALUES(?)",
                    pending_canonical,
                )
                connection.executemany(_UPSERT_MATCH, pending_matches)
                connection.commit()
                pending_canonical.clear()
                pending_matches.clear()
                flush_count += 1

            for record in records:
                input_records += 1
                subject, predicate, value, language, is_resource = record.triple
                if (
                    predicate not in (NAME_PREDICATE, ALIAS_PREDICATE)
                    or is_resource or language != "en" or _MID.fullmatch(subject) is None
                ):
                    continue
                if not isinstance(value, str):
                    raise ValueError("English literal metadata must contain string values.")
                if predicate == NAME_PREDICATE:
                    canonical_name_records += 1
                    if canonical_name_is_materializable(value):
                        pending_canonical.append((subject,))
                        flush_if_needed()
                label = normalized_label(value)
                matching_questions = questions_by_anchor.get(label, ())
                if not label or not matching_questions:
                    continue
                if not isinstance(record.source_shard, (str, PurePath)):
                    raise ValueError("Matched source shard must be a string or path.")
                shard = str(record.source_shard)
                matched_label_records += 1
                canonical = predicate == NAME_PREDICATE
                for question_id in matching_questions:
                    pending_matches.append((
                        question_id, subject, value, label,
                        "exact_normalized_name" if canonical else "exact_normalized_alias",
                        _existing_lexical_score(question_by_id[question_id].text, label),
                        shard, 0 if canonical else 1,
                    ))
                    flush_if_needed()
            flush_if_needed(force=True)
            connection.execute(
                "CREATE INDEX matches_rank ON matches("
                "question_id,lexical_score DESC,entity_id,matched_label,source_shard,match_priority)"
            )
            connection.commit()
            for question in questions:
                question_id = question.question_id
                count_row = connection.execute(
                    "SELECT count(*),count(c.entity_id) FROM matches m "
                    "LEFT JOIN canonical_entities c ON c.entity_id=m.entity_id "
                    "WHERE m.question_id=?", (question_id,),
                ).fetchone()
                matched_count, eligible_count = (int(value) for value in count_row)
                rows = connection.execute(
                    "SELECT m.entity_id,m.matched_label,m.normalized_label,m.match_type,"
                    "m.lexical_score,m.source_shard FROM matches m "
                    "JOIN canonical_entities c ON c.entity_id=m.entity_id "
                    f"WHERE m.question_id=? ORDER BY {_ORDER} LIMIT ?",
                    (question_id, max_candidates_per_query),
                ).fetchall()
                candidates[question_id] = tuple(
                    LocalCandidateMatch(
                        question_id=question_id, entity_id=row[0], matched_label=row[1],
                        normalized_label=row[2], match_type=row[3], score=float(row[4]),
                        source_shard=row[5], rank=rank,
                    )
                    for rank, row in enumerate(rows, start=1)
                )
                legacy_rows = connection.execute(
                    "SELECT c.entity_id IS NOT NULL FROM matches m "
                    "LEFT JOIN canonical_entities c ON c.entity_id=m.entity_id "
                    f"WHERE m.question_id=? ORDER BY {_ORDER} LIMIT ?",
                    (question_id, max_candidates_per_query),
                ).fetchall()
                legacy_eligible = sum(int(row[0]) for row in legacy_rows)
                selected_count = len(rows)
                per_query[question_id] = {
                    "matched_entity_count": matched_count,
                    "eligible_entity_count": eligible_count,
                    "dropped_without_canonical_count": matched_count - eligible_count,
                    "selected_count": selected_count,
                    "truncated_eligible_count": eligible_count - selected_count,
                    "legacy_topk_dropped_count": len(legacy_rows) - legacy_eligible,
                    "backfilled_count": selected_count - legacy_eligible,
                }
            canonical_entity_count = int(connection.execute(
                "SELECT count(*) FROM canonical_entities"
            ).fetchone()[0])
            spooled_match_count = int(connection.execute("SELECT count(*) FROM matches").fetchone()[0])
            page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
            page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        finally:
            connection.close()
        spool_bytes = database.stat().st_size

    return EligibleCandidateSelection(
        candidates=candidates,
        diagnostics={
            "schema_version": ELIGIBLE_SELECTION_SCHEMA_VERSION,
            "selection_policy": ELIGIBLE_SELECTION_POLICY,
            "gold_inputs": False,
            "per_query": per_query,
            "resource_usage": {
                "input_records": input_records,
                "canonical_name_records": canonical_name_records,
                "matched_label_records": matched_label_records,
                "canonical_entity_count": canonical_entity_count,
                "spooled_match_count": spooled_match_count,
                "flush_count": flush_count,
                "maximum_batch_rows": maximum_batch_rows,
                "batch_row_limit": _BATCH_ROWS,
                "sqlite_cache_size_kib": cache_size_kib,
                "sqlite_temp_store": temp_store,
                "sqlite_mmap_size_bytes": mmap_size,
                "spool_bytes": spool_bytes,
                "sqlite_page_count": page_count,
                "sqlite_page_size": page_size,
                "wall_clock_seconds": time.monotonic() - started,
            },
        },
    )
