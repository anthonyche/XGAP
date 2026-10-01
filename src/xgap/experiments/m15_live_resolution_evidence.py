"""Independent read-only audit for one M15-E2B CWRU live-resolution run."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.cwru_vllm import CWRUVLLMContract
from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_live_resolution import (
    PREFLIGHT_SCHEMA_VERSION,
    RUN_SCHEMA_VERSION,
    build_preflight_manifest,
    load_live_resolution_spec,
)
from xgap.llm import M15_RESOLUTION_INVOCATION_SCHEMA_VERSION
from xgap.tools import SEMANTIC_LLM_PROPOSE_TOOL


AUDIT_SCHEMA_VERSION = "m15-e2b-live-resolution-evidence-audit-v1"


def audit_live_resolution_run(
    *,
    run_root: str | Path,
    repo_root: str | Path,
    expected_commit: str,
) -> dict[str, Any]:
    """Reconstruct the successful gate without modifying its run tree."""

    root = Path(run_root).resolve()
    repo = Path(repo_root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"M15-E2B run root does not exist: {root}")
    if not _commit(expected_commit):
        raise ValueError("expected_commit must be an exact 40-hex commit")
    before = _tree_snapshot(root)
    checks: list[dict[str, Any]] = []

    def check(check_id: str, passed: bool, detail: Any = None) -> None:
        checks.append(
            {
                "check_id": check_id,
                "passed": bool(passed),
                "detail": detail,
            }
        )

    status = _load(root / "run_status.json")
    inventory = _load(root / "artifact_inventory.json")
    preflight = _load(root / "preflight_manifest.json")
    environment = _load(root / "cwru_environment.json")
    live_root = root / "live-resolution-run"
    manifest = _load(live_root / "run_manifest.json")
    goal = _load(live_root / "goal_state.json")
    invocation = _load(live_root / "provider_invocation.json")
    memory_snapshot = _load(live_root / "memory_snapshot.json")

    check("outer.schema", status.get("schema_version") == "m13e2-cwru-run-status-v1")
    check("outer.success", status.get("status") == "success")
    check("outer.exit_code", status.get("exit_code") == 0)
    check("preflight.schema", preflight.get("schema_version") == PREFLIGHT_SCHEMA_VERSION)
    check("preflight.git_commit", preflight.get("git_commit") == expected_commit)
    check("preflight.git_clean", preflight.get("git_clean") is True)
    check("preflight.no_external_calls", preflight.get("preflight_external_calls") == 0)
    check("preflight.no_repairs", preflight.get("provider_max_repair_calls") == 0)
    check(
        "preflight.hash",
        preflight.get("preflight_sha256")
        == content_hash(
            {key: value for key, value in preflight.items() if key != "preflight_sha256"}
        ),
    )

    spec_path = repo / str(preflight.get("spec_path", ""))
    _, spec = load_live_resolution_spec(repo, spec_path)
    reconstructed = build_preflight_manifest(
        repo_root=repo,
        spec_path=spec_path,
        git_commit_override=expected_commit,
        git_clean_override=True,
    )
    check("preflight.reconstructed_exactly", reconstructed == preflight)
    check("spec.freeze_hash", spec.get("freeze_hash") == preflight.get("spec_freeze_hash"))
    check("spec.file_hash", _file_sha256(spec_path) == preflight.get("spec_file_sha256"))

    contract_path = repo / str(preflight.get("deployment_contract_path", ""))
    contract = CWRUVLLMContract.load(contract_path)
    check(
        "deployment.contract_hash",
        contract.contract_hash == preflight.get("deployment_contract_hash"),
    )
    runtime_expected = dict(contract.data["runtime"])
    environment_runtime = _mapping(environment.get("runtime"), "environment.runtime")
    for field in ("python", "torch", "cuda_runtime", "vllm"):
        check(
            f"environment.runtime.{field}",
            environment_runtime.get(field) == runtime_expected.get(field),
            {
                "expected": runtime_expected.get(field),
                "observed": environment_runtime.get(field),
            },
        )
    environment_git = _mapping(environment.get("git"), "environment.git")
    check("environment.git_commit", environment_git.get("commit") == expected_commit)
    check("environment.git_clean", environment_git.get("clean") is True)
    environment_slurm = _mapping(environment.get("slurm"), "environment.slurm")
    check(
        "environment.slurm_job",
        isinstance(environment_slurm.get("job_id"), str)
        and bool(str(environment_slurm.get("job_id")).strip()),
    )
    environment_gpu = _mapping(environment.get("gpu"), "environment.gpu")
    check("environment.gpu_available", environment_gpu.get("status") == "available")
    check(
        "environment.h100",
        "H100" in str(environment_gpu.get("model", "")),
        environment_gpu.get("model"),
    )
    environment_model = _mapping(environment.get("model"), "environment.model")
    check("environment.model", environment_model.get("name") == preflight.get("model"))
    check(
        "environment.model_revision",
        isinstance(environment_model.get("revision"), str)
        and bool(str(environment_model.get("revision")).strip()),
    )
    check("environment.thinking_disabled", environment_model.get("thinking_enabled") is False)
    environment_provider = _mapping(
        environment.get("provider"), "environment.provider"
    )
    check(
        "environment.provider",
        environment_provider.get("id") == preflight.get("provider_id"),
    )
    check(
        "environment.loopback_endpoint",
        environment_provider.get("base_url") == "http://127.0.0.1:8000/v1",
    )
    check(
        "environment.credential_present",
        environment_provider.get("credential_present") is True,
    )
    check("environment.no_secrets", environment.get("secrets_persisted") is False)
    captured_at = _parse_datetime(environment.get("captured_at"))
    launch_at = _parse_datetime(
        (root / "service_launch_requested_at.txt").read_text(encoding="utf-8").strip()
    )
    check(
        "lifecycle.capture_after_launch",
        launch_at is not None and captured_at is not None and launch_at <= captured_at,
    )
    shutdown = (root / "service_shutdown.txt").read_text(encoding="utf-8").strip()
    check("lifecycle.shutdown", shutdown in {"sigterm", "sigkill"}, shutdown)

    check("live.schema", manifest.get("schema_version") == RUN_SCHEMA_VERSION)
    check("live.success", manifest.get("status") == "success")
    check("live.git_commit", manifest.get("git_commit") == expected_commit)
    check("live.paper_result", manifest.get("paper_result") is False)
    check("live.no_retries", manifest.get("automatic_retries") == 0)
    check("live.non_authoritative", manifest.get("authoritative_binding") is False)
    check(
        "live.manifest_hash",
        manifest.get("manifest_sha256")
        == content_hash(
            {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        ),
    )
    check(
        "live.goal_hash",
        manifest.get("goal_state_sha256") == _file_sha256(live_root / "goal_state.json"),
    )
    check(
        "live.invocation_file_hash",
        manifest.get("provider_invocation_sha256")
        == _file_sha256(live_root / "provider_invocation.json"),
    )
    check(
        "live.memory_log_hash",
        manifest.get("execution_memory_sha256")
        == _file_sha256(live_root / "execution_memory.jsonl"),
    )
    check(
        "live.memory_snapshot_hash",
        manifest.get("memory_snapshot_sha256")
        == _file_sha256(live_root / "memory_snapshot.json"),
    )
    check(
        "live.environment_hash",
        manifest.get("run_environment_sha256")
        == _file_sha256(root / "cwru_environment.json"),
    )

    check("goal.status", goal.get("status") == "succeeded")
    check("goal.tool_calls", goal.get("tool_calls") == 1)
    goal_contract = _mapping(goal.get("goal"), "goal contract")
    check("goal.max_steps", goal_contract.get("max_steps") == 2)
    check("goal.max_tool_calls", goal_contract.get("max_tool_calls") == 1)
    check("goal.preflight_contract", goal_contract == preflight.get("goal_contract"))
    trace = goal.get("trace")
    check("goal.trace_shape", isinstance(trace, list) and len(trace) == 2)
    if isinstance(trace, list) and len(trace) == 2:
        check("goal.trace_call", trace[0].get("tool_name") == SEMANTIC_LLM_PROPOSE_TOOL)
        check("goal.trace_call_success", trace[0].get("tool_status") == "success")
        check("goal.trace_terminal", trace[1].get("decision_kind") == "succeed")
    observations = goal.get("observations")
    check(
        "goal.observation_shape",
        isinstance(observations, list) and len(observations) == 2,
    )
    tool_result: Mapping[str, Any] = {}
    if isinstance(observations, list) and len(observations) == 2:
        tool_result = _mapping(observations[1].get("payload"), "tool result")
        check("tool.name", tool_result.get("tool_name") == SEMANTIC_LLM_PROPOSE_TOOL)
        check("tool.status", tool_result.get("status") == "success")
        metrics = _mapping(tool_result.get("metrics"), "tool metrics")
        check("tool.external_calls", metrics.get("external_calls") == 1.0)
        metadata = _mapping(tool_result.get("metadata"), "tool metadata")
        check("tool.bounded", metadata.get("bounded_candidate_ids") is True)
        check("tool.no_native_query", metadata.get("native_query_text_allowed") is False)
        value = _mapping(tool_result.get("value"), "tool value")
        value_metadata = _mapping(value.get("metadata"), "tool value metadata")
        check("tool.no_repairs", value_metadata.get("provider_repair_calls") == 0)
        allowed = set(spec["request"]["candidate_ids"])
        selected = value.get("candidate_ids")
        check(
            "tool.candidate_subset",
            isinstance(selected, list)
            and bool(selected)
            and len(selected) == len(set(selected))
            and set(selected).issubset(allowed),
            selected,
        )
        check("tool.non_authoritative", value.get("authoritative") is False)

    check(
        "invocation.schema",
        invocation.get("schema_version") == M15_RESOLUTION_INVOCATION_SCHEMA_VERSION,
    )
    check("invocation.success", invocation.get("status") == "success")
    check("invocation.external_calls", invocation.get("external_calls") == 1)
    check("invocation.no_failure", invocation.get("failure_category") is None)
    check("invocation.no_error", invocation.get("error_message") is None)
    check("invocation.model", invocation.get("model") == preflight.get("model"))
    check(
        "invocation.hard_constraints",
        invocation.get("hard_constraints_sha256")
        == preflight.get("hard_constraints_sha256"),
    )
    check(
        "invocation.request_hash",
        invocation.get("request_payload_sha256")
        == preflight.get("request_payload_sha256"),
    )
    check(
        "invocation.schema_hash",
        invocation.get("dynamic_schema_sha256")
        == preflight.get("dynamic_schema_sha256"),
    )
    check("invocation.response_hash", _sha256(invocation.get("response_sha256")))
    check("invocation.usage_reported", invocation.get("usage_reported") is True)
    input_tokens = invocation.get("input_tokens")
    output_tokens = invocation.get("output_tokens")
    total_tokens = invocation.get("total_tokens")
    check(
        "invocation.token_arithmetic",
        _nonnegative_int(input_tokens)
        and _nonnegative_int(output_tokens)
        and _nonnegative_int(total_tokens)
        and input_tokens + output_tokens == total_tokens,
    )
    invocation_hash = content_hash(invocation)
    if tool_result:
        value = _mapping(tool_result.get("value"), "tool value")
        value_metadata = _mapping(value.get("metadata"), "tool value metadata")
        check(
            "invocation.hash_link",
            value_metadata.get("invocation_sha256") == invocation_hash,
        )
        check(
            "invocation.prompt_hash_link",
            value_metadata.get("prompt_sha256") == preflight.get("prompt_hash"),
        )

    records = memory_snapshot.get("records")
    check("memory.one_record", isinstance(records, list) and len(records) == 1)
    jsonl_lines = (live_root / "execution_memory.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    check("memory.one_jsonl_line", len(jsonl_lines) == 1)
    if isinstance(records, list) and len(records) == 1 and len(jsonl_lines) == 1:
        check("memory.snapshot_matches_log", records[0] == json.loads(jsonl_lines[0]))
        check("memory.scope", records[0].get("scope") == "execution")
        check(
            "memory.tool_result",
            records[0].get("value")
            == {key: value for key, value in tool_result.items() if key != "call_id"},
        )

    summary = _mapping(manifest.get("summary"), "manifest.summary")
    goal_output = _mapping(goal.get("output"), "goal.output")
    candidate_sets = goal_output.get("candidate_sets")
    output_candidates: list[str] = []
    if isinstance(candidate_sets, list) and len(candidate_sets) == 1:
        raw_candidates = candidate_sets[0].get("candidate_ids")
        if isinstance(raw_candidates, list):
            output_candidates = list(raw_candidates)
    check("summary.goal_status", summary.get("goal_status") == goal.get("status"))
    check("summary.goal_tool_calls", summary.get("goal_tool_calls") == 1)
    check("summary.llm_tool_calls", summary.get("llm_tool_calls") == 1)
    check("summary.external_calls", summary.get("provider_external_calls") == 1)
    check("summary.no_repairs", summary.get("provider_repair_calls") == 0)
    check("summary.candidates", summary.get("candidate_ids") == output_candidates)
    check("summary.hard_constraints", summary.get("hard_constraints_preserved") is True)
    check("summary.no_native_query", summary.get("native_query_text_emitted") is False)

    inventory_files = inventory.get("files")
    inventory_map = {
        item.get("path"): item
        for item in inventory_files
        if isinstance(item, Mapping) and isinstance(item.get("path"), str)
    } if isinstance(inventory_files, list) else {}
    actual_inventory_paths = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
        and str(path.relative_to(root))
        not in {"artifact_inventory.json", "run_status.json"}
    }
    check("inventory.schema", inventory.get("schema_version") == "m13e2-artifact-inventory-v1")
    check(
        "inventory.unique_paths",
        isinstance(inventory_files, list) and len(inventory_map) == len(inventory_files),
    )
    check("inventory.path_set", set(inventory_map) == actual_inventory_paths)
    check("inventory.count", status.get("artifact_count") == len(inventory_map))
    for relative, item in sorted(inventory_map.items()):
        path = root / relative
        check(
            f"inventory.hash.{relative}",
            path.is_file() and item.get("sha256") == _file_sha256(path),
        )
        check(
            f"inventory.size.{relative}",
            path.is_file() and item.get("size_bytes") == path.stat().st_size,
        )

    after = _tree_snapshot(root)
    run_tree_mutated = before != after
    check("audit.run_tree_unchanged", not run_tree_mutated)
    failed = [item["check_id"] for item in checks if not item["passed"]]
    result = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "expected_commit": expected_commit,
        "run_root": str(root),
        "success": not failed,
        "check_count": len(checks),
        "failed_check_ids": failed,
        "run_tree_mutated": run_tree_mutated,
        "checks": checks,
        "paper_result": False,
    }
    result["audit_sha256"] = content_hash(result)
    return result


def _load(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ValueError(f"artifact root must be an object: {path}")
    return dict(loaded)


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def _tree_snapshot(root: Path) -> tuple[tuple[str, int, str], ...]:
    return tuple(
        (
            str(path.relative_to(root)),
            path.stat().st_size,
            _file_sha256(path),
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _commit(value: object) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    )


def _sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _write_json_new(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(dict(value), handle, indent=2, sort_keys=True, ensure_ascii=True)
        handle.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    result = audit_live_resolution_run(
        run_root=args.run_root,
        repo_root=args.repo_root,
        expected_commit=args.expected_commit,
    )
    _write_json_new(Path(args.output), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
