"""Capability-aware direct semantic frontier for the F2C9 development gate.

The full semantic solution space may contain interpretations that no current
backend artifact can execute.  This module keeps that coverage visible while
building candidates only for the four verified direct classes.  It reduces
two physical plans per class using sealed pre-execution estimates, then applies
semantic-deviation/cost Pareto, epsilon, and K-bounded selection.
"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_parameterized_federation import (
    build_m15_parameterized_plan_candidates,
    load_m15_parameterized_contract,
)
from xgap.experiments.m15_parameterized_workload import (
    M15ParameterizedWorkloadBundle,
    load_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_predicate_overlay import (
    M15PredicateMappingSpec,
    M15PredicateOverlayBundle,
    build_m15_predicate_semantic_solution_space,
    load_m15_predicate_overlay_bundle,
)
from xgap.experiments.m15_semantic_frontier import (
    M15SemanticRelaxationCatalog,
)
from xgap.runtime import FederatedExecutionPlan


DIRECT_SEMANTIC_CANDIDATE_SET_SCHEMA_VERSION = (
    "m15-f2c9-direct-semantic-candidate-set-v1"
)
PREEXECUTION_ESTIMATE_SNAPSHOT_SCHEMA_VERSION = (
    "m15-f2c9-preexecution-estimate-snapshot-v1"
)
DIRECT_SEMANTIC_FRONTIER_SCHEMA_VERSION = (
    "m15-f2c9-direct-semantic-frontier-v1"
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_ALLOWED_EVIDENCE_KINDS = frozenset(
    {
        "controlled_preexecution_fixture",
        "family_memory_prediction",
        "backend_observation_prediction",
    }
)
_CANDIDATE_SET_FIELDS = frozenset(
    {
        "schema_version",
        "source_solution_space_sha256",
        "predicate_overlay_sha256",
        "predicate_mapping_sha256",
        "family_compatibility_sha256",
        "base_query_id",
        "frontier_policy",
        "counts",
        "semantic_classes",
        "physical_candidates",
        "unavailable_semantic_class_ids",
        "unavailable_reason",
        "claim_boundary",
        "automatic_retries",
        "paper_result",
        "candidate_set_sha256",
    }
)
_ESTIMATE_SNAPSHOT_FIELDS = frozenset(
    {
        "schema_version",
        "candidate_set_sha256",
        "evidence_kind",
        "evidence_id",
        "sealed_before_execution",
        "answer_oracle_fields",
        "post_execution_measurements_used",
        "estimates",
        "automatic_retries",
        "paper_result",
        "estimate_snapshot_sha256",
    }
)
_ESTIMATE_FIELDS = frozenset(
    {
        "plan_id",
        "estimated_latency_ms",
        "estimated_resource_cost_units",
    }
)


class M15DirectSemanticFrontierError(ValueError):
    """Raised when candidate, estimate, or frontier identity drifts."""


@dataclass(frozen=True)
class M15DirectSemanticCandidateSet:
    payload: Mapping[str, Any]
    plans: Mapping[str, FederatedExecutionPlan]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))

    @property
    def candidate_set_hash(self) -> str:
        return str(self.payload["candidate_set_sha256"])


@dataclass(frozen=True)
class M15PreexecutionEstimateSnapshot:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))

    @property
    def snapshot_hash(self) -> str:
        return str(self.payload["estimate_snapshot_sha256"])


@dataclass(frozen=True)
class M15DirectSemanticFrontier:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15DirectSemanticFrontierError(f"{name} is not a safe identifier")
    return value


def _finite_nonnegative(value: object, *, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise M15DirectSemanticFrontierError(
            f"{name} must be a finite nonnegative number"
        )
    return float(value)


def _hash_bound_payload(
    raw: object,
    *,
    name: str,
    schema_version: str,
    hash_field: str,
    fields: frozenset[str],
) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != fields:
        raise M15DirectSemanticFrontierError(
            f"{name} fields do not match the sealed contract"
        )
    payload = copy.deepcopy(dict(raw))
    if payload.get("schema_version") != schema_version:
        raise M15DirectSemanticFrontierError(
            f"{name} schema_version is unsupported"
        )
    observed_hash = payload.get(hash_field)
    if not isinstance(observed_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", observed_hash
    ):
        raise M15DirectSemanticFrontierError(f"{name} hash is invalid")
    body = {key: value for key, value in payload.items() if key != hash_field}
    if content_hash(body) != observed_hash:
        raise M15DirectSemanticFrontierError(f"{name} hash mismatch")
    return payload


def _validated_candidate_payload(
    candidate_set: M15DirectSemanticCandidateSet,
) -> dict[str, Any]:
    payload = _hash_bound_payload(
        candidate_set.payload,
        name="candidate set",
        schema_version=DIRECT_SEMANTIC_CANDIDATE_SET_SCHEMA_VERSION,
        hash_field="candidate_set_sha256",
        fields=_CANDIDATE_SET_FIELDS,
    )
    counts = payload.get("counts")
    if counts != {
        "declared_semantic_classes": 12,
        "executable_direct_semantic_classes": 4,
        "unavailable_semantic_classes": 8,
        "physical_candidates": 8,
        "physical_candidates_per_class": 2,
    }:
        raise M15DirectSemanticFrontierError(
            "candidate set counts do not match the F2C9 contract"
        )
    classes = payload.get("semantic_classes")
    physical = payload.get("physical_candidates")
    unavailable = payload.get("unavailable_semantic_class_ids")
    if not isinstance(classes, list) or not isinstance(physical, list):
        raise M15DirectSemanticFrontierError(
            "candidate set class or physical plan records are invalid"
        )
    if not isinstance(unavailable, list):
        raise M15DirectSemanticFrontierError(
            "candidate set unavailable class records are invalid"
        )
    if len(classes) != 4 or not all(isinstance(item, Mapping) for item in classes):
        raise M15DirectSemanticFrontierError(
            "candidate set requires four direct semantic class records"
        )
    if len(physical) != 8 or not all(
        isinstance(item, Mapping) for item in physical
    ):
        raise M15DirectSemanticFrontierError(
            "candidate set requires eight physical plan records"
        )
    if len(unavailable) != 8:
        raise M15DirectSemanticFrontierError(
            "candidate set requires eight unavailable semantic classes"
        )
    class_ids = [
        _safe_id(item.get("semantic_class_id"), name="semantic_class_id")
        for item in classes
    ]
    if len(class_ids) != 4 or len(set(class_ids)) != 4:
        raise M15DirectSemanticFrontierError(
            "candidate set requires four unique direct semantic classes"
        )
    unavailable_ids = [
        _safe_id(value, name="unavailable semantic_class_id")
        for value in unavailable
    ]
    if (
        len(unavailable_ids) != 8
        or len(set(unavailable_ids)) != 8
        or set(class_ids) & set(unavailable_ids)
    ):
        raise M15DirectSemanticFrontierError(
            "candidate set availability partition is invalid"
        )
    plan_ids: list[str] = []
    class_counts = {class_id: 0 for class_id in class_ids}
    for raw in physical:
        if not isinstance(raw, Mapping):
            raise M15DirectSemanticFrontierError(
                "candidate set physical plan record is invalid"
            )
        plan_id = _safe_id(raw.get("plan_id"), name="physical plan_id")
        class_id = _safe_id(
            raw.get("semantic_class_id"), name="physical semantic_class_id"
        )
        if class_id not in class_counts:
            raise M15DirectSemanticFrontierError(
                "physical plan references an unknown semantic class"
            )
        plan_ids.append(plan_id)
        class_counts[class_id] += 1
        plan = candidate_set.plans.get(plan_id)
        if not isinstance(plan, FederatedExecutionPlan) or raw.get(
            "plan"
        ) != plan.to_dict():
            raise M15DirectSemanticFrontierError(
                "candidate set physical plan payload and runtime plan differ"
            )
    if (
        len(plan_ids) != 8
        or len(set(plan_ids)) != 8
        or set(plan_ids) != set(candidate_set.plans)
        or set(class_counts.values()) != {2}
    ):
        raise M15DirectSemanticFrontierError(
            "candidate set physical candidate coverage is invalid"
        )
    if (
        payload.get("automatic_retries") != 0
        or payload.get("paper_result") is not False
    ):
        raise M15DirectSemanticFrontierError(
            "candidate set claim boundary is invalid"
        )
    return payload


def _validated_snapshot_payload(
    snapshot: M15PreexecutionEstimateSnapshot,
    *,
    candidate_set: M15DirectSemanticCandidateSet,
) -> dict[str, Any]:
    payload = _hash_bound_payload(
        snapshot.payload,
        name="estimate snapshot",
        schema_version=PREEXECUTION_ESTIMATE_SNAPSHOT_SCHEMA_VERSION,
        hash_field="estimate_snapshot_sha256",
        fields=_ESTIMATE_SNAPSHOT_FIELDS,
    )
    if payload.get("candidate_set_sha256") != candidate_set.candidate_set_hash:
        raise M15DirectSemanticFrontierError(
            "estimate snapshot belongs to another candidate set"
        )
    if payload.get("evidence_kind") not in _ALLOWED_EVIDENCE_KINDS:
        raise M15DirectSemanticFrontierError(
            "estimate evidence kind is not admitted for pre-execution selection"
        )
    _safe_id(payload.get("evidence_id"), name="evidence_id")
    if (
        payload.get("sealed_before_execution") is not True
        or payload.get("answer_oracle_fields") != []
        or payload.get("post_execution_measurements_used") is not False
    ):
        raise M15DirectSemanticFrontierError(
            "online frontier cannot use answer or post-execution evidence"
        )
    estimates = payload.get("estimates")
    if not isinstance(estimates, list):
        raise M15DirectSemanticFrontierError(
            "estimate snapshot records are invalid"
        )
    plan_ids: list[str] = []
    for index, raw in enumerate(estimates):
        if not isinstance(raw, Mapping) or set(raw) != _ESTIMATE_FIELDS:
            raise M15DirectSemanticFrontierError(
                f"estimates[{index}] fields do not match the sealed contract"
            )
        plan_ids.append(_safe_id(raw.get("plan_id"), name="estimate plan_id"))
        _finite_nonnegative(
            raw.get("estimated_latency_ms"), name="estimated_latency_ms"
        )
        _finite_nonnegative(
            raw.get("estimated_resource_cost_units"),
            name="estimated_resource_cost_units",
        )
    if len(plan_ids) != len(set(plan_ids)) or set(plan_ids) != set(
        candidate_set.plans
    ):
        raise M15DirectSemanticFrontierError(
            "estimate snapshot must cover exactly every physical candidate"
        )
    if (
        payload.get("automatic_retries") != 0
        or payload.get("paper_result") is not False
    ):
        raise M15DirectSemanticFrontierError(
            "estimate snapshot claim boundary is invalid"
        )
    return payload


def _binding_values(records: object) -> dict[str, Any]:
    if not isinstance(records, list):
        raise M15DirectSemanticFrontierError("semantic bindings are invalid")
    values: dict[str, Any] = {}
    for raw in records:
        if not isinstance(raw, Mapping):
            raise M15DirectSemanticFrontierError("semantic binding is invalid")
        slot_id = _safe_id(raw.get("slot_id"), name="binding slot_id")
        if slot_id in values:
            raise M15DirectSemanticFrontierError(
                "semantic binding slot IDs are not unique"
            )
        values[slot_id] = raw.get("value")
    return values


def _selected_base(
    value: M15ParameterizedWorkloadBundle | str | Path,
) -> M15ParameterizedWorkloadBundle:
    return (
        value
        if isinstance(value, M15ParameterizedWorkloadBundle)
        else load_m15_parameterized_workload_bundle(value)
    )


def build_m15_direct_semantic_candidate_set(
    *,
    predicate_overlay: M15PredicateOverlayBundle | str | Path,
    base_bundle: M15ParameterizedWorkloadBundle | str | Path,
    catalog: M15SemanticRelaxationCatalog | str | Path,
    mapping: M15PredicateMappingSpec | str | Path,
) -> M15DirectSemanticCandidateSet:
    """Build two physical plans for each verified direct semantic class."""

    selected_base = _selected_base(base_bundle)
    overlay = load_m15_predicate_overlay_bundle(
        predicate_overlay.root
        if isinstance(predicate_overlay, M15PredicateOverlayBundle)
        else predicate_overlay,
        base_bundle=selected_base,
        catalog=catalog,
        mapping=mapping,
    )
    base_query_id = str(overlay.manifest["base_query_id"])
    solution = build_m15_predicate_semantic_solution_space(
        base_bundle=selected_base,
        base_query_id=base_query_id,
        catalog=catalog,
        mapping=mapping,
    )
    solution_payload = solution.to_dict()
    all_classes = {
        str(item["semantic_class_id"]): dict(item)
        for item in solution_payload["semantic_equivalence_classes"]
    }
    direct_classes = {
        class_id: semantic_class
        for class_id, semantic_class in all_classes.items()
        if _binding_values(semantic_class["bindings"])["path-shape"] == "direct"
    }
    if len(direct_classes) != 4:
        raise M15DirectSemanticFrontierError(
            "F2C9 requires exactly four executable direct semantic classes"
        )
    exact = [
        item
        for item in direct_classes.values()
        if float(item["semantic_deviation"]) == 0
    ]
    if len(exact) != 1:
        raise M15DirectSemanticFrontierError(
            "direct semantic classes require exactly one exact class"
        )
    query_by_class = {str(exact[0]["semantic_class_id"]): base_query_id}
    changed_by_class = {str(exact[0]["semantic_class_id"]): []}
    for raw in overlay.manifest["overlay_instances"]:
        class_id = str(raw["semantic_class_id"])
        if class_id in query_by_class:
            raise M15DirectSemanticFrontierError(
                "predicate overlay repeats a direct semantic class"
            )
        query_by_class[class_id] = str(raw["query_id"])
        changed_by_class[class_id] = list(raw["changed_slot_ids"])
    if set(query_by_class) != set(direct_classes):
        raise M15DirectSemanticFrontierError(
            "predicate overlay does not cover every direct semantic class"
        )

    class_records: list[dict[str, Any]] = []
    plan_records: list[dict[str, Any]] = []
    plans: dict[str, FederatedExecutionPlan] = {}
    for semantic_class in sorted(
        direct_classes.values(),
        key=lambda item: (
            float(item["semantic_deviation"]),
            str(item["semantic_class_id"]),
        ),
    ):
        class_id = str(semantic_class["semantic_class_id"])
        query_id = query_by_class[class_id]
        contract = load_m15_parameterized_contract(
            overlay.workload_bundle,
            query_id,
        )["contract"]
        if contract["query_instance_sha256"] != semantic_class[
            "query_instance_sha256"
        ]:
            raise M15DirectSemanticFrontierError(
                "semantic class and executable query identity differ"
            )
        class_records.append(
            {
                "semantic_class_id": class_id,
                "canonical_interpretation_id": semantic_class[
                    "canonical_interpretation_id"
                ],
                "semantic_deviation": float(
                    semantic_class["semantic_deviation"]
                ),
                "semantic_deviation_fraction": dict(
                    semantic_class["semantic_deviation_fraction"]
                ),
                "query_id": query_id,
                "query_instance_sha256": contract[
                    "query_instance_sha256"
                ],
                "binding_sha256": contract["binding_sha256"],
                "changed_slot_ids": list(changed_by_class[class_id]),
                "binding_values": _binding_values(contract["bindings"]),
            }
        )
        candidates = build_m15_parameterized_plan_candidates(
            overlay.workload_bundle,
            query_id=query_id,
        )
        if len(candidates) != 2:
            raise M15DirectSemanticFrontierError(
                "each direct semantic class requires two physical candidates"
            )
        for candidate in candidates:
            original = candidate.plan
            decorated = replace(
                original,
                metadata={
                    **dict(original.metadata),
                    "semantic_class_id": class_id,
                    "semantic_deviation": float(
                        semantic_class["semantic_deviation"]
                    ),
                    "canonical_interpretation_id": semantic_class[
                        "canonical_interpretation_id"
                    ],
                    "changed_slot_ids": list(changed_by_class[class_id]),
                    "predicate_overlay_sha256": overlay.manifest[
                        "overlay_sha256"
                    ],
                    "answer_oracle_used_for_construction": False,
                    "paper_result": False,
                },
            )
            if decorated.plan_id in plans:
                raise M15DirectSemanticFrontierError(
                    "direct physical plan IDs are not unique"
                )
            plans[decorated.plan_id] = decorated
            plan_records.append(
                {
                    "plan_id": decorated.plan_id,
                    "semantic_class_id": class_id,
                    "canonical_interpretation_id": semantic_class[
                        "canonical_interpretation_id"
                    ],
                    "query_id": query_id,
                    "physical_strategy": decorated.metadata[
                        "physical_strategy"
                    ],
                    "plan": decorated.to_dict(),
                }
            )
    if len(plans) != 8:
        raise M15DirectSemanticFrontierError(
            "F2C9 requires eight physical candidates"
        )
    unavailable = sorted(set(all_classes) - set(direct_classes))
    body = {
        "schema_version": DIRECT_SEMANTIC_CANDIDATE_SET_SCHEMA_VERSION,
        "source_solution_space_sha256": solution.solution_space_hash,
        "predicate_overlay_sha256": overlay.manifest["overlay_sha256"],
        "predicate_mapping_sha256": overlay.manifest["predicate_mapping"][
            "mapping_sha256"
        ],
        "family_compatibility_sha256": overlay.manifest[
            "family_compatibility_sha256"
        ],
        "base_query_id": base_query_id,
        "frontier_policy": dict(solution_payload["frontier_policy"]),
        "counts": {
            "declared_semantic_classes": len(all_classes),
            "executable_direct_semantic_classes": len(direct_classes),
            "unavailable_semantic_classes": len(unavailable),
            "physical_candidates": len(plans),
            "physical_candidates_per_class": 2,
        },
        "semantic_classes": class_records,
        "physical_candidates": sorted(
            plan_records,
            key=lambda item: (item["semantic_class_id"], item["plan_id"]),
        ),
        "unavailable_semantic_class_ids": unavailable,
        "unavailable_reason": "bounded_multihop_semantics_and_artifacts_unbound",
        "claim_boundary": {
            "artifact_class": "unexecuted_capability_aware_direct_candidates",
            "blocked_classes_excluded_from_planning": True,
            "answer_oracle_used": False,
            "backend_calls_made": 0,
            "llm_calls_made": 0,
            "ontology_calls_made": 0,
            "contains_cost_estimates": False,
            "paper_result": False,
        },
        "automatic_retries": 0,
        "paper_result": False,
    }
    candidate_set = M15DirectSemanticCandidateSet(
        {**body, "candidate_set_sha256": content_hash(body)},
        plans,
    )
    _validated_candidate_payload(candidate_set)
    return candidate_set


def build_m15_preexecution_estimate_snapshot(
    candidate_set: M15DirectSemanticCandidateSet,
    estimates: Sequence[Mapping[str, Any]],
    *,
    evidence_kind: str,
    evidence_id: str,
) -> M15PreexecutionEstimateSnapshot:
    """Seal one complete oracle-free estimate for all physical candidates."""

    _validated_candidate_payload(candidate_set)
    if evidence_kind not in _ALLOWED_EVIDENCE_KINDS:
        raise M15DirectSemanticFrontierError(
            "estimate evidence kind is not admitted for pre-execution selection"
        )
    selected_evidence_id = _safe_id(evidence_id, name="evidence_id")
    expected_plan_ids = set(candidate_set.plans)
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(estimates):
        if not isinstance(raw, Mapping) or set(raw) != _ESTIMATE_FIELDS:
            raise M15DirectSemanticFrontierError(
                f"estimates[{index}] fields do not match the sealed contract"
            )
        plan_id = _safe_id(raw["plan_id"], name="estimate plan_id")
        normalized.append(
            {
                "plan_id": plan_id,
                "estimated_latency_ms": _finite_nonnegative(
                    raw["estimated_latency_ms"],
                    name="estimated_latency_ms",
                ),
                "estimated_resource_cost_units": _finite_nonnegative(
                    raw["estimated_resource_cost_units"],
                    name="estimated_resource_cost_units",
                ),
            }
        )
    observed_ids = [item["plan_id"] for item in normalized]
    if len(observed_ids) != len(set(observed_ids)):
        raise M15DirectSemanticFrontierError("estimate plan IDs are not unique")
    if set(observed_ids) != expected_plan_ids:
        raise M15DirectSemanticFrontierError(
            "estimate snapshot must cover exactly every physical candidate"
        )
    body = {
        "schema_version": PREEXECUTION_ESTIMATE_SNAPSHOT_SCHEMA_VERSION,
        "candidate_set_sha256": candidate_set.candidate_set_hash,
        "evidence_kind": evidence_kind,
        "evidence_id": selected_evidence_id,
        "sealed_before_execution": True,
        "answer_oracle_fields": [],
        "post_execution_measurements_used": False,
        "estimates": sorted(normalized, key=lambda item: item["plan_id"]),
        "automatic_retries": 0,
        "paper_result": False,
    }
    snapshot = M15PreexecutionEstimateSnapshot(
        {**body, "estimate_snapshot_sha256": content_hash(body)}
    )
    _validated_snapshot_payload(snapshot, candidate_set=candidate_set)
    return snapshot


def _dominates(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    first_values = (
        float(first["semantic_deviation"]),
        float(first["estimated_latency_ms"]),
        float(first["estimated_resource_cost_units"]),
    )
    second_values = (
        float(second["semantic_deviation"]),
        float(second["estimated_latency_ms"]),
        float(second["estimated_resource_cost_units"]),
    )
    return all(
        first_value <= second_value
        for first_value, second_value in zip(
            first_values,
            second_values,
            strict=True,
        )
    ) and any(
        first_value < second_value
        for first_value, second_value in zip(
            first_values,
            second_values,
            strict=True,
        )
    )


def _relative_gain(reference: float, candidate: float) -> float:
    if reference == 0:
        return 0.0 if candidate == 0 else -math.inf
    return (reference - candidate) / reference


def _normalized_vector(
    record: Mapping[str, Any],
    bounds: Mapping[str, tuple[float, float]],
) -> tuple[float, float, float]:
    values = (
        float(record["semantic_deviation"]),
        float(record["estimated_latency_ms"]),
        float(record["estimated_resource_cost_units"]),
    )
    fields = (
        "semantic_deviation",
        "estimated_latency_ms",
        "estimated_resource_cost_units",
    )
    normalized: list[float] = []
    for value, field in zip(values, fields, strict=True):
        minimum, maximum = bounds[field]
        normalized.append(
            0.0
            if maximum == minimum
            else (value - minimum) / (maximum - minimum)
        )
    return tuple(normalized)  # type: ignore[return-value]


def _distance(first: Sequence[float], second: Sequence[float]) -> float:
    return math.sqrt(
        sum((left - right) ** 2 for left, right in zip(first, second, strict=True))
    )


def _bounded_representatives(
    records: list[dict[str, Any]],
    maximum: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []

    def add(record: dict[str, Any]) -> None:
        if (
            len(selected) < maximum
            and record["semantic_class_id"]
            not in {item["semantic_class_id"] for item in selected}
        ):
            selected.append(record)

    add(
        min(
            records,
            key=lambda item: (
                item["semantic_deviation"],
                item["estimated_latency_ms"],
                item["estimated_resource_cost_units"],
                item["plan_id"],
            ),
        )
    )
    add(
        min(
            records,
            key=lambda item: (
                item["estimated_latency_ms"],
                item["estimated_resource_cost_units"],
                item["semantic_deviation"],
                item["plan_id"],
            ),
        )
    )
    add(
        min(
            records,
            key=lambda item: (
                item["estimated_resource_cost_units"],
                item["estimated_latency_ms"],
                item["semantic_deviation"],
                item["plan_id"],
            ),
        )
    )
    fields = (
        "semantic_deviation",
        "estimated_latency_ms",
        "estimated_resource_cost_units",
    )
    bounds = {
        field: (
            min(float(item[field]) for item in records),
            max(float(item[field]) for item in records),
        )
        for field in fields
    }
    vectors = {
        item["semantic_class_id"]: _normalized_vector(item, bounds)
        for item in records
    }
    while len(selected) < maximum:
        remaining = [
            item
            for item in records
            if item["semantic_class_id"]
            not in {chosen["semantic_class_id"] for chosen in selected}
        ]
        if not remaining:
            break
        add(
            min(
                remaining,
                key=lambda item: (
                    -min(
                        _distance(
                            vectors[item["semantic_class_id"]],
                            vectors[chosen["semantic_class_id"]],
                        )
                        for chosen in selected
                    ),
                    item["plan_id"],
                ),
            )
        )
    return selected


def select_m15_direct_semantic_frontier(
    candidate_set: M15DirectSemanticCandidateSet,
    estimate_snapshot: M15PreexecutionEstimateSnapshot,
) -> M15DirectSemanticFrontier:
    """Reduce physical plans, then return a bounded direct semantic frontier."""

    candidates = _validated_candidate_payload(candidate_set)
    snapshot = _validated_snapshot_payload(
        estimate_snapshot,
        candidate_set=candidate_set,
    )
    estimate_by_plan = {
        str(item["plan_id"]): dict(item) for item in snapshot["estimates"]
    }
    class_by_id = {
        str(item["semantic_class_id"]): dict(item)
        for item in candidates["semantic_classes"]
    }
    enriched: list[dict[str, Any]] = []
    for raw in candidates["physical_candidates"]:
        estimate = estimate_by_plan.get(str(raw["plan_id"]))
        if estimate is None:
            raise M15DirectSemanticFrontierError(
                "estimate snapshot is incomplete at selection time"
            )
        semantic_class = class_by_id[str(raw["semantic_class_id"])]
        enriched.append(
            {
                "plan_id": raw["plan_id"],
                "physical_strategy": raw["physical_strategy"],
                "semantic_class_id": raw["semantic_class_id"],
                "canonical_interpretation_id": raw[
                    "canonical_interpretation_id"
                ],
                "query_id": raw["query_id"],
                "semantic_deviation": semantic_class["semantic_deviation"],
                "changed_slot_ids": semantic_class["changed_slot_ids"],
                "binding_values": semantic_class["binding_values"],
                "estimated_latency_ms": estimate["estimated_latency_ms"],
                "estimated_resource_cost_units": estimate[
                    "estimated_resource_cost_units"
                ],
                "estimate_evidence_id": snapshot["evidence_id"],
                "estimate_evidence_kind": snapshot["evidence_kind"],
            }
        )
    physical_representatives: list[dict[str, Any]] = []
    for class_id in sorted(class_by_id):
        eligible = [
            item for item in enriched if item["semantic_class_id"] == class_id
        ]
        if len(eligible) != 2:
            raise M15DirectSemanticFrontierError(
                "each direct class must have two estimated physical plans"
            )
        physical_representatives.append(
            min(
                eligible,
                key=lambda item: (
                    item["estimated_latency_ms"],
                    item["estimated_resource_cost_units"],
                    item["plan_id"],
                ),
            )
        )

    pareto = [
        candidate
        for candidate in physical_representatives
        if not any(
            _dominates(other, candidate)
            for other in physical_representatives
            if other["semantic_class_id"] != candidate["semantic_class_id"]
        )
    ]
    pareto.sort(key=lambda item: item["semantic_class_id"])
    policy = candidates["frontier_policy"]
    latency_epsilon = float(policy["minimum_latency_gain_ratio"])
    resource_epsilon = float(policy["minimum_resource_gain_ratio"])
    epsilon_frontier: list[dict[str, Any]] = []
    epsilon_removed: list[dict[str, Any]] = []
    for candidate in pareto:
        witnesses: list[dict[str, Any]] = []
        for reference in pareto:
            if reference["semantic_deviation"] >= candidate[
                "semantic_deviation"
            ]:
                continue
            latency_gain = _relative_gain(
                float(reference["estimated_latency_ms"]),
                float(candidate["estimated_latency_ms"]),
            )
            resource_gain = _relative_gain(
                float(reference["estimated_resource_cost_units"]),
                float(candidate["estimated_resource_cost_units"]),
            )
            if latency_gain < latency_epsilon and resource_gain < resource_epsilon:
                witnesses.append(
                    {
                        "semantic_class_id": reference["semantic_class_id"],
                        "latency_gain_ratio": latency_gain,
                        "resource_gain_ratio": resource_gain,
                    }
                )
        if witnesses:
            epsilon_removed.append(
                {
                    "semantic_class_id": candidate["semantic_class_id"],
                    "witnesses": sorted(
                        witnesses,
                        key=lambda item: item["semantic_class_id"],
                    ),
                }
            )
        else:
            epsilon_frontier.append(candidate)
    if not epsilon_frontier:
        raise M15DirectSemanticFrontierError(
            "semantic frontier unexpectedly removed every direct class"
        )
    representatives = _bounded_representatives(
        epsilon_frontier,
        int(policy["max_representatives"]),
    )
    returned = [
        {**record, "selection_rank": index}
        for index, record in enumerate(representatives, 1)
    ]
    if not returned or returned[0]["semantic_deviation"] != 0:
        raise M15DirectSemanticFrontierError(
            "the exact semantic interpretation must remain first"
        )
    returned_plans = [
        candidate_set.plans[item["plan_id"]].to_dict() for item in returned
    ]
    returned_class_ids = {item["semantic_class_id"] for item in returned}
    body = {
        "schema_version": DIRECT_SEMANTIC_FRONTIER_SCHEMA_VERSION,
        "candidate_set_sha256": candidate_set.candidate_set_hash,
        "estimate_snapshot_sha256": estimate_snapshot.snapshot_hash,
        "estimate_evidence_kind": snapshot["evidence_kind"],
        "estimate_evidence_id": snapshot["evidence_id"],
        "frontier_policy": dict(policy),
        "counts": {
            "declared_semantic_classes": candidates["counts"][
                "declared_semantic_classes"
            ],
            "executable_direct_semantic_classes": len(class_by_id),
            "unavailable_semantic_classes": len(
                candidates["unavailable_semantic_class_ids"]
            ),
            "physical_candidates": len(enriched),
            "physical_representatives": len(physical_representatives),
            "pareto_semantic_plans": len(pareto),
            "epsilon_frontier_semantic_plans": len(epsilon_frontier),
            "returned_semantic_plans": len(returned),
        },
        "physical_representatives": sorted(
            physical_representatives,
            key=lambda item: item["semantic_class_id"],
        ),
        "pareto_semantic_plans": pareto,
        "epsilon_removed": epsilon_removed,
        "epsilon_frontier_semantic_plans": epsilon_frontier,
        "returned_semantic_plans": returned,
        "returned_physical_plans": returned_plans,
        "not_returned_executable_semantic_class_ids": sorted(
            set(class_by_id) - returned_class_ids
        ),
        "unavailable_semantic_class_ids": list(
            candidates["unavailable_semantic_class_ids"]
        ),
        "claim_boundary": {
            "artifact_class": "preexecution_estimated_direct_semantic_frontier",
            "costs_are_predictions_not_observed_execution": True,
            "answer_oracle_used": False,
            "exact_semantics_retained": True,
            "blocked_multihop_classes_returned": False,
            "backend_calls_made_by_selector": 0,
            "llm_calls_made": 0,
            "ontology_calls_made": 0,
            "semantic_user_utility_validated": False,
            "performance_superiority_validated": False,
            "paper_result": False,
        },
        "automatic_retries": 0,
        "paper_result": False,
    }
    return M15DirectSemanticFrontier(
        {**body, "frontier_sha256": content_hash(body)}
    )
