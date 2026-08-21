from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.grailqa_preflight import (
    GrailQAPreflightSpec,
    QUERY_LOCAL_ARTIFACT_PROFILE,
    _jointly_reachable_subset_metrics,
    preflight_readiness,
)
from xgap.experiments.grailqa_semantic_pilot import build_inference_request
from xgap.experiments.hashing import content_hash
from xgap.experiments.live_run import build_openai_compatible_provider
from xgap.experiments.relation_endpoints import (
    RELATION_ENDPOINT_CONTRACT_VERSION,
    relation_endpoint_prompt_contract,
)


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "experiments/specs/grailqa_semantic_preflight_v2_cwru_qwen3_32b.json"


def _write_local_artifacts(
    root: Path,
    spec: GrailQAPreflightSpec,
    *,
    endpoint_contract: str = RELATION_ENDPOINT_CONTRACT_VERSION,
    question_ids: tuple[str, ...] | None = None,
) -> None:
    ids = question_ids or spec.question_ids
    rows = [
        {
            "question_id": question_id,
            "deployed_prompt": {"joint": {"reachable": index < 5}},
            "relation_endpoint_grounding": {
                "contract_version": endpoint_contract,
            },
        }
        for index, question_id in enumerate(ids)
    ]
    rows_text = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    (root / "reachability.jsonl").write_text(rows_text, encoding="utf-8")
    summary: dict[str, Any] = {
        "schema_version": "m13e3b4-grailqa-local-reachability-v2",
        "catalog_hash": "fixture-local-catalog-hash",
        "question_count": len(ids),
        "k_values": [1, 5, 10, 20],
        "prompt_limit": 4,
        "summary": {
            "catalog": {"joint": {"count": len(ids), "ratio": 1.0}},
            "retrieval": {},
            "deployed_prompt": {
                "joint": {"count": 5, "ratio": 5 / len(ids)},
            },
        },
        "relation_endpoint_grounding": {
            "contract_version": endpoint_contract,
        },
        "artifact_hashes": {
            "reachability.jsonl": hashlib.sha256(rows_text.encode("utf-8")).hexdigest(),
        },
    }
    summary["audit_hash"] = content_hash(summary)
    (root / "audit_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _configure_local_profile(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    spec: GrailQAPreflightSpec,
) -> None:
    fake_catalog = SimpleNamespace(
        root=root,
        catalog_hash="fixture-local-catalog-hash",
        manifest={
            "local_catalog_schema_version": "m13e3b-grailqa-local-catalog-v1",
            "requires_query_entity_filter": True,
            "gold_used_for_construction": False,
            "question_ids": list(spec.question_ids),
        },
    )
    monkeypatch.setattr(
        "xgap.experiments.grailqa_preflight.GrailQAInferenceCatalogV2.load",
        lambda path: fake_catalog,
    )
    monkeypatch.setattr(
        "xgap.experiments.grailqa_preflight.validate_local_catalog",
        lambda path: {"local_query_filter": "ok"},
    )
    monkeypatch.setenv(
        "XGAP_GRAILQA_PREFLIGHT_ARTIFACT_PROFILE", QUERY_LOCAL_ARTIFACT_PROFILE
    )
    monkeypatch.setenv("XGAP_GRAILQA_CATALOG_V2", str(root))
    monkeypatch.setenv("XGAP_GRAILQA_REACHABILITY_V2", str(root))
    monkeypatch.setenv(
        "XGAP_GRAILQA_REACHABILITY_SUMMARY", str(root / "audit_summary.json")
    )
    monkeypatch.setenv(
        "XGAP_GRAILQA_REACHABILITY_ROWS", str(root / "reachability.jsonl")
    )
    monkeypatch.setenv("XGAP_LLM_API_KEY", "local")


