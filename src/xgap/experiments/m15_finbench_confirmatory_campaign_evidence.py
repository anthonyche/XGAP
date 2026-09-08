"""Independently reconstruct one complete FinBench confirmatory campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_confirmatory_campaign import (
    FINBENCH_CONFIRMATORY_CAMPAIGN_SCHEMA_VERSION,
    FINBENCH_CONFIRMATORY_RESULT_SCHEMA_VERSION,
    FINBENCH_CONFIRMATORY_SELECTION_CHECKPOINT_SCHEMA_VERSION,
    FINBENCH_CONFIRMATORY_SUBMISSION_SCHEMA_VERSION,
    _INPUT_FILES,
    _PHASES,
    _POSTSELECTION_PHASES,
    _PRESELECTION_PHASES,
    _build_context,
    _git_state,
    _load_workspace,
    build_finbench_confirmatory_campaign_manifest,
    build_finbench_confirmatory_campaign_result,
    reconstruct_finbench_confirmatory_completed_block,
)
from xgap.experiments.m15_finbench_confirmatory_oracle import (
    open_finbench_confirmatory_oracle,
)
from xgap.experiments.m15_finbench_confirmatory_phase import (
    build_finbench_confirmatory_profile_phase,
    build_finbench_confirmatory_training_phase,
)
from xgap.experiments.m15_finbench_family_memory import DEFAULT_POLICY_PATH


FINBENCH_CONFIRMATORY_CAMPAIGN_AUDIT_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-campaign-evidence-audit-v1"
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_JOB_ID = re.compile(r"^[1-9][0-9]*(?:_[1-9][0-9]*)?$")


@dataclass(frozen=True)
class FinBenchConfirmatoryCampaignCheck:
    check_id: str
    passed: bool
    expected: Any
    observed: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "passed": self.passed,
            "expected": self.expected,
            "observed": self.observed,
        }


@dataclass(frozen=True)
class FinBenchConfirmatoryCampaignAudit:
    campaign_root: Path
    expected_commit: str
    campaign_id: str
    campaign_status: str
    source_campaign_result_sha256: str
    checks: tuple[FinBenchConfirmatoryCampaignCheck, ...]
    run_tree_mutated: bool

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(item.check_id for item in self.checks if not item.passed)

    @property
    def success(self) -> bool:
        return not self.failed_check_ids and not self.run_tree_mutated

    @property
    def confirmatory_result_admitted(self) -> bool:
        return self.success and self.campaign_status == "success"

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "schema_version": (
                FINBENCH_CONFIRMATORY_CAMPAIGN_AUDIT_SCHEMA_VERSION
            ),
            "success": self.success,
            "campaign_root": str(self.campaign_root),
            "expected_commit": self.expected_commit,
            "campaign_id": self.campaign_id,
            "campaign_status": self.campaign_status,
            "source_campaign_result_sha256": (
                self.source_campaign_result_sha256
            ),
            "check_count": len(self.checks),
            "failed_check_ids": list(self.failed_check_ids),
            "checks": [item.to_dict() for item in self.checks],
            "run_tree_mutated": self.run_tree_mutated,
            "confirmatory_result_admitted": (
                self.confirmatory_result_admitted
            ),
            "paper_result": self.confirmatory_result_admitted,
        }
        body["audit_sha256"] = content_hash(body)
        return body


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"campaign tree contains a symbolic link: {path}")
        if not path.is_file():
            continue
        relative = str(path.relative_to(root)).encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> tuple[Any, str]:
    if path.is_symlink() or not path.is_file():
        return None, "missing_or_nonregular"
    try:
        return json.loads(path.read_text(encoding="utf-8")), "ok"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"invalid_json:{exc}"


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _compact_check_value(value: Any) -> Any:
    """Retain bounded diagnostic evidence instead of whole campaign objects.

    The confirmatory campaign contains raw result rows for 1,888 plan runs.
    Keeping both sides of every successful equality check in ``checks`` made
    the independent auditor retain several complete copies of that evidence.
    Scalar values remain directly inspectable.  Container values retain their
    shape and already-sealed identities; the auditor still performs equality
    against the complete in-memory objects before this projection is made.
    """

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= 256:
            return value
        return {
            "value_type": "string",
            "character_count": len(value),
        }
    if isinstance(value, Mapping):
        identity_fields = {
            str(key): item
            for key, item in value.items()
            if (
                isinstance(key, str)
                and (
                    key == "schema_version"
                    or key.endswith("_sha256")
                )
                and isinstance(item, str)
            )
        }
        return {
            "value_type": "mapping",
            "entry_count": len(value),
            "identity_fields": dict(sorted(identity_fields.items())),
        }
    if isinstance(value, (list, tuple)):
        return {
            "value_type": "sequence",
            "item_count": len(value),
        }
    if isinstance(value, (set, frozenset)):
        return {
            "value_type": "set",
            "item_count": len(value),
        }
    return {"value_type": type(value).__name__}


def _hash_matches(value: object, field: str) -> bool:
    if not isinstance(value, Mapping) or not isinstance(value.get(field), str):
        return False
    return value[field] == content_hash(
        {key: item for key, item in value.items() if key != field}
    )


def _checkpoint(
    *,
    manifest: Mapping[str, Any],
    training: Mapping[str, Any],
    profile: Mapping[str, Any],
    accepted: Mapping[str, Mapping[str, Any]],
    context_hashes: Mapping[str, str],
) -> dict[str, Any]:
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
        "postselection_execution_context_sha256s": dict(context_hashes),
        "current_confirmatory_query_oracle_opened": False,
        "backend_calls_during_assembly": 0,
        "automatic_retries": 0,
        "paper_result": False,
    }
    body["selection_checkpoint_sha256"] = content_hash(body)
    return body


def _submission_valid(
    value: Mapping[str, Any], *, manifest: Mapping[str, Any]
) -> bool:
    jobs = value.get("jobs")
    return (
        value.get("schema_version")
        == FINBENCH_CONFIRMATORY_SUBMISSION_SCHEMA_VERSION
        and _hash_matches(value, "submission_sha256")
        and value.get("campaign_id") == manifest["campaign_id"]
        and value.get("campaign_manifest_sha256")
        == manifest["campaign_manifest_sha256"]
        and isinstance(jobs, Mapping)
        and set(jobs)
        == {
            "training_array",
            "profile",
            "selection_assembly",
            "serving_array",
            "shadow_array",
            "delayed_oracle",
            "independent_campaign_audit",
        }
        and all(_JOB_ID.fullmatch(str(item)) for item in jobs.values())
        and value.get("dependency_contract")
        == {
            "selection_after": ["training_array", "profile"],
            "serving_after": ["selection_assembly"],
            "shadow_after": ["selection_assembly"],
            "delayed_oracle_after": ["serving_array", "shadow_array"],
            "independent_campaign_audit_afterany": ["delayed_oracle"],
        }
        and value.get("automatic_retries") == 0
        and value.get("paper_result") is False
    )


def audit_finbench_confirmatory_campaign(
    *,
    campaign_root: str | Path,
    repo_root: str | Path,
    expected_commit: str,
    policy: Mapping[str, Any] | str | Path = DEFAULT_POLICY_PATH,
) -> FinBenchConfirmatoryCampaignAudit:
    """Replay every pre-oracle and post-oracle artifact without writing."""

    if _COMMIT.fullmatch(expected_commit) is None:
        raise ValueError("expected_commit must be a full lowercase Git commit")
    selected = Path(campaign_root)
    if selected.is_symlink():
        raise ValueError("campaign_root must not be a symbolic link")
    root = selected.resolve()
    repository = Path(repo_root).resolve()
    if not root.is_dir() or not (repository / "pyproject.toml").is_file():
        raise ValueError("campaign or repository root is missing")
    before = _tree_digest(root)
    checks: list[FinBenchConfirmatoryCampaignCheck] = []

    def check(check_id: str, expected: Any, observed: Any) -> None:
        passed = expected == observed
        checks.append(
            FinBenchConfirmatoryCampaignCheck(
                check_id=check_id,
                passed=passed,
                expected=_compact_check_value(expected),
                observed=_compact_check_value(observed),
            )
        )

    artifacts = {
        "manifest": root / "campaign_manifest.json",
        "runtime_paths": root / "runtime_paths.json",
        "selection_checkpoint": root / "selection_checkpoint.json",
        "training_phase": root / "phases/training_phase.json",
        "profile_phase": root / "phases/profile_phase.json",
        "oracle_gate": root / "oracle_gate.json",
        "campaign_result": root / "campaign_result.json",
        "submission": root / "submission.json",
    }
    loaded: dict[str, Any] = {}
    for name, path in artifacts.items():
        loaded[name], state = _read_json(path)
        check(f"artifact.{name}", "ok", state)
    manifest = _mapping(loaded["manifest"])
    runtime_paths = _mapping(loaded["runtime_paths"])
    checkpoint = _mapping(loaded["selection_checkpoint"])
    saved_training = _mapping(loaded["training_phase"])
    saved_profile = _mapping(loaded["profile_phase"])
    saved_oracle = _mapping(loaded["oracle_gate"])
    saved_result = _mapping(loaded["campaign_result"])
    submission = _mapping(loaded["submission"])
    check(
        "manifest.schema",
        FINBENCH_CONFIRMATORY_CAMPAIGN_SCHEMA_VERSION,
        manifest.get("schema_version"),
    )
    check("manifest.hash", True, _hash_matches(manifest, "campaign_manifest_sha256"))
    check("manifest.commit", expected_commit, manifest.get("runner_commit"))
    check("manifest.block_count", 22, manifest.get("measurement_block_count"))
    check("manifest.plan_runs", 1888, manifest.get("total_plan_runs"))
    check("manifest.backend_calls", 3776, manifest.get("maximum_backend_calls"))
    check("manifest.retry", 0, manifest.get("automatic_retries"))
    check("manifest.paper_result", False, manifest.get("paper_result"))
    check("runtime_paths.hash", True, _hash_matches(runtime_paths, "runtime_paths_sha256"))
    check("runtime_paths.repo", str(repository), runtime_paths.get("repo_root"))
    try:
        check(
            "repository.git_state",
            {"commit": expected_commit, "clean": True},
            _git_state(repository),
        )
    except Exception as exc:
        check(
            "repository.git_state",
            {"commit": expected_commit, "clean": True},
            f"error:{type(exc).__name__}:{exc}",
        )

    campaign_id = str(manifest.get("campaign_id", ""))
    campaign_status = str(saved_result.get("status", "unavailable"))
    source_result_hash = str(saved_result.get("campaign_result_sha256", ""))
    try:
        rebuilt_manifest, inputs = _load_workspace(root)
        all_ids = [
            block_id
            for phase in _PHASES
            for block_id in rebuilt_manifest["measurement_blocks"][phase]
        ]
        check("blocks.identities", 22, len(all_ids) if len(set(all_ids)) == 22 else -1)
        accepted: dict[str, dict[str, Any]] = {}
        saved_audit_success: dict[str, bool] = {}
        rebuilt_contexts: dict[str, dict[str, Any]] = {}
        for block_id in all_ids:
            context_value, context_state = _read_json(
                root / "contexts" / f"{block_id}.json"
            )
            check(f"context.{block_id}.artifact", "ok", context_state)
            phase = next(
                name
                for name in _PHASES
                if block_id in rebuilt_manifest["measurement_blocks"][name]
            )
            expected_context = _build_context(
                block_id=block_id,
                schedule=inputs["schedule"],
                request=inputs["execution_request"],
                authority=inputs["execution_authority"],
                family_selection_seal=(
                    saved_training.get("family_selection_seal")
                    if phase in _POSTSELECTION_PHASES
                    else None
                ),
                profile_selection_seal=(
                    saved_profile.get("profile_selection_seal")
                    if phase in _POSTSELECTION_PHASES
                    else None
                ),
            )
            check(f"context.{block_id}.reconstruction", expected_context, context_value)
            rebuilt_contexts[block_id] = expected_context
            rebuilt_audit, rebuilt_accepted = (
                reconstruct_finbench_confirmatory_completed_block(
                    campaign_root=root, block_id=block_id
                )
            )
            attempt_index = rebuilt_accepted["execution_context"][
                "block_attempt"
            ]["attempt_index"]
            saved_audit_value, audit_state = _read_json(
                root
                / "audits"
                / f"{block_id}-attempt-{attempt_index}.json"
            )
            saved_accepted_value, accepted_state = _read_json(
                root / "accepted-blocks" / f"{block_id}.json"
            )
            check(f"block.{block_id}.audit_artifact", "ok", audit_state)
            check(f"block.{block_id}.accepted_artifact", "ok", accepted_state)
            check(f"block.{block_id}.audit_reconstruction", rebuilt_audit, saved_audit_value)
            check(
                f"block.{block_id}.accepted_reconstruction",
                rebuilt_accepted,
                saved_accepted_value,
            )
            accepted[block_id] = rebuilt_accepted
            saved_audit_success[block_id] = rebuilt_audit.get("success") is True
        base_manifest = build_finbench_confirmatory_campaign_manifest(
            freeze_manifest=inputs["freeze_manifest"],
            freeze_audit=inputs["freeze_audit"],
            schedule=inputs["schedule"],
            selection_admission=inputs["selection_admission"],
            execution_request=inputs["execution_request"],
            execution_authority=inputs["execution_authority"],
        )
        expected_manifest = {
            **base_manifest,
            "input_file_sha256s": {
                name: _file_sha256(root / "inputs" / filename)
                for name, filename in _INPUT_FILES.items()
            },
            "preselection_execution_context_sha256s": {
                block_id: rebuilt_contexts[block_id][
                    "execution_context_sha256"
                ]
                for phase in _PRESELECTION_PHASES
                for block_id in rebuilt_manifest["measurement_blocks"][phase]
            },
            "state": "initialized_preselection",
        }
        expected_manifest["campaign_manifest_sha256"] = content_hash(
            {
                key: value
                for key, value in expected_manifest.items()
                if key != "campaign_manifest_sha256"
            }
        )
        check("manifest.reconstruction", expected_manifest, dict(manifest))
        measurement_count = sum(
            int(item["raw_measurements"]["measurement_count"])
            for item in accepted.values()
        )
        check("blocks.measurement_count", 1888, measurement_count)
        check(
            "blocks.all_audits_success",
            True,
            all(saved_audit_success.values()),
        )
        training_ids = rebuilt_manifest["measurement_blocks"][
            "crossfit_training_measurement"
        ]
        profile_ids = rebuilt_manifest["measurement_blocks"][
            "current_query_profile_acquisition"
        ]
        rebuilt_training = build_finbench_confirmatory_training_phase(
            workload_root=Path(runtime_paths["freeze_run_root"])
            / "confirmatory-workload",
            schedule=inputs["schedule"],
            selection_admission=inputs["selection_admission"],
            accepted_blocks=[accepted[item] for item in training_ids],
            measurement_source_id=(
                f"campaign:{rebuilt_manifest['campaign_id']}:training-blocks"
            ),
            policy=policy,
        )
        rebuilt_profile = build_finbench_confirmatory_profile_phase(
            schedule=inputs["schedule"],
            accepted_blocks=[accepted[item] for item in profile_ids],
        )
        check("phase.training_reconstruction", rebuilt_training, dict(saved_training))
        check("phase.profile_reconstruction", rebuilt_profile, dict(saved_profile))
        post_hashes = {
            block_id: _mapping(
                _read_json(root / "contexts" / f"{block_id}.json")[0]
            ).get("execution_context_sha256")
            for phase in _POSTSELECTION_PHASES
            for block_id in rebuilt_manifest["measurement_blocks"][phase]
        }
        preselection_accepted = {
            block_id: accepted[block_id]
            for phase in _PRESELECTION_PHASES
            for block_id in rebuilt_manifest["measurement_blocks"][phase]
        }
        rebuilt_checkpoint = _checkpoint(
            manifest=rebuilt_manifest,
            training=rebuilt_training,
            profile=rebuilt_profile,
            accepted=preselection_accepted,
            context_hashes=post_hashes,
        )
        check("selection.schema", FINBENCH_CONFIRMATORY_SELECTION_CHECKPOINT_SCHEMA_VERSION, checkpoint.get("schema_version"))
        check("selection.reconstruction", rebuilt_checkpoint, dict(checkpoint))
        rebuilt_oracle = open_finbench_confirmatory_oracle(
            workload_root=Path(runtime_paths["freeze_run_root"])
            / "confirmatory-workload",
            schedule=inputs["schedule"],
            selection_admission=inputs["selection_admission"],
            accepted_blocks=[accepted[item] for item in all_ids],
            training_phase=rebuilt_training,
            profile_phase=rebuilt_profile,
            policy=policy,
        )
        check("oracle.reconstruction", rebuilt_oracle, dict(saved_oracle))
        accepted_hashes = {
            block_id: accepted[block_id]["accepted_block_sha256"]
            for block_id in all_ids
        }
        rebuilt_result = build_finbench_confirmatory_campaign_result(
            campaign_manifest=rebuilt_manifest,
            selection_checkpoint=rebuilt_checkpoint,
            oracle_gate=rebuilt_oracle,
            accepted_block_sha256s=accepted_hashes,
        )
        expected_admission = rebuilt_result["status"] == "success"
        check("result.schema", FINBENCH_CONFIRMATORY_RESULT_SCHEMA_VERSION, saved_result.get("schema_version"))
        check("result.reconstruction", rebuilt_result, dict(saved_result))
        check(
            "result.all_exact",
            expected_admission,
            rebuilt_result.get("all_successful_measurements_exact"),
        )
        check(
            "result.statistics",
            expected_admission,
            rebuilt_result.get("confirmatory_statistics_computed"),
        )
        check("result.retry", 0, rebuilt_result.get("automatic_retries"))
        check("result.paper_result_before_audit", False, rebuilt_result.get("paper_result"))
        check("submission.contract", True, _submission_valid(submission, manifest=rebuilt_manifest))
        campaign_id = str(rebuilt_manifest["campaign_id"])
        campaign_status = str(rebuilt_result["status"])
        source_result_hash = str(rebuilt_result["campaign_result_sha256"])
    except Exception as exc:
        check(
            "independent.reconstruction",
            "success",
            f"error:{type(exc).__name__}:{exc}",
        )
    after = _tree_digest(root)
    return FinBenchConfirmatoryCampaignAudit(
        campaign_root=root,
        expected_commit=expected_commit,
        campaign_id=campaign_id,
        campaign_status=campaign_status,
        source_campaign_result_sha256=source_result_hash,
        checks=tuple(checks),
        run_tree_mutated=before != after,
    )


def _write(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"output exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        audit = audit_finbench_confirmatory_campaign(
            campaign_root=args.campaign_root,
            repo_root=args.repo_root,
            expected_commit=args.expected_commit,
            policy=args.policy,
        )
        payload = audit.to_dict()
        _write(Path(args.output), payload)
    except (FileExistsError, OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if audit.confirmatory_result_admitted else 1


if __name__ == "__main__":
    raise SystemExit(main())
