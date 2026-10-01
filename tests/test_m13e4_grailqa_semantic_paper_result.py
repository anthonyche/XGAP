from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from xgap.experiments.grailqa_semantic_paper_protocol import (
    AUTHOR_SELECTION_SCHEMA_VERSION,
    DEFAULT_PROTOCOL_PATH,
)
from xgap.experiments.grailqa_semantic_paper_result import (
    GrailQASemanticPaperResultError,
    PAPER_RESULT_SCHEMA_VERSION,
    admit_grailqa_semantic_paper_result,
    main,
    validate_grailqa_semantic_paper_result,
)
from xgap.experiments.hashing import content_hash


ROOT = Path(__file__).resolve().parents[1]


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _selection(protocol: dict[str, object]) -> dict[str, object]:
    decisions = {
        item["decision_id"]: item["recommended_value"]
        for item in protocol["author_decisions"]
    }
    body: dict[str, object] = {
        "schema_version": AUTHOR_SELECTION_SCHEMA_VERSION,
        "protocol_sha256": content_hash(protocol),
        "authority_source_id": "author:test:semantic-paper-v1",
        "decisions": decisions,
    }
    return {**body, "selection_sha256": content_hash(body)}


def _fixture(tmp_path: Path) -> dict[str, object]:
    protocol_path = ROOT / DEFAULT_PROTOCOL_PATH
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    selection = _selection(protocol)
    selection_path = tmp_path / "author_selection.json"
    _write_json(selection_path, selection)

    run_root = tmp_path / "semantic-run"
    outcomes_path = run_root / "evaluation/query_outcomes.jsonl"
    outcomes_path.parent.mkdir(parents=True)
    outcomes_path.write_text(
        "".join(
            json.dumps({"question_id": f"question-{index:03d}"}) + "\n"
            for index in range(150)
        ),
        encoding="utf-8",
    )
    outcome_sha256 = _file_sha256(outcomes_path)
    source_run_sha256 = "a" * 64
    commit = "e" * 40
    manifest_body: dict[str, object] = {
        "schema_version": "m13e4-grailqa-semantic-paper-run-v2",
        "status": "success",
        "run_id": "grailqa-semantic-paper-test-v1",
        "runner_commit": commit,
        "protocol_sha256": content_hash(protocol),
        "author_selection_sha256": selection["selection_sha256"],
        "execution_request_sha256": "b" * 64,
        "preexecution_admission_sha256": "c" * 64,
        "execution_authority_sha256": "d" * 64,
        "outcome_ledger_sha256": outcome_sha256,
        "source_run_sha256": source_run_sha256,
        "question_count": 150,
        "selection_uses_gold": False,
        "failures_retained": True,
        "gold_opened_after_all_inference": True,
        "inference_seal_written_before_gold_open": True,
        "automatic_retries": 0,
        "backend_calls": 0,
        "native_query_text_emitted": False,
        "paper_result": False,
    }
    manifest = {
        **manifest_body,
        "run_manifest_sha256": content_hash(manifest_body),
    }
    _write_json(run_root / "run_manifest.json", manifest)
    _write_json(
        run_root / "run_status.json",
        {
            "schema_version": "m13e4-grailqa-semantic-paper-run-status-v1",
            "status": "success",
            "run_id": manifest["run_id"],
            "source_run_sha256": source_run_sha256,
            "paper_result": False,
        },
    )

    run_audit_body: dict[str, object] = {
        "schema_version": (
            "m13e4-grailqa-semantic-paper-run-evidence-audit-v1"
        ),
        "success": True,
        "check_count": 401,
        "failed_check_ids": [],
        "run_tree_mutated": False,
        "expected_commit": commit,
        "source_run_sha256": source_run_sha256,
        "preexecution_admission_sha256": manifest[
            "preexecution_admission_sha256"
        ],
        "external_call_counts": {
            "llm_calls": 150,
            "repair_calls": 0,
            "backend_calls": 0,
            "ontology_service_calls": 0,
        },
        "claim_boundary": {
            "independent_run_reconstruction": True,
            "contains_new_measurements": False,
            "promotes_to_paper_result": False,
            "paper_result": False,
        },
        "paper_result": False,
    }
    run_audit = {
        **run_audit_body,
        "audit_sha256": content_hash(run_audit_body),
    }
    run_audit_path = tmp_path / "run_audit.json"
    _write_json(run_audit_path, run_audit)

    population = {
        "frozen_query_count": 150,
        "reporting_query_count": 150,
        "primary_inferential_query_count": 150,
        "jointly_prompt_reachable_query_count": 50,
        "inferential_unit": "query",
        "repetitions_used_as_independent_units": False,
    }
    analysis_body: dict[str, object] = {
        "schema_version": "m13e4-grailqa-semantic-analysis-v1",
        "protocol_sha256": content_hash(protocol),
        "author_selection_sha256": selection["selection_sha256"],
        "source_run_sha256": source_run_sha256,
        "outcome_ledger_sha256": outcome_sha256,
        "selected_decisions": selection["decisions"],
        "population": population,
        "primary": {"query_count": 150, "xgap_correct": 90},
        "all_query_sensitivity": {"query_count": 150},
        "jointly_prompt_reachable_stratum": {"query_count": 50},
        "secondary": {"candidate_recall_at_3": 0.8},
        "failures": {"policy": "no_imputation", "counts": {}},
        "system_cost": {"external_calls": 150},
        "claim_boundary": {
            "postinference_gold_used_for_evaluation_only": True,
            "backend_calls_made_by_analyzer": 0,
            "llm_calls_made_by_analyzer": 0,
            "ontology_service_calls_made_by_analyzer": 0,
            "independent_evidence_audit_required": True,
            "paper_result": False,
        },
        "automatic_retries": 0,
        "paper_result": False,
    }
    analysis = {
        **analysis_body,
        "analysis_sha256": content_hash(analysis_body),
    }
    analysis_path = tmp_path / "analysis.json"
    _write_json(analysis_path, analysis)

    pilot_path = ROOT / "datasets/grailqa_pilot_v1/pilot_ids.json"
    analysis_audit_body: dict[str, object] = {
        "schema_version": (
            "m13e4-grailqa-semantic-analysis-evidence-audit-v1"
        ),
        "success": True,
        "check_count": 307,
        "failed_check_ids": [],
        "input_artifacts_mutated": False,
        "analysis_exact_match": True,
        "expected_source_run_sha256": source_run_sha256,
        "input_sha256": {
            "outcome_ledger": outcome_sha256,
            "analysis": _file_sha256(analysis_path),
            "protocol": _file_sha256(protocol_path),
            "author_selection": _file_sha256(selection_path),
            "pilot_selection": _file_sha256(pilot_path),
        },
        "external_call_counts": {
            "backend_calls": 0,
            "llm_calls": 0,
            "ontology_service_calls": 0,
        },
        "claim_boundary": {
            "independent_analysis_reconstruction": True,
            "contains_new_measurements": False,
            "full_150_run_authorized": False,
            "paper_result": False,
        },
        "paper_result": False,
    }
    analysis_audit = {
        **analysis_audit_body,
        "audit_sha256": content_hash(analysis_audit_body),
    }
    analysis_audit_path = tmp_path / "analysis_audit.json"
    _write_json(analysis_audit_path, analysis_audit)
    return {
        "run_root": run_root,
        "run_audit_path": run_audit_path,
        "analysis_path": analysis_path,
        "analysis_audit_path": analysis_audit_path,
        "protocol_path": protocol_path,
        "selection_path": selection_path,
        "commit": commit,
    }


