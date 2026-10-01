"""Build a bounded semantic interpretation frontier for one M15 query.

F2C6 is deliberately a planning-only mechanism.  It validates explicit,
evidence-backed relaxation transitions, recompiles every derived binding as a
typed parameterized query, merges semantically equivalent derivations, keeps
one successful physical plan per semantic class, and applies deterministic
Pareto, epsilon, and K-bounded reductions.  It performs no backend, ontology,
or LLM calls and does not produce paper evidence.
"""

from __future__ import annotations

import argparse
import copy
import itertools
import json
import math
import re
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_parameterized_query import (
    M15ParameterizedQueryError,
    compile_m15_parameterized_query,
)


SEMANTIC_RELAXATION_CATALOG_SCHEMA_VERSION = (
    "m15-f2c6-semantic-relaxation-catalog-v1"
)
SEMANTIC_SOLUTION_SPACE_SCHEMA_VERSION = "m15-f2c6-semantic-solution-space-v1"
SEMANTIC_FRONTIER_SCHEMA_VERSION = "m15-f2c6-semantic-frontier-v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")
_EXPECTED_CATALOG_FIELDS = {
    "schema_version",
    "catalog_id",
    "family_compatibility_sha256",
    "semantic_deviation",
    "dimensions",
    "frontier_policy",
    "max_raw_interpretations",
    "automatic_retries",
    "paper_result",
}


class M15SemanticFrontierError(ValueError):
    """Raised before output when an F2C6 contract is invalid."""


@dataclass(frozen=True)
class M15SemanticRelaxationCatalog:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))

    @property
    def catalog_hash(self) -> str:
        return content_hash(self.payload)


@dataclass(frozen=True)
class M15SemanticSolutionSpace:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))

    @property
    def solution_space_hash(self) -> str:
        return str(self.payload["solution_space_sha256"])


@dataclass(frozen=True)
class M15SemanticFrontier:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))


