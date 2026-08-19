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


def load_catalog_universe(
    root: str | Path, *, required_entity_ids: Iterable[str] | None = None
) -> CatalogUniverse:
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
        required = tuple(sorted(set(required_entity_ids or ())))
        if required_entity_ids is None:
            entities = frozenset(
                str(row[0]) for row in connection.execute("SELECT id FROM entities")
            )
        else:
            found: set[str] = set()
            for offset in range(0, len(required), 900):
                chunk = required[offset : offset + 900]
                placeholders = ",".join("?" for _ in chunk)
                found.update(
                    str(row[0])
                    for row in connection.execute(
                        f"SELECT id FROM entities WHERE id IN ({placeholders})", chunk
                    )
                )
            entities = frozenset(found)
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
    questions = _read_jsonl(pilot / "inference_questions.jsonl")
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
    _write_jsonl(output / "retrieval.jsonl", retrieval_rows)

    # Evaluation-only artifacts are opened only after gold-free retrieval is persisted.
    references = _read_jsonl(pilot / "reference_interpretations.jsonl")
    workload = {
        str(item["question_id"]): item
        for item in _read_jsonl(pilot / "workload_stats.jsonl")
    }
    required_entities = {
        entity
        for reference in references
        for entity in reference_requirements(reference).entities
    }
    result = audit_reachability(
        references=references,
        retrieval_rows=retrieval_rows,
        catalog=load_catalog_universe(
            catalog_path, required_entity_ids=required_entities
        ),
        workload_by_id=workload,
        prompt_limit=4,
    )
    rows = result.pop("rows")
    gate = prompt_reachability_gate(result, minimum_joint_ratio=0.20)
    result["gate"] = gate
    result["live_preflight_allowed"] = gate["passed"]
    result["stage_failure_counts"] = _stage_failure_counts(rows)
    result["prompt_truncation_loss"] = _prompt_truncation_loss(
        rows, tuple(int(value) for value in result["k_values"])
    )
    result["audit_hash"] = content_hash(result)
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
    requirements = [reference_requirements(record) for record in references]
    catalog = load_catalog_universe(
        catalog_root,
        required_entity_ids={entity for item in requirements for entity in item.entities},
    )
    rows = []
    for requirement in requirements:
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


