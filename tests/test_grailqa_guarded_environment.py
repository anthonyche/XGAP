from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.cwru_vllm import CWRUVLLMContract, RUN_ENVIRONMENT_SCHEMA_VERSION
import xgap.experiments.grailqa_guarded_environment as guarded
from xgap.experiments.grailqa_preflight import GrailQAPreflightSpec
from xgap.experiments.hashing import content_hash
from xgap.experiments.live_run import build_openai_compatible_provider


ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a" * 40
REVISION = "b" * 40


@pytest.fixture
def bound(monkeypatch, tmp_path):
    repo = tmp_path.resolve() / "repo"
    repo.mkdir()
    model = ModelBundle.load(ROOT / "models/qwen3_32b_vllm_cwru_grailqa_contract_v1")
    monkeypatch.delenv("XGAP_LLM_MODEL", raising=False)
    monkeypatch.delenv("XGAP_LLM_BASE_URL", raising=False)
    provider = build_openai_compatible_provider(model)
    original_contract = CWRUVLLMContract.load(ROOT / "experiments/environments/cwru_pioneer_qwen3_32b_vllm.json")
    data = copy.deepcopy(original_contract.data)
    data["shared_paths"]["hf_home"] = str(tmp_path.resolve() / "hf-cache")
    data["contract_hash"] = content_hash({key: value for key, value in data.items() if key != "contract_hash"})
    contract_path = repo / "deployment.json"
    contract_path.write_text(json.dumps(data), encoding="utf-8")
    contract = CWRUVLLMContract.load(contract_path)
    original_spec = GrailQAPreflightSpec.load(ROOT / "experiments/specs/grailqa_semantic_preflight_output_contract_v1_cwru_qwen3_32b.json")
    spec_data = copy.deepcopy(original_spec.data)
    spec_data.update(
        model_bundle_root=str(model.root), deployment_contract="deployment.json",
        deployment_contract_hash=contract.contract_hash,
    )
    spec_data["freeze_hash"] = content_hash({key: value for key, value in spec_data.items() if key != "freeze_hash"})
    spec_path = repo / "preflight.json"
    spec_path.write_text(json.dumps(spec_data), encoding="utf-8")
    spec = GrailQAPreflightSpec.load(spec_path)
    snapshot = Path(data["shared_paths"]["hf_home"]) / "hub/models--Qwen--Qwen3-32B/snapshots" / REVISION
    # No model or tokenizer assets are required by record binding.
    snapshot.mkdir(parents=True)
    environment = {
        "schema_version": RUN_ENVIRONMENT_SCHEMA_VERSION,
        "secrets_persisted": False,
        "cluster": data["cluster"], "scheduler": data["scheduler"],
        "hostname": "test-node", "slurm": {"job_id": "98765"},
        "git": {"commit": COMMIT, "clean": True, "status": []},
        "experiment": {
            "spec_path": "preflight.json",
            "spec_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(),
            "spec_freeze_hash": spec.data["freeze_hash"],
            "model_bundle_hash": model.bundle_hash, "prompt_hash": model.prompt.prompt_hash,
        },
        "environment_contract": {"path": "deployment.json", "hash": contract.contract_hash},
        "model": {
            "name": contract.model, "revision": REVISION,
            "hf_home": data["shared_paths"]["hf_home"],
            **{key: data["serving"][key] for key in (
                "dtype", "max_model_len", "gpu_memory_utilization", "generation_config", "thinking_enabled",
            )},
        },
        "provider": {
            "id": model.config.provider, "base_url": provider.config.base_url,
            "credential_env_name": model.config.api_key_env, "credential_present": True,
            "structured_output_mode": model.config.structured_output_mode,
        },
        "runtime": {**data["runtime"], "python_executable": "/example/python"},
    }
    git_calls = []

    def git_output(path, *args):
        assert path == repo
        git_calls.append(args)
        assert args in (("rev-parse", "HEAD"), ("status", "--porcelain", "--untracked-files=all"))
        return COMMIT if args[0] == "rev-parse" else ""

    monkeypatch.setattr(guarded, "_git_output", git_output)
    monkeypatch.setattr(guarded.socket, "gethostname", lambda: "test-node")
    monkeypatch.setenv("SLURM_JOB_ID", "98765")
    kwargs = {
        "spec": spec, "model": model, "contract": contract,
        "provider_config": provider.config, "tokenizer_snapshot": snapshot,
        "tokenizer_revision": REVISION, "repo_root": repo,
        "expected_runner_commit": COMMIT,
    }
    return environment, kwargs, git_calls


