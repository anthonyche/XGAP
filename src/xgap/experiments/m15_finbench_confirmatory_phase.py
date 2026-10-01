"""Assemble pre-oracle confirmatory selection seals from audited blocks."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_confirmatory_analysis import (
    build_finbench_confirmatory_family_selection_seal,
    build_finbench_confirmatory_profile_selection_seal,
    _schedule,
)
from xgap.experiments.m15_finbench_confirmatory_block_evidence import (
    FINBENCH_CONFIRMATORY_BLOCK_AUDIT_SCHEMA_VERSION,
)
from xgap.experiments.m15_finbench_confirmatory_crossfit import (
    build_finbench_confirmatory_crossfit_predictions,
)
from xgap.experiments.m15_finbench_confirmatory_execution import (
    block_ids_for_phase,
    validate_finbench_confirmatory_block_execution_envelope,
)
from xgap.experiments.m15_finbench_confirmatory_selection_admission import (
    validate_finbench_confirmatory_selection_admission,
)
from xgap.experiments.m15_finbench_family_memory import DEFAULT_POLICY_PATH
from xgap.experiments.m15_live_finbench_confirmatory_block import (
    FINBENCH_CONFIRMATORY_RAW_MEASUREMENTS_SCHEMA_VERSION,
)


FINBENCH_CONFIRMATORY_TRAINING_PHASE_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-training-phase-v1"
)
FINBENCH_CONFIRMATORY_PROFILE_PHASE_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-profile-phase-v1"
)
FINBENCH_CONFIRMATORY_ACCEPTED_BLOCK_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-accepted-block-v1"
)
FINBENCH_CONFIRMATORY_FAILED_ATTEMPT_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-failed-attempt-v1"
)


class FinBenchConfirmatoryPhaseError(ValueError):
    """Raised when audited pre-oracle block evidence is incomplete."""


def _hashed(
    value: Mapping[str, Any], *, field: str, name: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FinBenchConfirmatoryPhaseError(f"{name} must be an object")
    result = copy.deepcopy(dict(value))
    claimed = result.get(field)
    body = {key: item for key, item in result.items() if key != field}
    if not isinstance(claimed, str) or content_hash(body) != claimed:
        raise FinBenchConfirmatoryPhaseError(f"{name} hash mismatch")
    return result


def build_finbench_confirmatory_failed_attempt_bundle(
    *,
    execution_context: Mapping[str, Any],
    raw_measurements: Mapping[str, Any],
    block_audit: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind an audited zero-measurement infrastructure failure."""

    context = validate_finbench_confirmatory_block_execution_envelope(
        execution_context
    )
    attempt = context["block_attempt"]
    raw = _hashed(
        raw_measurements,
        field="raw_measurements_sha256",
        name="failed-attempt raw measurements",
    )
    audit = _hashed(
        block_audit,
        field="audit_sha256",
        name="failed-attempt block audit",
    )
    if (
        attempt.get("attempt_index") != 1
        or attempt.get("replacement_of_attempt_id") is not None
        or raw.get("schema_version")
        != FINBENCH_CONFIRMATORY_RAW_MEASUREMENTS_SCHEMA_VERSION
        or raw.get("attempt_id") != attempt["attempt_id"]
        or raw.get("measurement_block_id") != attempt["measurement_block_id"]
        or raw.get("measurements") != []
        or raw.get("measurement_count") != 0
        or raw.get("query_timeout_count") != 0
        or raw.get("oracle_opened") is not False
        or raw.get("automatic_retries") != 0
        or raw.get("paper_result") is not False
        or audit.get("schema_version")
        != FINBENCH_CONFIRMATORY_BLOCK_AUDIT_SCHEMA_VERSION
        or audit.get("success") is not True
        or audit.get("failed_check_ids") != []
        or audit.get("run_tree_mutated") is not False
        or audit.get("attempt_id") != attempt["attempt_id"]
        or audit.get("block_attempt_sha256")
        != attempt["block_attempt_sha256"]
        or audit.get("execution_context_sha256")
        != context["execution_context_sha256"]
        or audit.get("raw_measurements_sha256")
        != raw["raw_measurements_sha256"]
        or audit.get("attempt_status") != "infrastructure_failed"
        or audit.get("replacement_eligible") is not True
        or audit.get("valid_measurement_count") != 0
        or audit.get("failure_category") != "infrastructure_failure"
    ):
        raise FinBenchConfirmatoryPhaseError(
            "failed attempt is not eligible replacement provenance"
        )
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_FAILED_ATTEMPT_SCHEMA_VERSION,
        "execution_context": copy.deepcopy(context),
        "raw_measurements": copy.deepcopy(raw),
        "block_audit": copy.deepcopy(audit),
    }
    body["failed_attempt_sha256"] = content_hash(body)
    return body


