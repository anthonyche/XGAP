"""New v2 representation, monotonicity and artifact boundaries; no services."""

from copy import deepcopy
from dataclasses import replace
import hashlib

import pytest

from xgap.experiments.tiny_work_training import prepare_tiny_work_training, EXCLUDED_IDS
from xgap.planning.runtime_estimator import RuntimeTrainingSample
from xgap.planning.runtime_work_estimator import (
    FrozenWorkEstimator, extract_work_features, fit_work_estimator,
    frozen_estimator_from_dict, load_frozen_estimator,
)
from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNodeKind as R


@pytest.fixture(scope="module")
def prepared():
    return prepare_tiny_work_training()


def samples(prepared):
    stats, entries, _, _ = prepared
    output = []
    for e in entries:
        f = dict(zip(extract_work_features(e["plan"], stats).names, extract_work_features(e["plan"], stats).values))
        # Analytic positive labels verify mechanisms, not native calibration.
        label = 5 + 2*f["plan.nodes"] + sum(
            f[f"backend.{backend}.{family}.{mode}.calls"] * cost
            for backend, family, cost in (("neo4j", "path", 60), ("fuseki", "path", 10),
                                         ("neo4j", "match", 5), ("fuseki", "match", 20))
            for mode in ("full", "bind"))
        output.append(RuntimeTrainingSample(e["query_id"], e["query_id"], e["plan"], label,
            hashlib.sha256(("analytic:"+e["query_id"]).encode()).hexdigest()))
    return output


def fit(prepared, **changes):
    stats = prepared[0]
    args = dict(statistics=stats, training_id="analytic-work-v2", model_version="mechanics-only",
        training_kind="toy_correctness", excluded_query_ids=EXCLUDED_IDS,
        collection_ref="fixture:analytic-nonnegative-labels", collection_elapsed_ms=None,
        collection_remote_calls=None)
    args.update(changes)
    return fit_work_estimator(samples(prepared), **args)


def get(prepared, query):
    return next(e["plan"] for e in prepared[1] if e["query_id"] == query)


def test_operator_backend_association_distinguishes_swaps_without_reading_ids_answers_or_text(prepared):
    stats = prepared[0]
    left = get(prepared, "WORK-TRAIN-PM-neo4j-fuseki-C")
    right = get(prepared, "WORK-TRAIN-PM-fuseki-neo4j-C")
    a, b = extract_work_features(left, stats), extract_work_features(right, stats)
    assert not a.unknown_fields and a.values != b.values
    assert dict(zip(a.names, a.values))["backend.neo4j.path.full.calls"] == 1
    assert dict(zip(b.names, b.values))["backend.neo4j.path.full.calls"] == 0
    changed = deepcopy(left.to_dict())
    changed["plan_id"] = "different-id"
    changed["metadata"].update(query_id="renamed", expected_rows=[{"gold": "forbidden"}], elapsed_ms=0, observed_winner="oracle")
    changed["nodes"].reverse()
    for n in changed["nodes"]:
        if n["kind"] in ("remote_query", "remote_bind_query"):
            n["parameters"]["artifact"]["text"] = "This must never be parsed as a feature or executed."
    assert extract_work_features(FederatedExecutionPlan.from_dict(changed), stats) == a
    assert len(prepared[1]) == 28 and not (set(EXCLUDED_IDS) & {e["query_id"] for e in prepared[1]})


def test_positive_fitting_distinguishes_backend_work_and_is_monotone_on_more_work(prepared):
    model = fit(prepared)
    assert all(c >= 0 for c in model.coefficients)
    slow = model.predict(get(prepared, "WORK-TRAIN-PM-neo4j-fuseki-C"))
    fast = model.predict(get(prepared, "WORK-TRAIN-PM-fuseki-neo4j-C"))
    assert slow.status == fast.status == "estimated" and slow.estimated_ms > fast.estimated_ms
    single = get(prepared, "WORK-TRAIN-M-neo4j-19")
    nodes = tuple(replace(n, node_id=f"{i}/{n.node_id}", inputs=tuple(f"{i}/{p}" for p in n.inputs))
                  for i in range(6) for n in single.nodes)
    larger = replace(single, plan_id="larger-unseen-work", nodes=nodes,
        roots=tuple(f"{i}/{r}" for i in range(6) for r in single.roots),
        metadata={**single.metadata, "query_id": "new-independent-shape"})
    prediction = model.predict(larger)
    assert prediction.status == "estimated" and prediction.out_of_training_range
    assert prediction.estimated_ms >= model.predict(single).estimated_ms > 0
    assert prediction.provenance["training_query_overlap"] is False
    assert prediction.provenance["quality_bound"] is None
    assert prediction.provenance["fit_calls"] == prediction.provenance["current_query_observation_calls"] == 0


