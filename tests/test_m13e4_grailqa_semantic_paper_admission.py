from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess

import pytest

from xgap.experiments.grailqa_semantic_paper_admission import (
    CATALOG_AUDIT_SCHEMA_VERSION,
    PREEXECUTION_ADMISSION_SCHEMA_VERSION,
    PREFLIGHT_AUDIT_SCHEMA_VERSION,
    GrailQASemanticPaperAdmissionError,
    build_grailqa_preflight_author_review,
    build_grailqa_semantic_author_selection,
    main,
    validate_grailqa_preflight_author_review,
    validate_grailqa_semantic_preexecution_admission,
)
from xgap.experiments.grailqa_semantic_paper_protocol import (
    DEFAULT_PROTOCOL_PATH,
    compile_grailqa_semantic_paper_readiness,
)
from xgap.experiments.hashing import content_hash


ROOT = Path(__file__).resolve().parents[1]


def _catalog_audit() -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": CATALOG_AUDIT_SCHEMA_VERSION,
        "audited_at": "2026-09-08T00:00:00+00:00",
        "catalog_root": "/catalog",
        "expected_builder_commit": "1" * 40,
        "catalog_hash": "2" * 64,
        "reachability_audit_hash": "3" * 64,
        "question_count": 150,
        "check_count": 1,
        "failed_check_ids": [],
        "checks": [],
        "run_tree_mutated": False,
        "source_verification_boundary": {
            "source_manifest_sha256": "4" * 64,
            "source_inventory_bound": True,
            "freebase_bytes_rescanned_by_auditor": 0,
        },
        "external_call_counts": {
            "llm_calls": 0,
            "backend_calls": 0,
            "ontology_service_calls": 0,
        },
        "claim_boundary": {
            "independent_catalog_reconstruction": True,
            "catalog_construction_gold_blind": True,
            "reachability_uses_gold_for_evaluation_only": True,
            "authorizes_model_execution": False,
            "paper_result": False,
        },
        "success": True,
        "paper_result": False,
    }
    return {**body, "audit_sha256": content_hash(body)}


def _preflight_audit() -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": PREFLIGHT_AUDIT_SCHEMA_VERSION,
        "created_at": "2026-09-08T00:00:00+00:00",
        "run_root": "/preflight",
        "expected_commit": "5" * 40,
        "success": True,
        "check_count": 1,
        "failed_check_ids": [],
        "run_tree_mutated": False,
        "diagnostic": {},
        "claim_boundary": {
            "development_preflight_only": True,
            "paper_result": False,
            "full_150_run_authorized": False,
            "backend_execution": False,
            "jointly_reachable_subset_reported_separately": True,
        },
        "checks": [],
    }
    return {**body, "audit_sha256": content_hash(body)}


def _admission() -> dict[str, object]:
    preflight = _preflight_audit()
    review = build_grailqa_preflight_author_review(
        preflight_audit=preflight,
        authority_source_id="author:test:review-v1",
        decision="accept_exact_preflight_without_parameter_tuning",
    )
    body: dict[str, object] = {
        "schema_version": PREEXECUTION_ADMISSION_SCHEMA_VERSION,
        "protocol_sha256": "6" * 64,
        "author_selection_sha256": "7" * 64,
        "selected_decisions": {
            "primary_reporting_population": "all_150_plus_joint_reachability_stratum",
            "primary_epsilon": "0.1",
            "primary_comparator": "model_confidence_top1_same_candidate_set",
            "inference_failure_estimand": "all_queries_failures_count_incorrect",
            "interactive_clarification_role": "oracle_upper_bound_only",
        },
        "catalog_hash": "2" * 64,
        "reachability_audit_hash": "3" * 64,
        "catalog_audit": _catalog_audit(),
        "preflight_audit": preflight,
        "author_preflight_review": review,
        "gates": {
            "catalog_independently_audited": True,
            "preflight_independently_audited": True,
            "preflight_explicitly_reviewed_by_author": True,
            "parameter_tuning_from_preflight_forbidden": True,
            "all_five_scientific_decisions_explicit": True,
        },
        "external_call_counts": {
            "llm_calls": 0,
            "backend_calls": 0,
            "ontology_service_calls": 0,
        },
        "full_150_execution_authorized": False,
        "paper_result": False,
    }
    return {**body, "preexecution_admission_sha256": content_hash(body)}


def test_review_and_admission_bind_exact_independent_evidence() -> None:
    preflight = _preflight_audit()
    review = build_grailqa_preflight_author_review(
        preflight_audit=preflight,
        authority_source_id="author:test:review-v1",
        decision="accept_exact_preflight_without_parameter_tuning",
    )

    assert validate_grailqa_preflight_author_review(
        preflight_audit=preflight, author_review=review
    ) == review
    assert validate_grailqa_semantic_preexecution_admission(_admission()) == _admission()


