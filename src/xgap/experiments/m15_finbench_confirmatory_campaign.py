"""Stage and assemble the authorized FinBench confirmatory campaign.

This module is deliberately a file-backed state machine rather than a loop
that talks to the databases itself.  Every native Slurm allocation executes
one immutable measurement block.  The coordinator may prepare contexts,
independently audit completed blocks, build result-blind selection seals, and
open the answer oracle only after the complete 22-block schedule is sealed.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_confirmatory_analysis import _schedule
from xgap.experiments.m15_finbench_confirmatory_block_evidence import (
    audit_finbench_confirmatory_block,
)
from xgap.experiments.m15_finbench_confirmatory_execution import (
    block_ids_for_phase,
    build_finbench_confirmatory_block_execution_envelope,
    build_finbench_confirmatory_execution_request,
    compile_finbench_confirmatory_block_attempt,
    validate_finbench_confirmatory_block_execution_envelope,
    validate_finbench_confirmatory_execution_authority,
    validate_finbench_confirmatory_execution_request,
)
from xgap.experiments.m15_finbench_confirmatory_oracle import (
    open_finbench_confirmatory_oracle,
)
from xgap.experiments.m15_finbench_confirmatory_phase import (
    build_finbench_confirmatory_accepted_block,
    build_finbench_confirmatory_failed_attempt_bundle,
    build_finbench_confirmatory_profile_phase,
    build_finbench_confirmatory_training_phase,
)
from xgap.experiments.m15_finbench_confirmatory_selection_admission import (
    validate_finbench_confirmatory_selection_admission,
)
from xgap.experiments.m15_finbench_family_memory import DEFAULT_POLICY_PATH


FINBENCH_CONFIRMATORY_CAMPAIGN_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-campaign-v1"
)
FINBENCH_CONFIRMATORY_SELECTION_CHECKPOINT_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-selection-checkpoint-v1"
)
FINBENCH_CONFIRMATORY_RESULT_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-campaign-result-v1"
)
FINBENCH_CONFIRMATORY_SUBMISSION_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-submission-v1"
)
FINBENCH_CONFIRMATORY_REPLACEMENT_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-replacement-v1"
)

_JOB_ID = re.compile(r"^[1-9][0-9]*(?:_[1-9][0-9]*)?$")
_PHASES = (
    "crossfit_training_measurement",
    "current_query_profile_acquisition",
    "paired_selected_serving",
    "postselection_shadow_evaluation",
)
_PRESELECTION_PHASES = _PHASES[:2]
_POSTSELECTION_PHASES = _PHASES[2:]
_EXPECTED_BLOCK_COUNTS = {
    "crossfit_training_measurement": 7,
    "current_query_profile_acquisition": 1,
    "paired_selected_serving": 7,
    "postselection_shadow_evaluation": 7,
}
_INPUT_FILES = {
    "freeze_manifest": "freeze_manifest.json",
    "freeze_audit": "freeze_audit.json",
    "schedule": "measurement_schedule.json",
    "selection_admission": "selection_admission.json",
    "execution_request": "execution_request.json",
    "execution_authority": "execution_authority.json",
}


class FinBenchConfirmatoryCampaignError(ValueError):
    """Raised when a campaign state or dependency is incomplete."""


def _read(path: str | Path, *, name: str) -> dict[str, Any]:
    selected = Path(path)
    if selected.is_symlink() or not selected.is_file():
        raise FinBenchConfirmatoryCampaignError(
            f"{name} must be a regular non-symbolic-link file"
        )
    try:
        value = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinBenchConfirmatoryCampaignError(
            f"{name} is not valid JSON"
        ) from exc
    if not isinstance(value, Mapping):
        raise FinBenchConfirmatoryCampaignError(
            f"{name} must contain a JSON object"
        )
    return copy.deepcopy(dict(value))


def _write(path: str | Path, value: Mapping[str, Any]) -> Path:
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


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _hashed(
    value: Mapping[str, Any], *, field: str, name: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FinBenchConfirmatoryCampaignError(f"{name} must be an object")
    result = copy.deepcopy(dict(value))
    claimed = result.get(field)
    body = {key: item for key, item in result.items() if key != field}
    if not isinstance(claimed, str) or content_hash(body) != claimed:
        raise FinBenchConfirmatoryCampaignError(f"{name} hash mismatch")
    return result


def _git_state(repo_root: Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    porcelain = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {"commit": commit, "clean": porcelain == ""}


def _block_map(schedule: Mapping[str, Any]) -> dict[str, list[str]]:
    result = {
        phase: list(block_ids_for_phase(schedule, phase)) for phase in _PHASES
    }
    if {
        phase: len(values) for phase, values in result.items()
    } != _EXPECTED_BLOCK_COUNTS:
        raise FinBenchConfirmatoryCampaignError(
            "confirmatory measurement block cardinality changed"
        )
    flattened = [item for phase in _PHASES for item in result[phase]]
    if len(flattened) != 22 or len(set(flattened)) != 22:
        raise FinBenchConfirmatoryCampaignError(
            "confirmatory measurement block identities changed"
        )
    return result


def build_finbench_confirmatory_campaign_manifest(
    *,
    freeze_manifest: Mapping[str, Any],
    freeze_audit: Mapping[str, Any],
    schedule: Mapping[str, Any],
    selection_admission: Mapping[str, Any],
    execution_request: Mapping[str, Any],
    execution_authority: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the complete authority chain and freeze campaign topology."""

    frozen = _schedule(schedule)
    admission = validate_finbench_confirmatory_selection_admission(
        selection_admission,
        workload_sha256=str(frozen["workload_sha256"]),
    )
    request = validate_finbench_confirmatory_execution_request(execution_request)
    authority = validate_finbench_confirmatory_execution_authority(
        execution_request=request,
        execution_authority=execution_authority,
    )
    rebuilt_request = build_finbench_confirmatory_execution_request(
        freeze_manifest=freeze_manifest,
        freeze_audit=freeze_audit,
        selection_admission=admission,
        runner_commit=str(request["runner_commit"]),
    )
    if rebuilt_request != request:
        raise FinBenchConfirmatoryCampaignError(
            "execution request failed freeze reconstruction"
        )
    if (
        request["schedule_sha256"] != frozen["schedule_sha256"]
        or request["workload_sha256"] != frozen["workload_sha256"]
        or request["selection_admission_sha256"]
        != admission["selection_admission_sha256"]
    ):
        raise FinBenchConfirmatoryCampaignError(
            "campaign inputs do not share one frozen workload"
        )
    blocks = _block_map(frozen)
    identity = {
        "schedule_sha256": frozen["schedule_sha256"],
        "workload_sha256": frozen["workload_sha256"],
        "selection_admission_sha256": admission[
            "selection_admission_sha256"
        ],
        "execution_request_sha256": request["execution_request_sha256"],
        "execution_authority_sha256": authority[
            "execution_authority_sha256"
        ],
        "runner_commit": request["runner_commit"],
    }
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_CAMPAIGN_SCHEMA_VERSION,
        "campaign_id": "m15-finbench-confirmatory-" + content_hash(identity)[:20],
        **identity,
        "measurement_blocks": blocks,
        "measurement_block_count": 22,
        "total_plan_runs": 1888,
        "maximum_backend_calls": 3776,
        "staging_order": [
            list(_PRESELECTION_PHASES),
            ["selection_assembly"],
            list(_POSTSELECTION_PHASES),
            ["delayed_oracle"],
            ["independent_campaign_audit"],
        ],
        "fresh_job_owned_services_per_measurement_block": True,
        "current_confirmatory_query_oracle_opened": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    body["campaign_manifest_sha256"] = content_hash(body)
    return body


