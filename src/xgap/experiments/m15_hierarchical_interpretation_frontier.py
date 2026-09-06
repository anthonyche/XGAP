"""Hierarchical unresolved-interpretation and anchored-relaxation selection.

E5 deliberately does not force unresolved meanings into the older global
semantic-deviation frontier.  It first predicts and reduces physical plans
within each interpretation, then applies the author-selected R1 semantic
structure gate across interpretations.  Only an authoritative in-set
structural choice can make a group execution-eligible.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_family_prediction import (
    M15DirectTrainingMemoryView,
    build_m15_family_cost_target_predictions,
)
from xgap.experiments.m15_direct_semantic_workload import (
    M15DirectSemanticWorkloadBundle,
)
from xgap.experiments.m15_resolution_execution_bridge import (
    M15ResolutionExecutionBridgePlan,
    RESOLUTION_EXECUTION_BRIDGE_PLAN_SCHEMA_VERSION,
)


HIERARCHICAL_INTERPRETATION_POLICY_SCHEMA_VERSION = (
    "m15-e5-hierarchical-interpretation-policy-v1"
)
HIERARCHICAL_INTERPRETATION_FRONTIER_SCHEMA_VERSION = (
    "m15-e5-hierarchical-interpretation-frontier-v1"
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STRUCTURAL_DIMENSIONS = [
    "aggregation_operator",
    "path_structure",
    "quantification",
    "answer_meaning",
    "output_contract",
    "executable_capability",
]
_RELATIONSHIP_AGGREGATIONS = {
    "qualifying_single_transfer": {
        "quantification": "existential_qualifying_edge",
        "answer_meaning": "company_with_qualifying_single_transfer",
        "output_contract": "qualifying_transfer_rows",
    },
    "window_total_amount": {
        "quantification": "window_group_sum_threshold",
        "answer_meaning": "company_with_cumulative_window_exposure",
        "output_contract": "company_window_aggregate_rows",
    },
    "window_transfer_count": {
        "quantification": "window_group_count_threshold",
        "answer_meaning": "company_with_frequent_window_transfers",
        "output_contract": "company_window_aggregate_rows",
    },
}


class M15HierarchicalInterpretationFrontierError(ValueError):
    """Raised before selection when an E5 policy or input boundary drifts."""


@dataclass(frozen=True)
class M15HierarchicalInterpretationFrontier:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))

    @property
    def frontier_hash(self) -> str:
        return str(self.payload["hierarchical_frontier_sha256"])


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15HierarchicalInterpretationFrontierError(
            f"{name} is not a safe identifier"
        )
    return value


def _sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise M15HierarchicalInterpretationFrontierError(
            f"{name} is not a SHA-256 digest"
        )
    return value


def _object(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise M15HierarchicalInterpretationFrontierError(
            f"{name} must be an object"
        )
    return copy.deepcopy(dict(value))


def _json_object(
    value: Mapping[str, Any] | str | Path,
    *,
    name: str,
) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise M15HierarchicalInterpretationFrontierError(
            f"{name} must be a regular non-symbolic-link file"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _object(payload, name=name)


def _policy(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    raw = _json_object(value, name="hierarchical interpretation policy")
    expected_fields = {
        "schema_version",
        "policy_id",
        "clarification_rule",
        "physical_reduction",
        "semantic_reduction",
        "clarification_options",
        "oracle_inputs",
        "post_execution_measurements_used",
        "backend_calls_made",
        "llm_calls_made",
        "ontology_service_calls_made",
        "automatic_retries",
        "paper_result",
    }
    if set(raw) != expected_fields:
        raise M15HierarchicalInterpretationFrontierError(
            "hierarchical interpretation policy fields do not match the contract"
        )
    if raw["schema_version"] != HIERARCHICAL_INTERPRETATION_POLICY_SCHEMA_VERSION:
        raise M15HierarchicalInterpretationFrontierError(
            "hierarchical interpretation policy schema is unsupported"
        )
    if raw["policy_id"] != "m15-e5-option-a-r1-development-v1":
        raise M15HierarchicalInterpretationFrontierError(
            "hierarchical interpretation policy ID changed"
        )
    rule = _object(raw["clarification_rule"], name="clarification_rule")
    if set(rule) != {
        "rule_id",
        "decisive_dimensions",
        "structural_hole_ids",
        "representative_hole_ids",
        "question_templates",
        "execution_when_structurally_unresolved",
    }:
        raise M15HierarchicalInterpretationFrontierError(
            "clarification rule fields do not match R1"
        )
    if (
        rule["rule_id"] != "semantic-structure-gate-r1"
        or rule["decisive_dimensions"] != _STRUCTURAL_DIMENSIONS
        or rule["structural_hole_ids"] != ["relationship-strength"]
        or rule["representative_hole_ids"] != ["transfer-predicate"]
        or rule["execution_when_structurally_unresolved"] is not False
    ):
        raise M15HierarchicalInterpretationFrontierError(
            "clarification rule no longer implements R1"
        )
    questions = _object(rule["question_templates"], name="question_templates")
    if set(questions) != {"relationship-strength"} or not isinstance(
        questions["relationship-strength"], str
    ) or not questions["relationship-strength"]:
        raise M15HierarchicalInterpretationFrontierError(
            "R1 clarification question is missing"
        )
    physical = _object(raw["physical_reduction"], name="physical_reduction")
    if physical != {
        "objective": "lexicographic_estimated_latency_then_bytes_then_plan_id",
        "representatives_per_interpretation": 1,
        "estimate_source": "sealed_same_family_strategy_conditioned_memory",
        "current_query_profile_calls": 0,
    }:
        raise M15HierarchicalInterpretationFrontierError(
            "physical reduction policy changed"
        )
    semantic = _object(raw["semantic_reduction"], name="semantic_reduction")
    if set(semantic) != {
        "unresolved_semantic_deviation",
        "anchored_relaxations_only",
        "epsilon_dominance",
        "maximum_returned_interpretation_plans",
    }:
        raise M15HierarchicalInterpretationFrontierError(
            "semantic reduction fields do not match the contract"
        )
    maximum = semantic["maximum_returned_interpretation_plans"]
    if (
        semantic["unresolved_semantic_deviation"] is not None
        or semantic["anchored_relaxations_only"] is not True
        or semantic["epsilon_dominance"]
        != "not_applicable_without_anchored_relaxations"
        or isinstance(maximum, bool)
        or not isinstance(maximum, int)
        or maximum <= 0
    ):
        raise M15HierarchicalInterpretationFrontierError(
            "semantic reduction policy changed"
        )
    options = _object(raw["clarification_options"], name="clarification_options")
    if set(options) != {"relationship-strength"}:
        raise M15HierarchicalInterpretationFrontierError(
            "clarification option holes changed"
        )
    option_records = options["relationship-strength"]
    if not isinstance(option_records, list) or len(option_records) < 2:
        raise M15HierarchicalInterpretationFrontierError(
            "R1 requires multiple bounded relationship-strength options"
        )
    candidate_ids: list[str] = []
    for item in option_records:
        option = _object(item, name="clarification option")
        if set(option) != {"candidate_id", "label"}:
            raise M15HierarchicalInterpretationFrontierError(
                "clarification option fields changed"
            )
        candidate_ids.append(_safe_id(option["candidate_id"], name="candidate_id"))
        if not isinstance(option["label"], str) or not option["label"]:
            raise M15HierarchicalInterpretationFrontierError(
                "clarification option label is invalid"
            )
    if len(candidate_ids) != len(set(candidate_ids)):
        raise M15HierarchicalInterpretationFrontierError(
            "clarification option candidate IDs are duplicated"
        )
    if any(
        (
            raw["oracle_inputs"],
            raw["post_execution_measurements_used"] is not False,
            raw["backend_calls_made"] != 0,
            raw["llm_calls_made"] != 0,
            raw["ontology_service_calls_made"] != 0,
            raw["automatic_retries"] != 0,
            raw["paper_result"] is not False,
        )
    ):
        raise M15HierarchicalInterpretationFrontierError(
            "E5 policy leakage or call boundary changed"
        )
    return raw


def _bridge_payload(bridge: M15ResolutionExecutionBridgePlan) -> dict[str, Any]:
    payload = bridge.to_dict()
    if payload.get("schema_version") != RESOLUTION_EXECUTION_BRIDGE_PLAN_SCHEMA_VERSION:
        raise M15HierarchicalInterpretationFrontierError(
            "E5 requires an E4 resolution-execution bridge plan"
        )
    observed = payload.get("bridge_plan_sha256")
    _sha256(observed, name="bridge_plan_sha256")
    if content_hash({k: v for k, v in payload.items() if k != "bridge_plan_sha256"}) != observed:
        raise M15HierarchicalInterpretationFrontierError("bridge plan hash mismatch")
    boundary = _object(payload.get("claim_boundary"), name="bridge claim boundary")
    if (
        boundary.get("all_bounded_interpretations_preserved") is not True
        or boundary.get("answer_oracle_used_for_selection") is not False
        or boundary.get("backend_calls_made") != 0
        or boundary.get("native_query_text_emitted") is not False
        or payload.get("automatic_retries") != 0
        or payload.get("paper_result") is not False
    ):
        raise M15HierarchicalInterpretationFrontierError(
            "bridge claim boundary is incompatible with E5"
        )
    return payload


def _structure_record(semantic_class: Mapping[str, Any]) -> dict[str, Any]:
    parameters = _object(
        semantic_class.get("semantic_parameters"), name="semantic_parameters"
    )
    relationship = _object(
        parameters.get("relationship-strength"),
        name="relationship-strength parameters",
    )
    aggregation = relationship.get("aggregation")
    if aggregation not in _RELATIONSHIP_AGGREGATIONS:
        raise M15HierarchicalInterpretationFrontierError(
            "relationship aggregation is outside the R1 contract"
        )
    bindings = _object(
        semantic_class.get("target_binding_values"), name="target_binding_values"
    )
    path_shape = bindings.get("path-shape")
    if path_shape != "direct":
        raise M15HierarchicalInterpretationFrontierError(
            "the first E5 slice supports only the registered direct path"
        )
    meaning = _RELATIONSHIP_AGGREGATIONS[aggregation]
    missing = semantic_class.get("missing_capability_ids")
    if not isinstance(missing, list):
        raise M15HierarchicalInterpretationFrontierError(
            "semantic class missing-capability list is invalid"
        )
    capability = {
        "availability": semantic_class.get("availability"),
        "missing_capability_ids": sorted(missing),
    }
    return {
        "aggregation_operator": aggregation,
        "path_structure": path_shape,
        "quantification": meaning["quantification"],
        "answer_meaning": meaning["answer_meaning"],
        "output_contract": meaning["output_contract"],
        "executable_capability": capability,
    }


def _target_features(semantic_class: Mapping[str, Any]) -> dict[str, Any]:
    bindings = _object(
        semantic_class.get("target_binding_values"), name="target_binding_values"
    )
    expected = {
        "amount-lower-bound",
        "person-identity",
        "risk-level",
        "time-lower-bound",
        "transfer-predicate",
    }
    if not expected.issubset(bindings):
        raise M15HierarchicalInterpretationFrontierError(
            "executable interpretation lacks family-memory features"
        )
    return {key: bindings[key] for key in sorted(expected)}


def select_m15_hierarchical_interpretation_frontier(
    *,
    bridge: M15ResolutionExecutionBridgePlan,
    workload: M15DirectSemanticWorkloadBundle,
    memory: M15DirectTrainingMemoryView,
    predictor_policy: Mapping[str, Any] | str | Path,
    interpretation_policy: Mapping[str, Any] | str | Path,
    authoritative_selections: Mapping[str, str] | None = None,
    authority_source_id: str | None = None,
    non_authoritative_candidate_subset: Mapping[str, Sequence[str]] | None = None,
) -> M15HierarchicalInterpretationFrontier:
    """Apply physical reduction and R1 without observing the current query."""

    selected_policy = _policy(interpretation_policy)
    bridge_payload = _bridge_payload(bridge)
    classes = bridge_payload.get("semantic_classes")
    physical = bridge_payload.get("physical_candidates")
    if not isinstance(classes, list) or not isinstance(physical, list):
        raise M15HierarchicalInterpretationFrontierError(
            "bridge semantic or physical candidates are invalid"
        )
    class_ids = [item.get("semantic_class_id") for item in classes]
    if len(class_ids) != len(set(class_ids)):
        raise M15HierarchicalInterpretationFrontierError(
            "bridge semantic class IDs are duplicated"
        )
    physical_by_class: dict[str, list[dict[str, Any]]] = {
        str(class_id): [] for class_id in class_ids
    }
    plan_ids: set[str] = set()
    for item in physical:
        plan = _object(item, name="physical candidate")
        plan_id = _safe_id(plan.get("plan_id"), name="plan_id")
        class_id = _safe_id(plan.get("semantic_class_id"), name="semantic_class_id")
        if plan_id in plan_ids or class_id not in physical_by_class:
            raise M15HierarchicalInterpretationFrontierError(
                "physical candidate identity is duplicate or unknown"
            )
        plan_ids.add(plan_id)
        if plan_id not in bridge.plans:
            raise M15HierarchicalInterpretationFrontierError(
                "bridge runtime plan map is incomplete"
            )
        physical_by_class[class_id].append(plan)
    if set(bridge.plans) != plan_ids:
        raise M15HierarchicalInterpretationFrontierError(
            "bridge runtime plan map contains undeclared physical plans"
        )

    structural_holes = selected_policy["clarification_rule"][
        "structural_hole_ids"
    ]
    universe: dict[str, set[str]] = {hole_id: set() for hole_id in structural_holes}
    class_records: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    for raw_class in classes:
        semantic_class = _object(raw_class, name="semantic class")
        class_id = _safe_id(
            semantic_class.get("semantic_class_id"), name="semantic_class_id"
        )
        selected = _object(
            semantic_class.get("selected_candidate_ids"),
            name="selected_candidate_ids",
        )
        for hole_id in structural_holes:
            universe[hole_id].add(
                _safe_id(selected.get(hole_id), name=f"{hole_id} candidate")
            )
        structure = _structure_record(semantic_class)
        availability = semantic_class.get("availability")
        candidates = sorted(
            physical_by_class[class_id], key=lambda item: item["plan_id"]
        )
        declared_ids = semantic_class.get("physical_candidate_ids")
        if not isinstance(declared_ids, list) or sorted(declared_ids) != [
            item["plan_id"] for item in candidates
        ]:
            raise M15HierarchicalInterpretationFrontierError(
                "semantic-to-physical candidate coverage drifted"
            )
        if availability == "executable":
            if not candidates:
                raise M15HierarchicalInterpretationFrontierError(
                    "executable interpretation has no physical candidate"
                )
            features = _target_features(semantic_class)
            for item in candidates:
                targets.append(
                    {
                        "target_id": item["plan_id"],
                        "semantic_class_id": class_id,
                        "target_query_instance_sha256": semantic_class[
                            "semantic_equivalence_sha256"
                        ],
                        "physical_strategy": item["physical_strategy"],
                        "features": features,
                    }
                )
        elif availability != "unavailable" or candidates:
            raise M15HierarchicalInterpretationFrontierError(
                "unavailable interpretation received physical candidates"
            )
        class_records.append(
            {
                "interpretation_class_id": class_id,
                "semantic_equivalence_sha256": semantic_class[
                    "semantic_equivalence_sha256"
                ],
                "selected_candidate_ids": dict(sorted(selected.items())),
                "structural_signature": structure,
                "structural_signature_sha256": content_hash(structure),
                "availability": availability,
                "missing_capability_ids": list(
                    semantic_class["missing_capability_ids"]
                ),
                "unavailable_reasons": copy.deepcopy(
                    semantic_class["unavailable_reasons"]
                ),
                "physical_candidate_ids": [
                    item["plan_id"] for item in candidates
                ],
                "physical_representative": None,
                "interpretation_status": (
                    "unavailable" if availability == "unavailable" else "unresolved"
                ),
                "relaxation_base_id": None,
                "semantic_deviation": None,
            }
        )

    configured_options = {
        hole_id: {
            item["candidate_id"]
            for item in selected_policy["clarification_options"][hole_id]
        }
        for hole_id in structural_holes
    }
    if universe != configured_options:
        raise M15HierarchicalInterpretationFrontierError(
            "policy clarification options do not exactly match E4 candidates"
        )

    non_authoritative = non_authoritative_candidate_subset or {}
    if not isinstance(non_authoritative, Mapping):
        raise M15HierarchicalInterpretationFrontierError(
            "non-authoritative candidate subset must be an object"
        )
    normalized_subset: dict[str, list[str]] = {}
    for hole_id, values in non_authoritative.items():
        if hole_id not in universe or not isinstance(values, Sequence) or isinstance(
            values, (str, bytes)
        ):
            raise M15HierarchicalInterpretationFrontierError(
                "non-authoritative subset targets an unknown structural hole"
            )
        normalized = sorted(
            _safe_id(item, name="non-authoritative candidate") for item in values
        )
        if not normalized or len(normalized) != len(set(normalized)) or not set(
            normalized
        ).issubset(universe[hole_id]):
            raise M15HierarchicalInterpretationFrontierError(
                "non-authoritative candidate subset is invalid"
            )
        normalized_subset[hole_id] = normalized

    selections = dict(authoritative_selections or {})
    if set(selections) - set(structural_holes):
        raise M15HierarchicalInterpretationFrontierError(
            "authoritative selections may bind only R1 structural holes"
        )
    normalized_selections: dict[str, str] = {}
    for hole_id, candidate_id in selections.items():
        selected_id = _safe_id(candidate_id, name="authoritative candidate")
        if selected_id not in universe[hole_id]:
            raise M15HierarchicalInterpretationFrontierError(
                "authoritative candidate is outside the sealed E4 set"
            )
        normalized_selections[hole_id] = selected_id
    if normalized_selections:
        if set(normalized_selections) != set(structural_holes):
            raise M15HierarchicalInterpretationFrontierError(
                "all R1 structural holes must be authoritatively selected together"
            )
        authority_id = _safe_id(authority_source_id, name="authority_source_id")
    elif authority_source_id is not None:
        raise M15HierarchicalInterpretationFrontierError(
            "authority source requires an authoritative selection"
        )
    else:
        authority_id = None

    prediction_source = build_m15_family_cost_target_predictions(
        workload=workload,
        memory=memory,
        policy=predictor_policy,
        targets=targets,
    )
    source_payload = prediction_source.to_dict()
    if content_hash(
        {
            key: value
            for key, value in source_payload.items()
            if key != "prediction_source_sha256"
        }
    ) != source_payload["prediction_source_sha256"]:
        raise M15HierarchicalInterpretationFrontierError(
            "family cost prediction source hash mismatch"
        )
    predictions = {
        item["target_id"]: item for item in source_payload["predictions"]
    }
    for record in class_records:
        candidate_ids = record["physical_candidate_ids"]
        if not candidate_ids:
            continue
        estimates = [predictions[item] for item in candidate_ids]
        representative = min(
            estimates,
            key=lambda item: (
                item["estimated_latency_ms"],
                item["estimated_total_bytes_moved"],
                item["target_id"],
            ),
        )
        record["physical_representative"] = {
            "plan_id": representative["target_id"],
            "physical_strategy": representative["physical_strategy"],
            "estimated_latency_ms": representative["estimated_latency_ms"],
            "estimated_total_bytes_moved": representative[
                "estimated_total_bytes_moved"
            ],
            "uncertainty": copy.deepcopy(representative["uncertainty"]),
            "family_cost_prediction_source_sha256": prediction_source.source_hash,
        }

    unresolved_holes = [
        hole_id for hole_id in structural_holes if hole_id not in normalized_selections
    ]
    clarification_required = bool(unresolved_holes)
    clarification_requests = []
    for hole_id in unresolved_holes:
        structural_signatures = {
            item["structural_signature_sha256"]
            for item in class_records
            if item["selected_candidate_ids"][hole_id] in universe[hole_id]
        }
        if len(structural_signatures) < 2:
            raise M15HierarchicalInterpretationFrontierError(
                "R1 clarification was requested without a structural difference"
            )
        relevant_structures = [
            item["structural_signature"]
            for item in class_records
            if item["selected_candidate_ids"][hole_id] in universe[hole_id]
        ]
        varying_dimensions = [
            dimension
            for dimension in _STRUCTURAL_DIMENSIONS
            if len(
                {
                    content_hash(structure[dimension])
                    for structure in relevant_structures
                }
            )
            > 1
        ]
        reason_codes: list[str] = []
        if set(varying_dimensions) & {
            "aggregation_operator",
            "path_structure",
            "quantification",
        }:
            reason_codes.append("semantic_operator_structure_differs")
        if set(varying_dimensions) & {"answer_meaning", "output_contract"}:
            reason_codes.append("answer_meaning_or_output_contract_differs")
        if "executable_capability" in varying_dimensions:
            reason_codes.append("executable_capability_differs")
        clarification_requests.append(
            {
                "hole_id": hole_id,
                "question": selected_policy["clarification_rule"][
                    "question_templates"
                ][hole_id],
                "options": copy.deepcopy(
                    selected_policy["clarification_options"][hole_id]
                ),
                "varying_structural_dimensions": varying_dimensions,
                "reason_codes": reason_codes,
                "authoritative_response_required": True,
            }
        )

    active = [
        item
        for item in class_records
        if all(
            item["selected_candidate_ids"][hole_id] == candidate_id
            for hole_id, candidate_id in normalized_selections.items()
        )
    ]
    executable_active = [
        item for item in active if item["availability"] == "executable"
    ]
    maximum = selected_policy["semantic_reduction"][
        "maximum_returned_interpretation_plans"
    ]
    returned: list[dict[str, Any]] = []
    if not clarification_required:
        for item in sorted(
            executable_active, key=lambda record: record["interpretation_class_id"]
        )[:maximum]:
            returned.append(
                {
                    "interpretation_class_id": item["interpretation_class_id"],
                    "selected_candidate_ids": copy.deepcopy(
                        item["selected_candidate_ids"]
                    ),
                    "semantic_deviation": None,
                    "relaxation_base_id": None,
                    "physical_representative": copy.deepcopy(
                        item["physical_representative"]
                    ),
                }
            )
    execution_eligible = bool(returned) and not clarification_required
    status = (
        "clarification_required"
        if clarification_required
        else "ready_with_bounded_representatives"
        if execution_eligible
        else "authoritatively_selected_structure_unavailable"
    )
    body = {
        "schema_version": HIERARCHICAL_INTERPRETATION_FRONTIER_SCHEMA_VERSION,
        "status": status,
        "bridge_plan_sha256": bridge.plan_hash,
        "resolution_commit_sha256": bridge_payload["resolution"][
            "resolution_commit_sha256"
        ],
        "hard_constraints_sha256": bridge_payload["resolution"][
            "hard_constraints_sha256"
        ],
        "resolved_entity_bindings": copy.deepcopy(
            bridge_payload["resolution"]["resolved_entity_bindings"]
        ),
        "interpretation_policy_sha256": content_hash(selected_policy),
        "family_cost_prediction_source": source_payload,
        "authoritative_structural_selections": dict(
            sorted(normalized_selections.items())
        ),
        "authority_source_id": authority_id,
        "non_authoritative_candidate_subset": dict(
            sorted(normalized_subset.items())
        ),
        "non_authoritative_subset_used_for_authority": False,
        "clarification_required": clarification_required,
        "clarification_requests": clarification_requests,
        "execution_eligible": execution_eligible,
        "all_interpretation_classes": sorted(
            class_records, key=lambda item: item["interpretation_class_id"]
        ),
        "active_interpretation_class_ids": sorted(
            item["interpretation_class_id"] for item in active
        ),
        "returned_interpretation_plans": returned,
        "relaxation_frontiers": [],
        "counts": {
            "interpretation_classes": len(class_records),
            "executable_interpretation_classes": sum(
                item["availability"] == "executable" for item in class_records
            ),
            "unavailable_interpretation_classes": sum(
                item["availability"] == "unavailable" for item in class_records
            ),
            "physical_candidates": len(physical),
            "family_cost_predictions": len(predictions),
            "physical_representatives": sum(
                item["physical_representative"] is not None
                for item in class_records
            ),
            "clarification_requests": len(clarification_requests),
            "returned_interpretation_plans": len(returned),
            "anchored_relaxation_frontiers": 0,
        },
        "selection_boundary": {
            "hierarchical_objective": "interpretation_then_physical",
            "clarification_rule": "semantic-structure-gate-r1",
            "physical_objective": selected_policy["physical_reduction"][
                "objective"
            ],
            "unresolved_semantic_deviation": None,
            "unresolved_cross_interpretation_cost_dominance": False,
            "anchored_relaxations_only": True,
            "maximum_returned_interpretation_plans": maximum,
        },
        "claim_boundary": {
            "artifact_class": "offline_hierarchical_interpretation_mechanism",
            "development_artifacts_only": True,
            "hard_constraints_preserved": True,
            "all_bounded_interpretations_preserved": True,
            "unavailable_interpretations_preserved": True,
            "answer_oracle_used_for_selection": False,
            "post_execution_measurements_used": False,
            "current_query_profile_calls": 0,
            "backend_calls_made": 0,
            "llm_calls_made": 0,
            "ontology_service_calls_made": 0,
            "native_query_text_emitted": False,
            "automatic_retries": 0,
            "paper_result": False,
        },
        "paper_result": False,
    }
    return M15HierarchicalInterpretationFrontier(
        {**body, "hierarchical_frontier_sha256": content_hash(body)}
    )
