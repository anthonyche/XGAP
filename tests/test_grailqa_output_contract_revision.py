from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.cwru_vllm import verify_preflight_token_budget
from xgap.experiments.grailqa_preflight import GrailQAPreflightSpec
from xgap.experiments.hashing import content_hash
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.experiments.live_run import build_openai_compatible_provider
from xgap.llm.schemas import PlannerRequest


ROOT = Path(__file__).resolve().parents[1]
OLD_MODEL = Path("models/qwen3_32b_vllm_cwru_m13e2")
NEW_MODEL = Path("models/qwen3_32b_vllm_cwru_grailqa_contract_v1")
OLD_SPEC = Path("experiments/specs/grailqa_semantic_preflight_v2_cwru_qwen3_32b.json")
NEW_SPEC = Path("experiments/specs/grailqa_semantic_preflight_output_contract_v1_cwru_qwen3_32b.json")
REVIEW = Path("experiments/artifacts/grailqa_output_contract_revision_draft_v1.json")


def _read(path: Path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_bundle_changes_only_prompt_and_versioned_identity() -> None:
    old = _read(OLD_MODEL / "model_config.json")
    new = _read(NEW_MODEL / "model_config.json")
    assert new["model_id"] == "qwen3_32b_vllm_cwru_grailqa_contract_v1"
    assert new["version"] == "m13e4-output-contract-draft-v1"
    assert new["prompt_hash"] != old["prompt_hash"]
    reconciled = copy.deepcopy(new)
    for key in ("model_id", "version", "prompt_hash"):
        reconciled[key] = old[key]
    assert reconciled == old
    assert (ROOT / NEW_MODEL / "structured_schema.json").read_bytes() == (
        ROOT / OLD_MODEL / "structured_schema.json"
    ).read_bytes()
    old_bundle = ModelBundle.load(ROOT / OLD_MODEL)
    new_bundle = ModelBundle.load(ROOT / NEW_MODEL)
    assert old_bundle.bundle_hash == "ed9fa4db9f0981e7307ef7323415159fdeb5117c8ab308218d1c8d282360bd6e"
    assert old_bundle.bundle_hash != new_bundle.bundle_hash
    assert new_bundle.config.token_limits == {"input": 8192, "output": 4096}
    assert new_bundle.config.max_repair_calls == 1


def test_prompt_preserves_original_instructions_and_adds_no_task_examples() -> None:
    old = _read(OLD_MODEL / "prompt.json")
    new = _read(NEW_MODEL / "prompt.json")
    assert new["system_prompt"].startswith(old["system_prompt"] + " Response structure contract:")
    assert new["few_shot_examples"] == old["few_shot_examples"] == []
    assert new["change_classification"] == "interface_contract_clarification_draft"
    normalized = copy.deepcopy(new)
    for key in ("system_prompt", "change_classification", "change_note"):
        normalized[key] = old[key]
    assert normalized == old
    addition = new["system_prompt"][len(old["system_prompt"]):]
    for required in (
        "including slots marked required_for_candidate=false",
        "does not prescribe the number of hops",
        "omit unrealized optional hops, not their top-level anchors",
        "need not equal those anchors",
        "never a variable name or a label value",
        "following the actual candidate tree",
        "condition is a property component only when a condition exists",
        "do not authorize new topology",
    ):
        assert required in addition
    # Only syntax is clarified; no benchmark IDs, gold values, or shot records.
    assert not any(qid in addition for qid in _read(OLD_SPEC)["question_ids"])
    assert "boats.ship" not in addition


def test_new_preflight_preserves_every_scientific_field_and_question_order() -> None:
    old = GrailQAPreflightSpec.load(ROOT / OLD_SPEC).data
    new = GrailQAPreflightSpec.load(ROOT / NEW_SPEC).data
    assert new["model_bundle_root"] == NEW_MODEL.as_posix()
    assert new["model_bundle_hash"] == ModelBundle.load(ROOT / NEW_MODEL).bundle_hash
    assert new["experiment_id"] != old["experiment_id"]
    assert new["run_id_prefix"] != old["run_id_prefix"]
    assert new["freeze_hash"] != old["freeze_hash"]
    reconciled = copy.deepcopy(new)
    for key in ("experiment_id", "run_id_prefix", "model_bundle_root", "model_bundle_hash", "freeze_hash"):
        reconciled[key] = old[key]
    assert reconciled == old
    assert new["backend_execution"] is False
    assert new["full_150_run_permitted"] is False


def test_existing_context_reservation_is_unchanged_not_a_tokenizer_measurement() -> None:
    kwargs = {
        "repo_root": ROOT,
        "contract_path": ROOT / "experiments/environments/cwru_pioneer_qwen3_32b_vllm.json",
    }
    old = verify_preflight_token_budget(spec_path=ROOT / OLD_SPEC, **kwargs)
    new = verify_preflight_token_budget(spec_path=ROOT / NEW_SPEC, **kwargs)
    assert new == old
    assert new["required_tokens"] == new["context_tokens"] == 12288
    assert _read(REVIEW)["token_budget"]["actual_new_request_tokenization"] == "not_measured"


def test_actual_provider_payload_diff_is_system_prompt_only(monkeypatch) -> None:
    monkeypatch.delenv("XGAP_LLM_MODEL", raising=False)
    monkeypatch.delenv("XGAP_LLM_BASE_URL", raising=False)
    request = PlannerRequest(
        "Synthetic question for interface testing only",
        max_candidates=3,
        metadata={
            "task_id": "test:output-contract",
            "prompt_schema_view": {
                "ontology": {"id": "test", "version": "v1", "hash": "synthetic"},
                "terms": [{"term_id": "test.relation", "kind": "relation"}],
                "entities": [],
                "query_slots": [{
                    "slot_id": "relation-hop-1",
                    "candidate_anchor_ids": ["test.relation"],
                }],
            },
        },
    )
    # Building a payload neither instantiates a model nor invokes transport.
    old_provider = build_openai_compatible_provider(
        ModelBundle.load(ROOT / OLD_MODEL), response_parser=parse_normalized_planner_response
    )
    new_provider = build_openai_compatible_provider(
        ModelBundle.load(ROOT / NEW_MODEL), response_parser=parse_normalized_planner_response
    )
    old = old_provider.build_request_payload(request)
    new = new_provider.build_request_payload(request)
    assert new["messages"][0]["content"] != old["messages"][0]["content"]
    new["messages"][0]["content"] = old["messages"][0]["content"]
    assert new == old
    assert old_provider.last_invocation is new_provider.last_invocation is None


def test_review_record_binds_exact_sources_but_cannot_grant_authority() -> None:
    review = _read(REVIEW)
    assert review["review_sha256"] == content_hash({
        key: value for key, value in review.items() if key != "review_sha256"
    })
    for field in ("preserved_files", "proposed_files"):
        for item in review[field]:
            if item["path"] in {
                "src/xgap/experiments/grailqa_semantic_pilot.py",
                "src/xgap/experiments/grailqa_preflight.py",
                "src/xgap/llm/openai_compatible.py",
            }:
                # D192 adds opt-in grounding; D197 adds an opt-in wire adapter.
                # This historical prompt-only review still binds its original
                # code, not later implementations; never rewrite its old hashes.
                data = subprocess.check_output([
                    "git", "show", f"{review['base_implementation_commit']}:{item['path']}",
                ], cwd=ROOT)
            else:
                data = (ROOT / item["path"]).read_bytes()
            assert hashlib.sha256(data).hexdigest() == item["sha256"]
    assert review["old_model_bundle_hash"] == ModelBundle.load(ROOT / OLD_MODEL).bundle_hash
    assert review["proposed_model_bundle_hash"] == ModelBundle.load(ROOT / NEW_MODEL).bundle_hash
    assert review["review_status"] == "awaiting_author_review_and_exact_live_scope"
    assert review["claim_boundary"] == {
        "offline_contract_preparation_only": True,
        "original_negative_result_preserved": True,
        "accuracy_improvement_measured": False,
        "author_review_receipt_created": False,
        "new_live_execution_authorized": False,
        "full_150_run_authorized": False,
        "paper_result": False,
    }


@pytest.mark.parametrize("script", [
    "scripts/slurm/run_grailqa_semantic_preflight_v2.sbatch",
    "scripts/slurm/run_grailqa_semantic_paper.sbatch",
])
def test_unreviewed_contract_is_not_activated_by_existing_shell_defaults(script) -> None:
    # The review record also pins bytes, so changing an indirect default fails.
    path = ROOT / script
    assert path.is_file()
    assert NEW_MODEL.as_posix() not in path.read_text()
    assert NEW_SPEC.name not in path.read_text()
