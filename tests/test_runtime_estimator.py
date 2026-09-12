"""Targeted frozen RuntimePlan prediction risks; no backend or model calls."""

from dataclasses import replace
import hashlib
import json
import math

import pytest

import xgap.planning.runtime_estimator as implementation
from xgap.planning.runtime_estimator import (
    FrozenRuntimeEstimator,
    FrozenSourceStatistics,
    RuntimeTrainingSample,
    SourceStatistics,
    extract_runtime_features,
    fit_runtime_estimator,
)
from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNode, RuntimeNodeKind


def _plan(query_id, remote_count=2, *, backend="neo4j", version="toy-snapshot-1"):
    nodes = [RuntimeNode("r0", RuntimeNodeKind.REMOTE_QUERY,
                         parameters={"backend_id": backend})]
    for index in range(1, remote_count):
        nodes.append(RuntimeNode(f"r{index}", RuntimeNodeKind.REMOTE_BIND_QUERY,
                                 inputs=(f"r{index - 1}",),
                                 parameters={"backend_id": backend}))
    nodes.append(RuntimeNode("answer", RuntimeNodeKind.PROJECT,
                             inputs=(f"r{remote_count - 1}",), parameters={"fields": ["id"]}))
    return FederatedExecutionPlan(f"plan-{query_id}", tuple(nodes), ("answer",),
        max_remote_calls=remote_count, max_parallelism=1,
        metadata={"query_id": query_id, "source_snapshot_versions": {backend: version}})


def _statistics():
    return FrozenSourceStatistics("toy-independent-statistics", "statistics-v1", (
        SourceStatistics("neo4j", "toy-source", "toy-snapshot-1", 100, 32.0,
                         "fixture:independent-training-source-summary"),
        SourceStatistics("fuseki", "unmeasured-source", "toy-snapshot-1", None, None,
                         "fixture:unavailable-source-summary"),
    ))


def _samples(*, slope=0.2):
    # Analytic synthetic labels check fitting correctness, not real performance.
    return tuple(RuntimeTrainingSample(
        f"train-observation-{index}", f"train-query-{index}", _plan(f"train-query-{index}", index),
        math.exp(1 + slope * index), hashlib.sha256(f"synthetic-{index}-{slope}".encode()).hexdigest())
        for index in range(1, 6))


def _fit(samples=None, **overrides):
    arguments = dict(statistics=_statistics(), training_id="independent-toy-training",
        model_version="toy-runtime-ridge-v1", training_kind="toy_correctness",
        excluded_query_ids=("evaluation-query",),
        collection_ref="fixture:analytic-labels-not-native-measurements",
        collection_elapsed_ms=None, collection_remote_calls=None)
    arguments.update(overrides)
    return fit_runtime_estimator(_samples() if samples is None else samples, **arguments)


def test_offline_fit_predicts_from_labels_and_not_a_fixed_routing_prior():
    model = _fit()
    opposite = _fit(_samples(slope=-0.2))
    heldout_plan = _plan("evaluation-query", 4)
    result = model.predict(heldout_plan)
    assert result.status == "estimated"
    assert result.estimated_ms == pytest.approx(math.exp(1.8), rel=0.002)
    assert opposite.predict(heldout_plan).estimated_ms == pytest.approx(math.exp(0.2), rel=0.002)
    assert result.empirical_log_rmse < 0.002
    assert result.provenance["training_query_overlap"] is False
    assert result.provenance["training_kind"] == "toy_correctness"
    assert result.provenance["quality_bound"] is None


def test_frozen_roundtrip_does_not_fit_and_preserves_identity_costs(tmp_path, monkeypatch):
    model = _fit()
    path = tmp_path / "frozen-model.json"
    model.save(path)
    with pytest.raises(FileExistsError):
        model.save(path)
    monkeypatch.setattr(implementation, "fit_runtime_estimator",
                        lambda *args, **kwargs: pytest.fail("prediction attempted online fit"))
    restored = FrozenRuntimeEstimator.load(path)
    assert restored.to_dict() == model.to_dict()
    record = restored.predict(_plan("evaluation-query")).to_dict()
    assert record["status"] == "estimated"
    assert record["prediction_elapsed_ms"] >= 0
    assert record["provenance"]["fit_calls"] == 0
    assert record["provenance"]["current_query_observation_calls"] == 0
    assert record["provenance"]["model_sha256"] == model.model_sha256
    offline = model.to_dict()["training_provenance"]["offline_cost"]
    assert offline["collection_elapsed_ms"] is None
    assert offline["collection_remote_calls"] is None
    assert offline["fit_elapsed_ms"] > 0


