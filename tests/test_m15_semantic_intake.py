from __future__ import annotations

import json
from pathlib import Path

import pytest

from xgap.agent import GoalStatus, hard_constraints_sha256
from xgap.experiments.m15_semantic_intake import run_semantic_intake
from xgap.semantic import (
    ConstraintPolicy,
    DeterministicSemanticIntake,
    SemanticHoleKind,
    SemanticIntakeError,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
INTAKE = REPO_ROOT / "experiments/configs/m15_e3_financial_risk_intake_dev.json"
CATALOG = REPO_ROOT / "experiments/specs/m15_e3_financial_risk_catalog_dev.json"
ONTOLOGY = REPO_ROOT / "experiments/specs/m15_e3_financial_risk_ontology_dev.json"
QUESTION = "查找过去一个月与 Alice 有密切资金往来的高风险公司。"


def test_deterministic_intake_compiles_typed_holes_and_constraints() -> None:
    intake = DeterministicSemanticIntake.from_path(INTAKE)

    first = intake.compile(QUESTION)
    second = intake.compile(QUESTION)

    assert first.to_dict() == second.to_dict()
    assert [item.kind for item in first.program.holes] == [
        SemanticHoleKind.ENTITY,
        SemanticHoleKind.PREDICATE,
        SemanticHoleKind.TYPE,
    ]
    assert [item.mention for item in first.program.holes] == [
        "Alice",
        "密切资金往来",
        "高风险公司",
    ]
    constraints = [
        item
        for operator in first.program.operators
        for item in operator.constraints
    ]
    assert [item.policy for item in constraints] == [
        ConstraintPolicy.HARD,
        ConstraintPolicy.HARD,
        ConstraintPolicy.RELAXABLE,
    ]
    assert len(hard_constraints_sha256(first.program)) == 64
    assert first.to_dict()["external_calls"] == 0
    assert first.to_dict()["native_query_text_emitted"] is False


def test_intake_uses_longest_declared_entity_phrase() -> None:
    intake = DeterministicSemanticIntake.from_path(INTAKE)

    result = intake.compile(
        "查找过去一个月与 Alice Smith 有密切资金往来的高风险公司。"
    )

    assert result.program.holes[0].mention == "Alice Smith"
    assert result.phrase_matches[0].declared_phrase == "Alice Smith"


def test_intake_fails_closed_when_required_phrase_is_missing() -> None:
    intake = DeterministicSemanticIntake.from_path(INTAKE)

    with pytest.raises(SemanticIntakeError, match="one-month-window"):
        intake.compile("查找 Alice 有密切资金往来的高风险公司。")


def test_intake_rejects_native_query_fields(tmp_path: Path) -> None:
    payload = json.loads(INTAKE.read_text(encoding="utf-8"))
    payload["operators"][0]["parameters"]["cypher"] = "MATCH (n) RETURN n"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SemanticIntakeError, match="native query text"):
        DeterministicSemanticIntake.from_path(path)


def test_intake_rejects_hash_mismatch_and_symlink(tmp_path: Path) -> None:
    with pytest.raises(SemanticIntakeError, match="SHA-256 mismatch"):
        DeterministicSemanticIntake.from_path(INTAKE, expected_sha256="0" * 64)

    link = tmp_path / "intake-link.json"
    link.symlink_to(INTAKE)
    with pytest.raises(SemanticIntakeError, match="regular file"):
        DeterministicSemanticIntake.from_path(link)


def test_end_to_end_intake_uses_catalog_ontology_and_explicit_user() -> None:
    result = run_semantic_intake(
        question=QUESTION,
        intake_path=INTAKE,
        catalog_path=CATALOG,
        ontology_path=ONTOLOGY,
        user_selections={"person-identity": "person:alice-smith"},
        user_source_id="test-explicit-user",
    )

    state = result["goal_state"]
    assert state["status"] == GoalStatus.SUCCEEDED.value
    assert result["cost"] == {
        "tool_calls": 5,
        "external_calls": 1,
        "llm_calls": 0,
        "catalog_artifact_reads": 3,
        "ontology_artifact_reads": 1,
    }
    assert len(result["execution_memory"]) == 5
    output = state["output"]
    assert output["hard_constraints_preserved"] is True
    assert output["resolved_entity_bindings"] == {
        "person-identity": "person:alice-smith"
    }
    assert output["resolved_entity_bindings_hard"] is True
    assert len(output["resolution_commit_sha256"]) == 64
    candidate_sets = {item["hole_id"]: item for item in output["candidate_sets"]}
    assert candidate_sets["transfer-predicate"]["candidate_ids"] == [
        "predicate:transferred_to",
        "predicate:paid_to",
    ]
    assert candidate_sets["company-risk-type"]["candidate_ids"] == [
        "type:HighRiskCompany"
    ]
    assert output["llm_calls"] == 0
    assert output["ontology_calls"] == 1
    assert result["claim_boundary"]["paper_result"] is False
    assert all(len(value) == 64 for value in result["artifacts"].values())


def test_intake_blocks_at_entity_without_explicit_user_authority() -> None:
    result = run_semantic_intake(
        question=QUESTION,
        intake_path=INTAKE,
        catalog_path=CATALOG,
        ontology_path=ONTOLOGY,
    )

    state = result["goal_state"]
    assert state["status"] == GoalStatus.BLOCKED.value
    assert state["tool_calls"] == 1
    assert "requires user clarification" in state["message"]
    assert result["cost"]["llm_calls"] == 0
    assert result["cost"]["ontology_artifact_reads"] == 0