def test_matching_records_are_not_remote_parity_or_authority(bound):
    environment, kwargs, git_calls = bound
    before = copy.deepcopy(environment)
    result = guarded.validate_guarded_environment(environment, **kwargs)
    assert environment == before
    assert result["success"] is result["deployment_binding_checked"] is True
    assert result["remote_serving_parity_verified"] is result["paper_result"] is False
    assert result["validation_scope"] == "record_bindings_only_not_serving_process_verification"
    assert all(row["passed"] for row in result["checks"])
    assert len({row["check_id"] for row in result["checks"]}) == len(result["checks"])
    assert result["environment_sha256"] == content_hash(environment)
    assert result["binding_sha256"] == content_hash({key: value for key, value in result.items() if key != "binding_sha256"})
    assert git_calls == [("rev-parse", "HEAD"), ("status", "--porcelain", "--untracked-files=all")]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("key,value,valid", [
    ("temperature", 0, True), ("temperature", 0.0, True),
    ("top_p", 1, True), ("top_p", 1.0, True),
    ("temperature", False, False), ("top_p", True, False),
    ("temperature", "0", False), ("top_p", 0.5, False),
])
def test_sampling_numeric_representation_preserves_value_not_boolean(bound, key, value, valid):
    environment, kwargs, _ = bound
    spec = kwargs["spec"]
    data = copy.deepcopy(spec.data)
    data[key] = value
    data["freeze_hash"] = content_hash({k: v for k, v in data.items() if k != "freeze_hash"})
    spec.path.write_text(json.dumps(data))
    kwargs["spec"] = GrailQAPreflightSpec.load(spec.path)
    environment["experiment"]["spec_sha256"] = hashlib.sha256(spec.path.read_bytes()).hexdigest()
    environment["experiment"]["spec_freeze_hash"] = data["freeze_hash"]
    if valid:
        assert guarded.validate_guarded_environment(environment, **kwargs)["success"]
    else:
        with pytest.raises(ValueError, match="spec_" + key):
            guarded.validate_guarded_environment(environment, **kwargs)


@pytest.mark.parametrize("path,value", [
    (("schema_version",), "wrong"), (("secrets_persisted",), True),
    (("git", "commit"), "c" * 40), (("git", "clean"), False),
    (("git", "clean"), 1), (("git", "status"), ["?? arbitrary-private-file"]),
    (("slurm", "job_id"), "old-job"), (("hostname",), "old-host"),
    (("cluster",), "another-cluster"), (("scheduler",), "another-scheduler"),
    (("experiment", "spec_path"), "different-spec.json"),
    (("experiment", "spec_sha256"), "wrong"), (("experiment", "spec_freeze_hash"), "wrong"),
    (("experiment", "model_bundle_hash"), "wrong"), (("experiment", "prompt_hash"), "wrong"),
    (("environment_contract", "path"), "wrong.json"), (("environment_contract", "hash"), "wrong"),
    (("model", "name"), "Other/Model"), (("model", "revision"), "c" * 40),
    (("model", "hf_home"), "/another/cache"), (("model", "dtype"), "float16"),
    (("model", "max_model_len"), 65536), (("model", "gpu_memory_utilization"), 0.95),
    (("model", "generation_config"), "auto"), (("model", "thinking_enabled"), True),
    (("provider", "base_url"), "http://credential-secret@example.com/v1"),
    (("provider", "id"), "other"), (("provider", "credential_env_name"), "OTHER_SECRET"),
    (("provider", "credential_present"), False), (("provider", "structured_output_mode"), "json_object"),
    (("runtime", "python"), "3.12"), (("runtime", "torch"), "other"),
    (("runtime", "cuda_runtime"), "other"), (("runtime", "vllm"), "other"),
])
def test_each_record_mismatch_fails_without_values(bound, path, value):
    environment, kwargs, _ = bound
    target = environment
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match="Guarded environment check failed:") as error:
        guarded.validate_guarded_environment(environment, **kwargs)
    assert "credential-secret" not in str(error.value)
    assert "arbitrary-private-file" not in str(error.value)


