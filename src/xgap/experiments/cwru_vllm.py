"""CWRU Pioneer vLLM serving checks and reproducibility artifacts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time
from typing import Any, Callable, Mapping, Sequence
import urllib.error
import urllib.request

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.hashing import content_hash
from xgap.experiments.live_run import build_openai_compatible_provider
from xgap.llm.openai_compatible import UrllibOpenAICompatibleTransport


CONTRACT_SCHEMA_VERSION = "m13e2-cwru-vllm-environment-v1"
RUN_ENVIRONMENT_SCHEMA_VERSION = "m13e2-cwru-run-environment-v1"


@dataclass(frozen=True)
class CWRUVLLMContract:
    path: Path
    data: Mapping[str, Any]

    @classmethod
    def load(cls, path: str | Path) -> "CWRUVLLMContract":
        contract_path = Path(path).resolve()
        loaded = json.loads(contract_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, Mapping):
            raise ValueError("CWRU vLLM contract root must be an object.")
        data = dict(loaded)
        if data.get("schema_version") != CONTRACT_SCHEMA_VERSION:
            raise ValueError("Unsupported CWRU vLLM environment contract.")
        expected = str(data.get("contract_hash", ""))
        payload = {key: value for key, value in data.items() if key != "contract_hash"}
        if content_hash(payload) != expected:
            raise ValueError("CWRU vLLM contract_hash does not match canonical content.")
        for field in ("cluster", "scheduler", "shared_paths", "runtime", "serving", "slurm"):
            if not data.get(field):
                raise ValueError(f"CWRU vLLM contract field '{field}' is required.")
        return cls(contract_path, data)

    @property
    def contract_hash(self) -> str:
        return str(self.data["contract_hash"])

    @property
    def model(self) -> str:
        return str(_mapping(self.data["serving"], "serving")["model"])


class VLLMReadinessError(RuntimeError):
    """Raised when the bounded local vLLM readiness check times out."""


def wait_for_vllm_model(
    *,
    base_url: str,
    model: str,
    api_key: str,
    timeout_seconds: float,
    interval_seconds: float = 5.0,
    fetch_json: Callable[[str, str, float], Mapping[str, Any]] | None = None,
    monotonic: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Poll the OpenAI-compatible models endpoint for one exact served model."""

    if timeout_seconds <= 0 or interval_seconds <= 0:
        raise ValueError("Readiness timeout and interval must be positive.")
    fetch = fetch_json or _get_json
    clock = monotonic or time.monotonic
    pause = sleep or time.sleep
    url = base_url.rstrip("/") + "/models"
    deadline = clock() + timeout_seconds
    attempts = 0
    last_error = "model was not returned"
    last_models: tuple[str, ...] = ()
    while True:
        attempts += 1
        try:
            response = fetch(url, api_key, min(10.0, timeout_seconds))
            last_models = _served_model_ids(response)
            if model in last_models:
                return {
                    "schema_version": "m13e2-vllm-readiness-v1",
                    "url": url,
                    "model": model,
                    "attempts": attempts,
                    "served_models": list(last_models),
                    "ready": True,
                }
            last_error = f"served models were {list(last_models)}"
        except (OSError, ValueError, urllib.error.URLError) as error:
            last_error = str(error)
        now = clock()
        if now >= deadline:
            raise VLLMReadinessError(
                f"Timed out after {timeout_seconds:g}s waiting for '{model}' at {url}; "
                f"last observation: {last_error}."
            )
        pause(min(interval_seconds, max(0.0, deadline - now)))


