from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.cwru_vllm import CWRUVLLMContract
from xgap.experiments.grailqa_preflight import GrailQAPreflightSpec
from xgap.experiments.grailqa_preflight_evidence import (
    AUDIT_SCHEMA_VERSION,
    RESULT_RELATIVE_ROOT,
    _recompute_metrics,
    audit_grailqa_preflight_run,
    main,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.relation_endpoints import RELATION_ENDPOINT_CONTRACT_VERSION


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = (
    ROOT / "experiments/specs/grailqa_semantic_preflight_v2_cwru_qwen3_32b.json"
)
CONTRACT_PATH = ROOT / "experiments/environments/cwru_pioneer_qwen3_32b_vllm.json"
COMMIT = "a" * 40


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(dict(row), sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inventory(root: Path) -> None:
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative in {"artifact_inventory.json", "run_status.json"}:
            continue
        files.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    _write(
        root / "artifact_inventory.json",
        {"schema_version": "m13e2-artifact-inventory-v1", "files": files},
    )
    _write(
        root / "run_status.json",
        {
            "schema_version": "m13e2-cwru-run-status-v1",
            "completed_at": "2026-09-08T00:00:00+00:00",
            "exit_code": 0,
            "status": "success",
            "artifact_count": len(files),
        },
    )


def _fixture_run(tmp_path: Path) -> Path:
    root = tmp_path / "run"
    result = root / RESULT_RELATIVE_ROOT
    external = tmp_path / "preflight18"
    spec = GrailQAPreflightSpec.load(SPEC_PATH)
    ids = spec.question_ids
    contract = CWRUVLLMContract.load(CONTRACT_PATH)
    model_bundle = ModelBundle.load(ROOT / str(spec.data["model_bundle_root"]))

    reachability_rows = [
        {
            "question_id": question_id,
            "deployed_prompt": {"joint": {"reachable": index < 5}},
            "relation_endpoint_grounding": {
                "contract_version": RELATION_ENDPOINT_CONTRACT_VERSION
            },
        }
        for index, question_id in enumerate(ids)
    ]
    _write_jsonl(external / "reachability.jsonl", reachability_rows)
    reachability_summary: dict[str, Any] = {
        "schema_version": "m13e3b4-grailqa-local-reachability-v2",
        "catalog_hash": "fixture-catalog-hash",
        "question_count": 18,
        "prompt_limit": 4,
        "summary": {
            "catalog": {"joint": {"count": 18, "ratio": 1.0}},
            "retrieval": {"joint": {"count": 10, "ratio": 10 / 18}},
            "deployed_prompt": {"joint": {"count": 5, "ratio": 5 / 18}},
        },
        "relation_endpoint_grounding": {
            "contract_version": RELATION_ENDPOINT_CONTRACT_VERSION
        },
        "artifact_hashes": {
            "reachability.jsonl": _sha256(external / "reachability.jsonl")
        },
    }
    reachability_summary["audit_hash"] = content_hash(reachability_summary)
    _write(external / "audit_summary.json", reachability_summary)

    checks = [
        {"name": "artifact_profile", "status": "pass", "detail": "query_local_e3b4"},
        {"name": "catalog_v2", "status": "pass", "detail": "fixture-catalog-hash"},
        {
            "name": "reachability_artifact",
            "status": "pass",
            "detail": reachability_summary["audit_hash"],
        },
        {"name": "reachability_rows", "status": "pass", "detail": "18 rows"},
        {"name": "artifact_profile_contract", "status": "pass", "detail": "ok"},
        {"name": "prompt_reachability_gate", "status": "pass", "detail": "ok"},
        {
            "name": "model_bundle",
            "status": "pass",
            "detail": spec.data["model_bundle_hash"],
        },
        {"name": "provider_credential", "status": "pass", "detail": "present"},
    ]
    readiness = {
        "schema_version": "m13e3b5-preflight-readiness-v3",
        "ready": True,
        "artifact_profile": "query_local_e3b4",
        "artifact_profile_contract": {
            "question_count": 18,
            "prompt_candidates_per_slot": 4,
        },
        "catalog_root": str(external),
        "reachability_root": str(external),
        "reachability_summary_path": str(external / "audit_summary.json"),
        "reachability_rows_path": str(external / "reachability.jsonl"),
        "reachability_audit_hash": reachability_summary["audit_hash"],
        "relation_endpoint_contract_version": RELATION_ENDPOINT_CONTRACT_VERSION,
        "prompt_candidates_per_slot": 4,
        "catalog_coverage": reachability_summary["summary"]["catalog"],
        "retrieval_coverage": reachability_summary["summary"]["retrieval"],
        "prompt_reachability": reachability_summary["summary"]["deployed_prompt"],
        "checks": checks,
    }
    _write(root / "preflight_readiness.json", readiness)
    _write(result / "readiness.json", readiness)

    environment = {
        "schema_version": "m13e2-cwru-run-environment-v1",
        "git": {"commit": COMMIT, "clean": True, "status": []},
        "gpu": {"status": "available", "model": "NVIDIA H100 NVL"},
        "slurm": {"job_id": "12345", "job_name": "fixture"},
        "experiment": {
            "spec_sha256": _sha256(SPEC_PATH),
            "spec_freeze_hash": spec.data["freeze_hash"],
            "model_bundle_hash": spec.data["model_bundle_hash"],
            "prompt_hash": model_bundle.prompt.prompt_hash,
        },
        "environment_contract": {"hash": contract.contract_hash},
        "secrets_persisted": False,
    }
    _write(root / "cwru_environment.json", environment)
    _write(
        root / "vllm_structured_smoke.json",
        {"schema_valid": True, "secrets_persisted": False},
    )

    manifest = {
        "schema_version": "m13e3b5-preflight-run-manifest-v3",
        "spec_sha256": _sha256(SPEC_PATH),
        "spec_freeze_hash": spec.data["freeze_hash"],
        "catalog_hash": "fixture-catalog-hash",
        "provider": spec.data["provider"],
        "model": spec.data["model"],
        "model_bundle_hash": spec.data["model_bundle_hash"],
        "prompt_hash": model_bundle.prompt.prompt_hash,
        "question_count": 18,
        "backend_execution": False,
        "secrets_persisted": False,
        "inference_artifacts": {
            "profile": "query_local_e3b4",
            "reachability_audit_hash": reachability_summary["audit_hash"],
            "prompt_candidates_per_slot": 4,
            "relation_endpoint_contract_version": RELATION_ENDPOINT_CONTRACT_VERSION,
        },
        "execution_environment": environment,
    }
    _write(result / "run_manifest.json", manifest)

    retrieval = [{"question_id": question_id} for question_id in ids]
    requests = [
        {
            "task_id": question_id,
            "call_index": 1,
            "call_kind": "generation",
            "payload": {"max_candidates": 3},
        }
        for question_id in ids
    ]
    responses = [
        {
            "task_id": question_id,
            "generation_calls": 1,
            "repair_calls": 0,
            "validation_status": "schema_valid",
            "structured_response": {"candidates": [{"candidate_id": "candidate-1"}]},
        }
        for question_id in ids
    ]
    candidates = [
        {
            "question_id": question_id,
            "candidate_id": "candidate-1",
            "normalized_reference_match": index < 5,
            "semantic_deviation": 0.0,
        }
        for index, question_id in enumerate(ids)
    ]
    components = [
        {
            "question_id": question_id,
            "candidate_id": "candidate-1",
            "matches": {
                "full_normalized_interpretation": index < 5,
                "relation_sequence": True,
            },
        }
        for index, question_id in enumerate(ids)
    ]
    semantic = [
        {"question_id": question_id, "candidate_id": "candidate-1"}
        for question_id in ids
    ]
    failures = [
        {"question_id": question_id, "category": "equivalence_failure"}
        for question_id in ids[5:]
    ]
    metrics = {
        "schema_version": "m13e1-preflight-metrics-v2",
        "catalog_availability": readiness["catalog_coverage"],
        "prompt_reachability": readiness["prompt_reachability"],
        **_recompute_metrics(
            expected_ids=ids,
            responses=responses,
            candidates=candidates,
            components=components,
            failures=failures,
            reachability={row["question_id"]: row for row in reachability_rows},
            epsilon_values=tuple(float(item) for item in spec.data["epsilon_values"]),
        ),
    }
    _write_jsonl(result / "retrieval.jsonl", retrieval)
    _write_jsonl(result / "llm_requests.jsonl", requests)
    _write_jsonl(result / "llm_responses.jsonl", responses)
    _write_jsonl(result / "validated_candidates.jsonl", candidates)
    _write_jsonl(result / "component_match.jsonl", components)
    _write_jsonl(result / "semantic_scores.jsonl", semantic)
    _write_jsonl(result / "failures.jsonl", failures)
    _write(result / "metrics.json", metrics)
    (root / "job.log").write_text("complete\n", encoding="utf-8")
    _inventory(root)
    return root


def test_complete_preflight_is_reconstructed_without_mutating_source(tmp_path: Path) -> None:
    root = _fixture_run(tmp_path)
    before = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }

    audit = audit_grailqa_preflight_run(
        run_root=root,
        repo_root=ROOT,
        expected_commit=COMMIT,
    )

    after = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert audit["schema_version"] == AUDIT_SCHEMA_VERSION
    assert audit["success"] is True
    assert audit["failed_check_ids"] == []
    assert audit["run_tree_mutated"] is False
    assert audit["diagnostic"] == {
        "provider_success_count": 18,
        "provider_failure_count": 0,
        "candidate_bearing_query_count": 18,
        "matched_query_count": 5,
        "candidate_recall_is_unconfounded_by_provider_failure": True,
    }
    assert audit["claim_boundary"]["paper_result"] is False
    assert content_hash(
        {key: value for key, value in audit.items() if key != "audit_sha256"}
    ) == audit["audit_sha256"]
    assert before == after


def test_empty_schema_valid_candidate_array_fails_provider_boundary_audit(
    tmp_path: Path,
) -> None:
    root = _fixture_run(tmp_path)
    responses_path = root / RESULT_RELATIVE_ROOT / "llm_responses.jsonl"
    responses = [json.loads(line) for line in responses_path.read_text().splitlines()]
    responses[0]["structured_response"]["candidates"] = []
    _write_jsonl(responses_path, responses)
    _inventory(root)

    audit = audit_grailqa_preflight_run(
        run_root=root,
        repo_root=ROOT,
        expected_commit=COMMIT,
    )

    assert audit["success"] is False
    assert "provider.response_candidate_cardinality" in audit["failed_check_ids"]


def test_cli_refuses_to_write_audit_inside_source_run(tmp_path: Path) -> None:
    root = _fixture_run(tmp_path)

    with pytest.raises(ValueError, match="outside the immutable source run tree"):
        main(
            [
                "--run-root",
                str(root),
                "--repo-root",
                str(ROOT),
                "--expected-commit",
                COMMIT,
                "--output",
                str(root / "audit.json"),
            ]
        )
