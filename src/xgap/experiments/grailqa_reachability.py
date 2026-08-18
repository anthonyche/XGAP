"""Evaluation-only catalog, retrieval, and prompt reachability audits."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from xgap.experiments.grailqa_catalog import GrailQAInferenceCatalog, sha256_file
from xgap.experiments.grailqa_catalog_v2 import GrailQAInferenceCatalogV2
from xgap.experiments.hashing import content_hash


REACHABILITY_SCHEMA_VERSION = "m13e1-grailqa-reachability-v2"
DEFAULT_K_VALUES = (1, 5, 10, 20)


@dataclass(frozen=True)
class ReferenceRequirements:
    question_id: str
    entities: tuple[str, ...]
    relations: tuple[str, ...]
    types: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "entities": list(self.entities),
            "relations": list(self.relations),
            "types": list(self.types),
        }


@dataclass(frozen=True)
class CatalogUniverse:
    catalog_id: str
    catalog_hash: str
    entities: frozenset[str]
    relations: frozenset[str]
    types: frozenset[str]


def reference_requirements(record: Mapping[str, Any]) -> ReferenceRequirements:
    pattern = _mapping(record.get("pattern_query"), "pattern_query")
    source = _mapping(pattern.get("source"), "source")
    target = _mapping(pattern.get("target"), "target")
    entities = {
        str(value)
        for node in (source, target)
        for key, value in _mapping(node.get("properties", {}), "properties").items()
        if key == "type.object.id"
    }
    types = {
        str(node["label"])
        for node in (source, target)
        if node.get("label") is not None
    }
    relations = tuple(_relation_labels(_mapping(pattern.get("expr"), "expr")))
    return ReferenceRequirements(
        question_id=str(record["question_id"]),
        entities=tuple(sorted(entities)),
        relations=relations,
        types=tuple(sorted(types)),
    )


def load_catalog_universe(root: str | Path) -> CatalogUniverse:
    catalog_root = Path(root)
    manifest = json.loads((catalog_root / "manifest.json").read_text(encoding="utf-8"))
    schema = str(manifest.get("schema_version", ""))
    if schema == "m13d-grailqa-inference-catalog-v1":
        catalog = GrailQAInferenceCatalog.load(catalog_root)
        return CatalogUniverse(
            catalog_id=str(manifest["catalog_id"]),
            catalog_hash=catalog.catalog_hash,
            entities=frozenset(item.entry_id for item in catalog.entities),
            relations=frozenset(item.entry_id for item in catalog.relations),
            types=frozenset(item.entry_id for item in catalog.types),
        )
    catalog_v2 = GrailQAInferenceCatalogV2.load(catalog_root)
    database = catalog_v2.root / "catalog.sqlite3"
    import sqlite3

    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        entities = frozenset(str(row[0]) for row in connection.execute("SELECT id FROM entities"))
    finally:
        connection.close()
    return CatalogUniverse(
        catalog_id=str(catalog_v2.manifest["catalog_id"]),
        catalog_hash=catalog_v2.catalog_hash,
        entities=entities,
        relations=frozenset(term.term_id for term in catalog_v2.terms if term.kind == "relation"),
        types=frozenset(term.term_id for term in catalog_v2.terms if term.kind == "type"),
    )


def audit_reachability(
    *,
    references: Sequence[Mapping[str, Any]],
    retrieval_rows: Sequence[Mapping[str, Any]],
    catalog: CatalogUniverse,
    workload_by_id: Mapping[str, Mapping[str, Any]] | None = None,
    k_values: Sequence[int] = DEFAULT_K_VALUES,
    prompt_limit: int = 4,
) -> dict[str, Any]:
    """Compare evaluation-only reference requirements with inference artifacts."""

    if any(value <= 0 for value in k_values) or not k_values:
        raise ValueError("k_values must contain positive integers.")
    if prompt_limit <= 0:
        raise ValueError("prompt_limit must be positive.")
    retrieval_by_id = {str(item["question_id"]): item for item in retrieval_rows}
    requirements = [reference_requirements(item) for item in references]
    missing = [item.question_id for item in requirements if item.question_id not in retrieval_by_id]
    if missing:
        raise ValueError(f"Missing retrieval rows for question IDs: {missing[:5]}")
    rows = [
        _audit_one(
            item,
            retrieval_by_id[item.question_id],
            catalog,
            tuple(int(value) for value in k_values),
            prompt_limit,
            (workload_by_id or {}).get(item.question_id, {}),
        )
        for item in requirements
    ]
    return {
        "schema_version": REACHABILITY_SCHEMA_VERSION,
        "catalog_id": catalog.catalog_id,
        "catalog_hash": catalog.catalog_hash,
        "question_count": len(rows),
        "k_values": list(k_values),
        "prompt_limit": prompt_limit,
        "summary": _aggregate(rows, tuple(int(value) for value in k_values)),
        "by_q": _stratify(rows, "Q", tuple(int(value) for value in k_values)),
        "by_path_length": _stratify(
            rows, "path_length", tuple(int(value) for value in k_values)
        ),
        "rows": rows,
    }


def prompt_reachability_gate(
    audit: Mapping[str, Any], *, minimum_joint_ratio: float
) -> dict[str, Any]:
    """Fail closed before a paid run when prompt reachability is insufficient."""

    if not 0.0 <= minimum_joint_ratio <= 1.0:
        raise ValueError("minimum_joint_ratio must be within [0, 1].")
    k_values = tuple(int(item) for item in audit.get("k_values", ()))
    if not k_values:
        raise ValueError("Reachability audit has no k values.")
    deployed = _mapping(_mapping(audit.get("summary"), "summary").get("deployed_prompt"), "deployed_prompt")
    ratio = float(_mapping(deployed.get("joint"), "joint").get("ratio", 0.0))
    passed = ratio >= minimum_joint_ratio
    return {
        "schema_version": "m13e1-prompt-reachability-gate-v1",
        "passed": passed,
        "minimum_joint_ratio": minimum_joint_ratio,
        "observed_joint_ratio": ratio,
        "prompt_limit": int(audit.get("prompt_limit", 0)),
        "reason": (
            "Prompt reachability meets the frozen engineering safeguard."
            if passed
            else "Joint prompt reachability is below the frozen engineering safeguard; live execution is refused."
        ),
        "paper_metric": False,
    }


def run_v1_baseline_audit(
    *, pilot_root: str | Path, catalog_root: str | Path, output_root: str | Path
) -> dict[str, Any]:
    """Reproduce the immutable M13-D reachability diagnosis offline."""

    pilot = Path(pilot_root)
    catalog_path = Path(catalog_root)
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    references = _read_jsonl(pilot / "reference_interpretations.jsonl")
    questions = _read_jsonl(pilot / "inference_questions.jsonl")
    workload = {
        str(item["question_id"]): item
        for item in _read_jsonl(pilot / "workload_stats.jsonl")
    }
    catalog = GrailQAInferenceCatalog.load(catalog_path)
    retrieval_rows = [
        catalog.retrieve(str(item["question_id"]), str(item["text"]), top_k=20).to_dict()
        for item in questions
    ]
    result = audit_reachability(
        references=references,
        retrieval_rows=retrieval_rows,
        catalog=load_catalog_universe(catalog_path),
        workload_by_id=workload,
        prompt_limit=4,
    )
    _write_jsonl(output / "retrieval.jsonl", retrieval_rows)
    _write_jsonl(output / "reachability.jsonl", result.pop("rows"))
    result["inputs"] = {
        "pilot_reference_sha256": sha256_file(pilot / "reference_interpretations.jsonl"),
        "pilot_questions_sha256": sha256_file(pilot / "inference_questions.jsonl"),
        "catalog_hash": catalog.catalog_hash,
    }
    result["audit_hash"] = content_hash(result)
    (output / "summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": "m13e1-reachability-artifact-manifest-v1",
        "dataset_id": "grailqa_m13d_reachability_baseline",
        "status": "complete",
        "gold_usage": "evaluation_only",
        "inference_gold_usage": False,
        "files": {
            name: sha256_file(output / name)
            for name in ("retrieval.jsonl", "reachability.jsonl", "summary.json")
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def run_v2_pilot_audit(
    *, pilot_root: str | Path, catalog_root: str | Path, output_root: str | Path
) -> dict[str, Any]:
    """Build the full 150-query offline v2 retrieval/reachability bundle."""

    pilot = Path(pilot_root)
    catalog_path = Path(catalog_root)
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    references = _read_jsonl(pilot / "reference_interpretations.jsonl")
    questions = _read_jsonl(pilot / "inference_questions.jsonl")
    workload = {
        str(item["question_id"]): item
        for item in _read_jsonl(pilot / "workload_stats.jsonl")
    }
    catalog = GrailQAInferenceCatalogV2.load(catalog_path)
    retrieval_rows = [
        catalog.retrieve(
            str(item["question_id"]),
            str(item["text"]),
            top_k=20,
            relation_slots=3,
            expansion_hops=1,
        ).to_dict()
        for item in questions
    ]
    result = audit_reachability(
        references=references,
        retrieval_rows=retrieval_rows,
        catalog=load_catalog_universe(catalog_path),
        workload_by_id=workload,
        prompt_limit=4,
    )
    rows = result.pop("rows")
    gate = prompt_reachability_gate(result, minimum_joint_ratio=0.20)
    result["gate"] = gate
    result["audit_hash"] = content_hash(result)
    _write_jsonl(output / "retrieval.jsonl", retrieval_rows)
    _write_jsonl(output / "reachability.jsonl", rows)
    (output / "summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": "m13e1-reachability-artifact-manifest-v1",
        "dataset_id": "grailqa_reachability_v2",
        "status": "complete",
        "catalog_hash": catalog.catalog_hash,
        "gold_usage": "evaluation_only",
        "inference_gold_usage": False,
        "gate": gate,
        "files": {
            name: sha256_file(output / name)
            for name in ("retrieval.jsonl", "reachability.jsonl", "summary.json")
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def audit_catalog_coverage(
    *, supported_questions_path: str | Path, catalog_root: str | Path
) -> dict[str, Any]:
    """Measure catalog coverage over evaluation records without retrieval."""

    records = _read_jsonl(Path(supported_questions_path))
    references = [
        {
            "question_id": item["question_id"],
            "pattern_query": item["reference_interpretation"],
        }
        for item in records
    ]
    catalog = load_catalog_universe(catalog_root)
    rows = []
    for record in references:
        requirement = reference_requirements(record)
        coverage = {
            "entity": _coverage(requirement.entities, catalog.entities),
            "relation": _coverage(requirement.relations, catalog.relations),
            "type": _coverage(requirement.types, catalog.types),
        }
        coverage["joint"] = _joint(coverage)
        rows.append(coverage)
    return {
        "schema_version": "m13e1-grailqa-catalog-coverage-v1",
        "catalog_id": catalog.catalog_id,
        "catalog_hash": catalog.catalog_hash,
        "question_count": len(rows),
        "gold_usage": "evaluation_only",
        "coverage": {
            kind: {
                "count": sum(bool(row[kind]["reachable"]) for row in rows),
                "ratio": (
                    sum(bool(row[kind]["reachable"]) for row in rows) / len(rows)
                    if rows
                    else None
                ),
            }
            for kind in ("entity", "relation", "type", "joint")
        },
    }


def _audit_one(
    requirement: ReferenceRequirements,
    retrieval: Mapping[str, Any],
    catalog: CatalogUniverse,
    k_values: tuple[int, ...],
    prompt_limit: int,
    workload: Mapping[str, Any],
) -> dict[str, Any]:
    retrieved_entities = tuple(str(item["id"]) for item in retrieval.get("entity_candidates", ()))
    retrieved_types = tuple(str(item["id"]) for item in retrieval.get("type_candidates", ()))
    raw_slots = retrieval.get("relation_slots")
    if isinstance(raw_slots, list):
        relation_slots = tuple(
            tuple(str(item["id"]) for item in slot.get("candidates", ()))
            for slot in raw_slots
        )
        retrieved_relations = tuple(dict.fromkeys(item for slot in relation_slots for item in slot))
    else:
        retrieved_relations = tuple(
            str(item["id"]) for item in retrieval.get("relation_candidates", ())
        )
        relation_slots = ()
    row: dict[str, Any] = {
        "question_id": requirement.question_id,
        "requirements": requirement.to_dict(),
        "strata": {
            "Q": workload.get("Q"),
            "path_length": workload.get("path_length"),
        },
        "catalog": {
            "entity": _coverage(requirement.entities, catalog.entities),
            "relation": _coverage(requirement.relations, catalog.relations),
            "type": _coverage(requirement.types, catalog.types),
        },
        "retrieval": {},
        "prompt": {},
    }
    row["catalog"]["joint"] = _joint(row["catalog"])
    for k in k_values:
        retrieval_coverage = {
            "entity": _coverage(requirement.entities, retrieved_entities[:k]),
            "relation": _relation_coverage(requirement.relations, retrieved_relations, relation_slots, k),
            "type": _coverage(requirement.types, retrieved_types[:k]),
        }
        retrieval_coverage["joint"] = _joint(retrieval_coverage)
        prompt_k = min(k, prompt_limit)
        prompt_coverage = {
            "entity": _coverage(requirement.entities, retrieved_entities[:prompt_k]),
            "relation": _relation_coverage(
                requirement.relations, retrieved_relations, relation_slots, prompt_k
            ),
            "type": _coverage(requirement.types, retrieved_types[:prompt_k]),
        }
        prompt_coverage["joint"] = _joint(prompt_coverage)
        row["retrieval"][str(k)] = retrieval_coverage
        row["prompt"][str(k)] = prompt_coverage
    deployed = {
        "entity": _coverage(requirement.entities, retrieved_entities[:prompt_limit]),
        "relation": _relation_coverage(
            requirement.relations, retrieved_relations, relation_slots, prompt_limit
        ),
        "type": _coverage(requirement.types, retrieved_types[:prompt_limit]),
    }
    deployed["joint"] = _joint(deployed)
    row["deployed_prompt"] = deployed
    row["first_unreachable_stage"] = _first_unreachable_stage(row)
    return row


def _coverage(required: Iterable[str], available: Iterable[str]) -> dict[str, Any]:
    required_set = set(required)
    available_set = set(available)
    missing = sorted(required_set - available_set)
    return {
        "reachable": not missing,
        "required_count": len(required_set),
        "matched_count": len(required_set) - len(missing),
        "missing": missing,
    }


def _relation_coverage(
    required: tuple[str, ...],
    pooled: tuple[str, ...],
    slots: tuple[tuple[str, ...], ...],
    k: int,
) -> dict[str, Any]:
    if slots:
        matched = [
            relation in slots[index][:k]
            for index, relation in enumerate(required)
            if index < len(slots)
        ]
        missing = [
            relation
            for index, relation in enumerate(required)
            if index >= len(slots) or relation not in slots[index][:k]
        ]
        return {
            "reachable": len(missing) == 0,
            "required_count": len(required),
            "matched_count": sum(matched),
            "missing": missing,
            "slot_aware": True,
        }
    result = _coverage(required, pooled[:k])
    result["slot_aware"] = False
    return result


def _joint(coverage: Mapping[str, Any]) -> dict[str, Any]:
    reachable = all(bool(_mapping(coverage[kind], kind)["reachable"]) for kind in ("entity", "relation", "type"))
    return {"reachable": reachable}


def _first_unreachable_stage(row: Mapping[str, Any]) -> str | None:
    if not _mapping(_mapping(row["catalog"], "catalog")["joint"], "joint")["reachable"]:
        return "reference_not_in_catalog"
    top_key = max(_mapping(row["retrieval"], "retrieval"), key=int)
    if not _mapping(_mapping(row["retrieval"], "retrieval")[top_key]["joint"], "joint")["reachable"]:
        return "reference_not_retrieved"
    if not _mapping(row["deployed_prompt"]["joint"], "joint")["reachable"]:
        return "reference_not_prompt_visible"
    return None


def _aggregate(rows: Sequence[Mapping[str, Any]], k_values: tuple[int, ...]) -> dict[str, Any]:
    return {
        "catalog": _aggregate_stage(rows, "catalog", None),
        "retrieval": {
            str(k): _aggregate_stage(rows, "retrieval", str(k)) for k in k_values
        },
        "prompt": {str(k): _aggregate_stage(rows, "prompt", str(k)) for k in k_values},
        "deployed_prompt": _aggregate_stage(rows, "deployed_prompt", None),
    }


def _aggregate_stage(
    rows: Sequence[Mapping[str, Any]], stage: str, k: str | None
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for kind in ("entity", "relation", "type", "joint"):
        count = sum(
            bool(
                _mapping(
                    (_mapping(row[stage], stage)[k] if k is not None else row[stage])[kind],
                    kind,
                )["reachable"]
            )
            for row in rows
        )
        result[kind] = {"count": count, "ratio": count / len(rows) if rows else None}
    return result


def _stratify(
    rows: Sequence[Mapping[str, Any]], field: str, k_values: tuple[int, ...]
) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        key = str(_mapping(row.get("strata"), "strata").get(field))
        groups.setdefault(key, []).append(row)
    return {
        key: {"count": len(values), **_aggregate(values, k_values)}
        for key, values in sorted(groups.items())
    }


def _relation_labels(expr: Mapping[str, Any]) -> Iterable[str]:
    kind = str(expr.get("kind", "")).casefold()
    if kind == "rel":
        edge = _mapping(expr.get("edge"), "edge")
        if edge.get("label") is not None:
            yield str(edge["label"])
        return
    if kind in ("seq", "alt"):
        yield from _relation_labels(_mapping(expr.get("left"), "left"))
        yield from _relation_labels(_mapping(expr.get("right"), "right"))
        return
    if kind in ("plus", "star", "optional", "bounded"):
        yield from _relation_labels(_mapping(expr.get("child"), "child"))


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object.")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(dict(row), sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    baseline = subparsers.add_parser("m13d-baseline")
    baseline.add_argument("--pilot-root", default="datasets/grailqa_pilot_v1")
    baseline.add_argument("--catalog-root", default="datasets/grailqa_inference_catalog_v1")
    baseline.add_argument("--output", required=True)
    v2 = subparsers.add_parser("v2-pilot")
    v2.add_argument("--pilot-root", default="datasets/grailqa_pilot_v1")
    v2.add_argument("--catalog-root", required=True)
    v2.add_argument("--output", required=True)
    coverage = subparsers.add_parser("catalog-coverage")
    coverage.add_argument("--supported-questions", required=True)
    coverage.add_argument("--catalog-root", required=True)
    coverage.add_argument("--output", required=True)
    gate = subparsers.add_parser("gate")
    gate.add_argument("--summary", required=True)
    gate.add_argument("--minimum", type=float, required=True)
    args = parser.parse_args(argv)
    if args.command == "m13d-baseline":
        result = run_v1_baseline_audit(
            pilot_root=args.pilot_root,
            catalog_root=args.catalog_root,
            output_root=args.output,
        )
        print(json.dumps(result["summary"], indent=2, sort_keys=True))
        return 0
    if args.command == "v2-pilot":
        result = run_v2_pilot_audit(
            pilot_root=args.pilot_root,
            catalog_root=args.catalog_root,
            output_root=args.output,
        )
        print(json.dumps(result["summary"], indent=2, sort_keys=True))
        return 0 if result["gate"]["passed"] else 2
    if args.command == "catalog-coverage":
        result = audit_catalog_coverage(
            supported_questions_path=args.supported_questions,
            catalog_root=args.catalog_root,
        )
        Path(args.output).write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(result["coverage"], indent=2, sort_keys=True))
        return 0
    audit = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    result = prompt_reachability_gate(audit, minimum_joint_ratio=args.minimum)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