def run_structured_output_smoke(
    *,
    base_url: str,
    model: str,
    api_key: str,
    timeout_seconds: float = 60.0,
    transport: UrllibOpenAICompatibleTransport | None = None,
) -> dict[str, Any]:
    """Verify non-thinking JSON Schema serving without invoking XGAP semantics."""

    schema = {
        "type": "object",
        "properties": {"status": {"type": "string", "const": "ok"}},
        "required": ["status"],
        "additionalProperties": False,
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Return only the JSON object required by the response schema.",
            },
            {"role": "user", "content": "Report status ok."},
        ],
        "temperature": 0.0,
        "top_p": 1.0,
        "max_tokens": 32,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "xgap_vllm_serving_smoke",
                "strict": True,
                "schema": schema,
            },
        },
        "chat_template_kwargs": {"enable_thinking": False},
    }
    client = transport or UrllibOpenAICompatibleTransport(user_agent="xgap-m13e2/1")
    response = client.post_json(
        url=base_url.rstrip("/") + "/chat/completions",
        api_key=api_key,
        payload=payload,
        timeout_seconds=timeout_seconds,
    )
    content = _response_content(response)
    if content != {"status": "ok"}:
        raise ValueError(
            "vLLM structured-output smoke response did not satisfy the frozen tiny schema."
        )
    return {
        "schema_version": "m13e2-vllm-structured-smoke-v1",
        "model": model,
        "endpoint": base_url.rstrip("/") + "/chat/completions",
        "request_hash": content_hash(payload),
        "request": payload,
        "response_id": str(response.get("id", "")) or None,
        "validated_content": content,
        "schema_valid": True,
        "secrets_persisted": False,
    }


def resolve_cached_model_revision(
    *, model: str, hf_home: str | Path, requested_revision: str | None = None
) -> str:
    """Resolve one existing Hugging Face cache snapshot without network access."""

    if not model or model.startswith("/") or ".." in model.split("/"):
        raise ValueError("A safe Hugging Face repository model ID is required.")
    cache = Path(hf_home).expanduser().resolve() / "hub" / (
        "models--" + model.replace("/", "--")
    )
    snapshots = cache / "snapshots"
    revision = requested_revision.strip() if requested_revision else "main"
    if Path(revision).is_absolute() or ".." in Path(revision).parts:
        raise ValueError("Model revision must be a cache revision name or snapshot hash.")
    direct = snapshots / revision
    if direct.is_dir():
        return revision
    ref = cache / "refs" / revision
    if ref.is_file():
        resolved = ref.read_text(encoding="utf-8").strip()
        if resolved and (snapshots / resolved).is_dir():
            return resolved
        raise FileNotFoundError(f"Hugging Face ref '{revision}' has no cached snapshot.")
    if requested_revision is None and snapshots.is_dir():
        available = sorted(path.name for path in snapshots.iterdir() if path.is_dir())
        if len(available) == 1:
            return available[0]
        if len(available) > 1:
            raise ValueError(
                "Multiple cached model snapshots exist and refs/main is unavailable; "
                "set XGAP_MODEL_REVISION explicitly."
            )
    raise FileNotFoundError(
        f"No cached snapshot for {model!r} revision {revision!r} under {cache}."
    )


def verify_runtime_environment(contract: CWRUVLLMContract) -> dict[str, Any]:
    """Fail when the activated CWRU environment differs from the frozen contract."""

    runtime = _mapping(contract.data["runtime"], "runtime")
    observed = _runtime_versions()
    expected = {
        "python": str(runtime["python"]),
        "torch": str(runtime["torch"]),
        "cuda_runtime": str(runtime["cuda_runtime"]),
        "vllm": str(runtime["vllm"]),
    }
    differences = {
        key: {"expected": value, "observed": observed.get(key)}
        for key, value in expected.items()
        if observed.get(key) != value
    }
    if differences:
        raise ValueError(f"CWRU runtime does not match frozen contract: {differences}")
    return {
        "schema_version": "m13e2-cwru-runtime-verification-v1",
        "status": "pass",
        "contract_hash": contract.contract_hash,
        "runtime": observed,
    }


