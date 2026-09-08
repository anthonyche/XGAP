from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import xgap.experiments.grailqa_semantic_analysis as producer
from xgap.experiments.grailqa_semantic_analysis import (
    QUERY_OUTCOME_SCHEMA_VERSION,
)
from xgap.experiments.grailqa_semantic_analysis_evidence import (
    AUDIT_SCHEMA_VERSION,
    GrailQASemanticAnalysisEvidenceError,
    audit_grailqa_semantic_analysis,
    main,
)
from xgap.experiments.grailqa_semantic_paper_protocol import (
    AUTHOR_SELECTION_SCHEMA_VERSION,
    DEFAULT_PROTOCOL_PATH,
)
from xgap.experiments.hashing import content_hash


ROOT = Path(__file__).resolve().parents[1]
SOURCE_RUN_SHA256 = "e" * 64


def _decisions() -> dict[str, str]:
    return {
        "primary_reporting_population": (
            "all_150_plus_joint_reachability_stratum"
        ),
        "primary_epsilon": "0.1",
        "primary_comparator": "model_confidence_top1_same_candidate_set",
        "inference_failure_estimand": "all_queries_failures_count_incorrect",
        "interactive_clarification_role": "oracle_upper_bound_only",
    }


def _author_selection() -> dict[str, object]:
    protocol = json.loads((ROOT / DEFAULT_PROTOCOL_PATH).read_text(encoding="utf-8"))
    body: dict[str, object] = {
        "schema_version": AUTHOR_SELECTION_SCHEMA_VERSION,
        "protocol_sha256": content_hash(protocol),
        "authority_source_id": "author:anthonyche:grailqa-semantic-audit-test-v1",
        "decisions": _decisions(),
    }
    return {**body, "selection_sha256": content_hash(body)}


def _candidate(
    question_id: str,
    index: int,
    *,
    confidence: float,
    deviation: float,
    reference_supported: bool,
) -> dict[str, object]:
    return {
        "candidate_id": f"{question_id}:candidate-{index}",
        "candidate_index": index,
        "confidence": confidence,
        "validation_ok": True,
        "grounded": True,
        "hard_constraints_preserved": True,
        "semantic_admissible": True,
        "semantic_deviation": deviation,
        "equivalence_key": f"{question_id}:class-{index}",
        "reference_supported": reference_supported,
    }


