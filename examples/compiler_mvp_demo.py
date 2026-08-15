"""M9 minimal compiler demo.

This demo does not contact Neo4j or Fuseki. It shows the deterministic
compiler boundary:

PathPatternQuery or logical plan -> M8 capability check -> QueryArtifact.
"""

from __future__ import annotations

import sys
from pathlib import Path as FilePath

ROOT = FilePath(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xgap.algebra.conditions import And, EdgeRef, LabelEquals, NodeRef, PropertyEquals
from xgap.algebra.ops import EdgesOp, JoinOp, RecursiveMode, SelectionOp
from xgap.compilers import compile_cypher, compile_sparql
from xgap.infrastructure.descriptors import load_yaml_mapping
from xgap.pattern import (
    EdgePattern,
    NodePattern,
    PathPatternQuery,
    Rel,
    Selector,
    SelectorKind,
    Var,
)


def cypher_pattern_demo() -> None:
    query = PathPatternQuery(
        path_var=Var("p"),
        source=NodePattern(var=Var("person"), label="Person", properties={"name": "Alice"}),
        expr=Rel(EdgePattern(label="OWNS")),
        target=NodePattern(var=Var("company"), label="Company"),
        selector=Selector(SelectorKind.ALL),
        restrictor=RecursiveMode.TRAIL,
    )
    artifact = compile_cypher(query)
    print("Cypher artifact:")
    print(artifact.text)


def sparql_plan_demo() -> None:
    plan = JoinOp(
        SelectionOp(LabelEquals(EdgeRef(1), "OWNS"), EdgesOp()),
        SelectionOp(
            And(
                LabelEquals(EdgeRef(1), "TRANSFER"),
                LabelEquals(NodeRef.last(), "Company"),
                PropertyEquals(NodeRef.last(), "risk", "high"),
            ),
            EdgesOp(),
        ),
    )
    mapping = load_yaml_mapping(ROOT / "datasets/financial_risk_dev/backend_mapping.yaml")
    artifact = compile_sparql(plan, backend_mapping=mapping)
    print("\nSPARQL artifact:")
    print(artifact.text)


if __name__ == "__main__":
    cypher_pattern_demo()
    sparql_plan_demo()