def _accepted_blocks(
    values: Sequence[Mapping[str, Any]],
    *,
    schedule: Mapping[str, Any],
    phase: str,
    require_complete: bool = True,
) -> list[dict[str, Any]]:
    expected_blocks = block_ids_for_phase(schedule, phase)
    result: list[dict[str, Any]] = []
    observed_blocks: set[str] = set()
    request_hashes: set[str] = set()
    authority_hashes: set[str] = set()
    for value in values:
        bundle = _hashed(
            value, field="accepted_block_sha256", name="accepted block"
        )
        if (
            bundle.get("schema_version")
            != FINBENCH_CONFIRMATORY_ACCEPTED_BLOCK_SCHEMA_VERSION
            or set(bundle)
            != {
                "schema_version",
                "execution_context",
                "raw_measurements",
                "block_audit",
                "prior_failed_attempts",
                "accepted_block_sha256",
            }
        ):
            raise FinBenchConfirmatoryPhaseError(
                "accepted block bundle fields changed"
            )
        context = validate_finbench_confirmatory_block_execution_envelope(
            bundle["execution_context"]
        )
        attempt = context["block_attempt"]
        raw = _hashed(
            bundle["raw_measurements"],
            field="raw_measurements_sha256",
            name="raw measurements",
        )
        audit = _hashed(
            bundle["block_audit"], field="audit_sha256", name="block audit"
        )
        block_id = str(attempt["measurement_block_id"])
        if (
            attempt.get("phase") != phase
            or block_id not in expected_blocks
            or block_id in observed_blocks
            or attempt.get("schedule_sha256") != schedule["schedule_sha256"]
            or raw.get("schema_version")
            != FINBENCH_CONFIRMATORY_RAW_MEASUREMENTS_SCHEMA_VERSION
            or raw.get("attempt_id") != attempt["attempt_id"]
            or raw.get("measurement_block_id") != block_id
            or raw.get("oracle_opened") is not False
            or raw.get("automatic_retries") != 0
            or raw.get("paper_result") is not False
            or audit.get("schema_version")
            != FINBENCH_CONFIRMATORY_BLOCK_AUDIT_SCHEMA_VERSION
            or audit.get("success") is not True
            or audit.get("failed_check_ids") != []
            or audit.get("run_tree_mutated") is not False
            or audit.get("attempt_id") != attempt["attempt_id"]
            or audit.get("block_attempt_sha256")
            != attempt["block_attempt_sha256"]
            or audit.get("execution_context_sha256")
            != context["execution_context_sha256"]
            or audit.get("raw_measurements_sha256")
            != raw["raw_measurements_sha256"]
            or audit.get("attempt_status") != "completed"
            or audit.get("replacement_eligible") is not False
            or audit.get("valid_measurement_count")
            != len(attempt["measurements"])
            or audit.get("failure_category") is not None
        ):
            raise FinBenchConfirmatoryPhaseError(
                "accepted block provenance changed"
            )
        measurements = raw.get("measurements")
        if (
            not isinstance(measurements, list)
            or raw.get("measurement_count") != len(attempt["measurements"])
            or len(measurements) != len(attempt["measurements"])
        ):
            raise FinBenchConfirmatoryPhaseError(
                "accepted block measurement coverage changed"
            )
        expected_identities = [
            item["scheduled_identity"] for item in attempt["measurements"]
        ]
        observed_identities = [
            item.get("scheduled_identity")
            for item in measurements
            if isinstance(item, Mapping)
        ]
        if expected_identities != observed_identities:
            raise FinBenchConfirmatoryPhaseError(
                "accepted block measurement order changed"
            )
        prior_values = bundle.get("prior_failed_attempts")
        if not isinstance(prior_values, list):
            raise FinBenchConfirmatoryPhaseError(
                "prior failed attempts must be a list"
            )
        prior_failures = [
            _hashed(
                item,
                field="failed_attempt_sha256",
                name="prior failed attempt",
            )
            for item in prior_values
        ]
        if attempt["attempt_index"] == 1:
            if prior_failures or attempt["replacement_of_attempt_id"] is not None:
                raise FinBenchConfirmatoryPhaseError(
                    "first attempt contains replacement provenance"
                )
        elif attempt["attempt_index"] == 2:
            if len(prior_failures) != 1:
                raise FinBenchConfirmatoryPhaseError(
                    "replacement attempt requires one prior infrastructure failure"
                )
        else:
            raise FinBenchConfirmatoryPhaseError(
                "accepted attempt exceeds the replacement limit"
            )
        infrastructure_attempts: list[dict[str, Any]] = []
        for prior in prior_failures:
            if (
                prior.get("schema_version")
                != FINBENCH_CONFIRMATORY_FAILED_ATTEMPT_SCHEMA_VERSION
                or set(prior)
                != {
                    "schema_version",
                    "execution_context",
                    "raw_measurements",
                    "block_audit",
                    "failed_attempt_sha256",
                }
            ):
                raise FinBenchConfirmatoryPhaseError(
                    "prior failed attempt fields changed"
                )
            validated_prior = build_finbench_confirmatory_failed_attempt_bundle(
                execution_context=prior["execution_context"],
                raw_measurements=prior["raw_measurements"],
                block_audit=prior["block_audit"],
            )
            if validated_prior != prior:
                raise FinBenchConfirmatoryPhaseError(
                    "prior failed attempt reconstruction changed"
                )
            prior_context = validated_prior["execution_context"]
            prior_attempt = prior_context["block_attempt"]
            if (
                prior_context["schedule"] != context["schedule"]
                or prior_attempt["measurement_block_id"] != block_id
                or prior_attempt["phase"] != phase
                or prior_attempt["measurements"] != attempt["measurements"]
                or prior_attempt["execution_request_sha256"]
                != attempt["execution_request_sha256"]
                or prior_attempt["execution_authority_sha256"]
                != attempt["execution_authority_sha256"]
                or prior_attempt["runner_commit"] != attempt["runner_commit"]
                or attempt["replacement_of_attempt_id"]
                != prior_attempt["attempt_id"]
            ):
                raise FinBenchConfirmatoryPhaseError(
                    "replacement attempt does not match its failed predecessor"
                )
            request_hashes.add(str(prior_attempt["execution_request_sha256"]))
            authority_hashes.add(str(prior_attempt["execution_authority_sha256"]))
            infrastructure_attempts.append(
                {
                    "attempt_id": prior_attempt["attempt_id"],
                    "measurement_block_id": block_id,
                    "attempt_index": 1,
                    "status": "infrastructure_failed",
                    "valid_measurement_count": 0,
                    "replacement_of_attempt_id": None,
                    "failure_category": "infrastructure_failure",
                    "failed_attempt_sha256": prior["failed_attempt_sha256"],
                }
            )
        request_hashes.add(str(attempt["execution_request_sha256"]))
        authority_hashes.add(str(attempt["execution_authority_sha256"]))
        observed_blocks.add(block_id)
        result.append(
            {
                "block_id": block_id,
                "attempt": copy.deepcopy(attempt),
                "measurements": copy.deepcopy(measurements),
                "execution_context_sha256": context[
                    "execution_context_sha256"
                ],
                "raw_measurements_sha256": raw[
                    "raw_measurements_sha256"
                ],
                "block_audit_sha256": audit["audit_sha256"],
                "prior_failed_attempt_sha256s": [
                    item["failed_attempt_sha256"] for item in prior_failures
                ],
                "infrastructure_attempts": infrastructure_attempts,
            }
        )
    if require_complete and tuple(sorted(observed_blocks)) != tuple(
        sorted(expected_blocks)
    ):
        raise FinBenchConfirmatoryPhaseError(
            f"{phase} does not cover its frozen measurement blocks"
        )
    if len(request_hashes) != 1 or len(authority_hashes) != 1:
        raise FinBenchConfirmatoryPhaseError(
            "accepted blocks do not share one execution authority"
        )
    return sorted(result, key=lambda item: expected_blocks.index(item["block_id"]))


