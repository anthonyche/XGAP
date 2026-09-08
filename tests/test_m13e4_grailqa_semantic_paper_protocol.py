from __future__ import annotations

import json
from pathlib import Path

import pytest

from xgap.experiments.grailqa_semantic_paper_protocol import (
    AUTHOR_SELECTION_SCHEMA_VERSION,
    DEFAULT_PROTOCOL_PATH,
    GrailQASemanticPaperProtocolError,
    READINESS_SCHEMA_VERSION,
    compile_grailqa_semantic_paper_readiness,
    main,
)
from xgap.experiments.hashing import content_hash


ROOT = Path(__file__).resolve().parents[1]
READINESS_ARTIFACT = ROOT / (
    "experiments/artifacts/"
    "grailqa_semantic_paper_protocol_readiness_draft_v1.json"
)


def _protocol() -> dict[str, object]:
    return json.loads((ROOT / DEFAULT_PROTOCOL_PATH).read_text(encoding="utf-8"))


def _refreeze(protocol: dict[str, object]) -> None:
    protocol["freeze_hash"] = content_hash(
        {key: value for key, value in protocol.items() if key != "freeze_hash"}
    )


def _author_selection(protocol: dict[str, object]) -> dict[str, object]:
    decisions = {
        item["decision_id"]: item["recommended_value"]
        for item in protocol["author_decisions"]
    }
    body: dict[str, object] = {
        "schema_version": AUTHOR_SELECTION_SCHEMA_VERSION,
        "protocol_sha256": content_hash(protocol),
        "authority_source_id": "author:anthonyche:grailqa-semantic-v1",
        "decisions": decisions,
    }
    return {**body, "selection_sha256": content_hash(body)}


def test_result_blind_draft_exposes_real_semantic_blockers() -> None:
    readiness = compile_grailqa_semantic_paper_readiness(
        ROOT / DEFAULT_PROTOCOL_PATH,
        repo_root=ROOT,
    ).to_dict()

    assert readiness["schema_version"] == READINESS_SCHEMA_VERSION
    assert readiness["gates"] == {
        "result_blind_protocol_structurally_valid": True,
        "all_author_decisions_selected": False,
        "author_approved": False,
        "preflight18_independently_audited_and_reviewed": False,
        "paper_runner_and_analysis_ready": False,
        "full_150_run_authorized": False,
    }
    assert readiness["bound_artifacts"] == {
        "dataset_id": "grailqa_pilot_v1",
        "pilot_question_count": 150,
        "model_bundle_hash": (
            "ed9fa4db9f0981e7307ef7323415159fdeb5117c8ab308218d1c8d282360bd6e"
        ),
        "preflight_question_count": 18,
        "preflight_full_run_permitted": False,
    }
    assert len(readiness["source_artifacts"]) == 6
    assert all(item["verified"] for item in readiness["source_artifacts"])
    assert len(readiness["next_author_decisions"]) == 5
    assert "author_approval.pending" in readiness["blockers"]
    assert "preflight18.author_review.pending" in readiness["blockers"]
    assert "execution_authority.full_150.missing" in readiness["blockers"]
    assert readiness["claim_boundary"] == {
        "artifact_class": "result_blind_semantic_protocol_readiness",
        "contains_measurements": False,
        "backend_calls_made": 0,
        "llm_calls_made": 0,
        "ontology_service_calls_made": 0,
        "author_decision_inferred": False,
        "paper_result": False,
    }
    assert readiness["automatic_retries"] == 0
    assert readiness["paper_result"] is False
    assert len(readiness["readiness_sha256"]) == 64


