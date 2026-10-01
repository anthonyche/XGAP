"""Fail-closed M15-E2B live semantic-resolution gate.

This module freezes one bounded predicate-resolution request before vLLM is
started, then executes it through the ordinary M15 goal loop.  It deliberately
does not evaluate answer quality: the gate proves the one-call/no-repair tool
boundary against a live OpenAI-compatible endpoint.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

from xgap.agent import (
    GoalLoop,
    GoalSpec,
    GoalStatus,
    JsonlMemoryStore,
    SelectiveResolutionConfig,
    SelectiveSemanticResolutionPolicy,
    build_selective_resolution_goal,
    hard_constraints_sha256,
    selective_resolution_environment,
)
from xgap.experiments.bundles import ModelBundle
from xgap.experiments.cwru_vllm import (
    CWRUVLLMContract,
    load_run_environment,
)
from xgap.experiments.hashing import content_hash
from xgap.llm import build_openai_compatible_resolution_provider
from xgap.llm.openai_compatible import OpenAICompatibleTransport
from xgap.semantic import (
    ConstraintPolicy,
    SemanticConstraint,
    SemanticGraphProgram,
    SemanticHole,
    SemanticHoleKind,
    SemanticOperator,
    SemanticOperatorKind,
    SemanticValueKind,
)
from xgap.tools import (
    ResolutionCandidateRequest,
    ResolutionCandidateTool,
    SEMANTIC_LLM_PROPOSE_TOOL,
    ToolEffect,
    ToolRegistry,
)


SPEC_SCHEMA_VERSION = "m15-e2b-live-resolution-spec-v1"
PREFLIGHT_SCHEMA_VERSION = "m15-e2b-live-resolution-preflight-v1"
RUN_SCHEMA_VERSION = "m15-e2b-live-resolution-run-v1"
SUPPORTED_HOLE_KINDS = {
    SemanticHoleKind.PREDICATE,
    SemanticHoleKind.TYPE,
    SemanticHoleKind.SOURCE,
}


def load_live_resolution_spec(
    repo_root: str | Path,
    spec_path: str | Path,
) -> tuple[Path, dict[str, Any]]:
    """Load and fully bind the frozen E2B request contract."""

    repo = Path(repo_root).resolve()
    path = _resolve_under(repo, spec_path, "experiment spec")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ValueError("M15-E2B spec root must be an object")
    spec = dict(loaded)
    if spec.get("schema_version") != SPEC_SCHEMA_VERSION:
        raise ValueError("unsupported M15-E2B live resolution spec")
    freeze_hash = spec.get("freeze_hash")
    if not _sha256(freeze_hash):
        raise ValueError("M15-E2B spec requires a SHA-256 freeze_hash")
    payload = {key: value for key, value in spec.items() if key != "freeze_hash"}
    if content_hash(payload) != freeze_hash:
        raise ValueError("M15-E2B spec freeze_hash does not match canonical content")

    required_strings = (
        "run_id",
        "deployment_contract_path",
        "deployment_contract_hash",
        "model_bundle_root",
        "model_bundle_hash",
        "expected_model",
        "expected_provider",
        "expected_base_url",
    )
    for name in required_strings:
        if not isinstance(spec.get(name), str) or not str(spec[name]).strip():
            raise ValueError(f"M15-E2B spec field '{name}' must be nonempty")
    if not _sha256(spec["deployment_contract_hash"]):
        raise ValueError("deployment_contract_hash must be SHA-256")
    if not _sha256(spec["model_bundle_hash"]):
        raise ValueError("model_bundle_hash must be SHA-256")

    request = _mapping(spec.get("request"), "request")
    if set(request) != {
        "program_id",
        "hole_id",
        "hole_kind",
        "mention",
        "question",
        "candidate_ids",
        "max_candidates",
        "hard_constraints",
    }:
        raise ValueError("M15-E2B request fields do not match the v1 contract")
    kind = SemanticHoleKind(str(request["hole_kind"]))
    if kind not in SUPPORTED_HOLE_KINDS:
        raise ValueError("M15-E2B live model request cannot resolve entity identity")
    candidates = request["candidate_ids"]
    if (
        not isinstance(candidates, list)
        or len(candidates) < 2
        or not all(isinstance(item, str) and item.strip() for item in candidates)
        or len(candidates) != len(set(candidates))
    ):
        raise ValueError("request candidate_ids must contain unique bounded strings")
    maximum = request["max_candidates"]
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum <= 0:
        raise ValueError("request max_candidates must be a positive integer")
    if len(candidates) > maximum:
        raise ValueError("request candidate_ids exceed max_candidates")
    for name in ("program_id", "hole_id", "mention", "question"):
        if not isinstance(request[name], str) or not request[name].strip():
            raise ValueError(f"request field '{name}' must be nonempty")
    constraints = request["hard_constraints"]
    if not isinstance(constraints, list) or not constraints:
        raise ValueError("request hard_constraints must be a nonempty array")
    seen_constraints: set[str] = set()
    for item in constraints:
        constraint = _mapping(item, "hard constraint")
        if set(constraint) != {"constraint_id", "expression"}:
            raise ValueError("hard constraint fields do not match the v1 contract")
        constraint_id = constraint["constraint_id"]
        expression = constraint["expression"]
        if not isinstance(constraint_id, str) or not constraint_id.strip():
            raise ValueError("hard constraint_id must be nonempty")
        if constraint_id in seen_constraints:
            raise ValueError("hard constraint IDs must be unique")
        seen_constraints.add(constraint_id)
        if not isinstance(expression, str) or not expression.strip():
            raise ValueError("hard constraint expression must be nonempty")

    execution = _mapping(spec.get("execution_contract"), "execution_contract")
    expected_execution = {
        "maximum_goal_tool_calls": 1,
        "maximum_llm_calls": 1,
        "maximum_provider_requests": 1,
        "maximum_repair_calls": 0,
        "automatic_retries": 0,
        "native_query_generation": False,
        "authoritative_binding": False,
        "paper_result": False,
    }
    if dict(execution) != expected_execution:
        raise ValueError("M15-E2B execution contract is not the frozen v1 policy")
    return path, spec


def build_semantic_program(spec: Mapping[str, Any]) -> SemanticGraphProgram:
    request = _mapping(spec["request"], "request")
    constraints = tuple(
        SemanticConstraint(
            str(item["constraint_id"]),
            str(item["expression"]),
            ConstraintPolicy.HARD,
        )
        for item in request["hard_constraints"]
    )
    operator = SemanticOperator(
        operator_id="semantic-intent",
        kind=SemanticOperatorKind.MATCH,
        input_ids=(),
        input_kinds=(),
        output_kind=SemanticValueKind.BINDING_SET,
        constraints=constraints,
    )
    hole = SemanticHole(
        hole_id=str(request["hole_id"]),
        kind=SemanticHoleKind(str(request["hole_kind"])),
        mention=str(request["mention"]),
        candidates=tuple(str(item) for item in request["candidate_ids"]),
    )
    return SemanticGraphProgram(
        program_id=str(request["program_id"]),
        operators=(operator,),
        roots=(operator.operator_id,),
        holes=(hole,),
        metadata={"gate": "m15-e2b-live-resolution"},
    )


def build_candidate_request(
    spec: Mapping[str, Any],
    program: SemanticGraphProgram,
) -> ResolutionCandidateRequest:
    request = _mapping(spec["request"], "request")
    return ResolutionCandidateRequest(
        program_id=program.program_id,
        hole_id=str(request["hole_id"]),
        hole_kind=SemanticHoleKind(str(request["hole_kind"])),
        mention=str(request["mention"]),
        candidate_ids=tuple(str(item) for item in request["candidate_ids"]),
        question=str(request["question"]),
        hard_constraints_sha256=hard_constraints_sha256(program),
        max_candidates=int(request["max_candidates"]),
    )


def build_live_resolution_goal(
    program: SemanticGraphProgram,
    config: SelectiveResolutionConfig,
) -> GoalSpec:
    """Narrow the general resolution goal to this gate's one-call budget."""

    return replace(
        build_selective_resolution_goal(program, config),
        max_steps=2,
        max_tool_calls=1,
    )


