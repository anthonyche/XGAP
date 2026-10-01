"""Read-only file and recorded deployment bindings for guarded development audits.

These checks bind retained records to explicit inputs. They are not scheduler,
serving-process, original-clock or model-weight attestation.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Mapping

from xgap.experiments.cwru_vllm import RUN_ENVIRONMENT_SCHEMA_VERSION
from xgap.experiments.cwru_gpu_profile import profile_for, validate_recorded_profile
from xgap.experiments.grailqa_candidate_feedback import TYPED_GROUNDING_ONCE
from xgap.experiments.grailqa_candidate_grounding import SEMANTIC_GROUNDING_POLICY
from xgap.experiments.grailqa_inline_evidence import _require, _same
from xgap.experiments.hashing import content_hash


# Complete ordered receipt vocabulary from the D200 guarded environment gate.
# This validates receipt completeness; original host/process facts remain
# recorded observations and are not recreated by these names.
_ENVIRONMENT_CHECKS = """
runner_commit_format tokenizer_revision_format current_git_commit current_git_clean
environment_schema environment_secret_boundary environment_git recorded_git_commit
recorded_git_clean recorded_git_status current_slurm_job environment_slurm
recorded_slurm_job recorded_hostname cluster scheduler spec_loaded_bytes contract_loaded_bytes
spec_freeze_hash contract_content_hash spec_model_bundle spec_deployment_contract deployment_contract_path
model_bundle_path environment_experiment experiment_spec_path experiment_spec_sha256
experiment_spec_freeze_hash experiment_model_bundle_hash experiment_prompt_hash environment_contract
recorded_contract_path recorded_contract_hash contract_serving contract_shared_paths bundle_served_model
spec_served_model spec_provider spec_candidate_cap spec_temperature_numeric spec_temperature
spec_top_p_numeric spec_top_p no_backend_execution development_population_only frozen_loopback
bundle_loopback_endpoint bundle_structured_mode bundle_template_parameters frozen_thinking_boolean
positive_token_budgets context_reservations effective_provider_provider_id effective_provider_base_url
effective_provider_api_key_env effective_provider_model effective_provider_temperature effective_provider_top_p
effective_provider_max_tokens effective_provider_candidate_cap effective_provider_timeout_seconds
effective_provider_structured_output_mode effective_provider_structured_schema effective_provider_prompt_hash
effective_provider_seed effective_provider_seed_supported effective_provider_max_repair_calls
effective_provider_extra_parameters effective_provider_response_contract environment_model recorded_model_name
recorded_model_revision recorded_model_hf_home recorded_model_dtype recorded_model_max_model_len
recorded_model_gpu_memory_utilization recorded_model_generation_config recorded_model_thinking_enabled
environment_provider recorded_provider_id recorded_provider_base_url recorded_provider_credential_env_name
recorded_provider_structured_output_mode recorded_provider_credential_present environment_runtime contract_runtime
frozen_runtime_python recorded_runtime_python frozen_runtime_torch recorded_runtime_torch
frozen_runtime_cuda_runtime recorded_runtime_cuda_runtime frozen_runtime_vllm recorded_runtime_vllm
absolute_hf_home served_model_cache_name snapshot_lexical_model_binding snapshot_directory snapshot_resolved_model_binding
""".split()


def regular(path: Path) -> Path:
    _require(path.is_absolute() and not any(p.is_symlink() for p in (path, *path.parents)), "absolute non-symlink input")
    _require(stat.S_ISREG(path.stat().st_mode), "regular evidence file")
    return path


def digest(path: Path, length: int | None = None) -> str:
    hasher = hashlib.sha256()
    with regular(path).open("rb") as handle:
        remaining = length
        while remaining is None or remaining > 0:
            chunk = handle.read(min(1024 * 1024, remaining) if remaining is not None else 1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
        _require(remaining in (None, 0), "complete inventory prefix")
    return hasher.hexdigest()


def snapshot(root: Path) -> dict[str, dict[str, Any]]:
    _require(root.is_absolute() and root.is_dir() and not any(p.is_symlink() for p in (root, *root.parents)), "regular evidence tree")
    result = {}
    for path in sorted(root.rglob("*")):
        _require(not path.is_symlink(), "no symlink in evidence tree")
        if path.is_dir():
            continue
        regular(path)
        result[path.relative_to(root).as_posix()] = {"size_bytes": path.stat().st_size, "sha256": digest(path)}
    return result


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "no duplicate JSON object key")
        result[key] = value
    return result


def _json(text):
    def invalid(_):
        raise ValueError("Nonfinite JSON number")
    value = json.loads(text, object_pairs_hook=_object_pairs, parse_constant=invalid)
    _require(isinstance(value, dict), "JSON object required")
    return value


def read_json(path: Path) -> dict[str, Any]:
    return _json(regular(path).read_text(encoding="utf-8"))


def read_rows(path: Path) -> list[dict[str, Any]]:
    data = regular(path).read_text(encoding="utf-8")
    _require(not data or data.endswith("\n"), "complete newline-terminated journal")
    return [_json(line) for line in data.splitlines()]


def finite_time(value: Any) -> None:
    _require(type(value) in (int, float) and math.isfinite(value) and value >= 0, "finite nonnegative recorded time")


def timestamp(value: str) -> datetime:
    _require(isinstance(value, str), "recorded timestamp string")
    parsed = datetime.fromisoformat(value)
    _require(parsed.tzinfo is not None, "timezone-qualified recorded timestamp")
    return parsed


def bind_producer_inputs(repo: Path, commit: str, paths: list[str]) -> dict[str, Any]:
    """Compare locally available source/input bytes with explicit Git objects.

    The caller may use an independent checkout; its HEAD need not equal the
    producer commit. No checkout/reset/fetch is performed.
    """
    _require(re.fullmatch(r"[0-9a-f]{40}", commit) is not None, "exact producer commit")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    result = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "-z", commit, "--", *paths],
                            env=environment, capture_output=True, check=True, timeout=30)
    files = {}
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        meta, raw_path = entry.split(b"\t", 1)
        mode, kind, blob_hash = meta.decode().split()
        relative = raw_path.decode()
        _require(kind == "blob" and mode in {"100644", "100755"}, "regular tracked producer input")
        data = regular(repo / relative).read_bytes()
        observed = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        _same(observed, blob_hash, "producer Git blob: " + relative)
        files[relative] = hashlib.sha256(data).hexdigest()
    for path in paths:
        _require(any(name == path or name.startswith(path.rstrip("/") + "/") for name in files), "required tracked producer source")
    return {"runner_commit": commit, "files": files, "recorded_identity_not_original_process_attestation": True}


def bind_outer_run(root: Path, files: Mapping[str, Any]) -> dict[str, Any]:
    status = read_json(root / "run_status.json")
    inventory = read_json(root / "artifact_inventory.json")
    _same(status["schema_version"], "m13e2-cwru-run-status-v1", "outer status schema")
    _same(status["status"], "success", "outer runner success")
    _same(status["exit_code"], 0, "outer command exit code")
    timestamp(status["completed_at"])
    _same(inventory["schema_version"], "m13e2-artifact-inventory-v1", "outer inventory schema")
    rows = inventory["files"]
    indexed = {r["path"]: r for r in rows}
    _same(len(indexed), len(rows), "unique inventory paths")
    _same(status["artifact_count"], len(rows), "outer inventory count")
    expected_paths = sorted(set(files) - {"run_status.json", "artifact_inventory.json"})
    _same(sorted(indexed), expected_paths, "complete inventory including inner status")
    for name in expected_paths:
        item = indexed[name]
        _same(sorted(item), ["path", "sha256", "size_bytes"], "inventory fields")
        if name == "job.log":
            _require(type(item["size_bytes"]) is int and 0 <= item["size_bytes"] <= files[name]["size_bytes"], "recorded job log prefix")
            _same(digest(root / name, item["size_bytes"]), item["sha256"], "job log inventory prefix")
            # The launcher writes the finalizer JSON and location after taking
            # the inventory. Bind the prefix without treating the tail as proof.
        else:
            _same({k: item[k] for k in ("size_bytes", "sha256")}, files[name], "inventory content: " + name)
    return status


def bind_environment_records(*, environment, binding, launch, spec, model, contract,
                             repo: Path, commit: str, revision: str, tokenizer_identity) -> dict[str, Any]:
    """Independently check deployment record values without impersonating Slurm."""
    _same(environment["schema_version"], RUN_ENVIRONMENT_SCHEMA_VERSION, "environment schema")
    _same(environment["secrets_persisted"], False, "environment credential boundary")
    _same(environment["git"], {"commit": commit, "clean": True, "status": []}, "recorded producer source")
    job = environment["slurm"]["job_id"]
    _require(isinstance(job, str) and re.fullmatch(r"[0-9]+", job) is not None, "recorded scheduler job ID")
    _require(isinstance(environment["hostname"], str) and bool(environment["hostname"]), "recorded hostname")
    for key in ("cluster", "scheduler"):
        _same(environment[key], contract.data[key], "deployment " + key)
    c, serving, shared = model.config, contract.data["serving"], contract.data["shared_paths"]
    _same(environment["experiment"], {
        "spec_path": spec.path.relative_to(repo).as_posix(), "spec_sha256": digest(spec.path),
        "spec_freeze_hash": spec.data["freeze_hash"], "model_bundle_hash": model.bundle_hash,
        "prompt_hash": model.prompt.prompt_hash,
    }, "recorded frozen experiment")
    _same(environment["environment_contract"], {"path": contract.path.relative_to(repo).as_posix(),
          "hash": contract.contract_hash}, "recorded contract")
    _same(spec.data["deployment_contract_hash"], contract.contract_hash, "spec contract hash")
    _same(spec.data["model_bundle_hash"], model.bundle_hash, "spec model bundle")
    _same(spec.data["model"], contract.model, "spec served model")
    _same(c.exact_model_snapshot, contract.model, "bundle served model")
    _same(spec.data["provider"], c.provider, "frozen provider")
    _same(spec.data["candidate_cap"], c.candidate_count, "frozen candidate cap")
    for key in ("temperature", "top_p"):
        _require(type(spec.data[key]) in (int, float), "numeric generation parameter: " + key)
        _same(float(spec.data[key]), getattr(c, key), "frozen generation parameter: " + key)
    _same(c.base_url, f"http://127.0.0.1:{serving['port']}/v1", "frozen local endpoint")
    _same(serving["host"], "127.0.0.1", "frozen serving interface")
    _same(c.structured_output_mode, serving["structured_output_mode"], "frozen output mode")
    _same(c.extra_parameters, {"chat_template_kwargs": {"enable_thinking": serving["thinking_enabled"]}}, "frozen template parameters")
    expected_model = {"name": contract.model, "revision": revision, "hf_home": shared["hf_home"],
        **{k: serving[k] for k in ("dtype", "max_model_len", "gpu_memory_utilization", "generation_config", "thinking_enabled")}}
    for key, value in expected_model.items():
        _same(environment["model"][key], value, "recorded model: " + key)
    for key, value in {"id": c.provider, "base_url": c.base_url, "credential_env_name": c.api_key_env,
                       "structured_output_mode": c.structured_output_mode, "credential_present": True}.items():
        _same(environment["provider"][key], value, "recorded provider: " + key)
    for key, value in contract.data["runtime"].items():
        _same(environment["runtime"][key], value, "recorded runtime: " + key)
    _same(environment["gpu"]["status"], "available", "recorded GPU availability")
    if profile_for(contract.data) is None:
        _require("H100" in environment["gpu"]["model"], "recorded H100 model")
    else:
        validate_recorded_profile(contract.data, environment)
    expected_snapshot = str(Path(shared["hf_home"]) / "hub" / ("models--" + contract.model.replace("/", "--")) / "snapshots" / revision)
    _same(tokenizer_identity["snapshot_path"], expected_snapshot, "tokenizer model cache binding")
    _same(tokenizer_identity["snapshot_revision"], revision, "tokenizer revision binding")
    _same(tokenizer_identity["remote_serving_parity_verified"], False, "tokenizer attestation boundary")
    _same(binding["binding_sha256"], content_hash({k: v for k, v in binding.items() if k != "binding_sha256"}), "environment binding digest")
    checks = binding["checks"]
    _same(checks, [{"check_id": name, "passed": True} for name in _ENVIRONMENT_CHECKS], "complete ordered deployment check receipts")
    _require(isinstance(checks, list) and bool(checks) and len({r["check_id"] for r in checks}) == len(checks), "unique retained deployment checks")
    for check in checks:
        _same(check, {"check_id": check["check_id"], "passed": True}, "retained deployment check outcome")
        _require(isinstance(check["check_id"], str) and re.fullmatch(r"[a-z0-9_]+", check["check_id"]) is not None, "deployment check ID")
    expected_binding = {
        "schema_version": "grailqa-guarded-environment-binding-v1", "success": True, "checks": checks,
        "runner_commit": commit, "slurm_job_id": job, "model_revision": revision,
        "spec_sha256": digest(spec.path), "spec_freeze_hash": spec.data["freeze_hash"],
        "model_bundle_hash": model.bundle_hash, "prompt_hash": model.prompt.prompt_hash,
        "deployment_contract_hash": contract.contract_hash, "environment_sha256": content_hash(environment),
        "deployment_binding_checked": True, "validation_scope": "record_bindings_only_not_serving_process_verification",
        "remote_serving_parity_verified": False, "paper_result": False,
    }
    _same(binding, {**expected_binding, "binding_sha256": content_hash(expected_binding)}, "complete deployment binding record")
    _same(launch, {
        "schema_version": "grailqa-guarded-launch-binding-v1", "runner_commit": commit,
        "spec_freeze_hash": spec.data["freeze_hash"], "slurm_job_id": job, "question_count": 18,
        "serving_python": str(Path(shared["vllm_env"]) / "bin/python"), "contract_hash": contract.contract_hash,
        "paper_result": False, "automatic_retries": 0, "author_receipt_created": False,
        "candidate_grounding_policy": SEMANTIC_GROUNDING_POLICY, "candidate_repair_policy": TYPED_GROUNDING_ONCE,
    }, "prelaunch handoff binding")
    return {"slurm_job_id": job, "record_bindings_verified": True, "serving_process_verified": False}
