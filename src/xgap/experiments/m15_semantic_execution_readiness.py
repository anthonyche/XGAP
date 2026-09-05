"""Audit which bounded semantic interpretations are executable today.

F2C7A binds the F2C6 solution-space mechanism to one verified F2C3 workload
bundle.  It separates already materialized interpretations, interpretations
that the current deterministic generator can safely materialize, and blocked
interpretations that still need semantics, data, compiler, or oracle work.
The audit makes no backend, ontology, or LLM call and produces no result claim.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_parameterized_workload import (
    PARAMETERIZED_PATH_QUANTIFIERS,
    PARAMETERIZED_RELATIONSHIP_TYPES,
    M15ParameterizedWorkloadBundle,
    load_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_semantic_frontier import (
    M15SemanticRelaxationCatalog,
    build_m15_semantic_solution_space,
    load_m15_semantic_relaxation_catalog,
)


SEMANTIC_EXECUTION_READINESS_SCHEMA_VERSION = (
    "m15-f2c7-semantic-execution-readiness-v1"
)
SEMANTIC_EXECUTION_CAPABILITY_VERSION = (
    "m15-f2c7-current-f2c3-executor-capabilities-v1"
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")


class M15SemanticExecutionReadinessError(ValueError):
    """Raised before output when the F2C7A readiness chain is invalid."""


@dataclass(frozen=True)
class M15SemanticExecutionReadiness:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15SemanticExecutionReadinessError(
            f"{name} must be a safe identifier"
        )
    return value


def _load_json_object(path: Path, *, name: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise M15SemanticExecutionReadinessError(
            f"{name} must be a regular non-symbolic-link file"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise M15SemanticExecutionReadinessError(f"{name} must be an object")
    return dict(payload)


def _concrete_query_spec(
    bundle: M15ParameterizedWorkloadBundle,
    query_id: str,
) -> tuple[dict[str, Any], Mapping[str, Any]]:
    matching = [
        item for item in bundle.spec.query_instances if item["query_id"] == query_id
    ]
    if len(matching) != 1:
        raise M15SemanticExecutionReadinessError(
            "query_id must identify exactly one workload instance"
        )
    instance = matching[0]
    template = _load_json_object(
        bundle.path("parameterized_query_template.json"),
        name="parameterized query template",
    )
    concrete = copy.deepcopy(template)
    concrete["query_id"] = query_id
    concrete["resolved_intent"] = instance["resolved_intent"]
    binding_values = dict(instance["binding_values"])
    slots = concrete.get("binding_slots")
    if not isinstance(slots, list):
        raise M15SemanticExecutionReadinessError(
            "parameterized query template binding_slots are invalid"
        )
    if {item.get("slot_id") for item in slots} != set(binding_values):
        raise M15SemanticExecutionReadinessError(
            "workload instance and query template binding coverage differ"
        )
    for slot in slots:
        slot["value"] = binding_values[slot["slot_id"]]
    return concrete, instance


def _bindings(value: Mapping[str, Any]) -> dict[str, Any]:
    records = value.get("bindings")
    if not isinstance(records, list):
        raise M15SemanticExecutionReadinessError(
            "semantic class bindings are invalid"
        )
    result: dict[str, Any] = {}
    for item in records:
        if not isinstance(item, Mapping):
            raise M15SemanticExecutionReadinessError(
                "semantic class binding must be an object"
            )
        slot_id = _safe_id(item.get("slot_id"), name="binding slot_id")
        if slot_id in result:
            raise M15SemanticExecutionReadinessError(
                "semantic class binding slot IDs must be unique"
            )
        result[slot_id] = item.get("value")
    return result


def _blockers(
    bindings: Mapping[str, Any],
    bundle: M15ParameterizedWorkloadBundle,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    risk = bindings.get("risk-level")
    predicate = bindings.get("transfer-predicate")
    path_shape = bindings.get("path-shape")
    if risk not in bundle.spec.risk_levels:
        result.extend(
            [
                {
                    "code": "risk_data_missing",
                    "slot_id": "risk-level",
                    "value": risk,
                },
                {
                    "code": "risk_oracle_support_missing",
                    "slot_id": "risk-level",
                    "value": risk,
                },
            ]
        )
    if predicate not in PARAMETERIZED_RELATIONSHIP_TYPES:
        result.extend(
            [
                {
                    "code": "predicate_backend_mapping_missing",
                    "slot_id": "transfer-predicate",
                    "value": predicate,
                },
                {
                    "code": "predicate_data_missing",
                    "slot_id": "transfer-predicate",
                    "value": predicate,
                },
                {
                    "code": "predicate_oracle_support_missing",
                    "slot_id": "transfer-predicate",
                    "value": predicate,
                },
            ]
        )
    if path_shape not in PARAMETERIZED_PATH_QUANTIFIERS:
        result.extend(
            [
                {
                    "code": "path_semantics_unbound",
                    "slot_id": "path-shape",
                    "value": path_shape,
                },
                {
                    "code": "path_backend_template_missing",
                    "slot_id": "path-shape",
                    "value": path_shape,
                },
                {
                    "code": "path_data_missing",
                    "slot_id": "path-shape",
                    "value": path_shape,
                },
                {
                    "code": "path_oracle_support_missing",
                    "slot_id": "path-shape",
                    "value": path_shape,
                },
            ]
        )
    return sorted(result, key=lambda item: (item["code"], str(item["value"])))


def audit_m15_semantic_execution_readiness(
    *,
    bundle: M15ParameterizedWorkloadBundle | str | Path,
    query_id: str,
    catalog: M15SemanticRelaxationCatalog | str | Path,
) -> M15SemanticExecutionReadiness:
    """Build a zero-call readiness matrix for one bundle-bound query."""

    selected_bundle = (
        bundle
        if isinstance(bundle, M15ParameterizedWorkloadBundle)
        else load_m15_parameterized_workload_bundle(bundle)
    )
    selected_catalog = (
        catalog
        if isinstance(catalog, M15SemanticRelaxationCatalog)
        else load_m15_semantic_relaxation_catalog(catalog)
    )
    selected_query_id = _safe_id(query_id, name="query_id")
    concrete_spec, instance = _concrete_query_spec(
        selected_bundle, selected_query_id
    )
    solution_space = build_m15_semantic_solution_space(
        concrete_spec, selected_catalog
    )
    space = solution_space.to_dict()
    if (
        space["family_compatibility_sha256"]
        != selected_bundle.manifest["family_compatibility_sha256"]
    ):
        raise M15SemanticExecutionReadinessError(
            "solution space and workload bundle families differ"
        )
    exact_classes = [
        item
        for item in space["semantic_equivalence_classes"]
        if item["semantic_deviation"] == 0
    ]
    if len(exact_classes) != 1:
        raise M15SemanticExecutionReadinessError(
            "solution space must contain exactly one exact semantic class"
        )
    exact_contract = _load_json_object(
        selected_bundle.path(
            f"instances/{selected_query_id}/parameterized_contract.json"
        ),
        name="bundle exact parameterized contract",
    )
    exact_class = exact_classes[0]
    if (
        exact_class["query_instance_sha256"]
        != exact_contract.get("query_instance_sha256")
        or exact_class["binding_sha256"] != exact_contract.get("binding_sha256")
    ):
        raise M15SemanticExecutionReadinessError(
            "solution-space exact interpretation is not bundle-bound"
        )

    bound_instance_hashes = {
        item["query_instance_sha256"]
        for item in selected_bundle.manifest["instances"]
    }
    exact_bindings = _bindings(exact_class)
    records: list[dict[str, Any]] = []
    blocker_counts: dict[str, int] = {}
    for semantic_class in space["semantic_equivalence_classes"]:
        bindings = _bindings(semantic_class)
        blockers = _blockers(bindings, selected_bundle)
        for blocker in blockers:
            blocker_counts[blocker["code"]] = (
                blocker_counts.get(blocker["code"], 0) + 1
            )
        materialized = (
            semantic_class["query_instance_sha256"] in bound_instance_hashes
        )
        if blockers:
            status = "blocked"
        elif materialized:
            status = "bound_ready"
        else:
            status = "overlay_generation_ready"
        changed_slots = sorted(
            slot_id
            for slot_id, value in bindings.items()
            if exact_bindings.get(slot_id) != value
        )
        records.append(
            {
                "semantic_class_id": semantic_class["semantic_class_id"],
                "query_instance_sha256": semantic_class[
                    "query_instance_sha256"
                ],
                "semantic_deviation": semantic_class["semantic_deviation"],
                "changed_slot_ids": changed_slots,
                "bindings": [
                    {"slot_id": slot_id, "value": bindings[slot_id]}
                    for slot_id in sorted(bindings)
                ],
                "backend_template_compilable": not blockers,
                "dataset_supported": not blockers,
                "oracle_generator_supported": not blockers,
                "bundle_artifacts_materialized": materialized,
                "status": status,
                "blockers": blockers,
            }
        )
    records.sort(key=lambda item: item["semantic_class_id"])
    status_counts = {
        status: sum(item["status"] == status for item in records)
        for status in ("bound_ready", "overlay_generation_ready", "blocked")
    }
    next_actions: list[dict[str, Any]] = []
    if status_counts["overlay_generation_ready"]:
        next_actions.append(
            {
                "action_id": "materialize-supported-relaxation-overlay",
                "requires_user_decision": False,
                "affected_semantic_class_count": status_counts[
                    "overlay_generation_ready"
                ],
            }
        )
    if any(key.startswith("predicate_") for key in blocker_counts):
        next_actions.append(
            {
                "action_id": "add-versioned-payment-data-compiler-and-oracle",
                "requires_user_decision": False,
                "affected_semantic_class_count": sum(
                    any(
                        blocker["code"].startswith("predicate_")
                        for blocker in item["blockers"]
                    )
                    for item in records
                ),
            }
        )
    if "path_semantics_unbound" in blocker_counts:
        next_actions.append(
            {
                "action_id": "freeze-multihop-hard-constraint-semantics",
                "requires_user_decision": True,
                "affected_semantic_class_count": blocker_counts[
                    "path_semantics_unbound"
                ],
            }
        )

    body = {
        "schema_version": SEMANTIC_EXECUTION_READINESS_SCHEMA_VERSION,
        "capability_version": SEMANTIC_EXECUTION_CAPABILITY_VERSION,
        "workload_id": selected_bundle.manifest["workload_id"],
        "workload_bundle_content_sha256": selected_bundle.manifest[
            "bundle_content_sha256"
        ],
        "query_id": selected_query_id,
        "split_role": instance["split_role"],
        "family_compatibility_sha256": space[
            "family_compatibility_sha256"
        ],
        "semantic_solution_space_sha256": solution_space.solution_space_hash,
        "semantic_catalog_sha256": space["catalog_sha256"],
        "current_executor_capabilities": {
            "risk_levels": list(selected_bundle.spec.risk_levels),
            "transfer_predicates": sorted(PARAMETERIZED_RELATIONSHIP_TYPES),
            "path_shapes": sorted(PARAMETERIZED_PATH_QUANTIFIERS),
        },
        "counts": {
            "semantic_classes": len(records),
            **status_counts,
        },
        "blocker_occurrence_counts": dict(sorted(blocker_counts.items())),
        "interpretations": records,
        "next_required_actions": next_actions,
        "claim_boundary": {
            "artifact_class": "semantic_execution_readiness_audit",
            "relaxed_backend_artifacts_executed": False,
            "semantic_answer_quality_validated": False,
            "backend_calls_made": 0,
            "llm_calls_made": 0,
            "ontology_calls_made": 0,
            "contains_measurements": False,
            "paper_result": False,
        },
        "automatic_retries": 0,
        "paper_result": False,
    }
    return M15SemanticExecutionReadiness(
        {**body, "readiness_sha256": content_hash(body)}
    )


def write_m15_semantic_execution_readiness(
    readiness: M15SemanticExecutionReadiness,
    output: str | Path,
) -> Path:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"semantic readiness output exists: {destination}")
    destination.write_text(
        json.dumps(
            readiness.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return destination


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", required=True)
    parser.add_argument("--query-id", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    try:
        readiness = audit_m15_semantic_execution_readiness(
            bundle=arguments.bundle_root,
            query_id=arguments.query_id,
            catalog=arguments.catalog,
        )
        write_m15_semantic_execution_readiness(readiness, arguments.output)
    except (FileExistsError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(
        json.dumps(
            {"status": "success", **readiness.to_dict()},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
