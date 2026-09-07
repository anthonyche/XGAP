from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import pytest

from xgap.tools import (
    REMOTE_EXECUTOR_TOOL,
    RemoteCommandResult,
    RemoteExecutorOperation,
    RemoteExecutorRegistry,
    RemoteExecutorTool,
    SlurmRemoteExecutor,
    SshTransport,
    ToolContext,
    ToolStatus,
)


COMMIT = "465e2e2454b74aaf7a1c055797740bde8ca5ace0"
SELECTED_SESSION_SCRIPT = (
    "scripts/slurm/run_m15_native_selected_interpretation_session.sbatch"
)


@dataclass
class FakeTransport:
    results: list[RemoteCommandResult] = field(default_factory=list)
    calls: list[tuple[str, ...]] = field(default_factory=list)
    fetches: list[tuple[str, Path]] = field(default_factory=list)

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
    ) -> RemoteCommandResult:
        assert timeout_seconds == 30.0
        self.calls.append(tuple(argv))
        if not self.results:
            raise AssertionError("unexpected remote call")
        return self.results.pop(0)

    def fetch(
        self,
        remote_path: str,
        local_path: Path,
        *,
        timeout_seconds: float,
    ) -> RemoteCommandResult:
        assert timeout_seconds == 30.0
        self.fetches.append((remote_path, local_path))
        if not self.results:
            raise AssertionError("unexpected fetch")
        return self.results.pop(0)


def _context() -> ToolContext:
    return ToolContext(goal_id="remote-g", step=1, call_id="remote-c")


def _executor(
    tmp_path: Path,
    transport: FakeTransport,
    *,
    allow_cancel: bool = False,
    submission_environment: dict[str, str] | None = None,
    allowed_sbatch_scripts: frozenset[str] | None = None,
    job_environment_allowlist: dict[str, frozenset[str]] | None = None,
):
    return SlurmRemoteExecutor(
        executor_id="cwru-pioneer",
        transport=transport,
        remote_repo_root="/home/researcher/XGAP-m15",
        remote_artifact_root="/home/researcher/XGAP-m15/runs",
        local_artifact_root=tmp_path,
        allowed_sbatch_scripts=allowed_sbatch_scripts
        or frozenset({"scripts/slurm/run_m15_core_smoke.sbatch"}),
        submission_environment=submission_environment or {},
        job_environment_allowlist=job_environment_allowlist or {},
        allow_cancel=allow_cancel,
    )


def _tool(executor: SlurmRemoteExecutor) -> RemoteExecutorTool:
    registry = RemoteExecutorRegistry()
    registry.register(executor)
    return RemoteExecutorTool(registry)


def _invoke(
    tool: RemoteExecutorTool,
    operation: RemoteExecutorOperation,
    payload: dict[str, object],
):
    return tool.invoke(
        {
            "executor_id": "cwru-pioneer",
            "operation": operation.value,
            "payload": payload,
        },
        _context(),
    )


def test_stage_run_checks_clean_commit_before_detached_switch(tmp_path: Path) -> None:
    transport = FakeTransport(
        results=[
            RemoteCommandResult(0, ""),
            RemoteCommandResult(0),
            RemoteCommandResult(0, COMMIT + "\n"),
            RemoteCommandResult(0),
        ]
    )
    result = _invoke(
        _tool(_executor(tmp_path, transport)),
        RemoteExecutorOperation.STAGE_RUN,
        {"branch": "codex/m15-agentic-federated-core", "commit": COMMIT},
    )

    assert result.status is ToolStatus.SUCCESS
    assert result.value["state"] == "staged"
    assert result.metrics["control_calls"] == 4.0
    assert transport.calls[-1][-3:] == ("switch", "--detach", COMMIT)


def test_stage_run_refuses_dirty_checkout_without_mutating_it(tmp_path: Path) -> None:
    transport = FakeTransport(results=[RemoteCommandResult(0, " M user-file\n")])
    result = _invoke(
        _tool(_executor(tmp_path, transport)),
        RemoteExecutorOperation.STAGE_RUN,
        {"branch": "codex/m15-agentic-federated-core", "commit": COMMIT},
    )

    assert result.status is ToolStatus.ERROR
    assert "dirty" in str(result.error)
    assert result.metrics["control_calls"] == 1.0
    assert len(transport.calls) == 1


def test_submit_job_is_allowlisted_and_returns_normalized_job_id(tmp_path: Path) -> None:
    transport = FakeTransport(results=[RemoteCommandResult(0, "4217;pioneer\n")])
    tool = _tool(_executor(tmp_path, transport))
    result = _invoke(
        tool,
        RemoteExecutorOperation.SUBMIT_JOB,
        {"script": "scripts/slurm/run_m15_core_smoke.sbatch"},
    )
    rejected = _invoke(
        tool,
        RemoteExecutorOperation.SUBMIT_JOB,
        {"script": "scripts/slurm/arbitrary.sbatch"},
    )

    assert result.status is ToolStatus.SUCCESS
    assert result.value["job_id"] == "4217"
    assert transport.calls[0] == (
        "sbatch",
        "--parsable",
        "--chdir",
        "/home/researcher/XGAP-m15",
        "/home/researcher/XGAP-m15/scripts/slurm/run_m15_core_smoke.sbatch",
    )
    assert rejected.status is ToolStatus.ERROR
    assert len(transport.calls) == 1