def _object(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise M15SemanticFrontierError(f"{name} must be an object")
    return dict(value)


def _strict_object(
    value: object,
    *,
    name: str,
    fields: set[str],
) -> dict[str, Any]:
    result = _object(value, name=name)
    if set(result) != fields:
        raise M15SemanticFrontierError(
            f"{name} fields do not match the F2C6 contract"
        )
    return result


def _array(value: object, *, name: str, allow_empty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "an array" if allow_empty else "a nonempty array"
        raise M15SemanticFrontierError(f"{name} must be {qualifier}")
    return value


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15SemanticFrontierError(f"{name} must be a safe identifier")
    return value


def _sha256(value: object, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise M15SemanticFrontierError(f"{name} must be a lowercase SHA-256")
    return value


def _ratio(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise M15SemanticFrontierError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result < 1.0:
        raise M15SemanticFrontierError(f"{name} must be in [0, 1)")
    return result


def _positive_integer(value: object, *, name: str, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= maximum
    ):
        raise M15SemanticFrontierError(
            f"{name} must be an integer between 1 and {maximum}"
        )
    return value


def _finite_nonnegative(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise M15SemanticFrontierError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise M15SemanticFrontierError(f"{name} must be finite and nonnegative")
    return result


def _binding_value(value: object, *, name: str) -> Any:
    try:
        content_hash(value)
    except (TypeError, ValueError) as exc:
        raise M15SemanticFrontierError(f"{name} must be a finite JSON value") from exc
    if isinstance(value, (Mapping, list)) or value is None:
        raise M15SemanticFrontierError(f"{name} must be a scalar binding value")
    return value


def load_m15_semantic_relaxation_catalog(
    path: str | Path,
) -> M15SemanticRelaxationCatalog:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise M15SemanticFrontierError(
            "semantic relaxation catalog must be a regular non-symbolic-link file"
        )
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    return validate_m15_semantic_relaxation_catalog(payload)


def validate_m15_semantic_relaxation_catalog(
    value: Mapping[str, Any],
) -> M15SemanticRelaxationCatalog:
    raw = _strict_object(
        value,
        name="semantic relaxation catalog",
        fields=_EXPECTED_CATALOG_FIELDS,
    )
    if raw["schema_version"] != SEMANTIC_RELAXATION_CATALOG_SCHEMA_VERSION:
        raise M15SemanticFrontierError(
            "semantic relaxation catalog schema_version is unsupported"
        )
    catalog_id = _safe_id(raw["catalog_id"], name="catalog_id")
    family_hash = _sha256(
        raw["family_compatibility_sha256"],
        name="family_compatibility_sha256",
    )
    semantic = _strict_object(
        raw["semantic_deviation"],
        name="semantic_deviation",
        fields={"method", "version"},
    )
    if semantic["method"] != "uniform_mean_normalized_relaxation_steps":
        raise M15SemanticFrontierError(
            "F2C6 requires uniform_mean_normalized_relaxation_steps"
        )
    semantic_version = _safe_id(semantic["version"], name="semantic version")

    dimensions: list[dict[str, Any]] = []
    dimension_ids: list[str] = []
    transition_ids: list[str] = []
    for dimension_index, item in enumerate(
        _array(raw["dimensions"], name="dimensions")
    ):
        dimension = _strict_object(
            item,
            name=f"dimensions[{dimension_index}]",
            fields={"constraint_id", "slot_id", "transitions"},
        )
        constraint_id = _safe_id(
            dimension["constraint_id"], name="dimension constraint_id"
        )
        slot_id = _safe_id(dimension["slot_id"], name="dimension slot_id")
        dimension_ids.append(constraint_id)
        transitions: list[dict[str, Any]] = []
        semantic_targets: dict[str, Any] = {}
        for transition_index, transition_item in enumerate(
            _array(dimension["transitions"], name="dimension transitions")
        ):
            transition = _strict_object(
                transition_item,
                name=(
                    f"dimensions[{dimension_index}].transitions[{transition_index}]"
                ),
                fields={
                    "transition_id",
                    "from_value",
                    "to_value",
                    "semantic_value_id",
                    "transformation",
                    "steps",
                    "evidence",
                },
            )
            transition_id = _safe_id(
                transition["transition_id"], name="transition_id"
            )
            transition_ids.append(transition_id)
            from_value = _binding_value(
                transition["from_value"], name=f"{transition_id}.from_value"
            )
            to_value = _binding_value(
                transition["to_value"], name=f"{transition_id}.to_value"
            )
            if from_value == to_value:
                raise M15SemanticFrontierError(
                    f"transition '{transition_id}' must change the binding value"
                )
            semantic_value_id = _safe_id(
                transition["semantic_value_id"], name="semantic_value_id"
            )
            if (
                semantic_value_id in semantic_targets
                and semantic_targets[semantic_value_id] != to_value
            ):
                raise M15SemanticFrontierError(
                    f"semantic value '{semantic_value_id}' maps to multiple values"
                )
            semantic_targets[semantic_value_id] = to_value
            evidence = _strict_object(
                transition["evidence"],
                name=f"transition '{transition_id}' evidence",
                fields={"kind", "reference"},
            )
            transitions.append(
                {
                    "transition_id": transition_id,
                    "from_value": from_value,
                    "to_value": to_value,
                    "semantic_value_id": semantic_value_id,
                    "transformation": _safe_id(
                        transition["transformation"], name="transformation"
                    ),
                    "steps": _positive_integer(
                        transition["steps"], name="transition steps", maximum=16
                    ),
                    "evidence": {
                        "kind": _safe_id(evidence["kind"], name="evidence kind"),
                        "reference": _safe_id(
                            evidence["reference"], name="evidence reference"
                        ),
                    },
                }
            )
        dimensions.append(
            {
                "constraint_id": constraint_id,
                "slot_id": slot_id,
                "transitions": sorted(
                    transitions, key=lambda item: item["transition_id"]
                ),
            }
        )
    if len(dimension_ids) != len(set(dimension_ids)):
        raise M15SemanticFrontierError("dimension constraint IDs must be unique")
    if len(transition_ids) != len(set(transition_ids)):
        raise M15SemanticFrontierError("transition IDs must be globally unique")

    policy = _strict_object(
        raw["frontier_policy"],
        name="frontier_policy",
        fields={
            "physical_plan_reduction",
            "epsilon_dominance",
            "minimum_latency_gain_ratio",
            "minimum_resource_gain_ratio",
            "max_representatives",
            "representative_selection",
        },
    )
    if policy["physical_plan_reduction"] != "latency_then_resource_then_plan_id":
        raise M15SemanticFrontierError(
            "F2C6 physical plan reduction policy is unsupported"
        )
    if policy["epsilon_dominance"] != "semantic_preserving_minimum_cost_gain":
        raise M15SemanticFrontierError("F2C6 epsilon dominance is unsupported")
    if policy["representative_selection"] != (
        "exact_then_cost_extremes_then_maxmin"
    ):
        raise M15SemanticFrontierError(
            "F2C6 representative selection policy is unsupported"
        )
    normalized_policy = {
        "physical_plan_reduction": policy["physical_plan_reduction"],
        "epsilon_dominance": policy["epsilon_dominance"],
        "minimum_latency_gain_ratio": _ratio(
            policy["minimum_latency_gain_ratio"],
            name="minimum_latency_gain_ratio",
        ),
        "minimum_resource_gain_ratio": _ratio(
            policy["minimum_resource_gain_ratio"],
            name="minimum_resource_gain_ratio",
        ),
        "max_representatives": _positive_integer(
            policy["max_representatives"],
            name="max_representatives",
            maximum=64,
        ),
        "representative_selection": policy["representative_selection"],
    }
    max_raw = _positive_integer(
        raw["max_raw_interpretations"],
        name="max_raw_interpretations",
        maximum=4096,
    )
    if raw["automatic_retries"] != 0 or raw["paper_result"] is not False:
        raise M15SemanticFrontierError(
            "F2C6 must disable retry and remain paper_result=false"
        )
    normalized = {
        "schema_version": SEMANTIC_RELAXATION_CATALOG_SCHEMA_VERSION,
        "catalog_id": catalog_id,
        "family_compatibility_sha256": family_hash,
        "semantic_deviation": {
            "method": semantic["method"],
            "version": semantic_version,
        },
        "dimensions": sorted(dimensions, key=lambda item: item["constraint_id"]),
        "frontier_policy": normalized_policy,
        "max_raw_interpretations": max_raw,
        "automatic_retries": 0,
        "paper_result": False,
    }
    return M15SemanticRelaxationCatalog(normalized)


def _query_contract_metadata(
    query_spec: Mapping[str, Any],
) -> tuple[Any, dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    try:
        contract = compile_m15_parameterized_query(query_spec)
    except M15ParameterizedQueryError as exc:
        raise M15SemanticFrontierError(str(exc)) from exc
    bindings = {
        str(item["slot_id"]): dict(item)
        for item in _array(query_spec.get("binding_slots"), name="binding_slots")
    }
    constraints: dict[str, dict[str, Any]] = {}
    for operator in _array(
        _object(query_spec.get("semantic_template"), name="semantic_template").get(
            "operators"
        ),
        name="semantic_template.operators",
    ):
        for constraint in _array(
            _object(operator, name="semantic operator").get("constraints"),
            name="operator.constraints",
            allow_empty=True,
        ):
            raw_constraint = _object(constraint, name="semantic constraint")
            constraint_id = str(raw_constraint.get("constraint_id"))
            if constraint_id in constraints:
                raise M15SemanticFrontierError("constraint IDs must be unique")
            constraints[constraint_id] = raw_constraint
    return contract, contract.to_dict(), bindings, constraints


def _exact_semantic_value_id(slot_id: str, value: object) -> str:
    return f"exact-{slot_id}-{content_hash(value)[:16]}"


def build_m15_semantic_solution_space(
    query_spec: Mapping[str, Any],
    catalog: M15SemanticRelaxationCatalog | Mapping[str, Any],
) -> M15SemanticSolutionSpace:
    selected_catalog = (
        catalog
        if isinstance(catalog, M15SemanticRelaxationCatalog)
        else validate_m15_semantic_relaxation_catalog(catalog)
    )
    catalog_payload = selected_catalog.to_dict()
    base_contract, base_payload, bindings, constraints = _query_contract_metadata(
        query_spec
    )
    if base_contract.family_hash != catalog_payload["family_compatibility_sha256"]:
        raise M15SemanticFrontierError(
            "catalog and query family compatibility hashes differ"
        )

    relaxable = {
        constraint_id: constraint
        for constraint_id, constraint in constraints.items()
        if constraint.get("policy") == "relaxable"
    }
    hard = {
        constraint_id: constraint
        for constraint_id, constraint in constraints.items()
        if constraint.get("policy") == "hard"
    }
    dimension_by_constraint = {
        item["constraint_id"]: item for item in catalog_payload["dimensions"]
    }
    if set(dimension_by_constraint) != set(relaxable):
        raise M15SemanticFrontierError(
            "catalog dimensions must cover all and only relaxable constraints"
        )

    hard_slot_ids: set[str] = set()
    for constraint_id, constraint in hard.items():
        slot_ids = constraint.get("binding_slot_ids")
        if not isinstance(slot_ids, list):
            raise M15SemanticFrontierError(
                f"hard constraint '{constraint_id}' has invalid binding slots"
            )
        hard_slot_ids.update(str(item) for item in slot_ids)
    hard_bindings = {
        slot_id: bindings[slot_id]["value"] for slot_id in sorted(hard_slot_ids)
    }

    options_by_dimension: list[tuple[str, str, int, list[dict[str, Any]]]] = []
    for constraint_id in sorted(relaxable):
        constraint = relaxable[constraint_id]
        slot_ids = constraint.get("binding_slot_ids")
        if not isinstance(slot_ids, list) or len(slot_ids) != 1:
            raise M15SemanticFrontierError(
                "F2C6 requires one binding slot per relaxable constraint"
            )
        slot_id = str(slot_ids[0])
        dimension = dimension_by_constraint[constraint_id]
        if dimension["slot_id"] != slot_id:
            raise M15SemanticFrontierError(
                f"dimension '{constraint_id}' does not match its binding slot"
            )
        if slot_id in hard_slot_ids:
            raise M15SemanticFrontierError(
                f"relaxation dimension '{constraint_id}' targets a hard binding"
            )
        if slot_id not in bindings:
            raise M15SemanticFrontierError(
                f"dimension '{constraint_id}' references an unknown binding"
            )
        relaxation = constraint.get("relaxation")
        if not isinstance(relaxation, Mapping):
            raise M15SemanticFrontierError(
                f"constraint '{constraint_id}' lacks a relaxation contract"
            )
        transformations = relaxation.get("transformations")
        max_steps = relaxation.get("max_steps")
        if not isinstance(transformations, list) or not isinstance(max_steps, int):
            raise M15SemanticFrontierError(
                f"constraint '{constraint_id}' relaxation contract is invalid"
            )
        current_value = bindings[slot_id]["value"]
        options = [
            {
                "transition_id": None,
                "from_value": current_value,
                "to_value": current_value,
                "semantic_value_id": _exact_semantic_value_id(
                    slot_id, current_value
                ),
                "transformation": None,
                "steps": 0,
                "evidence": None,
            }
        ]
        for transition in dimension["transitions"]:
            if transition["transformation"] not in transformations:
                raise M15SemanticFrontierError(
                    f"transition '{transition['transition_id']}' uses an "
                    "undeclared transformation"
                )
            if transition["steps"] > max_steps:
                raise M15SemanticFrontierError(
                    f"transition '{transition['transition_id']}' exceeds max_steps"
                )
            if transition["from_value"] == current_value:
                options.append(dict(transition))
        options_by_dimension.append(
            (constraint_id, slot_id, int(max_steps), options)
        )

    raw_count = math.prod(len(item[3]) for item in options_by_dimension)
    if raw_count > catalog_payload["max_raw_interpretations"]:
        raise M15SemanticFrontierError(
            "raw interpretation count exceeds max_raw_interpretations"
        )

    raw_interpretations: list[dict[str, Any]] = []
    for combination in itertools.product(
        *(item[3] for item in options_by_dimension)
    ):
        altered_spec = copy.deepcopy(dict(query_spec))
        altered_slots = {
            str(item["slot_id"]): item for item in altered_spec["binding_slots"]
        }
        semantic_values: list[dict[str, Any]] = []
        transitions: list[dict[str, Any]] = []
        deviation = Fraction(0, 1)
        for (constraint_id, slot_id, max_steps, _), option in zip(
            options_by_dimension, combination, strict=True
        ):
            altered_slots[slot_id]["value"] = option["to_value"]
            semantic_values.append(
                {
                    "constraint_id": constraint_id,
                    "slot_id": slot_id,
                    "semantic_value_id": option["semantic_value_id"],
                    "value": option["to_value"],
                }
            )
            if option["transition_id"] is not None:
                transitions.append(
                    {
                        "constraint_id": constraint_id,
                        "slot_id": slot_id,
                        **dict(option),
                    }
                )
            deviation += Fraction(int(option["steps"]), max_steps)
        deviation /= len(options_by_dimension)
        try:
            derived_contract = compile_m15_parameterized_query(altered_spec)
        except M15ParameterizedQueryError as exc:
            raise M15SemanticFrontierError(
                f"relaxed interpretation failed typed compilation: {exc}"
            ) from exc
        derived = derived_contract.to_dict()
        if derived_contract.family_hash != base_contract.family_hash:
            raise M15SemanticFrontierError(
                "relaxation changed structural query-family identity"
            )
        derived_bindings = {
            str(item["slot_id"]): item["value"] for item in derived["bindings"]
        }
        if any(
            derived_bindings[slot_id] != value
            for slot_id, value in hard_bindings.items()
        ):
            raise M15SemanticFrontierError("relaxation mutated a hard constraint")
        signature_body = {
            "family_compatibility_sha256": base_contract.family_hash,
            "hard_bindings": hard_bindings,
            "semantic_values": sorted(
                semantic_values, key=lambda item: item["constraint_id"]
            ),
        }
        derivation_body = {
            "signature": signature_body,
            "transition_ids": sorted(
                item["transition_id"] for item in transitions
            ),
        }
        raw_interpretations.append(
            {
                "interpretation_id": (
                    "m15-semantic-" + content_hash(derivation_body)[:24]
                ),
                "semantic_signature_sha256": content_hash(signature_body),
                "semantic_values": sorted(
                    semantic_values, key=lambda item: item["constraint_id"]
                ),
                "transitions": sorted(
                    transitions, key=lambda item: item["constraint_id"]
                ),
                "relaxation_step_count": sum(
                    int(item["steps"]) for item in transitions
                ),
                "semantic_deviation": float(deviation),
                "semantic_deviation_fraction": {
                    "numerator": deviation.numerator,
                    "denominator": deviation.denominator,
                },
                "bindings": derived["bindings"],
                "binding_sha256": derived["binding_sha256"],
                "typed_program_sha256": derived["typed_program_sha256"],
                "query_instance_sha256": derived["query_instance_sha256"],
                "compiled_contract_sha256": content_hash(derived),
            }
        )
    interpretation_ids = [
        item["interpretation_id"] for item in raw_interpretations
    ]
    if len(interpretation_ids) != len(set(interpretation_ids)):
        raise M15SemanticFrontierError("raw interpretation IDs are not unique")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for interpretation in raw_interpretations:
        grouped.setdefault(
            interpretation["semantic_signature_sha256"], []
        ).append(interpretation)
    classes: list[dict[str, Any]] = []
    for signature_hash, members in sorted(grouped.items()):
        canonical = min(
            members,
            key=lambda item: (
                item["semantic_deviation"],
                item["interpretation_id"],
            ),
        )
        if any(item["bindings"] != canonical["bindings"] for item in members):
            raise M15SemanticFrontierError(
                "one semantic equivalence class contains different bindings"
            )
        classes.append(
            {
                "semantic_class_id": "m15-class-" + signature_hash[:24],
                "semantic_signature_sha256": signature_hash,
                "member_interpretation_ids": sorted(
                    item["interpretation_id"] for item in members
                ),
                "canonical_interpretation_id": canonical["interpretation_id"],
                "semantic_deviation": canonical["semantic_deviation"],
                "semantic_deviation_fraction": canonical[
                    "semantic_deviation_fraction"
                ],
                "bindings": canonical["bindings"],
                "binding_sha256": canonical["binding_sha256"],
                "query_instance_sha256": canonical["query_instance_sha256"],
            }
        )

    raw_interpretations.sort(key=lambda item: item["interpretation_id"])
    classes.sort(key=lambda item: item["semantic_class_id"])
    body = {
        "schema_version": SEMANTIC_SOLUTION_SPACE_SCHEMA_VERSION,
        "catalog_id": catalog_payload["catalog_id"],
        "catalog_sha256": selected_catalog.catalog_hash,
        "family_compatibility_sha256": base_contract.family_hash,
        "base_query_instance_sha256": base_payload["query_instance_sha256"],
        "base_query_spec_sha256": content_hash(query_spec),
        "semantic_deviation": catalog_payload["semantic_deviation"],
        "hard_bindings": hard_bindings,
        "frontier_policy": catalog_payload["frontier_policy"],
        "raw_interpretation_count": len(raw_interpretations),
        "semantic_class_count": len(classes),
        "raw_interpretations": raw_interpretations,
        "semantic_equivalence_classes": classes,
        "claim_boundary": {
            "artifact_class": "unexecuted_bounded_semantic_solution_space",
            "backend_calls_made": 0,
            "llm_calls_made": 0,
            "ontology_calls_made": 0,
            "contains_measurements": False,
            "paper_result": False,
        },
        "automatic_retries": 0,
        "paper_result": False,
    }
    return M15SemanticSolutionSpace(
        {**body, "solution_space_sha256": content_hash(body)}
    )


def _dominates(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    first_values = (
        first["semantic_deviation"],
        first["latency_ms"],
        first["resource_cost_units"],
    )
    second_values = (
        second["semantic_deviation"],
        second["latency_ms"],
        second["resource_cost_units"],
    )
    no_worse = all(
        a <= b for a, b in zip(first_values, second_values, strict=True)
    )
    strictly_better = any(
        a < b for a, b in zip(first_values, second_values, strict=True)
    )
    return no_worse and strictly_better


def _relative_gain(reference: float, candidate: float) -> float:
    if reference == 0:
        return 0.0 if candidate == 0 else -math.inf
    return (reference - candidate) / reference


def _normalized_vector(
    plan: Mapping[str, Any],
    bounds: Mapping[str, tuple[float, float]],
) -> tuple[float, float, float]:
    values = (
        float(plan["semantic_deviation"]),
        float(plan["latency_ms"]),
        float(plan["resource_cost_units"]),
    )
    result = []
    for value, field in zip(
        values,
        ("semantic_deviation", "latency_ms", "resource_cost_units"),
        strict=True,
    ):
        minimum, maximum = bounds[field]
        normalized = (
            0.0
            if maximum == minimum
            else (value - minimum) / (maximum - minimum)
        )
        result.append(normalized)
    return tuple(result)  # type: ignore[return-value]


def _distance(first: Sequence[float], second: Sequence[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(first, second, strict=True)))


def _representatives(
    plans: list[dict[str, Any]],
    maximum: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []

    def add(candidate: dict[str, Any]) -> None:
        if (
            len(selected) < maximum
            and candidate["semantic_class_id"]
            not in {item["semantic_class_id"] for item in selected}
        ):
            selected.append(candidate)

    exact = min(
        plans,
        key=lambda item: (
            item["semantic_deviation"],
            item["latency_ms"],
            item["resource_cost_units"],
            item["plan_id"],
        ),
    )
    add(exact)
    add(
        min(
            plans,
            key=lambda item: (
                item["latency_ms"],
                item["resource_cost_units"],
                item["semantic_deviation"],
                item["plan_id"],
            ),
        )
    )
    add(
        min(
            plans,
            key=lambda item: (
                item["resource_cost_units"],
                item["latency_ms"],
                item["semantic_deviation"],
                item["plan_id"],
            ),
        )
    )
    bounds = {
        field: (
            min(float(item[field]) for item in plans),
            max(float(item[field]) for item in plans),
        )
        for field in ("semantic_deviation", "latency_ms", "resource_cost_units")
    }
    vectors = {
        item["semantic_class_id"]: _normalized_vector(item, bounds)
        for item in plans
    }
    while len(selected) < maximum:
        remaining = [
            item
            for item in plans
            if item["semantic_class_id"]
            not in {chosen["semantic_class_id"] for chosen in selected}
        ]
        if not remaining:
            break
        candidate = min(
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
        add(candidate)
    return selected


def build_m15_semantic_frontier(
    solution_space: M15SemanticSolutionSpace,
    plan_costs: Sequence[Mapping[str, Any]],
) -> M15SemanticFrontier:
    space = solution_space.to_dict()
    if space.get("schema_version") != SEMANTIC_SOLUTION_SPACE_SCHEMA_VERSION:
        raise M15SemanticFrontierError("solution space schema_version is unsupported")
    if not plan_costs:
        raise M15SemanticFrontierError("plan_costs must be nonempty")
    interpretations = {
        item["interpretation_id"]: item
        for item in space["raw_interpretations"]
    }
    class_by_interpretation = {
        interpretation_id: semantic_class
        for semantic_class in space["semantic_equivalence_classes"]
        for interpretation_id in semantic_class["member_interpretation_ids"]
    }
    normalized_costs: list[dict[str, Any]] = []
    cost_ids: list[str] = []
    for index, value in enumerate(plan_costs):
        raw = _strict_object(
            value,
            name=f"plan_costs[{index}]",
            fields={
                "plan_id",
                "interpretation_id",
                "latency_ms",
                "resource_cost_units",
                "evidence_id",
                "success",
            },
        )
        plan_id = _safe_id(raw["plan_id"], name="plan_id")
        interpretation_id = _safe_id(
            raw["interpretation_id"], name="interpretation_id"
        )
        if interpretation_id not in interpretations:
            raise M15SemanticFrontierError(
                f"plan '{plan_id}' references an unknown interpretation"
            )
        cost_id = f"{interpretation_id}:{plan_id}"
        cost_ids.append(cost_id)
        if raw["success"] is not True:
            continue
        semantic_class = class_by_interpretation[interpretation_id]
        normalized_costs.append(
            {
                "plan_id": plan_id,
                "interpretation_id": interpretation_id,
                "semantic_class_id": semantic_class["semantic_class_id"],
                "semantic_deviation": float(
                    semantic_class["semantic_deviation"]
                ),
                "latency_ms": _finite_nonnegative(
                    raw["latency_ms"], name="latency_ms"
                ),
                "resource_cost_units": _finite_nonnegative(
                    raw["resource_cost_units"], name="resource_cost_units"
                ),
                "evidence_id": _safe_id(raw["evidence_id"], name="evidence_id"),
                "success": True,
            }
        )
    if len(cost_ids) != len(set(cost_ids)):
        raise M15SemanticFrontierError(
            "plan IDs must be unique within each interpretation"
        )

    reduced: list[dict[str, Any]] = []
    for semantic_class in space["semantic_equivalence_classes"]:
        eligible = [
            item
            for item in normalized_costs
            if item["semantic_class_id"] == semantic_class["semantic_class_id"]
        ]
        if not eligible:
            raise M15SemanticFrontierError(
                "every semantic equivalence class requires a successful physical plan"
            )
        reduced.append(
            min(
                eligible,
                key=lambda item: (
                    item["latency_ms"],
                    item["resource_cost_units"],
                    item["plan_id"],
                ),
            )
        )
    reduced.sort(key=lambda item: item["semantic_class_id"])

    pareto = [
        candidate
        for candidate in reduced
        if not any(
            _dominates(other, candidate)
            for other in reduced
            if other["semantic_class_id"] != candidate["semantic_class_id"]
        )
    ]
    pareto.sort(key=lambda item: item["semantic_class_id"])
    policy = space["frontier_policy"]
    latency_epsilon = float(policy["minimum_latency_gain_ratio"])
    resource_epsilon = float(policy["minimum_resource_gain_ratio"])
    epsilon_frontier: list[dict[str, Any]] = []
    epsilon_removed: list[dict[str, Any]] = []
    for candidate in pareto:
        witnesses: list[dict[str, Any]] = []
        for reference in pareto:
            if reference["semantic_deviation"] >= candidate["semantic_deviation"]:
                continue
            latency_gain = _relative_gain(
                float(reference["latency_ms"]), float(candidate["latency_ms"])
            )
            resource_gain = _relative_gain(
                float(reference["resource_cost_units"]),
                float(candidate["resource_cost_units"]),
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
                        witnesses, key=lambda item: item["semantic_class_id"]
                    ),
                }
            )
        else:
            epsilon_frontier.append(candidate)
    representatives = _representatives(
        epsilon_frontier, int(policy["max_representatives"])
    )
    representative_ids = {
        item["semantic_class_id"] for item in representatives
    }
    representative_records = [
        {
            **item,
            "selection_rank": rank,
        }
        for rank, item in enumerate(representatives, 1)
    ]
    body = {
        "schema_version": SEMANTIC_FRONTIER_SCHEMA_VERSION,
        "solution_space_sha256": solution_space.solution_space_hash,
        "catalog_sha256": space["catalog_sha256"],
        "family_compatibility_sha256": space[
            "family_compatibility_sha256"
        ],
        "frontier_policy": policy,
        "counts": {
            "raw_interpretations": space["raw_interpretation_count"],
            "semantic_equivalence_classes": space["semantic_class_count"],
            "successful_physical_plan_costs": len(normalized_costs),
            "physical_representatives": len(reduced),
            "pareto_plans": len(pareto),
            "epsilon_frontier_plans": len(epsilon_frontier),
            "returned_representatives": len(representative_records),
        },
        "physical_representatives": reduced,
        "pareto_plans": pareto,
        "epsilon_removed": epsilon_removed,
        "epsilon_frontier_plans": epsilon_frontier,
        "returned_representatives": representative_records,
        "not_returned_semantic_class_ids": sorted(
            item["semantic_class_id"]
            for item in epsilon_frontier
            if item["semantic_class_id"] not in representative_ids
        ),
        "claim_boundary": {
            "artifact_class": "development_semantic_frontier_mechanism",
            "cost_inputs_are_external_measurements": True,
            "semantic_quality_validated": False,
            "performance_superiority_validated": False,
            "backend_calls_made_by_frontier": 0,
            "llm_calls_made": 0,
            "ontology_calls_made": 0,
            "paper_result": False,
        },
        "automatic_retries": 0,
        "paper_result": False,
    }
    return M15SemanticFrontier(
        {**body, "frontier_sha256": content_hash(body)}
    )


def write_m15_semantic_solution_space(
    solution_space: M15SemanticSolutionSpace,
    output: str | Path,
) -> Path:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"semantic solution space exists: {destination}")
    destination.write_text(
        json.dumps(
            solution_space.to_dict(),
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
    parser = argparse.ArgumentParser(
        description="Build one unexecuted M15 bounded semantic solution space."
    )
    parser.add_argument("--query-spec", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    query_path = Path(arguments.query_spec)
    if query_path.is_symlink() or not query_path.is_file():
        raise M15SemanticFrontierError(
            "query spec must be a regular non-symbolic-link file"
        )
    query_spec = json.loads(query_path.read_text(encoding="utf-8"))
    if not isinstance(query_spec, Mapping):
        raise M15SemanticFrontierError("query spec must be an object")
    solution_space = build_m15_semantic_solution_space(
        query_spec,
        load_m15_semantic_relaxation_catalog(arguments.catalog),
    )
    write_m15_semantic_solution_space(solution_space, arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