def test_author_selection_requires_five_explicit_allowed_choices(
    tmp_path: Path,
) -> None:
    decisions = {
        "primary_reporting_population": "all_150_plus_joint_reachability_stratum",
        "primary_epsilon": "0.1",
        "primary_comparator": "model_confidence_top1_same_candidate_set",
        "inference_failure_estimand": "all_queries_failures_count_incorrect",
        "interactive_clarification_role": "oracle_upper_bound_only",
    }
    selection = build_grailqa_semantic_author_selection(
        protocol_path=ROOT / DEFAULT_PROTOCOL_PATH,
        repo_root=ROOT,
        authority_source_id="author:test:semantic-selection-v1",
        decisions=decisions,
    )
    readiness = compile_grailqa_semantic_paper_readiness(
        ROOT / DEFAULT_PROTOCOL_PATH,
        repo_root=ROOT,
        author_selection=selection,
    ).to_dict()
    assert readiness["gates"]["author_approved"] is True
    assert selection["decisions"] == decisions

    output = tmp_path / "author-selection.json"
    assert main(
        [
            "select",
            "--protocol",
            str(ROOT / DEFAULT_PROTOCOL_PATH),
            "--repo-root",
            str(ROOT),
            "--authority-source-id",
            "author:test:semantic-selection-v1",
            "--primary-reporting-population",
            decisions["primary_reporting_population"],
            "--primary-epsilon",
            decisions["primary_epsilon"],
            "--primary-comparator",
            decisions["primary_comparator"],
            "--inference-failure-estimand",
            decisions["inference_failure_estimand"],
            "--interactive-clarification-role",
            decisions["interactive_clarification_role"],
            "--output",
            str(output),
        ]
    ) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == selection
    assert main(
        [
            "select",
            "--protocol",
            str(ROOT / DEFAULT_PROTOCOL_PATH),
            "--repo-root",
            str(ROOT),
            "--authority-source-id",
            "author:test:semantic-selection-v1",
            "--primary-reporting-population",
            decisions["primary_reporting_population"],
            "--primary-epsilon",
            decisions["primary_epsilon"],
            "--primary-comparator",
            decisions["primary_comparator"],
            "--inference-failure-estimand",
            decisions["inference_failure_estimand"],
            "--interactive-clarification-role",
            decisions["interactive_clarification_role"],
            "--output",
            str(output),
        ]
    ) == 2

    changed = dict(decisions)
    changed.pop("primary_epsilon")
    with pytest.raises(
        GrailQASemanticPaperAdmissionError, match="exactly the five"
    ):
        build_grailqa_semantic_author_selection(
            protocol_path=ROOT / DEFAULT_PROTOCOL_PATH,
            repo_root=ROOT,
            authority_source_id="author:test:semantic-selection-v1",
            decisions=changed,
        )


def test_review_cannot_authorize_execution_or_float_to_another_audit() -> None:
    preflight = _preflight_audit()
    review = build_grailqa_preflight_author_review(
        preflight_audit=preflight,
        authority_source_id="author:test:review-v1",
        decision="accept_exact_preflight_without_parameter_tuning",
    )
    changed = copy.deepcopy(review)
    changed["full_150_execution_authorized"] = True
    body = {
        key: value
        for key, value in changed.items()
        if key != "preflight_review_sha256"
    }
    changed["preflight_review_sha256"] = content_hash(body)

    with pytest.raises(GrailQASemanticPaperAdmissionError, match="exact preflight"):
        validate_grailqa_preflight_author_review(
            preflight_audit=preflight, author_review=changed
        )


def test_admission_fails_closed_on_independent_audit_drift() -> None:
    admission = _admission()
    catalog = copy.deepcopy(admission["catalog_audit"])
    assert isinstance(catalog, dict)
    catalog["success"] = False
    catalog_body = {
        key: value for key, value in catalog.items() if key != "audit_sha256"
    }
    catalog["audit_sha256"] = content_hash(catalog_body)
    admission["catalog_audit"] = catalog
    body = {
        key: value
        for key, value in admission.items()
        if key != "preexecution_admission_sha256"
    }
    admission["preexecution_admission_sha256"] = content_hash(body)

    with pytest.raises(GrailQASemanticPaperAdmissionError, match="catalog audit"):
        validate_grailqa_semantic_preexecution_admission(admission)


def test_preflight_audit_wrapper_is_cpu_only_and_fail_closed() -> None:
    path = ROOT / "scripts/slurm/audit_grailqa_semantic_preflight_v2.sbatch"
    result = subprocess.run(
        ("bash", "-n", str(path)),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    text = path.read_text(encoding="utf-8")
    assert "#SBATCH --cpus-per-task=2" in text
    assert "#SBATCH --mem=8G" in text
    assert "XGAP_GRAILQA_PREFLIGHT_PRODUCER_COMMIT" in text
    assert "XGAP_GRAILQA_PREFLIGHT_JOB_ID" in text
    assert (
        'DEFAULT_RUN_ROOT="$REPO_ROOT/runs/cwru-grailqa-preflight-v2-'
        '$PREFLIGHT_JOB_ID"'
    ) in text
    assert "grailqa_preflight_evidence" in text
    assert "output already exists" in text
    assert "#SBATCH --gres" not in text
    assert "vllm" not in text.casefold()
