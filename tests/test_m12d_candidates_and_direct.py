from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from xgap.experiments.bundles import DatasetBundle, ModelBundle
from xgap.experiments.candidate_freeze import (
    FrozenCandidateArtifact,
    generate_frozen_candidate_artifact,
)
from xgap.experiments.direct_baseline import build_direct_request, run_direct_baseline
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact


class _DirectTransport:
    def post_json(
        self,
        *,
        url: str,
        api_key: str,
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        del url, api_key, payload, timeout_seconds
        return {
            "id": "direct-test",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "language": "cypher",
                                "query": "MATCH (n) RETURN n LIMIT 1",
                            }
                        )
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }


class _DirectClient:
    backend_id = "neo4j"

    def healthcheck(self) -> BackendStatus:
        return BackendStatus("neo4j", True, "ok")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        return ExecutionReport(
            "neo4j",
            artifact.artifact_id,
            artifact.language,
            True,
            rows=[{"company": "Redstone Analytics"}],
            elapsed_ms=4.0,
        )


class _EmptyDirectClient(_DirectClient):
    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        return ExecutionReport(
            "neo4j",
            artifact.artifact_id,
            artifact.language,
            True,
            rows=[],
            elapsed_ms=4.0,
        )


def test_controlled_candidates_freeze_and_replay_with_hashes(tmp_path: Path) -> None:
    dataset = DatasetBundle.load("datasets/financial_risk_dev")
    model = ModelBundle.load("models/mock_path_pattern_dev")
    artifact = generate_frozen_candidate_artifact(
        dataset=dataset,
        model=model,
        question=dataset.question("fr-q001"),
        backend_ids=("neo4j", "fuseki"),
        max_candidates=3,
        task_id="freeze-test",
    )
    path = artifact.write(tmp_path / "candidate.json")
    loaded = FrozenCandidateArtifact.load(path)
    assert loaded.artifact_hash == artifact.artifact_hash
    assert loaded.candidate_hash == artifact.candidate_hash
    assert loaded.grounding_hash == artifact.grounding_hash
    assert len(loaded.planner_response().candidates) == 1
    serialized = json.dumps(loaded.to_dict())
    assert "gold_answers" not in serialized
    assert "gold_logical_form" not in serialized


def test_direct_request_is_separate_and_forbids_xgap_interpretations() -> None:
    model = ModelBundle.load("models/qwen3_max_dashscope_live")
    prompt = json.loads(
        Path("experiments/prompts/direct_text2graphquery_prompt.json").read_text()
    )
    schema = json.loads(
        Path("experiments/prompts/direct_text2graphquery_schema.json").read_text()
    )
    payload = build_direct_request(
        question="Find high-risk companies.",
        backend_id="neo4j",
        language="cypher",
        model=model,
        prompt=prompt,
        schema=schema,
        bounded_context={"ontology": {"id": "x", "version": "1"}},
    )
    user = payload["messages"][1]["content"]
    assert "exactly_one_native_query" in user
    assert "path_pattern_query_forbidden" in user
    assert payload["messages"][0]["content"] != model.prompt.system_prompt


def test_direct_baseline_persists_request_response_and_row_count(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key-not-persisted")
    result = run_direct_baseline(
        "experiments/configs/financial_risk_direct_qwen_dev.json",
        output_root_override=tmp_path,
        transport_override=_DirectTransport(),
        client_override=_DirectClient(),
    )
    assert result.status == "complete"
    assert result.row_count == 1
    request = (result.run_root / "direct_request.json").read_text()
    assert "test-key-not-persisted" not in request
    normalized = json.loads(
        (result.run_root / "results/normalized/result.json").read_text()
    )
    assert normalized["result_status"] == "execution_success_nonempty"
    assert normalized["row_count"] == 1


def test_direct_baseline_treats_empty_rows_as_success_not_correctness(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key-not-persisted")
    result = run_direct_baseline(
        "experiments/configs/financial_risk_direct_qwen_dev.json",
        output_root_override=tmp_path,
        transport_override=_DirectTransport(),
        client_override=_EmptyDirectClient(),
    )
    normalized = json.loads(
        (result.run_root / "results/normalized/result.json").read_text()
    )
    assert result.status == "complete"
    assert result.row_count == 0
    assert result.result_status == "execution_success_empty"
    assert normalized["answer_correctness"]["status"] == "not_available"
