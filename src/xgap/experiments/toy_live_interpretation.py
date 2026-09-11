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


def toy_model_requests(*, request_profile="legacy-v2"):
    """The same tiny requests and version context used by native run_question."""
    pin = json.loads((BUNDLE_FIXTURE / "reference.json").read_text())
    bundle = FrozenResolutionBundle.load(BUNDLE_FIXTURE / pin["root"], expected_bundle_hash=pin["bundle_hash"])
    graph, _, _ = load_fixture()
    version = hashlib.sha256(json.dumps(graph, sort_keys=True).encode()).hexdigest()
    context = {"resolution_bundle": bundle.identity,
               "sources": {"toy": {"version": version, "replicas": ["neo4j", "fuseki"]}}}
    result = []
    from xgap.experiments.toy_output_contract import apply_request_profile
    for case in load_binding_cases():
        request, _ = interpretation_inputs(case)
        request = replace(request, context={**request.context, "runtime": context})
        result.append((case["id"], apply_request_profile(request, request_profile)))
    return result


def run_toy_model_requests(provider, output, *, max_requests=5, start_index=0, run_metadata=None,
                           request_profile="legacy-v2"):
    """Record up to five distinct questions; never retry a failed model action."""
    if (type(max_requests) is not int or type(start_index) is not int
            or not 1 <= max_requests <= 5 or not 0 <= start_index < 5
            or start_index + max_requests > 5):
        raise ValueError("Toy execution requires a contiguous window within five requests")
    stop_index = start_index + max_requests
    requests = toy_model_requests(request_profile=request_profile)
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": "xgap-toy-live-interpretation-v1", "paper_result": False,
              "scope": "five tiny Interpretation connectivity requests; no backend execution",
              "provider_id": provider.provider_id, "automatic_retries": 0,
              "max_requests": max_requests, "start_index": start_index,
              "request_profile": request_profile,
              "queries": [{"query_id": qid, "status": "not_attempted"} for qid, _ in requests]}
    if run_metadata is not None:
        report["run_metadata"] = run_metadata
    for query in report["queries"][:start_index] + report["queries"][stop_index:]:
        query["status"] = "not_attempted_after_request_budget"

    def save():
        (root / "result.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")

    save()
    for index, (qid, request) in enumerate(requests[start_index:stop_index], start=start_index):
        item = report["queries"][index]
        item.update(status="started", observed_usage={"external_calls": None,
            "token_usage_known": False, "input_tokens": None, "output_tokens": None})
        save()  # An interrupted provider entry is unknown, never "not_attempted".
        journal = RecordingInterpretationProvider(provider)
        result = interpret_question(request, journal)
        item.update(status=result["status"], interpretation=result)
        usage_known = result.get("usage_unavailable") is not True
        item["observed_usage"] = {
            "external_calls": result["external_calls"], "token_usage_known": usage_known,
            "input_tokens": result["input_tokens"] if usage_known else None,
            "output_tokens": result["output_tokens"] if usage_known else None,
        }
        save()  # Preserve the received outcome even if the replay export fails.
        recording_path = root / (qid + ".json")
        try:
            journal.save(recording_path)
            recording_bytes = recording_path.stat().st_size
            item["recording"] = {"file": recording_path.name, "bytes": recording_bytes,
                                 "replay_size_admitted": recording_bytes <= 4_194_304}
        except (OSError, ValueError, TypeError) as error:
            item.update(status="recording_failed", recording={"file": recording_path.name,
                "replay_size_admitted": False, "error_type": type(error).__name__,
                "error": "Cannot export the received Interpretation recording"})
            for remaining in report["queries"][index + 1:stop_index]:
                remaining["status"] = "not_attempted_after_recording_failure"
            save()
            break
        save()
        if result.get("failure_category") in {
            "preflight_error", "token_budget", "missing_api_key", "timeout", "provider_error"}:
            for remaining in report["queries"][index + 1:stop_index]:
                remaining["status"] = "not_attempted_after_provider_failure"
            break
    report.update(external_calls=sum(q.get("interpretation", {}).get("external_calls", 0)
                                     for q in report["queries"]),
                  success=all(q["status"] == "interpreted" for q in report["queries"]))
    attempted = [q["observed_usage"] for q in report["queries"] if "observed_usage" in q]
    report["attempted_usage"] = {
        "scope": "attempted questions only; unattempted questions have no measured usage",
        "known_count": sum(u["token_usage_known"] for u in attempted),
        "unknown_count": sum(not u["token_usage_known"] for u in attempted),
        **{name: sum(u[name] for u in attempted) if all(u["token_usage_known"] for u in attempted) else None
           for name in ("input_tokens", "output_tokens")},
    }
    report["requested_window_success"] = all(q["status"] == "interpreted" for q in report["queries"][start_index:stop_index])
    report["requested_window_replay_size_admitted"] = all(
        q.get("recording", {}).get("replay_size_admitted") is True for q in report["queries"][start_index:stop_index])
    save()
    return report
