"""Typed remote-executor tools for batch-first experiment control.

The tool models SSH and Slurm as observable external systems.  It does not
store credentials, interpolate user input into a shell command, or retry a
failed operation.  A transport is injected so the control protocol can be
tested without a cluster connection.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Protocol, Sequence

from xgap.tools.contracts import ToolContext, ToolEffect, ToolResult, ToolSpec, ToolStatus


REMOTE_EXECUTOR_TOOL = "remote.executor"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SAFE_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_JOB_ID = re.compile(r"^[0-9]+$")
_SAFE_REMOTE_PATH = re.compile(r"^/[A-Za-z0-9._/-]+$")
_SAFE_ENV_VALUE = re.compile(r"^[A-Za-z0-9._/:+-]+$")
_ALLOWED_SUBMISSION_ENVIRONMENT = frozenset(
    {"XGAP_PYTHON", "XGAP_PYTHON_MODULE", "XGAP_JAVA_MODULE"}
)


class RemoteExecutorOperation(str, Enum):
    STAGE_RUN = "stage_run"
    SUBMIT_JOB = "submit_job"
    JOB_STATUS = "job_status"
    STREAM_LOG = "stream_log"
    CANCEL_JOB = "cancel_job"
    FETCH_ARTIFACTS = "fetch_artifacts"


class RemoteJobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class RemoteOperationError(ValueError):
    """A normalized remote failure with the number of consumed control calls."""

    def __init__(self, message: str, *, control_calls: int = 0):
        super().__init__(message)
        self.control_calls = control_calls


@dataclass(frozen=True)
class RemoteCommandResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    elapsed_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class RemoteTransport(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
    ) -> RemoteCommandResult:
        """Run one argv-vector on the remote host exactly once."""

    def fetch(
        self,
        remote_path: str,
        local_path: Path,
        *,
        timeout_seconds: float,
    ) -> RemoteCommandResult:
        """Fetch one validated remote artifact path exactly once."""


def _bounded(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]"


@dataclass(frozen=True)
class SshTransport:
    """Noninteractive OpenSSH transport with a fixed, user-owned host alias."""

    host_alias: str
    ssh_binary: str = "ssh"
    scp_binary: str = "scp"
    remote_python: str = "python3"
    max_output_bytes: int = 65536

    def __post_init__(self) -> None:
        if not _SAFE_ID.fullmatch(self.host_alias) or self.host_alias.startswith("-"):
            raise ValueError("SSH host alias contains unsupported characters")
        if not (
            _SAFE_ID.fullmatch(self.remote_python)
            or _SAFE_REMOTE_PATH.fullmatch(self.remote_python)
        ):
            raise ValueError("remote Python command contains unsupported characters")
        if self.max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
    ) -> RemoteCommandResult:
        normalized = tuple(str(item) for item in argv)
        if not normalized or any("\x00" in item or "\n" in item for item in normalized):
            raise ValueError("remote argv must be nonempty and contain no NUL or newline")
        encoded_argv = json.dumps(list(normalized), separators=(",", ":"))
        remote_program = (
            "import json, os\n"
            f"argv = json.loads({encoded_argv!r})\n"
            "os.execvp(argv[0], argv)\n"
        )
        return self._run_local(
            (
                self.ssh_binary,
                "-o",
                "BatchMode=yes",
                "--",
                self.host_alias,
                f"{self.remote_python} -",
            ),
            timeout_seconds=timeout_seconds,
            input_text=remote_program,
        )

    def fetch(
        self,
        remote_path: str,
        local_path: Path,
        *,
        timeout_seconds: float,
    ) -> RemoteCommandResult:
        if not _SAFE_REMOTE_PATH.fullmatch(remote_path) or ".." in PurePosixPath(remote_path).parts:
            raise ValueError("remote artifact path is not safe for transfer")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        return self._run_local(
            (
                self.scp_binary,
                "-r",
                "--",
                f"{self.host_alias}:{remote_path}",
                str(local_path),
            ),
            timeout_seconds=timeout_seconds,
        )

    def _run_local(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
        input_text: str | None = None,
    ) -> RemoteCommandResult:
        if timeout_seconds <= 0:
            raise ValueError("remote timeout must be positive")
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                list(argv),
                input=input_text,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            exit_code = 124
            stdout = exc.stdout or ""
            stderr = (exc.stderr or "") + f"\noperation timed out after {timeout_seconds}s"
        except OSError as exc:
            exit_code = 127
            stdout = ""
            stderr = str(exc)
        return RemoteCommandResult(
            exit_code=exit_code,
            stdout=_bounded(str(stdout), self.max_output_bytes),
            stderr=_bounded(str(stderr), self.max_output_bytes),
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )


class RemoteExecutorPlugin(Protocol):
    @property
    def executor_id(self) -> str:
        """Stable remote environment identity."""

    @property
    def supported_operations(self) -> frozenset[RemoteExecutorOperation]:
        """Operations this executor implements."""

    def invoke(
        self,
        operation: RemoteExecutorOperation,
        payload: Mapping[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Invoke one remote-control operation."""