def build_finbench_confirmatory_accepted_block(
    *,
    execution_context: Mapping[str, Any],
    raw_measurements: Mapping[str, Any],
    block_audit: Mapping[str, Any],
    prior_failed_attempts: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Package one independently audited block for phase assembly."""

    context = validate_finbench_confirmatory_block_execution_envelope(
        execution_context
    )
    attempt = context["block_attempt"]
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_ACCEPTED_BLOCK_SCHEMA_VERSION,
        "execution_context": copy.deepcopy(dict(execution_context)),
        "raw_measurements": copy.deepcopy(dict(raw_measurements)),
        "block_audit": copy.deepcopy(dict(block_audit)),
        "prior_failed_attempts": [
            copy.deepcopy(dict(item)) for item in prior_failed_attempts
        ],
    }
    body["accepted_block_sha256"] = content_hash(body)
    _accepted_blocks(
        [body],
        schedule=context["schedule"],
        phase=str(attempt["phase"]),
        require_complete=False,
    )
    return body


def extract_finbench_confirmatory_training_observations(
    accepted_blocks: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Keep only block-paired successful costs; never impute a timeout."""

    by_query: dict[str, dict[str, dict[int, tuple[Mapping[str, Any], Mapping[str, Any]]]]] = {}
    timeout_count = 0
    for block in accepted_blocks:
        attempt_by_identity = {
            str(item["scheduled_identity"]): item for item in block["attempt"]["measurements"]
        }
        for raw in block["measurements"]:
            expected = attempt_by_identity[str(raw["scheduled_identity"])]
            query_id = str(expected["query_id"])
            strategy = str(expected["physical_strategy"])
            block_index = int(
                str(block["block_id"]).rsplit("-", maxsplit=1)[-1]
            )
            if raw.get("outcome") == "query_timeout":
                timeout_count += 1
            elif raw.get("outcome") != "success":
                raise FinBenchConfirmatoryPhaseError(
                    "training block contains a non-method failure"
                )
            by_query.setdefault(query_id, {}).setdefault(strategy, {})[
                block_index
            ] = (expected, raw)
    observations: list[dict[str, Any]] = []
    dropped_unpaired = 0
    minimum_paired = 7
    for query_id in sorted(by_query):
        strategies = by_query[query_id]
        if len(strategies) != 2:
            raise FinBenchConfirmatoryPhaseError(
                "training query physical pair changed"
            )
        shared = set.intersection(
            *(
                {
                    block_index
                    for block_index, (_expected, raw) in values.items()
                    if raw.get("outcome") == "success"
                }
                for values in strategies.values()
            )
        )
        minimum_paired = min(minimum_paired, len(shared))
        dropped_unpaired += 14 - 2 * len(shared)
        if len(shared) < 4:
            raise FinBenchConfirmatoryPhaseError(
                f"fewer than four paired successful blocks for {query_id}"
            )
        for strategy in sorted(strategies):
            repetitions = []
            family_id: str | None = None
            for block_index in sorted(shared):
                expected, raw = strategies[strategy][block_index]
                family_id = str(expected["family_id"])
                repetitions.append(
                    {
                        "repetition_id": str(expected["scheduled_identity"]),
                        "block_index": block_index,
                        "order_position": int(expected["order_position"]),
                        "elapsed_ms": float(raw["elapsed_ms"]),
                        "total_bytes_moved": int(raw["total_bytes_moved"]),
                        "total_remote_calls": int(raw["total_remote_calls"]),
                        "execution_success": True,
                        "exact_answer": None,
                    }
                )
            observations.append(
                {
                    "query_id": query_id,
                    "family_id": family_id,
                    "physical_strategy": strategy,
                    "repetitions": repetitions,
                }
            )
    summary = {
        "query_count": len(by_query),
        "plan_observation_count": len(observations),
        "query_timeout_count": timeout_count,
        "dropped_unpaired_plan_outcomes": dropped_unpaired,
        "minimum_paired_successful_blocks_per_query": minimum_paired,
        "missing_measurements": "no_imputation",
        "current_confirmatory_query_oracle_opened": False,
    }
    return observations, summary


def build_finbench_confirmatory_training_phase(
    *,
    workload_root: str | Path,
    schedule: Mapping[str, Any],
    selection_admission: Mapping[str, Any],
    accepted_blocks: Sequence[Mapping[str, Any]],
    measurement_source_id: str,
    policy: Mapping[str, Any] | str | Path = DEFAULT_POLICY_PATH,
) -> dict[str, Any]:
    frozen = _schedule(schedule)
    admission = validate_finbench_confirmatory_selection_admission(
        selection_admission,
        workload_sha256=str(frozen["workload_sha256"]),
    )
    blocks = _accepted_blocks(
        accepted_blocks,
        schedule=frozen,
        phase="crossfit_training_measurement",
    )
    observations, outcome_summary = (
        extract_finbench_confirmatory_training_observations(blocks)
    )
    suite = build_finbench_confirmatory_crossfit_predictions(
        workload_root=workload_root,
        raw_observations=observations,
        measurement_source_id=measurement_source_id,
        policy=policy,
        selection_admission=admission,
    ).to_dict()
    family_seal = build_finbench_confirmatory_family_selection_seal(
        schedule=frozen,
        crossfit_prediction_suite=suite,
    )
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_TRAINING_PHASE_SCHEMA_VERSION,
        "schedule_sha256": frozen["schedule_sha256"],
        "workload_sha256": frozen["workload_sha256"],
        "selection_admission_sha256": admission[
            "selection_admission_sha256"
        ],
        "accepted_blocks": [
            {
                key: item[key]
                for key in (
                    "block_id",
                    "execution_context_sha256",
                    "raw_measurements_sha256",
                    "block_audit_sha256",
                    "prior_failed_attempt_sha256s",
                )
            }
            for item in blocks
        ],
        "outcome_summary": outcome_summary,
        "crossfit_prediction_suite": suite,
        "family_selection_seal": family_seal,
        "current_query_profile_calls": 0,
        "current_confirmatory_query_oracle_opened": False,
        "final_confirmatory_oracle_is_authoritative": True,
        "automatic_retries": 0,
        "paper_result": False,
    }
    body["training_phase_sha256"] = content_hash(body)
    return body


