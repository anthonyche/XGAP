from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from xgap.experiments.grailqa_semantic_analysis import (
    ANALYSIS_SCHEMA_VERSION,
    QUERY_OUTCOME_SCHEMA_VERSION,
    GrailQASemanticAnalysisError,
    analyze_grailqa_semantic_outcomes,
    main,
)
from xgap.experiments.grailqa_semantic_paper_protocol import (
    AUTHOR_SELECTION_SCHEMA_VERSION,
    DEFAULT_PROTOCOL_PATH,
)
from xgap.experiments.hashing import content_hash


ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 64


def _decisions() -> dict[str, str]:
    return {
        "primary_reporting_population": (
            "all_150_plus_joint_reachability_stratum"
        ),
        "primary_epsilon": "0.1",
        "primary_comparator": (
            "model_confidence_top1_same_candidate_set"
        ),
        "inference_failure_estimand": "all_queries_failures_count_incorrect",
        "interactive_clarification_role": "oracle_upper_bound_only",
    }


def _distribution() -> dict[str, object]:
    return {
        "split": {"train": 120, "dev": 30},
        "Q": {"13": 83, "19": 56, "25": 11},
    }


def _provider(*, completed: bool = True) -> dict[str, object]:
    return {
        "completed": completed,
        "external_calls": 1,
        "repair_calls": 0,
        "input_tokens": 100 if completed else 0,
        "output_tokens": 20 if completed else 0,
        "latency_ms": 10.0,
    }


def _candidate(
    candidate_id: str,
    index: int,
    *,
    confidence: float,
    reference_supported: bool,
    deviation: float | None,
    admissible: bool = True,
    hard: bool = True,
    equivalence_key: str | None = None,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "candidate_index": index,
        "confidence": confidence,
        "validation_ok": True,
        "grounded": True,
        "hard_constraints_preserved": hard,
        "semantic_admissible": admissible,
        "semantic_deviation": deviation,
        "equivalence_key": equivalence_key or candidate_id,
        "reference_supported": reference_supported,
    }


def _outcomes(question_ids: list[str] | None = None) -> list[dict[str, object]]:
    ids = question_ids or [f"q{index:03d}" for index in range(150)]
    rows: list[dict[str, object]] = []
    for index, question_id in enumerate(ids):
        if index < 60:
            candidates = [
                _candidate(
                    f"{question_id}:reference",
                    1,
                    confidence=0.4,
                    reference_supported=True,
                    deviation=0.0,
                    equivalence_key=f"{question_id}:reference-class",
                ),
                _candidate(
                    f"{question_id}:high-confidence",
                    2,
                    confidence=0.9,
                    reference_supported=False,
                    deviation=0.2,
                ),
                _candidate(
                    f"{question_id}:equivalent",
                    3,
                    confidence=0.8,
                    reference_supported=False,
                    deviation=0.05,
                    equivalence_key=f"{question_id}:reference-class",
                ),
            ]
            failure = None
            provider = _provider()
        elif index < 90:
            candidates = [
                _candidate(
                    f"{question_id}:reference",
                    1,
                    confidence=0.9,
                    reference_supported=True,
                    deviation=0.0,
                ),
                _candidate(
                    f"{question_id}:other",
                    2,
                    confidence=0.2,
                    reference_supported=False,
                    deviation=0.05,
                ),
            ]
            failure = None
            provider = _provider()
        elif index < 120:
            candidates = [
                _candidate(
                    f"{question_id}:reference",
                    1,
                    confidence=0.9,
                    reference_supported=True,
                    deviation=None,
                    admissible=False,
                ),
                _candidate(
                    f"{question_id}:admissible-wrong",
                    2,
                    confidence=0.3,
                    reference_supported=False,
                    deviation=0.0,
                ),
            ]
            failure = "semantic_bound_rejection"
            provider = _provider()
        elif index < 140:
            candidates = []
            failure = "provider_failure"
            provider = _provider(completed=False)
        else:
            candidates = [
                _candidate(
                    f"{question_id}:hard-violation",
                    1,
                    confidence=0.95,
                    reference_supported=False,
                    deviation=None,
                    admissible=False,
                    hard=False,
                ),
                _candidate(
                    f"{question_id}:reference",
                    2,
                    confidence=0.4,
                    reference_supported=True,
                    deviation=0.0,
                ),
            ]
            failure = None
            provider = _provider()
        rows.append(
            {
                "schema_version": QUERY_OUTCOME_SCHEMA_VERSION,
                "question_id": question_id,
                "split": "train" if index < 120 else "dev",
                "q_bucket": 13 if index < 83 else 19 if index < 139 else 25,
                "jointly_prompt_reachable": index < 50,
                "provider": provider,
                "failure_category": failure,
                "candidates": candidates,
            }
        )
    return rows


