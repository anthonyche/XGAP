from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest

from xgap.experiments.grailqa_preflight import _evaluate_preflight
from xgap.experiments.grailqa_preflight_evidence import audit_grailqa_preflight_run
from xgap.experiments.grailqa_semantic_pilot import _failure
from xgap.experiments.hashing import content_hash


ROOT = Path(__file__).resolve().parents[1]
ENDPOINT_FIXTURES = runpy.run_path(
    str(ROOT / "tests/test_m13e3b4_relation_endpoint_grounding.py")
)


def _case(tmp_path: Path):
    question_ids = ("masked", "grounding", "provider", "equivalence", "success")
    reference = ENDPOINT_FIXTURES["_pattern"]("OUT")
    states = []
    for question_id in question_ids:
        states.append({
            "question": {"question_id": question_id},
            "candidates": [],
            "semantic_scores": [],
            "failure": None,
            "api_call_completed": question_id != "provider",
        })
    states[0]["failure"] = _failure(
        "masked", "relation_grounding_failure", "Query anchor was not visible"
    )
    states[1]["failure"] = _failure(
        "grounding", "relation_grounding_failure", "Missing relation-hop component"
    )
    states[2]["failure"] = _failure(
        "provider", "malformed_output", "Recorded provider rejection: invalid JSON"
    )
    for index, state in enumerate(states[3:], start=3):
        pattern = copy.deepcopy(reference)
        if index == 3:
            pattern["expr"]["edge"]["label"] = "r.other"
        state["candidates"] = [{
            "question_id": state["question"]["question_id"],
            "candidate_id": "candidate-1",
            "pattern_query": pattern,
            "semantic_admissible": True,
            "semantic_deviation": 0.0,
        }]
        state["semantic_scores"] = [{
            "question_id": state["question"]["question_id"],
            "candidate_id": "candidate-1",
            "measurement": {"admissible": True, "finite_value": 0.0},
        }]
    pilot = tmp_path / "pilot"
    pilot.mkdir()
    references = [
        {"question_id": question_id, "pattern_query": reference}
        for question_id in question_ids
    ]
    reachability = [
        {
            "question_id": question_id,
            "first_unreachable_stage": (
                "reference_not_prompt_visible" if question_id == "masked" else None
            ),
            "deployed_prompt": {"joint": {"reachable": question_id != "masked"}},
        }
        for question_id in question_ids
    ]
    for path, rows in (
        (pilot / "reference_interpretations.jsonl", references),
        (tmp_path / "reachability.jsonl", reachability),
    ):
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    spec = SimpleNamespace(data={
        "pilot_root": "pilot", "epsilon_values": [0.0, 0.1, 0.25, 0.5, 0.75, 1.0]
    })
    readiness = {
        "reachability_rows_path": str(tmp_path / "reachability.jsonl"),
        "catalog_coverage": {"question_count": 5},
        "prompt_reachability": {"question_count": 4},
    }
    return states, spec, readiness


@pytest.mark.parametrize(
    ("question_id", "expected_category", "original_category", "message"),
    [
        ("masked", "reference_not_prompt_visible", "relation_grounding_failure",
         "Query anchor was not visible"),
        ("grounding", "generated_semantic_miss", "relation_grounding_failure",
         "Missing relation-hop component"),
        ("provider", "malformed_output", "malformed_output",
         "Recorded provider rejection: invalid JSON"),
    ],
)
def test_original_failure_survives_frozen_classification(
    tmp_path: Path, question_id: str, expected_category: str,
    original_category: str, message: str,
) -> None:
    states, spec, readiness = _case(tmp_path)

    result = _evaluate_preflight(states, spec, tmp_path, readiness)

    row = next(row for row in result["failures"] if row["question_id"] == question_id)
    assert row["schema_version"] == "m13e1-stage-aware-failure-v1"
    assert row["category"] == expected_category
    assert row["original_inference_failure"] == {
        "schema_version": "m13d-first-failure-v1",
        "question_id": question_id,
        "category": original_category,
        "message": message,
    }


def test_absent_inference_failure_stays_absent_and_success_adds_no_row(tmp_path: Path) -> None:
    states, spec, readiness = _case(tmp_path)

    result = _evaluate_preflight(states, spec, tmp_path, readiness)

    row = next(row for row in result["failures"] if row["question_id"] == "equivalence")
    assert row == {
        "schema_version": "m13e1-stage-aware-failure-v1",
        "question_id": "equivalence",
        "category": "equivalence_failure",
    }
    assert "success" not in {row["question_id"] for row in result["failures"]}


def test_retained_failure_is_an_independent_shallow_copy(tmp_path: Path) -> None:
    states, spec, readiness = _case(tmp_path)
    before = copy.deepcopy(states)

    result = _evaluate_preflight(states, spec, tmp_path, readiness)

    assert states == before
    original = states[0]["failure"]
    diagnostic = result["failures"][0]["original_inference_failure"]
    assert diagnostic is not original
    diagnostic["message"] = "Changed only in returned diagnostic"
    assert original["message"] == "Query anchor was not visible"
    original["category"] = "entity_grounding_failure"
    assert diagnostic["category"] == "relation_grounding_failure"


def test_all_legacy_outputs_match_pre_diagnostic_snapshot(tmp_path: Path) -> None:
    states, spec, readiness = _case(tmp_path)

    result = _evaluate_preflight(states, spec, tmp_path, readiness)

    for row in result["failures"]:
        row.pop("original_inference_failure", None)
    # Snapshot from the committed evaluator before additive failure retention.
    # This binds all legacy failure rows, metrics, candidates, and semantic/component rows.
    assert content_hash(result) == "5479e5bb7560869e307a15406a26fa57d3d35661d91591816bd00dfdb9ec8de9"


def test_existing_auditor_accepts_additive_producer_diagnostic(tmp_path: Path) -> None:
    fixtures = runpy.run_path(str(ROOT / "tests/test_m13e3b5_preflight_evidence.py"))
    root = fixtures["_fixture_run"](tmp_path)
    baseline = audit_grailqa_preflight_run(
        run_root=root, repo_root=ROOT, expected_commit=fixtures["COMMIT"]
    )
    assert baseline["success"] is True
    failures_path = root / fixtures["RESULT_RELATIVE_ROOT"] / "failures.jsonl"
    failures = [json.loads(line) for line in failures_path.read_text().splitlines()]
    failures[0]["original_inference_failure"] = _failure(
        failures[0]["question_id"], "relation_grounding_failure", "Retained diagnostic"
    )
    fixtures["_write_jsonl"](failures_path, failures)
    # This fixture models a newly produced run with a freshly captured inventory.
    fixtures["_inventory"](root)
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}

    audit = audit_grailqa_preflight_run(
        run_root=root, repo_root=ROOT, expected_commit=fixtures["COMMIT"]
    )

    assert audit["success"] is True
    assert audit["check_count"] == baseline["check_count"]
    assert audit["diagnostic"] == baseline["diagnostic"]
    assert audit["failed_check_ids"] == []
    assert audit["run_tree_mutated"] is False
    assert {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()} == before