def _profile_projection(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "scheduled_identity": raw["scheduled_identity"],
        "attempt_id": raw["attempt_id"],
        "outcome": raw["outcome"],
        "elapsed_ms": raw["elapsed_ms"],
        "total_bytes_moved": raw["total_bytes_moved"],
        "total_remote_calls": raw["total_remote_calls"],
        "exact_answer": raw["exact_answer"],
        "physical_strategy": raw["physical_strategy"],
    }


def build_finbench_confirmatory_profile_phase(
    *,
    schedule: Mapping[str, Any],
    accepted_blocks: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    frozen = _schedule(schedule)
    blocks = _accepted_blocks(
        accepted_blocks,
        schedule=frozen,
        phase="current_query_profile_acquisition",
    )
    measurements = [
        _profile_projection(item) for item in blocks[0]["measurements"]
    ]
    seal = build_finbench_confirmatory_profile_selection_seal(
        schedule=frozen,
        profile_measurements=measurements,
    )
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_PROFILE_PHASE_SCHEMA_VERSION,
        "schedule_sha256": frozen["schedule_sha256"],
        "workload_sha256": frozen["workload_sha256"],
        "accepted_block": {
            key: blocks[0][key]
            for key in (
                "block_id",
                "execution_context_sha256",
                "raw_measurements_sha256",
                "block_audit_sha256",
                "prior_failed_attempt_sha256s",
            )
        },
        "profile_selection_seal": seal,
        "profile_acquisition_plan_runs": 96,
        "current_confirmatory_query_oracle_opened": False,
        "final_confirmatory_oracle_is_authoritative": True,
        "automatic_retries": 0,
        "paper_result": False,
    }
    body["profile_phase_sha256"] = content_hash(body)
    return body