def _analyze(
    rows: list[dict[str, object]],
    *,
    decisions: dict[str, str] | None = None,
) -> dict[str, object]:
    return analyze_grailqa_semantic_outcomes(
        rows,
        expected_question_ids=[f"q{index:03d}" for index in range(150)],
        expected_distribution=_distribution(),
        selected_decisions=decisions or _decisions(),
        protocol_sha256=SHA,
        author_selection_sha256="b" * 64,
        source_run_sha256="c" * 64,
        outcome_ledger_sha256="d" * 64,
    )


def _author_selection() -> dict[str, object]:
    protocol = json.loads((ROOT / DEFAULT_PROTOCOL_PATH).read_text(encoding="utf-8"))
    body: dict[str, object] = {
        "schema_version": AUTHOR_SELECTION_SCHEMA_VERSION,
        "protocol_sha256": content_hash(protocol),
        "authority_source_id": "author:anthonyche:grailqa-semantic-analysis-v1",
        "decisions": _decisions(),
    }
    return {**body, "selection_sha256": content_hash(body)}


def test_query_level_analysis_is_paired_deterministic_and_cardinality_matched() -> None:
    first = _analyze(_outcomes())
    second = _analyze(_outcomes())

    assert first == second
    assert first["schema_version"] == ANALYSIS_SCHEMA_VERSION
    assert first["population"] == {
        "frozen_query_count": 150,
        "reporting_query_count": 150,
        "primary_inferential_query_count": 150,
        "jointly_prompt_reachable_query_count": 50,
        "inferential_unit": "query",
        "repetitions_used_as_independent_units": False,
    }
    assert first["method_contract"] == {
        "shared_generated_validated_grounded_candidate_set": True,
        "xgap_primary_choice": "rank_1_of_bounded_frontier",
        "comparator_primary_choice": (
            "model_confidence_top1_same_candidate_set"
        ),
        "primary_return_cardinality_matched": True,
        "any_frontier_member_correct_is_not_primary_correctness": True,
    }
    assert first["primary"]["xgap"]["correct_count"] == 100
    assert first["primary"]["comparator"]["correct_count"] == 70
    assert first["primary"]["primary_test"]["left_only"] == 60
    assert first["primary"]["primary_test"]["right_only"] == 30
    assert first["primary"]["primary_test"]["discordant_count"] == 90
    assert first["primary"]["confidence_interval"]["resamples"] == 10_000
    assert first["primary"]["confidence_interval"]["seed"] == (
        "m13e4-grailqa-semantic-ci-v1"
    )
    assert first["jointly_prompt_reachable_stratum"]["query_count"] == 50
    assert first["provider_completer_diagnostic"]["query_count"] == 130
    assert first["per_query"][0]["xgap_frontier_candidate_ids"] == [
        "q000:reference"
    ]
    assert first["per_query"][0]["xgap_correct"] is True
    assert first["per_query"][0]["comparator_correct"] is False
    assert first["analysis_sha256"] == content_hash(
        {key: value for key, value in first.items() if key != "analysis_sha256"}
    )
    assert first["paper_result"] is False


def test_failures_count_as_incorrect_and_remain_visible() -> None:
    analysis = _analyze(_outcomes())

    assert analysis["primary"]["query_count"] == 150
    assert analysis["all_query_sensitivity"]["query_count"] == 150
    assert analysis["failures"]["policy"] == "no_imputation"
    assert analysis["failures"]["counts"] == {
        "none": 100,
        "provider_failure": 20,
        "semantic_bound_rejection": 30,
    }
    assert analysis["secondary"]["candidate_recall_at_3"] == pytest.approx(
        130 / 150
    )
    assert analysis["secondary"][
        "generated_hard_constraint_violation_count"
    ] == 10
    assert analysis["secondary"][
        "generated_hard_constraint_violation_query_count"
    ] == 10
    assert analysis["secondary"][
        "generated_hard_constraint_violation_query_rate"
    ] == pytest.approx(10 / 150)
    assert analysis["system_cost"] == {
        "external_calls": 150,
        "repair_calls": 0,
        "input_tokens": 13_000,
        "output_tokens": 2_600,
        "latency_ms": 1_500.0,
        "completed_queries": 130,
    }


