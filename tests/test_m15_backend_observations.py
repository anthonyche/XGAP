from __future__ import annotations

from xgap.backends.neo4j_client import Neo4jClient
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import QueryArtifact


def _client() -> Neo4jClient:
    return Neo4jClient(
        BackendDescriptor(
            id="neo4j",
            engine="neo4j",
            language="cypher",
            data_model="property_graph",
        )
    )


def test_neo4j_explain_returns_native_plan_as_black_box_observation(
    monkeypatch,
) -> None:
    client = _client()
    calls: list[tuple[str, dict[str, object], bool]] = []

    def post(statement, parameters, *, include_stats=False):
        calls.append((statement, parameters, include_stats))
        return {
            "results": [
                {
                    "columns": ["company"],
                    "data": [],
                    "plan": {"operatorType": "ProduceResults", "children": []},
                    "stats": {},
                }
            ],
            "errors": [],
        }

    monkeypatch.setattr(client, "_post_statement", post)
    report = client.explain(
        QueryArtifact(
            "risk-query",
            "cypher",
            "MATCH (c:Company) RETURN c.id AS company",
            parameters={"limit": 5},
        )
    )

    assert report.success
    assert calls == [
        (
            "EXPLAIN MATCH (c:Company) RETURN c.id AS company",
            {"limit": 5},
            True,
        )
    ]
    assert report.metadata["observation"] == "explain"
    assert report.metadata["native_plan"]["operatorType"] == "ProduceResults"


def test_neo4j_profile_returns_rows_plan_and_stats(monkeypatch) -> None:
    client = _client()

    def post(statement, parameters, *, include_stats=False):
        assert statement.startswith("PROFILE ")
        assert include_stats is True
        return {
            "results": [
                {
                    "columns": ["company"],
                    "data": [{"row": ["C1"]}],
                    "profile": {
                        "operatorType": "ProduceResults",
                        "rows": 1,
                    },
                    "stats": {"contains_updates": False},
                }
            ],
            "errors": [],
        }

    monkeypatch.setattr(client, "_post_statement", post)
    report = client.profile(
        QueryArtifact("risk-query", "cypher", "RETURN 'C1' AS company")
    )

    assert report.success
    assert report.rows == [{"company": "C1"}]
    assert report.metadata["observation"] == "profile"
    assert report.metadata["native_plan"]["rows"] == 1
    assert report.metadata["stats"] == {"contains_updates": False}


def test_neo4j_observation_fails_closed_without_native_plan(monkeypatch) -> None:
    client = _client()
    monkeypatch.setattr(
        client,
        "_post_statement",
        lambda statement, parameters, *, include_stats=False: {
            "results": [{"columns": [], "data": [], "stats": {}}],
            "errors": [],
        },
    )

    report = client.explain(QueryArtifact("q", "cypher", "RETURN 1"))

    assert not report.success
    assert report.rows == []
    assert "returned no native plan" in str(report.error)


def test_neo4j_observation_rejects_prefixed_or_non_cypher_artifacts() -> None:
    client = _client()

    prefixed = client.explain(QueryArtifact("q", "cypher", " PROFILE RETURN 1"))
    wrong_language = client.profile(QueryArtifact("q", "sparql", "SELECT * WHERE {}"))

    assert not prefixed.success
    assert "must not include" in str(prefixed.error)
    assert not wrong_language.success
    assert "requires native or compiled Cypher" in str(wrong_language.error)
