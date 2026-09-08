"""Independent read-only audit of a GrailQA query-local catalog.

This module intentionally does not import the catalog producer.  It binds the
pilot population, question-only input, frozen source inventory, content files,
SQLite representation, per-query candidate isolation, and post-construction
reachability evidence without scanning the 32 GB Freebase source again.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
from typing import Any, Mapping, Sequence
import unicodedata

from xgap.experiments.hashing import content_hash


AUDIT_SCHEMA_VERSION = "m13e4-grailqa-local-catalog-evidence-audit-v1"
CATALOG_SCHEMA_VERSION = "m13e1-grailqa-inference-catalog-v2"
LOCAL_CATALOG_SCHEMA_VERSION = "m13e3b-grailqa-local-catalog-v1"
REACHABILITY_SCHEMA_VERSION = "m13e3b4-grailqa-local-reachability-v2"
ENDPOINT_CONTRACT_VERSION = "m13e3b4-relation-endpoint-grounding-v1"
EXPECTED_SOURCE_REPO = "CleverThis/freebase"
EXPECTED_SOURCE_REVISION = "dbb1931c2698295653effe9b980a02ab29f004e0"
EXPECTED_SOURCE_SHARDS = 964
EXPECTED_SOURCE_BYTES = 32_476_432_840
EXPECTED_CATALOG_FILES = (
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
EXPECTED_AUDIT_FILES = (
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
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MID = re.compile(r"^[mg]\.[A-Za-z0-9_-]+$")
_QUESTION_FIELDS = frozenset(
    {"question_id", "text", "schema_version", "source_benchmark_id", "split"}
)
_FORBIDDEN_FIELDS = frozenset(
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


class GrailQALocalCatalogEvidenceError(ValueError):
    """Raised when catalog evidence cannot be audited safely."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular_file(path: Path, *, root: Path, name: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise GrailQALocalCatalogEvidenceError(
            f"{name} must be a regular non-symbolic-link file"
        )
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise GrailQALocalCatalogEvidenceError(f"{name} escapes catalog root") from exc
    return resolved


def _load_json(path: Path, *, root: Path, name: str) -> dict[str, Any]:
    source = _regular_file(path, root=root, name=name)
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise GrailQALocalCatalogEvidenceError(f"{name} is not an object")
    return dict(value)


def _load_jsonl(path: Path, *, root: Path, name: str) -> list[dict[str, Any]]:
    source = _regular_file(path, root=root, name=name)
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        source.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line:
            continue
        value = json.loads(line)
        if not isinstance(value, Mapping):
            raise GrailQALocalCatalogEvidenceError(
                f"{name} line {line_number} is not an object"
            )
        rows.append(dict(value))
    return rows