def test_draft_compilation_is_deterministic() -> None:
    first = compile_grailqa_semantic_paper_readiness(
        ROOT / DEFAULT_PROTOCOL_PATH, repo_root=ROOT
    ).to_dict()
    second = compile_grailqa_semantic_paper_readiness(
        ROOT / DEFAULT_PROTOCOL_PATH, repo_root=ROOT
    ).to_dict()
    assert first == second
    assert json.loads(READINESS_ARTIFACT.read_text(encoding="utf-8")) == first


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda value: value["analysis_design"].update(
                {"inferential_unit": "generation"}
            ),
            "analysis boundary",
        ),
        (
            lambda value: value["evaluation_isolation"].update(
                {"gold_forbidden_during_inference": False}
            ),
            "evaluation isolation",
        ),
        (
            lambda value: value["failure_policy"].update(
                {"automatic_retries": 1}
            ),
            "failure policy",
        ),
        (
            lambda value: value["methods"].update(
                {"shared_candidate_generation": False}
            ),
            "method boundary",
        ),
        (
            lambda value: value.update({"paper_result": True}),
            "paper_result=false",
        ),
    ],
)
def test_scientific_boundaries_fail_closed(mutator, message: str) -> None:
    changed = _protocol()
    mutator(changed)
    _refreeze(changed)
    with pytest.raises(GrailQASemanticPaperProtocolError, match=message):
        compile_grailqa_semantic_paper_readiness(changed, repo_root=ROOT)


def test_source_and_dataset_drift_fail_closed() -> None:
    changed = _protocol()
    changed["source_artifacts"][0]["sha256"] = "0" * 64
    _refreeze(changed)
    with pytest.raises(GrailQASemanticPaperProtocolError, match="source artifact changed"):
        compile_grailqa_semantic_paper_readiness(changed, repo_root=ROOT)

    changed = _protocol()
    changed["dataset_contract"]["selection_uses_xgap_outcomes"] = True
    _refreeze(changed)
    with pytest.raises(GrailQASemanticPaperProtocolError, match="dataset boundary"):
        compile_grailqa_semantic_paper_readiness(changed, repo_root=ROOT)


def test_author_selection_approves_choices_but_never_authorizes_live_run() -> None:
    protocol = _protocol()
    selection = _author_selection(protocol)
    readiness = compile_grailqa_semantic_paper_readiness(
        protocol,
        repo_root=ROOT,
        author_selection=selection,
    ).to_dict()

    assert readiness["gates"]["all_author_decisions_selected"] is True
    assert readiness["gates"]["author_approved"] is True
    assert readiness["gates"]["full_150_run_authorized"] is False
    assert readiness["next_author_decisions"] == []
    assert readiness["author_selection_sha256"] == selection["selection_sha256"]
    assert "execution_authority.full_150.missing" in readiness["blockers"]


def test_invalid_author_selection_is_rejected() -> None:
    protocol = _protocol()
    selection = _author_selection(protocol)
    selection["decisions"]["primary_epsilon"] = "after_results"
    body = {key: value for key, value in selection.items() if key != "selection_sha256"}
    selection["selection_sha256"] = content_hash(body)
    with pytest.raises(GrailQASemanticPaperProtocolError, match="not allowed"):
        compile_grailqa_semantic_paper_readiness(
            protocol,
            repo_root=ROOT,
            author_selection=selection,
        )

    selection = _author_selection(protocol)
    selection["selection_sha256"] = "0" * 64
    with pytest.raises(GrailQASemanticPaperProtocolError, match="hash mismatch"):
        compile_grailqa_semantic_paper_readiness(
            protocol,
            repo_root=ROOT,
            author_selection=selection,
        )


def test_cli_writes_once_and_makes_no_external_calls(tmp_path: Path) -> None:
    output = tmp_path / "readiness.json"
    assert main(
        [
            "--protocol",
            str(ROOT / DEFAULT_PROTOCOL_PATH),
            "--repo-root",
            str(ROOT),
            "--output",
            str(output),
        ]
    ) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["claim_boundary"]["llm_calls_made"] == 0
    assert payload["claim_boundary"]["backend_calls_made"] == 0
    assert payload["paper_result"] is False
    assert main(
        [
            "--protocol",
            str(ROOT / DEFAULT_PROTOCOL_PATH),
            "--repo-root",
            str(ROOT),
            "--output",
            str(output),
        ]
    ) == 2