def build_preflight_manifest(
    *,
    repo_root: str | Path,
    spec_path: str | Path,
    git_commit_override: str | None = None,
    git_clean_override: bool | None = None,
) -> dict[str, Any]:
    """Reconstruct the exact request without contacting a service."""

    repo = Path(repo_root).resolve()
    path, spec = load_live_resolution_spec(repo, spec_path)
    contract_path = _resolve_under(repo, spec["deployment_contract_path"], "contract")
    contract = CWRUVLLMContract.load(contract_path)
    if contract.contract_hash != spec["deployment_contract_hash"]:
        raise ValueError("deployment contract hash does not match the E2B spec")
    model_root = _resolve_under(repo, spec["model_bundle_root"], "model bundle")
    model = ModelBundle.load(model_root)
    if model.bundle_hash != spec["model_bundle_hash"]:
        raise ValueError("model bundle hash does not match the E2B spec")
    provider = build_openai_compatible_resolution_provider(model)
    if provider.config.model != spec["expected_model"]:
        raise ValueError("effective model does not match the E2B spec")
    if provider.config.provider_id != spec["expected_provider"]:
        raise ValueError("effective provider does not match the E2B spec")
    if provider.config.base_url != spec["expected_base_url"]:
        raise ValueError("effective base URL does not match the E2B spec")
    if provider.config.max_repair_calls != 0:
        raise ValueError("E2B provider repairs must remain disabled")

    program = build_semantic_program(spec)
    request = build_candidate_request(spec, program)
    resolution_config = SelectiveResolutionConfig(
        use_catalog=False,
        use_ontology=False,
        use_llm=True,
        max_llm_calls=1,
        max_candidates_per_hole=int(spec["request"]["max_candidates"]),
    )
    goal = build_live_resolution_goal(program, resolution_config)
    payload, dynamic_schema = provider.build_request_payload(request)
    commit, clean = _git_state(repo)
    if git_commit_override is not None:
        commit = git_commit_override
    if git_clean_override is not None:
        clean = git_clean_override
    if not _commit(commit):
        raise ValueError("preflight requires an exact 40-hex Git commit")
    if not clean:
        raise ValueError("preflight refuses a dirty Git checkout")

    manifest = {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "run_id": spec["run_id"],
        "git_commit": commit,
        "git_clean": True,
        "spec_path": str(path.relative_to(repo)),
        "spec_file_sha256": _file_sha256(path),
        "spec_freeze_hash": spec["freeze_hash"],
        "deployment_contract_path": str(contract_path.relative_to(repo)),
        "deployment_contract_hash": contract.contract_hash,
        "model_bundle_root": str(model_root.relative_to(repo)),
        "model_bundle_hash": model.bundle_hash,
        "prompt_hash": model.prompt.prompt_hash,
        "structured_schema_hash": model.config.structured_schema_hash,
        "provider_id": provider.config.provider_id,
        "model": provider.config.model,
        "base_url": provider.config.base_url,
        "provider_timeout_seconds": provider.config.timeout_seconds,
        "provider_candidate_cap": provider.config.candidate_cap,
        "provider_output_token_cap": provider.config.max_tokens,
        "provider_max_repair_calls": provider.config.max_repair_calls,
        "program": program.to_dict(),
        "candidate_request": request.to_dict(),
        "goal_contract": goal.to_dict(),
        "hard_constraints_sha256": hard_constraints_sha256(program),
        "dynamic_schema": dynamic_schema,
        "dynamic_schema_sha256": content_hash(dynamic_schema),
        "request_payload_sha256": content_hash(payload),
        "execution_contract": dict(spec["execution_contract"]),
        "preflight_external_calls": 0,
        "secrets_persisted": False,
    }
    manifest["preflight_sha256"] = content_hash(manifest)
    return manifest


