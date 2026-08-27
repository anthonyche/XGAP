"""M13-E1 deterministic interpretation normalization and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
import argparse
import json
import math
from pathlib import Path
import statistics
from typing import Any, Iterable, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.llm.parser import parse_path_pattern_query, parse_planner_response
from xgap.llm.schemas import PlannerRequest, PlannerResponse


STAGE_AWARE_FAILURE_TAXONOMY = (
    "reference_not_in_catalog",
    "reference_not_in_local_catalog",
    "reference_not_retrieved",
    "reference_not_prompt_visible",
    "malformed_output",
    "generated_semantic_miss",
    "type_check_failure",
    "grounding_failure",
    "semantic_bound_rejection",
    "ranking_failure",
    "equivalence_failure",
)


@dataclass(frozen=True)
class CanonicalizationProfile:
    profile_id: str
    default_selector: str = "ALL"
    default_restrictor: str | None = None
    derive_simple_node_inequalities: bool = True


FIXED_PATH_PATTERN_PROFILE = CanonicalizationProfile(
    profile_id="xgap-fixed-path-pattern-v1",
    default_selector="ALL",
    default_restrictor="SIMPLE",
    derive_simple_node_inequalities=True,
)


def parse_normalized_planner_response(
    raw: Mapping[str, Any],
    request: PlannerRequest,
    *,
    profile: CanonicalizationProfile = FIXED_PATH_PATTERN_PROFILE,
) -> PlannerResponse:
    """Apply the v2 semantic contract before the existing typed parser."""

    normalized = _deep_mapping_copy(raw)
    candidates = normalized.get("candidates")
    if not isinstance(candidates, list):
        return parse_planner_response(normalized, request)
    for index, candidate in enumerate(candidates, start=1):
        candidate_map = _mapping(candidate, f"candidate[{index}]")
        pattern = _mapping(candidate_map.get("pattern_query"), "pattern_query")
        validate_generated_condition(pattern.get("condition"))
        candidate_map["pattern_query"] = normalize_interpretation(pattern, profile=profile)
    return parse_planner_response(normalized, request)


def validate_generated_condition(condition: object) -> None:
    """Validate the typed v2 condition grammar before canonical fields are added."""

    if condition is None:
        return
    value = _mapping(condition, "condition")
    kind = str(value.get("kind", "")).casefold()
    leaf_kinds = {
        "label_equals",
        "property_equals",
        "property_not_equals",
        "property_lt",
        "property_lte",
        "property_gt",
        "property_gte",
        "length_equals",
    }
    if kind == "node_not_equals":
        raise ValueError("node_not_equals is deterministic under SIMPLE and must not be generated.")
    if kind in leaf_kinds:
        parse_path_pattern_query(
            {
                "source": {"label": None, "properties": {}},
                "expr": {
                    "kind": "rel",
                    "edge": {"label": None, "direction": "OUT", "properties": {}},
                },
                "target": {"label": None, "properties": {}},
                "selector": {"kind": "ALL", "k": None},
                "restrictor": "TRAIL",
                "condition": value,
            }
        )
        return
    if kind in ("and", "or"):
        children = value.get("conditions")
        if not isinstance(children, list) or len(children) < 2:
            raise ValueError(f"{kind}.conditions must contain at least two typed conditions.")
        for child in children:
            validate_generated_condition(child)
        return
    if kind == "not":
        validate_generated_condition(value.get("condition"))
        return
    raise ValueError(f"Unsupported generated condition kind {kind!r}.")


def normalize_interpretation(
    value: Mapping[str, Any],
    *,
    profile: CanonicalizationProfile = FIXED_PATH_PATTERN_PROFILE,
) -> dict[str, Any]:
    """Normalize representation-only choices without weakening semantics."""

    pattern = _deep_mapping_copy(value)
    selector = pattern.get("selector")
    if selector is None:
        pattern["selector"] = {"kind": profile.default_selector, "k": None}
    else:
        selector_map = _mapping(selector, "selector")
        pattern["selector"] = {
            "kind": str(selector_map.get("kind", profile.default_selector)).upper(),
            "k": selector_map.get("k"),
        }
    restrictor = pattern.get("restrictor")
    if restrictor is None:
        if profile.default_restrictor is None:
            raise ValueError("Interpretation has no restrictor and profile defines no default.")
        pattern["restrictor"] = profile.default_restrictor
    else:
        pattern["restrictor"] = str(restrictor).upper()
    pattern.setdefault("path_var", None)
    pattern.setdefault("max_depth", None)

    node_count = _fixed_path_node_count(_mapping(pattern.get("expr"), "expr"))
    canonical_conditions = (
        _simple_node_inequalities(node_count)
        if profile.derive_simple_node_inequalities
        and pattern["restrictor"] == "SIMPLE"
        and node_count is not None
        else ()
    )
    explicit = _remove_canonical_conditions(pattern.get("condition"), canonical_conditions)
    pattern["condition"] = _combine_conditions((*explicit, *canonical_conditions))
    pattern = _normalize_condition_order(pattern)

    def scrub(item: object) -> Any:
        if isinstance(item, Mapping):
            return {
                str(key): scrub(child)
                for key, child in sorted(item.items())
                if str(key) not in {"var", "path_var"}
            }
        if isinstance(item, list):
            return [scrub(child) for child in item]
        return item

    normalized = scrub(pattern)
    parse_path_pattern_query(normalized)
    return normalized


def normalized_interpretation_match(
    generated: Mapping[str, Any],
    reference: Mapping[str, Any],
    *,
    profile: CanonicalizationProfile = FIXED_PATH_PATTERN_PROFILE,
) -> bool:
    return content_hash(normalize_interpretation(generated, profile=profile)) == content_hash(
        normalize_interpretation(reference, profile=profile)
    )


def component_match_report(
    generated: Mapping[str, Any],
    reference: Mapping[str, Any],
    *,
    profile: CanonicalizationProfile = FIXED_PATH_PATTERN_PROFILE,
) -> dict[str, Any]:
    generated_normalized = normalize_interpretation(generated, profile=profile)
    reference_normalized = normalize_interpretation(reference, profile=profile)
    generated_components = interpretation_components(generated_normalized, profile=profile)
    reference_components = interpretation_components(reference_normalized, profile=profile)
    keys = (
        "entity_grounding",
        "relation_sequence",
        "relation_direction",
        "path_structure",
        "type_constraints",
        "explicit_constraint",
        "focus",
        "selector",
        "restrictor",
        "canonical_condition",
    )
    matches = {key: generated_components[key] == reference_components[key] for key in keys}
    matches["canonical_field"] = all(
        matches[key] for key in ("selector", "restrictor", "canonical_condition")
    )
    matches["full_normalized_interpretation"] = (
        content_hash(generated_normalized) == content_hash(reference_normalized)
    )
    return {
        "schema_version": "m13e1-component-match-v1",
        "matches": matches,
        "generated": generated_components,
        "reference": reference_components,
        "generated_normalized_hash": content_hash(generated_normalized),
        "reference_normalized_hash": content_hash(reference_normalized),
    }


def interpretation_components(
    normalized: Mapping[str, Any],
    *,
    profile: CanonicalizationProfile = FIXED_PATH_PATTERN_PROFILE,
) -> dict[str, Any]:
    pattern = _deep_mapping_copy(normalized)
    source = _mapping(pattern.get("source"), "source")
    target = _mapping(pattern.get("target"), "target")
    expr = _mapping(pattern.get("expr"), "expr")
    path = _path_components(expr)
    node_count = _fixed_path_node_count(expr)
    canonical = (
        _simple_node_inequalities(node_count)
        if profile.derive_simple_node_inequalities
        and pattern.get("restrictor") == "SIMPLE"
        and node_count is not None
        else ()
    )
    explicit = _remove_canonical_conditions(pattern.get("condition"), canonical)
    return {
        "entity_grounding": {
            "source": _entity_ids(source),
            "target": _entity_ids(target),
        },
        "relation_sequence": path["relations"],
        "relation_direction": path["directions"],
        "path_structure": path["structure"],
        "type_constraints": {
            "source": source.get("label"),
            "target": target.get("label"),
        },
        "explicit_constraint": [_normalize_condition(item) for item in explicit],
        "focus": _focus(source, target),
        "selector": pattern.get("selector"),
        "restrictor": pattern.get("restrictor"),
        "canonical_condition": [_normalize_condition(item) for item in canonical],
    }


def classify_first_failure(
    *,
    reachability_row: Mapping[str, Any] | None,
    malformed_output: bool = False,
    generated_candidates: int = 0,
    type_check_ok: bool = True,
    grounding_ok: bool = True,
    semantic_admissible: bool = True,
    selected_candidate: bool = True,
    equivalent: bool = True,
) -> str | None:
    if reachability_row is not None:
        stage = reachability_row.get("first_unreachable_stage")
        if stage is not None:
            stage_name = str(stage)
            if stage_name not in STAGE_AWARE_FAILURE_TAXONOMY:
                raise ValueError(f"Unknown reachability failure stage {stage_name!r}.")
            return stage_name
    checks = (
        (malformed_output, "malformed_output"),
        (generated_candidates == 0, "generated_semantic_miss"),
        (not type_check_ok, "type_check_failure"),
        (not grounding_ok, "grounding_failure"),
        (not semantic_admissible, "semantic_bound_rejection"),
        (not selected_candidate, "ranking_failure"),
        (not equivalent, "equivalence_failure"),
    )
    return next((name for failed, name in checks if failed), None)


def semantic_deviation_distribution(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    finite: list[float] = []
    infinite = 0
    by_question: dict[str, set[float]] = {}
    for row in rows:
        measurement = row.get("measurement")
        raw = row.get("c_sem", row.get("semantic_deviation"))
        if raw is None and isinstance(measurement, Mapping):
            raw = measurement.get("finite_value", measurement.get("value"))
        if raw is None:
            infinite += 1
            continue
        value = float(raw)
        if not math.isfinite(value):
            infinite += 1
            continue
        finite.append(value)
        by_question.setdefault(str(row.get("question_id", "")), set()).add(value)
    ordered = sorted(finite)
    thresholds = (0.0, 0.1, 0.25, 0.5, 0.75, 1.0)
    histogram_ranges = ((0.0, 0.0), (0.0, 0.1), (0.1, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0))
    histogram: dict[str, int] = {}
    for lower, upper in histogram_ranges:
        label = "0" if lower == upper == 0 else f"({lower},{upper}]"
        histogram[label] = sum(
            value == 0.0 if lower == upper else lower < value <= upper for value in ordered
        )
    return {
        "schema_version": "m13e1-c-sem-distribution-v1",
        "candidate_count": len(rows),
        "finite_count": len(ordered),
        "infinite_count": infinite,
        "minimum": min(ordered) if ordered else None,
        "mean": statistics.fmean(ordered) if ordered else None,
        "median": statistics.median(ordered) if ordered else None,
        "p90": _percentile(ordered, 0.9),
        "maximum": max(ordered) if ordered else None,
        "histogram": histogram,
        "fraction": {
            f"le_{threshold}": (
                sum(value <= threshold for value in ordered) / len(ordered) if ordered else None
            )
            for threshold in thresholds
        },
        "per_query_distinct_values": {
            "minimum": min((len(values) for values in by_question.values()), default=None),
            "mean": (
                statistics.fmean(len(values) for values in by_question.values())
                if by_question
                else None
            ),
            "maximum": max((len(values) for values in by_question.values()), default=None),
        },
    }


def run_posthoc_contract_audit(
    *,
    source_run: str | Path,
    pilot_root: str | Path,
    output_root: str | Path,
    reachability_path: str | Path | None = None,
) -> dict[str, Any]:
    """Re-evaluate frozen responses without modifying their source directory."""

    source = Path(source_run).resolve()
    output = Path(output_root).resolve()
    if source == output or source in output.parents:
        raise ValueError("Post-hoc output must be separate from the frozen source run.")
    required = ("metrics.json", "validated_candidates.jsonl", "semantic_scores.jsonl")
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Frozen M13-D run is missing required files: {missing}")
    references = {
        str(item["question_id"]): item
        for item in _read_jsonl(Path(pilot_root) / "reference_interpretations.jsonl")
    }
    candidates = _read_jsonl(source / "validated_candidates.jsonl")
    original_failures = {
        str(item["question_id"]): item for item in _read_jsonl(source / "failures.jsonl")
    }
    reachability = (
        {
            str(item["question_id"]): item
            for item in _read_jsonl(Path(reachability_path))
        }
        if reachability_path is not None
        else {}
    )
    component_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        question_id = str(candidate["question_id"])
        if question_id not in references:
            continue
        report = component_match_report(
            _mapping(candidate["pattern_query"], "pattern_query"),
            _mapping(references[question_id]["pattern_query"], "reference pattern"),
        )
        component_rows.append(
            {
                "question_id": question_id,
                "candidate_id": candidate.get("candidate_id"),
                **report,
            }
        )
    match_keys = tuple(component_rows[0]["matches"]) if component_rows else ()
    component_rates = {
        key: sum(bool(row["matches"][key]) for row in component_rows) / len(component_rows)
        for key in match_keys
    }
    candidates_by_question: dict[str, list[Mapping[str, Any]]] = {}
    components_by_question: dict[str, list[Mapping[str, Any]]] = {}
    for candidate in candidates:
        candidates_by_question.setdefault(str(candidate["question_id"]), []).append(candidate)
    for component in component_rows:
        components_by_question.setdefault(str(component["question_id"]), []).append(component)
    corrected_failures: list[dict[str, Any]] = []
    for question_id in references:
        question_candidates = candidates_by_question.get(question_id, [])
        question_components = components_by_question.get(question_id, [])
        old = original_failures.get(question_id, {})
        old_category = str(old.get("category", ""))
        category = classify_first_failure(
            reachability_row=reachability.get(question_id),
            malformed_output=old_category == "malformed_output",
            generated_candidates=len(question_candidates),
            type_check_ok=old_category != "type_check_failure",
            grounding_ok=old_category
            not in {"entity_grounding_failure", "relation_grounding_failure"},
            semantic_admissible=any(
                bool(item.get("semantic_admissible")) for item in question_candidates
            ),
            selected_candidate=bool(question_candidates),
            equivalent=any(
                bool(item["matches"]["full_normalized_interpretation"])
                for item in question_components
            ),
        )
        if category is not None:
            corrected_failures.append(
                {
                    "schema_version": "m13e1-stage-aware-failure-v1",
                    "question_id": question_id,
                    "category": category,
                    "old_m13d_category": old.get("category"),
                }
            )
    failure_counts = {
        name: sum(item["category"] == name for item in corrected_failures)
        for name in STAGE_AWARE_FAILURE_TAXONOMY
    }
    old_metrics = json.loads((source / "metrics.json").read_text(encoding="utf-8"))
    result = {
        "schema_version": "m13e1-m13d-posthoc-contract-audit-v1",
        "source_run": str(source),
        "source_run_immutable": True,
        "diagnostic_not_replacement_result": True,
        "old_frozen_candidate_recall": _mapping(
            old_metrics.get("candidate", {}), "candidate metrics"
        ).get("candidate_recall"),
        "new_normalized_candidate_recall": _query_recall(component_rows),
        "component_match_rates": component_rates,
        "stage_aware_failure_taxonomy": failure_counts,
        "c_sem": semantic_deviation_distribution(
            _read_jsonl(source / "semantic_scores.jsonl")
        ),
    }
    output.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output / "component_match.jsonl", component_rows)
    _write_jsonl(output / "failures.jsonl", corrected_failures)
    (output / "metrics.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def _fixed_path_node_count(expr: Mapping[str, Any]) -> int | None:
    kind = str(expr.get("kind", "")).casefold()
    if kind == "rel":
        return 2
    if kind == "seq":
        left = _fixed_path_node_count(_mapping(expr.get("left"), "left"))
        right = _fixed_path_node_count(_mapping(expr.get("right"), "right"))
        if left is None or right is None:
            return None
        return left + right - 1
    return None


def _simple_node_inequalities(node_count: int) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "kind": "node_not_equals",
            "left": {"kind": "node", "position": left},
            "right": {"kind": "node", "position": right},
        }
        for left in range(1, node_count + 1)
        for right in range(left + 1, node_count + 1)
    )


def _remove_canonical_conditions(
    condition: object, canonical: tuple[dict[str, Any], ...]
) -> tuple[dict[str, Any], ...]:
    values = _top_level_conjuncts(condition)
    canonical_hashes = {content_hash(_normalize_condition(item)) for item in canonical}
    return tuple(
        item
        for item in values
        if content_hash(_normalize_condition(item)) not in canonical_hashes
    )


def _top_level_conjuncts(condition: object) -> tuple[dict[str, Any], ...]:
    if condition is None:
        return ()
    value = _deep_mapping_copy(_mapping(condition, "condition"))
    if str(value.get("kind", "")).casefold() != "and":
        return (value,)
    result: list[dict[str, Any]] = []
    for child in value.get("conditions", ()):
        result.extend(_top_level_conjuncts(child))
    return tuple(result)


def _combine_conditions(conditions: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    values = sorted(
        (_normalize_condition(item) for item in conditions), key=content_hash
    )
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return {"kind": "and", "conditions": values}


def _normalize_condition(condition: Mapping[str, Any]) -> dict[str, Any]:
    value = _deep_mapping_copy(condition)
    kind = str(value.get("kind", "")).casefold()
    value["kind"] = kind
    if kind in ("and", "or"):
        children = [_normalize_condition(_mapping(item, "condition child")) for item in value.get("conditions", ())]
        value["conditions"] = sorted(children, key=content_hash)
    elif kind == "not":
        value["condition"] = _normalize_condition(_mapping(value.get("condition"), "not.condition"))
    elif kind == "node_not_equals":
        left = _mapping(value.get("left"), "left")
        right = _mapping(value.get("right"), "right")
        if _ref_sort_key(left) > _ref_sort_key(right):
            value["left"], value["right"] = dict(right), dict(left)
    return {key: value[key] for key in sorted(value)}


def _normalize_condition_order(pattern: dict[str, Any]) -> dict[str, Any]:
    condition = pattern.get("condition")
    if condition is not None:
        pattern["condition"] = _normalize_condition(_mapping(condition, "condition"))
    return pattern


def _path_components(expr: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(expr.get("kind", "")).casefold()
    if kind == "rel":
        edge = _mapping(expr.get("edge"), "edge")
        return {
            "relations": [edge.get("label")],
            "directions": [str(edge.get("direction", "OUT")).upper()],
            "structure": "rel",
        }
    if kind in ("seq", "alt"):
        left = _path_components(_mapping(expr.get("left"), "left"))
        right = _path_components(_mapping(expr.get("right"), "right"))
        return {
            "relations": [*left["relations"], *right["relations"]],
            "directions": [*left["directions"], *right["directions"]],
            "structure": {"kind": kind, "left": left["structure"], "right": right["structure"]},
        }
    if kind in ("plus", "star", "optional", "bounded"):
        child = _path_components(_mapping(expr.get("child"), "child"))
        structure: dict[str, Any] = {"kind": kind, "child": child["structure"]}
        if kind == "bounded":
            structure.update(
                {"min_repeats": expr.get("min_repeats"), "max_repeats": expr.get("max_repeats")}
            )
        return {**child, "structure": structure}
    raise ValueError(f"Unsupported path expression kind {kind!r}.")


def _entity_ids(node: Mapping[str, Any]) -> list[str]:
    properties = _mapping(node.get("properties", {}), "properties")
    value = properties.get("type.object.id")
    return [] if value is None else [str(value)]


def _focus(source: Mapping[str, Any], target: Mapping[str, Any]) -> str:
    source_anchor = bool(_entity_ids(source))
    target_anchor = bool(_entity_ids(target))
    if source_anchor != target_anchor:
        return "target" if source_anchor else "source"
    return "underdetermined"


def _ref_sort_key(value: Mapping[str, Any]) -> tuple[str, str]:
    return str(value.get("kind", "")), str(value.get("position", value.get("index", "")))


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    index = max(0, math.ceil(len(values) * quantile) - 1)
    return values[index]


def _query_recall(rows: Sequence[Mapping[str, Any]]) -> float | None:
    if not rows:
        return None
    by_question: dict[str, bool] = {}
    for row in rows:
        question_id = str(row["question_id"])
        by_question[question_id] = by_question.get(question_id, False) or bool(
            row["matches"]["full_normalized_interpretation"]
        )
    return sum(by_question.values()) / len(by_question)


def _deep_mapping_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(dict(value)))


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
    parser.add_argument("command", choices=("posthoc", "c-sem"))
    parser.add_argument("--source-run", required=True)
    parser.add_argument("--pilot-root", default="datasets/grailqa_pilot_v1")
    parser.add_argument("--reachability")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    if args.command == "posthoc":
        if not args.output:
            parser.error("posthoc requires --output")
        result = run_posthoc_contract_audit(
            source_run=args.source_run,
            pilot_root=args.pilot_root,
            output_root=args.output,
            reachability_path=args.reachability,
        )
    else:
        rows = _read_jsonl(Path(args.source_run) / "semantic_scores.jsonl")
        result = semantic_deviation_distribution(rows)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