def test_available_case_estimand_changes_only_the_declared_primary() -> None:
    decisions = _decisions()
    decisions["inference_failure_estimand"] = (
        "available_case_primary_with_all_query_sensitivity"
    )
    analysis = _analyze(_outcomes(), decisions=decisions)

    assert analysis["population"]["primary_inferential_query_count"] == 130
    assert analysis["primary"]["query_count"] == 130
    assert analysis["all_query_sensitivity"]["query_count"] == 150


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda rows: rows.append(copy.deepcopy(rows[0])),
            "duplicate IDs",
        ),
        (
            lambda rows: rows.pop(),
            "exact frozen 150-query population",
        ),
        (
            lambda rows: rows[0].update({"split": "dev"}),
            "split distribution changed",
        ),
        (
            lambda rows: rows[0].update({"q_bucket": 19}),
            "Q-bucket distribution changed",
        ),
        (
            lambda rows: rows[0]["candidates"].append(
                _candidate(
                    "q000:fourth",
                    4,
                    confidence=0.1,
                    reference_supported=False,
                    deviation=0.0,
                )
            ),
            "candidate count exceeds",
        ),
        (
            lambda rows: rows[0]["candidates"][1].update(
                {"candidate_id": rows[0]["candidates"][0]["candidate_id"]}
            ),
            "candidate IDs are not unique",
        ),
        (
            lambda rows: rows[0]["candidates"][0].update(
                {"validation_ok": False}
            ),
            "cannot ground a type-invalid candidate",
        ),
        (
            lambda rows: rows[0]["candidates"][0].update(
                {"hard_constraints_preserved": False}
            ),
            "semantic admission bypassed",
        ),
        (
            lambda rows: rows[90]["candidates"][0].update(
                {"semantic_deviation": 0.1}
            ),
            "inadmissible candidate has a finite deviation",
        ),
        (
            lambda rows: rows[0]["provider"].update(
                {"external_calls": 2, "repair_calls": 0}
            ),
            "call accounting diverged",
        ),
        (
            lambda rows: rows[120]["provider"].update({"completed": True}),
            "completed provider call must emit",
        ),
        (
            lambda rows: rows[0].update({"unexpected": True}),
            "fields changed",
        ),
    ],
)
def test_population_and_candidate_contracts_fail_closed(mutator, message: str) -> None:
    rows = _outcomes()
    mutator(rows)
    with pytest.raises(GrailQASemanticAnalysisError, match=message):
        _analyze(rows)


def test_retrieval_miss_spends_no_provider_call() -> None:
    rows = _outcomes()
    rows[120]["failure_category"] = "retrieval_miss"
    rows[120]["provider"].update(
        {
            "external_calls": 0,
            "latency_ms": 0.0,
        }
    )
    analysis = _analyze(rows)
    assert analysis["failures"]["counts"]["retrieval_miss"] == 1

    rows[120]["provider"]["external_calls"] = 1
    with pytest.raises(GrailQASemanticAnalysisError, match="cannot spend"):
        _analyze(rows)


@pytest.mark.parametrize(
    "failure",
    (
        "generation_miss",
        "entity_grounding_failure",
        "relation_grounding_failure",
    ),
)
def test_completed_local_failure_may_retain_an_empty_candidate_set(
    failure: str,
) -> None:
    rows = _outcomes()
    rows[0]["failure_category"] = failure
    rows[0]["candidates"] = []

    analysis = _analyze(rows)

    assert analysis["failures"]["counts"][failure] == 1


def test_cli_binds_exact_ledger_writes_once_and_makes_no_external_calls(
    tmp_path: Path,
) -> None:
    pilot = json.loads(
        (ROOT / "datasets/grailqa_pilot_v1/pilot_ids.json").read_text(
            encoding="utf-8"
        )
    )
    rows = _outcomes(list(pilot["question_ids"]))
    outcomes_path = tmp_path / "outcomes.jsonl"
    outcomes_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(
        json.dumps(_author_selection(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "analysis.json"
    arguments = [
        "--outcomes",
        str(outcomes_path),
        "--protocol",
        str(ROOT / DEFAULT_PROTOCOL_PATH),
        "--author-selection",
        str(selection_path),
        "--repo-root",
        str(ROOT),
        "--source-run-sha256",
        "e" * 64,
        "--output",
        str(output),
    ]

    assert main(arguments) == 0
    analysis = json.loads(output.read_text(encoding="utf-8"))
    assert analysis["outcome_ledger_sha256"] == hashlib.sha256(
        outcomes_path.read_bytes()
    ).hexdigest()
    assert analysis["claim_boundary"] == {
        "postinference_gold_used_for_evaluation_only": True,
        "backend_calls_made_by_analyzer": 0,
        "llm_calls_made_by_analyzer": 0,
        "ontology_service_calls_made_by_analyzer": 0,
        "independent_evidence_audit_required": True,
        "paper_result": False,
    }
    assert main(arguments) == 2


def test_invalid_hash_and_author_decision_fail_closed() -> None:
    rows = _outcomes()
    with pytest.raises(GrailQASemanticAnalysisError, match="not a SHA-256"):
        analyze_grailqa_semantic_outcomes(
            rows,
            expected_question_ids=[f"q{index:03d}" for index in range(150)],
            expected_distribution=_distribution(),
            selected_decisions=_decisions(),
            protocol_sha256="not-a-hash",
            author_selection_sha256="b" * 64,
            source_run_sha256="c" * 64,
            outcome_ledger_sha256="d" * 64,
        )

    decisions = _decisions()
    decisions["primary_epsilon"] = "after_results"
    with pytest.raises(GrailQASemanticAnalysisError, match="selection is invalid"):
        _analyze(rows, decisions=decisions)