def run_m13e3_audit(
    *,
    supported_questions_path: str | Path,
    pilot_root: str | Path,
    catalog_root: str | Path,
    output_root: str | Path,
    expected_supported_questions: int = 35_439,
    expected_pilot_questions: int = 150,
) -> dict[str, Any]:
    """Run the frozen catalog-v2 coverage and retrieval audit without an LLM."""

    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    all_supported = audit_catalog_coverage(
        supported_questions_path=supported_questions_path,
        catalog_root=catalog_root,
    )
    if all_supported["question_count"] != expected_supported_questions:
        raise ValueError(
            "Supported GrailQA workload count differs from the frozen M13-E3 contract: "
            f"expected {expected_supported_questions}, got {all_supported['question_count']}."
        )
    pilot = run_v2_pilot_audit(
        pilot_root=pilot_root,
        catalog_root=catalog_root,
        output_root=output,
    )
    if pilot["question_count"] != expected_pilot_questions:
        raise ValueError(
            "Frozen GrailQA pilot count differs from the M13-E3 contract: "
            f"expected {expected_pilot_questions}, got {pilot['question_count']}."
        )
    catalog_coverage = {
        "schema_version": "m13e3-grailqa-catalog-coverage-v1",
        "all_supported": all_supported,
        "frozen_pilot": pilot["summary"]["catalog"],
    }
    retrieval_metrics = {
        "schema_version": "m13e3-grailqa-retrieval-metrics-v1",
        "question_count": pilot["question_count"],
        "k_values": pilot["k_values"],
        "metrics": pilot["summary"]["retrieval"],
        "by_q": {key: value["retrieval"] for key, value in pilot["by_q"].items()},
        "by_path_length": {
            key: value["retrieval"] for key, value in pilot["by_path_length"].items()
        },
    }
    prompt_reachability = {
        "schema_version": "m13e3-grailqa-prompt-reachability-v1",
        "question_count": pilot["question_count"],
        "k_values": pilot["k_values"],
        "frozen_prompt_bound": pilot["prompt_limit"],
        "at_k": pilot["summary"]["prompt"],
        "deployed_prompt": pilot["summary"]["deployed_prompt"],
        "truncation_loss": pilot["prompt_truncation_loss"],
        "by_q": {key: value["prompt"] for key, value in pilot["by_q"].items()},
        "by_path_length": {
            key: value["prompt"] for key, value in pilot["by_path_length"].items()
        },
    }
    stage_failures = {
        "schema_version": "m13e3-grailqa-stage-failure-counts-v1",
        **pilot["stage_failure_counts"],
    }
    audit_summary = {
        "schema_version": "m13e3-grailqa-reachability-audit-summary-v1",
        "status": "complete",
        "catalog_id": pilot["catalog_id"],
        "catalog_hash": pilot["catalog_hash"],
        "all_supported_question_count": all_supported["question_count"],
        "pilot_question_count": pilot["question_count"],
        "joint_catalog_coverage": {
            "all_supported": all_supported["coverage"]["joint"],
            "frozen_pilot": pilot["summary"]["catalog"]["joint"],
        },
        "joint_prompt_reachability": pilot["summary"]["prompt"],
        "deployed_joint_prompt_reachability": pilot["summary"]["deployed_prompt"][
            "joint"
        ],
        "live_preflight_allowed": pilot["live_preflight_allowed"],
        "gate": pilot["gate"],
        "gold_usage": "evaluation_only",
        "inference_gold_usage": False,
    }
    compact = {
        "audit_summary.json": audit_summary,
        "catalog_coverage.json": catalog_coverage,
        "retrieval_metrics.json": retrieval_metrics,
        "prompt_reachability.json": prompt_reachability,
        "stage_failure_counts.json": stage_failures,
    }
    for name, value in compact.items():
        (output / name).write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    file_names = (
        *compact,
        "retrieval.jsonl",
        "reachability.jsonl",
        "summary.json",
        "manifest.json",
    )
    manifest_reference = {
        "schema_version": "m13e3-grailqa-reachability-manifest-reference-v1",
        "status": "complete",
        "catalog_hash": pilot["catalog_hash"],
        "large_artifacts_external": ["retrieval.jsonl", "reachability.jsonl"],
        "files": {name: sha256_file(output / name) for name in file_names},
    }
    (output / "manifest_reference.json").write_text(
        json.dumps(manifest_reference, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return audit_summary


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
        pooled_at_k = {
            candidate for slot in slots for candidate in slot[:k]
        }
        per_slot = [
            {
                "slot": index + 1,
                "relation": relation,
                "reachable": index < len(slots) and relation in slots[index][:k],
            }
            for index, relation in enumerate(required)
        ]
        missing = [
            relation
            for index, relation in enumerate(required)
            if index >= len(slots) or relation not in slots[index][:k]
        ]
        matched_count = sum(bool(item["reachable"]) for item in per_slot)
        return {
            "reachable": len(missing) == 0,
            "all_required_reachable": len(missing) == 0,
            "any_reachable": not required or any(
                relation in pooled_at_k for relation in required
            ),
            "required_count": len(required),
            "matched_count": matched_count,
            "missing": missing,
            "slot_aware": True,
            "per_slot": per_slot,
        }
    result = _coverage(required, pooled[:k])
    result.update(
        {
            "all_required_reachable": result["reachable"],
            "any_reachable": not required or bool(result["matched_count"]),
            "slot_aware": False,
            "per_slot": [],
        }
    )
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
    relation_values = [
        _mapping(
            (_mapping(row[stage], stage)[k] if k is not None else row[stage])["relation"],
            "relation",
        )
        for row in rows
    ]
    any_count = sum(
        bool(
            value.get(
                "any_reachable",
                not value.get("required_count") or bool(value.get("matched_count")),
            )
        )
        for value in relation_values
    )
    result["relation_any"] = {
        "count": any_count,
        "ratio": any_count / len(rows) if rows else None,
    }
    result["all_required_relations"] = dict(result["relation"])
    max_slots = max((len(value.get("per_slot", ())) for value in relation_values), default=0)
    result["relation_per_slot"] = {
        str(slot + 1): _slot_metric(relation_values, slot, len(rows))
        for slot in range(max_slots)
    }
    return result


def _slot_metric(
    relation_values: Sequence[Mapping[str, Any]], slot: int, question_count: int
) -> dict[str, Any]:
    applicable = [
        value["per_slot"][slot]
        for value in relation_values
        if slot < len(value.get("per_slot", ()))
    ]
    count = sum(bool(item["reachable"]) for item in applicable)
    return {
        "count": count,
        "applicable_questions": len(applicable),
        "ratio": count / len(applicable) if applicable else None,
        "workload_ratio": count / question_count if question_count else None,
    }


def _stage_failure_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    stages = (
        "reference_not_in_catalog",
        "reference_not_retrieved",
        "reference_not_prompt_visible",
        "reachable",
    )
    counts = {stage: 0 for stage in stages}
    for row in rows:
        stage = row.get("first_unreachable_stage") or "reachable"
        if stage not in counts:
            raise ValueError(f"Unknown reachability stage {stage!r}.")
        counts[str(stage)] += 1
    total = len(rows)
    return {
        "question_count": total,
        "counts": counts,
        "ratios": {
            stage: count / total if total else None for stage, count in counts.items()
        },
    }


def _prompt_truncation_loss(
    rows: Sequence[Mapping[str, Any]], k_values: tuple[int, ...]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for k in k_values:
        key = str(k)
        metrics: dict[str, Any] = {}
        for kind in ("entity", "relation", "type", "joint"):
            count = sum(
                bool(row["retrieval"][key][kind]["reachable"])
                and not bool(row["prompt"][key][kind]["reachable"])
                for row in rows
            )
            metrics[kind] = {
                "count": count,
                "ratio": count / len(rows) if rows else None,
            }
        result[key] = metrics
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
    m13e3 = subparsers.add_parser("m13e3-audit")
    m13e3.add_argument(
        "--supported-questions", default="datasets/grailqa_audit_v2/supported_questions.jsonl"
    )
    m13e3.add_argument("--pilot-root", default="datasets/grailqa_pilot_v1")
    m13e3.add_argument("--catalog-root", required=True)
    m13e3.add_argument("--output", required=True)
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
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(result["coverage"], indent=2, sort_keys=True))
        return 0
    if args.command == "m13e3-audit":
        result = run_m13e3_audit(
            supported_questions_path=args.supported_questions,
            pilot_root=args.pilot_root,
            catalog_root=args.catalog_root,
            output_root=args.output,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["live_preflight_allowed"] else 2
    audit = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    result = prompt_reachability_gate(audit, minimum_joint_ratio=args.minimum)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
