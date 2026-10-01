"""Restore selected frozen pilot files from verified public sources, offline.

This is INT input recovery, not a new pilot, catalog build or evaluation.
No question selection, ambiguity expansion, model, fact scan or backend call.
The original manifest must match every produced byte before use.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

from xgap.backends import registry
from xgap.backends.mapping import RdfBackendMapping
from xgap.experiments.grailqa_audit import DATASET_FILES, load_ontology_resources
from xgap.experiments.grailqa_pilot import _load_gold_questions, _write_json, _write_jsonl
from xgap.experiments.grailqa_v2 import (
    build_backend_mapping, convert_question_v2, normalize_answers,
    normalize_ontology, yaml_text,
)


REPO = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def restore(dataset_root: Path, ontology_root: Path, output: Path) -> dict:
    frozen = REPO / "datasets/grailqa_pilot_v1"
    manifest_path = frozen / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    ids_path = frozen / "pilot_ids.json"
    if sha256(ids_path) != manifest["artifacts"][ids_path.name]["sha256"]:
        raise ValueError("Original pilot ID file hash mismatch")
    ids = json.loads(ids_path.read_text())["question_ids"]
    if len(ids) != 150 or len(set(ids)) != 150:
        raise ValueError("Expected the original 150 unique IDs, without reselection")
    sources = {}
    for split in ("train", "dev"):
        path = dataset_root / DATASET_FILES[split]
        actual = sha256(path)
        if actual != manifest["source_hashes"][split]:
            raise ValueError(f"Source hash mismatch: {split}")
        sources[split] = {"path": str(path), "sha256": actual, "bytes": path.stat().st_size}
    ontology = load_ontology_resources(ontology_root)
    if dict(ontology.source_hashes) != manifest["ontology_source_hashes"]:
        raise ValueError("Ontology source hashes differ from the frozen pilot")
    by_id = _load_gold_questions(dataset_root)
    if not set(ids).issubset(by_id):
        raise ValueError("An original pilot question is missing")
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    receipt = {
        "schema_version": "xgap-int-input-recovery-v1", "status": "started",
        "original_manifest_sha256": sha256(manifest_path),
        "pilot_ids_sha256": sha256(ids_path), "question_ids": ids,
        "sources": sources, "ontology_source_hashes": dict(ontology.source_hashes),
        "source_selection_changed": False, "catalog_built": False,
        "external_calls": 0, "paper_result": False,
        "complete_dataset_bundle": False, "artifacts": {},
    }
    try:
        normalized = normalize_ontology(ontology)
        registry.load_descriptors(REPO / "descriptors/backends")
        profiles = {key: registry.get_capability_profile(key) for key in ("neo4j", "fuseki")}
        rdf_mapping = RdfBackendMapping.from_artifact(build_backend_mapping(ontology))
        records = []
        for qid in ids:
            question = by_id[qid]
            result = convert_question_v2(question, question["_split"], ontology,
                normalized_ontology=normalized, cypher_profile=profiles["neo4j"],
                sparql_profile=profiles["fuseki"], rdf_mapping=rdf_mapping)
            if not result.supported:
                raise ValueError(f"Original reference no longer converts: {qid}: {result.record}")
            records.append(result.record)
        _write_jsonl(output / "inference_questions.jsonl", ({
            "schema_version": "m13d-grailqa-inference-question-v1",
            "question_id": qid, "text": by_id[qid]["question"],
            "split": by_id[qid]["_split"], "source_benchmark_id": f"grailqa-v1.0:{qid}",
        } for qid in ids))
        _write_jsonl(output / "gold_answers.jsonl", ({
            "question_id": qid, "answers": normalize_answers(by_id[qid].get("answer", [])),
            "evaluation_only": True,
        } for qid in ids))
        _write_jsonl(output / "gold_logical_forms.jsonl", ({
            "question_id": qid, "s_expression": by_id[qid].get("s_expression"),
            "sparql_query": by_id[qid].get("sparql_query"), "evaluation_only": True,
        } for qid in ids))
        _write_jsonl(output / "reference_interpretations.jsonl", ({
            "question_id": r["question_id"], "candidate_id": f"reference-{r['question_id']}",
            "pattern_query": r["reference_interpretation"],
            "answer_path_position": r["answer_path_position"], "answer_column": r["answer_column"],
            "provenance": "public_train_dev_gold_evaluation_only", "evaluation_only": True,
        } for r in records))
        _write_jsonl(output / "canonical_logical_plans.jsonl", ({
            "question_id": r["question_id"], "logical_plan_id": r["logical_plan_id"],
            "formatted_logical_plan": r["formatted_logical_plan"], "operators": r["operators"],
            "dependency_count": r["logical_dependency_count"], "canonical": True,
        } for r in records))
        terms = {str(slot[key]) for r in records for slot in r["ontology_slots"]
                 for key in ("term", "normalized_term")}
        (output / "backend_mapping.yaml").write_text(yaml_text(build_backend_mapping(ontology, terms)), encoding="utf-8")
        (output / "ontology.yaml").write_text(yaml_text(normalized.graph.to_dict()), encoding="utf-8")
        for path in sorted(output.iterdir()):
            expected = manifest["artifacts"][path.name]
            actual = {"bytes": path.stat().st_size, "sha256": sha256(path)}
            receipt["artifacts"][path.name] = {**actual, "matches_original": actual == expected}
        if not all(item["matches_original"] for item in receipt["artifacts"].values()):
            raise ValueError("Recovered bytes differ; retain failed receipt and do not use this directory")
        receipt["status"] = "verified_partial_input_recovery"
    except Exception as error:
        receipt.update(status="failed", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        receipt["elapsed_seconds"] = time.perf_counter() - started
        _write_json(output / "restore_receipt.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset-root", "ontology-root", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    result = restore(args.dataset_root, args.ontology_root, args.output)
    print(json.dumps({"status": result["status"], "files": len(result["artifacts"]),
                      "questions": len(result["question_ids"]), "elapsed_seconds": result["elapsed_seconds"]}))
