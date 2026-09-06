"""Build a compact claim-bounded summary of an audited F2C10D pilot."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_family_pilot_evidence import (
    DIRECT_FAMILY_PILOT_AUDIT_SCHEMA_VERSION,
)
from xgap.experiments.m15_live_direct_family_pilot import (
    DIRECT_FAMILY_PILOT_ANALYSIS_SCHEMA_VERSION,
    LIVE_DIRECT_FAMILY_PILOT_SCHEMA_VERSION,
)


DIRECT_FAMILY_PILOT_SUMMARY_SCHEMA_VERSION = (
    "m15-f2c10d-direct-family-pilot-summary-v1"
)


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


def build_m15_direct_family_pilot_summary(
    *,
    run_root: str | Path,
    audit: Mapping[str, Any] | str | Path,
) -> dict[str, Any]:
    """Extract only audited development metrics; never mutate the run tree."""

    selected = Path(run_root)
    if selected.is_symlink():
        raise ValueError("run_root must not be a symbolic link")
    root = selected.resolve()
    if not root.is_dir():
        raise ValueError("run_root must be a real directory")
    audit_payload = _json_object(audit)
    if audit_payload.get("schema_version") != (
        DIRECT_FAMILY_PILOT_AUDIT_SCHEMA_VERSION
    ):
        raise ValueError("audit schema is unsupported")
    if (
        audit_payload.get("success") is not True
        or audit_payload.get("failed_check_ids") != []
        or audit_payload.get("run_tree_mutated") is not False
        or Path(str(audit_payload.get("run_root"))).resolve() != root
    ):
        raise ValueError("pilot audit is not an accepted read-only audit")

    live = root / "native-service-run/direct-family-pilot-run"
    outer_status = _read_object(root / "run_status.json")
    manifest = _read_object(live / "run_manifest.json")
    seal = _read_object(live / "selection_seal.json")
    analysis = _read_object(live / "analysis.json")
    if manifest.get("schema_version") != LIVE_DIRECT_FAMILY_PILOT_SCHEMA_VERSION:
        raise ValueError("live pilot schema is unsupported")
    if analysis.get("schema_version") != (
        DIRECT_FAMILY_PILOT_ANALYSIS_SCHEMA_VERSION
    ):
        raise ValueError("pilot analysis schema is unsupported")
    if outer_status.get("git_commit") != audit_payload.get("expected_commit"):
        raise ValueError("audit and job commit differ")
    if outer_status.get("status") != "success" or manifest.get("status") != "success":
        raise ValueError("pilot run is not successful")
    if manifest.get("paper_result") is not False or analysis.get("paper_result") is not False:
        raise ValueError("development pilot was incorrectly promoted")

    prediction_error = analysis["prediction_error"]
    winner = analysis["physical_winner_accuracy"]
    overlap = analysis["predicted_observed_frontier_overlap"]
    body = {
        "schema_version": DIRECT_FAMILY_PILOT_SUMMARY_SCHEMA_VERSION,
        "evidence_class": "six_query_native_development_pilot",
        "git_commit": outer_status["git_commit"],
        "slurm_job_id": outer_status.get("slurm_job_id"),
        "hostname": manifest.get("environment", {}).get("hostname"),
        "schedule_sha256": manifest["schedule_sha256"],
        "selection_seal_sha256": manifest["selection_seal_sha256"],
        "training_memory_view_sha256": manifest["training_memory_view_sha256"],
        "prediction_suite_sha256": manifest["prediction_suite_sha256"],
        "analysis_sha256": manifest["analysis_sha256"],
        "counts": copy.deepcopy(dict(manifest["summary"])),
        "online_cardinality": copy.deepcopy(dict(seal["online_cardinality"])),
        "returned_semantic_plans_per_query": {
            str(item["base_query_id"]): int(item["returned_semantic_plan_count"])
            for item in seal["query_frontiers"]
        },
        "metrics": {
            "prediction_error": {
                "plan_count": prediction_error["plan_count"],
                "latency_ms": copy.deepcopy(dict(prediction_error["latency_ms"])),
                "total_bytes_moved": copy.deepcopy(
                    dict(prediction_error["total_bytes_moved"])
                ),
            },
            "physical_winner_accuracy": {
                "semantic_class_count": winner["semantic_class_count"],
                "correct_count": winner["correct_count"],
                "accuracy": winner["accuracy"],
            },
            "latency_regret_ms": copy.deepcopy(
                dict(analysis["latency_regret_ms"])
            ),
            "bytes_regret": copy.deepcopy(dict(analysis["bytes_regret"])),
            "predicted_observed_frontier_overlap": {
                "query_count": len(overlap["per_query"]),
                "mean_jaccard": overlap["mean_jaccard"],
                "per_query": [
                    {
                        "base_query_id": item["base_query_id"],
                        "jaccard": item["jaccard"],
                    }
                    for item in overlap["per_query"]
                ],
            },
        },
        "execution_boundary": {
            "current_query_profile_calls": analysis[
                "current_query_profile_calls"
            ],
            "shadow_used_for_selection": analysis["shadow_used_for_selection"],
            "automatic_retries": manifest["automatic_retries"],
        },
        "audit": {
            "schema_version": audit_payload["schema_version"],
            "check_count": audit_payload["check_count"],
            "failed_check_ids": [],
            "run_tree_mutated": False,
        },
        "claim_boundary": {
            "development_pilot_only": True,
            "confirmatory_statistics": False,
            "generalization_claim": False,
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
        payload = build_m15_direct_family_pilot_summary(
            run_root=args.run_root,
            audit=args.audit,
        )
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.exists():
                raise ValueError(f"summary output exists: {output}")
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
