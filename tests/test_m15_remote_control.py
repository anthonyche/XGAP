from __future__ import annotations

from pathlib import Path

import pytest

from xgap.experiments.remote_control import (
    DEFAULT_ALLOWED_SBATCH_SCRIPTS,
    RemoteControlConfig,
    _operation_and_payload,
    _parser,
    build_remote_executor,
    invoke_remote_control,
    load_remote_control_config,
)
from xgap.tools import RemoteCommandResult, RemoteExecutorOperation, ToolStatus


class FakeTransport:
    def __init__(self, responses: list[RemoteCommandResult]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def run(self, argv, *, timeout_seconds):
        self.calls.append(("run", tuple(argv)))
        return self.responses.pop(0)

    def fetch(self, remote_path, local_path, *, timeout_seconds):
        self.calls.append(("fetch", (remote_path, str(local_path))))
        return self.responses.pop(0)


def _config(tmp_path: Path, **overrides) -> RemoteControlConfig:
    values = {
        "host_alias": "cwru-pioneer",
        "remote_repo_root": "/home/user/XGAP",
        "remote_artifact_root": "/home/user/XGAP/runs",
        "local_artifact_root": tmp_path,
    }
    values.update(overrides)
    return RemoteControlConfig(**values)


def test_config_requires_remote_identity_and_repo_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="HOST_ALIAS"):
        load_remote_control_config({}, working_directory=tmp_path)
    with pytest.raises(ValueError, match="REPO_ROOT"):
        load_remote_control_config(
            {"XGAP_REMOTE_HOST_ALIAS": "cwru-pioneer"},
            working_directory=tmp_path,
        )


def test_config_uses_vllm_python_and_scoped_defaults(tmp_path: Path) -> None:
    config = load_remote_control_config(
        {
            "XGAP_REMOTE_HOST_ALIAS": "cwru-pioneer",
            "XGAP_REMOTE_REPO_ROOT": "/home/hxc859/XGAP-m15",
            "XGAP_REMOTE_PYTHON": "/home/hxc859/venvs/xgap-vllm/bin/python",
            "XGAP_REMOTE_JOB_PYTHON": "/home/hxc859/venvs/xgap-core/bin/python",
        },
        working_directory=tmp_path,
    )
    assert config.remote_artifact_root == "/home/hxc859/XGAP-m15/runs"
    assert config.local_artifact_root == tmp_path / "runs" / "remote-fetch"
    assert config.remote_python.endswith("/xgap-vllm/bin/python")
    assert config.allowed_sbatch_scripts == DEFAULT_ALLOWED_SBATCH_SCRIPTS
    assert config.submission_environment == {
        "XGAP_PYTHON": "/home/hxc859/venvs/xgap-core/bin/python",
        "XGAP_PYTHON_MODULE": "Miniconda3",
    }
    assert config.allow_cancel is False


