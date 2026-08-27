from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping

import pytest

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.cwru_vllm import (
    CWRUVLLMContract,
    VLLMReadinessError,
    collect_run_environment,
    finalize_run,
    resolve_cached_model_revision,
    run_structured_output_smoke,
    verify_preflight_token_budget,
    wait_for_vllm_model,
)
from xgap.experiments.grailqa_preflight import (
    GrailQAPreflightSpec,
    build_preflight_run_manifest,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.live_run import build_openai_compatible_provider
from xgap.llm.schemas import PlannerRequest


ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = ROOT / "models/qwen3_32b_vllm_cwru_m13e2"
SPEC_PATH = ROOT / "experiments/specs/grailqa_semantic_preflight_v2_cwru_qwen3_32b.json"
CONTRACT_PATH = ROOT / "experiments/environments/cwru_pioneer_qwen3_32b_vllm.json"


class FakeTransport:
    def __init__(self, response: Mapping[str, Any]) -> None:
        self.response = dict(response)
        self.calls: list[dict[str, Any]] = []

    def post_json(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(dict(kwargs))
        return self.response


def _planner_request() -> PlannerRequest:
    return PlannerRequest(
        "Who is connected to Alice?",
        max_candidates=1,
        metadata={
            "task_id": "cwru-contract-test",
            "prompt_schema_view": {
                "ontology": {"id": "fixture", "version": "v1", "hash": "hash"},
                "terms": [{"term_id": "people.person.parents", "kind": "relation"}],
                "entities": [],
                "query_slots": [
                    {
                        "slot_id": "relation-1",
                        "candidate_anchor_ids": ["people.person.parents"],
                    }
                ],
            },
        },
    )


def _provider_response() -> dict[str, Any]:
    value = {
        "provider_id": "vllm_openai_compatible",
        "model": "Qwen/Qwen3-32B",
        "query_slots": [
            {"slot_id": "relation-1", "query_anchor_id": "people.person.parents"}
        ],
        "candidates": [
            {
                "candidate_id": "candidate-1",
                "confidence": 1.0,
                "rationale": None,
                "pattern_query": {
                    "path_var": "p",
                    "source": {"var": "x", "label": "people.person", "properties": {}},
                    "expr": {
                        "kind": "rel",
                        "edge": {
                            "var": "e",
                            "label": "people.person.parents",
                            "direction": "OUT",
                            "properties": {},
                        },
                    },
                    "target": {"var": "y", "label": "people.person", "properties": {}},
                    "selector": {"kind": "ALL", "k": None},
                    "restrictor": "SIMPLE",
                    "condition": None,
                    "max_depth": None,
                },
                "grounding": {
                    "slot_realizations": [
                        {
                            "slot_id": "relation-1",
                            "ontology_term_id": "people.person.parents",
                            "component_ref": "expr.edge",
                        }
                    ],
                    "entity_ids": [],
                },
            }
        ],
    }
    return {
        "id": "cwru-request-1",
        "choices": [{"message": {"content": json.dumps(value)}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    }


def test_cwru_bundle_externalizes_runtime_and_preserves_legacy_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = ModelBundle.load(MODEL_ROOT)
    legacy = ModelBundle.load(ROOT / "models/qwen3_max_dashscope_live_m13e1")
    assert legacy.bundle_hash == "07f0a41807cd010e8801db37d933cd620b4a2a1693b0cb8a1b88d33332e45061"
    assert bundle.bundle_hash == "ed9fa4db9f0981e7307ef7323415159fdeb5117c8ab308218d1c8d282360bd6e"
    assert bundle.config.provider == "vllm_openai_compatible"
    assert bundle.config.structured_output_mode == "json_schema"
    assert bundle.config.extra_parameters == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
    candidate_schema = bundle.structured_schema["properties"]["candidates"]
    assert candidate_schema["minItems"] == 1
    assert candidate_schema["maxItems"] == 3
    assert "at least one and at most max_candidates" in bundle.prompt.system_prompt

    monkeypatch.setenv("XGAP_LLM_BASE_URL", "http://localhost:9000/v1")
    monkeypatch.setenv("XGAP_LLM_MODEL", "local-frozen-name")
    provider = build_openai_compatible_provider(bundle)
    assert provider.config.base_url == "http://localhost:9000/v1"
    assert provider.config.model == "local-frozen-name"
    assert provider.config.api_key_env == "XGAP_LLM_API_KEY"


def test_cwru_exact_request_preserves_schema_and_non_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "test-key-must-not-be-persisted"
    monkeypatch.setenv("XGAP_LLM_API_KEY", secret)
    monkeypatch.setenv("XGAP_LLM_MODEL", "Qwen/Qwen3-32B")
    transport = FakeTransport(_provider_response())
    bundle = ModelBundle.load(MODEL_ROOT)
    provider = build_openai_compatible_provider(bundle, transport)

    provider.generate_candidates(_planner_request())

    payload = transport.calls[0]["payload"]
    assert payload["model"] == "Qwen/Qwen3-32B"
    assert payload["temperature"] == 0.0
    assert payload["top_p"] == 1.0
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["response_format"]["json_schema"]["schema"] == bundle.structured_schema
    artifact = provider.last_invocation
    assert artifact is not None
    exact_request = artifact.request_records()[0]
    assert exact_request["payload"] == payload
    assert exact_request["payload"]["chat_template_kwargs"]["enable_thinking"] is False
    assert secret not in json.dumps(exact_request)


def test_structured_output_smoke_uses_tiny_strict_schema() -> None:
    transport = FakeTransport(
        {
            "id": "smoke-1",
            "choices": [{"message": {"content": '{"status":"ok"}'}}],
        }
    )
    result = run_structured_output_smoke(
        base_url="http://127.0.0.1:8000/v1",
        model="Qwen/Qwen3-32B",
        api_key="local",
        transport=transport,  # type: ignore[arg-type]
    )
    payload = transport.calls[0]["payload"]
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    assert result["schema_valid"] is True
    assert "local" not in json.dumps(result)


def test_readiness_timeout_is_bounded_and_reports_last_observation() -> None:
    now = [0.0]

    def fetch(url: str, api_key: str, timeout: float) -> Mapping[str, Any]:
        del url, api_key, timeout
        raise OSError("connection refused")

    def monotonic() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    with pytest.raises(VLLMReadinessError, match="connection refused"):
        wait_for_vllm_model(
            base_url="http://127.0.0.1:8000/v1",
            model="Qwen/Qwen3-32B",
            api_key="local",
            timeout_seconds=3,
            interval_seconds=1,
            fetch_json=fetch,
            monotonic=monotonic,
            sleep=sleep,
        )
    assert now[0] == 3.0


def test_cached_revision_resolution_never_requires_download(tmp_path: Path) -> None:
    model_cache = tmp_path / "hub/models--Qwen--Qwen3-32B"
    snapshot = "a" * 40
    (model_cache / "snapshots" / snapshot).mkdir(parents=True)
    (model_cache / "refs").mkdir()
    (model_cache / "refs/main").write_text(snapshot + "\n", encoding="utf-8")

    assert resolve_cached_model_revision(
        model="Qwen/Qwen3-32B", hf_home=tmp_path
    ) == snapshot
    assert resolve_cached_model_revision(
        model="Qwen/Qwen3-32B", hf_home=tmp_path, requested_revision=snapshot
    ) == snapshot


def test_cwru_environment_and_preflight_manifest_are_complete_and_secret_free(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XGAP_LLM_API_KEY", "credential-value")
    monkeypatch.setenv("XGAP_RESOLVED_MODEL_REVISION", "b" * 40)
    monkeypatch.setenv("SLURM_JOB_ID", "12345")
    monkeypatch.setenv("SLURM_JOB_NAME", "xgap-test")
    monkeypatch.setenv("SLURM_JOB_NODELIST", "dynamic-node")

    def command(
        args: tuple[str, ...], *, cwd: Path | None = None, allow_failure: bool = False
    ) -> str:
        del cwd, allow_failure
        if args[:2] == ("git", "rev-parse"):
            return "c" * 40
        if args[:2] == ("git", "status"):
            return ""
        if args[0] == "nvidia-smi":
            return "NVIDIA H100 NVL, 570.00, 95830"
        raise AssertionError(args)

    monkeypatch.setattr("xgap.experiments.cwru_vllm._command", command)
    monkeypatch.setattr(
        "xgap.experiments.cwru_vllm._runtime_versions",
        lambda: {
            "python": "3.11.5",
            "torch": "2.9.0+cu128",
            "cuda_runtime": "12.8",
            "vllm": "0.11.1",
        },
    )
    record = collect_run_environment(
        repo_root=ROOT,
        spec_path=SPEC_PATH,
        contract_path=CONTRACT_PATH,
    )

    serialized = json.dumps(record)
    assert record["slurm"]["job_id"] == "12345"
    assert record["gpu"]["model"] == "NVIDIA H100 NVL"
    assert record["runtime"]["vllm"] == "0.11.1"
    assert record["model"]["revision"] == "b" * 40
    assert record["model"]["thinking_enabled"] is False
    assert len(record["experiment"]["spec_sha256"]) == 64
    assert len(record["experiment"]["prompt_hash"]) == 64
    assert "credential-value" not in serialized

    spec = GrailQAPreflightSpec.load(SPEC_PATH)
    bundle = ModelBundle.load(MODEL_ROOT)
    manifest = build_preflight_run_manifest(
        output=tmp_path / "result",
        spec=spec,
        catalog_hash="catalog-hash",
        model=bundle,
        effective_model="Qwen/Qwen3-32B",
        question_count=18,
        execution_environment=record,
    )
    assert manifest["execution_environment"]["gpu"]["model"] == "NVIDIA H100 NVL"
    assert manifest["model_bundle_hash"] == bundle.bundle_hash
    assert manifest["prompt_hash"] == bundle.prompt.prompt_hash
    assert "credential-value" not in json.dumps(manifest)


def test_cwru_preflight_preserves_frozen_questions_and_forbids_full_run() -> None:
    local = GrailQAPreflightSpec.load(SPEC_PATH)
    remote = GrailQAPreflightSpec.load(
        ROOT / "experiments/specs/grailqa_semantic_preflight_v2.json"
    )
    contract = CWRUVLLMContract.load(CONTRACT_PATH)
    assert local.question_ids == remote.question_ids
    assert len(local.question_ids) == 18
    assert local.data["full_150_run_permitted"] is False
    assert local.data["model"] == contract.model == "Qwen/Qwen3-32B"
    assert local.data["deployment_contract_hash"] == contract.contract_hash


def test_cwru_request_budget_exactly_fits_served_context(tmp_path: Path) -> None:
    result = verify_preflight_token_budget(
        repo_root=ROOT,
        spec_path=SPEC_PATH,
        contract_path=CONTRACT_PATH,
    )
    assert result == {
        "schema_version": "m13e3b5-cwru-token-budget-v1",
        "status": "pass",
        "input_tokens": 8192,
        "output_tokens": 4096,
        "required_tokens": 12288,
        "context_tokens": 12288,
    }

    contract_data = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract_data["serving"]["max_model_len"] = 8192
    contract_data["contract_hash"] = content_hash(
        {key: value for key, value in contract_data.items() if key != "contract_hash"}
    )
    bad_contract = tmp_path / "bad-contract.json"
    bad_contract.write_text(json.dumps(contract_data), encoding="utf-8")
    spec_data = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    spec_data["deployment_contract_hash"] = contract_data["contract_hash"]
    spec_data["freeze_hash"] = content_hash(
        {key: value for key, value in spec_data.items() if key != "freeze_hash"}
    )
    bad_spec = tmp_path / "bad-spec.json"
    bad_spec.write_text(json.dumps(spec_data), encoding="utf-8")

    with pytest.raises(ValueError, match="exceeds the served context window"):
        verify_preflight_token_budget(
            repo_root=ROOT,
            spec_path=bad_spec,
            contract_path=bad_contract,
        )


def test_cwru_scripts_are_scheduler_selected_syntax_valid_and_cleanup_bounded() -> None:
    scripts = [
        ROOT / "scripts/cwru/common.sh",
        ROOT / "scripts/cwru/launch_vllm_qwen3_32b.sh",
        ROOT / "scripts/cwru/check_vllm_ready.sh",
        ROOT / "scripts/cwru/smoke_vllm_structured_output.sh",
        ROOT / "scripts/slurm/cwru_xgap_vllm.sbatch",
        ROOT / "scripts/slurm/run_grailqa_semantic_preflight_v2.sbatch",
        ROOT / "scripts/server/check_cwru_grailqa_preflight_ready.sh",
    ]
    for script in scripts:
        result = subprocess.run(
            ("bash", "-n", str(script)),
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    slurm = (ROOT / "scripts/slurm/cwru_xgap_vllm.sbatch").read_text()
    combined = "\n".join(script.read_text() for script in scripts)
    assert "#SBATCH --partition=gpu" in slurm
    assert "#SBATCH -C gpu2h100" in slurm
    assert "#SBATCH --gres=gpu:1" in slurm
    assert "#SBATCH --cpus-per-task=8" in slurm
    assert "#SBATCH --mem=64G" in slurm
    assert "trap cleanup EXIT" in slurm
    assert "kill -9" in slurm
    assert "127.0.0.1" in combined
    assert "gput072" not in combined
    assert "gput073" not in combined
    assert "docker" not in combined.lower()
    assert "sudo" not in combined.lower()
    contract = CWRUVLLMContract.load(CONTRACT_PATH)
    assert (
        f"--max-model-len {contract.data['serving']['max_model_len']}"
        in (ROOT / "scripts/cwru/launch_vllm_qwen3_32b.sh").read_text()
    )
    preflight = (
        ROOT / "scripts/slurm/run_grailqa_semantic_preflight_v2.sbatch"
    ).read_text()
    assert "query_local_e3b4" in preflight
    assert "audit_summary.json" in preflight
    assert "reachability.jsonl" in preflight


def test_finalize_run_hashes_artifacts_and_records_failure(tmp_path: Path) -> None:
    (tmp_path / "results").mkdir()
    (tmp_path / "results/value.json").write_text('{"ok":true}\n', encoding="utf-8")
    status = finalize_run(tmp_path, 17)
    inventory = json.loads((tmp_path / "artifact_inventory.json").read_text())
    assert status["status"] == "failed"
    assert status["exit_code"] == 17
    assert inventory["files"][0]["path"] == "results/value.json"
    assert len(inventory["files"][0]["sha256"]) == 64