def _rows(question_ids: list[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, question_id in enumerate(question_ids):
        rows.append(
            {
                "schema_version": QUERY_OUTCOME_SCHEMA_VERSION,
                "question_id": question_id,
                "split": "train" if index < 120 else "dev",
                "q_bucket": 13 if index < 83 else 19 if index < 139 else 25,
                "jointly_prompt_reachable": index % 2 == 0,
                "provider": {
                    "completed": True,
                    "external_calls": 1,
                    "repair_calls": 0,
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "latency_ms": 10.0,
                },
                "failure_category": None,
                "candidates": [
                    _candidate(
                        question_id,
                        1,
                        confidence=0.4,
                        deviation=0.0,
                        reference_supported=True,
                    ),
                    _candidate(
                        question_id,
                        2,
                        confidence=0.9,
                        deviation=0.2,
                        reference_supported=False,
                    ),
                ],
            }
        )
    return rows


def _write_package(tmp_path: Path) -> dict[str, Path]:
    pilot = json.loads(
        (ROOT / "datasets/grailqa_pilot_v1/pilot_ids.json").read_text(
            encoding="utf-8"
        )
    )
    outcomes = tmp_path / "outcomes.jsonl"
    outcomes.write_text(
        "".join(
            json.dumps(row, sort_keys=True) + "\n"
            for row in _rows(list(pilot["question_ids"]))
        ),
        encoding="utf-8",
    )
    selection = tmp_path / "author-selection.json"
    selection.write_text(
        json.dumps(_author_selection(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    analysis = tmp_path / "analysis.json"
    assert (
        producer.main(
            [
                "--outcomes",
                str(outcomes),
                "--protocol",
                str(ROOT / DEFAULT_PROTOCOL_PATH),
                "--author-selection",
                str(selection),
                "--repo-root",
                str(ROOT),
                "--source-run-sha256",
                SOURCE_RUN_SHA256,
                "--output",
                str(analysis),
            ]
        )
        == 0
    )
    return {"outcomes": outcomes, "selection": selection, "analysis": analysis}


def _audit(paths: dict[str, Path], **overrides: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "outcomes_path": paths["outcomes"],
        "analysis_path": paths["analysis"],
        "protocol_path": ROOT / DEFAULT_PROTOCOL_PATH,
        "author_selection_path": paths["selection"],
        "repo_root": ROOT,
        "source_run_sha256": SOURCE_RUN_SHA256,
    }
    arguments.update(overrides)
    return audit_grailqa_semantic_analysis(**arguments)


def test_auditor_independently_reconstructs_exact_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _write_package(tmp_path)
    before = {
        key: hashlib.sha256(path.read_bytes()).hexdigest()
        for key, path in paths.items()
    }
    monkeypatch.setattr(
        producer,
        "analyze_grailqa_semantic_outcomes",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("not independent")),
    )

    audit = _audit(paths)

    assert audit["schema_version"] == AUDIT_SCHEMA_VERSION
    assert audit["success"] is True
    assert audit["failed_check_ids"] == []
    assert audit["analysis_exact_match"] is True
    assert audit["input_artifacts_mutated"] is False
    assert audit["external_call_counts"] == {
        "backend_calls": 0,
        "llm_calls": 0,
        "ontology_service_calls": 0,
    }
    assert audit["claim_boundary"] == {
        "independent_analysis_reconstruction": True,
        "contains_new_measurements": False,
        "full_150_run_authorized": False,
        "paper_result": False,
    }
    assert audit["paper_result"] is False
    assert audit["audit_sha256"] == content_hash(
        {key: value for key, value in audit.items() if key != "audit_sha256"}
    )
    assert before == {
        key: hashlib.sha256(path.read_bytes()).hexdigest()
        for key, path in paths.items()
    }


def test_recomputed_self_hash_does_not_hide_analysis_tampering(tmp_path: Path) -> None:
    paths = _write_package(tmp_path)
    analysis = json.loads(paths["analysis"].read_text(encoding="utf-8"))
    analysis["primary"]["xgap"]["correct_count"] -= 1
    analysis["analysis_sha256"] = content_hash(
        {key: value for key, value in analysis.items() if key != "analysis_sha256"}
    )
    paths["analysis"].write_text(
        json.dumps(analysis, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = _audit(paths)

    assert audit["success"] is False
    assert audit["analysis_exact_match"] is False
    assert audit["failed_check_ids"] == ["analysis.exact_reconstruction"]
    detail = next(
        check["detail"]
        for check in audit["checks"]
        if check["check_id"] == "analysis.exact_reconstruction"
    )
    assert set(detail) == {
        "expected_analysis_sha256",
        "observed_analysis_sha256",
    }


def test_ledger_tampering_is_detected_without_mutating_inputs(tmp_path: Path) -> None:
    paths = _write_package(tmp_path)
    rows = paths["outcomes"].read_text(encoding="utf-8").splitlines()
    first = json.loads(rows[0])
    first["candidates"][0]["confidence"] = 0.3
    rows[0] = json.dumps(first, sort_keys=True)
    paths["outcomes"].write_text("\n".join(rows) + "\n", encoding="utf-8")

    audit = _audit(paths)

    assert audit["success"] is False
    assert audit["input_artifacts_mutated"] is False
    assert "analysis.outcome_ledger_sha256" in audit["failed_check_ids"]
    assert "analysis.exact_reconstruction" in audit["failed_check_ids"]


def test_population_corruption_fails_closed_as_reconstruction_error(
    tmp_path: Path,
) -> None:
    paths = _write_package(tmp_path)
    rows = paths["outcomes"].read_text(encoding="utf-8").splitlines()
    duplicate = json.loads(rows[-1])
    duplicate["question_id"] = json.loads(rows[0])["question_id"]
    rows[-1] = json.dumps(duplicate, sort_keys=True)
    paths["outcomes"].write_text("\n".join(rows) + "\n", encoding="utf-8")

    audit = _audit(paths)

    assert audit["success"] is False
    assert audit["analysis_exact_match"] is False
    assert "reconstruction.error" in audit["failed_check_ids"]
    assert "analysis.exact_reconstruction" in audit["failed_check_ids"]


def test_source_run_identity_is_reconstructed(tmp_path: Path) -> None:
    paths = _write_package(tmp_path)

    audit = _audit(paths, source_run_sha256="f" * 64)

    assert audit["success"] is False
    assert "analysis.source_run_sha256" in audit["failed_check_ids"]
    assert "analysis.exact_reconstruction" in audit["failed_check_ids"]


def test_cli_writes_once_and_returns_failure_for_invalid_analysis(
    tmp_path: Path,
) -> None:
    paths = _write_package(tmp_path)
    output = tmp_path / "audit.json"
    arguments = [
        "--outcomes",
        str(paths["outcomes"]),
        "--analysis",
        str(paths["analysis"]),
        "--protocol",
        str(ROOT / DEFAULT_PROTOCOL_PATH),
        "--author-selection",
        str(paths["selection"]),
        "--repo-root",
        str(ROOT),
        "--source-run-sha256",
        SOURCE_RUN_SHA256,
        "--output",
        str(output),
    ]

    assert main(arguments) == 0
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["success"] is True
    assert main(arguments) == 2

    invalid_output = tmp_path / "invalid-audit.json"
    analysis = json.loads(paths["analysis"].read_text(encoding="utf-8"))
    analysis["paper_result"] = True
    paths["analysis"].write_text(
        json.dumps(analysis, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    invalid_arguments = copy.copy(arguments)
    invalid_arguments[-1] = str(invalid_output)
    assert main(invalid_arguments) == 1
    assert json.loads(invalid_output.read_text(encoding="utf-8"))["success"] is False


def test_symlinked_evidence_is_rejected(tmp_path: Path) -> None:
    paths = _write_package(tmp_path)
    link = tmp_path / "analysis-link.json"
    link.symlink_to(paths["analysis"])

    with pytest.raises(
        GrailQASemanticAnalysisEvidenceError,
        match="regular non-symbolic-link",
    ):
        _audit(paths, analysis_path=link)
