"""CLI boundary for the typed XGAP remote experiment executor.

Configuration comes from non-secret environment variables.  Authentication
remains entirely in the user's SSH configuration and agent.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from xgap.tools import (
    RemoteExecutorOperation,
    RemoteExecutorRegistry,
    RemoteExecutorTool,
    RemoteTransport,
    SlurmRemoteExecutor,
    SshTransport,
    ToolContext,
    ToolResult,
    ToolStatus,
)


DEFAULT_EXECUTOR_ID = "cwru-pioneer"
DEFAULT_ALLOWED_SBATCH_SCRIPTS = (
    "scripts/slurm/run_m15_core_smoke.sbatch",
    "scripts/slurm/probe_m15_native_services.sbatch",
    "scripts/slurm/prepare_m15_native_artifacts.sbatch",
    "scripts/slurm/run_m15_native_services.sbatch",
    "scripts/slurm/run_m15_native_adaptive.sbatch",
    "scripts/slurm/run_m15_native_scaled_adaptive.sbatch",
    "scripts/slurm/run_m15_native_method_matrix.sbatch",
    "scripts/slurm/run_m15_native_campaign_session.sbatch",
    "scripts/slurm/run_m15_native_query_bound_session.sbatch",
    "scripts/slurm/run_m15_native_parameterized_stream.sbatch",
    "scripts/slurm/run_m15_native_family_transfer.sbatch",
    "scripts/slurm/run_m15_native_semantic_risk_relaxation.sbatch",
    "scripts/slurm/run_m15_native_semantic_predicate_relaxation.sbatch",
    "scripts/slurm/run_m15_native_semantic_direct_frontier.sbatch",
    "scripts/slurm/run_m15_native_direct_family_pilot.sbatch",
    "scripts/slurm/run_m15_native_current_query_profile_baseline.sbatch",
    "scripts/slurm/run_m15_native_paired_physical_comparison.sbatch",
    "scripts/slurm/run_m15_live_resolution.sbatch",
)


@dataclass(frozen=True)
class RemoteControlConfig:
    host_alias: str
    remote_repo_root: str
    remote_artifact_root: str
    local_artifact_root: Path
    remote_python: str = "python3"
    executor_id: str = DEFAULT_EXECUTOR_ID
    allowed_sbatch_scripts: tuple[str, ...] = DEFAULT_ALLOWED_SBATCH_SCRIPTS
    submission_environment: Mapping[str, str] | None = None
    allow_cancel: bool = False
    timeout_seconds: float = 30.0


def load_remote_control_config(
    environ: Mapping[str, str] | None = None,
    *,
    working_directory: Path | None = None,
) -> RemoteControlConfig:
    """Load fail-closed remote configuration without reading credentials."""

    values = os.environ if environ is None else environ
    host_alias = values.get("XGAP_REMOTE_HOST_ALIAS", "").strip()
    remote_repo_root = values.get("XGAP_REMOTE_REPO_ROOT", "").strip()
    if not host_alias:
        raise ValueError("XGAP_REMOTE_HOST_ALIAS is required")
    if not remote_repo_root:
        raise ValueError("XGAP_REMOTE_REPO_ROOT is required")

    default_artifact_root = str(PurePosixPath(remote_repo_root) / "runs")
    remote_artifact_root = values.get(
        "XGAP_REMOTE_ARTIFACT_ROOT",
        default_artifact_root,
    ).strip()
    base_directory = (working_directory or Path.cwd()).resolve()
    local_artifact_root = Path(
        values.get("XGAP_LOCAL_ARTIFACT_ROOT", str(base_directory / "runs" / "remote-fetch"))
    ).expanduser()
    raw_scripts = values.get(
        "XGAP_REMOTE_ALLOWED_SBATCH_SCRIPTS",
        ",".join(DEFAULT_ALLOWED_SBATCH_SCRIPTS),
    )
    allowed_scripts = tuple(item.strip() for item in raw_scripts.split(",") if item.strip())
    if not allowed_scripts:
        raise ValueError("XGAP_REMOTE_ALLOWED_SBATCH_SCRIPTS must not be empty")

    raw_timeout = values.get("XGAP_REMOTE_TIMEOUT_SECONDS", "30")
    try:
        timeout_seconds = float(raw_timeout)
    except ValueError as exc:
        raise ValueError("XGAP_REMOTE_TIMEOUT_SECONDS must be numeric") from exc
    if timeout_seconds <= 0:
        raise ValueError("XGAP_REMOTE_TIMEOUT_SECONDS must be positive")

    submission_environment = {}
    job_python = values.get("XGAP_REMOTE_JOB_PYTHON", "").strip()
    job_module = values.get("XGAP_REMOTE_JOB_MODULE", "Miniconda3").strip()
    if job_python:
        submission_environment["XGAP_PYTHON"] = job_python
    if job_module:
        submission_environment["XGAP_PYTHON_MODULE"] = job_module

    return RemoteControlConfig(
        host_alias=host_alias,
        remote_repo_root=remote_repo_root,
        remote_artifact_root=remote_artifact_root,
        local_artifact_root=local_artifact_root,
        remote_python=values.get("XGAP_REMOTE_PYTHON", "python3").strip(),
        executor_id=values.get("XGAP_REMOTE_EXECUTOR_ID", DEFAULT_EXECUTOR_ID).strip(),
        allowed_sbatch_scripts=allowed_scripts,
        submission_environment=submission_environment,
        allow_cancel=values.get("XGAP_REMOTE_ALLOW_CANCEL", "0") == "1",
        timeout_seconds=timeout_seconds,
    )


def build_remote_executor(
    config: RemoteControlConfig,
    *,
    transport: RemoteTransport | None = None,
) -> SlurmRemoteExecutor:
    selected_transport = transport or SshTransport(
        host_alias=config.host_alias,
        remote_python=config.remote_python,
    )
    return SlurmRemoteExecutor(
        executor_id=config.executor_id,
        transport=selected_transport,
        remote_repo_root=config.remote_repo_root,
        remote_artifact_root=config.remote_artifact_root,
        local_artifact_root=config.local_artifact_root,
        allowed_sbatch_scripts=frozenset(config.allowed_sbatch_scripts),
        submission_environment=dict(config.submission_environment or {}),
        allow_cancel=config.allow_cancel,
        timeout_seconds=config.timeout_seconds,
    )


def invoke_remote_control(
    config: RemoteControlConfig,
    operation: RemoteExecutorOperation,
    payload: Mapping[str, Any],
    *,
    transport: RemoteTransport | None = None,
) -> ToolResult:
    registry = RemoteExecutorRegistry()
    registry.register(build_remote_executor(config, transport=transport))
    tool = RemoteExecutorTool(registry)
    return tool.invoke(
        {
            "executor_id": config.executor_id,
            "operation": operation.value,
            "payload": dict(payload),
        },
        ToolContext(
            goal_id="m15-remote-control",
            step=1,
            call_id=f"remote-control-{operation.value}",
        ),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    stage = subparsers.add_parser("stage", help="stage an exact Git commit")
    stage.add_argument("--branch", required=True)
    stage.add_argument("--commit", required=True)

    submit = subparsers.add_parser("submit", help="submit an allowlisted Slurm script")
    submit.add_argument("--script", required=True)

    status = subparsers.add_parser("status", help="inspect one Slurm job")
    status.add_argument("--job-id", required=True)

    log = subparsers.add_parser("log", help="read a bounded remote log tail")
    log.add_argument("--path", required=True)
    log.add_argument("--lines", type=int, default=200)

    fetch = subparsers.add_parser("fetch", help="fetch artifacts below the configured root")
    fetch.add_argument("--remote-path", required=True)
    fetch.add_argument("--local-path", required=True)

    cancel = subparsers.add_parser("cancel", help="cancel only when explicitly enabled")
    cancel.add_argument("--job-id", required=True)
    cancel.add_argument("--confirm-job-id", required=True)
    return parser


def _operation_and_payload(args: argparse.Namespace) -> tuple[RemoteExecutorOperation, dict[str, Any]]:
    if args.command == "stage":
        return RemoteExecutorOperation.STAGE_RUN, {
            "branch": args.branch,
            "commit": args.commit,
        }
    if args.command == "submit":
        return RemoteExecutorOperation.SUBMIT_JOB, {"script": args.script}
    if args.command == "status":
        return RemoteExecutorOperation.JOB_STATUS, {"job_id": args.job_id}
    if args.command == "log":
        return RemoteExecutorOperation.STREAM_LOG, {
            "path": args.path,
            "lines": args.lines,
        }
    if args.command == "fetch":
        return RemoteExecutorOperation.FETCH_ARTIFACTS, {
            "remote_path": args.remote_path,
            "local_path": args.local_path,
        }
    if args.command == "cancel":
        return RemoteExecutorOperation.CANCEL_JOB, {
            "job_id": args.job_id,
            "confirm_job_id": args.confirm_job_id,
        }
    raise ValueError(f"unsupported command '{args.command}'")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_remote_control_config()
        operation, payload = _operation_and_payload(args)
        result = invoke_remote_control(config, operation, payload)
    except ValueError as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    if result.status is ToolStatus.SUCCESS:
        return 0
    return 3 if result.status is ToolStatus.UNAVAILABLE else 2


if __name__ == "__main__":
    raise SystemExit(main())
