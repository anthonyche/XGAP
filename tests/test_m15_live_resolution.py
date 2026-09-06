from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
from typing import Any, Mapping

import pytest

from xgap.experiments.cwru_vllm import finalize_run
from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_live_resolution import (
    PREFLIGHT_SCHEMA_VERSION,
    RUN_SCHEMA_VERSION,
    build_preflight_manifest,
    load_live_resolution_spec,
    run_live_resolution,
)
from xgap.experiments.m15_live_resolution_evidence import (
    audit_live_resolution_run,
)


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "experiments/configs/m15_e2b_live_resolution_gate.json"
COMMIT = "a" * 40


@dataclass
class _Transport:
    content: object
    calls: list[dict[str, Any]] = field(default_factory=list)

    def post_json(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(dict(kwargs))
        return {
            "id": "m15-e2b-test-request",
            "choices": [{"message": {"content": self.content}}],
            "usage": {
                "prompt_tokens": 51,
                "completion_tokens": 8,
                "total_tokens": 59,
            },
        }


def _clear_provider_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XGAP_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("XGAP_LLM_MODEL", raising=False)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _environment(preflight: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "m13e2-cwru-run-environment-v1",
        "captured_at": "2026-09-06T12:01:00+00:00",
        "slurm": {"job_id": "test-job", "job_name": "test", "node_list": "test"},
        "git": {"commit": preflight["git_commit"], "clean": True, "status": []},
        "runtime": {
            "python": "3.11.5",
            "torch": "2.9.0+cu128",
            "cuda_runtime": "12.8",
            "vllm": "0.11.1",
            "python_executable": "/test/xgap-vllm/bin/python",
        },
        "gpu": {
            "status": "available",
            "model": "NVIDIA H100 NVL",
            "driver_version": "test",
            "memory_mib": 95830,
        },
        "model": {
            "name": preflight["model"],
            "revision": "cached-revision",
            "thinking_enabled": False,
        },
        "provider": {
            "id": preflight["provider_id"],
            "base_url": preflight["base_url"],
            "credential_env_name": "XGAP_LLM_API_KEY",
            "credential_present": True,
        },
        "experiment": {
            "model_bundle_hash": preflight["model_bundle_hash"],
            "prompt_hash": preflight["prompt_hash"],
        },
        "environment_contract": {
            "hash": preflight["deployment_contract_hash"],
        },
        "secrets_persisted": False,
    }


def _sealed_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    _clear_provider_overrides(monkeypatch)
    preflight = build_preflight_manifest(
        repo_root=ROOT,
        spec_path=SPEC,
        git_commit_override=COMMIT,
        git_clean_override=True,
    )
    preflight_path = tmp_path / "preflight.json"
    environment_path = tmp_path / "environment.json"
    _write_json(preflight_path, preflight)
    _write_json(environment_path, _environment(preflight))
    return preflight_path, environment_path


def test_frozen_e2b_spec_and_preflight_bind_one_non_entity_call(monkeypatch) -> None:
    _clear_provider_overrides(monkeypatch)
    _, spec = load_live_resolution_spec(ROOT, SPEC)
    preflight = build_preflight_manifest(
        repo_root=ROOT,
        spec_path=SPEC,
        git_commit_override=COMMIT,
        git_clean_override=True,
    )

    assert spec["execution_contract"]["maximum_provider_requests"] == 1
    assert spec["execution_contract"]["maximum_repair_calls"] == 0
    assert spec["execution_contract"]["automatic_retries"] == 0
    assert preflight["schema_version"] == PREFLIGHT_SCHEMA_VERSION
    assert preflight["preflight_external_calls"] == 0
    assert preflight["provider_max_repair_calls"] == 0
    assert preflight["provider_output_token_cap"] == 256
    assert preflight["goal_contract"]["max_steps"] == 2
    assert preflight["goal_contract"]["max_tool_calls"] == 1
    assert preflight["dynamic_schema"]["properties"]["candidate_ids"][
        "items"
    ]["enum"] == spec["request"]["candidate_ids"]
    assert preflight["dynamic_schema"]["properties"]["candidate_ids"][
        "maxItems"
    ] == 4
    assert "uniqueItems" not in preflight["dynamic_schema"]["properties"][
        "candidate_ids"
    ]
    assert preflight["preflight_sha256"] == content_hash(
        {key: value for key, value in preflight.items() if key != "preflight_sha256"}
    )


def test_spec_rejects_entity_model_routing(tmp_path: Path) -> None:
    value = json.loads(SPEC.read_text(encoding="utf-8"))
    value["request"]["hole_kind"] = "entity"
    value["freeze_hash"] = content_hash(
        {key: item for key, item in value.items() if key != "freeze_hash"}
    )
    path = tmp_path / "entity-spec.json"
    _write_json(path, value)

    with pytest.raises(ValueError, match="cannot resolve entity identity"):
        load_live_resolution_spec(tmp_path, path)


def test_preflight_refuses_dirty_checkout(monkeypatch) -> None:
    _clear_provider_overrides(monkeypatch)
    with pytest.raises(ValueError, match="dirty Git checkout"):
        build_preflight_manifest(
            repo_root=ROOT,
            spec_path=SPEC,
            git_commit_override=COMMIT,
            git_clean_override=False,
        )


def test_live_gate_runs_one_costed_goal_tool_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflight, environment = _sealed_inputs(tmp_path, monkeypatch)
    monkeypatch.setenv("XGAP_LLM_API_KEY", "test-only-secret")
    transport = _Transport(
        {
            "hole_id": "transfer-predicate",
            "candidate_ids": ["predicate:invested_in", "predicate:paid"],
        }
    )
    output = tmp_path / "live"

    manifest = run_live_resolution(
        repo_root=ROOT,
        spec_path=SPEC,
        preflight_path=preflight,
        environment_path=environment,
        output_root=output,
        transport_override=transport,
        git_commit_override=COMMIT,
        git_clean_override=True,
    )

    assert manifest["schema_version"] == RUN_SCHEMA_VERSION
    assert manifest["status"] == "success"
    assert manifest["summary"]["goal_tool_calls"] == 1
    assert manifest["summary"]["llm_tool_calls"] == 1
    assert manifest["summary"]["provider_external_calls"] == 1
    assert manifest["summary"]["provider_repair_calls"] == 0
    assert manifest["summary"]["hard_constraints_preserved"] is True
    assert manifest["summary"]["native_query_text_emitted"] is False
    assert len(transport.calls) == 1
    assert "test-only-secret" not in "\n".join(
        path.read_text(encoding="utf-8")
        for path in output.iterdir()
        if path.is_file()
    )
    goal = json.loads((output / "goal_state.json").read_text(encoding="utf-8"))
    assert goal["status"] == "succeeded"
    assert len(goal["trace"]) == 2
    memory = json.loads((output / "memory_snapshot.json").read_text())
    assert len(memory["records"]) == 1
    assert memory["records"][0]["value"]["metrics"]["external_calls"] == 1.0


def test_malformed_live_response_fails_once_and_persists_cost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflight, environment = _sealed_inputs(tmp_path, monkeypatch)
    monkeypatch.setenv("XGAP_LLM_API_KEY", "test-only-secret")
    transport = _Transport("not-json")
    output = tmp_path / "failed-live"

    manifest = run_live_resolution(
        repo_root=ROOT,
        spec_path=SPEC,
        preflight_path=preflight,
        environment_path=environment,
        output_root=output,
        transport_override=transport,
        git_commit_override=COMMIT,
        git_clean_override=True,
    )

    assert manifest["status"] == "failed"
    assert manifest["summary"]["goal_status"] == "failed"
    assert manifest["summary"]["goal_tool_calls"] == 1
    assert manifest["summary"]["provider_external_calls"] == 1
    assert len(transport.calls) == 1
    invocation = json.loads((output / "provider_invocation.json").read_text())
    assert invocation["status"] == "failed"
    assert invocation["external_calls"] == 1
    assert invocation["failure_category"] == "structured_output_error"


def test_live_gate_rejects_tampered_preflight_before_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflight, environment = _sealed_inputs(tmp_path, monkeypatch)
    value = json.loads(preflight.read_text())
    value["request_payload_sha256"] = "0" * 64
    _write_json(preflight, value)
    transport = _Transport({})

    with pytest.raises(ValueError, match="sealed preflight"):
        run_live_resolution(
            repo_root=ROOT,
            spec_path=SPEC,
            preflight_path=preflight,
            environment_path=environment,
            output_root=tmp_path / "live",
            transport_override=transport,
            git_commit_override=COMMIT,
            git_clean_override=True,
        )
    assert transport.calls == []


def test_live_gate_rejects_environment_commit_drift_before_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflight, environment = _sealed_inputs(tmp_path, monkeypatch)
    value = json.loads(environment.read_text())
    value["git"]["commit"] = "b" * 40
    _write_json(environment, value)
    transport = _Transport({})

    with pytest.raises(ValueError, match="Git state"):
        run_live_resolution(
            repo_root=ROOT,
            spec_path=SPEC,
            preflight_path=preflight,
            environment_path=environment,
            output_root=tmp_path / "live",
            transport_override=transport,
            git_commit_override=COMMIT,
            git_clean_override=True,
        )
    assert transport.calls == []


def test_e2b_slurm_wrapper_is_bounded_and_has_one_inference_path() -> None:
    script = ROOT / "scripts/slurm/run_m15_live_resolution.sbatch"
    result = subprocess.run(
        ("bash", "-n", str(script)),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    text = script.read_text(encoding="utf-8")
    assert "#SBATCH --partition=gpu" in text
    assert "#SBATCH -C gpu2h100" in text
    assert "#SBATCH --gres=gpu:1" in text
    assert "#SBATCH --time=00:45:00" in text
    assert "trap cleanup EXIT" in text
    assert "kill -9" in text
    assert "structured-output smoke" in text
    assert "smoke_vllm_structured_output.sh" not in text
    assert text.count("m15_live_resolution run") == 1
    assert "automatic_retries" not in text


def _completed_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    run_root = tmp_path / "run"
    run_root.mkdir()
    preflight = build_preflight_manifest(
        repo_root=ROOT,
        spec_path=SPEC,
        git_commit_override=COMMIT,
        git_clean_override=True,
    )
    preflight_path = run_root / "preflight_manifest.json"
    environment_path = run_root / "cwru_environment.json"
    _write_json(preflight_path, preflight)
    _write_json(environment_path, _environment(preflight))
    (run_root / "service_launch_requested_at.txt").write_text(
        "2026-09-06T12:00:00Z\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("XGAP_LLM_API_KEY", "test-only-secret")
    run_live_resolution(
        repo_root=ROOT,
        spec_path=SPEC,
        preflight_path=preflight_path,
        environment_path=environment_path,
        output_root=run_root / "live-resolution-run",
        transport_override=_Transport(
            {
                "hole_id": "transfer-predicate",
                "candidate_ids": ["predicate:transferred_to"],
            }
        ),
        git_commit_override=COMMIT,
        git_clean_override=True,
    )
    (run_root / "job.log").write_text("bounded local test\n", encoding="utf-8")
    (run_root / "pytest.txt").write_text("19 passed\n", encoding="utf-8")
    (run_root / "service_shutdown.txt").write_text("sigterm\n", encoding="utf-8")
    finalize_run(run_root, 0)
    return run_root


def test_independent_evidence_audit_reconstructs_successful_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_provider_overrides(monkeypatch)
    run_root = _completed_run(tmp_path, monkeypatch)

    audit = audit_live_resolution_run(
        run_root=run_root,
        repo_root=ROOT,
        expected_commit=COMMIT,
    )

    assert audit["success"] is True, audit["failed_check_ids"]
    assert audit["failed_check_ids"] == []
    assert audit["run_tree_mutated"] is False
    assert audit["check_count"] > 60


def test_evidence_audit_rejects_post_run_goal_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_provider_overrides(monkeypatch)
    run_root = _completed_run(tmp_path, monkeypatch)
    goal_path = run_root / "live-resolution-run/goal_state.json"
    goal = json.loads(goal_path.read_text())
    goal["tool_calls"] = 0
    _write_json(goal_path, goal)

    audit = audit_live_resolution_run(
        run_root=run_root,
        repo_root=ROOT,
        expected_commit=COMMIT,
    )

    assert audit["success"] is False
    assert "goal.tool_calls" in audit["failed_check_ids"]
    assert "live.goal_hash" in audit["failed_check_ids"]
    assert audit["run_tree_mutated"] is False