def verify_preflight_token_budget(
    *, repo_root: str | Path, spec_path: str | Path, contract_path: str | Path
) -> dict[str, Any]:
    """Verify that the frozen request budget fits the served context window."""

    repo = Path(repo_root).resolve()
    spec_file = (
        (repo / spec_path).resolve()
        if not Path(spec_path).is_absolute()
        else Path(spec_path).resolve()
    )
    spec = json.loads(spec_file.read_text(encoding="utf-8"))
    if not isinstance(spec, Mapping):
        raise ValueError("Experiment spec root must be an object.")
    contract = CWRUVLLMContract.load(contract_path)
    if spec.get("deployment_contract_hash") != contract.contract_hash:
        raise ValueError("Experiment spec deployment contract hash does not match CWRU.")
    model_root = spec.get("model_bundle_root")
    if not isinstance(model_root, str) or not model_root:
        raise ValueError("Experiment spec must identify a model bundle.")
    model = ModelBundle.load(repo / model_root)
    if model.bundle_hash != spec.get("model_bundle_hash"):
        raise ValueError("Experiment spec model bundle hash does not match the bundle.")
    input_tokens = int(model.config.token_limits.get("input", 0))
    output_tokens = int(model.config.token_limits.get("output", 0))
    context_tokens = int(
        _mapping(contract.data["serving"], "serving").get("max_model_len", 0)
    )
    if min(input_tokens, output_tokens, context_tokens) <= 0:
        raise ValueError("Input, output, and context token budgets must be positive.")
    required_tokens = input_tokens + output_tokens
    if required_tokens > context_tokens:
        raise ValueError(
            "Frozen request token budget exceeds the served context window: "
            f"input={input_tokens}, output={output_tokens}, "
            f"required={required_tokens}, context={context_tokens}."
        )
    return {
        "schema_version": "m13e3b5-cwru-token-budget-v1",
        "status": "pass",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "required_tokens": required_tokens,
        "context_tokens": context_tokens,
    }


def collect_run_environment(
    *,
    repo_root: str | Path,
    spec_path: str | Path,
    contract_path: str | Path,
) -> dict[str, Any]:
    """Collect a whitelisted, credential-free CWRU run environment record."""

    repo = Path(repo_root).resolve()
    spec_file = (repo / spec_path).resolve() if not Path(spec_path).is_absolute() else Path(spec_path)
    contract = CWRUVLLMContract.load(contract_path)
    spec = json.loads(spec_file.read_text(encoding="utf-8"))
    if not isinstance(spec, Mapping):
        raise ValueError("Experiment spec root must be an object.")
    model_root = spec.get("model_bundle_root") or spec.get("model_bundle")
    if not isinstance(model_root, str) or not model_root:
        raise ValueError("Experiment spec must identify a model bundle.")
    model = ModelBundle.load(repo / model_root)
    provider = build_openai_compatible_provider(model)
    revision = os.environ.get("XGAP_RESOLVED_MODEL_REVISION")
    if not revision:
        shared = _mapping(contract.data["shared_paths"], "shared_paths")
        revision = resolve_cached_model_revision(
            model=provider.config.model,
            hf_home=str(shared["hf_home"]),
            requested_revision=os.environ.get("XGAP_MODEL_REVISION"),
        )
    commit = _command(("git", "rev-parse", "HEAD"), cwd=repo)
    git_status = _command(("git", "status", "--porcelain"), cwd=repo, allow_failure=True)
    gpu = _gpu_metadata()
    serving = _mapping(contract.data["serving"], "serving")
    from xgap.experiments.cwru_gpu_profile import collect_visible_gpus, profile_for
    gpu_profile = profile_for(contract.data)
    if gpu_profile is not None:
        gpu = collect_visible_gpus(gpu_profile)
    record = {
        "schema_version": RUN_ENVIRONMENT_SCHEMA_VERSION,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "cluster": str(contract.data["cluster"]),
        "scheduler": str(contract.data["scheduler"]),
        "hostname": socket.gethostname(),
        "slurm": {
            "job_id": os.environ.get("SLURM_JOB_ID"),
            "job_name": os.environ.get("SLURM_JOB_NAME"),
            "node_list": os.environ.get("SLURM_JOB_NODELIST"),
        },
        "git": {
            "commit": commit,
            "clean": not bool(git_status.strip()),
            "status": git_status.splitlines(),
        },
        "runtime": {
            **_runtime_versions(),
            "python_executable": sys.executable,
        },
        "gpu": gpu,
        "model": {
            "name": provider.config.model,
            "revision": revision,
            "hf_home": str(_mapping(contract.data["shared_paths"], "shared_paths")["hf_home"]),
            "dtype": str(serving["dtype"]),
            "max_model_len": int(serving["max_model_len"]),
            "gpu_memory_utilization": float(serving["gpu_memory_utilization"]),
            "generation_config": str(serving["generation_config"]),
            "thinking_enabled": bool(serving["thinking_enabled"]),
        },
        "provider": {
            "id": provider.config.provider_id,
            "base_url": provider.config.base_url,
            "credential_env_name": provider.config.api_key_env,
            "credential_present": bool(os.environ.get(provider.config.api_key_env)),
            "structured_output_mode": provider.config.structured_output_mode,
        },
        "experiment": {
            "spec_path": str(spec_file.relative_to(repo)),
            "spec_sha256": _file_sha256(spec_file),
            "spec_freeze_hash": spec.get("freeze_hash"),
            "model_bundle_hash": model.bundle_hash,
            "prompt_hash": model.prompt.prompt_hash,
        },
        "environment_contract": {
            "path": str(contract.path.relative_to(repo)),
            "hash": contract.contract_hash,
        },
        "secrets_persisted": False,
    }
    if gpu_profile is not None:
        record["model"].update(tensor_parallel_size=gpu_profile.tensor_parallel_size,
                               pipeline_parallel_size=gpu_profile.pipeline_parallel_size)
    _assert_no_credential_values(record)
    return record


