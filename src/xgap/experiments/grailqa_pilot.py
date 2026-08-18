"""Deterministic M13-C GrailQA pilot bundle and offline vertical slice."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from xgap.backends import registry
from xgap.backends.capabilities import SupportLevel
from xgap.backends.compatibility import check_backend_support
from xgap.compilers import compile_cypher, compile_sparql
from xgap.experiments.bundles import DatasetBundle
from xgap.experiments.grailqa_audit import DATASET_FILES, load_ontology_resources
from xgap.experiments.grailqa_v2 import (
    build_backend_mapping,
    normalize_answers,
    normalize_ontology,
    yaml_text,
)
from xgap.experiments.hashing import content_hash
from xgap.llm.parser import parse_path_pattern_query, path_pattern_query_to_dict
from xgap.llm.schemas import PlannerCandidate
from xgap.pattern.lowering import lower_to_logical_plan
from xgap.planning import (
    ArtifactOntologyAlignmentProvider,
    DeterministicStateFeatureExtractor,
    ExchangeCatalog,
    ExistingCompilerAdapter,
    FixedBudgetPolicy,
    GaussianProcessConfig,
    GaussianProcessCostEstimator,
    PlanningConfig,
    ProvidedSemanticDeviationScorer,
    QueryPlanningContext,
    XGAPPhysicalPlanner,
)
from xgap.planning.topology import index_logical_plan


PILOT_SCHEMA_VERSION = "m13c-grailqa-pilot-v1"
DEFAULT_SEED = 1303
DEFAULT_SIZE = 150


def select_pilot_records(
    records: Sequence[Mapping[str, Any]],
    *,
    size: int = DEFAULT_SIZE,
    seed: int = DEFAULT_SEED,
) -> tuple[dict[str, Any], ...]:
    """Select a split-aware, workload-stratified subset without outcomes."""

    if size <= 0 or size > len(records):
        raise ValueError("Pilot size must be positive and no larger than the support set.")
    by_split: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        split = str(record.get("split", ""))
        if split not in {"train", "dev"}:
            raise ValueError("Pilot candidates must come from public train/dev only.")
        by_split[split].append(record)
    dev_quota = min(len(by_split["dev"]), max(1, round(size * 0.2)))
    quotas = {"dev": dev_quota, "train": size - dev_quota}
    if quotas["train"] > len(by_split["train"]):
        difference = quotas["train"] - len(by_split["train"])
        quotas["train"] -= difference
        quotas["dev"] += difference

    selected: list[dict[str, Any]] = []
    for split in ("train", "dev"):
        groups: dict[tuple[object, ...], list[Mapping[str, Any]]] = defaultdict(list)
        for record in by_split[split]:
            ambiguity = record.get("ambiguity", {})
            a_value = (
                int(ambiguity.get("A_recommended", 1))
                if isinstance(ambiguity, Mapping)
                else 1
            )
            relation = str(next(iter(record.get("traversal_relations", ())), "unknown"))
            stratum = (
                int(record["logical_plan_size"]),
                int(record["path_length"]),
                _ambiguity_bucket(a_value),
                str(record.get("function", "none")),
                relation.split(".", 1)[0],
            )
            groups[stratum].append(record)
        for group in groups.values():
            group.sort(key=lambda item: _seeded_key(seed, str(item["question_id"])))
        group_keys = sorted(
            groups,
            key=lambda key: _seeded_key(seed, json.dumps(key, sort_keys=True)),
        )
        split_selected: list[Mapping[str, Any]] = []
        round_index = 0
        while len(split_selected) < quotas[split]:
            progressed = False
            for key in group_keys:
                group = groups[key]
                if round_index < len(group):
                    split_selected.append(group[round_index])
                    progressed = True
                    if len(split_selected) == quotas[split]:
                        break
            if not progressed:
                raise ValueError(f"Not enough records to satisfy {split} pilot quota.")
            round_index += 1
        selected.extend(dict(item) for item in split_selected)
    return tuple(
        sorted(selected, key=lambda item: (str(item["split"]), str(item["question_id"])))
    )


def _ambiguity_bucket(value: int) -> str:
    if value == 1:
        return "A1"
    if value <= 3:
        return "A2_3"
    if value <= 8:
        return "A4_8"
    return "A9_plus"


def _seeded_key(seed: int, value: str) -> tuple[str, str]:
    digest = hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()
    return digest, value


def build_pilot_bundle(
    dataset_root: str | Path,
    ontology_root: str | Path,
    audit_root: str | Path,
    output_root: str | Path,
    *,
    size: int = DEFAULT_SIZE,
    seed: int = DEFAULT_SEED,
) -> DatasetBundle:
    dataset_path = Path(dataset_root)
    ontology_path = Path(ontology_root)
    audit_path = Path(audit_root)
    output_path = Path(output_root)
    records = _read_jsonl(audit_path / "supported_questions.jsonl")
    selected = select_pilot_records(records, size=size, seed=seed)
    selected_ids = {str(item["question_id"]) for item in selected}
    by_id = _load_gold_questions(dataset_path)
    if not selected_ids.issubset(by_id):
        raise ValueError("Pilot selection references a missing train/dev question.")

    ontology = load_ontology_resources(ontology_path)
    normalized = normalize_ontology(ontology)
    selected_terms = {
        str(slot["term"])
        for record in selected
        for slot in record["ontology_slots"]
    }
    selected_terms.update(
        str(slot["normalized_term"])
        for record in selected
        for slot in record["ontology_slots"]
    )
    mapping = build_backend_mapping(ontology, selected_terms)
    output_path.mkdir(parents=True, exist_ok=True)

    question_records: list[dict[str, Any]] = []
    fragment_records: list[dict[str, Any]] = []
    gold_answers: list[dict[str, Any]] = []
    gold_forms: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    query_slots: list[dict[str, Any]] = []
    plans: list[dict[str, Any]] = []
    workload: list[dict[str, Any]] = []
    alignments: list[dict[str, Any]] = []
    evaluation_entities: dict[str, dict[str, Any]] = {}

    for record in selected:
        question_id = str(record["question_id"])
        question = by_id[question_id]
        normalized_gold = normalize_answers(question.get("answer", []))
        terms = tuple(
            str(slot["normalized_term"]) for slot in record["ontology_slots"]
        )
        question_records.append(
            {
                "schema_version": "m12-question-v1",
                "question_id": question_id,
                "text": str(question["question"]),
                "split": str(record["split"]),
                "source_benchmark_id": f"grailqa-v1.0:{question_id}",
                "fragment_support": "xgap_supported",
                "gold_answers": normalized_gold,
                "gold_logical_form": question.get("s_expression"),
                "ontology_slots": list(terms),
                "unavailable_fields": [],
                "metadata": {
                    "evaluation_only_gold": True,
                    "level": question.get("level"),
                    "function": question.get("function"),
                    "Q": record["logical_plan_size"],
                    "A_recommended": record["ambiguity"]["A_recommended"],
                },
            }
        )
        fragment_records.append(
            {"question_id": question_id, "fragment_support": "xgap_supported"}
        )
        gold_answers.append(
            {
                "question_id": question_id,
                "answers": normalized_gold,
                "evaluation_only": True,
            }
        )
        gold_forms.append(
            {
                "question_id": question_id,
                "s_expression": question.get("s_expression"),
                "sparql_query": question.get("sparql_query"),
                "evaluation_only": True,
            }
        )
        references.append(
            {
                "question_id": question_id,
                "candidate_id": f"reference-{question_id}",
                "pattern_query": record["reference_interpretation"],
                "answer_path_position": record["answer_path_position"],
                "answer_column": record["answer_column"],
                "provenance": "public_train_dev_gold_evaluation_only",
                "evaluation_only": True,
            }
        )
        query_slots.append(
            {
                "question_id": question_id,
                "slots": record["ontology_slots"],
                "reference_anchor_source": "public_train_dev_gold_evaluation_only",
                "inference_visible": False,
            }
        )
        plans.append(
            {
                "question_id": question_id,
                "logical_plan_id": record["logical_plan_id"],
                "formatted_logical_plan": record["formatted_logical_plan"],
                "operators": record["operators"],
                "dependency_count": record["logical_dependency_count"],
                "canonical": True,
            }
        )
        workload.append(
            {
                "question_id": question_id,
                "Q": record["logical_plan_size"],
                "A_recommended": record["ambiguity"]["A_recommended"],
                "A_by_epsilon": record["ambiguity"]["counts_by_epsilon"],
                "path_length": record["path_length"],
                "relations": record["traversal_relations"],
                "function": record["function"],
            }
        )
        alignments.append(
            {
                "question_id": question_id,
                "candidate_id": f"reference-{question_id}",
                "alignment_id": f"grailqa-reference-alignment-{question_id}",
                "mapping_status": "complete",
                "required_terms": list(terms),
                "mapped_terms": list(terms),
                "evidence": ["public_train_dev_gold_evaluation_only"],
                "slot_alignments": [
                    {
                        "slot_id": slot["slot_id"],
                        "query_term": slot["normalized_term"],
                        "aligned_term": slot["normalized_term"],
                        "covered": True,
                    }
                    for slot in record["ontology_slots"]
                ],
                "controlled": False,
                "metadata": {"evaluation_only": True, "semantic_deviation": 0.0},
            }
        )
        for node in question.get("graph_query", {}).get("nodes", []):
            if node.get("node_type") != "entity":
                continue
            entity_id = str(node.get("id"))
            evaluation_entities[entity_id] = {
                "entity_id": entity_id,
                "canonical_label": str(node.get("friendly_name") or entity_id),
                "types": [str(node.get("class"))],
                "source": "public_train_dev_gold_evaluation_only",
            }

    schema_content = {
        "freebase": {
            "classes": sorted(term for term in selected_terms if term in ontology.classes),
            "relations": sorted(term for term in selected_terms if term in ontology.relations),
            "properties": sorted(term for term in selected_terms if term in ontology.properties),
            "entity_identity_property": "type.object.id",
        },
        "backend_conventions": {
            "neo4j": "canonical terms as escaped labels/types/property keys",
            "fuseki": "canonical terms under DatasetBundle Freebase namespace mapping",
        },
    }
    schema_snapshot = {
        "schema_version": "m12-schema-snapshot-v1",
        "source": "grailqa-official-processed-freebase-ontology",
        "version": "grailqa-v1.0-m13c-pilot-v1",
        "timestamp": None,
        "content": schema_content,
        "content_hash": content_hash(schema_content),
    }
    aliases = {
        "schema_version": "m13c-grailqa-alias-policy-v1",
        "policy": "no_runtime_aliases_without_a_versioned_public_freebase_alias_lexicon",
        "ontology_terms": {},
        "relations": {},
        "entities": {},
        "gold_annotation_labels_exposed_to_inference": False,
    }
    answer_protocol = {
        "schema_version": "m13c-grailqa-answer-normalization-v1",
        "entity_equivalence": "canonical Freebase ID exact match",
        "entity_labels": "display metadata only; never an equivalence key",
        "scalar_equivalence": "exact normalized lexical value in the selected fragment",
        "duplicates": "deduplicate by typed equivalence_key",
        "ordering": "sort by equivalence_key when answer order is not semantic",
        "supported_current_pilot_answers": ["entity", "scalar evaluation records"],
    }
    pilot_ids = {
        "schema_version": "m13c-grailqa-pilot-selection-v1",
        "seed": seed,
        "requested_size": size,
        "selected_size": len(selected),
        "selection_uses_xgap_outcomes": False,
        "policy": (
            "80/20 train/dev quota; seeded round-robin over Q, path length, "
            "A bucket, query function, and first relation domain"
        ),
        "question_ids": [str(item["question_id"]) for item in selected],
        "distribution": _pilot_distribution(selected),
    }
    inference_manifest = {
        "schema_version": "m13d-grailqa-inference-isolation-v2",
        "runtime_visible": [
            "inference_questions.jsonl",
            "ontology.yaml",
            "aliases.yaml",
            "entity_catalog.jsonl",
            "backend_mapping.yaml",
            "schema_snapshot.json",
        ],
        "evaluation_only": [
            "questions.jsonl:gold_answers",
            "questions.jsonl:gold_logical_form",
            "gold_answers.jsonl",
            "gold_logical_forms.jsonl",
            "gold_alignments.jsonl",
            "reference_interpretations.jsonl",
            "query_slots.jsonl",
            "evaluation_entity_catalog.jsonl",
        ],
        "runtime_entity_catalog_empty": True,
        "gold_exposed_to_inference": False,
    }
    execution_feasibility = {
        "schema_version": "m13c-freebase-execution-feasibility-v1",
        "outcome": "C",
        "outcome_label": "semantic_evaluation_only_currently_practical",
        "source": {
            "name": "Google Freebase RDF data dump",
            "url": "https://developers.google.com/freebase",
            "status": "public_historical_snapshot_not_downloaded_or_verified_by_xgap",
            "license": "CC-BY",
            "published_scale": {
                "triples": 1_900_000_000,
                "compressed_gib_approx": 22,
                "uncompressed_gib_approx": 250,
            },
        },
        "grailqa_reference_setup": {
            "url": "https://github.com/dki-lab/Freebase-Setup",
            "native_store": "Virtuoso",
            "processed_database_disk_gib_min": 53,
            "recommended_memory_gib_min": 100,
        },
        "fuseki": {
            "status": "conversion_not_built_or_measured",
            "feasibility": (
                "A query-independent repaired N-Triples snapshot could be bulk-loaded "
                "into TDB, but the artifact and resource envelope are not frozen."
            ),
        },
        "neo4j": {
            "status": "conversion_not_built_or_measured",
            "feasibility": (
                "A deterministic streaming conversion must preserve Freebase MIDs, "
                "CVTs, types, relations, and literals; no such artifact is frozen."
            ),
        },
        "leakage_boundary": (
            "No per-question gold answers or logical forms may be used to construct "
            "an execution graph."
        ),
        "grailqa_backend_execution_available": False,
    }

    _write_jsonl(output_path / "questions.jsonl", question_records)
    _write_jsonl(
        output_path / "inference_questions.jsonl",
        (
            {
                "schema_version": "m13d-grailqa-inference-question-v1",
                "question_id": item["question_id"],
                "text": item["text"],
                "split": item["split"],
                "source_benchmark_id": item["source_benchmark_id"],
            }
            for item in question_records
        ),
    )
    _write_jsonl(output_path / "fragment_support.jsonl", fragment_records)
    _write_jsonl(output_path / "gold_answers.jsonl", gold_answers)
    _write_jsonl(output_path / "gold_logical_forms.jsonl", gold_forms)
    _write_jsonl(output_path / "reference_interpretations.jsonl", references)
    _write_jsonl(output_path / "query_slots.jsonl", query_slots)
    _write_jsonl(output_path / "canonical_logical_plans.jsonl", plans)
    _write_jsonl(output_path / "workload_stats.jsonl", workload)
    _write_jsonl(output_path / "gold_alignments.jsonl", alignments)
    _write_jsonl(
        output_path / "evaluation_entity_catalog.jsonl",
        [evaluation_entities[key] for key in sorted(evaluation_entities)],
    )
    (output_path / "entity_catalog.jsonl").write_text("", encoding="utf-8")
    (output_path / "ontology.yaml").write_text(
        yaml_text(normalized.graph.to_dict()), encoding="utf-8"
    )
    (output_path / "aliases.yaml").write_text(yaml_text(aliases), encoding="utf-8")
    (output_path / "backend_mapping.yaml").write_text(
        yaml_text(mapping), encoding="utf-8"
    )
    _write_json(output_path / "schema_snapshot.json", schema_snapshot)
    _write_json(output_path / "answer_normalization.json", answer_protocol)
    _write_json(output_path / "pilot_ids.json", pilot_ids)
    _write_json(output_path / "inference_manifest.json", inference_manifest)
    _write_json(output_path / "ontology_normalization.json", normalized.artifact)
    _write_json(
        output_path / "freebase_execution_feasibility.json",
        execution_feasibility,
    )

    dataset_metadata = {
        "schema_version": "m12-dataset-bundle-v1",
        "dataset_id": "grailqa_pilot_v1",
        "version": "m13c-public-train-dev-v1",
        "name": "GrailQA M13-C Reproducible Pilot Bundle",
        "description": "Evaluation-only 150-question GrailQA vertical-slice pilot.",
        "provenance": (
            "GrailQA v1.0 public train/dev and official processed Freebase ontology; "
            "CC BY-SA 4.0 dataset and Apache-2.0 repository resources."
        ),
        "controlled": False,
        "required_artifacts": [
            "questions",
            "ontology",
            "aliases",
            "entity_catalog",
            "backend_mapping",
            "schema_snapshot",
            "fragment_support",
            "gold_alignments",
            "gold_answers",
            "gold_logical_forms",
            "reference_interpretations",
            "query_slots",
            "canonical_logical_plans",
            "workload_stats",
            "answer_normalization",
            "pilot_ids",
            "inference_manifest",
            "ontology_normalization",
            "freebase_execution_feasibility",
            "artifact_manifest",
        ],
        "optional_artifacts": [],
        "artifacts": {
            "questions": "questions.jsonl",
            "ontology": "ontology.yaml",
            "aliases": "aliases.yaml",
            "entity_catalog": "entity_catalog.jsonl",
            "backend_mapping": "backend_mapping.yaml",
            "schema_snapshot": "schema_snapshot.json",
            "fragment_support": "fragment_support.jsonl",
            "gold_alignments": "gold_alignments.jsonl",
            "gold_answers": "gold_answers.jsonl",
            "gold_logical_forms": "gold_logical_forms.jsonl",
            "reference_interpretations": "reference_interpretations.jsonl",
            "query_slots": "query_slots.jsonl",
            "canonical_logical_plans": "canonical_logical_plans.jsonl",
            "workload_stats": "workload_stats.jsonl",
            "answer_normalization": "answer_normalization.json",
            "pilot_ids": "pilot_ids.json",
            "inference_manifest": "inference_manifest.json",
            "ontology_normalization": "ontology_normalization.json",
            "freebase_execution_feasibility": "freebase_execution_feasibility.json",
            "artifact_manifest": "artifact_manifest.json",
        },
        "backend_load": {},
        "metadata": {
            "benchmark_status": "paper_vertical_slice_pilot",
            "final_paper_benchmark": False,
            "case_count": len(selected),
            "gold_isolation_required": True,
            "live_backend_execution_available": False,
        },
    }
    (output_path / "dataset.yaml").write_text(
        yaml_text(dataset_metadata), encoding="utf-8"
    )
    manifest = {
        "schema_version": "m13c-grailqa-artifact-manifest-v1",
        "dataset_id": "grailqa_pilot_v1",
        "source_hashes": {
            split: _sha256(dataset_path / filename)
            for split, filename in DATASET_FILES.items()
        },
        "ontology_source_hashes": dict(sorted(ontology.source_hashes.items())),
        "artifacts": {
            path.name: {"sha256": _sha256(path), "bytes": path.stat().st_size}
            for path in sorted(output_path.iterdir())
            if path.is_file() and path.name != "artifact_manifest.json"
        },
    }
    _write_json(output_path / "artifact_manifest.json", manifest)
    return DatasetBundle.load(output_path)


def run_offline_vertical_slice(
    bundle_root: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Run one Q=13/19/25 reference candidate through c_sem, M11, and M9."""

    bundle = DatasetBundle.load(bundle_root)
    references = {
        str(item["question_id"]): item
        for item in _read_jsonl(bundle.root / "reference_interpretations.jsonl")
    }
    workload = _read_jsonl(bundle.root / "workload_stats.jsonl")
    representatives: list[dict[str, Any]] = []
    for q_value in sorted({int(item["Q"]) for item in workload}):
        representatives.append(
            min(
                (item for item in workload if int(item["Q"]) == q_value),
                key=lambda item: str(item["question_id"]),
            )
        )

    registry.load_descriptors(Path(__file__).resolve().parents[3] / "descriptors" / "backends")
    profiles = tuple(
        registry.get_capability_profile(item)
        for item in ("reference_evaluator", "neo4j", "fuseki")
    )
    extractor = DeterministicStateFeatureExtractor(
        tuple(item.backend_id for item in profiles)
    )
    estimator = GaussianProcessCostEstimator(
        config=GaussianProcessConfig(model_version="m13c-prior-only-no-grailqa-d0"),
        feature_extractor=extractor,
        observations=(),
    )
    results: list[dict[str, Any]] = []
    for task_index, workload_record in enumerate(representatives, 1):
        question_id = str(workload_record["question_id"])
        question = bundle.question(question_id)
        reference = references[question_id]
        query = parse_path_pattern_query(reference["pattern_query"])
        candidate = PlannerCandidate(
            question=question.text,
            pattern_query=query,
            candidate_id=f"reference-{question_id}",
            confidence=1.0,
            metadata={"provider": "evaluation_only_controlled_reference"},
        )
        terms = tuple(question.ontology_slots or ())
        alignment_provider = ArtifactOntologyAlignmentProvider(
            {
                "artifact_version": 1,
                "ontology": {
                    "id": bundle.ontology.ontology_id,
                    "version": bundle.ontology.version,
                },
                "mapping": {
                    "id": bundle.backend_mapping["mapping_id"],
                    "version": bundle.backend_mapping["version"],
                },
                "interpretations": {
                    candidate.candidate_id: {
                        "alignment_id": f"vertical-slice-{question_id}",
                        "mapping_status": "sufficient",
                        "required_terms": list(terms),
                        "mapped_terms": list(terms),
                        "evidence": ["evaluation_only_reference_alignment"],
                        "semantic_inputs": {
                            "semantic_deviation": 0.0,
                            "components": {
                                "definition": "frozen_c_sem",
                                "normalized_ontology_hash": bundle.ontology.ontology_hash,
                            },
                        },
                    }
                },
            }
        )
        planner = XGAPPhysicalPlanner(
            alignment_provider=alignment_provider,
            semantic_scorer=ProvidedSemanticDeviationScorer(),
            backend_profiles=profiles,
            exchange_catalog=ExchangeCatalog(),
            budget_policy=FixedBudgetPolicy(500),
            cost_estimator=estimator,
            physical_compiler=ExistingCompilerAdapter(
                backend_mapping=bundle.backend_mapping
            ),
        )
        planning_result = planner.plan(
            query_context=QueryPlanningContext(
                query_id=question_id,
                task_id=f"grailqa-pilot-{question_id}",
                question=question.text,
                metadata={"evaluation_only_reference": True},
            ),
            candidates=(candidate,),
            config=PlanningConfig(
                run_id=f"m13c-grailqa-{question_id}",
                semantic_threshold=0.1,
                execution_threshold=1e12,
                top_k=1,
                global_delta=0.05,
                task_index=task_index,
                deterministic_seed=DEFAULT_SEED,
            ),
        )
        logical_plan = lower_to_logical_plan(query)
        indexed = index_logical_plan(logical_plan)
        cypher = compile_cypher(query, profile=registry.get_capability_profile("neo4j"))
        sparql = compile_sparql(
            query,
            profile=registry.get_capability_profile("fuseki"),
            backend_mapping=bundle.backend_mapping,
        )
        record = planning_result.candidate_records[0]
        results.append(
            {
                "question_id": question_id,
                "question": question.text,
                "Q": workload_record["Q"],
                "A_recommended": workload_record["A_recommended"],
                "candidate_provider": "evaluation_only_controlled_reference",
                "candidate": path_pattern_query_to_dict(query),
                "semantic_deviation": (
                    record.semantic_deviation.to_dict()
                    if record.semantic_deviation is not None
                    else None
                ),
                "logical_plan_id": indexed.logical_plan_id,
                "m11": {
                    "status": planning_result.status,
                    "reason": planning_result.reason,
                    "candidate_status": record.status,
                    "discovered_complete_plan_count": (
                        len(record.search.discovered_complete_plans)
                        if record.search is not None
                        else 0
                    ),
                    "selected_plan_count": len(planning_result.selected_plans),
                    "cost_model": "RBF GP prior only; no GrailQA D0",
                },
                "native_compilation": {
                    "neo4j": {"language": "cypher", "text": cypher.text},
                    "fuseki": {"language": "sparql", "text": sparql.text},
                },
                "execution": {
                    "status": "blocked",
                    "reason": "clean_public_freebase_execution_artifact_not_available",
                },
            }
        )

    physical = physical_realization_distribution(bundle, profiles)
    summary = {
        "schema_version": "m13c-grailqa-vertical-slice-v1",
        "status": "ok" if all(item["m11"]["selected_plan_count"] == 1 for item in results) else "failed",
        "representative_question_count": len(results),
        "Q_values": [item["Q"] for item in results],
        "pipeline": [
            "evaluation-only controlled candidate",
            "frozen c_sem",
            "PathPatternQuery lowering",
            "M11 physical planning",
            "M9 Cypher/SPARQL compilation",
        ],
        "results": results,
        "semantic_metrics": {
            "status": "pipeline_integrity_smoke_not_paper_measurement",
            "top_1_interpretation_accuracy": 1.0,
            "candidate_recall": 1.0,
            "feasible_coverage": 1.0,
            "question_count": len(results),
        },
        "physical_realizations": physical,
        "live_llm": {
            "status": "gated_not_run",
            "required": ["XGAP_RUN_LIVE_LLM=1", "DASHSCOPE_API_KEY"],
            "blocking_data_issue": (
                "No versioned public Freebase alias/entity catalog is frozen for "
                "inference-safe entity grounding."
            ),
            "prompt_changed": False,
        },
        "backend_execution": {
            "status": "blocked",
            "financial_risk_D0_reused": False,
            "grailqa_D0_created": False,
        },
    }
    _write_json(Path(output_path), summary)
    _refresh_artifact_manifest(bundle.root)
    return summary


