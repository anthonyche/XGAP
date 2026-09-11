"""Small provenance and cost checks; synthetic preparation, real tiny RDF serving."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from test_semantic_acquisition import single_source_fixture
from test_semantic_planning import registry
from xgap.runtime.observations import PlanObservationCollection
from xgap.runtime.planning import PlanObservationSnapshot, RemoteEstimate
from xgap.runtime.semantic_forecast import AcquisitionPreparationSample, context_identity, prepare_acquisition_policy
from xgap.runtime.semantic_refresh import SemanticRefreshPolicy
from xgap.runtime.semantic_planning import run_semantic_plans
from xgap.tools.contracts import ToolResult, ToolStatus
from xgap.tools.backends import _artifact_sha256


def setup():
    space, history = single_source_fixture()
    return prepare_fixture(space, history)


def prepare_fixture(space, history, episode="development-preparation"):
    initial, _ = space.select(history)
    request = SemanticRefreshPolicy().choose_request(space, initial.plan, history)
    context = context_identity(space, history, episode)
    catalog = space.observation_catalogs[request.backend_id]
    artifact = catalog.query_artifacts[request.payload["query_id"]]
    samples = []
    for i, elapsed in enumerate((1.0, 1000.0)):
        result = ToolResult("backend.invoke", ToolStatus.SUCCESS, value={
            "operation": "profile", "backend_id": request.backend_id, "catalog_id": catalog.catalog_id,
            "catalog_version": catalog.version, "artifact_id": artifact.artifact_id,
            "artifact_sha256": _artifact_sha256(artifact),
            "observation": {"rows": [{"id": "a"}], "row_count": 1, "elapsed_ms": elapsed,
                "success": True, "backend_id": request.backend_id, "artifact_id": artifact.artifact_id,
                "started_at": datetime.fromtimestamp(i, timezone.utc).isoformat(),
                "ended_at": datetime.fromtimestamp(i+1, timezone.utc).isoformat()}})
        estimate = RemoteEstimate.from_tool_result(request.observation_key, result)
        snapshot = PlanObservationSnapshot("synthetic", "v1", (estimate,), 1000)
        collection = PlanObservationCollection((request,), (result,), snapshot, elapsed+2)
        samples.append(AcquisitionPreparationSample(str(i), "preparation", i+1, context,
            "b"*64, collection, 3+i))
    options = dict(space=space, snapshot=history, request=request,
        environment_episode=episode, cutoff_at=3, max_expected_extra_ms=1000)
    return space, history, initial, tuple(samples), options


def test_empirical_distribution_uses_action_wall_and_retains_preparation_cost():
    space, history, initial, samples, options = setup()
    policy, receipt = prepare_acquisition_policy(samples, **options)
    assert [o.probability for o in policy.outcomes] == [.5, .5]
    assert policy.expected_acquisition_ms == 502.5  # Includes wrapper cost, not backend500.5.
    assert policy.expected_reselection_ms == 3.5
    assert receipt["historical_acquisition_ms"] == 1005
    assert receipt["historical_reselection_ms"] == 7
    assert policy.target.historical_calls == 2
    assert policy.target.preparation_sha256 == receipt["preparation_sha256"]
    assert policy.target.preparation_cpu_ms >= 0
    decision = policy.decide(space, history, initial, environment_episode=options["environment_episode"])
    assert decision["action"] == "stop"
    tool, calls = registry(space)
    result = run_semantic_plans(space, tool, snapshot=history, acquisition_policy=policy,
        environment_episode=options["environment_episode"])
    assert result["success"], result
    assert result["observation_calls"] == 0 and len(calls) == 1
    assert result["execution"]["value"]["final_rows"]
    assert result["acquisition"]["policy"]["target"]["historical_calls"] == 2


def test_response_reselection_and_common_scoring_have_separate_observed_costs():
    from test_semantic_acquisition import forecast_policy
    space, history = single_source_fixture()
    tool, _ = registry(space)
    result = run_semantic_plans(space, tool, snapshot=history, acquisition_policy=forecast_policy())
    assert result["success"], result
    assert result["acquisition"]["decision"]["action"] == "acquire"
    refresh = result["refresh"]
    assert refresh["reselection_ms"] > 0 and refresh["scoring_ms"] > 0
    assert refresh["selection_ms"] == refresh["reselection_ms"] + refresh["scoring_ms"]


@pytest.mark.parametrize("change", ["context", "request"])
def test_prepared_forecast_cannot_silently_follow_a_different_context_or_request(change):
    space, history, initial, samples, options = setup()
    policy, _ = prepare_acquisition_policy(samples, **options)
    altered = replace(history, coordinator_row_ms=history.coordinator_row_ms+1) if change == "context" else replace(
        history, estimates=tuple(replace(e, elapsed_ms=100 if e.backend_id==options["request"].backend_id else 0)
                                for e in history.estimates))
    tool, calls = registry(space)
    result = run_semantic_plans(space, tool, snapshot=altered, acquisition_policy=policy,
        environment_episode=options["environment_episode"])
    assert not result["success"] and "match" in result["error"]
    assert calls == [] and result["total_remote_calls"] == 0


@pytest.mark.parametrize("mutation", [
    lambda s: replace(s, phase="evaluation"),
    lambda s: replace(s, completed_at=3),
    lambda s: replace(s, context_sha256="0"*64),
    lambda s: replace(s, collection=replace(s.collection, error="saved failed attempt")),
    lambda s: replace(s, reselection_ms=float("nan")),
])
def test_invalid_or_failed_history_rejects_preparation_without_filtering(mutation):
    _, _, _, samples, options = setup()
    with pytest.raises(ValueError):
        prepare_acquisition_policy((samples[0], mutation(samples[1])), **options)


@pytest.mark.parametrize("episode", [None, "a-new-environment"])
def test_prepared_forecast_requires_the_current_environment_episode(episode):
    space, history, _, samples, options = setup()
    policy, _ = prepare_acquisition_policy(samples, **options)
    tool, calls = registry(space)
    result = run_semantic_plans(space, tool, snapshot=history, acquisition_policy=policy,
        environment_episode=episode)
    assert not result["success"] and "environment episode" in result["error"]
    assert calls == [] and result["total_remote_calls"] == 0


@pytest.mark.parametrize("field,value", [
    ("operation", "sample"), ("artifact_sha256", "0"*64), ("artifact_id", "other-query"),
    ("success", False), ("ended_at", "1970-01-01T00:00:04+00:00"),
])
def test_original_response_cannot_disagree_with_declared_request_or_prior_phase(field, value):
    _, _, _, samples, options = setup()
    sample = samples[1]
    original = sample.collection.tool_results[0]
    response = dict(original.value)
    if field in ("success", "ended_at"):
        response["observation"] = {**response["observation"], field: value}
    else:
        response[field] = value
    changed = replace(original, value=response)
    estimate = RemoteEstimate.from_tool_result(options["request"].observation_key, changed)
    altered = replace(sample, collection=replace(sample.collection, tool_results=(changed,),
        snapshot=replace(sample.collection.snapshot, estimates=(estimate,))))
    with pytest.raises(ValueError):
        prepare_acquisition_policy((samples[0], altered), **options)


def test_an_alias_does_not_turn_one_observation_into_two_calls():
    _, _, _, samples, options = setup()
    with pytest.raises(ValueError, match="multiple preparation samples"):
        prepare_acquisition_policy((*samples, replace(samples[0], sample_id="alias")), **options)


def test_prepared_forecast_ordinary_entry_uses_the_current_memory_episode(tmp_path, monkeypatch):
    import xgap.agent.semantic_execution as entry
    from test_question_interpretation import question_run
    from test_semantic_acquisition import synthetic_profiles
    from test_semantic_refresh import B04, planning
    from xgap.agent.memory import JsonlMemoryStore
    from xgap.runtime.semantic_memory import SemanticPlanMemory

    captured = []
    original = entry.prepare_semantic_placements

    def capture(*args, **kwargs):
        space = original(*args, **kwargs)
        captured.append(space)
        return space

    monkeypatch.setattr(entry, "prepare_semantic_placements", capture)
    synthetic_profiles(monkeypatch, {"rdf_a": 1, "rdf_b": 10})
    memory = SemanticPlanMemory(JsonlMemoryStore(tmp_path / "memory.jsonl"), "current-B04", 3600)
    cold, _ = question_run(B04, plan_memory=memory)
    assert cold["success"], cold
    history = PlanObservationSnapshot.from_dict(planning(cold)["observation"]["snapshot"])
    _, _, _, samples, options = prepare_fixture(captured[0], history, memory.environment_episode)
    policy, _ = prepare_acquisition_policy(samples, **options)
    saved = [r.to_dict() for r in memory.store.records()]
    warm, calls = question_run(B04, plan_memory=memory, acquisition_policy=policy)
    assert warm["success"], warm
    run = planning(warm)
    assert run["execution"]["value"]["final_rows"] == B04["expected_rows"]
    assert run["acquisition"]["decision"]["action"] == "stop"
    assert run["memory"]["state"] == "hit" and run["observation_calls"] == 0 and len(calls) == 1
    assert saved == [r.to_dict() for r in memory.store.records()]
    rejected, calls = question_run(B04, plan_memory=memory, acquisition_policy=policy,
        environment_episode="another-B04")
    assert not rejected["success"] and not calls
    assert "environment episode" in rejected["state"]["message"]