def test_default_allowlist_includes_only_scoped_m15_bootstrap_jobs() -> None:
    assert DEFAULT_ALLOWED_SBATCH_SCRIPTS == (
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
    )
    probe = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "slurm"
        / "probe_m15_native_services.sbatch"
    ).read_text(encoding="utf-8")
    assert "native_service_prerequisites_ready" in probe
    assert "outbound_download_tested=false" in probe
    assert "podman run" not in probe
    assert "docker run" not in probe
    preparation = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "slurm"
        / "prepare_m15_native_artifacts.sbatch"
    ).read_text(encoding="utf-8")
    assert "XGAP_PREPARE_M15_NATIVE_ARTIFACTS=1" in preparation
    assert "archives_extracted=false" in preparation
    assert "services_started=false" in preparation
    service_run = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "slurm"
        / "run_m15_native_services.sbatch"
    ).read_text(encoding="utf-8")
    assert "XGAP_RUN_M15_NATIVE_SERVICES=1" in service_run
    assert "SLURM_TMPDIR" in service_run
    assert "runtime_removed" in service_run
    adaptive_run = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "slurm"
        / "run_m15_native_adaptive.sbatch"
    ).read_text(encoding="utf-8")
    assert "XGAP_M15_WORKLOAD_MODE=adaptive" in adaptive_run
    assert "run_m15_native_services.sbatch" in adaptive_run
    assert "SLURM_SUBMIT_DIR" in adaptive_run
    assert "BASH_SOURCE" not in adaptive_run
    scaled_run = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "slurm"
        / "run_m15_native_scaled_adaptive.sbatch"
    ).read_text(encoding="utf-8")
    assert "XGAP_M15_WORKLOAD_MODE=scaled_adaptive" in scaled_run
    assert "SLURM_SUBMIT_DIR" in scaled_run
    assert "BASH_SOURCE" not in scaled_run
    matrix_run = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "slurm"
        / "run_m15_native_method_matrix.sbatch"
    ).read_text(encoding="utf-8")
    assert "XGAP_M15_WORKLOAD_MODE=scaled_method_matrix" in matrix_run
    assert "SLURM_SUBMIT_DIR" in matrix_run
    assert "BASH_SOURCE" not in matrix_run
    campaign_run = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "slurm"
        / "run_m15_native_campaign_session.sbatch"
    ).read_text(encoding="utf-8")
    assert "XGAP_M15_WORKLOAD_MODE=scaled_campaign_session" in campaign_run
    assert "XGAP_M15_CAMPAIGN_SESSION_ID" in campaign_run
    assert "SLURM_SUBMIT_DIR" in campaign_run
    assert "BASH_SOURCE" not in campaign_run
    assert "scripts/slurm/run_m15_native_campaign_session.sbatch" in (
        DEFAULT_ALLOWED_SBATCH_SCRIPTS
    )
    query_bound_run = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "slurm"
        / "run_m15_native_query_bound_session.sbatch"
    ).read_text(encoding="utf-8")
    assert "XGAP_M15_WORKLOAD_MODE=scaled_query_bound_session" in (
        query_bound_run
    )
    assert "SLURM_SUBMIT_DIR" in query_bound_run
    assert "BASH_SOURCE" not in query_bound_run
    assert "scripts/slurm/run_m15_native_query_bound_session.sbatch" in (
        DEFAULT_ALLOWED_SBATCH_SCRIPTS
    )
    parameterized_run = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "slurm"
        / "run_m15_native_parameterized_stream.sbatch"
    ).read_text(encoding="utf-8")
    assert "XGAP_M15_WORKLOAD_MODE=parameterized_stream" in parameterized_run
    assert "SLURM_SUBMIT_DIR" in parameterized_run
    assert "BASH_SOURCE" not in parameterized_run
    family_transfer_run = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "slurm"
        / "run_m15_native_family_transfer.sbatch"
    ).read_text(encoding="utf-8")
    assert "XGAP_M15_WORKLOAD_MODE=parameterized_family_transfer" in (
        family_transfer_run
    )
    assert "SLURM_SUBMIT_DIR" in family_transfer_run
    assert "BASH_SOURCE" not in family_transfer_run
    semantic_relaxation_run = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "slurm"
        / "run_m15_native_semantic_risk_relaxation.sbatch"
    ).read_text(encoding="utf-8")
    assert "XGAP_M15_WORKLOAD_MODE=semantic_risk_relaxation" in (
        semantic_relaxation_run
    )
    assert "SLURM_SUBMIT_DIR" in semantic_relaxation_run
    assert "BASH_SOURCE" not in semantic_relaxation_run
    predicate_relaxation_run = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "slurm"
        / "run_m15_native_semantic_predicate_relaxation.sbatch"
    ).read_text(encoding="utf-8")
    assert "XGAP_M15_WORKLOAD_MODE=semantic_predicate_relaxation" in (
        predicate_relaxation_run
    )
    assert "SLURM_SUBMIT_DIR" in predicate_relaxation_run
    assert "BASH_SOURCE" not in predicate_relaxation_run


def test_config_enables_cancel_only_with_exact_opt_in(tmp_path: Path) -> None:
    base = {
        "XGAP_REMOTE_HOST_ALIAS": "cwru-pioneer",
        "XGAP_REMOTE_REPO_ROOT": "/home/user/XGAP",
    }
    assert not load_remote_control_config(
        {**base, "XGAP_REMOTE_ALLOW_CANCEL": "true"},
        working_directory=tmp_path,
    ).allow_cancel
    assert load_remote_control_config(
        {**base, "XGAP_REMOTE_ALLOW_CANCEL": "1"},
        working_directory=tmp_path,
    ).allow_cancel


def test_cli_parser_maps_commands_to_typed_operations() -> None:
    parser = _parser()
    operation, payload = _operation_and_payload(
        parser.parse_args(["status", "--job-id", "12345"])
    )
    assert operation is RemoteExecutorOperation.JOB_STATUS
    assert payload == {"job_id": "12345"}

    operation, payload = _operation_and_payload(
        parser.parse_args(
            ["fetch", "--remote-path", "run-1", "--local-path", "run-1"]
        )
    )
    assert operation is RemoteExecutorOperation.FETCH_ARTIFACTS
    assert payload == {"remote_path": "run-1", "local_path": "run-1"}


def test_control_entry_invokes_registered_executor(tmp_path: Path) -> None:
    transport = FakeTransport([RemoteCommandResult(0, stdout="9921\n")])
    result = invoke_remote_control(
        _config(tmp_path),
        RemoteExecutorOperation.SUBMIT_JOB,
        {"script": DEFAULT_ALLOWED_SBATCH_SCRIPTS[0]},
        transport=transport,
    )
    assert result.status is ToolStatus.SUCCESS
    assert result.value["job_id"] == "9921"
    assert transport.calls == [
        (
            "run",
            (
                "sbatch",
                "--parsable",
                "--chdir",
                "/home/user/XGAP",
                "/home/user/XGAP/scripts/slurm/run_m15_core_smoke.sbatch",
            ),
        )
    ]


def test_executor_builder_validates_remote_configuration(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute POSIX"):
        build_remote_executor(
            _config(tmp_path, remote_repo_root="relative/repo"),
            transport=FakeTransport([]),
        )