def physical_realization_distribution(
    bundle: DatasetBundle,
    profiles: Sequence[object],
) -> dict[str, Any]:
    references = _read_jsonl(bundle.root / "reference_interpretations.jsonl")
    counts: list[int] = []
    for reference in references:
        query = parse_path_pattern_query(reference["pattern_query"])
        indexed = index_logical_plan(lower_to_logical_plan(query))
        count = sum(
            all(
                check_backend_support(profile, operator.feature_id).level
                is not SupportLevel.UNSUPPORTED
                for operator in indexed.operators
            )
            for profile in profiles
        )
        counts.append(count)
    ordered = sorted(counts)
    return {
        "scope": "M11 all-local complete logical-plan placements",
        "count": len(ordered),
        "min": min(ordered),
        "median": _percentile(ordered, 0.5),
        "p90": _percentile(ordered, 0.9),
        "max": max(ordered),
        "fraction_gt_1": sum(item > 1 for item in ordered) / len(ordered),
        "fraction_gt_2": sum(item > 2 for item in ordered) / len(ordered),
        "histogram": {
            str(key): value for key, value in sorted(Counter(ordered).items())
        },
        "native_compiler_targets_per_interpretation": 2,
        "note": (
            "M9 compiles the ALL PathPatternQuery fragment for both native backends, "
            "but current M11 full logical plans retain selector GroupBy/Projection, "
            "which native capability profiles do not claim."
        ),
    }


