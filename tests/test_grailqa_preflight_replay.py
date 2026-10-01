from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

from xgap.experiments.grailqa_preflight_replay import (
    PreflightReplaySourceError,
    main,
    replay_grailqa_preflight,
)
from xgap.experiments.hashing import content_hash


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = runpy.run_path(str(ROOT / "tests/test_m13e3b4_relation_endpoint_grounding.py"))


def _records(target_type: str = "type.target") -> tuple[dict, dict]:
    view = FIXTURES["_prompt_view"]()
    user = {
        "task_id": view.task_id,
        "question": "question",
        "max_candidates": 3,
        "schema_hints": list(view.source_schema_items),
        "prompt_schema_view": view.to_dict(),
    }
    payload = {"messages": [{"role": "user", "content": json.dumps(user)}]}
    digest = content_hash(payload)
    request = {
        "task_id": view.task_id,
        "call_index": 1,
        "call_kind": "generation",
        "payload": payload,
        "payload_hash": digest,
    }
    response = {
        "task_id": view.task_id,
        "prompt_schema_view_hash": view.view_hash,
        "assembled_request_hashes": [digest],
        "validation_status": "schema_valid",
        "structured_response": FIXTURES["_grounded_raw"](target_type=target_type),
    }
    return request, response


def _write(root: Path, requests: list[dict], responses: list[dict]) -> None:
    for name, rows in (("llm_requests.jsonl", requests), ("llm_responses.jsonl", responses)):
        (root / name).write_text("".join(json.dumps(row) + "\n" for row in rows))


@pytest.mark.parametrize(
    ("target_type", "stage"),
    (("type.target", "grounding_passed"), ("type.wrong", "grounding_rejected")),
)
def test_real_grounding_replay_preserves_source(tmp_path: Path, target_type: str, stage: str) -> None:
    request, response = _records(target_type)
    _write(tmp_path, [request], [response])
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    result = replay_grailqa_preflight(run_root=tmp_path)

    assert result["status"] == "complete"
    assert result["counts"] == {"queries": 1, "raw_candidates": 1, "by_stage": {stage: 1}}
    assert result["queries"][0]["stage"] == stage
    if stage == "grounding_rejected":
        assert result["queries"][0]["error_type"] == "RuntimeAlignmentError"
        assert result["queries"][0]["category"] == "hallucinated_ontology_id"
        assert "type.wrong" in result["queries"][0]["message"]
    else:
        assert result["queries"][0]["grounded_candidate_count"] == 1
    assert result["external_call_counts"] == {"llm_calls": 0, "backend_calls": 0, "ontology_service_calls": 0}
    assert result["paper_result"] is False
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_provider_failure_is_retained(tmp_path: Path) -> None:
    request, response = _records()
    response.update(validation_status="failed", structured_response=None,
                    failure_category="provider_error", error_message="Recorded transport failure")
    _write(tmp_path, [request], [response])

    result = replay_grailqa_preflight(run_root=tmp_path)

    assert result["queries"] == [{
        "question_id": "q1", "provider_validation": "failed", "raw_candidate_count": 0,
        "stage": "provider_failed", "error_type": "provider_error",
        "message": "Recorded transport failure",
    }]


@pytest.mark.parametrize("defect", ["missing", "payload", "response_hash", "prompt_hash", "task_id"])
def test_missing_or_tampered_request_fails_explicitly(tmp_path: Path, defect: str) -> None:
    request, response = _records()
    requests = [request]
    if defect == "missing":
        requests = []
    elif defect == "payload":
        request["payload"]["messages"][0]["content"] += " "
    elif defect == "response_hash":
        response["assembled_request_hashes"] = ["0" * 64]
    elif defect == "prompt_hash":
        response["prompt_schema_view_hash"] = "0" * 64
    else:
        user = json.loads(request["payload"]["messages"][0]["content"])
        user["task_id"] = "another-query"
        request["payload"]["messages"][0]["content"] = json.dumps(user)
        request["payload_hash"] = content_hash(request["payload"])
        response["assembled_request_hashes"] = [request["payload_hash"]]
    _write(tmp_path, requests, [response])

    with pytest.raises(PreflightReplaySourceError):
        replay_grailqa_preflight(run_root=tmp_path)


def test_repair_ledger_uses_initial_prompt(tmp_path: Path) -> None:
    request, response = _records()
    repair = copy.deepcopy(request)
    repair.update(call_index=2, call_kind="repair")
    repair["payload"]["messages"].append({"role": "user", "content": "repair context"})
    repair["payload_hash"] = content_hash(repair["payload"])
    response["assembled_request_hashes"].append(repair["payload_hash"])
    _write(tmp_path, [request, repair], [response])

    result = replay_grailqa_preflight(run_root=tmp_path)

    assert result["queries"][0]["stage"] == "grounding_passed"


def test_cli_rejection_is_successful_diagnostic_but_bad_identity_fails(tmp_path: Path, capsys) -> None:
    request, response = _records("type.wrong")
    _write(tmp_path, [request], [response])
    assert main(["--run-root", str(tmp_path)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    report = json.loads(lines[0])
    assert report["queries"][0]["stage"] == "grounding_rejected"
    assert "structured_response" not in report["queries"][0]
    assert "payload" not in report["queries"][0]

    response["prompt_schema_view_hash"] = "0" * 64
    _write(tmp_path, [request], [response])
    assert main(["--run-root", str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "configuration_error"


def test_cli_runs_from_stdin_without_module_installation(tmp_path: Path) -> None:
    request, response = _records("type.wrong")
    _write(tmp_path, [request], [response])
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    source = ROOT / "src/xgap/experiments/grailqa_preflight_replay.py"

    process = subprocess.run(
        [sys.executable, "-B", "-", "--run-root", str(tmp_path)],
        input=source.read_text(),
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    assert len(process.stdout.splitlines()) == 1
    assert json.loads(process.stdout)["queries"][0]["stage"] == "grounding_rejected"
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