def write_preflight_manifest(
    *,
    repo_root: str | Path,
    spec_path: str | Path,
    output: str | Path,
) -> dict[str, Any]:
    manifest = build_preflight_manifest(repo_root=repo_root, spec_path=spec_path)
    _write_json_new(Path(output), manifest)
    return manifest


def run_live_resolution(
    *,
    repo_root: str | Path,
    spec_path: str | Path,
    preflight_path: str | Path,
    environment_path: str | Path,
    output_root: str | Path,
    transport_override: OpenAICompatibleTransport | None = None,
    git_commit_override: str | None = None,
    git_clean_override: bool | None = None,
) -> dict[str, Any]:
    """Execute one provider request through the M15 goal loop."""

    repo = Path(repo_root).resolve()
    path, spec = load_live_resolution_spec(repo, spec_path)
    expected_preflight = build_preflight_manifest(
        repo_root=repo,
        spec_path=path,
        git_commit_override=git_commit_override,
        git_clean_override=git_clean_override,
    )
    preflight_file = Path(preflight_path).resolve()
    preflight = _load_mapping(preflight_file, "preflight")
    if preflight != expected_preflight:
        raise ValueError("sealed preflight does not match reconstructed E2B request")
    environment = load_run_environment(environment_path)
    _validate_environment(environment, preflight)

    root = Path(output_root).resolve()
    if root.exists():
        raise FileExistsError(f"live resolution output already exists: {root}")
    root.mkdir(parents=True)
    model = ModelBundle.load(repo / str(spec["model_bundle_root"]))
    provider = build_openai_compatible_resolution_provider(model, transport_override)
    program = build_semantic_program(spec)
    memory_path = root / "execution_memory.jsonl"
    memory = JsonlMemoryStore(memory_path)
    registry = ToolRegistry()
    registry.register(
        ResolutionCandidateTool(
            name=SEMANTIC_LLM_PROPOSE_TOOL,
            description="one-call bounded M15 live semantic candidate proposal",
            provider=provider,
            may_introduce_candidates=False,
            effect=ToolEffect.EXTERNAL,
            remote=True,
            maximum_external_calls=1,
        )
    )
    config = SelectiveResolutionConfig(
        use_catalog=False,
        use_ontology=False,
        use_llm=True,
        max_llm_calls=1,
        max_candidates_per_hole=int(spec["request"]["max_candidates"]),
    )
    environment_object = selective_resolution_environment(
        registry,
        metadata={
            "deployment_contract_hash": spec["deployment_contract_hash"],
            "model_bundle_hash": spec["model_bundle_hash"],
            "live_provider_gate": True,
        },
    )
    environment_object.memory = memory
    started_at = datetime.now(timezone.utc).isoformat()
    state = GoalLoop().run(
        build_live_resolution_goal(program, config),
        SelectiveSemanticResolutionPolicy(
            program,
            str(spec["request"]["question"]),
            config,
        ),
        environment_object,
    )
    ended_at = datetime.now(timezone.utc).isoformat()
    invocation = provider.last_invocation
    invocation_value = invocation.to_dict() if invocation is not None else None
    _write_json_new(root / "goal_state.json", state.to_dict())
    _write_json_new(
        root / "provider_invocation.json",
        invocation_value
        or {
            "schema_version": "m15-e2b-missing-provider-invocation-v1",
            "status": "missing",
        },
    )
    memory_records = [record.to_dict() for record in memory.records()]
    _write_json_new(
        root / "memory_snapshot.json",
        {
            "schema_version": "m15-e2b-memory-snapshot-v1",
            "records": memory_records,
        },
    )
    success = (
        state.status is GoalStatus.SUCCEEDED
        and state.tool_calls == 1
        and invocation is not None
        and invocation.status == "success"
        and invocation.external_calls == 1
        and isinstance(state.output, Mapping)
        and state.output.get("hard_constraints_preserved") is True
        and state.output.get("native_query_text_emitted") is False
    )
    manifest = {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": spec["run_id"],
        "started_at": started_at,
        "ended_at": ended_at,
        "status": "success" if success else "failed",
        "git_commit": preflight["git_commit"],
        "spec_freeze_hash": spec["freeze_hash"],
        "preflight_sha256": preflight["preflight_sha256"],
        "run_environment_sha256": _file_sha256(Path(environment_path)),
        "model_bundle_hash": model.bundle_hash,
        "goal_state_sha256": _file_sha256(root / "goal_state.json"),
        "provider_invocation_sha256": _file_sha256(
            root / "provider_invocation.json"
        ),
        "execution_memory_sha256": _file_sha256(memory_path),
        "memory_snapshot_sha256": _file_sha256(root / "memory_snapshot.json"),
        "summary": {
            "goal_status": state.status.value,
            "goal_tool_calls": state.tool_calls,
            "llm_tool_calls": (
                state.output.get("llm_calls")
                if isinstance(state.output, Mapping)
                else None
            ),
            "provider_external_calls": (
                invocation.external_calls if invocation is not None else None
            ),
            "provider_repair_calls": 0,
            "input_tokens": invocation.input_tokens if invocation else 0,
            "output_tokens": invocation.output_tokens if invocation else 0,
            "latency_ms": invocation.latency_ms if invocation else 0.0,
            "candidate_ids": (
                list(state.output["candidate_sets"][0]["candidate_ids"])
                if success
                else []
            ),
            "hard_constraints_preserved": (
                state.output.get("hard_constraints_preserved")
                if isinstance(state.output, Mapping)
                else False
            ),
            "native_query_text_emitted": (
                state.output.get("native_query_text_emitted")
                if isinstance(state.output, Mapping)
                else None
            ),
        },
        "automatic_retries": 0,
        "authoritative_binding": False,
        "paper_result": False,
    }
    manifest["manifest_sha256"] = content_hash(manifest)
    _write_json_new(root / "run_manifest.json", manifest)
    return manifest


