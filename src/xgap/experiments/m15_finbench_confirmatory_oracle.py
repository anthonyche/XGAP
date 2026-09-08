"""Open the FinBench oracle only after every confirmatory block is sealed."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_confirmatory_analysis import (
    analyze_finbench_confirmatory_measurement_ledger,
    build_finbench_confirmatory_measurement_ledger,
    _schedule,
)
from xgap.experiments.m15_finbench_confirmatory_phase import (
    FINBENCH_CONFIRMATORY_PROFILE_PHASE_SCHEMA_VERSION,
    FINBENCH_CONFIRMATORY_TRAINING_PHASE_SCHEMA_VERSION,
    build_finbench_confirmatory_profile_phase,
    build_finbench_confirmatory_training_phase,
    _accepted_blocks,
)
from xgap.experiments.m15_finbench_confirmatory_selection_admission import (
    validate_finbench_confirmatory_selection_admission,
)
from xgap.experiments.m15_finbench_federation import canonicalize_finbench_rows
from xgap.experiments.m15_finbench_family_memory import DEFAULT_POLICY_PATH
from xgap.experiments.m15_finbench_workload import load_finbench_primary_workload


FINBENCH_CONFIRMATORY_ORACLE_GATE_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-delayed-oracle-gate-v1"
)


class FinBenchConfirmatoryOracleError(ValueError):
    """Raised when the delayed-oracle boundary is incomplete or inconsistent."""


def _hashed(value: Mapping[str, Any], *, field: str, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FinBenchConfirmatoryOracleError(f"{name} must be an object")
    result = copy.deepcopy(dict(value))
    claimed = result.get(field)
    body = {key: item for key, item in result.items() if key != field}
    if not isinstance(claimed, str) or content_hash(body) != claimed:
        raise FinBenchConfirmatoryOracleError(f"{name} hash mismatch")
    return result


def _phase_blocks(
    accepted_blocks: Sequence[Mapping[str, Any]],
    *,
    schedule: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    phases = (
        "crossfit_training_measurement",
        "current_query_profile_acquisition",
        "paired_selected_serving",
        "postselection_shadow_evaluation",
    )
    by_phase: dict[str, list[Mapping[str, Any]]] = {phase: [] for phase in phases}
    for bundle in accepted_blocks:
        context = bundle.get("execution_context") if isinstance(bundle, Mapping) else None
        attempt = context.get("block_attempt") if isinstance(context, Mapping) else None
        phase = attempt.get("phase") if isinstance(attempt, Mapping) else None
        if phase not in by_phase:
            raise FinBenchConfirmatoryOracleError("accepted block phase changed")
        by_phase[str(phase)].append(bundle)
    return {
        phase: _accepted_blocks(values, schedule=schedule, phase=phase)
        for phase, values in by_phase.items()
    }


def open_finbench_confirmatory_oracle(
    *,
    workload_root: str | Path,
    schedule: Mapping[str, Any],
    selection_admission: Mapping[str, Any],
    accepted_blocks: Sequence[Mapping[str, Any]],
    training_phase: Mapping[str, Any],
    profile_phase: Mapping[str, Any],
    policy: Mapping[str, Any] | str | Path = DEFAULT_POLICY_PATH,
) -> dict[str, Any]:
    """Validate all 1,888 outcomes, then and only then read answer rows."""

    frozen = _schedule(schedule)
    admission = validate_finbench_confirmatory_selection_admission(
        selection_admission,
        workload_sha256=str(frozen["workload_sha256"]),
    )
    phases = _phase_blocks(accepted_blocks, schedule=frozen)
    all_blocks = [item for values in phases.values() for item in values]
    measurement_count = sum(len(item["measurements"]) for item in all_blocks)
    if len(all_blocks) != 22 or measurement_count != 1888:
        raise FinBenchConfirmatoryOracleError(
            "the complete frozen measurement campaign is not sealed"
        )
    training = _hashed(
        training_phase, field="training_phase_sha256", name="training phase"
    )
    profile = _hashed(
        profile_phase, field="profile_phase_sha256", name="profile phase"
    )
    if (
        training.get("schema_version")
        != FINBENCH_CONFIRMATORY_TRAINING_PHASE_SCHEMA_VERSION
        or profile.get("schema_version")
        != FINBENCH_CONFIRMATORY_PROFILE_PHASE_SCHEMA_VERSION
    ):
        raise FinBenchConfirmatoryOracleError("selection phase schema changed")
    rebuilt_training = build_finbench_confirmatory_training_phase(
        workload_root=workload_root,
        schedule=frozen,
        selection_admission=admission,
        accepted_blocks=[
            bundle
            for bundle in accepted_blocks
            if bundle["execution_context"]["block_attempt"]["phase"]
            == "crossfit_training_measurement"
        ],
        measurement_source_id=str(
            training["crossfit_prediction_suite"]["measurement_source_id"]
        ),
        policy=policy,
    )
    rebuilt_profile = build_finbench_confirmatory_profile_phase(
        schedule=frozen,
        accepted_blocks=[
            bundle
            for bundle in accepted_blocks
            if bundle["execution_context"]["block_attempt"]["phase"]
            == "current_query_profile_acquisition"
        ],
    )
    if rebuilt_training != training or rebuilt_profile != profile:
        raise FinBenchConfirmatoryOracleError(
            "pre-oracle selection phase reconstruction failed"
        )
    request_hashes = {
        item["attempt"]["execution_request_sha256"] for item in all_blocks
    }
    authority_hashes = {
        item["attempt"]["execution_authority_sha256"] for item in all_blocks
    }
    if len(request_hashes) != 1 or len(authority_hashes) != 1:
        raise FinBenchConfirmatoryOracleError(
            "measurement blocks do not share one authority"
        )

    # This is the first operation in this function that parses answer content.
    workload = load_finbench_primary_workload(workload_root)
    oracle_queries = workload["sealed_oracles"]["queries"]
    measurements: list[dict[str, Any]] = []
    exact_failure_ids: list[str] = []
    timeout_count = 0
    for block in all_blocks:
        expected_by_identity = {
            str(item["scheduled_identity"]): item
            for item in block["attempt"]["measurements"]
        }
        for raw in block["measurements"]:
            identity = str(raw["scheduled_identity"])
            expected = expected_by_identity[identity]
            query_id = str(expected["query_id"])
            if raw["outcome"] == "query_timeout":
                exact_answer = None
                timeout_count += 1
            else:
                oracle = oracle_queries.get(query_id)
                if not isinstance(oracle, Mapping) or not isinstance(
                    oracle.get("final_rows"), list
                ):
                    raise FinBenchConfirmatoryOracleError(
                        f"answer oracle is invalid for {query_id}"
                    )
                expected_rows = canonicalize_finbench_rows(
                    str(expected["family_id"]), oracle["final_rows"]
                )
                exact_answer = raw["canonical_rows"] == expected_rows
                if not exact_answer:
                    exact_failure_ids.append(identity)
            measurements.append(
                {
                    "scheduled_identity": identity,
                    "attempt_id": raw["attempt_id"],
                    "outcome": raw["outcome"],
                    "elapsed_ms": raw["elapsed_ms"],
                    "total_bytes_moved": raw["total_bytes_moved"],
                    "total_remote_calls": raw["total_remote_calls"],
                    "exact_answer": exact_answer,
                    "physical_strategy": raw["physical_strategy"],
                }
            )
    oracle_body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_ORACLE_GATE_SCHEMA_VERSION,
        "schedule_sha256": frozen["schedule_sha256"],
        "workload_sha256": frozen["workload_sha256"],
        "selection_admission_sha256": admission[
            "selection_admission_sha256"
        ],
        "execution_request_sha256": next(iter(request_hashes)),
        "execution_authority_sha256": next(iter(authority_hashes)),
        "training_phase_sha256": training["training_phase_sha256"],
        "profile_phase_sha256": profile["profile_phase_sha256"],
        "accepted_block_count": len(all_blocks),
        "measurement_count_before_oracle_open": measurement_count,
        "backend_calls_after_oracle_open": 0,
        "answer_oracle_opened_after_all_measurements": True,
        "answer_oracle_used_for_selection": False,
        "query_timeout_count": timeout_count,
        "successful_measurement_count": measurement_count - timeout_count,
        "exact_failure_ids": sorted(exact_failure_ids),
        "all_successful_measurements_exact": not exact_failure_ids,
        "automatic_retries": 0,
        "paper_result": False,
    }
    if exact_failure_ids:
        result = {
            **oracle_body,
            "status": "invalidated_by_answer_oracle",
            "measurement_ledger": None,
            "analysis": None,
        }
        result["oracle_gate_sha256"] = content_hash(result)
        return result
    infrastructure_attempts: list[dict[str, Any]] = []
    for item in all_blocks:
        infrastructure_attempts.extend(
            {
                key: prior[key]
                for key in (
                    "attempt_id",
                    "measurement_block_id",
                    "attempt_index",
                    "status",
                    "valid_measurement_count",
                    "replacement_of_attempt_id",
                    "failure_category",
                )
            }
            for prior in item["infrastructure_attempts"]
        )
        infrastructure_attempts.append(
            {
                "attempt_id": item["attempt"]["attempt_id"],
                "measurement_block_id": item["attempt"][
                    "measurement_block_id"
                ],
                "attempt_index": item["attempt"]["attempt_index"],
                "status": "completed",
                "valid_measurement_count": len(item["measurements"]),
                "replacement_of_attempt_id": item["attempt"][
                    "replacement_of_attempt_id"
                ],
                "failure_category": None,
            }
        )
    ledger = build_finbench_confirmatory_measurement_ledger(
        schedule=frozen,
        crossfit_prediction_suite=training["crossfit_prediction_suite"],
        family_selection_seal=training["family_selection_seal"],
        profile_selection_seal=profile["profile_selection_seal"],
        measurements=measurements,
        infrastructure_attempts=infrastructure_attempts,
    ).to_dict()
    analysis = analyze_finbench_confirmatory_measurement_ledger(ledger)
    result = {
        **oracle_body,
        "status": "success",
        "measurement_ledger": ledger,
        "analysis": analysis,
    }
    result["oracle_gate_sha256"] = content_hash(result)
    return result


def _read(path: str | Path, *, name: str) -> dict[str, Any]:
    selected = Path(path)
    if selected.is_symlink() or not selected.is_file():
        raise FinBenchConfirmatoryOracleError(f"{name} must be a regular file")
    value = json.loads(selected.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FinBenchConfirmatoryOracleError(f"{name} must contain an object")
    return value


def _write(path: str | Path, value: Mapping[str, Any]) -> Path:
    selected = Path(path)
    if selected.exists() or selected.is_symlink():
        raise FileExistsError(f"output exists: {selected}")
    selected.parent.mkdir(parents=True, exist_ok=True)
    temporary = selected.with_name(selected.name + f".partial-{os.getpid()}")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, selected)
    return selected


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload-root", required=True)
    parser.add_argument("--schedule", required=True)
    parser.add_argument("--selection-admission", required=True)
    parser.add_argument("--accepted-block", action="append", required=True)
    parser.add_argument("--training-phase", required=True)
    parser.add_argument("--profile-phase", required=True)
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        result = open_finbench_confirmatory_oracle(
            workload_root=args.workload_root,
            schedule=_read(args.schedule, name="measurement schedule"),
            selection_admission=_read(
                args.selection_admission, name="selection admission"
            ),
            accepted_blocks=[
                _read(path, name=f"accepted block {index}")
                for index, path in enumerate(args.accepted_block, start=1)
            ],
            training_phase=_read(args.training_phase, name="training phase"),
            profile_phase=_read(args.profile_phase, name="profile phase"),
            policy=args.policy,
        )
        output = _write(args.output, result)
    except (FileExistsError, OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": result["status"],
                "output": str(output.resolve()),
                "oracle_gate_sha256": result["oracle_gate_sha256"],
                "paper_result": False,
            },
            sort_keys=True,
        )
    )
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
