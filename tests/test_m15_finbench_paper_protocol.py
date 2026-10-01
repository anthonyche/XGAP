from __future__ import annotations

import json
from pathlib import Path

import pytest

from xgap.experiments.m15_finbench_paper_protocol import (
    DEFAULT_AUTHOR_SELECTION_PATH,
    DEFAULT_PROTOCOL_PATH,
    FINBENCH_PAPER_READINESS_SCHEMA_VERSION,
    FinBenchPaperProtocolError,
    apply_finbench_paper_protocol_author_selection,
    compile_finbench_paper_protocol_readiness,
    main,
    write_finbench_paper_protocol_readiness,
)


ROOT = Path(__file__).resolve().parents[1]
READINESS_ARTIFACT = ROOT / (
    "experiments/artifacts/"
    "m15_finbench_paper_protocol_readiness_draft_v1.json"
)


def _protocol() -> dict[str, object]:
    return json.loads((ROOT / DEFAULT_PROTOCOL_PATH).read_text(encoding="utf-8"))


def test_result_blind_draft_exposes_every_real_promotion_blocker() -> None:
    readiness = compile_finbench_paper_protocol_readiness(
        ROOT / DEFAULT_PROTOCOL_PATH,
        repo_root=ROOT,
    ).to_dict()

    assert readiness["schema_version"] == FINBENCH_PAPER_READINESS_SCHEMA_VERSION
    assert readiness["gates"] == {
        "result_blind_protocol_structurally_valid": True,
        "all_author_decisions_selected": False,
        "author_approved": False,
        "development_evidence_verified": False,
        "physical_implementation_ready": False,
        "physical_confirmatory_run_authorized": False,
        "paper_experiment_stack_ready": False,
    }
    assert len(readiness["source_artifacts"]) == 4
    assert readiness["author_selection_sha256"] is None
    assert all(item["verified"] for item in readiness["source_artifacts"])
    assert len(readiness["next_author_decisions"]) == 9
    assert (
        "author_decision.confirmatory_population.unselected"
        in readiness["physical_confirmatory_blockers"]
    )
    assert (
        "author_decision.semantic_track.unselected"
        not in readiness["physical_confirmatory_blockers"]
    )
    assert (
        "author_decision.semantic_track.unselected"
        in readiness["paper_experiment_blockers"]
    )
    assert (
        "development_evidence.sf0_1_family_campaign_audit.unbound"
        in readiness["physical_confirmatory_blockers"]
    )
    assert readiness["development_evidence_receipts"] == []
    assert readiness["claim_boundary"] == {
        "artifact_class": "result_blind_paper_protocol_readiness",
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


def test_draft_is_deterministic() -> None:
    first = compile_finbench_paper_protocol_readiness(
        ROOT / DEFAULT_PROTOCOL_PATH,
        repo_root=ROOT,
    ).to_dict()
    second = compile_finbench_paper_protocol_readiness(
        ROOT / DEFAULT_PROTOCOL_PATH,
        repo_root=ROOT,
    ).to_dict()
    assert first == second
    assert json.loads(READINESS_ARTIFACT.read_text(encoding="utf-8")) == first


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda value: value["population_design"].update(
                {"sampling_must_be_answer_independent": False}
            ),
            "population protections",
        ),
        (
            lambda value: value["methods"].update(
                {"current_query_profile_calls_for_family_memory": 1}
            ),
            "method boundary",
        ),
        (
            lambda value: value["analysis_design"].update(
                {"secondary_multiplicity": "none"}
            ),
            "analysis integrity",
        ),
        (
            lambda value: value["failure_policy"].update(
                {"query_timeout_is_not_replacement_eligible": False}
            ),
            "failure policy",
        ),
        (
            lambda value: value.update({"paper_result": True}),
            "paper_result=false",
        ),
    ],
)
def test_integrity_boundaries_fail_closed(mutator, message: str) -> None:
    changed = _protocol()
    mutator(changed)
    with pytest.raises(FinBenchPaperProtocolError, match=message):
        compile_finbench_paper_protocol_readiness(changed, repo_root=ROOT)


def test_source_hash_drift_and_invalid_author_choice_are_rejected() -> None:
    changed = _protocol()
    changed["source_artifacts"][0]["sha256"] = "0" * 64
    with pytest.raises(FinBenchPaperProtocolError, match="source artifact changed"):
        compile_finbench_paper_protocol_readiness(changed, repo_root=ROOT)

    changed = _protocol()
    changed["author_decisions"][0]["selected_value"] = "after_seeing_results"
    with pytest.raises(FinBenchPaperProtocolError, match="is not allowed"):
        compile_finbench_paper_protocol_readiness(changed, repo_root=ROOT)


