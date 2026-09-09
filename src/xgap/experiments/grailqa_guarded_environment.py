"""Fail-closed record bindings for the opt-in GrailQA development entrypoint.

This module does not inspect a serving process or verify its tokenizer. Matching
records constrain a deployment; they do not prove remote chat-template parity.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
from typing import Any, Mapping

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.cwru_vllm import CWRUVLLMContract, RUN_ENVIRONMENT_SCHEMA_VERSION
from xgap.experiments.grailqa_preflight import GrailQAPreflightSpec
from xgap.experiments.hashing import content_hash
from xgap.llm.openai_compatible import OpenAICompatibleProviderConfig


SCHEMA_VERSION = "grailqa-guarded-environment-binding-v1"


def _git_output(repo: Path, *args: str) -> str:
    # Git-specific shell overrides must not redirect checks to another tree.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True,
            check=False, timeout=30, env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        raise ValueError("Guarded environment check failed: git_unavailable.") from None
    if result.returncode != 0:
        raise ValueError("Guarded environment check failed: git_unavailable.")
    return result.stdout.strip()


def validate_guarded_environment(
    environment: Mapping[str, Any], *, spec: GrailQAPreflightSpec,
    model: ModelBundle, contract: CWRUVLLMContract,
    provider_config: OpenAICompatibleProviderConfig,
    tokenizer_snapshot: Path, tokenizer_revision: str, repo_root: Path,
    expected_runner_commit: str,
) -> dict[str, Any]:
    """Validate frozen/current record identities before any model transmission.

    The caller must first load the credential-free run environment through
    ``load_run_environment``. Errors contain fixed check names, never observed
    values, paths, provider URLs, credentials, or subprocess output.
    """
    checks: list[dict[str, Any]] = []

    def require(ok: bool, name: str) -> None:
        if not ok:
            raise ValueError(f"Guarded environment check failed: {name}.")
        checks.append({"check_id": name, "passed": True})

    def mapping(value: Any, name: str) -> Mapping[str, Any]:
        require(isinstance(value, Mapping), name)
        return value

    def equal(observed: Any, expected: Any, name: str) -> None:
        # JSON comparison distinguishes true from 1, unlike Python equality.
        try:
            matches = json.dumps(observed, sort_keys=True, allow_nan=False) == json.dumps(
                expected, sort_keys=True, allow_nan=False,
            )
        except (TypeError, ValueError):
            matches = False
        require(matches, name)

    def sha40(value: Any) -> bool:
        return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None

    require(sha40(expected_runner_commit), "runner_commit_format")
    require(sha40(tokenizer_revision), "tokenizer_revision_format")
    repo = Path(repo_root).resolve()
    equal(_git_output(repo, "rev-parse", "HEAD"), expected_runner_commit, "current_git_commit")
    equal(_git_output(repo, "status", "--porcelain", "--untracked-files=all"), "", "current_git_clean")
    equal(environment.get("schema_version"), RUN_ENVIRONMENT_SCHEMA_VERSION, "environment_schema")
    equal(environment.get("secrets_persisted"), False, "environment_secret_boundary")
    git = mapping(environment.get("git"), "environment_git")
    equal(git.get("commit"), expected_runner_commit, "recorded_git_commit")
    equal(git.get("clean"), True, "recorded_git_clean")
    equal(git.get("status"), [], "recorded_git_status")

    job_id = os.environ.get("SLURM_JOB_ID")
    require(isinstance(job_id, str) and re.fullmatch(r"[0-9]+", job_id) is not None, "current_slurm_job")
    slurm = mapping(environment.get("slurm"), "environment_slurm")
    equal(slurm.get("job_id"), job_id, "recorded_slurm_job")
    equal(environment.get("hostname"), socket.gethostname(), "recorded_hostname")
    equal(environment.get("cluster"), contract.data.get("cluster"), "cluster")
    equal(environment.get("scheduler"), contract.data.get("scheduler"), "scheduler")

    try:
        spec_bytes = spec.path.read_bytes()
        serialized_spec = json.loads(spec_bytes)
        serialized_contract = json.loads(contract.path.read_bytes())
        spec_relative = spec.path.resolve().relative_to(repo).as_posix()
        contract_relative = contract.path.resolve().relative_to(repo).as_posix()
    except (OSError, ValueError, TypeError):
        raise ValueError("Guarded environment check failed: frozen_file_identity.") from None
    equal(serialized_spec, spec.data, "spec_loaded_bytes")
    equal(serialized_contract, contract.data, "contract_loaded_bytes")
    equal(content_hash({key: value for key, value in spec.data.items() if key != "freeze_hash"}), spec.data.get("freeze_hash"), "spec_freeze_hash")
    equal(content_hash({key: value for key, value in contract.data.items() if key != "contract_hash"}), contract.contract_hash, "contract_content_hash")
    equal(spec.data.get("model_bundle_hash"), model.bundle_hash, "spec_model_bundle")
    equal(spec.data.get("deployment_contract_hash"), contract.contract_hash, "spec_deployment_contract")
    require((repo / str(spec.data.get("deployment_contract", ""))).resolve() == contract.path.resolve(), "deployment_contract_path")
    require((repo / str(spec.data.get("model_bundle_root", ""))).resolve() == model.root.resolve(), "model_bundle_path")
    experiment = mapping(environment.get("experiment"), "environment_experiment")
    spec_sha256 = hashlib.sha256(spec_bytes).hexdigest()
    for key, expected in {
        "spec_path": spec_relative, "spec_sha256": spec_sha256,
        "spec_freeze_hash": spec.data["freeze_hash"],
        "model_bundle_hash": model.bundle_hash, "prompt_hash": model.prompt.prompt_hash,
    }.items():
        equal(experiment.get(key), expected, f"experiment_{key}")
    recorded_contract = mapping(environment.get("environment_contract"), "environment_contract")
    equal(recorded_contract.get("path"), contract_relative, "recorded_contract_path")
    equal(recorded_contract.get("hash"), contract.contract_hash, "recorded_contract_hash")

    serving = mapping(contract.data.get("serving"), "contract_serving")
    shared = mapping(contract.data.get("shared_paths"), "contract_shared_paths")
    config = model.config
    equal(config.exact_model_snapshot, contract.model, "bundle_served_model")
    equal(spec.data.get("model"), contract.model, "spec_served_model")
    equal(spec.data.get("provider"), config.provider, "spec_provider")
    equal(spec.data.get("candidate_cap"), config.candidate_count, "spec_candidate_cap")
    equal(spec.data.get("temperature"), config.temperature, "spec_temperature")
    equal(spec.data.get("top_p"), config.top_p, "spec_top_p")
    equal(spec.data.get("backend_execution"), False, "no_backend_execution")
    equal(spec.data.get("full_150_run_permitted"), False, "development_population_only")
    require(serving.get("host") == "127.0.0.1" and type(serving.get("port")) is int, "frozen_loopback")
    expected_url = f"http://127.0.0.1:{serving['port']}/v1"
    equal(config.base_url, expected_url, "bundle_loopback_endpoint")
    equal(config.structured_output_mode, serving.get("structured_output_mode"), "bundle_structured_mode")
    equal(config.extra_parameters, {"chat_template_kwargs": {"enable_thinking": serving.get("thinking_enabled")}}, "bundle_template_parameters")
    require(type(serving.get("thinking_enabled")) is bool, "frozen_thinking_boolean")
    limits = (config.token_limits.get("input"), config.token_limits.get("output"), serving.get("max_model_len"))
    require(all(type(value) is int and value > 0 for value in limits), "positive_token_budgets")
    require(limits[0] + limits[1] <= limits[2], "context_reservations")
    for key, expected in {
        "provider_id": config.provider, "base_url": expected_url,
        "api_key_env": config.api_key_env, "model": contract.model,
        "temperature": config.temperature, "top_p": config.top_p,
        "max_tokens": config.token_limits["output"], "candidate_cap": config.candidate_count,
        "timeout_seconds": config.timeout_seconds, "structured_output_mode": config.structured_output_mode,
        "structured_schema": model.structured_schema, "prompt_hash": model.prompt.prompt_hash,
        "seed": config.seed, "seed_supported": config.seed_supported,
        "max_repair_calls": config.max_repair_calls, "extra_parameters": config.extra_parameters,
    }.items():
        equal(getattr(provider_config, key, None), expected, f"effective_provider_{key}")

    recorded_model = mapping(environment.get("model"), "environment_model")
    for key, expected in {
        "name": contract.model, "revision": tokenizer_revision, "hf_home": shared.get("hf_home"),
        **{key: serving.get(key) for key in (
            "dtype", "max_model_len", "gpu_memory_utilization", "generation_config", "thinking_enabled",
        )},
    }.items():
        equal(recorded_model.get(key), expected, f"recorded_model_{key}")
    recorded_provider = mapping(environment.get("provider"), "environment_provider")
    for key, expected in {
        "id": config.provider, "base_url": expected_url, "credential_env_name": config.api_key_env,
        "structured_output_mode": config.structured_output_mode, "credential_present": True,
    }.items():
        equal(recorded_provider.get(key), expected, f"recorded_provider_{key}")
    recorded_runtime = mapping(environment.get("runtime"), "environment_runtime")
    runtime = mapping(contract.data.get("runtime"), "contract_runtime")
    for key in ("python", "torch", "cuda_runtime", "vllm"):
        require(isinstance(runtime.get(key), str) and bool(runtime[key]), f"frozen_runtime_{key}")
        equal(recorded_runtime.get(key), runtime[key], f"recorded_runtime_{key}")

    # Bind both lexical location and resolved location. A same-revision snapshot
    # from another model, a snapshot symlink, or a redirected cache is rejected.
    hf_home = shared.get("hf_home")
    require(isinstance(hf_home, str) and Path(hf_home).is_absolute(), "absolute_hf_home")
    require(re.fullmatch(r"[^/\.][^/]*/[^/\.][^/]*", contract.model) is not None, "served_model_cache_name")
    expected_snapshot = Path(hf_home) / "hub" / ("models--" + contract.model.replace("/", "--")) / "snapshots" / tokenizer_revision
    snapshot = Path(tokenizer_snapshot)
    require(snapshot.is_absolute() and snapshot == expected_snapshot, "snapshot_lexical_model_binding")
    try:
        require(not snapshot.is_symlink() and snapshot.is_dir(), "snapshot_directory")
        require(snapshot.resolve(strict=True) == expected_snapshot, "snapshot_resolved_model_binding")
    except (OSError, RuntimeError):
        raise ValueError("Guarded environment check failed: snapshot_resolution.") from None
    try:
        environment_sha256 = content_hash(environment)
    except (TypeError, ValueError):
        raise ValueError("Guarded environment check failed: environment_json.") from None
    result = {
        "schema_version": SCHEMA_VERSION, "success": True, "checks": checks,
        "runner_commit": expected_runner_commit, "slurm_job_id": job_id,
        "model_revision": tokenizer_revision, "spec_sha256": spec_sha256,
        "spec_freeze_hash": spec.data["freeze_hash"], "model_bundle_hash": model.bundle_hash,
        "prompt_hash": model.prompt.prompt_hash, "deployment_contract_hash": contract.contract_hash,
        "environment_sha256": environment_sha256, "deployment_binding_checked": True,
        "validation_scope": "record_bindings_only_not_serving_process_verification",
        "remote_serving_parity_verified": False, "paper_result": False,
    }
    result["binding_sha256"] = content_hash(result)
    return result