def test_unseen_category_and_missing_descriptor_are_unavailable_not_free(prepared):
    model = fit(prepared)
    original = get(prepared, "WORK-TRAIN-MM-neo4j-fuseki-C")
    novel = replace(original, nodes=tuple(replace(n, kind=R.COORDINATOR_SEMI_JOIN)
        if n.kind is R.COORDINATOR_JOIN else n for n in original.nodes))
    result = model.predict(novel)
    assert result.status == "unavailable_unseen_work" and result.estimated_ms is None
    assert "kind.coordinator_semi_join.count" in result.provenance["unseen_work_categories"]
    unknown = deepcopy(original.to_dict())
    n = next(n for n in unknown["nodes"] if n["kind"] == "remote_query")
    n["parameters"]["artifact"]["parameters"].pop("compiler")
    result = model.predict(FederatedExecutionPlan.from_dict(unknown))
    assert result.status == "unavailable_missing_features" and result.estimated_ms is None


def test_model_identity_loader_and_frozen_cost_provenance_do_not_fit_at_runtime(prepared, tmp_path, monkeypatch):
    model = fit(prepared)
    path = tmp_path / "frozen-v2.json"
    model.save(path)
    with pytest.raises(FileExistsError):
        model.save(path)
    import xgap.planning.runtime_work_estimator as module
    monkeypatch.setattr(module, "fit_work_estimator", lambda *a, **k: pytest.fail("online fitting"))
    restored = load_frozen_estimator(path)
    assert restored.to_dict() == model.to_dict()
    result = restored.predict(get(prepared, "WORK-TRAIN-PM-fuseki-neo4j-B")).to_dict()
    assert result["features"]["schema_version"].endswith("v2") and result["status"] == "estimated"
    assert result["provenance"]["fit_calls"] == result["provenance"]["current_query_observation_calls"] == 0
    assert model.to_dict()["training_provenance"]["offline_cost"]["collection_remote_calls"] is None
    # This is the newly added loader boundary, not a rerun of the legacy gate.
    from test_runtime_estimator import _fit
    legacy = _fit()
    assert frozen_estimator_from_dict(legacy.to_dict()).to_dict() == legacy.to_dict()
    corrupt = model.to_dict(); corrupt["coefficients"][0] += 1
    with pytest.raises(ValueError, match="hash mismatch"):
        frozen_estimator_from_dict(corrupt)
    with pytest.raises(ValueError, match="nonnegative"):
        replace(model, coefficients=(-1, *model.coefficients[1:]))


def test_training_bounds_and_excluded_identity_are_enforced(prepared):
    with pytest.raises(ValueError, match="overlap"):
        fit(prepared, excluded_query_ids=(prepared[1][0]["query_id"],))
    with pytest.raises(ValueError, match="1..256"):
        fit(prepared, fit_sweeps=257)
    model = fit(prepared)
    assert model.to_dict()["training_provenance"]["fit_sweeps"] == 128
    assert model.to_dict()["training_provenance"]["algorithm"] == "fixed_sweep_nonnegative_relative_ridge_v1"


def test_versioned_binding_cost_counts_transmitted_keys_not_all_driver_rows(prepared):
    model=fit(prepared);before=model.to_dict()
    plan=get(prepared,'WORK-TRAIN-PM-fuseki-neo4j-B')
    nodes=[]
    for node in plan.nodes:
        if node.kind is R.REMOTE_BIND_QUERY:
            node=replace(node,parameters={**node.parameters,'max_bindings':1})
        nodes.append(node)
    legacy=replace(plan,nodes=tuple(nodes))
    raw=deepcopy(legacy.to_dict())
    for node in raw['nodes']:
        if node['kind']=='remote_bind_query':
            node['parameters']['artifact']['parameters']['binding_key_work_profile']='scheduler-distinct-key-cap-v1'
    current=FederatedExecutionPlan.from_dict(raw)
    a=model.predict(legacy);b=model.predict(current)
    assert a.status==b.status=='estimated'
    assert 'binding_work_extension' not in a.provenance
    assert b.provenance['binding_work_extension']['calibrated'] is False
    changed=[]
    for name,left,right in zip(a.features.names,a.features.values,b.features.values):
        if left!=right:
            assert name.endswith('.bind.binding_units') and left>right==1
            changed.append(name)
    assert changed and b.estimated_ms<=a.estimated_ms  # A frozen coefficient may be zero.
    assert model.to_dict()==before  # No fit, weight change, or legacy reinterpretation.
    for node in raw['nodes']:
        if node['kind']=='remote_bind_query':
            node['parameters']['artifact']['parameters']['binding_key_work_profile']='unknown-profile'
    invalid=model.predict(FederatedExecutionPlan.from_dict(raw))
    assert invalid.status=='unavailable_missing_features' and invalid.estimated_ms is None
