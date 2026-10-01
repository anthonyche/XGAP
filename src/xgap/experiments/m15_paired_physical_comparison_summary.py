"""Build a compact claim-bounded summary of an audited F2C13B paired run."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_live_paired_physical_comparison import (
    LIVE_PAIRED_PHYSICAL_SCHEMA_VERSION,
    PAIRED_PHYSICAL_ANALYSIS_SCHEMA_VERSION,
)
from xgap.experiments.m15_paired_physical_comparison_evidence import (
    PAIRED_PHYSICAL_AUDIT_SCHEMA_VERSION,
    audit_m15_paired_physical_comparison,
)


PAIRED_PHYSICAL_SUMMARY_SCHEMA_VERSION = (
    "m15-f2c13c-paired-physical-comparison-summary-v1"
)
_METHOD_IDS = ("family_memory", "current_query_dual_profile")
_EXPECTED_COUNTS = {
    "training_plan_runs": 144,
    "profile_acquisition_plan_runs": 20,
    "paired_selected_plan_runs": 20,
    "evaluation_shadow_plan_runs": 80,
    "total_plan_runs": 264,
    "training_backend_calls": 288,
    "profile_acquisition_backend_calls": 40,
    "paired_selected_backend_calls": 40,
    "evaluation_shadow_backend_calls": 160,
    "total_backend_calls": 528,
    "family_memory_current_query_profile_calls": 0,
    "profile_method_current_query_profile_calls": 20,
}


def _json_object(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise ValueError("summary input must be a regular non-symbolic-link file")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("summary input must contain a JSON object")
    return dict(payload)


def _read_object(path: Path) -> dict[str, Any]:
    return _json_object(path)


def _method_metrics(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "physical_winner_accuracy": copy.deepcopy(
            dict(value["physical_winner_accuracy"])
        ),
        "selected_plan_latency_regret_ms": copy.deepcopy(
            dict(value["selected_plan_latency_regret_ms"])
        ),
        "selected_plan_bytes_regret": copy.deepcopy(
            dict(value["selected_plan_bytes_regret"])
        ),
        "selected_serving_latency_ms": copy.deepcopy(
            dict(value["selected_execution_latency_ms"])
        ),
        "selected_serving_bytes": copy.deepcopy(
            dict(value["selected_execution_bytes"])
        ),
    }


def build_m15_paired_physical_comparison_summary(
    *,
    run_root: str | Path,
    audit: Mapping[str, Any] | str | Path,
) -> dict[str, Any]:
    """Extract audited paired metrics without mutating or reopening the run."""

    selected = Path(run_root)
    if selected.is_symlink():
        raise ValueError("run_root must not be a symbolic link")
    root = selected.resolve()
    if not root.is_dir():
        raise ValueError("run_root must be a real directory")
    audit_payload = _json_object(audit)
    if audit_payload.get("schema_version") != PAIRED_PHYSICAL_AUDIT_SCHEMA_VERSION:
        raise ValueError("audit schema is unsupported")
    if (
        audit_payload.get("success") is not True
        or audit_payload.get("failed_check_ids") != []
        or audit_payload.get("run_tree_mutated") is not False
        or Path(str(audit_payload.get("run_root"))).resolve() != root
    ):
        raise ValueError("paired audit is not an accepted read-only audit")
    fresh_audit = audit_m15_paired_physical_comparison(
        run_root=root,
        expected_commit=str(audit_payload["expected_commit"]),
    )
    if not fresh_audit.success or fresh_audit.run_tree_mutated:
        raise ValueError("paired run no longer passes its read-only audit")
    if fresh_audit.to_dict() != audit_payload:
        raise ValueError("supplied audit differs from current reconstruction")

    live = root / "native-service-run/paired-physical-comparison-run"
    outer_status = _read_object(root / "run_status.json")
    manifest = _read_object(live / "run_manifest.json")
    family_seal = _read_object(live / "family_selection_seal.json")
    profile_seal = _read_object(live / "profile_selection_seal.json")
    analysis = _read_object(live / "analysis.json")
    if manifest.get("schema_version") != LIVE_PAIRED_PHYSICAL_SCHEMA_VERSION:
        raise ValueError("live paired schema is unsupported")
    if analysis.get("schema_version") != PAIRED_PHYSICAL_ANALYSIS_SCHEMA_VERSION:
        raise ValueError("paired analysis schema is unsupported")
    if outer_status.get("git_commit") != audit_payload.get("expected_commit"):
        raise ValueError("audit and job commit differ")
    if outer_status.get("status") != "success" or manifest.get("status") != "success":
        raise ValueError("paired run is not successful")
    if manifest.get("validation", {}).get("passed") is not True:
        raise ValueError("paired run validation did not pass")
    if (
        manifest.get("paper_result") is not False
        or analysis.get("paper_result") is not False
        or manifest.get("confirmatory_statistics") is not False
        or analysis.get("confirmatory_statistics") is not False
    ):
        raise ValueError("development comparison was incorrectly promoted")
    if manifest.get("summary") != _EXPECTED_COUNTS:
        raise ValueError("paired run counts differ from the frozen protocol")
    if analysis.get("semantic_task_count") != 10:
        raise ValueError("paired analysis must cover exactly ten semantic tasks")
    if analysis.get("shadow_measurements_used_for_evaluation_only") is not True:
        raise ValueError("shadow measurements crossed the selection boundary")

    family_by_task = {
        str(item["semantic_task_id"]): item
        for item in family_seal["selections"]
    }
    profile_by_task = {
        str(item["semantic_task_id"]): item
        for item in profile_seal["selections"]
    }
    if set(family_by_task) != set(profile_by_task) or len(family_by_task) != 10:
        raise ValueError("paired selection seals do not cover the same ten tasks")
    if manifest.get("family_selection_seal_sha256") != family_seal.get(
        "selection_seal_sha256"
    ):
        raise ValueError("family selection seal hash differs from the manifest")
    if manifest.get("profile_selection_seal_sha256") != profile_seal.get(
        "selection_seal_sha256"
    ):
        raise ValueError("profile selection seal hash differs from the manifest")
    if manifest.get("analysis_sha256") != analysis.get("analysis_sha256"):
        raise ValueError("analysis hash differs from the manifest")

    agreement_rows = []
    for task_id in sorted(family_by_task):
        family_item = family_by_task[task_id]
        profile_item = profile_by_task[task_id]
        agreement_rows.append(
            {
                "semantic_task_id": task_id,
                "same_selected_plan": (
                    family_item["selected_plan_id"]
                    == profile_item["selected_plan_id"]
                ),
                "same_selected_strategy": (
                    family_item["selected_strategy"]
                    == profile_item["selected_strategy"]
                ),
            }
        )
    methods = analysis["methods"]
    if set(methods) != set(_METHOD_IDS):
        raise ValueError("paired analysis method set is unsupported")
    paired = analysis["paired_profile_minus_memory"]
    historical_training = copy.deepcopy(dict(analysis["historical_training"]))
    if (
        historical_training.get("reported_separately") is not True
        or historical_training.get("silently_amortized") is not False
    ):
        raise ValueError("historical training cost boundary is invalid")

    body = {
        "schema_version": PAIRED_PHYSICAL_SUMMARY_SCHEMA_VERSION,
        "evidence_class": (
            "ten_semantic_task_same_allocation_paired_development_run"
        ),
        "git_commit": outer_status["git_commit"],
        "slurm_job_id": outer_status.get("slurm_job_id"),
        "hostname": manifest.get("environment", {}).get("hostname"),
        "schedule_sha256": manifest["schedule_sha256"],
        "family_selection_seal_sha256": manifest[
            "family_selection_seal_sha256"
        ],
        "profile_selection_seal_sha256": manifest[
            "profile_selection_seal_sha256"
        ],
        "analysis_sha256": manifest["analysis_sha256"],
        "counts": copy.deepcopy(_EXPECTED_COUNTS),
        "methods": {
            method_id: _method_metrics(methods[method_id])
            for method_id in _METHOD_IDS
        },
        "paired_profile_minus_memory": {
            "latency_regret_ms": copy.deepcopy(
                dict(paired["latency_regret_ms"])
            ),
            "bytes_regret": copy.deepcopy(dict(paired["bytes_regret"])),
            "per_semantic_task": copy.deepcopy(
                list(paired["per_semantic_task"])
            ),
        },
        "selection_agreement": {
            "semantic_task_count": len(agreement_rows),
            "same_selected_plan_count": sum(
                item["same_selected_plan"] for item in agreement_rows
            ),
            "same_selected_strategy_count": sum(
                item["same_selected_strategy"] for item in agreement_rows
            ),
            "per_semantic_task": agreement_rows,
        },
        "profile_acquisition_cost": copy.deepcopy(
            dict(analysis["profile_acquisition"])
        ),
        "historical_training_cost": historical_training,
        "count_based_training_break_even_future_tasks": analysis[
            "count_based_training_break_even_future_tasks"
        ],
        "evaluation_only_controls": copy.deepcopy(
            dict(analysis["evaluation_only_controls"])
        ),
        "execution_boundary": {
            "family_memory_current_query_profile_calls": 0,
            "profile_method_current_query_profile_calls": 20,
            "shadow_measurements_used_for_evaluation_only": True,
            "automatic_retries": manifest["automatic_retries"],
            "llm_calls_made": manifest["llm_calls_made"],
            "ontology_service_calls_made": manifest[
                "ontology_service_calls_made"
            ],
        },
        "audit": {
            "schema_version": audit_payload["schema_version"],
            "check_count": audit_payload["check_count"],
            "failed_check_ids": [],
            "run_tree_mutated": False,
        },
        "claim_boundary": {
            "development_run_only": True,
            "semantic_task_count": 10,
            "native_allocation_count": 1,
            "descriptive_statistics_only": True,
            "confirmatory_statistics": False,
            "generalization_claim": False,
            "semantic_frontier_claim": False,
            "paper_result": False,
        },
        "paper_result": False,
    }
    return {**body, "summary_sha256": content_hash(body)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        payload = build_m15_paired_physical_comparison_summary(
            run_root=args.run_root,
            audit=args.audit,
        )
        if args.output:
            output = Path(args.output)
            resolved_root = Path(args.run_root).resolve()
            resolved_output = output.resolve()
            if resolved_output == resolved_root or resolved_output.is_relative_to(
                resolved_root
            ):
                raise ValueError("summary output must be outside the run tree")
            if output.exists():
                raise ValueError(f"summary output exists: {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
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
