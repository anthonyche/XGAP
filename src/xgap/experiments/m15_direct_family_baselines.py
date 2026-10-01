"""Results-blind post-selection physical baselines for an audited F2C10D run."""

from __future__ import annotations

import argparse
import copy
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_family_pilot_evidence import (
    DIRECT_FAMILY_PILOT_AUDIT_SCHEMA_VERSION,
    audit_m15_direct_family_pilot,
)
from xgap.experiments.m15_direct_family_prediction import (
    build_m15_direct_family_prediction_suite,
    build_m15_direct_training_memory_view,
)
from xgap.experiments.m15_direct_semantic_workload import (
    load_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_parameterized_workload import (
    load_m15_parameterized_workload_bundle,
)


DIRECT_FAMILY_BASELINE_POLICY_SCHEMA_VERSION = (
    "m15-f2c11-physical-baseline-policy-v1"
)
DIRECT_FAMILY_BASELINE_ANALYSIS_SCHEMA_VERSION = (
    "m15-f2c11-physical-baseline-analysis-v1"
)
_METHOD_IDS = (
    "family_memory_primary",
    "family_global_no_instance_features",
    "fixed_parallel_hash",
    "fixed_risk_first_bind",
    "observed_oracle_upper_bound",
)
_STRATEGIES = ("parallel_hash_join", "risk_first_bind_join")


def _json_object(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise ValueError("baseline input must be a regular non-symbolic-link file")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("baseline input must contain a JSON object")
    return dict(payload)


def _policy(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    policy = _json_object(value)
    if set(policy) != {
        "schema_version",
        "policy_id",
        "source_experiment",
        "methods",
        "aggregation",
        "physical_selection_order",
        "evaluation_oracles",
        "metrics",
        "input_boundary",
        "analysis_backend_calls",
        "confirmatory_statistics",
        "development_candidate_baselines_only",
        "paper_result",
    }:
        raise ValueError("baseline policy fields changed")
    if policy["schema_version"] != DIRECT_FAMILY_BASELINE_POLICY_SCHEMA_VERSION:
        raise ValueError("baseline policy schema is unsupported")
    expected_methods = [
        {
            "method_id": "family_memory_primary",
            "role": "primary_method",
            "selection_source": "sealed_family_memory_predictions",
        },
        {
            "method_id": "family_global_no_instance_features",
            "role": "ablation",
            "selection_source": "training_strategy_global_medians",
        },
        {
            "method_id": "fixed_parallel_hash",
            "role": "static_baseline",
            "selection_source": "fixed_parallel_hash_join",
        },
        {
            "method_id": "fixed_risk_first_bind",
            "role": "static_baseline",
            "selection_source": "fixed_risk_first_bind_join",
        },
        {
            "method_id": "observed_oracle_upper_bound",
            "role": "evaluation_upper_bound",
            "selection_source": "postselection_shadow_medians",
        },
    ]
    if policy["methods"] != expected_methods:
        raise ValueError("baseline method set or order changed")
    expected_boundary = {
        "requires_successful_f2c10d_read_only_audit": True,
        "admission_audit_may_validate_full_run": True,
        "training_measurements_allowed": True,
        "postselection_shadow_measurements_allowed_for_evaluation_only": True,
        "online_selected_results_allowed_for_selection_or_metrics": False,
        "answer_row_values_allowed_for_selection_or_metrics": False,
        "current_query_observation_operations": [],
    }
    if policy["input_boundary"] != expected_boundary:
        raise ValueError("baseline input boundary changed")
    expected_oracles = {
        "physical_winner": ["latency_ms", "total_bytes_moved", "plan_id"],
        "latency_regret_reference": [
            "latency_ms",
            "total_bytes_moved",
            "plan_id",
        ],
        "bytes_regret_reference": [
            "total_bytes_moved",
            "latency_ms",
            "plan_id",
        ],
    }
    if (
        policy["policy_id"]
        != "m15-f2c11-results-blind-development-baselines-v1"
        or policy["source_experiment"] != "m15-f2c10d-direct-family-pilot"
        or policy["aggregation"]
        != {
            "per_plan": "median_over_four_repetitions",
            "family_global": "median_of_training_plan_medians_per_strategy",
        }
        or policy["physical_selection_order"]
        != ["latency_ms", "total_bytes_moved", "plan_id"]
        or policy["evaluation_oracles"] != expected_oracles
        or policy["metrics"]
        != [
            "physical_winner_accuracy",
            "latency_regret_ms",
            "bytes_regret",
            "strategy_selection_counts",
        ]
        or policy["analysis_backend_calls"] != 0
        or policy["confirmatory_statistics"] is not False
        or policy["development_candidate_baselines_only"] is not True
        or policy["paper_result"] is not False
    ):
        raise ValueError("baseline claim or execution boundary changed")
    return policy


def _accepted_audit(
    value: Mapping[str, Any] | str | Path, *, run_root: Path
) -> dict[str, Any]:
    audit = _json_object(value)
    if (
        audit.get("schema_version") != DIRECT_FAMILY_PILOT_AUDIT_SCHEMA_VERSION
        or audit.get("success") is not True
        or audit.get("failed_check_ids") != []
        or audit.get("run_tree_mutated") is not False
        or Path(str(audit.get("run_root"))).resolve() != run_root
    ):
        raise ValueError("baseline analysis requires an accepted F2C10D audit")
    current = audit_m15_direct_family_pilot(
        run_root=run_root,
        expected_commit=str(audit["expected_commit"]),
    ).to_dict()
    if (
        current["success"] is not True
        or current["failed_check_ids"] != []
        or current["run_tree_mutated"] is not False
        or current["check_count"] != audit.get("check_count")
        or current != audit
    ):
        raise ValueError(
            "F2C10D run no longer passes an independent read-only audit"
        )
    return audit


def _training_strategy_global_medians(
    observations: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, float]]:
    plan_medians: dict[str, list[tuple[float, float]]] = {
        strategy: [] for strategy in _STRATEGIES
    }
    for observation in observations:
        strategy = str(observation.get("physical_strategy"))
        repetitions = observation.get("repetitions")
        if (
            strategy not in plan_medians
            or not isinstance(repetitions, list)
            or len(repetitions) != 4
        ):
            raise ValueError("training observations do not match the frozen design")
        if any(
            item.get("execution_success") is not True
            or item.get("exact_answer") is not True
            or not math.isfinite(float(item.get("elapsed_ms", math.nan)))
            or float(item["elapsed_ms"]) < 0
            or not math.isfinite(
                float(item.get("total_bytes_moved", math.nan))
            )
            or float(item["total_bytes_moved"]) < 0
            for item in repetitions
        ):
            raise ValueError(
                "baseline training observation is not successful and exact"
            )
        plan_medians[strategy].append(
            (
                float(statistics.median(item["elapsed_ms"] for item in repetitions)),
                float(
                    statistics.median(
                        item["total_bytes_moved"] for item in repetitions
                    )
                ),
            )
        )
    if any(len(values) != 18 for values in plan_medians.values()):
        raise ValueError("training observations do not cover 18 plans per strategy")
    return {
        strategy: {
            "latency_ms": float(statistics.median(item[0] for item in values)),
            "total_bytes_moved": float(
                statistics.median(item[1] for item in values)
            ),
        }
        for strategy, values in plan_medians.items()
    }


def _median_observations(
    shadow_runs: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for run in shadow_runs:
        if (
            run.get("success") is not True
            or run.get("exact_answer") is not True
            or not math.isfinite(float(run.get("elapsed_ms", math.nan)))
            or float(run["elapsed_ms"]) < 0
            or not math.isfinite(
                float(run.get("total_bytes_moved", math.nan))
            )
            or float(run["total_bytes_moved"]) < 0
        ):
            raise ValueError("shadow run is not successful and exact")
        grouped.setdefault(str(run["plan_id"]), []).append(run)
    if len(grouped) != 20 or any(len(items) != 4 for items in grouped.values()):
        raise ValueError("shadow results do not cover 20 plans four times")
    return {
        plan_id: {
            "latency_ms": float(statistics.median(item["elapsed_ms"] for item in runs)),
            "total_bytes_moved": float(
                statistics.median(item["total_bytes_moved"] for item in runs)
            ),
        }
        for plan_id, runs in grouped.items()
    }


def _summary(values: Sequence[float]) -> dict[str, float]:
    return {
        "mean": sum(values) / len(values),
        "median": float(statistics.median(values)),
        "minimum": min(values),
        "maximum": max(values),
    }


def _choose(
    *,
    candidates: Mapping[str, Mapping[str, Any]],
    costs: Mapping[str, Mapping[str, Any]],
    order: Sequence[str],
) -> str:
    if set(candidates) != set(_STRATEGIES) or set(costs) != set(_STRATEGIES):
        raise ValueError("physical strategy coverage changed")

    def key(strategy: str) -> tuple[float | str, ...]:
        values: list[float | str] = []
        for field in order:
            if field == "plan_id":
                values.append(str(candidates[strategy]["plan_id"]))
            else:
                value = float(costs[strategy][field])
                if not math.isfinite(value) or value < 0:
                    raise ValueError("baseline cost is not finite and nonnegative")
                values.append(value)
        return tuple(values)

    return min(_STRATEGIES, key=key)


def analyze_m15_direct_family_baselines(
    *,
    run_root: str | Path,
    audit: Mapping[str, Any] | str | Path,
    policy: Mapping[str, Any] | str | Path,
) -> dict[str, Any]:
    """Compare predeclared physical policies using no new backend calls."""

    selected = Path(run_root)
    if selected.is_symlink():
        raise ValueError("run_root must not be a symbolic link")
    root = selected.resolve()
    if not root.is_dir():
        raise ValueError("run_root must be a real directory")
    accepted = _accepted_audit(audit, run_root=root)
    selected_policy = _policy(policy)
    live = root / "native-service-run/direct-family-pilot-run"
    base = load_m15_parameterized_workload_bundle(
        root / "direct-family-base-workload-bundle"
    )
    direct = load_m15_direct_semantic_workload_bundle(
        root / "direct-semantic-workload-bundle",
        base_bundle=root / "direct-family-base-workload-bundle",
        catalog=root / "semantic_catalog.json",
        mapping=root / "predicate_mapping.json",
    )
    training = _json_object(live / "training/training_observations.json")
    strategy_global_medians = _training_strategy_global_medians(
        training["observations"]
    )
    manifest = _json_object(live / "run_manifest.json")
    memory = build_m15_direct_training_memory_view(
        workload=direct,
        raw_observations=training["observations"],
        runtime_compatibility_sha256=str(
            manifest["runtime_compatibility_sha256"]
        ),
        policy=root / "direct_family_predictor_policy.json",
        measurement_source_kind="native_counterbalanced_development_pilot",
    )
    reconstructed_suite = build_m15_direct_family_prediction_suite(
        workload=direct,
        base_bundle=base,
        catalog=root / "semantic_catalog.json",
        mapping=root / "predicate_mapping.json",
        memory=memory,
        policy=root / "direct_family_predictor_policy.json",
    )
    persisted_suite = _json_object(live / "selection/prediction_suite.json")
    if persisted_suite != reconstructed_suite.to_dict():
        raise ValueError("persisted prediction suite differs from reconstruction")
    source_records = {
        str(item["base_query_id"]): item
        for item in persisted_suite["prediction_sources"]
    }
    sources: dict[str, dict[str, Any]] = {}
    for query_id, source in reconstructed_suite.sources.items():
        persisted = _json_object(
            live / "selection/queries" / query_id / "prediction_source.json"
        )
        if persisted != source.to_dict():
            raise ValueError("persisted prediction source differs from reconstruction")
        record = source_records.get(query_id)
        if (
            not isinstance(record, Mapping)
            or record.get("prediction_source_sha256")
            != persisted.get("prediction_source_sha256")
            or record.get("candidate_set_sha256")
            != reconstructed_suite.candidate_sets[query_id].candidate_set_hash
            or record.get("prediction_count") != len(persisted["predictions"])
        ):
            raise ValueError("prediction suite source binding drifted")
        sources[query_id] = persisted
    shadow_files = sorted((live / "shadow/runs").glob("*.json"))
    shadow_runs = [_json_object(path) for path in shadow_files]
    observed = _median_observations(shadow_runs)
    task_records: list[dict[str, Any]] = []
    for task in direct.heldout_selection_view["semantic_tasks"]:
        query_id = str(task["base_query_id"])
        class_id = str(task["semantic_class_id"])
        candidates = {
            str(item["physical_strategy"]): dict(item)
            for item in task["physical_candidates"]
        }
        if set(candidates) != set(_STRATEGIES):
            raise ValueError("held-out task physical strategy set changed")
        predictions = {
            str(item["physical_strategy"]): item
            for item in sources[query_id]["predictions"]
            if item["semantic_class_id"] == class_id
        }
        if set(predictions) != set(_STRATEGIES):
            raise ValueError("sealed predictions do not cover one held-out class")

        observed_costs = {
            strategy: observed[candidates[strategy]["plan_id"]]
            for strategy in _STRATEGIES
        }
        family_costs = {
            strategy: {
                "latency_ms": predictions[strategy]["estimated_latency_ms"],
                "total_bytes_moved": predictions[strategy][
                    "estimated_total_bytes_moved"
                ],
            }
            for strategy in _STRATEGIES
        }
        choices = {
            "family_memory_primary": _choose(
                candidates=candidates,
                costs=family_costs,
                order=selected_policy["physical_selection_order"],
            ),
            "family_global_no_instance_features": _choose(
                candidates=candidates,
                costs=strategy_global_medians,
                order=selected_policy["physical_selection_order"],
            ),
            "fixed_parallel_hash": "parallel_hash_join",
            "fixed_risk_first_bind": "risk_first_bind_join",
            "observed_oracle_upper_bound": _choose(
                candidates=candidates,
                costs=observed_costs,
                order=selected_policy["evaluation_oracles"]["physical_winner"],
            ),
        }
        physical_winner = choices["observed_oracle_upper_bound"]
        latency_reference = _choose(
            candidates=candidates,
            costs=observed_costs,
            order=selected_policy["evaluation_oracles"][
                "latency_regret_reference"
            ],
        )
        bytes_reference = _choose(
            candidates=candidates,
            costs=observed_costs,
            order=selected_policy["evaluation_oracles"][
                "bytes_regret_reference"
            ],
        )
        task_records.append(
            {
                "base_query_id": query_id,
                "semantic_task_id": task["semantic_task_id"],
                "semantic_class_id": class_id,
                "physical_winner_strategy": physical_winner,
                "latency_regret_reference_strategy": latency_reference,
                "bytes_regret_reference_strategy": bytes_reference,
                "methods": {
                    method_id: {
                        "selected_strategy": strategy,
                        "selected_plan_id": candidates[strategy]["plan_id"],
                        "winner_correct": strategy == physical_winner,
                        "observed_median_latency_ms": observed_costs[strategy][
                            "latency_ms"
                        ],
                        "observed_median_total_bytes_moved": observed_costs[
                            strategy
                        ]["total_bytes_moved"],
                        "latency_regret_ms": observed_costs[strategy]["latency_ms"]
                        - observed_costs[latency_reference]["latency_ms"],
                        "bytes_regret": observed_costs[strategy][
                            "total_bytes_moved"
                        ]
                        - observed_costs[bytes_reference]["total_bytes_moved"],
                    }
                    for method_id, strategy in choices.items()
                },
            }
        )
    if len(task_records) != 10:
        raise ValueError("held-out baseline analysis must cover ten semantic tasks")

    methods: dict[str, Any] = {}
    method_specs = {
        str(item["method_id"]): item for item in selected_policy["methods"]
    }
    for method_id in _METHOD_IDS:
        records = [item["methods"][method_id] for item in task_records]
        winner_count = sum(item["winner_correct"] for item in records)
        methods[method_id] = {
            "role": method_specs[method_id]["role"],
            "selection_source": method_specs[method_id]["selection_source"],
            "semantic_task_count": len(records),
            "physical_winner_correct_count": winner_count,
            "physical_winner_accuracy": winner_count / len(records),
            "latency_regret_ms": _summary(
                [float(item["latency_regret_ms"]) for item in records]
            ),
            "bytes_regret": _summary(
                [float(item["bytes_regret"]) for item in records]
            ),
            "strategy_selection_counts": dict(
                sorted(Counter(item["selected_strategy"] for item in records).items())
            ),
        }
    body = {
        "schema_version": DIRECT_FAMILY_BASELINE_ANALYSIS_SCHEMA_VERSION,
        "policy_id": selected_policy["policy_id"],
        "policy_sha256": content_hash(selected_policy),
        "source_run_root": str(root),
        "source_commit": accepted["expected_commit"],
        "source_audit_sha256": content_hash(accepted),
        "source_audit_check_count": accepted["check_count"],
        "source_audit_revalidated_at_analysis": True,
        "aggregation": copy.deepcopy(selected_policy["aggregation"]),
        "evaluation_oracles": copy.deepcopy(
            selected_policy["evaluation_oracles"]
        ),
        "counts": {
            "training_physical_plans": len(training["observations"]),
            "heldout_semantic_tasks": len(task_records),
            "shadow_plan_runs": len(shadow_runs),
            "methods": len(_METHOD_IDS),
        },
        "training_strategy_global_medians": strategy_global_medians,
        "methods": methods,
        "per_semantic_task": task_records,
        "analysis_scope": "physical_strategy_within_semantic_class",
        "semantic_frontier_comparison": False,
        "live_current_query_profiling_baseline": False,
        "analysis_backend_calls": 0,
        "analysis_llm_calls": 0,
        "analysis_ontology_service_calls": 0,
        "current_query_observation_operations": [],
        "shadow_measurements_used_for_evaluation_only": True,
        "online_selected_results_used_for_selection_or_metrics": False,
        "answer_row_values_used_for_selection_or_metrics": False,
        "confirmatory_statistics": False,
        "development_candidate_baselines_only": True,
        "paper_result": False,
    }
    return {**body, "analysis_sha256": content_hash(body)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        run_root = Path(args.run_root).resolve()
        payload = analyze_m15_direct_family_baselines(
            run_root=run_root,
            audit=args.audit,
            policy=args.policy,
        )
        if args.output:
            output = Path(args.output).resolve()
            if output == run_root or run_root in output.parents:
                raise ValueError(
                    "baseline output must remain outside the source run tree"
                )
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.exists():
                raise ValueError(f"baseline output exists: {output}")
            output.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
