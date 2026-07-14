from pathlib import Path

from xgap.backends import registry
from xgap.backends.capabilities import BackendCapabilityProfile, SupportLevel
from xgap.backends.compatibility import (
    FeatureRequest,
    check_backend_features,
    check_backend_support,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR_DIR = REPO_ROOT / "descriptors" / "backends"


def _profile(backend_id: str) -> BackendCapabilityProfile:
    registry.load_descriptors(DESCRIPTOR_DIR)
    return registry.get_capability_profile(backend_id)


def test_neo4j_support_check_distinguishes_levels() -> None:
    profile = _profile("neo4j")

    supported = check_backend_support(profile, "graph_model.node_labels")
    conditional = check_backend_support(profile, FeatureRequest("path_algebra.Recursive.WALK"))
    unsupported = check_backend_support(profile, "m6.QuantifiedCheck")

    assert supported.level is SupportLevel.SUPPORTED
    assert supported.unsupported_features == ()
    assert conditional.level is SupportLevel.CONDITIONAL
    assert conditional.conditions
    assert unsupported.level is SupportLevel.UNSUPPORTED
    assert unsupported.unsupported_features[0].feature_id == "m6.QuantifiedCheck"


def test_fuseki_support_check_reports_pathset_boundary() -> None:
    profile = _profile("fuseki")

    rdf = check_backend_support(profile, "graph_model.rdf_graph")
    path_set = check_backend_support(profile, "result_model.path_set")
    path_pattern = check_backend_support(profile, "pattern.PathPatternQuery")

    assert rdf.level is SupportLevel.SUPPORTED
    assert path_set.level is SupportLevel.UNSUPPORTED
    assert "PathSet" in path_set.reason.message
    assert path_pattern.level is SupportLevel.CONDITIONAL


def test_reference_evaluator_support_check_is_not_native_compiler_support() -> None:
    profile = _profile("reference_evaluator")

    assert check_backend_support(profile, "m6.FocusProjection").level is SupportLevel.SUPPORTED
    assert check_backend_support(profile, "native.cypher").level is SupportLevel.UNSUPPORTED


def test_undeclared_feature_is_explicitly_unsupported() -> None:
    profile = _profile("neo4j")

    report = check_backend_support(profile, "future.unimplemented_feature")

    assert report.level is SupportLevel.UNSUPPORTED
    assert report.reason.code == "feature_not_declared"
    assert report.unsupported_features[0].feature_id == "future.unimplemented_feature"


def test_feature_set_check_is_deterministic_and_blocks_on_unsupported() -> None:
    profile = _profile("neo4j")

    report = check_backend_features(
        profile,
        (
            "graph_model.node_labels",
            "path_algebra.Selection",
            "m6.FocusedQuantifiedPatternQuery",
        ),
        feature_set_id="minimal_mvp_probe",
    )

    assert report.feature_id == "minimal_mvp_probe"
    assert report.level is SupportLevel.UNSUPPORTED
    assert report.metadata["checked_features"] == [
        "graph_model.node_labels",
        "m6.FocusedQuantifiedPatternQuery",
        "path_algebra.Selection",
    ]
    assert [feature.feature_id for feature in report.unsupported_features] == [
        "m6.FocusedQuantifiedPatternQuery",
        "path_algebra.Selection",
    ]


def test_feature_set_check_can_be_conditional() -> None:
    profile = _profile("fuseki")

    report = check_backend_features(
        profile,
        (
            "graph_model.rdf_graph",
            "graph_model.scalar_property_predicates",
        ),
    )

    assert report.level is SupportLevel.CONDITIONAL
    assert report.unsupported_features[0].feature_id == "graph_model.scalar_property_predicates"