def _percentile(values: Sequence[int], fraction: float) -> int:
    return values[max(0, math.ceil(fraction * len(values)) - 1)]


def _pilot_distribution(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "split": dict(sorted(Counter(str(item["split"]) for item in records).items())),
        "Q": dict(
            sorted(Counter(str(item["logical_plan_size"]) for item in records).items())
        ),
        "path_length": dict(
            sorted(Counter(str(item["path_length"]) for item in records).items())
        ),
        "function": dict(sorted(Counter(str(item["function"]) for item in records).items())),
        "A_bucket": dict(
            sorted(
                Counter(
                    _ambiguity_bucket(int(item["ambiguity"]["A_recommended"]))
                    for item in records
                ).items()
            )
        ),
        "relation_domain_count": len(
            {
                str(next(iter(item["traversal_relations"]))).split(".", 1)[0]
                for item in records
            }
        ),
    }


def _load_gold_questions(dataset_root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for split in ("train", "dev"):
        values = json.loads((dataset_root / DATASET_FILES[split]).read_text(encoding="utf-8"))
        for value in values:
            record = dict(value)
            record["_split"] = split
            result[str(record["qid"])] = record
    return result


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for value in values:
            handle.write(json.dumps(value, sort_keys=True, ensure_ascii=True) + "\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _refresh_artifact_manifest(bundle_root: Path) -> None:
    manifest_path = bundle_root / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"] = {
        path.name: {"sha256": _sha256(path), "bytes": path.stat().st_size}
        for path in sorted(bundle_root.iterdir())
        if path.is_file() and path.name != manifest_path.name
    }
    _write_json(manifest_path, manifest)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and run the M13-C GrailQA pilot.")
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--ontology-root", required=True)
    parser.add_argument("--audit-root", default="datasets/grailqa_audit_v2")
    parser.add_argument("--output", default="datasets/grailqa_pilot_v1")
    parser.add_argument("--size", type=int, default=DEFAULT_SIZE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--skip-vertical-slice", action="store_true")
    args = parser.parse_args(argv)
    bundle = build_pilot_bundle(
        args.dataset_root,
        args.ontology_root,
        args.audit_root,
        args.output,
        size=args.size,
        seed=args.seed,
    )
    print(f"Built {bundle.dataset_id}: {len(bundle.questions)} questions, {bundle.bundle_hash}")
    if not args.skip_vertical_slice:
        summary = run_offline_vertical_slice(
            bundle.root,
            bundle.root / "vertical_slice_results.json",
        )
        print(f"Vertical slice: {summary['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
