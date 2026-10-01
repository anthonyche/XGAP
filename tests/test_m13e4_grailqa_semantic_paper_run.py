from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

import xgap.experiments.grailqa_semantic_paper_run as runner
from xgap.experiments.grailqa_semantic_analysis import (
    QUERY_OUTCOME_SCHEMA_VERSION,
)
from xgap.experiments.grailqa_semantic_paper_run import (
    EXECUTION_REQUEST_SCHEMA_VERSION,
    GrailQASemanticPaperRunError,
    build_grailqa_semantic_execution_authority,
    execute_grailqa_semantic_paper_run,
    validate_grailqa_semantic_execution_authority,
    validate_grailqa_semantic_execution_request,
)
from xgap.experiments.grailqa_semantic_paper_admission import (
    CATALOG_AUDIT_SCHEMA_VERSION,
    PREEXECUTION_ADMISSION_SCHEMA_VERSION,
    PREFLIGHT_AUDIT_SCHEMA_VERSION,
    build_grailqa_preflight_author_review,
)
from xgap.experiments.grailqa_semantic_paper_run_evidence import (
    AUDIT_SCHEMA_VERSION,
    audit_grailqa_semantic_paper_run,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.semantic import OntologyGraph


ROOT = Path(__file__).resolve().parents[1]


def _ids() -> list[str]:
    return [f"q{index:03d}" for index in range(150)]


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


def _catalog_audit() -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": CATALOG_AUDIT_SCHEMA_VERSION,
        "audited_at": "2026-09-08T00:00:00+00:00",
        "catalog_root": "/catalog",
        "expected_builder_commit": "b" * 40,
        "catalog_hash": "5" * 64,
        "reachability_audit_hash": "7" * 64,
        "question_count": 150,
        "check_count": 1,
        "failed_check_ids": [],
        "checks": [{"check_id": "fixture", "passed": True, "detail": None}],
        "run_tree_mutated": False,
        "source_verification_boundary": {
            "source_manifest_sha256": "c" * 64,
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
        "expected_commit": "d" * 40,
        "success": True,
        "check_count": 1,
        "failed_check_ids": [],
        "run_tree_mutated": False,
        "diagnostic": {
            "provider_success_count": 18,
            "provider_failure_count": 0,
            "candidate_bearing_query_count": 18,
            "matched_query_count": 10,
            "candidate_recall_is_unconfounded_by_provider_failure": True,
        },
        "claim_boundary": {
            "development_preflight_only": True,
            "paper_result": False,
            "full_150_run_authorized": False,
            "backend_execution": False,
            "jointly_reachable_subset_reported_separately": True,
        },
        "checks": [{"check_id": "fixture", "passed": True, "detail": None}],
    }
    return {**body, "audit_sha256": content_hash(body)}


def _admission() -> dict[str, object]:
    preflight = _preflight_audit()
    review = build_grailqa_preflight_author_review(
        preflight_audit=preflight,
        authority_source_id="author:test:preflight-review-v1",
        decision="accept_exact_preflight_without_parameter_tuning",
    )
    body: dict[str, object] = {
        "schema_version": PREEXECUTION_ADMISSION_SCHEMA_VERSION,
        "protocol_sha256": "2" * 64,
        "author_selection_sha256": "3" * 64,
        "selected_decisions": _decisions(),
        "catalog_hash": "5" * 64,
        "reachability_audit_hash": "7" * 64,
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


def _request() -> dict[str, object]:
    admission = _admission()
    body: dict[str, object] = {
        "schema_version": EXECUTION_REQUEST_SCHEMA_VERSION,
        "run_id": "grailqa-paper-test-v1",
        "runner_commit": "1" * 40,
        "protocol_sha256": "2" * 64,
        "author_selection_sha256": "3" * 64,
        "preexecution_admission_sha256": admission[
            "preexecution_admission_sha256"
        ],
        "selected_decisions": _decisions(),
        "population": {
            "query_count": 150,
            "question_ids_sha256": content_hash(_ids()),
            "pilot_selection_sha256": "4" * 64,
            "split_distribution": {"train": 120, "dev": 30},
            "q_distribution": {"13": 83, "19": 56, "25": 11},
        },
        "catalog": {
            "catalog_hash": "5" * 64,
            "manifest_sha256": "6" * 64,
            "question_count": 150,
            "query_local": True,
            "gold_used_for_construction": False,
        },
        "reachability": {
            "audit_hash": "7" * 64,
            "summary_sha256": "8" * 64,
            "rows_sha256": "9" * 64,
            "question_count": 150,
            "opened_by_runner_after_inference_seal": True,
        },
        "inference": {
            "model_bundle_hash": "a" * 64,
            "query_count": 150,
            "retrieval_k": 20,
            "prompt_candidates_per_slot": 4,
            "candidate_cap": 3,
            "maximum_repair_calls_per_query": 1,
            "maximum_external_calls_per_query": 2,
            "automatic_retries": 0,
            "native_query_generation": False,
            "backend_execution": False,
        },
        "evaluation_isolation": {
            "gold_forbidden_during_inference": True,
            "all_query_states_sealed_before_gold_open": True,
            "shared_candidate_set_across_methods": True,
            "failures_retained": True,
        },
        "full_150_execution_authorized": False,
        "paper_result": False,
    }
    return {**body, "execution_request_sha256": content_hash(body)}


def _authority(request: dict[str, object]) -> dict[str, object]:
    return build_grailqa_semantic_execution_authority(
        execution_request=request,
        preexecution_admission=_admission(),
        authority_source_id="author:test:semantic-paper-v1",
        decision="authorize_exact_150_query_semantic_execution",
    )


def _pattern() -> dict[str, object]:
    return {
        "path_var": "p",
        "source": {"var": "answer", "label": "type.a", "properties": {}},
        "expr": {
            "kind": "rel",
            "edge": {
                "var": "e",
                "label": "r.a",
                "direction": "OUT",
                "properties": {},
            },
        },
        "target": {"var": "anchor", "label": "type.b", "properties": {}},
        "selector": {"kind": "ALL", "k": None},
        "restrictor": "SIMPLE",
        "condition": None,
        "max_depth": None,
    }


def _ontology() -> OntologyGraph:
    return OntologyGraph(
        ontology_id="test-ontology",
        version="v1",
        classes=("type.a", "type.b"),
        relations=("r.a",),
        properties=(),
        parents={"type.a": (), "type.b": (), "r.a": ()},
        max_relaxation_hops=3,
        domain_range={"r.a": {"domain": "type.a", "range": "type.b"}},
    )


def _questions() -> list[dict[str, object]]:
    return [
        {
            "question_id": question_id,
            "text": f"Question {question_id}",
            "split": "train" if index < 120 else "dev",
        }
        for index, question_id in enumerate(_ids())
    ]


def _state(question: dict[str, object]) -> dict[str, object]:
    question_id = str(question["question_id"])
    base: dict[str, object] = {
        "schema_version": "m13d-query-state-v1",
        "question": question,
        "retrieval": {},
        "request_records": [{"request_index": 1}],
        "response_record": {
            "usage": {"input_tokens": 100, "output_tokens": 20}
        },
        "structured_response": {},
        "prompt_view": {},
        "semantic_scores": [],
        "retrieval_latency_seconds": 0.001,
        "llm_latency_seconds": 0.01,
        "deterministic_latency_seconds": 0.001,
        "repair_calls": 0,
        "provider_id": "fake-provider",
        "api_call_completed": True,
        "terminal": True,
        "failure": None,
    }
    if question_id == "q147":
        return {
            **base,
            "candidates": [],
            "failure": {
                "category": "relation_grounding_failure",
                "message": "not grounded",
            },
        }
    if question_id == "q148":
        return {
            **base,
            "candidates": [],
            "api_call_completed": False,
            "response_record": {
                "failure_category": "provider_error",
                "usage": {},
            },
            "structured_response": None,
            "failure": {"category": "malformed_output", "message": "provider"},
        }
    if question_id == "q149":
        return {
            **base,
            "candidates": [],
            "failure": {"category": "generation_miss", "message": "empty"},
        }
    return {
        **base,
        "candidates": [
            {
                "candidate_id": f"{question_id}:candidate-1",
                "pattern_query": _pattern(),
                "confidence": 0.9,
                "validation": {"ok": True},
                "grounded": True,
                "semantic_admissible": True,
                "semantic_deviation": 0.0,
            }
        ],
    }


def test_authority_is_exactly_bound_and_fails_closed_on_tampering() -> None:
    request = _request()
    authority = _authority(request)

    assert validate_grailqa_semantic_execution_request(request) == request
    assert (
        validate_grailqa_semantic_execution_authority(
            execution_request=request,
            preexecution_admission=_admission(),
            authority=authority,
        )
        == authority
    )
    changed = dict(request)
    changed["paper_result"] = True
    with pytest.raises(GrailQASemanticPaperRunError, match="request is invalid"):
        validate_grailqa_semantic_execution_request(changed)
    changed_authority = dict(authority)
    changed_authority["single_run_only"] = False
    with pytest.raises(GrailQASemanticPaperRunError, match="authority is invalid"):
        validate_grailqa_semantic_execution_authority(
            execution_request=request,
            preexecution_admission=_admission(),
            authority=changed_authority,
        )


def test_exact_150_states_are_sealed_before_any_gold_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request()
    authority = _authority(request)
    output = tmp_path / str(request["run_id"])
    questions = _questions()
    pattern = _pattern()
    observed_seals: list[str] = []

    def infer_one(**kwargs):
        return _state(dict(kwargs["question"]))

    monkeypatch.setattr(runner, "_infer_one", infer_one)

    def assert_sealed() -> None:
        seal_path = output / "inference/inference_seal.json"
        assert seal_path.is_file()
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        assert seal["question_count"] == 150
        assert seal["all_query_states_present"] is True
        assert len(seal["query_state_files"]) == 150
        assert len(list((output / "inference/query-state").glob("*.json"))) == 150
        observed_seals.append(seal["inference_seal_sha256"])

    def references_loader():
        assert_sealed()
        return [
            {"question_id": question_id, "pattern_query": pattern}
            for question_id in _ids()
        ]

    def workloads_loader():
        assert_sealed()
        return [
            {"question_id": question_id, "Q": 13}
            for question_id in _ids()
        ]

    def reachability_loader():
        assert_sealed()
        return [
            {
                "question_id": question_id,
                "deployed_prompt": {"joint": {"reachable": index % 2 == 0}},
            }
            for index, question_id in enumerate(_ids())
        ]

    manifest = execute_grailqa_semantic_paper_run(
        output_root=output,
        request=request,
        admission=_admission(),
        authority=authority,
        question_rows=questions,
        expected_ids=_ids(),
        catalog=SimpleNamespace(ontology=_ontology()),
        provider=SimpleNamespace(provider_id="fake-provider"),
        references_loader=references_loader,
        workloads_loader=workloads_loader,
        reachability_loader=reachability_loader,
        execution_environment={"host": "test"},
    )

    assert len(observed_seals) == 3
    assert len(set(observed_seals)) == 1
    assert manifest["question_count"] == 150
    assert manifest["provider_external_calls"] == 150
    assert manifest["provider_repair_calls"] == 0
    assert manifest["backend_calls"] == 0
    assert manifest["native_query_text_emitted"] is False
    assert manifest["selection_uses_gold"] is False
    assert manifest["gold_opened_after_all_inference"] is True
    assert manifest["paper_result"] is False
    outcomes = [
        json.loads(line)
        for line in (output / "evaluation/query_outcomes.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(outcomes) == 150
    assert {item["schema_version"] for item in outcomes} == {
        QUERY_OUTCOME_SCHEMA_VERSION
    }
    assert outcomes[147]["failure_category"] == "relation_grounding_failure"
    assert outcomes[148]["failure_category"] == "provider_failure"
    assert outcomes[149]["failure_category"] == "generation_miss"
    assert outcomes[148]["provider"]["completed"] is False
    assert outcomes[149]["provider"]["completed"] is True

    audit = audit_grailqa_semantic_paper_run(
        run_root=output, expected_commit="1" * 40
    )
    assert audit["schema_version"] == AUDIT_SCHEMA_VERSION
    assert audit["success"] is True
    assert audit["failed_check_ids"] == []
    assert audit["run_tree_mutated"] is False
    assert audit["external_call_counts"] == {
        "llm_calls": 150,
        "repair_calls": 0,
        "backend_calls": 0,
        "ontology_service_calls": 0,
    }
    assert audit["paper_result"] is False
    state_path = output / "inference/query-state/q000.json"
    changed_state = json.loads(state_path.read_text(encoding="utf-8"))
    changed_state["candidates"][0]["confidence"] = 0.1
    state_path.write_text(
        json.dumps(changed_state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tampered = audit_grailqa_semantic_paper_run(
        run_root=output, expected_commit="1" * 40
    )
    assert tampered["success"] is False
    assert "states.hashes" in tampered["failed_check_ids"]

    with pytest.raises(FileExistsError, match="output exists"):
        execute_grailqa_semantic_paper_run(
            output_root=output,
            request=request,
            admission=_admission(),
            authority=authority,
            question_rows=questions,
            expected_ids=_ids(),
            catalog=SimpleNamespace(ontology=_ontology()),
            provider=SimpleNamespace(provider_id="fake-provider"),
            references_loader=references_loader,
            workloads_loader=workloads_loader,
            reachability_loader=reachability_loader,
        )


def test_runner_rejects_less_than_the_frozen_population(tmp_path: Path) -> None:
    request = _request()
    with pytest.raises(GrailQASemanticPaperRunError, match="exact frozen 150"):
        execute_grailqa_semantic_paper_run(
            output_root=tmp_path / "run",
            request=request,
            admission=_admission(),
            authority=_authority(request),
            question_rows=_questions()[:-1],
            expected_ids=_ids()[:-1],
            catalog=SimpleNamespace(ontology=_ontology()),
            provider=SimpleNamespace(provider_id="fake-provider"),
            references_loader=lambda: [],
            workloads_loader=lambda: [],
            reachability_loader=lambda: [],
        )


def test_cwru_wrapper_is_frozen_authority_gated_and_syntax_valid() -> None:
    script = ROOT / "scripts/slurm/run_grailqa_semantic_paper.sbatch"
    generic = ROOT / "scripts/slurm/cwru_xgap_vllm.sbatch"
    for path in (script, generic):
        result = subprocess.run(
            ("bash", "-n", str(path)),
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    text = script.read_text(encoding="utf-8")
    assert "#SBATCH -C gpu2h100" in text
    assert "XGAP_GRAILQA_SEMANTIC_EXECUTION_AUTHORITY" in text
    assert "XGAP_GRAILQA_SEMANTIC_PREEXECUTION_ADMISSION" in text
    assert "--admission" in text
    assert "grailqa_semantic_paper_run check" in text
    assert "grailqa_semantic_paper_run run" in text
    assert "XGAP_SKIP_VLLM_STRUCTURED_SMOKE=1" in text
    assert text.index("grailqa_semantic_paper_run check") < text.index(
        "cwru_xgap_vllm.sbatch"
    )
    spec_path = ROOT / (
        "experiments/specs/"
        "grailqa_semantic_paper_run_cwru_qwen3_32b.json"
    )
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    assert spec["question_count"] == 150
    assert spec["maximum_external_calls"] == 300
    assert spec["generic_structured_smoke_calls"] == 0
    assert spec["automatic_retries"] == 0
    assert spec["backend_execution"] is False
    assert spec["paper_result"] is False
    assert spec["freeze_hash"] == content_hash(
        {key: value for key, value in spec.items() if key != "freeze_hash"}
    )