def _admit(paths: dict[str, object]) -> dict[str, object]:
    return admit_grailqa_semantic_paper_result(
        run_root=paths["run_root"],
        run_audit_path=paths["run_audit_path"],
        analysis_path=paths["analysis_path"],
        analysis_audit_path=paths["analysis_audit_path"],
        protocol_path=paths["protocol_path"],
        author_selection_path=paths["selection_path"],
        repo_root=ROOT,
        expected_commit=str(paths["commit"]),
    )


def test_result_requires_both_independent_audits(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    before = {
        path.relative_to(paths["run_root"]).as_posix(): path.read_bytes()
        for path in Path(paths["run_root"]).rglob("*")
        if path.is_file()
    }
    result = _admit(paths)

    assert result["schema_version"] == PAPER_RESULT_SCHEMA_VERSION
    assert result["paper_result"] is True
    assert result["population"]["frozen_query_count"] == 150
    assert result["claim_boundary"]["query_level_inference"] is True
    assert validate_grailqa_semantic_paper_result(result) == result
    after = {
        path.relative_to(paths["run_root"]).as_posix(): path.read_bytes()
        for path in Path(paths["run_root"]).rglob("*")
        if path.is_file()
    }
    assert after == before


def test_failed_run_audit_cannot_be_promoted(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    audit_path = Path(paths["run_audit_path"])
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["success"] = False
    body = {key: value for key, value in audit.items() if key != "audit_sha256"}
    audit["audit_sha256"] = content_hash(body)
    _write_json(tmp_path / "failed_run_audit.json", audit)
    paths["run_audit_path"] = tmp_path / "failed_run_audit.json"

    with pytest.raises(GrailQASemanticPaperResultError, match="run audit"):
        _admit(paths)


def test_analysis_audit_identity_drift_fails_closed(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    audit_path = Path(paths["analysis_audit_path"])
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["input_sha256"]["analysis"] = "0" * 64
    body = {key: value for key, value in audit.items() if key != "audit_sha256"}
    audit["audit_sha256"] = content_hash(body)
    _write_json(tmp_path / "drifted_analysis_audit.json", audit)
    paths["analysis_audit_path"] = tmp_path / "drifted_analysis_audit.json"

    with pytest.raises(GrailQASemanticPaperResultError, match="analysis audit"):
        _admit(paths)


def test_author_selection_must_bind_the_exact_protocol(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    selection_path = Path(paths["selection_path"])
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    selection["protocol_sha256"] = "0" * 64
    body = {
        key: value for key, value in selection.items() if key != "selection_sha256"
    }
    selection["selection_sha256"] = content_hash(body)
    _write_json(tmp_path / "drifted_selection.json", selection)
    paths["selection_path"] = tmp_path / "drifted_selection.json"

    with pytest.raises(GrailQASemanticPaperResultError, match="semantic analysis"):
        _admit(paths)


def test_cli_is_write_once(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    output = tmp_path / "paper_result.json"
    args = [
        "admit",
        "--run-root",
        str(paths["run_root"]),
        "--run-audit",
        str(paths["run_audit_path"]),
        "--analysis",
        str(paths["analysis_path"]),
        "--analysis-audit",
        str(paths["analysis_audit_path"]),
        "--protocol",
        str(paths["protocol_path"]),
        "--author-selection",
        str(paths["selection_path"]),
        "--repo-root",
        str(ROOT),
        "--expected-commit",
        str(paths["commit"]),
        "--output",
        str(output),
    ]
    assert main(args) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["paper_result"] is True
    assert main(args) == 2


def test_rehashed_paper_result_claim_drift_is_rejected(tmp_path: Path) -> None:
    result = _admit(_fixture(tmp_path))
    changed = copy.deepcopy(result)
    changed["claim_boundary"]["generalization_beyond_frozen_grailqa_population"] = True
    body = {
        key: value for key, value in changed.items() if key != "paper_result_sha256"
    }
    changed["paper_result_sha256"] = content_hash(body)

    with pytest.raises(GrailQASemanticPaperResultError, match="invalid"):
        validate_grailqa_semantic_paper_result(changed)


def test_cwru_submission_and_finalization_are_dependency_gated() -> None:
    submit = ROOT / "scripts/server/submit_grailqa_semantic_paper_pipeline.sh"
    finalize = ROOT / "scripts/slurm/finalize_grailqa_semantic_paper.sbatch"
    for path in (submit, finalize):
        result = subprocess.run(
            ("bash", "-n", str(path)),
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    submit_text = submit.read_text(encoding="utf-8")
    assert "afterok:$PAPER_JOB_ID" in submit_text
    assert "run_grailqa_semantic_paper.sbatch" in submit_text
    assert "finalize_grailqa_semantic_paper.sbatch" in submit_text
    assert "automatic_retries" in submit_text
    assert "paper_result\": False" in submit_text

    finalize_text = finalize.read_text(encoding="utf-8")
    assert "#SBATCH --gres" not in finalize_text
    assert "grailqa_semantic_paper_run_evidence" in finalize_text
    assert "grailqa_semantic_analysis_evidence" in finalize_text
    assert "grailqa_semantic_paper_result admit" in finalize_text
    assert finalize_text.index("grailqa_semantic_paper_run_evidence") < (
        finalize_text.index("grailqa_semantic_analysis")
    )
    assert finalize_text.index("grailqa_semantic_analysis_evidence") < (
        finalize_text.index("grailqa_semantic_paper_result admit")
    )