def test_query_local_preflight_artifact_passes_exact_fail_closed_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    spec = GrailQAPreflightSpec.load(SPEC_PATH)
    _write_local_artifacts(tmp_path, spec)
    _configure_local_profile(monkeypatch, tmp_path, spec)

    report = preflight_readiness(spec, ROOT, require_credentials=True)

    assert report["ready"] is True
    assert report["artifact_profile"] == QUERY_LOCAL_ARTIFACT_PROFILE
    assert report["reachability_summary_path"].endswith("audit_summary.json")
    assert report["artifact_profile_contract"]["question_count"] == 18
    assert report["artifact_profile_contract"]["prompt_candidates_per_slot"] == 4
    assert report["gate"]["observed_joint_ratio"] == pytest.approx(5 / 18)


@pytest.mark.parametrize("mutation", ["endpoint_contract", "question_ids"])
def test_query_local_preflight_rejects_contract_or_question_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
) -> None:
    spec = GrailQAPreflightSpec.load(SPEC_PATH)
    if mutation == "endpoint_contract":
        _write_local_artifacts(tmp_path, spec, endpoint_contract="wrong-contract")
    else:
        _write_local_artifacts(
            tmp_path,
            spec,
            question_ids=(*spec.question_ids[:-1], "wrong-question"),
        )
    _configure_local_profile(monkeypatch, tmp_path, spec)

    report = preflight_readiness(spec, ROOT, require_credentials=True)

    assert report["ready"] is False
    profile_check = next(
        item for item in report["checks"] if item["name"] == "artifact_profile_contract"
    )
    assert profile_check["status"] == "fail"


def test_query_local_preflight_rejects_reachability_hash_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    spec = GrailQAPreflightSpec.load(SPEC_PATH)
    _write_local_artifacts(tmp_path, spec)
    rows_path = tmp_path / "reachability.jsonl"
    rows_path.write_text(rows_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    _configure_local_profile(monkeypatch, tmp_path, spec)

    report = preflight_readiness(spec, ROOT, require_credentials=True)

    assert report["ready"] is False
    profile_check = next(
        item for item in report["checks"] if item["name"] == "artifact_profile_contract"
    )
    assert "rows hash" in profile_check["detail"]


def test_structured_request_contains_exact_relation_endpoint_contract() -> None:
    prompt_schema_view = {
        "ontology": {"id": "fixture", "version": "v1", "hash": "hash"},
        "terms": [
            {
                "term_id": "people.person.parents",
                "kind": "relation",
                "domain": "people.person",
                "range": "people.person",
            }
        ],
        "entities": [],
        "query_slots": [
            {
                "slot_id": "relation-hop-1",
                "candidate_anchor_ids": ["people.person.parents"],
            }
        ],
    }
    retrieval = SimpleNamespace(to_dict=lambda: {"question_id": "q1"})
    prompt_view = SimpleNamespace(
        to_dict=lambda: prompt_schema_view,
        source_schema_items=("people.person.parents",),
    )
    request = build_inference_request(
        {"question_id": "q1", "text": "Who are Alice's parents?"},
        retrieval,
        prompt_view,
        1,
    )
    bundle = ModelBundle.load(ROOT / "models/qwen3_32b_vllm_cwru_m13e2")
    provider = build_openai_compatible_provider(bundle)

    payload = provider.build_request_payload(request)
    user_payload = json.loads(payload["messages"][1]["content"])

    assert user_payload["grounding_contracts"] == [
        relation_endpoint_prompt_contract()
    ]
    assert user_payload["requirements"]["apply_supplied_grounding_contracts"] is True


def test_jointly_reachable_metrics_separate_ceiling_from_model_accuracy() -> None:
    states = [
        {
            "question": {"question_id": f"q{index}"},
            "api_call_completed": index != 1,
            "candidates": [{}] if index in {0, 2} else [],
        }
        for index in range(4)
    ]
    reachability = {
        f"q{index}": {
            "deployed_prompt": {"joint": {"reachable": index < 2}},
        }
        for index in range(4)
    }

    metrics = _jointly_reachable_subset_metrics(
        states,
        {"q0": True, "q1": False, "q2": True, "q3": False},
        reachability,
    )

    assert metrics["question_count"] == 2
    assert metrics["unreachable_question_count"] == 2
    assert metrics["prompt_reachability_ceiling"] == 0.5
    assert metrics["candidate_recall"] == 0.5
    assert metrics["provider_success_rate"] == 0.5
    assert metrics["structured_valid_rate"] == 0.5
