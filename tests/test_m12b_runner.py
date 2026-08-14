from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from xgap.experiments.run import run_experiment


@dataclass
class GroundedFakeHTTPTransport:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def post_json(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(dict(kwargs))
        user_request = json.loads(kwargs["payload"]["messages"][1]["content"])
        view = user_request["prompt_schema_view"]
        slots = view["query_slots"]
        anchor_by_slot = {
            slot["slot_id"]: slot["candidate_anchor_ids"][0] for slot in slots
        }
        component_by_term = {
            "Person": "source",
            "Ownership": "expr.left.edge",
            "Transfer": "expr.right.edge",
            "Account": "target",
        }
        structured = {
            "provider_id": "fake-dashscope-openai-compatible",
            "model": "qwen3-max-2026-01-23",
            "query_slots": [
                {"slot_id": slot_id, "query_anchor_id": term_id}
                for slot_id, term_id in anchor_by_slot.items()
            ],
            "candidates": [
                {
                    "candidate_id": "fake-live-exact",
                    "confidence": 0.91,
                    "rationale": "Deterministic fake-HTTP exact interpretation.",
                    "pattern_query": {
                        "path_var": "p",
                        "source": {
                            "var": "person",
                            "label": "Person",
                            "properties": {"name": "Alice"},
                        },
                        "expr": {
                            "kind": "seq",
                            "left": {
                                "kind": "rel",
                                "edge": {
                                    "var": "owns",
                                    "label": "OWNS",
                                    "direction": "OUT",
                                    "properties": {},
                                },
                            },
                            "right": {
                                "kind": "rel",
                                "edge": {
                                    "var": "transfer",
                                    "label": "TRANSFER",
                                    "direction": "OUT",
                                    "properties": {},
                                },
                            },
                        },
                        "target": {
                            "var": "account",
                            "label": "Account",
                            "properties": {},
                        },
                        "selector": {"kind": "ALL", "k": None},
                        "restrictor": "TRAIL",
                        "condition": None,
                        "max_depth": None,
                    },
                    "grounding": {
                        "slot_realizations": [
                            {
                                "slot_id": slot_id,
                                "ontology_term_id": term_id,
                                "component_ref": component_by_term[term_id],
                            }
                            for slot_id, term_id in anchor_by_slot.items()
                        ],
                        "entity_ids": [item["entity_id"] for item in view["entities"]],
                    },
                }
            ],
        }
        return {
            "id": "fake-live-request-1",
            "choices": [{"message": {"content": json.dumps(structured)}}],
            "usage": {
                "prompt_tokens": 640,
                "completion_tokens": 220,
                "total_tokens": 860,
            },
        }


def test_runner_switches_to_full_live_provider_path_with_fake_http(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fake-test-secret")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://regional-provider.invalid/v1")
    transport = GroundedFakeHTTPTransport()

    result = run_experiment(
        "experiments/configs/financial_risk_qwen_live_dev.json",
        output_root_override=tmp_path,
        run_id_override="m12b-fake-http-integration",
        transport_override=transport,
    )

    assert result.attempted_question_count == 1
    assert result.successful_question_count == 1
    assert len(transport.calls) == 1
    assert transport.calls[0]["url"] == (
        "https://regional-provider.invalid/v1/chat/completions"
    )
    expected = {
        "prompt_schema_view.jsonl",
        "llm_requests.jsonl",
        "raw_model_responses.jsonl",
        "grounding.jsonl",
        "query_slots.jsonl",
        "alignment_results.jsonl",
        "live_diagnostics.json",
        "runtime_ontology_manifest.json",
    }
    assert expected.issubset(result.inventory)
    raw_text = "\n".join(
        (result.run_root / name).read_text(encoding="utf-8")
        for name in (
            "questions.jsonl",
            "prompt_schema_view.jsonl",
            "llm_requests.jsonl",
            "raw_model_responses.jsonl",
            "grounding.jsonl",
            "query_slots.jsonl",
        )
    )
    assert "fake-test-secret" not in raw_text
    assert "gold_answers" not in raw_text
    assert "gold_logical_form" not in raw_text
    assert "gold_alignments" not in raw_text

    invocation = json.loads(
        (result.run_root / "raw_model_responses.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assembled_request = json.loads(
        (result.run_root / "llm_requests.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    metrics = json.loads((result.run_root / "metrics.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (result.run_root / "experiment_manifest.json").read_text(encoding="utf-8")
    )
    assert invocation["generation_calls"] == 1
    assert invocation["repair_calls"] == 0
    assert invocation["usage"]["total_tokens"] == 860
    assert assembled_request["call_kind"] == "generation"
    assert assembled_request["payload"] == transport.calls[0]["payload"]
    assert assembled_request["payload_hash"] == invocation["assembled_request_hashes"][0]
    assert metrics["live_generation"]["generation_success_rate"]["value"] == 1
    assert metrics["live_generation"]["ontology_grounding_success_rate"]["value"] == 1
    assert manifest["model"]["exact_snapshot"] == "qwen3-max-2026-01-23"
    assert manifest["live_provider"]["base_url"] == (
        "https://regional-provider.invalid/v1"
    )
    assert manifest["runtime_ontology_alignment"]["gold_artifacts_exposed"] is False
    assert manifest["estimator"]["calibration_status"] == "not_available"
    assert manifest["estimator"]["development_prior"] is True


def test_runner_config_switch_preserves_m12a_mock_path(tmp_path: Path) -> None:
    result = run_experiment(
        "experiments/configs/financial_risk_xgap_dev.json",
        output_root_override=tmp_path,
        run_id_override="m12a-config-switch-regression",
    )

    assert result.successful_question_count == 2
    assert "raw_model_responses.jsonl" not in result.inventory
    assert (result.run_root / "alignment_results.jsonl").is_file()
