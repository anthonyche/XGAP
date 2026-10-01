"""Development-only paired comparison of frozen v1 and eligibility-first catalogs.

Both real retrievals are persisted before evaluation references are read. This
module does not issue an old reachability admission or authorize model execution.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence

from xgap.experiments.grailqa_catalog import sha256_file
from xgap.experiments.grailqa_catalog_v2 import GrailQAInferenceCatalogV2
from xgap.experiments.grailqa_local_catalog import (
    ELIGIBLE_CANDIDATE_SELECTION,
    LOCAL_CATALOG_SCHEMA_VERSION,
    LOCAL_ELIGIBLE_CATALOG_SCHEMA_VERSION,
    load_inference_questions,
    validate_local_catalog,
)
from xgap.experiments.grailqa_reachability import audit_reachability, load_catalog_universe
from xgap.experiments.hashing import content_hash
from xgap.llm.parser import parse_path_pattern_query
from xgap.pattern.typecheck import type_check_path_pattern


COMPARISON_SCHEMA_VERSION = "m13e4-grailqa-catalog-comparison-v1"
_SCHEMA_FILES = (
    "ontology.yaml", "terms.jsonl", "type_aliases.jsonl", "relation_aliases.jsonl",
    "relation_metadata.jsonl", "reverse_properties.json",
)
_KINDS = ("entity", "relation", "type", "effective_type", "joint")


def compare_local_catalogs(
    *,
    legacy_catalog_root: str | Path,
    eligible_catalog_root: str | Path,
    inference_questions_path: str | Path,
    question_ids: Sequence[str],
    reference_interpretations_path: str | Path,
    output_root: str | Path,
    top_k: int = 20,
    prompt_limit: int = 4,
) -> dict[str, Any]:
    """Compare the same complete question population; preserve failures and inputs.

    Catalog provenance is checked against published manifests, not by rescanning
    the source. Reference interpretation coverage is not an answer-quality score.
    Existing output and symlink paths are refused; failed partial outputs remain.
    """
    if isinstance(question_ids, (str, bytes)):
        raise ValueError("question_ids must be an explicit sequence, not a string.")
    ids = tuple(question_ids)
    if not ids or any(not isinstance(item, str) or not item.strip() for item in ids):
        raise ValueError("question_ids must contain nonempty string IDs.")
    if len(set(ids)) != len(ids):
        raise ValueError("question_ids must be unique.")
    if type(top_k) is not int or not 1 <= top_k <= 900:
        raise ValueError("top_k must be an integer within [1, 900].")
    if type(prompt_limit) is not int or not 1 <= prompt_limit <= top_k:
        raise ValueError("prompt_limit must be an integer within [1, top_k].")
    roots = {"legacy": _safe_path(legacy_catalog_root),
             "eligible": _safe_path(eligible_catalog_root)}
    questions_path = _safe_path(inference_questions_path)
    references_path = _safe_path(reference_interpretations_path)
    output = _safe_path(output_root)
    for path in roots.values():
        if not path.is_dir():
            raise FileNotFoundError(f"Catalog input directory is missing: {path}")
    for path in (questions_path, references_path):
        if not path.is_file():
            raise FileNotFoundError(f"Input file is missing: {path}")
    if _overlap(roots["legacy"], roots["eligible"]):
        raise ValueError("Input catalog directories must be distinct and disjoint.")
    if any(_overlap(output, path) for path in (*roots.values(), questions_path, references_path)):
        raise ValueError("Output must not overlap any input path.")
    if output.exists():
        raise FileExistsError(f"Comparison requires a fresh output directory: {output}")
    output.mkdir(parents=True, exist_ok=False)
    stage = "input_validation"
    try:
        questions = load_inference_questions(questions_path, question_ids=ids)
        question_rows = [{"question_id": item.question_id, "text": item.text} for item in questions]
        manifests: dict[str, Any] = {}
        entities: dict[str, dict[str, list[str]]] = {}
        snapshots: dict[str, dict[str, str]] = {}
        for variant, root in roots.items():
            _check_catalog_files(root)
            validate_local_catalog(root)
            manifests[variant] = _read_json(root / "manifest.json")
            entities[variant] = _catalog_entities(root, question_rows)
            snapshots[variant] = _catalog_snapshot(root, manifests[variant])
        binding = _bind_inputs(manifests, question_rows, questions_path)
        questions_hash = sha256_file(questions_path)
        request = {
            "schema_version": COMPARISON_SCHEMA_VERSION,
            "created_at": _now(), "question_ids": list(ids), "question_count": len(ids),
            "top_k": top_k, "prompt_limit": prompt_limit,
            "relation_slots": 3, "expansion_hops": 1,
            "catalog_roots": {name: str(root) for name, root in roots.items()},
            "input_binding": binding, "inference_questions_sha256": questions_hash,
            "paper_result": False, "live_execution_authorized": False,
            "gold_used_for_retrieval": False,
        }
        _write_json(output / "comparison_request.json", request)
        _write_jsonl(output / "inference_questions.jsonl", question_rows)
        stage = "retrieval"
        retrievals: dict[str, list[dict[str, Any]]] = {name: [] for name in roots}
        with (output / "retrieval.jsonl").open("x", encoding="utf-8") as handle:
            for variant, root in roots.items():
                catalog = GrailQAInferenceCatalogV2.load(root)
                for question in questions:
                    row = catalog.retrieve(question.question_id, question.text, top_k=top_k,
                                           relation_slots=3, expansion_hops=1).to_dict()
                    retrievals[variant].append(row)
                    handle.write(json.dumps({"variant": variant, "retrieval": row},
                                            sort_keys=True, allow_nan=False) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
        _verify_inputs(roots, manifests, snapshots, questions_path, questions_hash)
        seal = {
            "schema_version": "m13e4-grailqa-catalog-retrieval-seal-v1",
            "sealed_at": _now(), "question_ids": list(ids), "input_binding": binding,
            "catalog_hashes": {name: item["catalog_hash"] for name, item in manifests.items()},
            "file_hashes": {name: sha256_file(output / name) for name in
                            ("comparison_request.json", "inference_questions.jsonl", "retrieval.jsonl")},
            "retrieval_row_count": 2 * len(ids), "reference_content_read": False,
            "backend_calls": 0, "llm_calls": 0, "paper_result": False,
        }
        seal["retrieval_seal_sha256"] = content_hash(seal)
        _write_json(output / "retrieval_seal.json", seal)

        # First reference content access, strictly after both retrievals and seal.
        stage = "evaluation"
        reference_hash = sha256_file(references_path)
        references = _read_references(references_path, ids)
        audits = {
            name: audit_reachability(references=references, retrieval_rows=retrievals[name],
                                     catalog=load_catalog_universe(root),
                                     catalog_entities_by_question=entities[name],
                                     k_values=(top_k,), prompt_limit=prompt_limit)
            for name, root in roots.items()
        }
        _verify_inputs(roots, manifests, snapshots, questions_path, questions_hash)
        if sha256_file(references_path) != reference_hash:
            raise ValueError("Evaluation references changed during comparison.")
        for name, expected in seal["file_hashes"].items():
            if sha256_file(output / name) != expected:
                raise ValueError(f"Sealed inference artifact changed: {name}")
        if _read_json(output / "retrieval_seal.json") != seal:
            raise ValueError("Retrieval seal changed during evaluation.")
        report = {
            "schema_version": COMPARISON_SCHEMA_VERSION, "status": "success",
            "question_ids": list(ids), "question_count": len(ids),
            "top_k": top_k, "prompt_limit": prompt_limit, "input_binding": binding,
            "reference_interpretations_sha256": reference_hash,
            "retrieval_seal_sha256": seal["retrieval_seal_sha256"],
            "variants": {name: {
                "catalog_hash": manifests[name]["catalog_hash"],
                "local_catalog_schema_version": manifests[name]["local_catalog_schema_version"],
                "reachability": audits[name],
                "resource_manifest": {key: manifests[name].get(key) for key in
                                      ("construction", "scan", "database_size_bytes", "counts")},
            } for name in roots},
            "coverage_changes": _coverage_changes(audits, top_k),
            "entity_changes": _entity_changes(ids, entities, retrievals, prompt_limit),
            "gold_usage": "evaluation_only_after_both_retrievals_sealed",
            "backend_calls": 0, "llm_calls": 0, "automatic_retries": 0,
            "paper_result": False, "live_execution_authorized": False,
            "limitations": [
                "Development comparison, not a historical reachability admission.",
                "Coverage of reference components is not generated-query or answer accuracy.",
                "Source provenance is manifest-bound; this comparison does not rescan Freebase.",
                "Resource fields are original construction observations, not paired speedup evidence.",
            ],
        }
        report["comparison_sha256"] = content_hash(report)
        stage = "publication"
        _write_json(output / "comparison.json", report)
        _write_json(output / "run_status.json", {
            "schema_version": COMPARISON_SCHEMA_VERSION, "status": "success",
            "comparison_sha256": report["comparison_sha256"], "paper_result": False,
        })
        return report
    except Exception as exc:
        failure = {
            "schema_version": COMPARISON_SCHEMA_VERSION, "status": "failed",
            "failed_stage": stage, "error_type": type(exc).__name__, "error": str(exc),
            "paper_result": False, "live_execution_authorized": False,
        }
        try:
            _write_json(output / "run_status.json", failure)
        except OSError:
            # A storage failure is still raised, never transformed into success.
            pass
        try:
            _write_json(output / "comparison_failure.json", failure)
        except OSError:
            pass
        raise


def _safe_path(value: str | Path) -> Path:
    path = Path(value).expanduser().absolute()
    if ".." in path.parts:
        raise ValueError("Parent traversal is not supported in comparison paths.")
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError(f"Symlink input/output paths are not permitted: {path}")
    return path


def _overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _check_catalog_files(root: Path) -> None:
    manifest_path = _safe_path(_safe_path(root) / "manifest.json")
    if not manifest_path.is_file():
        raise ValueError("Catalog manifest must be a regular file.")
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError("Catalog manifest must be a regular JSON object file.")
    hashes = manifest.get("file_hashes")
    if not isinstance(hashes, dict):
        raise ValueError("Catalog manifest requires file hashes.")
    for name in ("manifest.json", *hashes):
        if not isinstance(name, str) or Path(name).name != name or name in {".", ".."}:
            raise ValueError("Catalog artifact names must be direct children.")
        path = _safe_path(root / name)
        if not path.is_file():
            raise ValueError(f"Catalog artifact is not a regular file: {name}")


def _catalog_snapshot(root: Path, manifest: Mapping[str, Any]) -> dict[str, str]:
    return {name: sha256_file(root / name) for name in ("manifest.json", *manifest["file_hashes"])}


def _catalog_entities(root: Path, questions: Sequence[Mapping[str, str]]) -> dict[str, list[str]]:
    expected = {row["question_id"]: row["text"] for row in questions}
    connection = sqlite3.connect(f"file:{root / 'catalog.sqlite3'}?mode=ro", uri=True)
    try:
        actual = {str(qid): str(text) for qid, text in
                  connection.execute("SELECT question_id,question_text FROM local_queries")}
        if actual != expected:
            raise ValueError("Catalog question set/text must exactly match requested questions.")
        result: dict[str, list[str]] = {qid: [] for qid in expected}
        for qid, mid in connection.execute(
            "SELECT question_id,entity_id FROM query_entity_candidates ORDER BY question_id,rank,entity_id"
        ):
            result[str(qid)].append(str(mid))
        return result
    finally:
        connection.close()


def _bind_inputs(manifests: Mapping[str, Any], rows: list[dict[str, str]], questions: Path) -> dict[str, Any]:
    old, new = manifests["legacy"], manifests["eligible"]
    if old.get("local_catalog_schema_version") != LOCAL_CATALOG_SCHEMA_VERSION:
        raise ValueError("Legacy input must use the original local catalog v1 schema.")
    if new.get("local_catalog_schema_version") != LOCAL_ELIGIBLE_CATALOG_SCHEMA_VERSION:
        raise ValueError("Eligible input must use the separate local catalog v2 schema.")
    if new.get("candidate_selection") != ELIGIBLE_CANDIDATE_SELECTION:
        raise ValueError("Eligible input has the wrong candidate selection policy.")
    ids = [row["question_id"] for row in rows]
    for item in manifests.values():
        if item.get("question_ids") != ids or item.get("question_set_sha256") != content_hash(ids):
            raise ValueError("Catalog question IDs/order differ from the requested population.")
        if item.get("question_text_sha256") != content_hash(rows):
            raise ValueError("Catalog question text hash differs from inference input.")
        if item.get("sources", {}).get("inference_questions", {}).get("sha256") != sha256_file(questions):
            raise ValueError("Catalog inference-question source file hash differs.")
    for field in ("ontology_hash", "anchor_extraction"):
        if field not in old or old[field] != new.get(field):
            raise ValueError(f"Catalogs differ in frozen field: {field}")
    for field in ("freebase_archival_parquet", "ontology"):
        if not old.get("sources", {}).get(field) or old["sources"][field] != new.get("sources", {}).get(field):
            raise ValueError(f"Catalogs differ in source provenance: {field}")
    source_hash = old["sources"]["freebase_archival_parquet"].get("source_manifest_sha256")
    if (not isinstance(source_hash, str) or len(source_hash) != 64
            or any(character not in "0123456789abcdef" for character in source_hash)):
        raise ValueError("Source manifest hash is missing or invalid.")
    for name in _SCHEMA_FILES:
        if name not in old["file_hashes"] or old["file_hashes"][name] != new["file_hashes"].get(name):
            raise ValueError(f"Catalogs differ in schema/ontology content: {name}")
    return {"source_manifest_sha256": source_hash, "ontology_hash": old["ontology_hash"],
            "question_text_sha256": content_hash(rows), "question_set_sha256": content_hash(ids),
            "anchor_extraction": old["anchor_extraction"],
            "schema_file_hashes": {name: old["file_hashes"][name] for name in _SCHEMA_FILES}}


def _verify_inputs(roots: Mapping[str, Path], manifests: Mapping[str, Any],
                   snapshots: Mapping[str, Any], questions: Path, expected: str) -> None:
    for name, root in roots.items():
        _check_catalog_files(root)
        if _catalog_snapshot(root, manifests[name]) != snapshots[name]:
            raise ValueError(f"Catalog input changed during comparison: {name}")
    if sha256_file(_safe_path(questions)) != expected:
        raise ValueError("Inference questions changed during comparison.")


def _read_references(path: Path, question_ids: Sequence[str]) -> list[dict[str, Any]]:
    requested = set(question_ids)
    selected: dict[str, dict[str, Any]] = {}
    with _safe_path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("Evaluation references must contain JSON objects.")
            qid = str(row.get("question_id", ""))
            if qid in requested:
                if qid in selected:
                    raise ValueError(f"Duplicate evaluation reference: {qid}")
                pattern = row.get("pattern_query")
                if not isinstance(pattern, dict):
                    raise ValueError(f"Evaluation reference has no valid pattern query: {qid}")
                # The historical coverage extractor is permissive for unknown
                # operators. Refuse malformed references here rather than
                # reporting an empty requirement set as a coverage gain.
                type_check_path_pattern(parse_path_pattern_query(pattern))
                selected[qid] = row
    if set(selected) != requested:
        raise ValueError("Evaluation references do not cover the complete selected population.")
    return [selected[qid] for qid in question_ids]


def _coverage_changes(audits: Mapping[str, Any], top_k: int) -> dict[str, Any]:
    pairs = list(zip(audits["legacy"]["rows"], audits["eligible"]["rows"], strict=True))
    result: dict[str, Any] = {}
    for stage in ("catalog", "retrieval", "deployed_prompt"):
        result[stage] = {}
        for kind in _KINDS:
            gained, lost, both, neither = [], [], [], []
            for old, new in pairs:
                left, right = old[stage], new[stage]
                if stage == "retrieval":
                    left, right = left[str(top_k)], right[str(top_k)]
                a, b = left[kind]["reachable"], right[kind]["reachable"]
                (both if a and b else lost if a else gained if b else neither).append(old["question_id"])
            result[stage][kind] = {
                "legacy_count": len(both) + len(lost), "eligible_count": len(both) + len(gained),
                "denominator": len(pairs), "legacy_ratio": (len(both) + len(lost)) / len(pairs),
                "eligible_ratio": (len(both) + len(gained)) / len(pairs),
                "gained_question_ids": gained, "lost_question_ids": lost,
                "unchanged_reachable_question_ids": both, "unchanged_unreachable_question_ids": neither,
            }
    return result


def _entity_changes(ids: Sequence[str], entities: Mapping[str, Any],
                    retrievals: Mapping[str, Any], prompt_limit: int) -> list[dict[str, Any]]:
    retrieved = {name: {row["question_id"]: [item["id"] for item in row["entity_candidates"]]
                        for row in rows} for name, rows in retrievals.items()}
    rows = []
    for qid in ids:
        row: dict[str, Any] = {"question_id": qid}
        for stage in ("catalog", "retrieval", "deployed_prompt"):
            values = entities if stage == "catalog" else retrieved
            old, new = values["legacy"][qid], values["eligible"][qid]
            if stage == "deployed_prompt":
                old, new = old[:prompt_limit], new[:prompt_limit]
            row[stage] = {"legacy_ids": old, "eligible_ids": new,
                          "added_ids": sorted(set(new) - set(old)),
                          "removed_ids": sorted(set(old) - set(new))}
        rows.append(row)
    return rows


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-catalog-root", required=True)
    parser.add_argument("--eligible-catalog-root", required=True)
    parser.add_argument("--inference-questions", required=True)
    parser.add_argument("--question-ids", required=True, help="Explicit comma-separated question IDs, in frozen order.")
    parser.add_argument("--reference-interpretations", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--prompt-limit", type=int, default=4)
    args = parser.parse_args(argv)
    try:
        report = compare_local_catalogs(
            legacy_catalog_root=args.legacy_catalog_root, eligible_catalog_root=args.eligible_catalog_root,
            inference_questions_path=args.inference_questions, question_ids=args.question_ids.split(","),
            reference_interpretations_path=args.reference_interpretations, output_root=args.output_root,
            top_k=args.top_k, prompt_limit=args.prompt_limit,
        )
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc), "paper_result": False}))
        return 1
    print(json.dumps({"status": "success", "comparison_sha256": report["comparison_sha256"],
                      "question_count": report["question_count"], "paper_result": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
