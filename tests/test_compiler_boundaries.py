from pathlib import Path

import pytest

from xgap.algebra.conditions import EdgeRef, LabelEquals
from xgap.algebra.ops import (
    BindNodeOp,
    EdgesOp,
    FocusProjectionOp,
    RecursiveMode,
    RecursiveOp,
)
from xgap.backends import registry
from xgap.compilers import compile_cypher, compile_gql
from xgap.compilers.errors import UnsupportedCompilationError


REPO_ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR_DIR = REPO_ROOT / "descriptors" / "backends"


def _profile(backend_id: str):
    registry.load_descriptors(DESCRIPTOR_DIR)
    return registry.get_capability_profile(backend_id)


def test_cypher_compiler_blocks_unsupported_features_before_artifact() -> None:
    profile = _profile("neo4j")
    plan = RecursiveOp(
        EdgesOp(),
        RecursiveMode.TRAIL,
    )

    with pytest.raises(UnsupportedCompilationError) as exc_info:
        compile_cypher(plan, profile=profile)

    failure = exc_info.value.failure
    assert failure.backend_id == "neo4j"
    assert failure.language == "cypher"
    assert failure.unsupported_feature.feature_id == "path_algebra.Recursive.TRAIL"
    assert failure.metadata["compiler_input"]["target_backend_id"] == "neo4j"


def test_m6_binding_layer_is_explicitly_outside_m9_compilation() -> None:
    profile = _profile("neo4j")
    plan = FocusProjectionOp("x", BindNodeOp("x", EdgesOp()))

    with pytest.raises(UnsupportedCompilationError) as exc_info:
        compile_cypher(plan, profile=profile)

    unsupported_ids = {
        item["feature_id"]
        for item in exc_info.value.failure.metadata["all_unsupported_features"]
    }
    assert "m6.FocusProjection" in unsupported_ids
    assert "m6.BindNode" in unsupported_ids


def test_gql_compiler_remains_explicitly_unsupported_in_m9() -> None:
    with pytest.raises(NotImplementedError) as exc_info:
        compile_gql(EdgesOp())

    assert isinstance(exc_info.value, UnsupportedCompilationError)
    assert exc_info.value.failure.unsupported_feature.feature_id == "native.gql"


def test_condition_not_declared_by_profile_fails_explicitly() -> None:
    from xgap.algebra.conditions import Or
    from xgap.algebra.ops import SelectionOp

    profile = _profile("neo4j")
    plan = SelectionOp(
        Or(LabelEquals(EdgeRef(1), "OWNS"), LabelEquals(EdgeRef(1), "TRANSFER")),
        EdgesOp(),
    )

    with pytest.raises(UnsupportedCompilationError) as exc_info:
        compile_cypher(plan, profile=profile)

    assert exc_info.value.failure.unsupported_feature.feature_id == "condition.boolean_or"