def _build_context(
    *,
    block_id: str,
    schedule: Mapping[str, Any],
    request: Mapping[str, Any],
    authority: Mapping[str, Any],
    family_selection_seal: Mapping[str, Any] | None = None,
    profile_selection_seal: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    attempt = compile_finbench_confirmatory_block_attempt(
        schedule=schedule,
        execution_request=request,
        execution_authority=authority,
        measurement_block_id=block_id,
        family_selection_seal=family_selection_seal,
        profile_selection_seal=profile_selection_seal,
    )
    return build_finbench_confirmatory_block_execution_envelope(
        block_attempt=attempt,
        schedule=schedule,
        execution_request=request,
        execution_authority=authority,
        family_selection_seal=family_selection_seal,
        profile_selection_seal=profile_selection_seal,
    )


def initialize_finbench_confirmatory_campaign_workspace(
    *,
    campaign_root: str | Path,
    freeze_run_root: str | Path,
    freeze_audit_path: str | Path,
    selection_admission_path: str | Path,
    execution_request_path: str | Path,
    execution_authority_path: str | Path,
    repo_root: str | Path,
) -> dict[str, Any]:
    """Create an immutable preselection workspace before Slurm submission."""

    root = Path(campaign_root)
    if root.exists() or root.is_symlink():
        raise FileExistsError(f"campaign root exists: {root}")
    freeze_root = Path(freeze_run_root)
    repository = Path(repo_root).resolve()
    if (
        not (repository / "pyproject.toml").is_file()
        or freeze_root.is_symlink()
        or not freeze_root.is_dir()
    ):
        raise FinBenchConfirmatoryCampaignError(
            "repository or freeze run is missing or unsafe"
        )
    git = _git_state(repository)
    freeze_manifest = _read(
        freeze_root / "run_manifest.json", name="freeze manifest"
    )
    freeze_audit = _read(freeze_audit_path, name="freeze audit")
    schedule = _read(
        freeze_root / "measurement_schedule.json", name="measurement schedule"
    )
    admission = _read(selection_admission_path, name="selection admission")
    request = _read(execution_request_path, name="execution request")
    authority = _read(execution_authority_path, name="execution authority")
    manifest = build_finbench_confirmatory_campaign_manifest(
        freeze_manifest=freeze_manifest,
        freeze_audit=freeze_audit,
        schedule=schedule,
        selection_admission=admission,
        execution_request=request,
        execution_authority=authority,
    )
    if git != {"commit": manifest["runner_commit"], "clean": True}:
        raise FinBenchConfirmatoryCampaignError(
            "campaign initialization requires the exact clean runner commit"
        )
    root = root.resolve()
    root.mkdir(parents=True)
    inputs = root / "inputs"
    inputs.mkdir()
    values = {
        "freeze_manifest": freeze_manifest,
        "freeze_audit": freeze_audit,
        "schedule": schedule,
        "selection_admission": admission,
        "execution_request": request,
        "execution_authority": authority,
    }
    input_hashes: dict[str, str] = {}
    for name, filename in _INPUT_FILES.items():
        path = _write(inputs / filename, values[name])
        input_hashes[name] = _file_sha256(path)
    runtime_body = {
        "freeze_run_root": str(freeze_root.resolve()),
        "repo_root": str(repository),
    }
    runtime_body["runtime_paths_sha256"] = content_hash(runtime_body)
    _write(root / "runtime_paths.json", runtime_body)
    contexts = root / "contexts"
    contexts.mkdir()
    context_hashes: dict[str, str] = {}
    for phase in _PRESELECTION_PHASES:
        for block_id in manifest["measurement_blocks"][phase]:
            context = _build_context(
                block_id=block_id,
                schedule=schedule,
                request=request,
                authority=authority,
            )
            _write(contexts / f"{block_id}.json", context)
            context_hashes[block_id] = context["execution_context_sha256"]
    initialized = {
        **manifest,
        "input_file_sha256s": input_hashes,
        "preselection_execution_context_sha256s": context_hashes,
        "state": "initialized_preselection",
    }
    initialized["campaign_manifest_sha256"] = content_hash(
        {
            key: value
            for key, value in initialized.items()
            if key != "campaign_manifest_sha256"
        }
    )
    _write(root / "campaign_manifest.json", initialized)
    return initialized


def _load_workspace(root: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    manifest = _hashed(
        _read(root / "campaign_manifest.json", name="campaign manifest"),
        field="campaign_manifest_sha256",
        name="campaign manifest",
    )
    if (
        manifest.get("schema_version")
        != FINBENCH_CONFIRMATORY_CAMPAIGN_SCHEMA_VERSION
        or manifest.get("state") != "initialized_preselection"
        or manifest.get("paper_result") is not False
    ):
        raise FinBenchConfirmatoryCampaignError("campaign manifest boundary changed")
    inputs = {
        name: _read(root / "inputs" / filename, name=name.replace("_", " "))
        for name, filename in _INPUT_FILES.items()
    }
    observed_hashes = {
        name: _file_sha256(root / "inputs" / filename)
        for name, filename in _INPUT_FILES.items()
    }
    if observed_hashes != manifest.get("input_file_sha256s"):
        raise FinBenchConfirmatoryCampaignError("campaign input snapshot changed")
    rebuilt = build_finbench_confirmatory_campaign_manifest(
        freeze_manifest=inputs["freeze_manifest"],
        freeze_audit=inputs["freeze_audit"],
        schedule=inputs["schedule"],
        selection_admission=inputs["selection_admission"],
        execution_request=inputs["execution_request"],
        execution_authority=inputs["execution_authority"],
    )
    for field in (
        "campaign_id",
        "schedule_sha256",
        "workload_sha256",
        "selection_admission_sha256",
        "execution_request_sha256",
        "execution_authority_sha256",
        "runner_commit",
        "measurement_blocks",
    ):
        if manifest.get(field) != rebuilt.get(field):
            raise FinBenchConfirmatoryCampaignError(
                f"campaign manifest {field} changed"
            )
    observed_context_hashes: dict[str, str] = {}
    for phase in _PRESELECTION_PHASES:
        for block_id in manifest["measurement_blocks"][phase]:
            context = validate_finbench_confirmatory_block_execution_envelope(
                _read(
                    root / "contexts" / f"{block_id}.json",
                    name=f"preselection context {block_id}",
                )
            )
            observed_context_hashes[block_id] = context[
                "execution_context_sha256"
            ]
    if observed_context_hashes != manifest.get(
        "preselection_execution_context_sha256s"
    ):
        raise FinBenchConfirmatoryCampaignError(
            "preselection execution contexts changed"
        )
    return manifest, inputs


def _attempt_root(root: Path, block_id: str, context: Mapping[str, Any]) -> Path:
    attempt = context["block_attempt"]
    attempt_id = str(attempt["attempt_id"])
    attempt_index = int(attempt["attempt_index"])
    if attempt_index not in {1, 2}:
        raise FinBenchConfirmatoryCampaignError("attempt index changed")
    return (
        root
        / "block-runs"
        / block_id
        / f"attempt-{attempt_index}"
        / "native-service-run"
        / attempt_id
    )


def _replacement(
    root: Path, block_id: str, *, expected_commit: str
) -> tuple[dict[str, Any] | None, dict[str, Any], list[dict[str, Any]]]:
    """Select attempt one or its single audited infrastructure replacement."""

    initial = validate_finbench_confirmatory_block_execution_envelope(
        _read(root / "contexts" / f"{block_id}.json", name="block context")
    )
    path = root / "replacements" / f"{block_id}.json"
    if not path.exists() and not path.is_symlink():
        return None, initial, []
    record = _hashed(
        _read(path, name="replacement record"),
        field="replacement_sha256",
        name="replacement record",
    )
    failed = record.get("failed_attempt_bundle")
    replacement_context = validate_finbench_confirmatory_block_execution_envelope(
        _read(
            root / "contexts" / f"{block_id}-attempt-2.json",
            name="replacement block context",
        )
    )
    if (
        record.get("schema_version")
        != FINBENCH_CONFIRMATORY_REPLACEMENT_SCHEMA_VERSION
        or record.get("measurement_block_id") != block_id
        or record.get("initial_execution_context_sha256")
        != initial.get("execution_context_sha256")
        or not isinstance(failed, Mapping)
        or record.get("failed_attempt_sha256")
        != failed.get("failed_attempt_sha256")
        or record.get("replacement_execution_context_sha256")
        != replacement_context.get("execution_context_sha256")
        or replacement_context.get("block_attempt", {}).get("attempt_index") != 2
        or replacement_context.get("block_attempt", {}).get(
            "replacement_of_attempt_id"
        )
        != initial.get("block_attempt", {}).get("attempt_id")
        or record.get("automatic_retries") != 0
        or record.get("paper_result") is not False
    ):
        raise FinBenchConfirmatoryCampaignError(
            f"replacement provenance changed for {block_id}"
        )
    rebuilt_audit = audit_finbench_confirmatory_block(
        attempt_root=_attempt_root(root, block_id, initial),
        execution_context=initial,
        expected_commit=expected_commit,
    ).to_dict()
    saved_audit = _read(
        root / "audits" / f"{block_id}-attempt-1.json",
        name="failed attempt audit",
    )
    raw = _read(
        _attempt_root(root, block_id, initial) / "raw_measurements.json",
        name="failed raw measurements",
    )
    rebuilt_failed = build_finbench_confirmatory_failed_attempt_bundle(
        execution_context=initial,
        raw_measurements=raw,
        block_audit=rebuilt_audit,
    )
    if rebuilt_audit != saved_audit or rebuilt_failed != failed:
        raise FinBenchConfirmatoryCampaignError(
            f"failed attempt replay changed for {block_id}"
        )
    return record, replacement_context, [rebuilt_failed]


def prepare_finbench_confirmatory_replacement_workspace(
    *, campaign_root: str | Path, block_id: str
) -> dict[str, Any]:
    """Mint attempt two only after auditing a zero-measurement failure."""

    root = Path(campaign_root).resolve()
    manifest, inputs = _load_workspace(root)
    known = {
        item
        for values in manifest["measurement_blocks"].values()
        for item in values
    }
    if block_id not in known:
        raise FinBenchConfirmatoryCampaignError("unknown campaign block")
    if (
        (root / "replacements" / f"{block_id}.json").exists()
        or (root / "accepted-blocks" / f"{block_id}.json").exists()
    ):
        raise FileExistsError("replacement or accepted block already exists")
    initial = _read(
        root / "contexts" / f"{block_id}.json", name="initial block context"
    )
    initial_attempt = initial["block_attempt"]
    initial_root = _attempt_root(root, block_id, initial)
    audit = audit_finbench_confirmatory_block(
        attempt_root=initial_root,
        execution_context=initial,
        expected_commit=str(manifest["runner_commit"]),
    ).to_dict()
    if (
        audit.get("success") is not True
        or audit.get("failed_check_ids") != []
        or audit.get("attempt_status") != "infrastructure_failed"
        or audit.get("replacement_eligible") is not True
        or audit.get("valid_measurement_count") != 0
        or audit.get("failure_category") != "infrastructure_failure"
    ):
        raise FinBenchConfirmatoryCampaignError(
            "attempt is not an audited zero-measurement infrastructure failure"
        )
    raw = _read(initial_root / "raw_measurements.json", name="failed raw measurements")
    failed = build_finbench_confirmatory_failed_attempt_bundle(
        execution_context=initial,
        raw_measurements=raw,
        block_audit=audit,
    )
    phase = str(initial_attempt["phase"])
    family: Mapping[str, Any] | None = None
    profile: Mapping[str, Any] | None = None
    if phase in _POSTSELECTION_PHASES:
        training = _read(root / "phases/training_phase.json", name="training phase")
        profiling = _read(root / "phases/profile_phase.json", name="profile phase")
        family = training["family_selection_seal"]
        profile = profiling["profile_selection_seal"]
    attempt = compile_finbench_confirmatory_block_attempt(
        schedule=inputs["schedule"],
        execution_request=inputs["execution_request"],
        execution_authority=inputs["execution_authority"],
        measurement_block_id=block_id,
        attempt_index=2,
        replacement_of_attempt_id=str(initial_attempt["attempt_id"]),
        family_selection_seal=family,
        profile_selection_seal=profile,
    )
    replacement_context = build_finbench_confirmatory_block_execution_envelope(
        block_attempt=attempt,
        schedule=inputs["schedule"],
        execution_request=inputs["execution_request"],
        execution_authority=inputs["execution_authority"],
        family_selection_seal=family,
        profile_selection_seal=profile,
    )
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_REPLACEMENT_SCHEMA_VERSION,
        "campaign_manifest_sha256": manifest["campaign_manifest_sha256"],
        "measurement_block_id": block_id,
        "initial_execution_context_sha256": initial[
            "execution_context_sha256"
        ],
        "failed_attempt_sha256": failed["failed_attempt_sha256"],
        "failed_attempt_bundle": failed,
        "replacement_execution_context_sha256": replacement_context[
            "execution_context_sha256"
        ],
        "replacement_limit_consumed": 1,
        "replacement_reason": "audited_zero_measurement_infrastructure_failure",
        "automatic_retries": 0,
        "paper_result": False,
    }
    body["replacement_sha256"] = content_hash(body)
    _write(root / "audits" / f"{block_id}-attempt-1.json", audit)
    _write(root / "contexts" / f"{block_id}-attempt-2.json", replacement_context)
    _write(root / "replacements" / f"{block_id}.json", body)
    return body


def reconstruct_finbench_confirmatory_completed_block(
    *, campaign_root: str | Path, block_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Re-audit and package one completed first attempt without writing."""

    root = Path(campaign_root).resolve()
    manifest, _inputs = _load_workspace(root)
    if block_id not in {
        item
        for values in manifest["measurement_blocks"].values()
        for item in values
    }:
        raise FinBenchConfirmatoryCampaignError("unknown campaign block")
    _replacement_record, context, prior_failures = _replacement(
        root, block_id, expected_commit=str(manifest["runner_commit"])
    )
    attempt_root = _attempt_root(root, block_id, context)
    outer_root = attempt_root.parents[1]
    outer = _read(outer_root / "run_status.json", name="outer block status")
    if (
        outer.get("status") != "success"
        or outer.get("exit_code") != 0
        or outer.get("git_commit") != manifest["runner_commit"]
        or outer.get("workload_mode") != "finbench_confirmatory_block"
        or outer.get("runtime_removed") is not True
        or outer.get("cleanup_error") is not None
    ):
        raise FinBenchConfirmatoryCampaignError(
            f"outer native status failed for {block_id}"
        )
    audit = audit_finbench_confirmatory_block(
        attempt_root=attempt_root,
        execution_context=context,
        expected_commit=str(manifest["runner_commit"]),
    ).to_dict()
    if (
        audit.get("success") is not True
        or audit.get("failed_check_ids") != []
        or audit.get("attempt_status") != "completed"
        or audit.get("replacement_eligible") is not False
    ):
        raise FinBenchConfirmatoryCampaignError(
            f"completed block audit failed for {block_id}"
        )
    raw = _read(attempt_root / "raw_measurements.json", name="raw measurements")
    accepted = build_finbench_confirmatory_accepted_block(
        execution_context=context,
        raw_measurements=raw,
        block_audit=audit,
        prior_failed_attempts=prior_failures,
    )
    return audit, accepted


def _persist_completed_block(root: Path, block_id: str) -> dict[str, Any]:
    audit, accepted = reconstruct_finbench_confirmatory_completed_block(
        campaign_root=root, block_id=block_id
    )
    attempt_index = accepted["execution_context"]["block_attempt"][
        "attempt_index"
    ]
    _write(root / "audits" / f"{block_id}-attempt-{attempt_index}.json", audit)
    _write(root / "accepted-blocks" / f"{block_id}.json", accepted)
    return accepted


def _read_accepted(root: Path, block_ids: Sequence[str]) -> list[dict[str, Any]]:
    return [
        _read(
            root / "accepted-blocks" / f"{block_id}.json",
            name=f"accepted block {block_id}",
        )
        for block_id in block_ids
    ]


def assemble_finbench_confirmatory_selection_workspace(
    *,
    campaign_root: str | Path,
    policy: Mapping[str, Any] | str | Path = DEFAULT_POLICY_PATH,
) -> dict[str, Any]:
    """Audit preselection blocks, seal choices, and mint later contexts."""

    root = Path(campaign_root).resolve()
    manifest, inputs = _load_workspace(root)
    if (root / "selection_checkpoint.json").exists():
        raise FileExistsError("selection checkpoint already exists")
    accepted: dict[str, dict[str, Any]] = {}
    for phase in _PRESELECTION_PHASES:
        for block_id in manifest["measurement_blocks"][phase]:
            accepted[block_id] = _persist_completed_block(root, block_id)
    training_ids = manifest["measurement_blocks"][
        "crossfit_training_measurement"
    ]
    profile_ids = manifest["measurement_blocks"][
        "current_query_profile_acquisition"
    ]
    training = build_finbench_confirmatory_training_phase(
        workload_root=Path(
            _read(root / "runtime_paths.json", name="runtime paths")[
                "freeze_run_root"
            ]
        )
        / "confirmatory-workload",
        schedule=inputs["schedule"],
        selection_admission=inputs["selection_admission"],
        accepted_blocks=[accepted[item] for item in training_ids],
        measurement_source_id=(
            f"campaign:{manifest['campaign_id']}:training-blocks"
        ),
        policy=policy,
    )
    profile = build_finbench_confirmatory_profile_phase(
        schedule=inputs["schedule"],
        accepted_blocks=[accepted[item] for item in profile_ids],
    )
    _write(root / "phases" / "training_phase.json", training)
    _write(root / "phases" / "profile_phase.json", profile)
    later_hashes: dict[str, str] = {}
    for phase in _POSTSELECTION_PHASES:
        for block_id in manifest["measurement_blocks"][phase]:
            context = _build_context(
                block_id=block_id,
                schedule=inputs["schedule"],
                request=inputs["execution_request"],
                authority=inputs["execution_authority"],
                family_selection_seal=training["family_selection_seal"],
                profile_selection_seal=profile["profile_selection_seal"],
            )
            _write(root / "contexts" / f"{block_id}.json", context)
            later_hashes[block_id] = context["execution_context_sha256"]
    body: dict[str, Any] = {
        "schema_version": (
            FINBENCH_CONFIRMATORY_SELECTION_CHECKPOINT_SCHEMA_VERSION
        ),
        "campaign_manifest_sha256": manifest["campaign_manifest_sha256"],
        "schedule_sha256": manifest["schedule_sha256"],
        "selection_admission_sha256": manifest[
            "selection_admission_sha256"
        ],
        "training_phase_sha256": training["training_phase_sha256"],
        "profile_phase_sha256": profile["profile_phase_sha256"],
        "accepted_preselection_block_sha256s": {
            block_id: accepted[block_id]["accepted_block_sha256"]
            for block_id in sorted(accepted)
        },
        "postselection_execution_context_sha256s": later_hashes,
        "current_confirmatory_query_oracle_opened": False,
        "backend_calls_during_assembly": 0,
        "automatic_retries": 0,
        "paper_result": False,
    }
    body["selection_checkpoint_sha256"] = content_hash(body)
    _write(root / "selection_checkpoint.json", body)
    return body


def build_finbench_confirmatory_campaign_result(
    *,
    campaign_manifest: Mapping[str, Any],
    selection_checkpoint: Mapping[str, Any],
    oracle_gate: Mapping[str, Any],
    accepted_block_sha256s: Mapping[str, str],
) -> dict[str, Any]:
    manifest = _hashed(
        campaign_manifest,
        field="campaign_manifest_sha256",
        name="campaign manifest",
    )
    checkpoint = _hashed(
        selection_checkpoint,
        field="selection_checkpoint_sha256",
        name="selection checkpoint",
    )
    oracle = _hashed(
        oracle_gate, field="oracle_gate_sha256", name="oracle gate"
    )
    if (
        checkpoint.get("campaign_manifest_sha256")
        != manifest["campaign_manifest_sha256"]
        or oracle.get("schedule_sha256") != manifest["schedule_sha256"]
        or oracle.get("workload_sha256") != manifest["workload_sha256"]
        or oracle.get("selection_admission_sha256")
        != manifest["selection_admission_sha256"]
        or oracle.get("execution_request_sha256")
        != manifest["execution_request_sha256"]
        or oracle.get("execution_authority_sha256")
        != manifest["execution_authority_sha256"]
        or oracle.get("training_phase_sha256")
        != checkpoint["training_phase_sha256"]
        or oracle.get("profile_phase_sha256")
        != checkpoint["profile_phase_sha256"]
        or set(accepted_block_sha256s)
        != {
            item
            for values in manifest["measurement_blocks"].values()
            for item in values
        }
    ):
        raise FinBenchConfirmatoryCampaignError(
            "final campaign provenance changed"
        )
    status = str(oracle.get("status"))
    if status not in {"success", "invalidated_by_answer_oracle"}:
        raise FinBenchConfirmatoryCampaignError("oracle gate status changed")
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_RESULT_SCHEMA_VERSION,
        "campaign_id": manifest["campaign_id"],
        "status": status,
        "campaign_manifest_sha256": manifest["campaign_manifest_sha256"],
        "selection_checkpoint_sha256": checkpoint[
            "selection_checkpoint_sha256"
        ],
        "oracle_gate_sha256": oracle["oracle_gate_sha256"],
        "accepted_block_sha256s": dict(
            sorted(accepted_block_sha256s.items())
        ),
        "measurement_block_count": 22,
        "total_plan_runs": 1888,
        "maximum_backend_calls": 3776,
        "all_successful_measurements_exact": oracle[
            "all_successful_measurements_exact"
        ],
        "query_timeout_count": oracle["query_timeout_count"],
        "confirmatory_statistics_computed": (
            status == "success"
            and isinstance(oracle.get("analysis"), Mapping)
            and oracle["analysis"].get("confirmatory_statistics") is True
        ),
        "independent_campaign_audit_required": True,
        "automatic_retries": 0,
        "paper_result": False,
    }
    body["campaign_result_sha256"] = content_hash(body)
    return body


def finalize_finbench_confirmatory_campaign_workspace(
    *,
    campaign_root: str | Path,
    policy: Mapping[str, Any] | str | Path = DEFAULT_POLICY_PATH,
) -> dict[str, Any]:
    """Audit later blocks and open the oracle after exact completeness."""

    root = Path(campaign_root).resolve()
    manifest, inputs = _load_workspace(root)
    checkpoint = _hashed(
        _read(root / "selection_checkpoint.json", name="selection checkpoint"),
        field="selection_checkpoint_sha256",
        name="selection checkpoint",
    )
    if (root / "campaign_result.json").exists():
        raise FileExistsError("campaign result already exists")
    for phase in _POSTSELECTION_PHASES:
        for block_id in manifest["measurement_blocks"][phase]:
            _persist_completed_block(root, block_id)
    all_ids = [
        block_id
        for phase in _PHASES
        for block_id in manifest["measurement_blocks"][phase]
    ]
    accepted = _read_accepted(root, all_ids)
    training = _read(root / "phases/training_phase.json", name="training phase")
    profile = _read(root / "phases/profile_phase.json", name="profile phase")
    runtime_paths = _hashed(
        _read(root / "runtime_paths.json", name="runtime paths"),
        field="runtime_paths_sha256",
        name="runtime paths",
    )
    oracle = open_finbench_confirmatory_oracle(
        workload_root=Path(runtime_paths["freeze_run_root"])
        / "confirmatory-workload",
        schedule=inputs["schedule"],
        selection_admission=inputs["selection_admission"],
        accepted_blocks=accepted,
        training_phase=training,
        profile_phase=profile,
        policy=policy,
    )
    _write(root / "oracle_gate.json", oracle)
    accepted_hashes = {
        block_id: bundle["accepted_block_sha256"]
        for block_id, bundle in zip(all_ids, accepted)
    }
    result = build_finbench_confirmatory_campaign_result(
        campaign_manifest=manifest,
        selection_checkpoint=checkpoint,
        oracle_gate=oracle,
        accepted_block_sha256s=accepted_hashes,
    )
    _write(root / "campaign_result.json", result)
    return result


def record_finbench_confirmatory_submission(
    *,
    campaign_root: str | Path,
    training_job_id: str,
    profile_job_id: str,
    selection_job_id: str,
    serving_job_id: str,
    shadow_job_id: str,
    finalize_job_id: str,
    audit_job_id: str,
) -> dict[str, Any]:
    root = Path(campaign_root).resolve()
    manifest, _inputs = _load_workspace(root)
    jobs = {
        "training_array": training_job_id,
        "profile": profile_job_id,
        "selection_assembly": selection_job_id,
        "serving_array": serving_job_id,
        "shadow_array": shadow_job_id,
        "delayed_oracle": finalize_job_id,
        "independent_campaign_audit": audit_job_id,
    }
    if any(_JOB_ID.fullmatch(str(value)) is None for value in jobs.values()):
        raise FinBenchConfirmatoryCampaignError("invalid Slurm job identity")
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_SUBMISSION_SCHEMA_VERSION,
        "campaign_id": manifest["campaign_id"],
        "campaign_manifest_sha256": manifest["campaign_manifest_sha256"],
        "jobs": jobs,
        "dependency_contract": {
            "selection_after": ["training_array", "profile"],
            "serving_after": ["selection_assembly"],
            "shadow_after": ["selection_assembly"],
            "delayed_oracle_after": ["serving_array", "shadow_array"],
            "independent_campaign_audit_afterany": ["delayed_oracle"],
        },
        "automatic_retries": 0,
        "paper_result": False,
    }
    body["submission_sha256"] = content_hash(body)
    _write(root / "submission.json", body)
    return body


def _print_success(command: str, output: Mapping[str, Any]) -> None:
    identifier = next(
        (
            value
            for key, value in output.items()
            if key.endswith("_sha256")
        ),
        None,
    )
    print(
        json.dumps(
            {
                "status": "success",
                "command": command,
                "identifier": identifier,
                "paper_result": False,
            },
            sort_keys=True,
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("initialize")
    initialize.add_argument("--campaign-root", required=True)
    initialize.add_argument("--freeze-run-root", required=True)
    initialize.add_argument("--freeze-audit", required=True)
    initialize.add_argument("--selection-admission", required=True)
    initialize.add_argument("--execution-request", required=True)
    initialize.add_argument("--execution-authority", required=True)
    initialize.add_argument("--repo-root", required=True)

    selection = commands.add_parser("assemble-selection")
    selection.add_argument("--campaign-root", required=True)
    selection.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))

    finalize = commands.add_parser("finalize")
    finalize.add_argument("--campaign-root", required=True)
    finalize.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))

    submission = commands.add_parser("record-submission")
    submission.add_argument("--campaign-root", required=True)
    for name in (
        "training-job-id",
        "profile-job-id",
        "selection-job-id",
        "serving-job-id",
        "shadow-job-id",
        "finalize-job-id",
        "audit-job-id",
    ):
        submission.add_argument(f"--{name}", required=True)
    replacement = commands.add_parser("prepare-replacement")
    replacement.add_argument("--campaign-root", required=True)
    replacement.add_argument("--measurement-block-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "initialize":
            result = initialize_finbench_confirmatory_campaign_workspace(
                campaign_root=args.campaign_root,
                freeze_run_root=args.freeze_run_root,
                freeze_audit_path=args.freeze_audit,
                selection_admission_path=args.selection_admission,
                execution_request_path=args.execution_request,
                execution_authority_path=args.execution_authority,
                repo_root=args.repo_root,
            )
        elif args.command == "assemble-selection":
            result = assemble_finbench_confirmatory_selection_workspace(
                campaign_root=args.campaign_root, policy=args.policy
            )
        elif args.command == "finalize":
            result = finalize_finbench_confirmatory_campaign_workspace(
                campaign_root=args.campaign_root, policy=args.policy
            )
        elif args.command == "record-submission":
            result = record_finbench_confirmatory_submission(
                campaign_root=args.campaign_root,
                training_job_id=args.training_job_id,
                profile_job_id=args.profile_job_id,
                selection_job_id=args.selection_job_id,
                serving_job_id=args.serving_job_id,
                shadow_job_id=args.shadow_job_id,
                finalize_job_id=args.finalize_job_id,
                audit_job_id=args.audit_job_id,
            )
        else:
            result = prepare_finbench_confirmatory_replacement_workspace(
                campaign_root=args.campaign_root,
                block_id=args.measurement_block_id,
            )
    except (
        FileExistsError,
        OSError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
    ) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 2
    _print_success(args.command, result)
    return 0 if result.get("status") != "invalidated_by_answer_oracle" else 1


if __name__ == "__main__":
    raise SystemExit(main())