def test_submit_job_exports_only_configured_environment(tmp_path: Path) -> None:
    transport = FakeTransport(results=[RemoteCommandResult(0, "4218\n")])
    executor = _executor(
        tmp_path,
        transport,
        submission_environment={
            "XGAP_PYTHON": "/home/researcher/venvs/xgap-core/bin/python",
            "XGAP_PYTHON_MODULE": "Miniconda3",
        },
    )
    result = _invoke(
        _tool(executor),
        RemoteExecutorOperation.SUBMIT_JOB,
        {"script": "scripts/slurm/run_m15_core_smoke.sbatch"},
    )
    assert result.status is ToolStatus.SUCCESS
    assert transport.calls[0][4:6] == (
        "--export",
        "ALL,XGAP_PYTHON=/home/researcher/venvs/xgap-core/bin/python,"
        "XGAP_PYTHON_MODULE=Miniconda3",
    )

    with pytest.raises(ValueError, match="not allowlisted"):
        _executor(
            tmp_path,
            FakeTransport(),
            submission_environment={"LD_PRELOAD": "/tmp/injected"},
        )


def test_submit_job_accepts_only_script_scoped_authority_environment(
    tmp_path: Path,
) -> None:
    authority_keys = frozenset(
        {
            "XGAP_M15_SELECTED_TRAINING_MEMORY",
            "XGAP_M15_SELECTED_MEMORY_SHA256",
            "XGAP_M15_SELECTED_SESSION_ID",
            "XGAP_M15_SELECTED_STRUCTURAL_CANDIDATE",
            "XGAP_M15_SELECTED_PREDICATE_CANDIDATE",
            "XGAP_M15_SELECTED_AUTHORITY_SOURCE_ID",
        }
    )
    environment = {
        "XGAP_M15_SELECTED_TRAINING_MEMORY": (
            "/home/researcher/XGAP-m15/runs/source/training_memory_view.json"
        ),
        "XGAP_M15_SELECTED_MEMORY_SHA256": "a" * 64,
        "XGAP_M15_SELECTED_SESSION_ID": "m15-e5d-session-v1",
        "XGAP_M15_SELECTED_STRUCTURAL_CANDIDATE": (
            "constraint:single-transfer-at-least-50000"
        ),
        "XGAP_M15_SELECTED_PREDICATE_CANDIDATE": (
            "predicate:transferred_to"
        ),
        "XGAP_M15_SELECTED_AUTHORITY_SOURCE_ID": (
            "author:researcher:explicit-choice-a-v1"
        ),
    }
    transport = FakeTransport(results=[RemoteCommandResult(0, "4220\n")])
    executor = _executor(
        tmp_path,
        transport,
        submission_environment={"XGAP_JAVA_MODULE": "Java/17.0.6"},
        allowed_sbatch_scripts=frozenset(
            {
                "scripts/slurm/run_m15_core_smoke.sbatch",
                SELECTED_SESSION_SCRIPT,
            }
        ),
        job_environment_allowlist={
            SELECTED_SESSION_SCRIPT: authority_keys,
        },
    )
    result = _invoke(
        _tool(executor),
        RemoteExecutorOperation.SUBMIT_JOB,
        {"script": SELECTED_SESSION_SCRIPT, "environment": environment},
    )

    assert result.status is ToolStatus.SUCCESS
    assert result.value["job_environment_keys"] == sorted(authority_keys)
    export_value = transport.calls[0][5]
    assert export_value.startswith("ALL,")
    for key, value in {"XGAP_JAVA_MODULE": "Java/17.0.6", **environment}.items():
        assert f"{key}={value}" in export_value.split(",")

    core_tool = _tool(
        _executor(
            tmp_path,
            FakeTransport(),
            allowed_sbatch_scripts=frozenset(
                {
                    "scripts/slurm/run_m15_core_smoke.sbatch",
                    SELECTED_SESSION_SCRIPT,
                }
            ),
            job_environment_allowlist={
                SELECTED_SESSION_SCRIPT: authority_keys,
            },
        )
    )
    wrong_script = _invoke(
        core_tool,
        RemoteExecutorOperation.SUBMIT_JOB,
        {
            "script": "scripts/slurm/run_m15_core_smoke.sbatch",
            "environment": {
                "XGAP_M15_SELECTED_PREDICATE_CANDIDATE": (
                    "predicate:transferred_to"
                )
            },
        },
    )
    unsafe_value = _invoke(
        _tool(executor),
        RemoteExecutorOperation.SUBMIT_JOB,
        {
            "script": SELECTED_SESSION_SCRIPT,
            "environment": {
                "XGAP_M15_SELECTED_PREDICATE_CANDIDATE": "bad,value"
            },
        },
    )
    assert wrong_script.status is ToolStatus.ERROR
    assert "not allowlisted for this script" in str(wrong_script.error)
    assert unsafe_value.status is ToolStatus.ERROR
    assert "unsafe" in str(unsafe_value.error)