def _validate_environment(
    environment: Mapping[str, Any],
    preflight: Mapping[str, Any],
) -> None:
    git = _mapping(environment.get("git"), "run environment git")
    model = _mapping(environment.get("model"), "run environment model")
    provider = _mapping(environment.get("provider"), "run environment provider")
    experiment = _mapping(
        environment.get("experiment"), "run environment experiment"
    )
    contract = _mapping(
        environment.get("environment_contract"),
        "run environment contract",
    )
    if git.get("commit") != preflight["git_commit"] or git.get("clean") is not True:
        raise ValueError("run environment Git state differs from sealed preflight")
    if model.get("name") != preflight["model"]:
        raise ValueError("run environment model differs from sealed preflight")
    if provider.get("id") != preflight["provider_id"]:
        raise ValueError("run environment provider differs from sealed preflight")
    if provider.get("base_url") != preflight["base_url"]:
        raise ValueError("run environment base URL differs from sealed preflight")
    if provider.get("credential_present") is not True:
        raise ValueError("run environment lacks the declared provider credential")
    if experiment.get("model_bundle_hash") != preflight["model_bundle_hash"]:
        raise ValueError("run environment model bundle differs from sealed preflight")
    if experiment.get("prompt_hash") != preflight["prompt_hash"]:
        raise ValueError("run environment prompt differs from sealed preflight")
    if contract.get("hash") != preflight["deployment_contract_hash"]:
        raise ValueError("run environment contract differs from sealed preflight")