def _read_json(path: str | Path, *, name: str) -> dict[str, Any]:
    selected = Path(path)
    if selected.is_symlink() or not selected.is_file():
        raise FinBenchConfirmatoryPhaseError(
            f"{name} must be a regular non-symbolic-link file"
        )
    try:
        value = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinBenchConfirmatoryPhaseError(f"{name} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise FinBenchConfirmatoryPhaseError(f"{name} must contain an object")
    return value


def _write_json(path: str | Path, value: Mapping[str, Any]) -> Path:
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


def _accepted_files(paths: Sequence[str]) -> list[dict[str, Any]]:
    return [
        _read_json(path, name=f"accepted block {index}")
        for index, path in enumerate(paths, start=1)
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    pack = commands.add_parser("pack")
    pack.add_argument("--execution-context", required=True)
    pack.add_argument("--raw-measurements", required=True)
    pack.add_argument("--block-audit", required=True)
    pack.add_argument("--prior-execution-context")
    pack.add_argument("--prior-raw-measurements")
    pack.add_argument("--prior-block-audit")
    pack.add_argument("--output", required=True)

    training = commands.add_parser("training")
    training.add_argument("--workload-root", required=True)
    training.add_argument("--schedule", required=True)
    training.add_argument("--selection-admission", required=True)
    training.add_argument("--accepted-block", action="append", required=True)
    training.add_argument("--measurement-source-id", required=True)
    training.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    training.add_argument("--output", required=True)

    profile = commands.add_parser("profile")
    profile.add_argument("--schedule", required=True)
    profile.add_argument("--accepted-block", action="append", required=True)
    profile.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "pack":
            prior_paths = (
                args.prior_execution_context,
                args.prior_raw_measurements,
                args.prior_block_audit,
            )
            if any(prior_paths) and not all(prior_paths):
                raise FinBenchConfirmatoryPhaseError(
                    "prior failure requires context, raw measurements, and audit"
                )
            prior_failed_attempts = (
                [
                    build_finbench_confirmatory_failed_attempt_bundle(
                        execution_context=_read_json(
                            args.prior_execution_context,
                            name="prior execution context",
                        ),
                        raw_measurements=_read_json(
                            args.prior_raw_measurements,
                            name="prior raw measurements",
                        ),
                        block_audit=_read_json(
                            args.prior_block_audit,
                            name="prior block audit",
                        ),
                    )
                ]
                if all(prior_paths)
                else []
            )
            result = build_finbench_confirmatory_accepted_block(
                execution_context=_read_json(
                    args.execution_context, name="execution context"
                ),
                raw_measurements=_read_json(
                    args.raw_measurements, name="raw measurements"
                ),
                block_audit=_read_json(args.block_audit, name="block audit"),
                prior_failed_attempts=prior_failed_attempts,
            )
            identifier = result["accepted_block_sha256"]
        elif args.command == "training":
            result = build_finbench_confirmatory_training_phase(
                workload_root=args.workload_root,
                schedule=_read_json(args.schedule, name="measurement schedule"),
                selection_admission=_read_json(
                    args.selection_admission, name="selection admission"
                ),
                accepted_blocks=_accepted_files(args.accepted_block),
                measurement_source_id=args.measurement_source_id,
                policy=args.policy,
            )
            identifier = result["training_phase_sha256"]
        else:
            result = build_finbench_confirmatory_profile_phase(
                schedule=_read_json(args.schedule, name="measurement schedule"),
                accepted_blocks=_accepted_files(args.accepted_block),
            )
            identifier = result["profile_phase_sha256"]
        output = _write_json(args.output, result)
    except (FileExistsError, OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": "success",
                "command": args.command,
                "identifier": identifier,
                "output": str(output.resolve()),
                "paper_result": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
