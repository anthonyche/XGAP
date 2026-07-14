import json
from pathlib import Path

import pytest

from xgap.backends import registry
from xgap.backends.capabilities import (
    BackendCapabilityProfile,
    CompilerFailureSpec,
    CompilerInputSpec,
    CompilerOutputSpec,
    SupportLevel,
    SupportReason,
    UnsupportedFeature,
)
from xgap.infrastructure.runtime import QueryArtifact


REPO_ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR_DIR = REPO_ROOT / "descriptors" / "backends"


def _profiles() -> dict[str, BackendCapabilityProfile]:
    descriptors = registry.load_descriptors(DESCRIPTOR_DIR)
    return {
        descriptor.id: BackendCapabilityProfile.from_descriptor(descriptor)
        for descriptor in descriptors
    }


def test_descriptor_capability_profiles_load() -> None:
    profiles = _profiles()

    assert set(profiles) == {"fuseki", "neo4j", "reference_evaluator"}
    assert profiles["neo4j"].feature_namespace == "xgap.path_gpc"
    assert profiles["fuseki"].version == 1
    assert profiles["reference_evaluator"].feature("m6.QuantifiedCheck").level is SupportLevel.SUPPORTED


def test_support_level_parsing_and_validation() -> None:
    assert SupportLevel.from_value("supported") is SupportLevel.SUPPORTED
    assert SupportLevel.from_value("CONDITIONAL") is SupportLevel.CONDITIONAL

    with pytest.raises(ValueError, match="Unsupported support level"):
        SupportLevel.from_value("maybe")


def test_profile_serialization_round_trip() -> None:
    profile = _profiles()["neo4j"]

    payload = profile.to_dict()
    rebuilt = BackendCapabilityProfile.from_dict(json.loads(profile.to_json()))

    assert rebuilt == profile
    assert payload["features"]["graph_model.node_labels"]["level"] == "supported"


def test_neo4j_profile_has_mvp_and_unsupported_boundaries() -> None:
    profile = _profiles()["neo4j"]

    assert profile.feature("graph_model.labeled_property_graph").level is SupportLevel.SUPPORTED
    assert profile.feature("path_algebra.Nodes").level is SupportLevel.CONDITIONAL
    assert profile.feature("path_algebra.Recursive.TRAIL").level is SupportLevel.UNSUPPORTED
    assert profile.feature("m6.FocusedQuantifiedPatternQuery").level is SupportLevel.UNSUPPORTED


def test_fuseki_profile_has_rdf_and_path_identity_boundaries() -> None:
    profile = _profiles()["fuseki"]

    assert profile.feature("graph_model.rdf_graph").level is SupportLevel.SUPPORTED
    assert profile.feature("graph_model.node_labels").level is SupportLevel.CONDITIONAL
    assert profile.feature("result_model.path_set").level is SupportLevel.UNSUPPORTED
    assert profile.feature("pattern.PathPatternQuery").level is SupportLevel.CONDITIONAL


def test_reference_profile_covers_implemented_m0_to_m6_reference_semantics() -> None:
    profile = _profiles()["reference_evaluator"]

    for feature_id in (
        "path_algebra.Nodes",
        "path_algebra.Edges",
        "path_algebra.Selection",
        "path_algebra.Union",
        "path_algebra.Join",
        "path_algebra.Recursive.WALK",
        "path_algebra.Recursive.TRAIL",
        "path_algebra.Recursive.ACYCLIC",
        "path_algebra.Recursive.SIMPLE",
        "path_algebra.Recursive.SHORTEST",
        "extended_path.GroupBy",
        "extended_path.OrderBy",
        "extended_path.Projection",
        "pattern.PathPatternQuery",
        "m6.FocusedQuantifiedPatternQuery",
        "m6.BindingRelation",
        "m6.BindNode",
        "m6.BindEdge",
        "m6.BindingJoin",
        "m6.BindingProject",
        "m6.QuantifiedCheck",
        "m6.AntiSemiJoin",
        "m6.FocusProjection",
    ):
        assert profile.feature(feature_id).level is SupportLevel.SUPPORTED

    assert profile.feature("native.cypher").level is SupportLevel.UNSUPPORTED


def test_compiler_boundary_records_are_serializable() -> None:
    compiler_input = CompilerInputSpec(
        logical_plan_id="plan-1",
        logical_plan_kind="PathPatternQuery.lowered",
        target_backend_id="neo4j",
        target_language="cypher",
        expected_result_model="row_bindings",
        required_features=("graph_model.node_labels", "path_algebra.Selection"),
    )
    artifact = QueryArtifact(
        artifact_id="future-artifact",
        language="cypher",
        text="RETURN 1 AS ok",
        kind="compiled",
    )
    compiler_output = CompilerOutputSpec(
        target_backend_id="neo4j",
        artifact=artifact,
        result_model="row_bindings",
        semantic_assumptions=("future compiler output placeholder",),
    )
    unsupported = UnsupportedFeature(
        feature_id="m6.QuantifiedCheck",
        level=SupportLevel.UNSUPPORTED,
        reason=SupportReason(
            code="not_compiled_in_m8",
            message="M8 defines the boundary but does not compile M6 quantified checks.",
        ),
    )
    compiler_failure = CompilerFailureSpec(
        backend_id="neo4j",
        language="cypher",
        unsupported_feature=unsupported,
        reason=unsupported.reason,
        support_level=SupportLevel.UNSUPPORTED,
        future_milestone_hint="M9+",
    )

    assert CompilerInputSpec.from_dict(compiler_input.to_dict()) == compiler_input
    assert CompilerOutputSpec.from_dict(compiler_output.to_dict()) == compiler_output
    assert CompilerFailureSpec.from_dict(compiler_failure.to_dict()) == compiler_failure
    json.dumps(compiler_failure.to_dict(), sort_keys=True)