def _git_state(repo: Path) -> tuple[str, bool]:
    commit = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ("git", "status", "--porcelain"),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return commit, not bool(status)


def _resolve_under(repo: Path, value: str | Path, name: str) -> Path:
    raw = Path(value)
    path = raw.resolve() if raw.is_absolute() else (repo / raw).resolve()
    try:
        path.relative_to(repo)
    except ValueError as exc:
        raise ValueError(f"{name} must remain inside the repository") from exc
    if not path.exists():
        raise FileNotFoundError(f"{name} does not exist: {path}")
    return path


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _load_mapping(path: Path, name: str) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ValueError(f"{name} root must be an object")
    return dict(loaded)


def _file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _commit(value: object) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    )


def _write_json_new(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(dict(value), handle, indent=2, sort_keys=True, ensure_ascii=True)
        handle.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--repo-root", required=True)
    preflight.add_argument("--spec", required=True)
    preflight.add_argument("--output", required=True)
    run = commands.add_parser("run")
    run.add_argument("--repo-root", required=True)
    run.add_argument("--spec", required=True)
    run.add_argument("--preflight", required=True)
    run.add_argument("--environment", required=True)
    run.add_argument("--output-root", required=True)
    args = parser.parse_args(argv)
    if args.command == "preflight":
        result = write_preflight_manifest(
            repo_root=args.repo_root,
            spec_path=args.spec,
            output=args.output,
        )
    else:
        result = run_live_resolution(
            repo_root=args.repo_root,
            spec_path=args.spec,
            preflight_path=args.preflight,
            environment_path=args.environment,
            output_root=args.output_root,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status", "success") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