@pytest.mark.parametrize("plan,missing", [
    (_plan("evaluation-query", backend="unknown"), "backend.unknown.source_statistics"),
    (_plan("evaluation-query", backend="fuseki"), "backend.fuseki.queried_log_rows"),
    (_plan("evaluation-query", version="different-snapshot"),
     "backend.neo4j.source_snapshot_version_missing_or_mismatched"),
    (replace(_plan("evaluation-query"), metadata={"query_id": "evaluation-query"}),
     "backend.neo4j.source_snapshot_version_missing_or_mismatched"),
])
def test_unknown_features_or_source_identity_never_become_a_zero_cost(plan, missing):
    result = _fit().predict(plan)
    assert result.status == "unavailable_missing_features"
    assert result.estimated_ms is None
    assert result.empirical_log_rmse is None
    assert missing in result.features.unknown_fields
    assert result.provenance["current_query_observation_calls"] == 0


def test_training_cannot_use_heldout_or_duplicate_observations_or_unknown_features():
    samples = _samples()
    with pytest.raises(ValueError, match="overlap"):
        _fit(excluded_query_ids=(samples[0].query_id,))
    with pytest.raises(ValueError, match="unique"):
        _fit((samples[0], samples[0]))
    with pytest.raises(ValueError, match="separately declared training"):
        replace(samples[0], split_role="heldout_family")
    bad = replace(samples[0], plan=_plan(samples[0].query_id, backend="fuseki"))
    with pytest.raises(ValueError, match="unknown"):
        _fit((bad, samples[1]))
    with pytest.raises(ValueError, match="2..256"):
        _fit(samples * 52)


def test_corrupted_model_and_renamed_source_snapshot_are_rejected():
    artifact = _fit().to_dict()
    artifact["coefficients"][0] += 1
    with pytest.raises(ValueError, match="hash mismatch"):
        FrozenRuntimeEstimator.from_dict(artifact)
    model = _fit()
    with pytest.raises(ValueError, match="training provenance"):
        replace(model, statistics=replace(model.statistics, version="tampered-version"))
    # Even a recomputed outer hash cannot switch the fixed feature contract.
    artifact = model.to_dict()
    artifact["feature_names"][0] = "oracle.answer_rows"
    body = {key: value for key, value in artifact.items() if key != "model_sha256"}
    artifact["model_sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    with pytest.raises(ValueError, match="feature names"):
        FrozenRuntimeEstimator.from_dict(artifact)


def test_prediction_exposes_extrapolation_and_missing_query_identity():
    model = _fit()
    distant = _plan("evaluation-query", 7)
    result = model.predict(distant)
    assert result.status == "estimated"
    assert "plan.node_count" in result.out_of_training_range
    assert result.to_dict()["uncertainty_kind"] == "training_log_residual_rmse_not_calibrated"
    unidentified = replace(distant, metadata={"source_snapshot_versions": {"neo4j": "toy-snapshot-1"}})
    assert model.predict(unidentified).provenance["training_query_overlap"] is None


def test_features_use_dependency_topology_not_serialized_node_order_or_hidden_metadata():
    plan = _plan("evaluation-query", 3)
    baseline = extract_runtime_features(plan, _statistics())
    shuffled = replace(plan, nodes=tuple(reversed(plan.nodes)), metadata={
        **plan.metadata, "expected_rows": [{"id": "must-not-be-a-feature"}],
        "observed_winner": "untrusted-historical-hint", "elapsed_ms": 0})
    assert extract_runtime_features(shuffled, _statistics()) == baseline
    assert baseline.values[baseline.names.index("plan.critical_remote_depth")] == 3