def test_job_status_uses_squeue_then_terminal_sacct(tmp_path: Path) -> None:
    running_transport = FakeTransport(results=[RemoteCommandResult(0, "RUNNING\n")])
    running = _invoke(
        _tool(_executor(tmp_path, running_transport)),
        RemoteExecutorOperation.JOB_STATUS,
        {"job_id": "4217"},
    )
    assert running.value["state"] == "running"
    assert running.value["terminal"] is False

    terminal_transport = FakeTransport(
        results=[
            RemoteCommandResult(0, ""),
            RemoteCommandResult(0, "4217|COMPLETED|0:0|00:00:04\n4217.batch|COMPLETED|0:0|00:00:03\n"),
        ]
    )
    terminal = _invoke(
        _tool(_executor(tmp_path, terminal_transport)),
        RemoteExecutorOperation.JOB_STATUS,
        {"job_id": "4217"},
    )
    assert terminal.value["state"] == "succeeded"
    assert terminal.value["terminal"] is True
    assert terminal.metrics["control_calls"] == 2.0


def test_log_and_artifact_paths_cannot_escape_roots(tmp_path: Path) -> None:
    transport = FakeTransport(
        results=[RemoteCommandResult(0, "line one\nline two\n"), RemoteCommandResult(0)]
    )
    tool = _tool(_executor(tmp_path, transport))
    log = _invoke(
        tool,
        RemoteExecutorOperation.STREAM_LOG,
        {"path": "runs/job-4217/job.log", "lines": 2},
    )
    fetched = _invoke(
        tool,
        RemoteExecutorOperation.FETCH_ARTIFACTS,
        {"remote_path": "job-4217", "local_path": "job-4217"},
    )
    escaped = _invoke(
        tool,
        RemoteExecutorOperation.FETCH_ARTIFACTS,
        {"remote_path": "../private", "local_path": "private"},
    )

    assert log.value["lines"] == ["line one", "line two"]
    assert fetched.status is ToolStatus.SUCCESS
    assert transport.fetches == [
        ("/home/researcher/XGAP-m15/runs/job-4217", tmp_path / "job-4217")
    ]
    assert escaped.status is ToolStatus.ERROR

    (tmp_path / "existing").mkdir()
    overwrite = _invoke(
        tool,
        RemoteExecutorOperation.FETCH_ARTIFACTS,
        {"remote_path": "job-4217", "local_path": "existing"},
    )
    assert overwrite.status is ToolStatus.ERROR
    assert "overwrite" in str(overwrite.error)
    assert len(transport.fetches) == 1


def test_cancel_requires_executor_permission_and_matching_confirmation(tmp_path: Path) -> None:
    disabled_transport = FakeTransport()
    disabled = _invoke(
        _tool(_executor(tmp_path, disabled_transport)),
        RemoteExecutorOperation.CANCEL_JOB,
        {"job_id": "4217", "confirm_job_id": "4217"},
    )
    assert disabled.status is ToolStatus.UNAVAILABLE
    assert disabled_transport.calls == []

    enabled_transport = FakeTransport(results=[RemoteCommandResult(0)])
    enabled_tool = _tool(_executor(tmp_path, enabled_transport, allow_cancel=True))
    mismatch = _invoke(
        enabled_tool,
        RemoteExecutorOperation.CANCEL_JOB,
        {"job_id": "4217", "confirm_job_id": "9999"},
    )
    cancelled = _invoke(
        enabled_tool,
        RemoteExecutorOperation.CANCEL_JOB,
        {"job_id": "4217", "confirm_job_id": "4217"},
    )
    assert mismatch.status is ToolStatus.ERROR
    assert cancelled.value["state"] == "cancel_requested"
    assert enabled_transport.calls == [("scancel", "4217")]


def test_registry_unknown_executor_and_transport_alias_validation(tmp_path: Path) -> None:
    registry = RemoteExecutorRegistry()
    result = RemoteExecutorTool(registry).invoke(
        {"executor_id": "missing", "operation": "job_status", "payload": {"job_id": "1"}},
        _context(),
    )
    assert result.status is ToolStatus.UNAVAILABLE
    assert result.tool_name == REMOTE_EXECUTOR_TOOL
    with pytest.raises(ValueError, match="host alias"):
        SshTransport("-oProxyCommand=bad")
