"""Only the new preflight/recording seam; controlled transport, no backend run."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from xgap.experiments.hashing import content_hash
from xgap.experiments.one_shot_toy import (
    load_one_shot_toy_provider, one_shot_toy_inputs, one_shot_toy_preflight,
    one_shot_toy_prompt, replay_one_shot_interpretation, run_one_shot_toy,
)
from xgap.planning.runtime_estimator import (
    FrozenSourceStatistics, RuntimeTrainingSample, SourceStatistics, fit_runtime_estimator,
)
from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNode, RuntimeNodeKind
from xgap.semantic.interpretation_candidates import SCHEMA


class NoExternal:
    def post_json(self, **kwargs):
        pytest.fail("Preflight must not reach a model or backend")


def frozen_model(tmp_path, *, snapshot=None):
    _, inputs = one_shot_toy_inputs()
    snapshot = snapshot or inputs["sources"]["toy"].snapshot_version
    stats = FrozenSourceStatistics("tiny-harness-test", "v1", tuple(
        SourceStatistics(backend, "toy", snapshot, 20, 80, "fixture:analytic-statistics")
        for backend in ("neo4j", "fuseki")))
    samples = []
    for index, backend in enumerate(("neo4j", "fuseki")):
        qid = "independent-harness-training-" + str(index)
        node = RuntimeNode("source", RuntimeNodeKind.REMOTE_QUERY, parameters={"backend_id": backend})
        plan = FederatedExecutionPlan(qid, (node,), ("source",),
            metadata={"query_id": qid, "source_snapshot_versions": {backend: snapshot}})
        samples.append(RuntimeTrainingSample(qid, qid, plan, 10 + index,
            hashlib.sha256(qid.encode()).hexdigest()))
    fitted = fit_runtime_estimator(samples, statistics=stats, training_id="independent-harness",
        model_version="toy-harness-test", training_kind="toy_correctness", excluded_query_ids=("B01", "B04"),
        collection_ref="fixture:analytic-labels", collection_elapsed_ms=None, collection_remote_calls=None)
    path = tmp_path / "model.json"
    fitted.save(path)
    return path


def test_both_factory_modes_have_matching_schema_prompt_and_explicit_byte_output_budgets():
    for mode, cap, output in (("precision", 3, 6144), ("performance", 1, 4096)):
        provider = load_one_shot_toy_provider(mode=mode)
        request, inputs = one_shot_toy_inputs(mode=mode)
        assert provider.config.candidate_cap == inputs["policy"].candidate_cap == cap
        assert provider.config.max_tokens == output
        assert provider.config.prompt_hash == content_hash(one_shot_toy_prompt())
        payload = provider.build_request_payload(request)
        check = provider.token_guard.check(payload, call_kind="generation")
        assert check["passed"] and check["requested_output_tokens"] == output
        assert not check["exact_input_tokens_verified"] and check["input_tokens"] is None
        assert payload["response_format"]["json_schema"]["schema"]["properties"]["candidates"]["maxItems"] == cap
    with pytest.raises(ValueError):
        load_one_shot_toy_provider(output_tokens=6145)


def test_default_preflight_is_zero_call_readonly_frozen_input_and_exclusive_output(tmp_path, monkeypatch):
    model = frozen_model(tmp_path)
    before = model.read_bytes()
    provider = load_one_shot_toy_provider()
    provider.transport = NoExternal()
    import xgap.planning.runtime_estimator as training
    monkeypatch.setattr(training, "fit_runtime_estimator", lambda *a, **k: pytest.fail("online fit"))
    root = tmp_path / "preflight"
    result = run_one_shot_toy(estimator_path=model, output=root, provider=provider)
    assert result["success"] and result["operation"] == "preflight"
    assert result["external_calls"] == result["backend_calls"] == 0
    assert model.read_bytes() == before
    assert {path.name for path in root.iterdir()} == {"preflight.json", "receipt.json"}
    preflight = json.loads((root / "preflight.json").read_text())
    assert preflight["source_snapshot_version"] == json.loads(before)["statistics"]["entries"][0]["snapshot_version"]
    assert not preflight["gold_used_for_inference"] and not preflight["live_endpoint_verified"]
    with pytest.raises(FileExistsError):
        run_one_shot_toy(estimator_path=model, output=root, provider=provider)


def test_one_invalid_live_style_response_is_durable_before_gold_and_replays_without_calls(tmp_path, monkeypatch):
    model = frozen_model(tmp_path)
    provider = load_one_shot_toy_provider()
    calls = []

    class ControlledWire:
        def post_json(self, **kwargs):
            calls.append(kwargs)
            raw = {"schema_version": SCHEMA, "candidates": [{"candidate_id": "bad",
                "quality_proxy": None, "program": {}, "operator_sources": {}}]}
            return {"model": provider.config.model,
                "usage": {"prompt_tokens": 101, "completion_tokens": 17, "total_tokens": 118},
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(raw)}}]}

    provider.transport = ControlledWire()
    monkeypatch.setenv(provider.config.api_key_env, "controlled-one-shot-harness-secret")
    root = tmp_path / "single-response"
    read_text = Path.read_text

    def gold_after_seal(path, *args, **kwargs):
        if path.name == "cases.json" and path.parent.name == "backbone_binding_v1":
            assert (root / "result.json").is_file(), "Gold opened before ordinary result was sealed"
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", gold_after_seal)
    receipt = run_one_shot_toy(estimator_path=model, output=root, provider=provider,
        execute=True, backend_clients={"neo4j": NoExternal(), "fuseki": NoExternal()}, evaluate=True)
    assert not receipt["success"] and receipt["status"] == "no_admissible_interpretation"
    assert receipt["external_calls"] == len(calls) == 1 and receipt["backend_calls"] == 0
    assert receipt["execution_success"] is None and receipt["answer_exact"] is False
    assert receipt["input_tokens"] == 101 and receipt["output_tokens"] == 17
    outcome = json.loads((root / "result.json").read_text())
    assert outcome["final_plan_executions"] == 0
    evaluation = json.loads((root / "evaluation.json").read_text())
    assert evaluation["inference_result_sealed_sha256"] == hashlib.sha256((root / "result.json").read_bytes()).hexdigest()
    assert not evaluation["answer_exact"]
    replayed = replay_one_shot_interpretation(root / "interpretation.json", output=tmp_path / "replay")
    assert replayed["success"] and replayed["replayed_status"] == receipt["status"]
    assert replayed["external_calls"] == replayed["backend_calls"] == 0 and len(calls) == 1
    assert all("controlled-one-shot-harness-secret" not in path.read_text() for path in root.glob("*.json"))


def test_wrong_graph_estimator_or_missing_prepared_clients_dispatches_nothing(tmp_path):
    wrong = frozen_model(tmp_path, snapshot="wrong-graph")
    provider = load_one_shot_toy_provider()
    provider.transport = NoExternal()
    failed = run_one_shot_toy(estimator_path=wrong, output=tmp_path / "wrong", provider=provider, execute=True)
    assert not failed["success"] and failed["external_calls"] == failed["backend_calls"] == 0
    assert "exact original tiny graph" in failed["error"]
    another = tmp_path / "another"
    another.mkdir()
    correct = frozen_model(another)
    missing = run_one_shot_toy(estimator_path=correct, output=tmp_path / "missing", provider=provider, execute=True)
    assert missing["status"] == "prepared_backend_clients_required" and missing["external_calls"] == 0


def test_failed_recording_after_unknown_provider_usage_preserves_unknown_calls(tmp_path, monkeypatch):
    import xgap.experiments.one_shot_toy as harness
    model = frozen_model(tmp_path)
    provider = load_one_shot_toy_provider()
    entered = []

    def unavailable_usage(request):
        entered.append(request)
        raise RuntimeError("Provider failed without a usable usage receipt")

    write_once = harness._write_once

    def failed_recording(path, record):
        if path.name == "interpretation.json":
            raise OSError("Controlled recording storage failure")
        return write_once(path, record)

    monkeypatch.setattr(provider, "interpret", unavailable_usage)
    monkeypatch.setattr(harness, "_write_once", failed_recording)
    root = tmp_path / "unknown-calls"
    receipt = run_one_shot_toy(estimator_path=model, output=root, provider=provider,
        execute=True, backend_clients={"neo4j": NoExternal(), "fuseki": NoExternal()})
    result = json.loads((root / "result.json").read_text())
    assert receipt["status"] == "provider_failure" and len(entered) == 1
    assert receipt["external_calls"] is None and receipt["backend_calls"] == 0
    assert result["interpretation"]["failure_category"] == "recording_failed"
    assert result["interpretation"]["external_call_count_complete"] is False
    assert result["interpretation_usage_known_lower_bounds"]["external_calls"] == 0
    assert receipt["input_tokens"] is None and receipt["output_tokens"] is None
    assert result["automatic_retries"] == 0
