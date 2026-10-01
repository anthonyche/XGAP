"""Bind FinBench confirmatory execution to explicit author authority.

The author-selected population and frozen schedule deliberately do not grant
permission to spend the confirmatory measurement budget.  This module creates
the missing, content-addressed boundary: an execution request reconstructed
from a successful independent freeze audit, a separately signed authority
record, and one immutable attempt specification for each frozen measurement
block.  It performs no backend, profile, model, ontology, or oracle call.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_confirmatory_analysis import (
    FINBENCH_CONFIRMATORY_FAMILY_SELECTION_SCHEMA_VERSION,
    FINBENCH_CONFIRMATORY_PROFILE_SELECTION_SCHEMA_VERSION,
    FinBenchConfirmatoryAnalysisError,
    _schedule,
    _selection_map,
)
from xgap.experiments.m15_finbench_confirmatory_freeze_evidence import (
    FINBENCH_CONFIRMATORY_FREEZE_AUDIT_SCHEMA_VERSION,
)
from xgap.experiments.m15_finbench_confirmatory_freeze_job import (
    FINBENCH_CONFIRMATORY_FREEZE_MANIFEST_SCHEMA_VERSION,
)
from xgap.experiments.m15_finbench_confirmatory_selection_admission import (
    validate_finbench_confirmatory_selection_admission,
)


FINBENCH_CONFIRMATORY_EXECUTION_REQUEST_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-execution-request-v1"
)
FINBENCH_CONFIRMATORY_EXECUTION_AUTHORITY_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-execution-authority-v1"
)
FINBENCH_CONFIRMATORY_BLOCK_ATTEMPT_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-block-attempt-v1"
)
FINBENCH_CONFIRMATORY_BLOCK_EXECUTION_CONTEXT_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-block-execution-context-v1"
)

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$")
_EXPECTED_COUNTS = {
    "seen_family_query_count": 32,
    "cold_family_query_count": 16,
    "inferential_query_count": 32,
    "training_plan_runs": 448,
    "profile_acquisition_plan_runs": 96,
    "selected_serving_plan_runs": 672,
    "evaluation_shadow_plan_runs": 672,
    "total_plan_runs": 1888,
    "total_backend_calls": 3776,
}
_BLOCK_FIELDS = {
    "crossfit_training_measurement": "crossfit_training_runs",
    "current_query_profile_acquisition": "profile_acquisition_runs",
    "paired_selected_serving": "selected_serving_slots",
    "postselection_shadow_evaluation": "evaluation_shadow_runs",
}


class FinBenchConfirmatoryExecutionError(ValueError):
    """Raised when execution authority or a frozen block binding drifts."""


def _hashed(
    value: Mapping[str, Any], *, hash_field: str, name: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FinBenchConfirmatoryExecutionError(f"{name} must be an object")
    result = copy.deepcopy(dict(value))
    claimed = result.get(hash_field)
    body = {key: item for key, item in result.items() if key != hash_field}
    if not isinstance(claimed, str) or content_hash(body) != claimed:
        raise FinBenchConfirmatoryExecutionError(f"{name} hash mismatch")
    return result


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise FinBenchConfirmatoryExecutionError(f"{name} is not a safe identifier")
    return value


def _validate_freeze(
    *, freeze_manifest: Mapping[str, Any], freeze_audit: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _hashed(
        freeze_manifest, hash_field="manifest_sha256", name="freeze manifest"
    )
    audit = copy.deepcopy(dict(freeze_audit))
    git = manifest.get("git")
    calls = manifest.get("external_call_counts")
    if (
        manifest.get("schema_version")
        != FINBENCH_CONFIRMATORY_FREEZE_MANIFEST_SCHEMA_VERSION
        or manifest.get("status") != "success"
        or not isinstance(git, Mapping)
        or _COMMIT.fullmatch(str(git.get("commit"))) is None
        or git.get("clean") is not True
        or manifest.get("expected_counts") != _EXPECTED_COUNTS
        or manifest.get("confirmatory_workload_compilation_authorized") is not True
        or manifest.get("confirmatory_execution_authorized") is not False
        or manifest.get("automatic_retries") != 0
        or manifest.get("paper_result") is not False
        or calls
        != {
            "backend_calls": 0,
            "current_query_profile_calls": 0,
            "llm_calls": 0,
            "ontology_service_calls": 0,
        }
    ):
        raise FinBenchConfirmatoryExecutionError("freeze manifest boundary changed")
    if (
        audit.get("schema_version")
        != FINBENCH_CONFIRMATORY_FREEZE_AUDIT_SCHEMA_VERSION
        or audit.get("success") is not True
        or audit.get("failed_check_ids") != []
        or audit.get("run_tree_mutated") is not False
        or audit.get("expected_commit") != git["commit"]
        or audit.get("check_count") != 44
        or not isinstance(audit.get("checks"), list)
        or len(audit["checks"]) != 44
        or any(
            not isinstance(item, Mapping) or item.get("passed") is not True
            for item in audit["checks"]
        )
    ):
        raise FinBenchConfirmatoryExecutionError(
            "independent freeze audit is not accepted"
        )
    return manifest, audit


def build_finbench_confirmatory_execution_request(
    *,
    freeze_manifest: Mapping[str, Any],
    freeze_audit: Mapping[str, Any],
    selection_admission: Mapping[str, Any],
    runner_commit: str,
) -> dict[str, Any]:
    """Create a non-authorizing request for the exact confirmatory campaign."""

    if _COMMIT.fullmatch(runner_commit) is None:
        raise FinBenchConfirmatoryExecutionError(
            "runner_commit must be a full lowercase Git commit"
        )
    manifest, audit = _validate_freeze(
        freeze_manifest=freeze_manifest, freeze_audit=freeze_audit
    )
    admission = validate_finbench_confirmatory_selection_admission(
        selection_admission,
        workload_sha256=str(manifest["workload_sha256"]),
    )
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_EXECUTION_REQUEST_SCHEMA_VERSION,
        "freeze_manifest_sha256": manifest["manifest_sha256"],
        "freeze_audit_content_sha256": content_hash(audit),
        "freeze_producer_commit": manifest["git"]["commit"],
        "runner_commit": runner_commit,
        "schedule_sha256": manifest["schedule_sha256"],
        "workload_sha256": manifest["workload_sha256"],
        "selection_admission_sha256": admission[
            "selection_admission_sha256"
        ],
        "selection_exactness_semantics": admission[
            "training_exactness_semantics"
        ],
        "current_confirmatory_query_oracle_opened": False,
        "final_confirmatory_oracle_is_authoritative": True,
        "author_selection_sha256": manifest["author_selection_sha256"],
        "population_approval_sha256": manifest["population_approval_sha256"],
        "execution_scope": {
            "measurement_block_count": 22,
            "total_plan_runs": 1888,
            "maximum_backend_calls": 3776,
            "backend_timeout_seconds": 60,
            "automatic_retries": 0,
            "infrastructure_replacement_limit_per_block": 1,
            "fresh_job_owned_services_per_measurement_block": True,
            "query_timeout_is_method_outcome": True,
            "query_timeout_is_not_replacement_eligible": True,
        },
        "authority_required": "explicit_author_decision_after_freeze_audit",
        "authorization_status": "awaiting_explicit_author_decision",
        "confirmatory_execution_authorized": False,
        "oracle_inputs": [],
        "paper_result": False,
    }
    body["execution_request_sha256"] = content_hash(body)
    return body


def build_finbench_confirmatory_execution_authority(
    *,
    execution_request: Mapping[str, Any],
    authority_source_id: str,
    decision: str,
) -> dict[str, Any]:
    """Bind an explicit author decision to one exact execution request.

    Calling this function is appropriate only after the author has explicitly
    authorized the measurement run.  Population selection alone is not that
    authorization.
    """

    request = validate_finbench_confirmatory_execution_request(execution_request)
    source = _safe_id(authority_source_id, name="authority_source_id")
    if decision != "authorize_exact_confirmatory_execution":
        raise FinBenchConfirmatoryExecutionError(
            "decision does not authorize exact confirmatory execution"
        )
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_EXECUTION_AUTHORITY_SCHEMA_VERSION,
        "execution_request_sha256": request["execution_request_sha256"],
        "authority_source_id": source,
        "decision": decision,
        "authorized_scope": copy.deepcopy(request["execution_scope"]),
        "single_campaign_only": True,
        "scope_expansion_requires_new_authority": True,
        "confirmatory_execution_authorized": True,
        "paper_result": False,
    }
    body["execution_authority_sha256"] = content_hash(body)
    return body


def validate_finbench_confirmatory_execution_request(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    request = _hashed(
        value, hash_field="execution_request_sha256", name="execution request"
    )
    if (
        request.get("schema_version")
        != FINBENCH_CONFIRMATORY_EXECUTION_REQUEST_SCHEMA_VERSION
        or _COMMIT.fullmatch(str(request.get("freeze_producer_commit"))) is None
        or _COMMIT.fullmatch(str(request.get("runner_commit"))) is None
        or _SHA256.fullmatch(
            str(request.get("selection_admission_sha256"))
        )
        is None
        or request.get("selection_exactness_semantics")
        != "plan_family_semantic_contract_not_current_query_oracle"
        or request.get("current_confirmatory_query_oracle_opened") is not False
        or request.get("final_confirmatory_oracle_is_authoritative") is not True
        or request.get("execution_scope")
        != {
            "measurement_block_count": 22,
            "total_plan_runs": 1888,
            "maximum_backend_calls": 3776,
            "backend_timeout_seconds": 60,
            "automatic_retries": 0,
            "infrastructure_replacement_limit_per_block": 1,
            "fresh_job_owned_services_per_measurement_block": True,
            "query_timeout_is_method_outcome": True,
            "query_timeout_is_not_replacement_eligible": True,
        }
        or request.get("authority_required")
        != "explicit_author_decision_after_freeze_audit"
        or request.get("authorization_status")
        != "awaiting_explicit_author_decision"
        or request.get("confirmatory_execution_authorized") is not False
        or request.get("oracle_inputs") != []
        or request.get("paper_result") is not False
    ):
        raise FinBenchConfirmatoryExecutionError("execution request boundary changed")
    return request


def validate_finbench_confirmatory_execution_authority(
    *, execution_request: Mapping[str, Any], execution_authority: Mapping[str, Any]
) -> dict[str, Any]:
    request = validate_finbench_confirmatory_execution_request(execution_request)
    authority = _hashed(
        execution_authority,
        hash_field="execution_authority_sha256",
        name="execution authority",
    )
    if (
        authority.get("schema_version")
        != FINBENCH_CONFIRMATORY_EXECUTION_AUTHORITY_SCHEMA_VERSION
        or authority.get("execution_request_sha256")
        != request["execution_request_sha256"]
        or _SAFE_ID.fullmatch(str(authority.get("authority_source_id"))) is None
        or authority.get("decision") != "authorize_exact_confirmatory_execution"
        or authority.get("authorized_scope") != request["execution_scope"]
        or authority.get("single_campaign_only") is not True
        or authority.get("scope_expansion_requires_new_authority") is not True
        or authority.get("confirmatory_execution_authorized") is not True
        or authority.get("paper_result") is not False
    ):
        raise FinBenchConfirmatoryExecutionError("execution authority boundary changed")
    return authority


def validate_finbench_confirmatory_block_attempt(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one compiled block without opening the schedule or an oracle."""

    attempt = _hashed(
        value,
        hash_field="block_attempt_sha256",
        name="block attempt",
    )
    identity_body = {
        key: item
        for key, item in attempt.items()
        if key not in {"attempt_id", "block_attempt_sha256"}
    }
    if attempt.get("attempt_id") != (
        "finbench-confirmatory-attempt-" + content_hash(identity_body)[:24]
    ):
        raise FinBenchConfirmatoryExecutionError("block attempt identity mismatch")
    measurements = attempt.get("measurements")
    phase = attempt.get("phase")
    expected_count = 64 if phase == "crossfit_training_measurement" else 96
    if (
        attempt.get("schema_version")
        != FINBENCH_CONFIRMATORY_BLOCK_ATTEMPT_SCHEMA_VERSION
        or _COMMIT.fullmatch(str(attempt.get("runner_commit"))) is None
        or phase not in _BLOCK_FIELDS
        or not isinstance(measurements, list)
        or len(measurements) != expected_count
        or len(measurements) != attempt.get("expected_plan_run_count")
        or attempt.get("maximum_backend_calls") != len(measurements) * 2
        or attempt.get("backend_timeout_seconds") != 60
        or attempt.get("fresh_job_owned_services") is not True
        or attempt.get("automatic_retries") != 0
        or attempt.get("valid_measurement_count_before_execution") != 0
        or attempt.get("query_timeout_is_method_outcome") is not True
        or attempt.get("query_timeout_is_not_replacement_eligible") is not True
        or attempt.get("oracle_inputs") != []
        or attempt.get("paper_result") is not False
    ):
        raise FinBenchConfirmatoryExecutionError("block attempt boundary changed")
    identities = [
        item.get("scheduled_identity")
        for item in measurements
        if isinstance(item, Mapping)
    ]
    if len(identities) != len(measurements) or any(
        not isinstance(item, str) or not item for item in identities
    ) or len(set(identities)) != len(identities):
        raise FinBenchConfirmatoryExecutionError(
            "block measurement identities changed"
        )
    return attempt