def test_author_approval_binds_all_selected_choices_and_subject_hash() -> None:
    selected = _protocol()
    for decision in selected["author_decisions"]:
        decision["selected_value"] = decision["recommended_value"]
    pending = compile_finbench_paper_protocol_readiness(
        selected, repo_root=ROOT
    ).to_dict()
    assert pending["gates"]["all_author_decisions_selected"] is True
    assert pending["gates"]["author_approved"] is False

    selected["approval"] = {
        "status": "approved",
        "authority_source_id": "author:anthonyche:paper-protocol-v1",
        "approved_subject_sha256": pending["approval_subject_sha256"],
    }
    approved = compile_finbench_paper_protocol_readiness(
        selected, repo_root=ROOT
    ).to_dict()
    assert approved["gates"]["author_approved"] is True
    assert approved["gates"]["physical_confirmatory_run_authorized"] is False
    assert all(
        not blocker.startswith("author_")
        for blocker in approved["physical_confirmatory_blockers"]
    )

    selected["approval"]["approved_subject_sha256"] = "0" * 64
    with pytest.raises(FinBenchPaperProtocolError, match="does not bind"):
        compile_finbench_paper_protocol_readiness(selected, repo_root=ROOT)


def test_explicit_option_a_selection_is_hash_bound_and_still_not_run_authority() -> None:
    selected = apply_finbench_paper_protocol_author_selection(
        ROOT / DEFAULT_PROTOCOL_PATH,
        ROOT / DEFAULT_AUTHOR_SELECTION_PATH,
    )
    readiness = compile_finbench_paper_protocol_readiness(
        ROOT / DEFAULT_PROTOCOL_PATH,
        repo_root=ROOT,
        author_selection=ROOT / DEFAULT_AUTHOR_SELECTION_PATH,
    ).to_dict()

    assert [
        item["selected_value"] for item in selected["author_decisions"]
    ] == [item["recommended_value"] for item in selected["author_decisions"]]
    assert selected["approval"]["status"] == "approved"
    assert readiness["author_selection_sha256"] == (
        "d2bc5980ed61e1e4c8472c6dc12223179267f7083d67df8b98ee0388c0a6aa1e"
    )
    assert readiness["gates"]["all_author_decisions_selected"] is True
    assert readiness["gates"]["author_approved"] is True
    assert readiness["gates"]["physical_confirmatory_run_authorized"] is False
    assert readiness["next_author_decisions"] == []

    tampered = json.loads(
        (ROOT / DEFAULT_AUTHOR_SELECTION_PATH).read_text(encoding="utf-8")
    )
    tampered["decisions"]["training_repetitions_per_plan"] = "4"
    with pytest.raises(FinBenchPaperProtocolError, match="hash mismatch"):
        apply_finbench_paper_protocol_author_selection(
            ROOT / DEFAULT_PROTOCOL_PATH,
            tampered,
        )


def test_physical_approval_does_not_require_semantic_or_external_choice() -> None:
    selected = _protocol()
    for decision in selected["author_decisions"][:7]:
        decision["selected_value"] = decision["recommended_value"]
    pending = compile_finbench_paper_protocol_readiness(
        selected, repo_root=ROOT
    ).to_dict()
    selected["approval"] = {
        "status": "approved",
        "authority_source_id": "author:anthonyche:physical-protocol-v1",
        "approved_subject_sha256": pending["approval_subject_sha256"],
    }

    approved = compile_finbench_paper_protocol_readiness(
        selected, repo_root=ROOT
    ).to_dict()

    assert approved["gates"]["author_approved"] is True
    assert approved["gates"]["all_author_decisions_selected"] is False
    assert not any(
        blocker.startswith("author_decision.semantic_track")
        or blocker.startswith("author_decision.external_validation")
        for blocker in approved["physical_confirmatory_blockers"]
    )
    assert "author_decision.semantic_track.unselected" in approved[
        "paper_experiment_blockers"
    ]


def test_evidence_bindings_refuse_symlink_before_audit_replay(
    tmp_path: Path,
) -> None:
    target = tmp_path / "bindings.json"
    target.write_text("{}\n", encoding="utf-8")
    link = tmp_path / "bindings-link.json"
    link.symlink_to(target)
    with pytest.raises(FinBenchPaperProtocolError, match="non-symbolic-link"):
        compile_finbench_paper_protocol_readiness(
            ROOT / DEFAULT_PROTOCOL_PATH,
            repo_root=ROOT,
            evidence_bindings=link,
        )


def test_writer_and_cli_are_no_overwrite(tmp_path: Path, capsys) -> None:
    readiness = compile_finbench_paper_protocol_readiness(
        ROOT / DEFAULT_PROTOCOL_PATH,
        repo_root=ROOT,
    )
    output = tmp_path / "readiness.json"
    write_finbench_paper_protocol_readiness(readiness, output)
    assert json.loads(output.read_text(encoding="utf-8")) == readiness.to_dict()
    with pytest.raises(FileExistsError):
        write_finbench_paper_protocol_readiness(readiness, output)

    cli_output = tmp_path / "cli-readiness.json"
    assert (
        main(
            [
                "--protocol",
                str(ROOT / DEFAULT_PROTOCOL_PATH),
                "--repo-root",
                str(ROOT),
                "--output",
                str(cli_output),
            ]
        )
        == 0
    )
    assert json.loads(cli_output.read_text(encoding="utf-8"))[
        "paper_result"
    ] is False
    assert "\"status\": \"success\"" in capsys.readouterr().out