class RemoteExecutorRegistry:
    def __init__(self) -> None:
        self._executors: dict[str, RemoteExecutorPlugin] = {}

    def register(self, executor: RemoteExecutorPlugin) -> None:
        if not _SAFE_ID.fullmatch(executor.executor_id):
            raise ValueError("remote executor id contains unsupported characters")
        if executor.executor_id in self._executors:
            raise ValueError(f"remote executor '{executor.executor_id}' is already registered")
        self._executors[executor.executor_id] = executor

    def describe(self) -> dict[str, list[str]]:
        return {
            executor_id: sorted(item.value for item in executor.supported_operations)
            for executor_id, executor in sorted(self._executors.items())
        }

    def invoke(
        self,
        executor_id: str,
        operation: RemoteExecutorOperation,
        payload: Mapping[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        executor = self._executors.get(executor_id)
        if executor is None:
            return ToolResult.unavailable(
                REMOTE_EXECUTOR_TOOL,
                f"remote executor '{executor_id}' is not registered",
            )
        if operation not in executor.supported_operations:
            return ToolResult.unavailable(
                REMOTE_EXECUTOR_TOOL,
                f"remote executor '{executor_id}' does not support '{operation.value}'",
            )
        return executor.invoke(operation, payload, context)


@dataclass
class SlurmRemoteExecutor:
    """Batch-first Slurm plugin over an injected remote transport."""

    executor_id: str
    transport: RemoteTransport
    remote_repo_root: str
    remote_artifact_root: str
    local_artifact_root: Path
    allowed_sbatch_scripts: frozenset[str]
    submission_environment: Mapping[str, str] = field(default_factory=dict)
    job_environment_allowlist: Mapping[str, frozenset[str]] = field(
        default_factory=dict
    )
    allow_cancel: bool = False
    timeout_seconds: float = 30.0
    supported_operations: frozenset[RemoteExecutorOperation] = field(
        default_factory=lambda: frozenset(RemoteExecutorOperation)
    )

    def __post_init__(self) -> None:
        if not _SAFE_ID.fullmatch(self.executor_id):
            raise ValueError("remote executor id contains unsupported characters")
        self.remote_repo_root = self._absolute_remote_path(self.remote_repo_root, "repo root")
        self.remote_artifact_root = self._absolute_remote_path(
            self.remote_artifact_root,
            "artifact root",
        )
        self.local_artifact_root = self.local_artifact_root.resolve()
        if self.timeout_seconds <= 0:
            raise ValueError("remote executor timeout must be positive")
        if not self.allowed_sbatch_scripts:
            raise ValueError("at least one sbatch script must be allowlisted")
        for script in self.allowed_sbatch_scripts:
            self._relative_remote_path(script, "sbatch script")
        normalized_environment: dict[str, str] = {}
        for key, value in self.submission_environment.items():
            if key not in _ALLOWED_SUBMISSION_ENVIRONMENT:
                raise ValueError(f"submission environment key '{key}' is not allowlisted")
            if not isinstance(value, str) or not _SAFE_ENV_VALUE.fullmatch(value):
                raise ValueError(f"submission environment value for '{key}' is unsafe")
            normalized_environment[key] = value
        self.submission_environment = normalized_environment
        normalized_job_allowlist: dict[str, frozenset[str]] = {}
        for script, keys in self.job_environment_allowlist.items():
            if script not in self.allowed_sbatch_scripts:
                raise ValueError(
                    "job environment allowlist references a non-allowlisted script"
                )
            normalized_keys: set[str] = set()
            for key in keys:
                if (
                    not isinstance(key, str)
                    or not key.startswith("XGAP_")
                    or not key.replace("_", "").isalnum()
                ):
                    raise ValueError("job environment key is unsafe")
                if key in self.submission_environment:
                    raise ValueError(
                        "job environment key duplicates fixed submission environment"
                    )
                normalized_keys.add(key)
            normalized_job_allowlist[script] = frozenset(normalized_keys)
        self.job_environment_allowlist = normalized_job_allowlist

    def invoke(
        self,
        operation: RemoteExecutorOperation,
        payload: Mapping[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        del context
        started = time.perf_counter()
        try:
            if operation is RemoteExecutorOperation.CANCEL_JOB and not self.allow_cancel:
                return ToolResult.unavailable(
                    REMOTE_EXECUTOR_TOOL,
                    "job cancellation is disabled for this executor",
                )
            if operation is RemoteExecutorOperation.STAGE_RUN:
                value, calls = self._stage_run(payload)
            elif operation is RemoteExecutorOperation.SUBMIT_JOB:
                value, calls = self._submit_job(payload)
            elif operation is RemoteExecutorOperation.JOB_STATUS:
                value, calls = self._job_status(payload)
            elif operation is RemoteExecutorOperation.STREAM_LOG:
                value, calls = self._stream_log(payload)
            elif operation is RemoteExecutorOperation.CANCEL_JOB:
                value, calls = self._cancel_job(payload)
            elif operation is RemoteExecutorOperation.FETCH_ARTIFACTS:
                value, calls = self._fetch_artifacts(payload)
            else:  # pragma: no cover - exhaustive enum guard
                return ToolResult.unavailable(
                    REMOTE_EXECUTOR_TOOL,
                    f"unsupported remote operation '{operation.value}'",
                )
        except RemoteOperationError as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            return ToolResult(
                tool_name=REMOTE_EXECUTOR_TOOL,
                status=ToolStatus.ERROR,
                error=str(exc),
                metrics={
                    "control_elapsed_ms": elapsed_ms,
                    "control_calls": float(exc.control_calls),
                },
            )
        except ValueError as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            return ToolResult(
                tool_name=REMOTE_EXECUTOR_TOOL,
                status=ToolStatus.ERROR,
                error=str(exc),
                metrics={"control_elapsed_ms": elapsed_ms, "control_calls": 0.0},
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
        return ToolResult.success(
            REMOTE_EXECUTOR_TOOL,
            {"executor_id": self.executor_id, "operation": operation.value, **value},
            metrics={"control_elapsed_ms": elapsed_ms, "control_calls": float(calls)},
        )

    def _stage_run(self, payload: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
        branch = payload.get("branch")
        commit = payload.get("commit")
        if not isinstance(branch, str) or not _SAFE_BRANCH.fullmatch(branch) or ".." in branch:
            raise ValueError("branch contains unsupported characters")
        if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
            raise ValueError("commit must be a full lowercase 40-hex Git commit")

        calls = 1
        status = self._run(("git", "-C", self.remote_repo_root, "status", "--porcelain"))
        self._require_ok(status, "inspect remote checkout", control_calls=calls)
        if status.stdout.strip():
            raise RemoteOperationError(
                "remote experiment checkout is dirty; refusing to stage",
                control_calls=calls,
            )

        calls += 1
        fetched = self._run(
            ("git", "-C", self.remote_repo_root, "fetch", "--no-tags", "origin", branch)
        )
        self._require_ok(fetched, "fetch remote branch", control_calls=calls)

        calls += 1
        resolved = self._run(("git", "-C", self.remote_repo_root, "rev-parse", "FETCH_HEAD"))
        self._require_ok(resolved, "resolve fetched commit", control_calls=calls)
        if resolved.stdout.strip() != commit:
            raise RemoteOperationError(
                "fetched branch does not resolve to the requested commit",
                control_calls=calls,
            )

        calls += 1
        switched = self._run(
            ("git", "-C", self.remote_repo_root, "switch", "--detach", commit)
        )
        self._require_ok(switched, "switch remote checkout", control_calls=calls)
        return {"state": "staged", "branch": branch, "commit": commit}, calls

    def _submit_job(self, payload: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
        script = payload.get("script")
        if not isinstance(script, str) or script not in self.allowed_sbatch_scripts:
            raise ValueError("sbatch script is not allowlisted")
        raw_environment = payload.get("environment", {})
        if not isinstance(raw_environment, Mapping):
            raise ValueError("job environment must be an object")
        allowed_keys = self.job_environment_allowlist.get(script, frozenset())
        job_environment: dict[str, str] = {}
        for key, value in raw_environment.items():
            if not isinstance(key, str) or key not in allowed_keys:
                raise ValueError(
                    f"job environment key '{key}' is not allowlisted for this script"
                )
            if (
                not isinstance(value, str)
                or len(value) > 1024
                or not _SAFE_ENV_VALUE.fullmatch(value)
            ):
                raise ValueError(f"job environment value for '{key}' is unsafe")
            job_environment[key] = value
        remote_script = self._join_remote(self.remote_repo_root, script, "sbatch script")
        command = ["sbatch", "--parsable", "--chdir", self.remote_repo_root]
        combined_environment = {
            **self.submission_environment,
            **job_environment,
        }
        if combined_environment:
            exported = ",".join(
                f"{key}={value}"
                for key, value in sorted(combined_environment.items())
            )
            command.extend(("--export", f"ALL,{exported}"))
        command.append(remote_script)
        result = self._run(command)
        self._require_ok(result, "submit Slurm job", control_calls=1)
        raw_job_id = result.stdout.strip().split(";", 1)[0]
        if not _JOB_ID.fullmatch(raw_job_id):
            raise ValueError("sbatch returned an invalid job id")
        return {
            "state": "submitted",
            "job_id": raw_job_id,
            "script": script,
            "job_environment_keys": sorted(job_environment),
        }, 1

    def _job_status(self, payload: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
        job_id = self._validated_job_id(payload)
        queued = self._run(("squeue", "--noheader", "--jobs", job_id, "--format", "%T"))
        self._require_ok(queued, "query active Slurm job", control_calls=1)
        raw_state = queued.stdout.strip().splitlines()
        if raw_state:
            state_text = raw_state[0].strip()
            return {
                "job_id": job_id,
                "state": self._normalize_job_state(state_text).value,
                "slurm_state": state_text,
                "terminal": False,
            }, 1

        accounted = self._run(
            (
                "sacct",
                "--noheader",
                "--parsable2",
                "--jobs",
                job_id,
                "--format",
                "JobIDRaw,State,ExitCode,Elapsed",
            )
        )
        self._require_ok(accounted, "query completed Slurm job", control_calls=2)
        record = None
        for line in accounted.stdout.splitlines():
            fields = line.strip().split("|")
            if fields and fields[0] == job_id:
                record = fields
                break
        if record is None or len(record) < 4:
            return {
                "job_id": job_id,
                "state": RemoteJobState.UNKNOWN.value,
                "slurm_state": None,
                "terminal": False,
            }, 2
        state_text = record[1].strip()
        state = self._normalize_job_state(state_text)
        return {
            "job_id": job_id,
            "state": state.value,
            "slurm_state": state_text,
            "exit_code": record[2].strip(),
            "elapsed": record[3].strip(),
            "terminal": state
            in {RemoteJobState.SUCCEEDED, RemoteJobState.FAILED, RemoteJobState.CANCELLED},
        }, 2

    def _stream_log(self, payload: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
        raw_path = payload.get("path")
        raw_lines = payload.get("lines", 200)
        if not isinstance(raw_path, str):
            raise ValueError("log path must be a relative string")
        try:
            lines = int(raw_lines)
        except (TypeError, ValueError) as exc:
            raise ValueError("log line count must be an integer") from exc
        if not 1 <= lines <= 500:
            raise ValueError("log line count must be between 1 and 500")
        remote_path = self._join_remote(self.remote_repo_root, raw_path, "log path")
        result = self._run(("tail", "--lines", str(lines), remote_path))
        self._require_ok(result, "read remote log", control_calls=1)
        return {"path": raw_path, "lines": result.stdout.splitlines()}, 1

    def _cancel_job(self, payload: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
        job_id = self._validated_job_id(payload)
        if payload.get("confirm_job_id") != job_id:
            raise ValueError("cancel_job requires confirm_job_id equal to job_id")
        result = self._run(("scancel", job_id))
        self._require_ok(result, "cancel Slurm job", control_calls=1)
        return {"job_id": job_id, "state": "cancel_requested"}, 1

    def _fetch_artifacts(self, payload: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
        remote_relative = payload.get("remote_path")
        local_relative = payload.get("local_path")
        if not isinstance(remote_relative, str) or not isinstance(local_relative, str):
            raise ValueError("remote_path and local_path must be relative strings")
        remote_path = self._join_remote(
            self.remote_artifact_root,
            remote_relative,
            "artifact path",
        )
        local_path = self._join_local(local_relative)
        if local_path.exists():
            raise ValueError("local artifact destination already exists; refusing to overwrite")
        result = self.transport.fetch(
            remote_path,
            local_path,
            timeout_seconds=self.timeout_seconds,
        )
        self._require_ok(result, "fetch remote artifacts", control_calls=1)
        return {
            "remote_path": remote_relative,
            "local_path": str(local_path),
            "state": "fetched",
        }, 1

    def _run(self, argv: Sequence[str]) -> RemoteCommandResult:
        return self.transport.run(argv, timeout_seconds=self.timeout_seconds)

    @staticmethod
    def _require_ok(
        result: RemoteCommandResult,
        action: str,
        *,
        control_calls: int,
    ) -> None:
        if result.ok:
            return
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.exit_code}"
        raise RemoteOperationError(
            f"failed to {action}: {_bounded(detail, 2048)}",
            control_calls=control_calls,
        )

    @staticmethod
    def _validated_job_id(payload: Mapping[str, Any]) -> str:
        job_id = payload.get("job_id")
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            raise ValueError("job_id must contain digits only")
        return job_id

    @staticmethod
    def _normalize_job_state(raw_state: str) -> RemoteJobState:
        state = raw_state.upper().split("+", 1)[0].split(None, 1)[0]
        if state in {"PENDING", "CONFIGURING", "REQUEUED", "RESIZING"}:
            return RemoteJobState.PENDING
        if state in {"RUNNING", "COMPLETING", "SUSPENDED"}:
            return RemoteJobState.RUNNING
        if state == "COMPLETED":
            return RemoteJobState.SUCCEEDED
        if state in {"CANCELLED", "PREEMPTED"}:
            return RemoteJobState.CANCELLED
        if state in {
            "FAILED",
            "BOOT_FAIL",
            "DEADLINE",
            "NODE_FAIL",
            "OUT_OF_MEMORY",
            "REVOKED",
            "TIMEOUT",
        }:
            return RemoteJobState.FAILED
        return RemoteJobState.UNKNOWN

    @staticmethod
    def _absolute_remote_path(value: str, field_name: str) -> str:
        path = PurePosixPath(value)
        if (
            not path.is_absolute()
            or ".." in path.parts
            or not _SAFE_REMOTE_PATH.fullmatch(str(path))
        ):
            raise ValueError(f"{field_name} must be a safe absolute POSIX path")
        return str(path)

    @staticmethod
    def _relative_remote_path(value: str, field_name: str) -> PurePosixPath:
        path = PurePosixPath(value)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise ValueError(f"{field_name} must remain below its configured root")
        if any(not _SAFE_ID.fullmatch(part) for part in path.parts):
            raise ValueError(f"{field_name} contains unsupported characters")
        return path

    @classmethod
    def _join_remote(cls, root: str, value: str, field_name: str) -> str:
        return str(PurePosixPath(root) / cls._relative_remote_path(value, field_name))

    def _join_local(self, value: str) -> Path:
        relative = Path(value)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise ValueError("local artifact path must remain below its configured root")
        candidate = (self.local_artifact_root / relative).resolve()
        if candidate != self.local_artifact_root and self.local_artifact_root not in candidate.parents:
            raise ValueError("local artifact path escaped its configured root")
        return candidate


@dataclass
class RemoteExecutorTool:
    executors: RemoteExecutorRegistry

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=REMOTE_EXECUTOR_TOOL,
            description="Stage, submit, observe, and retrieve allowlisted remote batch experiments",
            input_schema={
                "type": "object",
                "required": ["executor_id", "operation"],
                "properties": {
                    "executor_id": {"type": "string"},
                    "operation": {
                        "enum": [operation.value for operation in RemoteExecutorOperation]
                    },
                    "payload": {"type": "object"},
                },
            },
            output_kind="remote_execution_observation",
            effect=ToolEffect.STATEFUL,
            remote=True,
            tags=("remote", "slurm", "experiment"),
        )

    def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        executor_id = arguments.get("executor_id")
        raw_operation = arguments.get("operation")
        payload = arguments.get("payload", {})
        if not isinstance(executor_id, str) or not executor_id.strip():
            return ToolResult.error_result(REMOTE_EXECUTOR_TOOL, "executor_id must be nonempty")
        try:
            operation = RemoteExecutorOperation(str(raw_operation))
        except ValueError:
            return ToolResult.error_result(
                REMOTE_EXECUTOR_TOOL,
                f"unknown remote executor operation '{raw_operation}'",
            )
        if not isinstance(payload, Mapping):
            return ToolResult.error_result(REMOTE_EXECUTOR_TOOL, "payload must be a mapping")
        return self.executors.invoke(executor_id, operation, payload, context)
