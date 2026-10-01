"""New deployment/partition/NL input risks only; no training or model calls."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest
from rdflib import Graph, Namespace

from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.experiments.one_shot_split import FIXTURE, QUERY_ID, split_inputs, prepare_split_deployment
from xgap.planning.runtime_estimator import FrozenSourceStatistics, SourceStatistics, _hash, _json
from xgap.planning.runtime_work_estimator import (
    FEATURE_SCHEMA, FrozenWorkEstimator, feature_names, load_frozen_estimator,
)
from xgap.planning.runtime_work_deployment import FrozenWorkDeployment
from xgap.runtime.one_shot_planning import prepare_one_shot_domain
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.semantic.program import SemanticGraphProgram


@pytest.fixture
def parent():
    stats = FrozenSourceStatistics("synthetic-old", "v0", tuple(SourceStatistics(b,
        "original", "v0", 13, 80, "analytic-mechanics-only") for b in ("neo4j", "fuseki")))
    names = feature_names(stats)
    # Explicit analytic constants, not collected labels or another training run.
    provenance = {"training_id": "analytic-deployment-mechanics", "training_kind": "toy_correctness",
        "split_role": "training", "sample_count": 2, "source_statistics_sha256": stats.sha256,
        "algorithm": "fixed_sweep_nonnegative_relative_ridge_v1", "fit_sweeps": 1,
        "training_query_ids": ["analytic-a", "analytic-b"], "excluded_query_ids": [QUERY_ID],
        "training_samples_sha256": "0"*64}
    return FrozenWorkEstimator("analytic-not-measured", stats, names,
        _hash({"version": FEATURE_SCHEMA, "names": names}), (1.,)*(len(names)+1),
        (1.,)*len(names), (0.,)*len(names), (100.,)*len(names), 1., _json(provenance))


def plans():
    request, stats, inputs, _ = split_inputs()
    gold = json.loads((FIXTURE / "gold/program.json").read_text())
    domain, receipt = prepare_one_shot_domain(SemanticGraphProgram.from_dict(gold["program"]),
        operator_sources=gold["operator_sources"], sources=inputs["sources"],
        backends=inputs["backends"], policy=OneShotPolicy.for_mode("performance"))
    return stats, domain, receipt


def test_deployment_reuses_weights_and_roundtrips_without_fit(parent, tmp_path, monkeypatch):
    import xgap.planning.runtime_work_estimator as work
    monkeypatch.setattr(work, "fit_work_estimator", lambda *a, **kw: pytest.fail("Unexpected fit"))
    parent_path, target = tmp_path/"parent.json", tmp_path/"deployment.json"
    parent.save(parent_path)
    before = parent_path.read_bytes()
    deployment = prepare_split_deployment(parent_path, target)
    loaded = load_frozen_estimator(target)
    assert loaded.to_dict() == deployment.to_dict() and parent_path.read_bytes() == before
    assert loaded.trained_model.to_dict() == parent.to_dict()
    stats, choices, _ = plans()
    prediction = loaded.predict(choices[0].plan)
    assert prediction.status == "estimated"
    assert prediction.provenance["training_source_statistics_sha256"] == parent.statistics.sha256
    assert prediction.provenance["serving_source_statistics_sha256"] == stats.sha256
    assert prediction.provenance["transfer_calibrated"] is False
    assert prediction.provenance["fit_calls"] == prediction.provenance["collection_calls"] == 0
    assert prediction.provenance["model_sha256"] == loaded.model_sha256 != parent.model_sha256
    with pytest.raises(FileExistsError): loaded.save(target)
    corrupt = loaded.to_dict(); corrupt["trained_model"]["coefficients"][0] += 1
    with pytest.raises(ValueError, match="hash"): FrozenWorkDeployment.from_dict(corrupt)


def test_deployment_checks_identity_snapshot_and_feature_compatibility(parent):
    stats, choices, _ = plans()
    deployment = FrozenWorkDeployment("split", parent, stats, "fixture:offline")
    original = choices[0].plan
    assert parent.predict(original).status == "unavailable_missing_features"
    for field, value in (("source_id", "wrong-source"), ("snapshot_version", "stale")):
        meta = deepcopy(original.metadata)
        meta["source_identities"]["neo4j"][field] = value
        result = deployment.predict(replace(original, metadata=meta))
        assert result.status == "unavailable_missing_features" and result.estimated_ms is None
        assert any("identity_mismatch" in key for key in result.features.unknown_fields)
    meta = deepcopy(original.metadata); meta["source_snapshot_versions"]["fuseki"] = "stale"
    assert deployment.predict(replace(original, metadata=meta)).estimated_ms is None
    alien = replace(stats, entries=tuple(replace(s, backend_id="other") if s.backend_id=="neo4j" else s for s in stats.entries))
    with pytest.raises(ValueError, match="feature schema"):
        FrozenWorkDeployment("split", parent, alien, "fixture:offline")
    # New scorer delegation preserves the existing v2 result on its own snapshot.
    same = FrozenWorkDeployment("same", parent, parent.statistics, "fixture:no-shift")
    meta = deepcopy(original.metadata)
    meta["source_snapshot_versions"] = {b:"v0" for b in ("neo4j", "fuseki")}
    meta["source_identities"] = {b:{"source_id":"original", "snapshot_version":"v0"} for b in ("neo4j", "fuseki")}
    plan = replace(original, metadata=meta)
    assert same.predict(plan).estimated_ms == parent.predict(plan).estimated_ms


def test_request_has_nl_and_reusable_schema_without_reading_gold(monkeypatch):
    read = Path.read_text
    def guarded(path, *a, **kw):
        if "gold" in path.parts: pytest.fail("Gold read during inference preparation")
        return read(path, *a, **kw)
    monkeypatch.setattr(Path, "read_text", guarded)
    request, stats, inputs, _ = split_inputs()
    assert request.required_constraints == ()
    assert set(request.context) == {"query_id", "source_schema", "one_shot_profile", "runtime"}
    assert "operator_id" not in json.dumps(request.to_dict())
    assert "requested_output" not in request.context
    assert {s.source_id for s in stats.entries} == {"profiles", "relations"}
    assert inputs["sources"]["profiles"].replica_backend_ids == ("neo4j",)
    assert inputs["sources"]["relations"].replica_backend_ids == ("fuseki",)


def test_split_facts_and_both_compiled_strategies_require_two_sources():
    stats, choices, receipt = plans()
    assert len(choices) == 2
    rdf = Graph().parse(FIXTURE / "load.ttl", format="turtle")
    ns = Namespace("https://xgap.test/split/")
    assert not list(rdf.triples((None, ns.age, None)))
    assert not list(rdf.triples((None, None, ns.Person)))
    profiles = json.loads((FIXTURE / "profiles.json").read_text())
    assert profiles["edges"] == [] and len(profiles["nodes"]) == 4
    relations = json.loads((FIXTURE / "relations.json").read_text())
    assert all(n["properties"] == {} for n in relations["nodes"])
    expected_paths = {(ns.b, ns.r1), (ns.c, ns.r2)}
    assert {(row.person, row.edge) for row in rdf.query((FIXTURE / "gold/relations.rq").read_text())} == expected_paths
    for choice in choices:
        remote = [n for n in choice.plan.nodes if n.kind in (R.REMOTE_QUERY,R.REMOTE_BIND_QUERY)]
        assert {n.parameters["backend_id"] for n in remote} == {"neo4j", "fuseki"}
        assert len(remote) == 2
        path = next(n for n in remote if n.parameters["backend_id"] == "fuseki")
        rows = list(rdf.query(path.parameters["artifact"]["text"]))
        assert len(rows) == 2
    targets = {str(p["id"]) for p in profiles["nodes"] if p["properties"]["age"] >= 30}
    actual = [{"person":str(person), "edge":str(edge)} for person,edge in expected_paths
              if str(person).removeprefix(str(ns)) in targets]
    assert actual == json.loads((FIXTURE / "gold/expected_rows.json").read_text())
