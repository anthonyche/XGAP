from __future__ import annotations

from pathlib import Path

import pytest

from xgap.algebra.conditions import And, EdgeRef, LabelEquals, NodeRef, PropertyEquals
from xgap.algebra.ops import EdgesOp, SelectionOp
from xgap.backends import registry
from xgap.infrastructure.descriptors import load_yaml_mapping
from xgap.runtime import ExistingM9FragmentCompiler, FragmentCompilationError, SemanticFragment


REPO_ROOT = Path(__file__).resolve().parents[1]


def _compiler() -> ExistingM9FragmentCompiler:
    registry.load_descriptors(REPO_ROOT / "descriptors" / "backends")
    return ExistingM9FragmentCompiler(
        backend_profiles={
            "neo4j": registry.get_capability_profile("neo4j"),
            "fuseki": registry.get_capability_profile("fuseki"),
        },
        backend_mappings={
            "fuseki": load_yaml_mapping(
                REPO_ROOT / "datasets" / "financial_risk_dev" / "backend_mapping.yaml"
            )
        },
    )


def test_existing_m9_compilers_compile_independent_backend_fragments() -> None:
    transfer_plan = SelectionOp(
        And(
            LabelEquals(EdgeRef(1), "OWNS"),
            PropertyEquals(NodeRef.first(), "name", "Alice"),
        ),
        EdgesOp(),
    )
    risk_plan = SelectionOp(
        And(
            LabelEquals(EdgeRef(1), "OWNS"),
            LabelEquals(NodeRef.last(), "Company"),
        ),
        EdgesOp(),
    )
    compiler = _compiler()

    neo4j = compiler.compile(
        SemanticFragment("transfer", "neo4j", transfer_plan, ("match-transfer",))
    )
    fuseki = compiler.compile(
        SemanticFragment("risk", "fuseki", risk_plan, ("match-risk",))
    )

    assert neo4j.artifact.language == "cypher"
    assert fuseki.artifact.language == "sparql"
    assert neo4j.to_runtime_node().parameters["backend_id"] == "neo4j"
    assert fuseki.to_runtime_node().parameters["artifact"]["kind"] == "compiled"


def test_sparql_fragment_requires_explicit_mapping() -> None:
    registry.load_descriptors(REPO_ROOT / "descriptors" / "backends")
    compiler = ExistingM9FragmentCompiler(
        backend_profiles={"fuseki": registry.get_capability_profile("fuseki")}
    )
    fragment = SemanticFragment("risk", "fuseki", EdgesOp(), ("match-risk",))
    with pytest.raises(FragmentCompilationError, match="requires a backend mapping"):
        compiler.compile(fragment)
