"""Synthetic offline request assembly tests; no tokenizer package or service."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import xgap.experiments.grailqa_request_tokens as inventory
from xgap.experiments.bundles import ModelBundle
from xgap.experiments.cwru_vllm import CWRUVLLMContract
from xgap.experiments.hashing import content_hash
from xgap.experiments.runtime_alignment import (
    PromptQuerySlot, PromptSchemaView, RetrievedOntologyTerm, RetrievalLimits,
)
from xgap.llm.openai_compatible import OpenAICompatibleStructuredCandidateProvider


ROOT = Path(__file__).resolve().parents[1]
REVISION = "a" * 40


def _view(question_id: str) -> PromptSchemaView:
    terms = tuple(RetrievedOntologyTerm(
        term_id=term_id, kind=kind, label=term_id, aliases=(),
        retrieval_score=1.0, retrieval_provenance=("synthetic-token-fixture",),
        domain="T" if kind == "relation" else None,
        range="T" if kind == "relation" else None,
    ) for term_id, kind in (("T", "class"), ("r", "relation")))
    return PromptSchemaView(
        task_id=question_id, ontology_id="synthetic", ontology_version="1",
        ontology_hash="synthetic-hash", schema_snapshot_version="1",
        schema_snapshot_hash="synthetic-schema", terms=terms, entities=(),
        query_slots=(PromptQuerySlot("relation-hop-1", "relation", "relation", ("r",), ("fixture",)),),
        backend_hints={}, source_schema_items=("Synthetic source schema",),
        limits=RetrievalLimits(),
    )


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    model = ModelBundle.load(ROOT / "models/qwen3_32b_vllm_cwru_m13e2")
    contract_path = ROOT / "experiments/environments/cwru_pioneer_qwen3_32b_vllm.json"
    contract = CWRUVLLMContract.load(contract_path)
    pilot = tmp_path / "pilot"
    pilot.mkdir()
    question_ids = tuple(f"synthetic-{index}" for index in reversed(range(15)))
    questions = [{"question_id": qid, "text": f"Find synthetic relation for {qid}."} for qid in sorted(question_ids)]
    question_path = pilot / "inference_questions.jsonl"
    question_path.write_text("".join(json.dumps(row) + "\n" for row in questions))
    data = {
        "schema_version": "m13e1-grailqa-semantic-preflight-v2",
        "question_ids": list(question_ids), "pilot_root": str(pilot),
        "catalog_root": str(tmp_path / "catalog"),
        "reachability_root": str(tmp_path / "reachability"),
        "model_bundle_root": str(model.root), "model_bundle_hash": model.bundle_hash,
        "deployment_contract": str(contract_path), "deployment_contract_hash": contract.contract_hash,
        "retrieval_k": 7, "prompt_candidates_per_slot": 2, "candidate_cap": 3,
    }
    data["freeze_hash"] = content_hash(data)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(data))
    state = SimpleNamespace(
        tmp=tmp_path, model=model, spec=spec, spec_data=data, question_ids=question_ids,
        question_path=question_path, payloads=[], retrieval_calls=[], view_calls=[],
        missing_retrieval=set(), token_counts={}, tokenize_failures=set(), readiness_calls=[],
        readiness={"ready": True, "catalog_root": str(tmp_path / "catalog"),
                   "reachability_root": str(tmp_path / "reachability"),
                   "reference_interpretation": "GATE_ONLY_NEVER_INPUT"},
        tokenizer_calls=[], snapshot=tmp_path / "cache" / "snapshots" / REVISION,
    )

    def readiness(spec, repo, *, require_credentials):
        state.readiness_calls.append((spec.question_ids, repo, require_credentials))
        return deepcopy(state.readiness)

    class Catalog:
        def retrieve(self, qid, text, *, top_k):
            state.retrieval_calls.append((qid, text, top_k))
            return SimpleNamespace(
                question_id=qid, types=() if qid in state.missing_retrieval else ("T",),
                relations=("r",), to_dict=lambda: {"question_id": qid, "types": ["T"], "relations": ["r"]},
            )

        def prompt_view(self, retrieval, **kwargs):
            state.view_calls.append(kwargs)
            return _view(retrieval.question_id)

    class Counter:
        def __init__(self, snapshot, revision):
            state.tokenizer_calls.append((snapshot, revision))
            self.identity = {"fixture": True, "snapshot_revision": revision}

        def count_payload_tokens(self, payload):
            state.payloads.append(deepcopy(payload))
            qid = json.loads(payload["messages"][1]["content"])["task_id"]
            if qid in state.tokenize_failures:
                raise ValueError("No fabricated fallback count.")
            return state.token_counts.get(qid, 100)

    def no_generation(*args, **kwargs):
        pytest.fail("Token inventory must never generate or send a request.")

    monkeypatch.setattr(inventory, "preflight_readiness", readiness)
    monkeypatch.setattr(inventory, "GrailQAInferenceCatalogV2", SimpleNamespace(load=lambda _: Catalog()))
    monkeypatch.setattr(inventory, "LocalPinnedChatTokenizer", Counter)
    monkeypatch.setattr(OpenAICompatibleStructuredCandidateProvider, "generate_candidates", no_generation)
    for name in ("XGAP_LLM_API_KEY", "XGAP_LLM_MODEL", "XGAP_LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    return state


def _run(state):
    return inventory.inventory_request_tokens(
        spec_path=state.spec, repo_root=state.tmp,
        tokenizer_snapshot=state.snapshot, tokenizer_revision=REVISION,
    )


def _argv(state, output: Path) -> list[str]:
    return ["--spec", str(state.spec), "--repo-root", str(state.tmp),
            "--tokenizer-snapshot", str(state.snapshot), "--tokenizer-revision", REVISION,
            "--output", str(output)]


def test_exact_existing_payload_in_frozen_order_without_credentials(setup):
    result = _run(setup)
    assert result["success"] is result["complete"] is True
    assert result["counted_request_count"] == result["passed_request_count"] == 15
    assert [row["question_id"] for row in result["requests"]] == list(setup.question_ids)
    assert [call[0] for call in setup.retrieval_calls] == list(setup.question_ids)
    assert {call[2] for call in setup.retrieval_calls} == {7}
    assert setup.view_calls == [{"candidates_per_slot": 2, "max_entities": 2}] * 15
    assert setup.readiness_calls == [(setup.question_ids, setup.tmp, False)]
    assert setup.tokenizer_calls == [(setup.snapshot, REVISION)]
    for qid, payload, receipt in zip(setup.question_ids, setup.payloads, result["requests"]):
        assert payload["messages"][0]["content"] == setup.model.prompt.system_prompt
        user = json.loads(payload["messages"][1]["content"])
        assert user["task_id"] == qid
        assert user["max_candidates"] == 3
        assert user["structured_output_schema"] == setup.model.structured_schema
        assert user["prompt_schema_view"] == _view(qid).to_dict()
        assert user["grounding_contracts"]
        assert user["schema_hints"] == ["Synthetic source schema"]
        assert payload["response_format"]["type"] == "json_schema"
        assert payload["chat_template_kwargs"] == {"enable_thinking": False}
        assert payload["max_tokens"] == setup.model.config.token_limits["output"]
        assert receipt["payload_sha256"] == content_hash(payload)
        assert "GATE_ONLY_NEVER_INPUT" not in json.dumps(payload)
    assert set(result["external_call_counts"].values()) == {0}
    boundary = result["claim_boundary"]
    assert boundary["run_authorized"] is boundary["paper_result"] is False
    assert boundary["repair_payloads_counted"] is False
    assert boundary["per_send_repair_guard_required"] is True
    assert boundary["remote_serving_parity_verified"] is False
    assert result["inventory_sha256"] == content_hash({k: v for k, v in result.items() if k != "inventory_sha256"})


def test_missing_retrieval_is_a_row_not_an_omission(setup):
    missing = setup.question_ids[3]
    setup.missing_retrieval.add(missing)
    result = _run(setup)
    assert len(result["requests"]) == 15
    assert result["counted_request_count"] == 14
    assert result["unavailable_request_count"] == 1
    assert result["requests"][3]["reason"] == "retrieval_unavailable"
    assert result["requests"][3]["input_tokens"] is None
    assert result["success"] is result["complete"] is False


def test_missing_question_is_explicit_and_other_requests_still_counted(setup):
    rows = [json.loads(line) for line in setup.question_path.read_text().splitlines()]
    missing = setup.question_ids[0]
    setup.question_path.write_text("".join(json.dumps(row) + "\n" for row in rows if row["question_id"] != missing))
    result = _run(setup)
    assert result["requests"][0]["reason"] == "question_unavailable"
    assert result["counted_request_count"] == 14
    assert len(result["requests"]) == 15


def test_tokenizer_unavailable_has_no_estimates_and_retains_payload_hashes(setup, monkeypatch):
    def unavailable(*args):
        raise ImportError("No local tokenizer installed.")
    monkeypatch.setattr(inventory, "LocalPinnedChatTokenizer", unavailable)
    result = _run(setup)
    assert result["status"] == "incomplete"
    assert result["counted_request_count"] == 0
    assert result["unavailable_request_count"] == 15
    assert all(row["input_tokens"] is None and row["payload_sha256"] for row in result["requests"])
    assert result["maximum_input_tokens"] is None
    assert setup.payloads == []


def test_one_unavailable_tokenization_does_not_omit_other_counts(setup):
    setup.tokenize_failures.add(setup.question_ids[4])
    result = _run(setup)
    assert result["requests"][4]["reason"] == "tokenization_unavailable"
    assert result["counted_request_count"] == 14
    assert len(setup.payloads) == len(result["requests"]) == 15


def test_over_budget_is_complete_failed_inventory(setup):
    setup.token_counts[setup.question_ids[-1]] = setup.model.config.token_limits["input"] + 1
    result = _run(setup)
    assert result["complete"] is True
    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["requests"][-1]["reason"] == "input_budget_exceeded"
    assert result["counted_request_count"] == 15


def test_model_environment_override_fails_without_send(setup, monkeypatch):
    monkeypatch.setenv("XGAP_LLM_MODEL", "not-the-pinned-model")
    result = _run(setup)
    assert result["success"] is False
    assert {row["reason"] for row in result["requests"]} == {"model_mismatch"}
    assert setup.payloads == []


def test_gate_metadata_failure_is_not_hidden_by_token_fit(setup):
    setup.readiness["ready"] = False
    result = _run(setup)
    assert result["success"] is True  # Only token fit, not experimental admission.
    assert result["scope"] == "generation_request_token_fit_only"
    assert result["readiness"]["ready"] is False
    assert result["claim_boundary"]["run_authorized"] is False


def test_duplicate_question_artifact_fails_closed(setup):
    with setup.question_path.open("a") as handle:
        handle.write(setup.question_path.read_text().splitlines()[0] + "\n")
    result = _run(setup)
    assert result["errors"][0]["reason"] == "inputs_unavailable"
    assert result["unavailable_request_count"] == 15
    assert setup.tokenizer_calls == setup.payloads == []


def test_inference_leakage_is_rejected_before_payload_counting(setup):
    rows = [json.loads(line) for line in setup.question_path.read_text().splitlines()]
    next(row for row in rows if row["question_id"] == setup.question_ids[2])["gold_answer"] = "not-input"
    setup.question_path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    result = _run(setup)
    assert result["requests"][2]["reason"] == "request_build_unavailable"
    assert result["counted_request_count"] == 14
    assert "not-input" not in json.dumps(setup.payloads)


def test_cli_exclusive_json_safe_output_and_failed_exit(setup, capsys):
    output = setup.tmp / "runs" / "token-inventory.json"
    setup.missing_retrieval.add(setup.question_ids[0])
    assert inventory.main(_argv(setup, output)) == 1
    report = json.loads(output.read_text())
    assert report["unavailable_request_count"] == 1
    assert json.loads(capsys.readouterr().out)["paper_result"] is False
    before = output.read_bytes()
    with pytest.raises(SystemExit) as error:
        inventory.main(_argv(setup, output))
    assert error.value.code == 2
    assert output.read_bytes() == before


@pytest.mark.parametrize("destination", ["pilot/new.json", "catalog/new.json", "reachability/new.json", "datasets/new.json", "models/new.json"])
def test_cli_cannot_write_inside_protected_artifacts(setup, destination):
    output = setup.tmp / destination
    with pytest.raises(SystemExit) as error:
        inventory.main(_argv(setup, output))
    assert error.value.code == 2
    assert not output.exists()


@pytest.mark.parametrize("option", ["--spec", "--repo-root", "--tokenizer-snapshot", "--tokenizer-revision", "--output"])
def test_cli_requires_all_explicit_inputs(setup, option):
    argv = _argv(setup, setup.tmp / "result.json")
    index = argv.index(option)
    del argv[index:index + 2]
    with pytest.raises(SystemExit) as error:
        inventory.main(argv)
    assert error.value.code == 2


def test_invalid_spec_produces_explicit_incomplete_report(setup):
    setup.spec.write_text("{}")
    result = _run(setup)
    assert result["status"] == "incomplete"
    assert result["question_count"] is None
    assert result["errors"][0]["reason"] == "spec_unavailable"
    assert setup.payloads == setup.tokenizer_calls == []
