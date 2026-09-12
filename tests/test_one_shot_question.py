"""New ordinary-entry slice; independent tiny gold, no native/LLM services."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from test_semantic_binding_execution import setup
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.question import run_question
from xgap.experiments.toy_binding import BUNDLE_FIXTURE, interpretation_inputs, load_binding_cases
from xgap.planning.runtime_estimator import (FrozenRuntimeEstimator, FrozenSourceStatistics,
    RuntimeTrainingSample, SourceStatistics, fit_runtime_estimator)
from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNode, RuntimeNodeKind as R
from xgap.semantic.interpretation import InterpretationResponse
from xgap.semantic.interpretation_candidates import SCHEMA


CASE = load_binding_cases()[0]
PIN = json.loads((BUNDLE_FIXTURE / "reference.json").read_text())


@pytest.fixture(scope="module")
def estimator():
    # This is independent analytic toy training to exercise the connection;
    # neither the final query's plan nor its expected answer/time is a label.
    stats = FrozenSourceStatistics("tiny-statistics", "v1", tuple(
        SourceStatistics(backend, "toy", "toy-v1", 20, 80, "fixture:toy-statistics")
        for backend in ("rdf_a", "rdf_b")))
    samples = []
    for index, (backend, count, cost) in enumerate((
            ("rdf_a", 1, 8), ("rdf_a", 2, 16), ("rdf_b", 1, 12), ("rdf_b", 2, 24))):
        query_id = f"analytic-training-{index}"
        nodes = tuple(RuntimeNode(f"source-{i}", R.REMOTE_QUERY,
            parameters={"backend_id": backend}) for i in range(count))
        plan = FederatedExecutionPlan(query_id, nodes, tuple(n.node_id for n in nodes),
            metadata={"query_id": query_id, "source_snapshot_versions": {backend: "toy-v1"}})
        samples.append(RuntimeTrainingSample(query_id, query_id, plan, cost,
            hashlib.sha256(query_id.encode()).hexdigest()))
    fitted = fit_runtime_estimator(samples, statistics=stats, training_id="tiny-independent",
        model_version="tiny-ridge", training_kind="toy_correctness", excluded_query_ids=("slice-query",),
        collection_ref="fixture:analytic-labels-only", collection_elapsed_ms=None, collection_remote_calls=None)
    return FrozenRuntimeEstimator.from_dict(fitted.to_dict())


class CandidateProvider:
    provider_id = "controlled-candidate-pool"

    def __init__(self, *, invalid_first=False, unknown_quality=False):
        self.calls = 0
        self.invalid_first = invalid_first
        self.unknown_quality = unknown_quality

    def interpret(self, request):
        self.calls += 1
        _, template = interpretation_inputs(CASE)
        single = template.interpret(request).payload
        cap = request.context["one_shot_profile"]["candidate_cap"]
        pool = [{"candidate_id": "first", "quality_proxy": None if self.unknown_quality else 0.4,
                 "program": deepcopy(single["program"]), "operator_sources": single["operator_sources"]}]
        if cap > 1:
            pool.append({"candidate_id": "second", "quality_proxy": 0.9,
                         "program": deepcopy(single["program"]), "operator_sources": single["operator_sources"]})
        if self.invalid_first:
            pool[0]["program"]["operators"][0]["kind"] = "unsupported"
        return InterpretationResponse({"schema_version": SCHEMA, "candidates": pool},
            external_calls=1, input_tokens=11, output_tokens=17,
            provenance={"kind": "controlled-no-external-service", "usage_reported": True})


def run(estimator, *, mode="precision", provider=None, fail=False, **overrides):
    request, _ = interpretation_inputs(CASE)
    request = replace(request, context={**request.context, "query_id": "slice-query"})
    tool, calls = setup(CASE, fail=fail)
    arguments = dict(mode=mode, estimator=estimator,
        catalog_root=BUNDLE_FIXTURE / PIN["root"], catalog_hash=PIN["bundle_hash"],
        sources=tool.sources, backends=tool.backends, backend_clients=tool.backend_clients)
    arguments.update(overrides)
    provider = provider or CandidateProvider()
    return run_question(request, provider, **arguments), calls, provider


@pytest.mark.parametrize("mode,winner,admitted", [("precision", "second", 2), ("performance", "first", 1)])
def test_ordinary_entry_selects_from_estimates_and_executes_once(estimator, mode, winner, admitted, monkeypatch):
    import xgap.planning.runtime_estimator as training
    import xgap.runtime.observations as observations
    monkeypatch.setattr(training, "fit_runtime_estimator", lambda *a, **k: pytest.fail("online training"))
    monkeypatch.setattr(observations.PlanObservationCollector, "collect", lambda *a, **k: pytest.fail("online probing"))
    result, calls, provider = run(estimator, mode=mode)
    assert result["success"], result
    assert result["answer_rows"] == CASE["expected_rows"]
    assert result["selection"]["candidate_id"] == winner
    assert result["interpretation"]["admitted_count"] == admitted
    assert provider.calls == result["interpretation_external_calls"] == 1
    assert (result["input_tokens"], result["output_tokens"]) == (11, 17)
    assert len(calls) == result["backend_remote_calls"] == CASE["expected_remote_calls"]
    assert result["final_plan_executions"] == 1 and result["observation_calls"] == 0
    assert result["selection"]["selection_uses_execution_observations"] is False
    assert result["answer_quality_verified"] is False  # Gold is used by this test only.
    assert result["policy"]["use_ontology"] is (mode == "precision")
    assert result["end_to_end_ms"] >= result["grounding_ms"] + result["planning_ms"] + result["execution_ms"]
    assert result["estimator"]["training_provenance"]["offline_cost"]["collection_elapsed_ms"] is None
    json.dumps(result, allow_nan=False)


def test_invalid_interpretation_sibling_kept_without_discarding_valid_answer(estimator):
    result, calls, provider = run(estimator, provider=CandidateProvider(invalid_first=True))
    assert result["success"] and result["selection"]["candidate_id"] == "second"
    assert result["interpretation"]["candidates"][0]["status"] == "invalid"
    assert provider.calls == 1 and len(calls) == CASE["expected_remote_calls"]


def test_backend_failure_is_terminal_without_candidate_fallback(estimator):
    result, calls, provider = run(estimator, fail=True)
    assert not result["success"] and result["status"] == "execution_failed"
    assert result["answer_rows"] is None and result["final_plan_executions"] == 1
    assert provider.calls == 1 and result["automatic_retries"] == 0
    assert len(calls) == result["backend_remote_calls"] <= CASE["expected_remote_calls"]


def test_unknown_quality_remains_unknown_with_declared_ranking_fallback(estimator):
    result, _, _ = run(estimator, mode="performance", provider=CandidateProvider(unknown_quality=True))
    assert result["success"]
    assert result["selection"]["quality_proxy"] is None
    assert result["selection"]["quality_fallback_used"] is True
    assert result["selection"]["ranking_quality_proxy"] == 0.5


def test_bad_catalog_stops_before_interpretation(estimator, tmp_path):
    result, calls, provider = run(estimator, catalog_root=tmp_path)
    assert result["status"] == "catalog_unavailable" and not calls and provider.calls == 0


def test_changed_snapshot_never_uses_stale_estimator_or_executes(estimator):
    from xgap.runtime.semantic_planning import LogicalSource
    result, calls, _ = run(estimator, sources={"toy": LogicalSource("toy", "new-snapshot", ("rdf_a", "rdf_b"))})
    assert result["status"] == "no_executable_interpretation" and not calls
    assert result["final_plan_executions"] == 0
    assert all(plan["status"] == "estimator_source_mismatch"
               for candidate in result["candidates"] for plan in candidate["plans"])


def test_bounded_domain_rejected_before_execution_instead_of_silent_truncation(estimator):
    policy = replace(OneShotPolicy(), max_physical_candidates=1)
    result, calls, _ = run(estimator, one_shot_policy=policy)
    assert result["status"] == "no_executable_interpretation" and not calls
    assert all(candidate["status"] == "planning_failed" for candidate in result["candidates"])
    assert all("candidate-work budget" in candidate["error"] for candidate in result["candidates"])


def test_no_implicit_legacy_probe_or_clarification_options(estimator):
    with pytest.raises(ValueError, match="incompatible"):
        run(estimator, max_observation_calls=10)
    with pytest.raises(ValueError, match="disagree"):
        run(estimator, one_shot_policy=OneShotPolicy.for_mode("performance"))


def test_unknown_provider_usage_is_not_zero_cost(estimator):
    class UnknownUsageProvider:
        provider_id = "unexpected-failure"
        def interpret(self, request):
            raise OSError("controlled unknown failure after dispatch")
    result, calls, _ = run(estimator, provider=UnknownUsageProvider())
    assert result["status"] == "provider_failure" and not calls
    assert result["interpretation_external_calls"] is None
    assert result["input_tokens"] is result["output_tokens"] is None
    assert result["interpretation_usage_known_lower_bounds"]["external_calls"] == 0


def test_wire_candidate_cap_mismatch_fails_before_any_model_charge(estimator):
    from types import SimpleNamespace
    provider = CandidateProvider()
    provider.config = SimpleNamespace(candidate_cap=3)
    result, calls, _ = run(estimator, mode="performance", provider=provider)
    assert result["status"] == "configuration_unavailable"
    assert not calls and provider.calls == result["interpretation_external_calls"] == 0
