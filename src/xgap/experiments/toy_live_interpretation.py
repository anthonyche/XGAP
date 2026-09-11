"""Pinned Qwen configuration for tiny connectivity, never a dataset campaign."""

import os
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from xgap.experiments.hashing import content_hash
from xgap.llm.interpretation import INTERPRETATION_SCHEMA, OpenAICompatibleInterpretationProvider
from xgap.llm.openai_compatible import OpenAICompatibleProviderConfig
from xgap.llm.token_budget import LocalPinnedChatTokenizer, ChatTokenBudgetGuard
from xgap.catalog.bundle import FrozenResolutionBundle
from xgap.experiments.toy_backbone import load_fixture
from xgap.experiments.toy_binding import BUNDLE_FIXTURE, interpretation_inputs, load_binding_cases
from xgap.semantic.interpretation import interpret_question
from xgap.semantic.interpretation_replay import RecordingInterpretationProvider


MODEL = "Qwen/Qwen3-32B"
REVISION = "9216db5781bf21249d130ec9da846c4624c16137"
PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts/interpretation/semantic_program_v2.txt"


def qwen_toy_config():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    config = OpenAICompatibleProviderConfig(provider_id="qwen3-32b-toy-interpretation-v2",
        base_url=os.environ.get("XGAP_LLM_BASE_URL", "http://127.0.0.1:8000/v1"),
        api_key_env="XGAP_LLM_API_KEY", model=MODEL, temperature=0, top_p=1,
        max_tokens=4096, candidate_cap=1, timeout_seconds=120,
        structured_output_mode="json_schema", structured_schema=INTERPRETATION_SCHEMA,
        prompt_hash=content_hash(prompt), max_repair_calls=0,
        extra_parameters={"chat_template_kwargs": {"enable_thinking": False}})
    return config, prompt


def load_qwen_toy_provider(tokenizer_snapshot):
    config, prompt = qwen_toy_config()
    counter = LocalPinnedChatTokenizer(snapshot_path=Path(tokenizer_snapshot), revision=REVISION)
    guard = ChatTokenBudgetGuard(counter, input_limit=8192, output_limit=4096,
                                 context_limit=12288, expected_model=MODEL)
    return OpenAICompatibleInterpretationProvider(config, prompt, guard)


def toy_model_requests():
    """The same tiny requests and version context used by native run_question."""
    pin = json.loads((BUNDLE_FIXTURE / "reference.json").read_text())
    bundle = FrozenResolutionBundle.load(BUNDLE_FIXTURE / pin["root"], expected_bundle_hash=pin["bundle_hash"])
    graph, _, _ = load_fixture()
    version = hashlib.sha256(json.dumps(graph, sort_keys=True).encode()).hexdigest()
    context = {"resolution_bundle": bundle.identity,
               "sources": {"toy": {"version": version, "replicas": ["neo4j", "fuseki"]}}}
    result = []
    for case in load_binding_cases():
        request, _ = interpretation_inputs(case)
        result.append((case["id"], replace(request, context={**request.context, "runtime": context})))
    return result


def run_toy_model_requests(provider, output):
    """Record up to five distinct questions; never retry a failed model action."""
    requests = toy_model_requests()
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": "xgap-toy-live-interpretation-v1", "paper_result": False,
              "scope": "five tiny Interpretation connectivity requests; no backend execution",
              "provider_id": provider.provider_id, "automatic_retries": 0,
              "queries": [{"query_id": qid, "status": "not_attempted"} for qid, _ in requests]}

    def save():
        (root / "result.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")

    save()
    for index, (qid, request) in enumerate(requests):
        journal = RecordingInterpretationProvider(provider)
        result = interpret_question(request, journal)
        journal.save(root / (qid + ".json"))
        report["queries"][index].update(status=result["status"], interpretation=result)
        save()
        if result.get("failure_category") in {
            "preflight_error", "token_budget", "missing_api_key", "timeout", "provider_error"}:
            for remaining in report["queries"][index + 1:]:
                remaining["status"] = "not_attempted_after_provider_failure"
            break
    report.update(external_calls=sum(q.get("interpretation", {}).get("external_calls", 0)
                                     for q in report["queries"]),
                  success=all(q["status"] == "interpreted" for q in report["queries"]))
    save()
    return report