def load_run_environment(path: str | Path) -> dict[str, Any]:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ValueError("CWRU run environment root must be an object.")
    record = dict(loaded)
    if record.get("schema_version") != RUN_ENVIRONMENT_SCHEMA_VERSION:
        raise ValueError("Unsupported CWRU run environment artifact.")
    _assert_no_credential_values(record)
    return record


def finalize_run(root: str | Path, exit_code: int) -> dict[str, Any]:
    run_root = Path(root).resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    excluded = {"artifact_inventory.json", "run_status.json"}
    inventory = []
    for path in sorted(item for item in run_root.rglob("*") if item.is_file()):
        relative = str(path.relative_to(run_root))
        if relative in excluded:
            continue
        inventory.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": _file_sha256(path),
            }
        )
    _write_json(
        run_root / "artifact_inventory.json",
        {"schema_version": "m13e2-artifact-inventory-v1", "files": inventory},
    )
    status = {
        "schema_version": "m13e2-cwru-run-status-v1",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "exit_code": int(exit_code),
        "status": "success" if exit_code == 0 else "failed",
        "artifact_count": len(inventory),
    }
    _write_json(run_root / "run_status.json", status)
    return status


def _get_json(url: str, api_key: str, timeout_seconds: float) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}", "User-Agent": "xgap-m13e2/1"},
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        loaded = json.loads(response.read().decode("utf-8"))
    if not isinstance(loaded, Mapping):
        raise ValueError("OpenAI-compatible response root must be an object.")
    return loaded


def _served_model_ids(response: Mapping[str, Any]) -> tuple[str, ...]:
    data = response.get("data")
    if not isinstance(data, list):
        raise ValueError("Models response requires a data list.")
    return tuple(
        str(item["id"])
        for item in data
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    )


def _response_content(response: Mapping[str, Any]) -> dict[str, Any]:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("Smoke response has no choices[0].message.content.") from error
    value = json.loads(content) if isinstance(content, str) else content
    if not isinstance(value, Mapping):
        raise ValueError("Smoke response content must be a JSON object.")
    return dict(value)


def _runtime_versions() -> dict[str, str | None]:
    try:
        import torch  # type: ignore[import-not-found]

        torch_version = str(torch.__version__)
        cuda_runtime = str(torch.version.cuda) if torch.version.cuda is not None else None
    except (ImportError, AttributeError):
        torch_version = None
        cuda_runtime = None
    try:
        vllm_version = importlib.metadata.version("vllm")
    except importlib.metadata.PackageNotFoundError:
        vllm_version = None
    return {
        "python": platform.python_version(),
        "torch": torch_version,
        "cuda_runtime": cuda_runtime,
        "vllm": vllm_version,
    }