def _serving_maps(
    *,
    schedule: Mapping[str, Any],
    family_selection_seal: Mapping[str, Any] | None,
    profile_selection_seal: Mapping[str, Any] | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    schedule_hash = str(schedule["schedule_sha256"])
    if family_selection_seal is None or profile_selection_seal is None:
        raise FinBenchConfirmatoryExecutionError(
            "serving block requires both pre-execution selection seals"
        )
    try:
        _family, family = _selection_map(
            family_selection_seal,
            schema_version=FINBENCH_CONFIRMATORY_FAMILY_SELECTION_SCHEMA_VERSION,
            schedule_hash=schedule_hash,
            name="family selection seal",
        )
        _profile, profile = _selection_map(
            profile_selection_seal,
            schema_version=FINBENCH_CONFIRMATORY_PROFILE_SELECTION_SCHEMA_VERSION,
            schedule_hash=schedule_hash,
            name="profile selection seal",
        )
    except FinBenchConfirmatoryAnalysisError as exc:
        raise FinBenchConfirmatoryExecutionError(str(exc)) from exc
    return family, profile


def compile_finbench_confirmatory_block_attempt(
    *,
    schedule: Mapping[str, Any],
    execution_request: Mapping[str, Any],
    execution_authority: Mapping[str, Any],
    measurement_block_id: str,
    attempt_index: int = 1,
    replacement_of_attempt_id: str | None = None,
    family_selection_seal: Mapping[str, Any] | None = None,
    profile_selection_seal: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve one frozen block without executing or opening an oracle."""

    try:
        frozen = _schedule(schedule)
    except FinBenchConfirmatoryAnalysisError as exc:
        raise FinBenchConfirmatoryExecutionError(str(exc)) from exc
    request = validate_finbench_confirmatory_execution_request(execution_request)
    authority = validate_finbench_confirmatory_execution_authority(
        execution_request=request, execution_authority=execution_authority
    )
    block_id = _safe_id(measurement_block_id, name="measurement_block_id")
    if (
        request["schedule_sha256"] != frozen["schedule_sha256"]
        or request["workload_sha256"] != frozen["workload_sha256"]
        or block_id not in frozen["measurement_block_ids"]
    ):
        raise FinBenchConfirmatoryExecutionError(
            "execution request does not bind the frozen block"
        )
    if attempt_index not in {1, 2}:
        raise FinBenchConfirmatoryExecutionError("attempt index exceeds replacement limit")
    if (attempt_index == 1 and replacement_of_attempt_id is not None) or (
        attempt_index == 2
        and (
            replacement_of_attempt_id is None
            or _SAFE_ID.fullmatch(replacement_of_attempt_id) is None
        )
    ):
        raise FinBenchConfirmatoryExecutionError("replacement provenance is invalid")
    phase_matches = [
        phase
        for phase, field in _BLOCK_FIELDS.items()
        if any(
            isinstance(item, Mapping)
            and item.get("measurement_block_id") == block_id
            for item in frozen[field]
        )
    ]
    if len(phase_matches) != 1:
        raise FinBenchConfirmatoryExecutionError("measurement block phase is ambiguous")
    phase = phase_matches[0]
    scheduled = [
        copy.deepcopy(dict(item))
        for item in frozen[_BLOCK_FIELDS[phase]]
        if item["measurement_block_id"] == block_id
    ]
    family: dict[str, dict[str, Any]] = {}
    profile: dict[str, dict[str, Any]] = {}
    if phase == "paired_selected_serving":
        family, profile = _serving_maps(
            schedule=frozen,
            family_selection_seal=family_selection_seal,
            profile_selection_seal=profile_selection_seal,
        )
    resolved: list[dict[str, Any]] = []
    for item in scheduled:
        method = item.get("method_id")
        query_id = str(item["query_id"])
        if method == "current_query_dual_profile":
            strategy = profile[query_id]["selected_physical_strategy"]
        elif method in {
            "family_memory_zero_profile",
            "predeclared_family_fallback",
        }:
            if family[query_id].get("method_id") != method:
                raise FinBenchConfirmatoryExecutionError(
                    "family method stratum changed"
                )
            strategy = family[query_id]["selected_physical_strategy"]
        else:
            strategy = item.get("physical_strategy")
        if not isinstance(strategy, str) or not strategy:
            raise FinBenchConfirmatoryExecutionError(
                "physical strategy was not resolved before execution"
            )
        resolved.append(
            {
                "scheduled_identity": item.get("run_id") or item.get("slot_id"),
                "query_id": query_id,
                "family_id": item["family_id"],
                "evaluation_stratum": item["evaluation_stratum"],
                "method_id": method,
                "physical_strategy": strategy,
                "query_position": item["query_position"],
                "order_position": item["order_position"],
                "selection_input": item["selection_input"],
                "current_query_profile": item["current_query_profile"],
                "memory_write_allowed": item["memory_write_allowed"],
                "oracle_inputs": [],
            }
        )
    expected = 64 if phase == "crossfit_training_measurement" else 96
    if len(resolved) != expected:
        raise FinBenchConfirmatoryExecutionError("measurement block size changed")
    attempt_body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_BLOCK_ATTEMPT_SCHEMA_VERSION,
        "schedule_sha256": frozen["schedule_sha256"],
        "workload_sha256": frozen["workload_sha256"],
        "execution_request_sha256": request["execution_request_sha256"],
        "execution_authority_sha256": authority["execution_authority_sha256"],
        "runner_commit": request["runner_commit"],
        "measurement_block_id": block_id,
        "phase": phase,
        "attempt_index": attempt_index,
        "replacement_of_attempt_id": replacement_of_attempt_id,
        "measurements": resolved,
        "expected_plan_run_count": len(resolved),
        "maximum_backend_calls": len(resolved) * 2,
        "backend_timeout_seconds": 60,
        "fresh_job_owned_services": True,
        "automatic_retries": 0,
        "valid_measurement_count_before_execution": 0,
        "query_timeout_is_method_outcome": True,
        "query_timeout_is_not_replacement_eligible": True,
        "oracle_inputs": [],
        "paper_result": False,
    }
    attempt_body["attempt_id"] = (
        "finbench-confirmatory-attempt-" + content_hash(attempt_body)[:24]
    )
    attempt_body["block_attempt_sha256"] = content_hash(attempt_body)
    return attempt_body


def validate_finbench_confirmatory_block_execution_context(
    *,
    block_attempt: Mapping[str, Any],
    schedule: Mapping[str, Any],
    execution_request: Mapping[str, Any],
    execution_authority: Mapping[str, Any],
    family_selection_seal: Mapping[str, Any] | None = None,
    profile_selection_seal: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Recompile a block and reject any attempt minted outside its authority."""

    attempt = validate_finbench_confirmatory_block_attempt(block_attempt)
    rebuilt = compile_finbench_confirmatory_block_attempt(
        schedule=schedule,
        execution_request=execution_request,
        execution_authority=execution_authority,
        measurement_block_id=str(attempt["measurement_block_id"]),
        attempt_index=int(attempt["attempt_index"]),
        replacement_of_attempt_id=attempt.get("replacement_of_attempt_id"),
        family_selection_seal=family_selection_seal,
        profile_selection_seal=profile_selection_seal,
    )
    if rebuilt != attempt:
        raise FinBenchConfirmatoryExecutionError(
            "block attempt is not the exact authorized schedule projection"
        )
    return attempt


def build_finbench_confirmatory_block_execution_envelope(
    *,
    block_attempt: Mapping[str, Any],
    schedule: Mapping[str, Any],
    execution_request: Mapping[str, Any],
    execution_authority: Mapping[str, Any],
    family_selection_seal: Mapping[str, Any] | None = None,
    profile_selection_seal: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Package every authority input required to execute exactly one block."""

    attempt = validate_finbench_confirmatory_block_execution_context(
        block_attempt=block_attempt,
        schedule=schedule,
        execution_request=execution_request,
        execution_authority=execution_authority,
        family_selection_seal=family_selection_seal,
        profile_selection_seal=profile_selection_seal,
    )
    body: dict[str, Any] = {
        "schema_version": (
            FINBENCH_CONFIRMATORY_BLOCK_EXECUTION_CONTEXT_SCHEMA_VERSION
        ),
        "block_attempt": attempt,
        "schedule": copy.deepcopy(dict(schedule)),
        "execution_request": copy.deepcopy(dict(execution_request)),
        "execution_authority": copy.deepcopy(dict(execution_authority)),
        "family_selection_seal": (
            copy.deepcopy(dict(family_selection_seal))
            if family_selection_seal is not None
            else None
        ),
        "profile_selection_seal": (
            copy.deepcopy(dict(profile_selection_seal))
            if profile_selection_seal is not None
            else None
        ),
        "oracle_inputs": [],
        "paper_result": False,
    }
    body["execution_context_sha256"] = content_hash(body)
    return body


def validate_finbench_confirmatory_block_execution_envelope(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a self-contained block envelope before services start."""

    context = _hashed(
        value,
        hash_field="execution_context_sha256",
        name="block execution context",
    )
    if (
        context.get("schema_version")
        != FINBENCH_CONFIRMATORY_BLOCK_EXECUTION_CONTEXT_SCHEMA_VERSION
        or context.get("oracle_inputs") != []
        or context.get("paper_result") is not False
        or not isinstance(context.get("block_attempt"), Mapping)
        or not isinstance(context.get("schedule"), Mapping)
        or not isinstance(context.get("execution_request"), Mapping)
        or not isinstance(context.get("execution_authority"), Mapping)
        or (
            context.get("family_selection_seal") is not None
            and not isinstance(context.get("family_selection_seal"), Mapping)
        )
        or (
            context.get("profile_selection_seal") is not None
            and not isinstance(context.get("profile_selection_seal"), Mapping)
        )
    ):
        raise FinBenchConfirmatoryExecutionError(
            "block execution context boundary changed"
        )
    validate_finbench_confirmatory_block_execution_context(
        block_attempt=context["block_attempt"],
        schedule=context["schedule"],
        execution_request=context["execution_request"],
        execution_authority=context["execution_authority"],
        family_selection_seal=context.get("family_selection_seal"),
        profile_selection_seal=context.get("profile_selection_seal"),
    )
    return context


def block_ids_for_phase(
    schedule: Mapping[str, Any], phase: str
) -> tuple[str, ...]:
    """Return the immutable block order for one measurement phase."""

    if phase not in _BLOCK_FIELDS:
        raise FinBenchConfirmatoryExecutionError("unknown measurement phase")
    try:
        frozen = _schedule(schedule)
    except FinBenchConfirmatoryAnalysisError as exc:
        raise FinBenchConfirmatoryExecutionError(str(exc)) from exc
    values: Sequence[Mapping[str, Any]] = frozen[_BLOCK_FIELDS[phase]]
    return tuple(dict.fromkeys(str(item["measurement_block_id"]) for item in values))


def _read_json_file(path: str | Path, *, name: str) -> dict[str, Any]:
    selected = Path(path)
    if selected.is_symlink() or not selected.is_file():
        raise FinBenchConfirmatoryExecutionError(
            f"{name} must be a regular non-symbolic-link file"
        )
    try:
        value = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FinBenchConfirmatoryExecutionError(
            f"{name} is not valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise FinBenchConfirmatoryExecutionError(f"{name} must contain an object")
    return value


def _write_json_file(path: str | Path, value: Mapping[str, Any]) -> Path:
    selected = Path(path)
    if selected.exists() or selected.is_symlink():
        raise FileExistsError(f"output exists: {selected}")
    selected.parent.mkdir(parents=True, exist_ok=True)
    temporary = selected.with_name(selected.name + f".partial-{os.getpid()}")
    temporary.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, selected)
    return selected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    request = commands.add_parser("request")
    request.add_argument("--freeze-run", required=True)
    request.add_argument("--freeze-audit", required=True)
    request.add_argument("--selection-admission", required=True)
    request.add_argument("--runner-commit", required=True)
    request.add_argument("--output", required=True)

    authorize = commands.add_parser("authorize")
    authorize.add_argument("--request", required=True)
    authorize.add_argument("--authority-source-id", required=True)
    authorize.add_argument(
        "--decision",
        default="authorize_exact_confirmatory_execution",
        choices=("authorize_exact_confirmatory_execution",),
    )
    authorize.add_argument("--output", required=True)

    block = commands.add_parser("block")
    block.add_argument("--schedule", required=True)
    block.add_argument("--request", required=True)
    block.add_argument("--authority", required=True)
    block.add_argument("--measurement-block-id", required=True)
    block.add_argument("--attempt-index", type=int, default=1)
    block.add_argument("--replacement-of-attempt-id")
    block.add_argument("--family-selection-seal")
    block.add_argument("--profile-selection-seal")
    block.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "request":
            freeze_root = Path(args.freeze_run)
            manifest = _read_json_file(
                freeze_root / "run_manifest.json", name="freeze manifest"
            )
            audit = _read_json_file(args.freeze_audit, name="freeze audit")
            admission = _read_json_file(
                args.selection_admission, name="selection admission"
            )
            result = build_finbench_confirmatory_execution_request(
                freeze_manifest=manifest,
                freeze_audit=audit,
                selection_admission=admission,
                runner_commit=args.runner_commit,
            )
            identifier = result["execution_request_sha256"]
        elif args.command == "authorize":
            request = _read_json_file(args.request, name="execution request")
            result = build_finbench_confirmatory_execution_authority(
                execution_request=request,
                authority_source_id=args.authority_source_id,
                decision=args.decision,
            )
            identifier = result["execution_authority_sha256"]
        else:
            schedule = _read_json_file(args.schedule, name="measurement schedule")
            request = _read_json_file(args.request, name="execution request")
            authority = _read_json_file(args.authority, name="execution authority")
            family = (
                _read_json_file(args.family_selection_seal, name="family selection seal")
                if args.family_selection_seal
                else None
            )
            profile = (
                _read_json_file(args.profile_selection_seal, name="profile selection seal")
                if args.profile_selection_seal
                else None
            )
            attempt = compile_finbench_confirmatory_block_attempt(
                schedule=schedule,
                execution_request=request,
                execution_authority=authority,
                measurement_block_id=args.measurement_block_id,
                attempt_index=args.attempt_index,
                replacement_of_attempt_id=args.replacement_of_attempt_id,
                family_selection_seal=family,
                profile_selection_seal=profile,
            )
            result = build_finbench_confirmatory_block_execution_envelope(
                block_attempt=attempt,
                schedule=schedule,
                execution_request=request,
                execution_authority=authority,
                family_selection_seal=family,
                profile_selection_seal=profile,
            )
            identifier = result["execution_context_sha256"]
        output = _write_json_file(args.output, result)
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
