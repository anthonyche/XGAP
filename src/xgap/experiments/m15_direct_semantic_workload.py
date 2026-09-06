"""Compile the F2C10A preserve-all direct-semantic development workload.

The compiler expands every frozen base query into every executable direct
semantic class admitted by the catalog.  It preserves the base query's split
role, keeps answer artifacts outside selection views, and performs no backend,
LLM, or ontology-service call.  The development population is a mechanism and
leakage gate only, not paper evidence.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_parameterized_federation import (
    build_m15_parameterized_plan_candidates,
    load_m15_parameterized_contract,
)
from xgap.experiments.m15_parameterized_workload import (
    M15ParameterizedWorkloadBundle,
    M15ParameterizedWorkloadSpec,
    load_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_predicate_overlay import (
    M15PredicateMappingSpec,
    _load_predicate_workload_bundle,
    _write_bundle,
    build_m15_catalog_bound_direct_semantic_classes,
)
from xgap.experiments.m15_semantic_frontier import (
    M15SemanticRelaxationCatalog,
    load_m15_semantic_relaxation_catalog,
)


DIRECT_SEMANTIC_WORKLOAD_SCHEMA_VERSION = (
    "m15-f2c10-direct-semantic-workload-v1"
)
DIRECT_SEMANTIC_WORKLOAD_POLICY_SCHEMA_VERSION = (
    "m15-f2c10-direct-semantic-workload-policy-v1"
)
DIRECT_SEMANTIC_WORKLOAD_GENERATOR_VERSION = (
    "m15-f2c10-direct-semantic-workload-generator-v1"
)
DIRECT_SEMANTIC_SELECTION_VIEW_SCHEMA_VERSION = (
    "m15-f2c10-direct-semantic-selection-view-v1"
)
DIRECT_SEMANTIC_EVALUATION_REGISTRY_SCHEMA_VERSION = (
    "m15-f2c10-direct-semantic-evaluation-registry-v1"
)
_HARD_SLOT_IDS = (
    "amount-lower-bound",
    "person-identity",
    "time-lower-bound",
)
_ROOT_MEMBERS = {
    "manifest.json",
    "training_selection_view.json",
    "heldout_selection_view.json",
    "evaluation_registry.json",
    "cardinality_policy.json",
    "parameterized-workload-bundle",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class M15DirectSemanticWorkloadError(ValueError):
    """Raised when the preserve-all workload or split boundary drifts."""


@dataclass(frozen=True)
class M15DirectSemanticWorkloadBundle:
    root: Path
    workload_bundle: M15ParameterizedWorkloadBundle
    manifest: Mapping[str, Any]
    training_selection_view: Mapping[str, Any]
    heldout_selection_view: Mapping[str, Any]
    evaluation_registry: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.manifest))


def _json_text(value: object) -> str:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _regular_json_object(path: Path, *, name: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise M15DirectSemanticWorkloadError(
            f"{name} must be a regular non-symbolic-link file"
        )
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise M15DirectSemanticWorkloadError(f"{name} must be an object")
    return dict(value)


def _selected_base(
    value: M15ParameterizedWorkloadBundle | str | Path,
) -> M15ParameterizedWorkloadBundle:
    return (
        value
        if isinstance(value, M15ParameterizedWorkloadBundle)
        else load_m15_parameterized_workload_bundle(value)
    )


def _selected_catalog(
    value: M15SemanticRelaxationCatalog | str | Path,
) -> M15SemanticRelaxationCatalog:
    return (
        value
        if isinstance(value, M15SemanticRelaxationCatalog)
        else load_m15_semantic_relaxation_catalog(value)
    )


def _selected_mapping(
    value: M15PredicateMappingSpec | str | Path,
) -> M15PredicateMappingSpec:
    return (
        value
        if isinstance(value, M15PredicateMappingSpec)
        else M15PredicateMappingSpec.from_json(value)
    )


def _selected_policy(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    raw = (
        copy.deepcopy(dict(value))
        if isinstance(value, Mapping)
        else _regular_json_object(Path(value), name="direct semantic policy")
    )
    fields = {
        "schema_version",
        "policy_id",
        "preserve_all_catalog_adjacent_interpretations",
        "executable_path_shapes",
        "expected_direct_semantic_classes_by_base_risk",
        "physical_strategies",
        "physical_candidates_per_class",
        "post_enumeration_bound",
        "hard_slot_ids",
        "automatic_retries",
        "paper_result",
    }
    if set(raw) != fields:
        raise M15DirectSemanticWorkloadError(
            "direct semantic policy fields do not match the contract"
        )
    if raw["schema_version"] != DIRECT_SEMANTIC_WORKLOAD_POLICY_SCHEMA_VERSION:
        raise M15DirectSemanticWorkloadError(
            "direct semantic policy schema is unsupported"
        )
    if raw["policy_id"] != "preserve-all-catalog-adjacent-direct-v1":
        raise M15DirectSemanticWorkloadError("direct semantic policy ID changed")
    if raw["preserve_all_catalog_adjacent_interpretations"] is not True:
        raise M15DirectSemanticWorkloadError(
            "direct semantic policy must preserve every adjacent interpretation"
        )
    if raw["executable_path_shapes"] != ["direct"]:
        raise M15DirectSemanticWorkloadError(
            "only direct path semantics are approved"
        )
    if raw["expected_direct_semantic_classes_by_base_risk"] != {
        "HIGH": 4,
        "LOW": 4,
        "MEDIUM": 6,
    }:
        raise M15DirectSemanticWorkloadError(
            "direct semantic risk cardinalities changed"
        )
    if raw["physical_strategies"] != [
        "parallel_hash_join",
        "risk_first_bind_join",
    ] or raw["physical_candidates_per_class"] != 2:
        raise M15DirectSemanticWorkloadError(
            "direct semantic physical strategy contract changed"
        )
    if raw["post_enumeration_bound"] != (
        "physical_then_pareto_then_epsilon_then_k"
    ):
        raise M15DirectSemanticWorkloadError(
            "direct semantic frontier order changed"
        )
    if raw["hard_slot_ids"] != list(_HARD_SLOT_IDS):
        raise M15DirectSemanticWorkloadError(
            "direct semantic hard-slot contract changed"
        )
    if raw["automatic_retries"] != 0 or raw["paper_result"] is not False:
        raise M15DirectSemanticWorkloadError(
            "direct semantic policy claim boundary changed"
        )
    return raw


def _query_id(base_query_id: str, semantic_class_id: str) -> str:
    return (
        f"{base_query_id}-relaxed-"
        f"{semantic_class_id.removeprefix('m15-class-')}"
    )


def _task_id(base_query_id: str, semantic_class_id: str) -> str:
    return "m15-f2c10-task-" + content_hash(
        {
            "base_query_id": base_query_id,
            "semantic_class_id": semantic_class_id,
        }
    )[:24]


def _compile_tasks(
    *,
    base_bundle: M15ParameterizedWorkloadBundle,
    catalog: M15SemanticRelaxationCatalog,
    mapping: M15PredicateMappingSpec,
    policy: Mapping[str, Any],
) -> tuple[M15ParameterizedWorkloadSpec, list[dict[str, Any]], list[dict[str, Any]]]:
    if base_bundle.manifest["family_compatibility_sha256"] != (
        mapping.family_compatibility_sha256
    ):
        raise M15DirectSemanticWorkloadError(
            "base workload and predicate mapping families differ"
        )
    spec_payload = base_bundle.spec.to_dict()
    base_instances = {
        str(item["query_id"]): item for item in base_bundle.spec.query_instances
    }
    base_manifest_records = {
        str(item["query_id"]): item for item in base_bundle.manifest["instances"]
    }
    tasks: list[dict[str, Any]] = []
    base_records: list[dict[str, Any]] = []
    additions: list[dict[str, Any]] = []
    for base_instance in base_bundle.spec.query_instances:
        base_query_id = str(base_instance["query_id"])
        split_role = str(base_instance["split_role"])
        base_bindings = copy.deepcopy(dict(base_instance["binding_values"]))
        solution, direct_classes, exact_bindings = (
            build_m15_catalog_bound_direct_semantic_classes(
                bundle=base_bundle,
                query_id=base_query_id,
                catalog=catalog,
                mapping=mapping,
            )
        )
        if exact_bindings != base_bindings:
            raise M15DirectSemanticWorkloadError(
                "base semantic bindings changed during direct compilation"
            )
        solution_payload = solution.to_dict()
        direct_classes = sorted(
            direct_classes,
            key=lambda item: (
                float(item["semantic_deviation"]),
                str(item["semantic_class_id"]),
            ),
        )
        exact_classes = [
            item
            for item in direct_classes
            if not item["changed_slot_ids"]
            and float(item["semantic_deviation"]) == 0
        ]
        if len(exact_classes) != 1:
            raise M15DirectSemanticWorkloadError(
                "each base query requires exactly one exact direct class"
            )
        expected_direct = policy[
            "expected_direct_semantic_classes_by_base_risk"
        ][base_bindings["risk-level"]]
        if len(direct_classes) != expected_direct:
            raise M15DirectSemanticWorkloadError(
                "catalog-derived direct class cardinality is unexpected"
            )
        all_class_ids = {
            str(item["semantic_class_id"])
            for item in solution_payload["semantic_equivalence_classes"]
        }
        direct_class_ids = {
            str(item["semantic_class_id"]) for item in direct_classes
        }
        unavailable = sorted(all_class_ids - direct_class_ids)
        base_records.append(
            {
                "base_query_id": base_query_id,
                "split_role": split_role,
                "base_risk_level": base_bindings["risk-level"],
                "base_query_instance_sha256": solution_payload[
                    "base_query_instance_sha256"
                ],
                "source_solution_space_sha256": solution.solution_space_hash,
                "declared_semantic_class_count": len(all_class_ids),
                "direct_semantic_class_count": len(direct_classes),
                "physical_candidate_count": 2 * len(direct_classes),
                "direct_semantic_class_ids": sorted(direct_class_ids),
                "unavailable_semantic_class_ids": unavailable,
            }
        )
        for semantic_class in direct_classes:
            semantic_class_id = str(semantic_class["semantic_class_id"])
            changed = list(semantic_class["changed_slot_ids"])
            target_bindings = copy.deepcopy(
                dict(semantic_class["binding_values"])
            )
            if any(
                target_bindings[slot_id] != base_bindings[slot_id]
                for slot_id in _HARD_SLOT_IDS
            ):
                raise M15DirectSemanticWorkloadError(
                    "a direct semantic class changed a hard binding"
                )
            if target_bindings["path-shape"] != "direct":
                raise M15DirectSemanticWorkloadError(
                    "a non-direct class entered the executable workload"
                )
            executable_query_id = (
                base_query_id
                if not changed
                else _query_id(base_query_id, semantic_class_id)
            )
            if changed:
                addition = {
                    "query_id": executable_query_id,
                    "resolved_intent": (
                        "Development direct semantic interpretation "
                        f"{semantic_class_id} derived from {base_query_id}."
                    ),
                    "split_role": split_role,
                    "binding_values": target_bindings,
                }
                spec_payload["query_instances"].append(addition)
                additions.append(addition)
            tasks.append(
                {
                    "semantic_task_id": _task_id(
                        base_query_id, semantic_class_id
                    ),
                    "base_query_id": base_query_id,
                    "executable_query_id": executable_query_id,
                    "split_role": split_role,
                    "base_risk_level": base_bindings["risk-level"],
                    "source_solution_space_sha256": solution.solution_space_hash,
                    "semantic_class_id": semantic_class_id,
                    "canonical_interpretation_id": semantic_class[
                        "canonical_interpretation_id"
                    ],
                    "semantic_deviation": float(
                        semantic_class["semantic_deviation"]
                    ),
                    "semantic_deviation_fraction": dict(
                        semantic_class["semantic_deviation_fraction"]
                    ),
                    "changed_slot_ids": changed,
                    "base_binding_sha256": base_manifest_records[base_query_id][
                        "binding_sha256"
                    ],
                    "target_binding_sha256": semantic_class["binding_sha256"],
                    "base_query_instance_sha256": solution_payload[
                        "base_query_instance_sha256"
                    ],
                    "target_query_instance_sha256": semantic_class[
                        "query_instance_sha256"
                    ],
                    "binding_values": target_bindings,
                }
            )
    spec = M15ParameterizedWorkloadSpec.from_dict(spec_payload)
    task_ids = [item["semantic_task_id"] for item in tasks]
    query_ids = [item["executable_query_id"] for item in tasks]
    if len(task_ids) != len(set(task_ids)) or len(query_ids) != len(set(query_ids)):
        raise M15DirectSemanticWorkloadError(
            "semantic task or executable query IDs are not unique"
        )
    if len(additions) != len(tasks) - len(base_instances):
        raise M15DirectSemanticWorkloadError(
            "non-exact semantic additions are incomplete"
        )
    return spec, tasks, base_records


def _selection_task(
    task: Mapping[str, Any],
    workload: M15ParameterizedWorkloadBundle,
) -> dict[str, Any]:
    query_id = str(task["executable_query_id"])
    contract = load_m15_parameterized_contract(workload, query_id)["contract"]
    if contract["query_instance_sha256"] != task["target_query_instance_sha256"]:
        raise M15DirectSemanticWorkloadError(
            "semantic class and executable query identities differ"
        )
    plans = build_m15_parameterized_plan_candidates(workload, query_id=query_id)
    if len(plans) != 2:
        raise M15DirectSemanticWorkloadError(
            "each direct semantic task requires two physical candidates"
        )
    return {
        **copy.deepcopy(dict(task)),
        "physical_candidates": sorted(
            [
                {
                    "plan_id": item.plan.plan_id,
                    "physical_strategy": item.plan.metadata[
                        "physical_strategy"
                    ],
                }
                for item in plans
            ],
            key=lambda item: item["plan_id"],
        ),
    }


def _selection_view(
    *,
    split_role: str,
    tasks: Sequence[Mapping[str, Any]],
    base_bundle: M15ParameterizedWorkloadBundle,
    workload: M15ParameterizedWorkloadBundle,
) -> dict[str, Any]:
    selected = [
        _selection_task(item, workload)
        for item in tasks
        if item["split_role"] == split_role
    ]
    body = {
        "schema_version": DIRECT_SEMANTIC_SELECTION_VIEW_SCHEMA_VERSION,
        "split_role": split_role,
        "base_workload_bundle_content_sha256": base_bundle.manifest[
            "bundle_content_sha256"
        ],
        "direct_workload_bundle_content_sha256": workload.manifest[
            "bundle_content_sha256"
        ],
        "family_compatibility_sha256": workload.manifest[
            "family_compatibility_sha256"
        ],
        "base_query_ids": sorted(
            {str(item["base_query_id"]) for item in selected}
        ),
        "semantic_task_count": len(selected),
        "physical_candidate_count": 2 * len(selected),
        "semantic_tasks": sorted(
            selected,
            key=lambda item: (
                item["base_query_id"],
                item["semantic_deviation"],
                item["semantic_class_id"],
            ),
        ),
        "answer_artifacts_visible": False,
        "post_execution_measurements_used": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    view = {**body, "selection_view_sha256": content_hash(body)}
    serialized = json.dumps(view, sort_keys=True).lower()
    if "oracle" in serialized or "expected_result" in serialized:
        raise M15DirectSemanticWorkloadError(
            "selection view leaks an answer artifact"
        )
    return view


def _evaluation_registry(
    *,
    tasks: Sequence[Mapping[str, Any]],
    workload: M15ParameterizedWorkloadBundle,
) -> dict[str, Any]:
    records_by_query = {
        str(item["query_id"]): item for item in workload.manifest["instances"]
    }
    hashes = workload.manifest["files_sha256"]
    records: list[dict[str, Any]] = []
    for task in tasks:
        query_id = str(task["executable_query_id"])
        instance = records_by_query[query_id]
        root = f"instances/{query_id}"
        records.append(
            {
                "semantic_task_id": task["semantic_task_id"],
                "base_query_id": task["base_query_id"],
                "executable_query_id": query_id,
                "split_role": task["split_role"],
                "semantic_class_id": task["semantic_class_id"],
                "target_query_instance_sha256": task[
                    "target_query_instance_sha256"
                ],
                "source_oracle": {
                    "path": f"{root}/expected_source_results.json",
                    "sha256": hashes[f"{root}/expected_source_results.json"],
                    "counts": {
                        key: value
                        for key, value in instance["oracle_counts"].items()
                        if key != "final"
                    },
                },
                "final_oracle": {
                    "path": f"{root}/expected_result.json",
                    "sha256": hashes[f"{root}/expected_result.json"],
                    "row_count": instance["oracle_counts"]["final"],
                },
            }
        )
    body = {
        "schema_version": DIRECT_SEMANTIC_EVALUATION_REGISTRY_SCHEMA_VERSION,
        "direct_workload_bundle_content_sha256": workload.manifest[
            "bundle_content_sha256"
        ],
        "semantic_task_count": len(records),
        "records": sorted(records, key=lambda item: item["semantic_task_id"]),
        "selection_input": False,
        "opened_only_after_selection": True,
        "automatic_retries": 0,
        "paper_result": False,
    }
    return {**body, "evaluation_registry_sha256": content_hash(body)}


def _manifest(
    *,
    base_bundle: M15ParameterizedWorkloadBundle,
    catalog: M15SemanticRelaxationCatalog,
    mapping: M15PredicateMappingSpec,
    policy: Mapping[str, Any],
    workload: M15ParameterizedWorkloadBundle,
    tasks: Sequence[Mapping[str, Any]],
    base_records: Sequence[Mapping[str, Any]],
    training_view: Mapping[str, Any],
    heldout_view: Mapping[str, Any],
    evaluation_registry: Mapping[str, Any],
    file_hashes: Mapping[str, str],
) -> dict[str, Any]:
    direct_count = len(tasks)
    physical_count = 2 * direct_count
    unavailable_count = sum(
        len(item["unavailable_semantic_class_ids"]) for item in base_records
    )
    body = {
        "schema_version": DIRECT_SEMANTIC_WORKLOAD_SCHEMA_VERSION,
        "generator_version": DIRECT_SEMANTIC_WORKLOAD_GENERATOR_VERSION,
        "base_workload_bundle_content_sha256": base_bundle.manifest[
            "bundle_content_sha256"
        ],
        "direct_workload_bundle_content_sha256": workload.manifest[
            "bundle_content_sha256"
        ],
        "semantic_catalog_sha256": catalog.catalog_hash,
        "predicate_mapping_sha256": content_hash(mapping.to_dict()),
        "cardinality_policy_sha256": content_hash(policy),
        "family_compatibility_sha256": workload.manifest[
            "family_compatibility_sha256"
        ],
        "cardinality_policy": copy.deepcopy(dict(policy)),
        "hard_slot_ids": list(_HARD_SLOT_IDS),
        "base_queries": [copy.deepcopy(dict(item)) for item in base_records],
        "counts": {
            "base_query_instances": len(base_records),
            "exact_semantic_tasks": len(base_records),
            "relaxed_semantic_tasks": direct_count - len(base_records),
            "direct_semantic_tasks": direct_count,
            "unavailable_multihop_semantic_classes": unavailable_count,
            "physical_candidates": physical_count,
            "training_base_queries": len(training_view["base_query_ids"]),
            "heldout_base_queries": len(heldout_view["base_query_ids"]),
            "training_semantic_tasks": training_view["semantic_task_count"],
            "heldout_semantic_tasks": heldout_view["semantic_task_count"],
            "augmented_query_instances": workload.manifest["counts"][
                "query_instances"
            ],
            "payment_edges": workload.manifest["counts"]["payment_edges"],
        },
        "selection_views": {
            "training": training_view["selection_view_sha256"],
            "heldout": heldout_view["selection_view_sha256"],
        },
        "evaluation_registry_sha256": evaluation_registry[
            "evaluation_registry_sha256"
        ],
        "files_sha256": dict(file_hashes),
        "claim_boundary": {
            "artifact_class": "unexecuted_direct_semantic_development_workload",
            "preserve_all_adjacent_direct_interpretations": True,
            "multihop_classes_materialized": False,
            "hard_bindings_preserved": True,
            "split_frozen_before_measurement": True,
            "evaluation_artifacts_excluded_from_selection_views": True,
            "backend_calls_made": 0,
            "llm_calls_made": 0,
            "ontology_service_calls_made": 0,
            "contains_measurements": False,
            "development_population_only": True,
            "paper_result": False,
        },
        "automatic_retries": 0,
        "paper_result": False,
    }
    return {**body, "manifest_sha256": content_hash(body)}


def _artifact_payloads(
    *,
    base_bundle: M15ParameterizedWorkloadBundle,
    catalog: M15SemanticRelaxationCatalog,
    mapping: M15PredicateMappingSpec,
    policy: Mapping[str, Any],
    workload: M15ParameterizedWorkloadBundle,
    tasks: Sequence[Mapping[str, Any]],
    base_records: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    training = _selection_view(
        split_role="seed",
        tasks=tasks,
        base_bundle=base_bundle,
        workload=workload,
    )
    heldout = _selection_view(
        split_role="heldout_instance",
        tasks=tasks,
        base_bundle=base_bundle,
        workload=workload,
    )
    evaluation = _evaluation_registry(tasks=tasks, workload=workload)
    texts = {
        "training_selection_view.json": _json_text(training),
        "heldout_selection_view.json": _json_text(heldout),
        "evaluation_registry.json": _json_text(evaluation),
        "cardinality_policy.json": _json_text(policy),
    }
    manifest = _manifest(
        base_bundle=base_bundle,
        catalog=catalog,
        mapping=mapping,
        policy=policy,
        workload=workload,
        tasks=tasks,
        base_records=base_records,
        training_view=training,
        heldout_view=heldout,
        evaluation_registry=evaluation,
        file_hashes={
            path: _sha256_bytes(text.encode("utf-8"))
            for path, text in texts.items()
        },
    )
    return manifest, training, heldout, evaluation


def generate_m15_direct_semantic_workload_bundle(
    *,
    base_bundle: M15ParameterizedWorkloadBundle | str | Path,
    catalog: M15SemanticRelaxationCatalog | str | Path,
    mapping: M15PredicateMappingSpec | str | Path,
    policy: Mapping[str, Any] | str | Path,
    destination: str | Path,
) -> M15DirectSemanticWorkloadBundle:
    """Build the sealed F2C10A development workload without external calls."""

    selected_base = _selected_base(base_bundle)
    selected_catalog = _selected_catalog(catalog)
    selected_mapping = _selected_mapping(mapping)
    selected_policy = _selected_policy(policy)
    spec, tasks, base_records = _compile_tasks(
        base_bundle=selected_base,
        catalog=selected_catalog,
        mapping=selected_mapping,
        policy=selected_policy,
    )
    destination_path = Path(destination).resolve()
    if destination_path.exists():
        raise FileExistsError(
            f"direct semantic workload destination exists: {destination_path}"
        )
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{destination_path.name}.tmp-",
            dir=destination_path.parent,
        )
    )
    try:
        workload = _write_bundle(
            destination=temporary / "parameterized-workload-bundle",
            base_bundle=selected_base,
            spec=spec,
            mapping=selected_mapping,
        )
        manifest, training, heldout, evaluation = _artifact_payloads(
            base_bundle=selected_base,
            catalog=selected_catalog,
            mapping=selected_mapping,
            policy=selected_policy,
            workload=workload,
            tasks=tasks,
            base_records=base_records,
        )
        for filename, payload in {
            "manifest.json": manifest,
            "training_selection_view.json": training,
            "heldout_selection_view.json": heldout,
            "evaluation_registry.json": evaluation,
            "cardinality_policy.json": selected_policy,
        }.items():
            (temporary / filename).write_text(
                _json_text(payload), encoding="utf-8"
            )
        load_m15_direct_semantic_workload_bundle(
            temporary,
            base_bundle=selected_base,
            catalog=selected_catalog,
            mapping=selected_mapping,
        )
        os.replace(temporary, destination_path)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return load_m15_direct_semantic_workload_bundle(
        destination_path,
        base_bundle=selected_base,
        catalog=selected_catalog,
        mapping=selected_mapping,
    )


def load_m15_direct_semantic_workload_bundle(
    root: str | Path,
    *,
    base_bundle: M15ParameterizedWorkloadBundle | str | Path,
    catalog: M15SemanticRelaxationCatalog | str | Path,
    mapping: M15PredicateMappingSpec | str | Path,
) -> M15DirectSemanticWorkloadBundle:
    """Reconstruct and verify an F2C10A workload and its leakage boundary."""

    selected_base = _selected_base(base_bundle)
    selected_catalog = _selected_catalog(catalog)
    selected_mapping = _selected_mapping(mapping)
    bundle_root = Path(root).resolve()
    if bundle_root.is_symlink() or not bundle_root.is_dir():
        raise M15DirectSemanticWorkloadError(
            "direct semantic workload root must be a regular directory"
        )
    if any(path.is_symlink() for path in bundle_root.rglob("*")):
        raise M15DirectSemanticWorkloadError(
            "direct semantic workload cannot contain symlinks"
        )
    if {path.name for path in bundle_root.iterdir()} != _ROOT_MEMBERS:
        raise M15DirectSemanticWorkloadError(
            "direct semantic workload root members are invalid"
        )
    manifest = _regular_json_object(bundle_root / "manifest.json", name="manifest")
    training = _regular_json_object(
        bundle_root / "training_selection_view.json",
        name="training selection view",
    )
    heldout = _regular_json_object(
        bundle_root / "heldout_selection_view.json",
        name="heldout selection view",
    )
    evaluation = _regular_json_object(
        bundle_root / "evaluation_registry.json",
        name="evaluation registry",
    )
    policy = _selected_policy(
        _regular_json_object(
            bundle_root / "cardinality_policy.json",
            name="embedded direct semantic policy",
        )
    )
    for name, payload, schema, hash_field in (
        (
            "training selection view",
            training,
            DIRECT_SEMANTIC_SELECTION_VIEW_SCHEMA_VERSION,
            "selection_view_sha256",
        ),
        (
            "heldout selection view",
            heldout,
            DIRECT_SEMANTIC_SELECTION_VIEW_SCHEMA_VERSION,
            "selection_view_sha256",
        ),
        (
            "evaluation registry",
            evaluation,
            DIRECT_SEMANTIC_EVALUATION_REGISTRY_SCHEMA_VERSION,
            "evaluation_registry_sha256",
        ),
    ):
        if payload.get("schema_version") != schema:
            raise M15DirectSemanticWorkloadError(f"{name} schema is unsupported")
        recorded_hash = payload.get(hash_field)
        if not isinstance(recorded_hash, str) or not _SHA256.fullmatch(
            recorded_hash
        ):
            raise M15DirectSemanticWorkloadError(f"{name} hash is invalid")
        body = {key: value for key, value in payload.items() if key != hash_field}
        if content_hash(body) != recorded_hash:
            raise M15DirectSemanticWorkloadError(f"{name} hash mismatch")
    if manifest.get("schema_version") != DIRECT_SEMANTIC_WORKLOAD_SCHEMA_VERSION:
        raise M15DirectSemanticWorkloadError("manifest schema is unsupported")
    if manifest.get("generator_version") != (
        DIRECT_SEMANTIC_WORKLOAD_GENERATOR_VERSION
    ):
        raise M15DirectSemanticWorkloadError("manifest generator is unsupported")
    recorded_manifest_hash = manifest.get("manifest_sha256")
    manifest_body = {
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    }
    if (
        not isinstance(recorded_manifest_hash, str)
        or not _SHA256.fullmatch(recorded_manifest_hash)
        or content_hash(manifest_body) != recorded_manifest_hash
    ):
        raise M15DirectSemanticWorkloadError("manifest hash mismatch")
    file_hashes = manifest.get("files_sha256")
    if not isinstance(file_hashes, Mapping) or set(file_hashes) != {
        "training_selection_view.json",
        "heldout_selection_view.json",
        "evaluation_registry.json",
        "cardinality_policy.json",
    }:
        raise M15DirectSemanticWorkloadError("manifest file hashes are invalid")
    for filename, expected_hash in file_hashes.items():
        if not isinstance(expected_hash, str) or not _SHA256.fullmatch(expected_hash):
            raise M15DirectSemanticWorkloadError("manifest member hash is invalid")
        if _sha256_bytes((bundle_root / filename).read_bytes()) != expected_hash:
            raise M15DirectSemanticWorkloadError(
                f"direct semantic workload SHA-256 mismatch: {filename}"
            )
    spec, tasks, base_records = _compile_tasks(
        base_bundle=selected_base,
        catalog=selected_catalog,
        mapping=selected_mapping,
        policy=policy,
    )
    workload = _load_predicate_workload_bundle(
        bundle_root / "parameterized-workload-bundle",
        base_bundle=selected_base,
        expected_spec=spec,
        mapping=selected_mapping,
    )
    expected = _artifact_payloads(
        base_bundle=selected_base,
        catalog=selected_catalog,
        mapping=selected_mapping,
        policy=policy,
        workload=workload,
        tasks=tasks,
        base_records=base_records,
    )
    if (manifest, training, heldout, evaluation) != expected:
        raise M15DirectSemanticWorkloadError(
            "direct semantic workload is not deterministic"
        )
    return M15DirectSemanticWorkloadBundle(
        bundle_root,
        workload,
        manifest,
        training,
        heldout,
        evaluation,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-bundle-root", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    bundle = generate_m15_direct_semantic_workload_bundle(
        base_bundle=args.base_bundle_root,
        catalog=args.catalog,
        mapping=args.mapping,
        policy=args.policy,
        destination=args.output,
    )
    print(_json_text(bundle.to_dict()), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