def _tree_snapshot(root: Path) -> dict[str, tuple[int, str]]:
    snapshot: dict[str, tuple[int, str]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise GrailQALocalCatalogEvidenceError(
                f"catalog tree contains symbolic link: {path.relative_to(root)}"
            )
        if path.is_file():
            snapshot[path.relative_to(root).as_posix()] = (
                path.stat().st_size,
                _sha256_file(path),
            )
    return snapshot


def _normalized_label(value: str) -> str:
    text = unicodedata.normalize("NFKC", value)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = text.replace("_", " ").replace(".", " ").replace("/", " ")
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _safe_source_shard(value: object) -> bool:
    path = PurePosixPath(str(value))
    return bool(str(value)) and not path.is_absolute() and ".." not in path.parts


def _exact_ids(values: Sequence[object], expected: Sequence[str]) -> bool:
    observed = [str(item) for item in values]
    return observed == list(expected) and len(set(observed)) == len(observed)


def audit_grailqa_local_catalog(
    *,
    catalog_root: str | Path,
    repo_root: str | Path,
    source_manifest_path: str | Path,
    expected_builder_commit: str,
) -> dict[str, Any]:
    """Reconstruct a pilot150 catalog and reachability identity read-only."""

    root_input = Path(catalog_root)
    repo_input = Path(repo_root)
    source_manifest_input = Path(source_manifest_path)
    if root_input.is_symlink():
        raise GrailQALocalCatalogEvidenceError(
            "catalog_root must be a non-symbolic-link directory"
        )
    if repo_input.is_symlink():
        raise GrailQALocalCatalogEvidenceError(
            "repo_root must be a non-symbolic-link directory"
        )
    if source_manifest_input.is_symlink():
        raise GrailQALocalCatalogEvidenceError(
            "source_manifest must be a regular non-symbolic-link file"
        )
    root = root_input.resolve()
    repo = repo_input.resolve()
    source_manifest = source_manifest_input.resolve()
    if not root.is_dir():
        raise GrailQALocalCatalogEvidenceError("catalog_root does not exist")
    if not repo.is_dir():
        raise GrailQALocalCatalogEvidenceError("repo_root does not exist")
    if not source_manifest.is_file():
        raise GrailQALocalCatalogEvidenceError("source_manifest does not exist")
    if _COMMIT.fullmatch(expected_builder_commit) is None:
        raise GrailQALocalCatalogEvidenceError(
            "expected_builder_commit must be exact 40-hex"
        )
    before = _tree_snapshot(root)
    checks: list[dict[str, Any]] = []

    def check(check_id: str, passed: bool, detail: Any = None) -> None:
        checks.append(
            {"check_id": check_id, "passed": bool(passed), "detail": detail}
        )

    manifest = _load_json(root / "manifest.json", root=root, name="manifest")
    reachability = _load_json(
        root / "audit_summary.json", root=root, name="reachability summary"
    )
    pilot_root = repo / "datasets/grailqa_pilot_v1"
    pilot = _load_json(
        pilot_root / "pilot_ids.json", root=repo, name="pilot selection"
    )
    artifact_manifest = _load_json(
        pilot_root / "artifact_manifest.json",
        root=repo,
        name="pilot artifact manifest",
    )
    expected_ids = tuple(str(item) for item in pilot.get("question_ids", ()))
    inference_path = pilot_root / "inference_questions.jsonl"
    questions = _load_jsonl(
        inference_path,
        root=repo,
        name="inference questions",
    )
    question_ids = tuple(str(item.get("question_id", "")) for item in questions)
    question_text = {
        str(item.get("question_id", "")): str(item.get("text", ""))
        for item in questions
    }

    check("population.pilot_size", len(expected_ids) == 150, len(expected_ids))
    check("population.pilot_unique", len(set(expected_ids)) == 150)
    check("population.inference_exact", _exact_ids(question_ids, expected_ids))
    check(
        "population.manifest_exact",
        _exact_ids(tuple(manifest.get("question_ids", ())), expected_ids),
    )
    check(
        "inference.fields_gold_blind",
        all(
            not (_FORBIDDEN_FIELDS & set(item))
            and set(item) <= _QUESTION_FIELDS
            and bool(str(item.get("question_id", "")))
            and bool(str(item.get("text", "")).strip())
            for item in questions
        ),
    )
    expected_inference = (
        artifact_manifest.get("artifacts", {})
        .get("inference_questions.jsonl", {})
        .get("sha256")
    )
    inference_sha = _sha256_file(inference_path)
    check("inference.artifact_sha256", expected_inference == inference_sha)
    check(
        "manifest.schema",
        manifest.get("schema_version") == CATALOG_SCHEMA_VERSION
        and manifest.get("local_catalog_schema_version")
        == LOCAL_CATALOG_SCHEMA_VERSION,
    )
    check("manifest.complete", manifest.get("status") == "complete")
    check("manifest.workload", manifest.get("workload_name") == "pilot150")
    check("manifest.query_filter", manifest.get("requires_query_entity_filter") is True)
    check("manifest.gold_blind", manifest.get("gold_used_for_construction") is False)
    construction = manifest.get("construction", {})
    check(
        "manifest.builder_commit",
        isinstance(construction, Mapping)
        and construction.get("builder_git_commit") == expected_builder_commit,
    )
    check(
        "manifest.question_set_hash",
        manifest.get("question_set_sha256") == content_hash(list(expected_ids)),
    )
    question_text_body = [
        {"question_id": question_id, "text": question_text[question_id]}
        for question_id in expected_ids
        if question_id in question_text
    ]
    check(
        "manifest.question_text_hash",
        len(question_text_body) == 150
        and manifest.get("question_text_sha256") == content_hash(question_text_body),
    )
    sources = manifest.get("sources", {})
    source = sources.get("freebase_archival_parquet", {}) if isinstance(sources, Mapping) else {}
    check(
        "source.identity",
        isinstance(source, Mapping)
        and source.get("repo_id") == EXPECTED_SOURCE_REPO
        and source.get("revision") == EXPECTED_SOURCE_REVISION
        and source.get("resolved_parquet_revision") == EXPECTED_SOURCE_REVISION,
    )
    check(
        "source.inventory",
        isinstance(source, Mapping)
        and source.get("shard_count") == EXPECTED_SOURCE_SHARDS
        and source.get("size_bytes") == EXPECTED_SOURCE_BYTES,
    )
    source_sha = _sha256_file(source_manifest)
    check(
        "source.manifest_sha256",
        isinstance(source, Mapping)
        and source.get("source_manifest_sha256") == source_sha,
    )

    file_hashes = manifest.get("file_hashes", {})
    check(
        "catalog.file_hash_keys",
        isinstance(file_hashes, Mapping)
        and set(file_hashes) == set(EXPECTED_CATALOG_FILES),
    )
    for name in EXPECTED_CATALOG_FILES:
        path = root / name
        actual = _sha256_file(_regular_file(path, root=root, name=name))
        check(
            f"catalog.file_hash.{name}",
            isinstance(file_hashes, Mapping) and file_hashes.get(name) == actual,
        )
    if isinstance(file_hashes, Mapping):
        catalog_identity = {
            "schema_version": LOCAL_CATALOG_SCHEMA_VERSION,
            "source_manifest_sha256": source_sha,
            "question_text_sha256": manifest.get("question_text_sha256"),
            "content_file_hashes": {
                key: value
                for key, value in file_hashes.items()
                if key != "catalog.sqlite3"
            },
        }
        check(
            "catalog.identity",
            content_hash(catalog_identity) == manifest.get("catalog_hash"),
        )

    local_queries = _load_jsonl(
        root / "local_queries.jsonl", root=root, name="local queries"
    )
    candidate_rows = _load_jsonl(
        root / "query_entity_candidates.jsonl",
        root=root,
        name="query entity candidates",
    )
    check(
        "local_queries.exact_population",
        _exact_ids([item.get("question_id") for item in local_queries], expected_ids),
    )
    check(
        "local_queries.text_and_hash",
        all(
            item.get("text") == question_text.get(str(item.get("question_id")))
            and item.get("question_hash")
            == hashlib.sha256(str(item.get("text", "")).encode("utf-8")).hexdigest()
            for item in local_queries
        ),
    )
    candidate_tuples: list[tuple[Any, ...]] = []
    candidates_by_question: dict[str, list[dict[str, Any]]] = {
        question_id: [] for question_id in expected_ids
    }
    for row in candidate_rows:
        question_id = str(row.get("question_id", ""))
        candidates_by_question.setdefault(question_id, []).append(row)
        candidate_tuples.append(
            (
                question_id,
                str(row.get("entity_id", "")),
                int(row.get("rank", -1)),
                float(row.get("lexical_score", float("nan"))),
                str(row.get("matched_label", "")),
                str(row.get("normalized_label", "")),
                str(row.get("match_type", "")),
                str(row.get("source_shard", "")),
            )
        )
    candidate_questions = set(candidates_by_question) - set(expected_ids)
    check("candidates.question_isolation", not candidate_questions, sorted(candidate_questions))
    check(
        "candidates.contract",
        all(
            _MID.fullmatch(str(item.get("entity_id", ""))) is not None
            and item.get("match_type")
            in {"exact_normalized_name", "exact_normalized_alias"}
            and item.get("normalized_label")
            == _normalized_label(str(item.get("matched_label", "")))
            and f" {item.get('normalized_label')} "
            in (
                " "
                + _normalized_label(
                    question_text.get(str(item.get("question_id")), "")
                )
                + " "
            )
            and _safe_source_shard(item.get("source_shard"))
            for item in candidate_rows
        ),
    )
    check(
        "candidates.rank_and_bound",
        all(
            [int(item.get("rank", -1)) for item in values]
            == list(range(1, len(values) + 1))
            and len(values) <= 50
            for values in candidates_by_question.values()
        ),
    )
    check(
        "candidates.unique_per_query",
        all(
            len({str(item.get("entity_id")) for item in values}) == len(values)
            for values in candidates_by_question.values()
        ),
    )

    database = _regular_file(
        root / "catalog.sqlite3", root=root, name="catalog database"
    )
    connection = sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True)
    try:
        quick_check = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        indexes = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        check("sqlite.quick_check", quick_check == ["ok"], quick_check)
        check(
            "sqlite.required_tables",
            {
                "entities",
                "entity_aliases",
                "entity_types",
                "terms",
                "term_aliases",
                "entity_search",
                "local_queries",
                "query_entity_candidates",
            }
            <= tables,
        )
        check(
            "sqlite.required_indexes",
            {
                "entity_canonical_name_idx",
                "entity_alias_normalized_idx",
                "entity_types_entity_idx",
                "entity_types_type_idx",
                "term_alias_term_idx",
                "term_alias_normalized_idx",
                "query_entity_candidate_idx",
            }
            <= indexes,
        )
        sqlite_queries = list(
            connection.execute(
                "SELECT question_id,question_hash,question_text FROM local_queries "
                "ORDER BY rowid"
            )
        )
        json_queries = [
            (item["question_id"], item["question_hash"], item["text"])
            for item in local_queries
        ]
        check("sqlite.local_queries_exact", sqlite_queries == json_queries)
        sqlite_candidates = list(
            connection.execute(
                "SELECT question_id,entity_id,rank,lexical_score,matched_label,"
                "normalized_label,match_type,source_shard "
                "FROM query_entity_candidates ORDER BY question_id,rank,entity_id"
            )
        )
        check(
            "sqlite.candidates_exact",
            sqlite_candidates
            == sorted(candidate_tuples, key=lambda item: (item[0], item[2], item[1])),
        )
        orphan_count = int(
            connection.execute(
                "SELECT count(*) FROM query_entity_candidates q "
                "LEFT JOIN local_queries l ON l.question_id=q.question_id "
                "LEFT JOIN entities e ON e.id=q.entity_id "
                "LEFT JOIN entity_aliases a ON a.entity_id=q.entity_id "
                "AND a.alias=q.matched_label "
                "WHERE l.question_id IS NULL OR e.id IS NULL OR a.entity_id IS NULL"
            ).fetchone()[0]
        )
        check("sqlite.no_candidate_orphans", orphan_count == 0, orphan_count)
        counts = {
            name: int(connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0])
            for name in (
                "entities",
                "entity_aliases",
                "entity_types",
                "terms",
                "local_queries",
                "query_entity_candidates",
            )
        }
    finally:
        connection.close()
    declared_counts = manifest.get("counts", {})
    check(
        "manifest.counts",
        isinstance(declared_counts, Mapping)
        and declared_counts.get("questions") == counts["local_queries"] == 150
        and declared_counts.get("entities") == counts["entities"]
        and declared_counts.get("unique_candidate_mids") == counts["entities"]
        and declared_counts.get("entity_aliases") == counts["entity_aliases"]
        and declared_counts.get("entity_types") == counts["entity_types"]
        and declared_counts.get("query_candidate_assignments")
        == counts["query_entity_candidates"]
        and declared_counts.get("types", 0) + declared_counts.get("relations", 0)
        == counts["terms"],
        {"declared": declared_counts, "observed": counts},
    )

    check("reachability.schema", reachability.get("schema_version") == REACHABILITY_SCHEMA_VERSION)
    check("reachability.question_count", reachability.get("question_count") == 150)
    check("reachability.prompt_limit", reachability.get("prompt_limit") == 4)
    check(
        "reachability.catalog_hash",
        reachability.get("catalog_hash") == manifest.get("catalog_hash"),
    )
    check(
        "reachability.gold_boundary",
        reachability.get("gold_used_for_construction") is False
        and reachability.get("gold_usage")
        == "evaluation_only_after_retrieval_persisted",
    )
    gate = reachability.get("gate", {})
    check(
        "reachability.gate",
        isinstance(gate, Mapping)
        and gate.get("passed") is True
        and gate.get("minimum_joint_ratio") == 0.20
        and gate.get("prompt_limit") == 4
        and float(gate.get("observed_joint_ratio", -1.0)) >= 0.20
        and reachability.get("live_preflight_allowed") is True,
    )
    endpoint = reachability.get("relation_endpoint_grounding", {})
    check(
        "reachability.endpoint_contract",
        isinstance(endpoint, Mapping)
        and endpoint.get("contract_version") == ENDPOINT_CONTRACT_VERSION,
    )
    check(
        "reachability.self_hash",
        reachability.get("audit_hash")
        == content_hash(
            {key: value for key, value in reachability.items() if key != "audit_hash"}
        ),
    )
    reachability_hashes = reachability.get("artifact_hashes", {})
    check(
        "reachability.file_hash_keys",
        isinstance(reachability_hashes, Mapping)
        and set(reachability_hashes) == set(EXPECTED_AUDIT_FILES),
    )
    for name in EXPECTED_AUDIT_FILES:
        path = _regular_file(root / name, root=root, name=name)
        check(
            f"reachability.file_hash.{name}",
            isinstance(reachability_hashes, Mapping)
            and reachability_hashes.get(name) == _sha256_file(path),
        )
    reachability_rows = _load_jsonl(
        root / "reachability.jsonl", root=root, name="reachability rows"
    )
    retrieval_rows = _load_jsonl(
        root / "retrieval.jsonl", root=root, name="retrieval rows"
    )
    check(
        "reachability.rows_exact_population",
        _exact_ids(
            [item.get("question_id") for item in reachability_rows], expected_ids
        ),
    )
    check(
        "retrieval.rows_exact_population",
        _exact_ids([item.get("question_id") for item in retrieval_rows], expected_ids),
    )
    check(
        "reachability.row_endpoint_contract",
        all(
            isinstance(item.get("relation_endpoint_grounding"), Mapping)
            and item["relation_endpoint_grounding"].get("contract_version")
            == ENDPOINT_CONTRACT_VERSION
            for item in reachability_rows
        ),
    )

    after = _tree_snapshot(root)
    check("catalog.non_mutating_audit", before == after)
    failed = [item["check_id"] for item in checks if not item["passed"]]
    body: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "catalog_root": str(root),
        "expected_builder_commit": expected_builder_commit,
        "catalog_hash": manifest.get("catalog_hash"),
        "reachability_audit_hash": reachability.get("audit_hash"),
        "question_count": len(expected_ids),
        "check_count": len(checks),
        "failed_check_ids": failed,
        "checks": checks,
        "run_tree_mutated": before != after,
        "source_verification_boundary": {
            "source_manifest_sha256": source_sha,
            "source_inventory_bound": True,
            "freebase_bytes_rescanned_by_auditor": 0,
        },
        "external_call_counts": {
            "llm_calls": 0,
            "backend_calls": 0,
            "ontology_service_calls": 0,
        },
        "claim_boundary": {
            "independent_catalog_reconstruction": True,
            "catalog_construction_gold_blind": not failed,
            "reachability_uses_gold_for_evaluation_only": not failed,
            "authorizes_model_execution": False,
            "paper_result": False,
        },
        "success": not failed,
        "paper_result": False,
    }
    return {**body, "audit_sha256": content_hash(body)}


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"audit output exists: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-root", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--expected-builder-commit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    root = Path(args.catalog_root).resolve()
    if output == root or root in output.parents:
        print(
            json.dumps(
                {
                    "status": "configuration_error",
                    "error": "audit output must be outside the immutable catalog tree",
                }
            )
        )
        return 2
    try:
        audit = audit_grailqa_local_catalog(
            catalog_root=args.catalog_root,
            repo_root=args.repo_root,
            source_manifest_path=args.source_manifest,
            expected_builder_commit=args.expected_builder_commit,
        )
        _write_json_exclusive(output, audit)
    except (
        FileExistsError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        sqlite3.Error,
    ) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps({"status": "success", **audit}, sort_keys=True))
    return 0 if audit["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
