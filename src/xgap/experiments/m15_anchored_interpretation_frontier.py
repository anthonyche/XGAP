"""Provenance-bound semantic relaxation after authoritative E5 binding.

This module is deliberately downstream of the R1 structural clarification
gate.  It never turns an unresolved interpretation, model proposal, ontology
neighbor, or low-cost plan into semantic authority.  Once both the structural
meaning and one representative predicate have authoritative bindings, it may
form a one-hop ontology-declared relaxation frontier around that base.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_hierarchical_interpretation_frontier import (
    HIERARCHICAL_INTERPRETATION_FRONTIER_SCHEMA_VERSION,
    M15HierarchicalInterpretationFrontier,
)
from xgap.experiments.m15_resolution_execution_bridge import (
    M15ResolutionExecutionBridgePlan,
    RESOLUTION_EXECUTION_BRIDGE_PLAN_SCHEMA_VERSION,
)


ANCHORED_RELAXATION_POLICY_SCHEMA_VERSION = (
    "m15-e5b-anchored-relaxation-policy-v1"
)
ANCHORED_INTERPRETATION_FRONTIER_SCHEMA_VERSION = (
    "m15-e5b-anchored-interpretation-frontier-v1"
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OBJECTIVES = [
    "semantic_deviation",
    "estimated_latency_ms",
    "estimated_total_bytes_moved",
]


class M15AnchoredInterpretationFrontierError(ValueError):
    """Raised before selection when semantic authority or provenance drifts."""


@dataclass(frozen=True)
class M15AnchoredInterpretationFrontier:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))

    @property
    def frontier_hash(self) -> str:
        return str(self.payload["anchored_frontier_sha256"])


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15AnchoredInterpretationFrontierError(
            f"{name} is not a safe identifier"
        )
    return value


def _sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise M15AnchoredInterpretationFrontierError(
            f"{name} is not a SHA-256 digest"
        )
    return value


def _object(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise M15AnchoredInterpretationFrontierError(f"{name} must be an object")
    return copy.deepcopy(dict(value))


def _finite_nonnegative(value: object, *, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise M15AnchoredInterpretationFrontierError(
            f"{name} must be finite and nonnegative"
        )
    return float(value)


def _json_object(
    value: Mapping[str, Any] | str | Path,
    *,
    name: str,
) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise M15AnchoredInterpretationFrontierError(
            f"{name} must be a regular non-symbolic-link file"
        )
    return _object(json.loads(path.read_text(encoding="utf-8")), name=name)


def _policy(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    raw = _json_object(value, name="anchored relaxation policy")
    expected_fields = {
        "schema_version",
        "policy_id",
        "anchor",
        "ontology_relaxation",
        "frontier_policy",
        "current_query_profile_calls",
        "oracle_inputs",
        "post_execution_measurements_used",
        "backend_calls_made",
        "llm_calls_made",
        "ontology_service_calls_made",
        "automatic_retries",
        "paper_result",
    }
    if set(raw) != expected_fields:
        raise M15AnchoredInterpretationFrontierError(
            "anchored relaxation policy fields do not match the contract"
        )
    if raw["schema_version"] != ANCHORED_RELAXATION_POLICY_SCHEMA_VERSION:
        raise M15AnchoredInterpretationFrontierError(
            "anchored relaxation policy schema is unsupported"
        )
    if raw["policy_id"] != "m15-e5b-anchored-predicate-sibling-development-v1":
        raise M15AnchoredInterpretationFrontierError(
            "anchored relaxation policy ID changed"
        )
    anchor = _object(raw["anchor"], name="anchor policy")
    if anchor != {
        "hole_id": "transfer-predicate",
        "authoritative_source_required": True,
        "base_semantic_deviation": 0.0,
    }:
        raise M15AnchoredInterpretationFrontierError("anchor policy changed")
    ontology = _object(raw["ontology_relaxation"], name="ontology policy")
    if ontology != {
        "source_artifact_role": "resolution_ontology",
        "ontology_id": "financial-risk-resolution-ontology",
        "ontology_version": "dev-v1",
        "candidate_kind": "predicate",
        "allowed_relations": ["sibling"],
        "maximum_hops": 1,
        "deviation_source": "declared_ontology_relation",
        "reverse_traversal_requires_bidirectional": True,
    }:
        raise M15AnchoredInterpretationFrontierError(
            "ontology relaxation policy changed"
        )
    frontier = _object(raw["frontier_policy"], name="frontier policy")
    if frontier != {
        "objectives": _OBJECTIVES,
        "epsilon_dominance": "semantic_preserving_minimum_cost_gain",
        "minimum_latency_gain_ratio": 0.05,
        "minimum_resource_gain_ratio": 0.05,
        "maximum_returned_plans": 4,
        "representative_selection": "exact_then_cost_extremes_then_maxmin",
    }:
        raise M15AnchoredInterpretationFrontierError("frontier policy changed")
    if (
        raw["current_query_profile_calls"] != 0
        or raw["oracle_inputs"] != []
        or raw["post_execution_measurements_used"] is not False
        or raw["backend_calls_made"] != 0
        or raw["llm_calls_made"] != 0
        or raw["ontology_service_calls_made"] != 0
        or raw["automatic_retries"] != 0
        or raw["paper_result"] is not False
    ):
        raise M15AnchoredInterpretationFrontierError(
            "anchored relaxation leakage or call boundary changed"
        )
    return raw


def _bridge_payload(bridge: M15ResolutionExecutionBridgePlan) -> dict[str, Any]:
    payload = bridge.to_dict()
    if payload.get("schema_version") != RESOLUTION_EXECUTION_BRIDGE_PLAN_SCHEMA_VERSION:
        raise M15AnchoredInterpretationFrontierError(
            "E5B requires an E4 resolution-execution bridge plan"
        )
    observed = _sha256(payload.get("bridge_plan_sha256"), name="bridge plan hash")
    if content_hash(
        {key: value for key, value in payload.items() if key != "bridge_plan_sha256"}
    ) != observed:
        raise M15AnchoredInterpretationFrontierError("bridge plan hash mismatch")
    return payload


def _hierarchical_payload(
    frontier: M15HierarchicalInterpretationFrontier,
    *,
    bridge: M15ResolutionExecutionBridgePlan,
) -> dict[str, Any]:
    payload = frontier.to_dict()
    if payload.get("schema_version") != HIERARCHICAL_INTERPRETATION_FRONTIER_SCHEMA_VERSION:
        raise M15AnchoredInterpretationFrontierError(
            "E5B requires an E5 hierarchical interpretation frontier"
        )
    observed = _sha256(
        payload.get("hierarchical_frontier_sha256"),
        name="hierarchical frontier hash",
    )
    if content_hash(
        {
            key: value
            for key, value in payload.items()
            if key != "hierarchical_frontier_sha256"
        }
    ) != observed:
        raise M15AnchoredInterpretationFrontierError(
            "hierarchical frontier hash mismatch"
        )
    if payload.get("bridge_plan_sha256") != bridge.plan_hash:
        raise M15AnchoredInterpretationFrontierError(
            "hierarchical frontier and bridge identity differ"
        )
    boundary = _object(payload.get("claim_boundary"), name="E5 claim boundary")
    if (
        payload.get("status") != "ready_with_bounded_representatives"
        or payload.get("clarification_required") is not False
        or payload.get("execution_eligible") is not True
        or not payload.get("authoritative_structural_selections")
        or payload.get("relaxation_frontiers") != []
        or boundary.get("hard_constraints_preserved") is not True
        or boundary.get("answer_oracle_used_for_selection") is not False
        or boundary.get("post_execution_measurements_used") is not False
        or boundary.get("current_query_profile_calls") != 0
        or boundary.get("backend_calls_made") != 0
        or boundary.get("llm_calls_made") != 0
        or boundary.get("ontology_service_calls_made") != 0
    ):
        raise M15AnchoredInterpretationFrontierError(
            "structural interpretation is not authoritatively ready for relaxation"
        )
    return payload


def _ontology_payload(
    path_value: str | Path,
    *,
    bridge_payload: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    path = Path(path_value)
    if path.is_symlink() or not path.is_file():
        raise M15AnchoredInterpretationFrontierError(
            "resolution ontology must be a regular non-symbolic-link file"
        )
    observed_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    sources = _object(bridge_payload.get("source_artifacts"), name="bridge sources")
    role = policy["ontology_relaxation"]["source_artifact_role"]
    source = _object(sources.get(role), name="resolution ontology source")
    if source.get("sha256") != observed_hash:
        raise M15AnchoredInterpretationFrontierError(
            "resolution ontology hash does not match the sealed E4 source"
        )
    ontology = _object(
        json.loads(path.read_text(encoding="utf-8")), name="resolution ontology"
    )
    if set(ontology) != {
        "schema_version",
        "ontology_id",
        "ontology_version",
        "concepts",
        "relations",
        "metadata",
    }:
        raise M15AnchoredInterpretationFrontierError(
            "resolution ontology fields do not match the contract"
        )
    ontology_policy = policy["ontology_relaxation"]
    if (
        ontology["schema_version"] != "m15-e3-resolution-ontology-v1"
        or ontology["ontology_id"] != ontology_policy["ontology_id"]
        or ontology["ontology_version"] != ontology_policy["ontology_version"]
    ):
        raise M15AnchoredInterpretationFrontierError(
            "resolution ontology identity changed"
        )
    metadata = _object(ontology["metadata"], name="ontology metadata")
    if (
        metadata.get("reasoning_depth") != 1
        or metadata.get("entity_resolution_allowed") is not False
        or metadata.get("domain_truth_claim") is not False
        or metadata.get("paper_result") is not False
    ):
        raise M15AnchoredInterpretationFrontierError(
            "resolution ontology claim boundary changed"
        )
    return ontology, observed_hash


def _dominates(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    left = tuple(float(first[field]) for field in _OBJECTIVES)
    right = tuple(float(second[field]) for field in _OBJECTIVES)
    return all(a <= b for a, b in zip(left, right, strict=True)) and any(
        a < b for a, b in zip(left, right, strict=True)
    )


def _relative_gain(reference: float, candidate: float) -> float:
    if reference == 0:
        return 0.0 if candidate == 0 else -math.inf
    return (reference - candidate) / reference


def _normalized_vector(
    record: Mapping[str, Any],
    bounds: Mapping[str, tuple[float, float]],
) -> tuple[float, ...]:
    result = []
    for field in _OBJECTIVES:
        value = float(record[field])
        minimum, maximum = bounds[field]
        result.append(
            0.0 if minimum == maximum else (value - minimum) / (maximum - minimum)
        )
    return tuple(result)


def _bounded_representatives(
    records: list[dict[str, Any]],
    maximum: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []

    def add(record: dict[str, Any]) -> None:
        if (
            len(selected) < maximum
            and record["interpretation_class_id"]
            not in {item["interpretation_class_id"] for item in selected}
        ):
            selected.append(record)

    add(
        min(
            records,
            key=lambda item: (
                item["semantic_deviation"],
                item["estimated_latency_ms"],
                item["estimated_total_bytes_moved"],
                item["interpretation_class_id"],
            ),
        )
    )
    add(
        min(
            records,
            key=lambda item: (
                item["estimated_latency_ms"],
                item["estimated_total_bytes_moved"],
                item["semantic_deviation"],
                item["interpretation_class_id"],
            ),
        )
    )
    add(
        min(
            records,
            key=lambda item: (
                item["estimated_total_bytes_moved"],
                item["estimated_latency_ms"],
                item["semantic_deviation"],
                item["interpretation_class_id"],
            ),
        )
    )
    bounds = {
        field: (
            min(float(item[field]) for item in records),
            max(float(item[field]) for item in records),
        )
        for field in _OBJECTIVES
    }
    vectors = {
        item["interpretation_class_id"]: _normalized_vector(item, bounds)
        for item in records
    }
    while len(selected) < maximum:
        selected_ids = {item["interpretation_class_id"] for item in selected}
        remaining = [
            item
            for item in records
            if item["interpretation_class_id"] not in selected_ids
        ]
        if not remaining:
            break
        add(
            min(
                remaining,
                key=lambda item: (
                    -min(
                        math.dist(
                            vectors[item["interpretation_class_id"]],
                            vectors[chosen["interpretation_class_id"]],
                        )
                        for chosen in selected
                    ),
                    item["interpretation_class_id"],
                ),
            )
        )
    return selected


def _relation_evidence(
    *,
    ontology: Mapping[str, Any],
    base_id: str,
    candidate_id: str,
    policy: Mapping[str, Any],
    ontology_sha256: str,
) -> dict[str, Any] | None:
    allowed = set(policy["ontology_relaxation"]["allowed_relations"])
    for raw in ontology["relations"]:
        relation = _object(raw, name="ontology relation")
        if set(relation) != {
            "source_id",
            "target_id",
            "relation",
            "deviation",
            "bidirectional",
            "provenance",
        }:
            raise M15AnchoredInterpretationFrontierError(
                "ontology relation fields do not match the contract"
            )
        source_id = _safe_id(relation["source_id"], name="relation source")
        target_id = _safe_id(relation["target_id"], name="relation target")
        relation_id = _safe_id(relation["relation"], name="relation ID")
        deviation = _finite_nonnegative(
            relation["deviation"], name="ontology relation deviation"
        )
        if deviation <= 0:
            raise M15AnchoredInterpretationFrontierError(
                "ontology relaxation deviation must be positive"
            )
        direction = None
        if source_id == base_id and target_id == candidate_id:
            direction = "forward"
        elif target_id == base_id and source_id == candidate_id:
            if (
                policy["ontology_relaxation"][
                    "reverse_traversal_requires_bidirectional"
                ]
                and relation["bidirectional"] is not True
            ):
                continue
            direction = "reverse"
        if direction is None or relation_id not in allowed:
            continue
        provenance = _object(relation["provenance"], name="relation provenance")
        if set(provenance) != {"evidence", "record_id"}:
            raise M15AnchoredInterpretationFrontierError(
                "ontology relation provenance fields changed"
            )
        return {
            "kind": "ontology_declared_one_hop_relaxation",
            "ontology_sha256": ontology_sha256,
            "ontology_id": ontology["ontology_id"],
            "ontology_version": ontology["ontology_version"],
            "relation": relation_id,
            "relation_source_id": source_id,
            "relation_target_id": target_id,
            "traversal_direction": direction,
            "hop_count": 1,
            "declared_deviation": deviation,
            "bidirectional": relation["bidirectional"],
            "provenance": provenance,
        }
    return None


def select_m15_anchored_interpretation_frontier(
    *,
    hierarchical_frontier: M15HierarchicalInterpretationFrontier,
    bridge: M15ResolutionExecutionBridgePlan,
    ontology_path: str | Path,
    relaxation_policy: Mapping[str, Any] | str | Path,
    authoritative_base_candidate_id: str,
    authority_source_id: str,
) -> M15AnchoredInterpretationFrontier:
    """Build an ontology-declared frontier around one authoritative predicate."""

    policy = _policy(relaxation_policy)
    bridge_payload = _bridge_payload(bridge)
    hierarchical = _hierarchical_payload(
        hierarchical_frontier,
        bridge=bridge,
    )
    ontology, ontology_sha256 = _ontology_payload(
        ontology_path,
        bridge_payload=bridge_payload,
        policy=policy,
    )
    anchor_hole = policy["anchor"]["hole_id"]
    base_candidate_id = _safe_id(
        authoritative_base_candidate_id,
        name="authoritative base candidate",
    )
    authority_id = _safe_id(authority_source_id, name="authority source ID")

    active_ids = set(hierarchical["active_interpretation_class_ids"])
    class_records = {
        item["interpretation_class_id"]: copy.deepcopy(item)
        for item in hierarchical["all_interpretation_classes"]
    }
    active = [class_records[class_id] for class_id in sorted(active_ids)]
    executable = [item for item in active if item["availability"] == "executable"]
    if not executable:
        raise M15AnchoredInterpretationFrontierError(
            "authoritatively selected structure has no executable interpretation"
        )
    candidates = {
        item["selected_candidate_ids"][anchor_hole]: item for item in executable
    }
    if len(candidates) != len(executable) or base_candidate_id not in candidates:
        raise M15AnchoredInterpretationFrontierError(
            "authoritative base candidate is outside the active executable set"
        )
    structure_hashes = {item["structural_signature_sha256"] for item in executable}
    if len(structure_hashes) != 1:
        raise M15AnchoredInterpretationFrontierError(
            "anchored predicate relaxation crossed an R1 structural boundary"
        )

    concept_kinds: dict[str, str] = {}
    for raw in ontology["concepts"]:
        concept = _object(raw, name="ontology concept")
        candidate_id = _safe_id(concept.get("candidate_id"), name="concept candidate")
        kind = _safe_id(concept.get("kind"), name="concept kind")
        if candidate_id in concept_kinds:
            raise M15AnchoredInterpretationFrontierError(
                "ontology concept IDs are duplicated"
            )
        concept_kinds[candidate_id] = kind
    expected_kind = policy["ontology_relaxation"]["candidate_kind"]
    if any(concept_kinds.get(candidate_id) != expected_kind for candidate_id in candidates):
        raise M15AnchoredInterpretationFrontierError(
            "active predicate candidates lack matching ontology concepts"
        )

    anchored: list[dict[str, Any]] = []
    base_class_id = candidates[base_candidate_id]["interpretation_class_id"]
    for candidate_id, item in sorted(candidates.items()):
        representative = _object(
            item.get("physical_representative"),
            name="physical representative",
        )
        if candidate_id == base_candidate_id:
            deviation = float(policy["anchor"]["base_semantic_deviation"])
            evidence = {
                "kind": "authoritative_base",
                "candidate_id": candidate_id,
                "authority_source_id": authority_id,
            }
            status = "authoritatively_bound"
        else:
            evidence = _relation_evidence(
                ontology=ontology,
                base_id=base_candidate_id,
                candidate_id=candidate_id,
                policy=policy,
                ontology_sha256=ontology_sha256,
            )
            if evidence is None:
                continue
            deviation = float(evidence["declared_deviation"])
            status = "anchored_relaxation"
        anchored.append(
            {
                "interpretation_class_id": item["interpretation_class_id"],
                "selected_candidate_ids": copy.deepcopy(
                    item["selected_candidate_ids"]
                ),
                "interpretation_status": status,
                "relaxation_base_id": base_class_id,
                "semantic_deviation": deviation,
                "semantic_deviation_evidence": evidence,
                "plan_id": representative["plan_id"],
                "physical_strategy": representative["physical_strategy"],
                "estimated_latency_ms": _finite_nonnegative(
                    representative["estimated_latency_ms"],
                    name="estimated latency",
                ),
                "estimated_total_bytes_moved": _finite_nonnegative(
                    representative["estimated_total_bytes_moved"],
                    name="estimated transferred bytes",
                ),
                "uncertainty": copy.deepcopy(representative["uncertainty"]),
                "family_cost_prediction_source_sha256": representative[
                    "family_cost_prediction_source_sha256"
                ],
            }
        )
    if not anchored or sum(
        item["interpretation_status"] == "authoritatively_bound" for item in anchored
    ) != 1:
        raise M15AnchoredInterpretationFrontierError(
            "anchored frontier must contain exactly one authoritative base"
        )

    pareto = [
        candidate
        for candidate in anchored
        if not any(
            _dominates(other, candidate)
            for other in anchored
            if other["interpretation_class_id"]
            != candidate["interpretation_class_id"]
        )
    ]
    pareto.sort(key=lambda item: item["interpretation_class_id"])
    frontier_policy = policy["frontier_policy"]
    latency_epsilon = float(frontier_policy["minimum_latency_gain_ratio"])
    resource_epsilon = float(frontier_policy["minimum_resource_gain_ratio"])
    epsilon_frontier: list[dict[str, Any]] = []
    epsilon_removed: list[dict[str, Any]] = []
    for candidate in pareto:
        witnesses = []
        for reference in pareto:
            if reference["semantic_deviation"] >= candidate["semantic_deviation"]:
                continue
            latency_gain = _relative_gain(
                float(reference["estimated_latency_ms"]),
                float(candidate["estimated_latency_ms"]),
            )
            resource_gain = _relative_gain(
                float(reference["estimated_total_bytes_moved"]),
                float(candidate["estimated_total_bytes_moved"]),
            )
            if latency_gain < latency_epsilon and resource_gain < resource_epsilon:
                witnesses.append(
                    {
                        "interpretation_class_id": reference[
                            "interpretation_class_id"
                        ],
                        "latency_gain_ratio": latency_gain,
                        "resource_gain_ratio": resource_gain,
                    }
                )
        if witnesses:
            epsilon_removed.append(
                {
                    "interpretation_class_id": candidate[
                        "interpretation_class_id"
                    ],
                    "witnesses": sorted(
                        witnesses,
                        key=lambda item: item["interpretation_class_id"],
                    ),
                }
            )
        else:
            epsilon_frontier.append(candidate)
    returned = [
        {**item, "selection_rank": index}
        for index, item in enumerate(
            _bounded_representatives(
                epsilon_frontier,
                int(frontier_policy["maximum_returned_plans"]),
            ),
            1,
        )
    ]
    if not returned or returned[0]["interpretation_status"] != "authoritatively_bound":
        raise M15AnchoredInterpretationFrontierError(
            "authoritative base must remain the first returned plan"
        )

    annotated_classes = []
    anchored_by_id = {
        item["interpretation_class_id"]: item for item in anchored
    }
    for class_id in sorted(class_records):
        record = class_records[class_id]
        if class_id in anchored_by_id:
            selected = anchored_by_id[class_id]
            record["interpretation_status"] = selected["interpretation_status"]
            record["relaxation_base_id"] = selected["relaxation_base_id"]
            record["semantic_deviation"] = selected["semantic_deviation"]
            record["semantic_deviation_evidence"] = copy.deepcopy(
                selected["semantic_deviation_evidence"]
            )
        annotated_classes.append(record)

    returned_ids = {item["interpretation_class_id"] for item in returned}
    body = {
        "schema_version": ANCHORED_INTERPRETATION_FRONTIER_SCHEMA_VERSION,
        "status": "ready_with_anchored_relaxation_frontier",
        "hierarchical_frontier_sha256": hierarchical_frontier.frontier_hash,
        "bridge_plan_sha256": bridge.plan_hash,
        "resolution_commit_sha256": hierarchical["resolution_commit_sha256"],
        "hard_constraints_sha256": hierarchical["hard_constraints_sha256"],
        "resolved_entity_bindings": copy.deepcopy(
            hierarchical["resolved_entity_bindings"]
        ),
        "authoritative_structural_selections": copy.deepcopy(
            hierarchical["authoritative_structural_selections"]
        ),
        "structural_authority_source_id": hierarchical["authority_source_id"],
        "authoritative_base": {
            "hole_id": anchor_hole,
            "candidate_id": base_candidate_id,
            "interpretation_class_id": base_class_id,
            "authority_source_id": authority_id,
        },
        "relaxation_policy_sha256": content_hash(policy),
        "ontology_source": {
            "role": policy["ontology_relaxation"]["source_artifact_role"],
            "sha256": ontology_sha256,
            "ontology_id": ontology["ontology_id"],
            "ontology_version": ontology["ontology_version"],
            "domain_truth_claim": False,
        },
        "family_cost_prediction_source_sha256": hierarchical[
            "family_cost_prediction_source"
        ]["prediction_source_sha256"],
        "all_interpretation_classes": annotated_classes,
        "anchored_interpretation_plans": anchored,
        "pareto_interpretation_plans": pareto,
        "epsilon_removed": epsilon_removed,
        "epsilon_frontier_interpretation_plans": epsilon_frontier,
        "returned_interpretation_plans": returned,
        "not_returned_anchored_interpretation_class_ids": sorted(
            set(anchored_by_id) - returned_ids
        ),
        "counts": {
            "interpretation_classes": len(class_records),
            "active_interpretation_classes": len(active),
            "anchored_interpretation_classes": len(anchored),
            "physical_representatives": len(anchored),
            "pareto_interpretation_plans": len(pareto),
            "epsilon_frontier_interpretation_plans": len(epsilon_frontier),
            "returned_interpretation_plans": len(returned),
            "current_query_profile_calls": 0,
        },
        "selection_boundary": {
            "hierarchical_objective": "anchored_semantic_then_physical",
            "semantic_deviation_source": "authoritative_base_or_declared_ontology_relation",
            "physical_estimate_source": "sealed_same_family_strategy_conditioned_memory",
            "one_physical_representative_per_interpretation": True,
            "frontier_policy": copy.deepcopy(frontier_policy),
            "unresolved_interpretations_compared_by_semantic_deviation": False,
        },
        "claim_boundary": {
            "artifact_class": "offline_anchored_relaxation_mechanism",
            "development_artifacts_only": True,
            "authoritative_base_required": True,
            "hard_constraints_preserved": True,
            "all_bounded_interpretations_preserved": True,
            "unavailable_interpretations_preserved": True,
            "ontology_relation_used_as_domain_truth": False,
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
    return M15AnchoredInterpretationFrontier(
        {**body, "anchored_frontier_sha256": content_hash(body)}
    )