@pytest.mark.parametrize("field,value", [
    ("model", "Other/Model"), ("base_url", "http://127.0.0.1:8001/v1"),
    ("max_tokens", 2048), ("candidate_cap", 2), ("temperature", 0.5), ("top_p", 0.8),
    ("timeout_seconds", 999), ("structured_output_mode", "json_object"),
    ("max_repair_calls", 0), ("seed", 1), ("prompt_hash", "changed"),
    ("structured_schema", {"type": "object"}),
    ("extra_parameters", {"chat_template_kwargs": {"enable_thinking": True}}),
])
def test_effective_provider_cannot_drift(bound, field, value):
    environment, kwargs, _ = bound
    kwargs["provider_config"] = replace(kwargs["provider_config"], **{field: value})
    with pytest.raises(ValueError, match=f"effective_provider_{field}"):
        guarded.validate_guarded_environment(environment, **kwargs)


@pytest.mark.parametrize("field", ["expected_runner_commit", "tokenizer_revision"])
@pytest.mark.parametrize("value", ["short", "A" * 40, "a" * 39, None])
def test_exact_revision_inputs_required(bound, field, value):
    environment, kwargs, _ = bound
    kwargs[field] = value
    with pytest.raises(ValueError, match="format"):
        guarded.validate_guarded_environment(environment, **kwargs)


@pytest.mark.parametrize("job", [None, "", "old", "98765\n"])
def test_requires_current_slurm_allocation(bound, monkeypatch, job):
    environment, kwargs, _ = bound
    if job is None:
        monkeypatch.delenv("SLURM_JOB_ID")
    else:
        monkeypatch.setenv("SLURM_JOB_ID", job)
    with pytest.raises(ValueError, match="current_slurm_job"):
        guarded.validate_guarded_environment(environment, **kwargs)


@pytest.mark.parametrize("head,status,check", [
    ("c" * 40, "", "current_git_commit"),
    (COMMIT, "?? untracked", "current_git_clean"),
    (COMMIT, " M tracked", "current_git_clean"),
])
def test_current_checkout_is_checked_not_only_record(bound, monkeypatch, head, status, check):
    environment, kwargs, _ = bound
    monkeypatch.setattr(guarded, "_git_output", lambda repo, *args: head if args[0] == "rev-parse" else status)
    with pytest.raises(ValueError, match=check):
        guarded.validate_guarded_environment(environment, **kwargs)


@pytest.mark.parametrize("artifact,check", [("spec", "spec_loaded_bytes"), ("contract", "contract_loaded_bytes")])
def test_loaded_object_must_match_current_file_bytes(bound, artifact, check):
    environment, kwargs, _ = bound
    path = kwargs[artifact].path
    data = json.loads(path.read_text())
    data["changed_since_load"] = True
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=check):
        guarded.validate_guarded_environment(environment, **kwargs)


@pytest.mark.parametrize("kind", ["wrong_model", "relative", "symlink", "parent_symlink", "missing"])
def test_snapshot_is_exact_model_and_revision_directory(bound, kind):
    environment, kwargs, _ = bound
    snapshot = kwargs["tokenizer_snapshot"]
    if kind == "wrong_model":
        wrong = snapshot.parent.parent.parent / "models--Other--Model/snapshots" / REVISION
        wrong.mkdir(parents=True)
        kwargs["tokenizer_snapshot"] = wrong
    elif kind == "relative":
        kwargs["tokenizer_snapshot"] = Path("snapshots") / REVISION
    elif kind == "symlink":
        target = snapshot.parent / "elsewhere"
        snapshot.rename(target)
        snapshot.symlink_to(target, target_is_directory=True)
    elif kind == "parent_symlink":
        parent = snapshot.parent
        target = parent.with_name("redirected")
        parent.rename(target)
        parent.symlink_to(target, target_is_directory=True)
    else:
        snapshot.rmdir()
    with pytest.raises(ValueError, match="snapshot_"):
        guarded.validate_guarded_environment(environment, **kwargs)


def test_raw_git_helper_strips_overrides_and_does_not_leak_stderr(monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_DIR", "/secret/different/repository")
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        assert "GIT_DIR" not in kwargs["env"]
        assert kwargs["timeout"] == 30
        return SimpleNamespace(returncode=1, stdout="", stderr="credential-secret")

    monkeypatch.setattr(guarded.subprocess, "run", run)
    with pytest.raises(ValueError, match="git_unavailable") as error:
        guarded._git_output(tmp_path, "rev-parse", "HEAD")
    assert "secret" not in str(error.value)
    assert calls[0][0] == ["git", "-C", str(tmp_path), "rev-parse", "HEAD"]
