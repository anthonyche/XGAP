import json

import pytest

from xgap.llm import (
    MockStructuredCandidateProvider,
    PlannerRequest,
    PlannerSchemaError,
    parse_path_pattern_query,
    path_pattern_query_to_dict,
    plan_from_question,
    plan_response_from_question,
    validate_candidate,
)
from xgap.pattern import Rel, SelectorKind


def candidate_payload() -> dict[str, object]:
    return {
        "provider_id": "mock",
        "model": "mock-structured-candidates",
        "candidates": [
            {
                "candidate_id": "c1",
                "confidence": 0.9,
                "rationale": "Alice is represented as a source node property.",
                "pattern_query": {
                    "path_var": "p",
                    "source": {
                        "var": "person",
                        "label": "Person",
                        "properties": {"name": "Alice"},
                    },
                    "expr": {
                        "kind": "seq",
                        "left": {
                            "kind": "rel",
                            "edge": {"label": "OWNS", "direction": "OUT"},
                        },
                        "right": {
                            "kind": "rel",
                            "edge": {"label": "TRANSFER", "direction": "OUT"},
                        },
                    },
                    "target": {
                        "var": "company",
                        "label": "Company",
                        "properties": {"risk": "high"},
                    },
                    "selector": {"kind": "ALL"},
                    "restrictor": "TRAIL",
                },
            }
        ],
    }


def test_controlled_json_parses_to_path_pattern_query_and_round_trips() -> None:
    query_json = candidate_payload()["candidates"][0]["pattern_query"]  # type: ignore[index]

    query = parse_path_pattern_query(query_json)  # type: ignore[arg-type]

    assert query.path_var.name == "p"
    assert query.source.label == "Person"
    assert query.selector.kind is SelectorKind.ALL
    assert path_pattern_query_to_dict(query)["target"]["properties"] == {"risk": "high"}


def test_plan_from_question_requires_explicit_provider_in_m10() -> None:
    with pytest.raises(NotImplementedError, match="no default live LLM provider"):
        plan_from_question("Find high-risk companies connected to Alice.")


def test_mock_provider_returns_structured_candidates_without_live_llm() -> None:
    provider = MockStructuredCandidateProvider(payload=candidate_payload())

    response = plan_response_from_question(
        "Find high-risk companies connected to Alice by recent transfers.",
        provider=provider,
    )

    assert response.provider_id == "mock"
    assert response.candidates[0].candidate_id == "c1"
    assert response.candidates[0].confidence == 0.9
    json.loads(response.to_json())


def test_candidate_validation_runs_typecheck_lowering_and_plan_validation() -> None:
    provider = MockStructuredCandidateProvider(payload=candidate_payload())
    candidate = plan_from_question("Find high-risk companies connected to Alice.", provider=provider)[0]

    report = validate_candidate(candidate)

    assert report.ok is True
    assert report.stage == "validated"
    assert "Projection [*, *, *]" in report.formatted_plan


def test_invalid_candidate_json_fails_explicitly() -> None:
    request = PlannerRequest("Question?")
    provider = MockStructuredCandidateProvider(
        payload={
            "provider_id": "mock",
            "candidates": [
                {
                    "candidate_id": "bad",
                    "cypher": "MATCH (n) RETURN n",
                    "pattern_query": {},
                }
            ],
        }
    )

    with pytest.raises(PlannerSchemaError, match="native query"):
        plan_response_from_question(request.question, provider=provider)


def test_validation_reports_lowering_stage_for_unsupported_regex_placeholder() -> None:
    payload = candidate_payload()
    candidate = payload["candidates"][0]  # type: ignore[index]
    pattern_query = candidate["pattern_query"]  # type: ignore[index]
    pattern_query["expr"] = {
        "kind": "optional",
        "child": {"kind": "rel", "edge": {"label": "OWNS", "direction": "OUT"}},
    }
    provider = MockStructuredCandidateProvider(payload=payload)

    result = validate_candidate(plan_from_question("Question?", provider=provider)[0])

    assert result.ok is False
    assert result.stage == "lowering"
    assert "OptionalExpr lowering is not implemented" in result.message


def test_rel_json_remains_existing_path_pattern_ast_not_new_operator() -> None:
    query_json = {
        "source": {"var": "x"},
        "expr": {"kind": "rel", "edge": {"label": "OWNS"}},
        "target": {"var": "y"},
        "selector": {"kind": "ALL"},
        "restrictor": "TRAIL",
    }

    query = parse_path_pattern_query(query_json)

    assert isinstance(query.expr, Rel)