def _gpu_metadata() -> dict[str, Any]:
    output = _command(
        (
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total",
            "--format=csv,noheader,nounits",
        ),
        allow_failure=True,
    )
    first = output.splitlines()[0] if output else ""
    values = [item.strip() for item in first.split(",")]
    if len(values) != 3:
        return {"status": "unavailable", "model": None, "driver_version": None, "memory_mib": None}
    try:
        memory = int(values[2])
    except ValueError:
        memory = None
    return {
        "status": "available",
        "model": values[0],
        "driver_version": values[1],
        "memory_mib": memory,
    }


def _command(
    args: Sequence[str], *, cwd: Path | None = None, allow_failure: bool = False
) -> str:
    try:
        result = subprocess.run(
            tuple(args),
            cwd=cwd,
            check=not allow_failure,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        if allow_failure:
            return ""
        raise
    return result.stdout.strip()


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"CWRU contract field '{name}' must be an object.")
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_no_credential_values(value: Mapping[str, Any]) -> None:
    forbidden = {"api_key", "authorization", "password", "secret", "access_token"}
    stack: list[object] = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, Mapping):
            for key, child in item.items():
                if str(key).lower() in forbidden:
                    raise ValueError(f"Credential field '{key}' must not be persisted.")
                stack.append(child)
        elif isinstance(item, list | tuple):
            stack.extend(item)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    ready = subparsers.add_parser("check-ready")
    ready.add_argument("--base-url", required=True)
    ready.add_argument("--model", required=True)
    ready.add_argument("--api-key", required=True)
    ready.add_argument("--timeout", type=float, default=900.0)
    ready.add_argument("--interval", type=float, default=5.0)

    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--base-url", required=True)
    smoke.add_argument("--model", required=True)
    smoke.add_argument("--api-key", required=True)
    smoke.add_argument("--timeout", type=float, default=60.0)
    smoke.add_argument("--output", required=True)

    revision = subparsers.add_parser("resolve-revision")
    revision.add_argument("--model", required=True)
    revision.add_argument("--hf-home", required=True)
    revision.add_argument("--revision")

    verify = subparsers.add_parser("verify-environment")
    verify.add_argument("--contract", required=True)

    token_budget = subparsers.add_parser("verify-token-budget")
    token_budget.add_argument("--repo-root", required=True)
    token_budget.add_argument("--spec", required=True)
    token_budget.add_argument("--contract", required=True)

    capture = subparsers.add_parser("capture-environment")
    capture.add_argument("--repo-root", required=True)
    capture.add_argument("--spec", required=True)
    capture.add_argument("--contract", required=True)
    capture.add_argument("--output", required=True)

    finalize = subparsers.add_parser("finalize-run")
    finalize.add_argument("--root", required=True)
    finalize.add_argument("--exit-code", type=int, required=True)

    args = parser.parse_args(argv)
    if args.command == "check-ready":
        result = wait_for_vllm_model(
            base_url=args.base_url,
            model=args.model,
            api_key=args.api_key,
            timeout_seconds=args.timeout,
            interval_seconds=args.interval,
        )
    elif args.command == "smoke":
        result = run_structured_output_smoke(
            base_url=args.base_url,
            model=args.model,
            api_key=args.api_key,
            timeout_seconds=args.timeout,
        )
        _write_json(Path(args.output), result)
    elif args.command == "resolve-revision":
        print(
            resolve_cached_model_revision(
                model=args.model,
                hf_home=args.hf_home,
                requested_revision=args.revision,
            )
        )
        return 0
    elif args.command == "verify-environment":
        result = verify_runtime_environment(CWRUVLLMContract.load(args.contract))
    elif args.command == "verify-token-budget":
        result = verify_preflight_token_budget(
            repo_root=args.repo_root,
            spec_path=args.spec,
            contract_path=args.contract,
        )
    elif args.command == "capture-environment":
        result = collect_run_environment(
            repo_root=args.repo_root,
            spec_path=args.spec,
            contract_path=args.contract,
        )
        _write_json(Path(args.output), result)
    else:
        result = finalize_run(args.root, args.exit_code)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
