from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_query_bound_campaign import (
    compile_m15_query_bound_campaign_file,
)
from xgap.experiments.m15_query_stream import (
    QUERY_STREAM_PLAN_SCHEMA_VERSION,
    M15QueryStreamError,
    compile_m15_query_stream,
    compile_m15_query_stream_file,
    main,
    write_m15_query_stream_plan,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = REPO_ROOT / "experiments/configs/m15_f2_query_bound_campaign_dev.json"
SESSION_ID = "m15-f2-development-protocol-v1.selective.b01.s01"
REGISTRY_SHA = "9547c000d3d652837657ea75ba62ea9fcbaca4c03f8befbe0293d25d2ee44d23"
SCHEDULE_SHA = "cf2a5aead7fc4378213fa0ff48da6271553005c86b19e1f8951086732db1c746"


def _bound() -> dict[str, object]:
    return compile_m15_query_bound_campaign_file(
        REGISTRY,
        repo_root=REPO_ROOT,
    ).to_dict()


def _compile(payload: dict[str, object] | None = None):
    selected = payload or _bound()
    return compile_m15_query_stream(
        selected,
        session_id=SESSION_ID,
        expected_registry_spec_sha256=selected["registry_spec_sha256"],
        expected_query_bound_schedule_sha256=selected[
            "query_bound_schedule_sha256"
        ],
    )


def _rehash(payload: dict[str, object]) -> None:
    portable = [
        {
            key: value
            for key, value in item.items()
            if key not in {"query_spec_path", "query_contract_verification"}
        }
        for item in payload["query_bindings"]
    ]
    payload["query_binding_sha256"] = content_hash(portable)
    payload["query_bound_schedule_sha256"] = content_hash(
        {
            "registry_id": payload["registry_id"],
            "base_schedule_sha256": payload["base_campaign"]["schedule_sha256"],
            "query_binding_sha256": payload["query_binding_sha256"],
            "sessions": payload["sessions"],
        }
    )


def test_current_campaign_expands_unique_tasks_and_reports_memory_blocker() -> None:
    plan = _compile().to_dict()

    assert plan["schema_version"] == QUERY_STREAM_PLAN_SCHEMA_VERSION
    assert plan["expected_counts"] == {
        "query_contracts": 1,
        "method_streams": 6,
        "warmup_tasks": 0,
        "measured_tasks": 6,
        "total_tasks": 6,
    }
    tasks = [
        task
        for stream in plan["method_streams"]
        for task in stream["tasks"]
    ]
    assert len({task["task_id"] for task in tasks}) == 6
    assert [task["task_index"] for task in tasks] == list(range(1, 7))
    assert all(task["phase"] == "measured" for task in tasks)
    validation = plan["design_validation"]
    assert validation["explicit_task_identity"] is True
    assert validation["multi_task_memory_ready"] is False
    assert validation["blocking_conditions"] == [
        "cross_task_transfer_model_not_bound",
        "fewer_than_two_distinct_query_contracts_in_session",
        "query_instances_are_not_yet_parameterized",
        "fewer_than_two_measured_tasks_per_method_stream",
    ]
    assert plan["claim_boundary"]["backend_calls_made"] == 0
    assert plan["claim_boundary"]["cross_task_memory_benefit_measured"] is False
    assert plan["paper_result"] is False


def test_two_query_session_has_explicit_method_local_history() -> None:
    payload = _bound()
    session = next(
        item for item in payload["sessions"] if item["session_id"] == SESSION_ID
    )
    second = copy.deepcopy(session["query_contract_refs"][0])
    second["query_id"] = "financial-risk-bob-medium-risk"
    second["expected_query_spec_sha256"] = "1" * 64
    second["expected_query_contract_sha256"] = "2" * 64
    session["query_contract_refs"].append(second)
    for stream in session["method_streams"]:
        stream["query_ids"].append(second["query_id"])
        stream["query_contract_refs"].append(copy.deepcopy(second))
    first_binding = next(
        item
        for item in payload["query_bindings"]
        if item["workload_label"] == "selective"
    )
    second_binding = copy.deepcopy(first_binding)
    second_binding["query_id"] = second["query_id"]
    second_binding["expected_query_spec_sha256"] = second[
        "expected_query_spec_sha256"
    ]
    second_binding["expected_query_contract_sha256"] = second[
        "expected_query_contract_sha256"
    ]
    payload["query_bindings"].append(second_binding)
    payload["query_bindings"].sort(
        key=lambda item: (item["workload_label"], item["query_id"])
    )
    _rehash(payload)

    plan = _compile(payload).to_dict()
    assert plan["expected_counts"]["measured_tasks"] == 12
    by_method = {item["method"]: item for item in plan["method_streams"]}

    full_tasks = by_method["full_agent"]["tasks"]
    assert len(full_tasks) == 2
    assert full_tasks[0]["memory"]["eligible_predecessor_task_ids"] == []
    assert full_tasks[1]["memory"]["eligible_predecessor_task_ids"] == [
        full_tasks[0]["task_id"]
    ]
    assert full_tasks[1]["memory"]["namespace"] == full_tasks[0]["memory"]["namespace"]

    no_memory_tasks = by_method["no_memory"]["tasks"]
    assert all(
        task["memory"]["eligible_predecessor_task_ids"] == []
        for task in no_memory_tasks
    )
    assert (
        full_tasks[0]["memory"]["namespace"]
        != no_memory_tasks[0]["memory"]["namespace"]
    )
    assert plan["design_validation"]["multi_task_memory_ready"] is False
    assert plan["design_validation"]["blocking_conditions"] == [
        "cross_task_transfer_model_not_bound"
    ]


@pytest.mark.parametrize(
    ("registry_hash", "schedule_hash", "message"),
    [
        ("0" * 64, SCHEDULE_SHA, "registry spec hash drifted"),
        (REGISTRY_SHA, "0" * 64, "schedule hash drifted"),
    ],
)
def test_query_stream_rejects_source_hash_drift(
    registry_hash: str,
    schedule_hash: str,
    message: str,
) -> None:
    with pytest.raises(M15QueryStreamError, match=message):
        compile_m15_query_stream(
            _bound(),
            session_id=SESSION_ID,
            expected_registry_spec_sha256=registry_hash,
            expected_query_bound_schedule_sha256=schedule_hash,
        )


def test_query_stream_rejects_stream_contract_mismatch() -> None:
    payload = _bound()
    session = next(
        item for item in payload["sessions"] if item["session_id"] == SESSION_ID
    )
    session["method_streams"][0]["query_contract_refs"][0][
        "expected_query_contract_sha256"
    ] = "0" * 64

    with pytest.raises(M15QueryStreamError, match="session payload hash drifted"):
        _compile(payload)


def test_query_stream_rejects_binding_payload_hash_drift() -> None:
    payload = _bound()
    payload["query_bindings"][0]["hard_constraint_count"] = 99

    with pytest.raises(M15QueryStreamError, match="binding payload hash drifted"):
        _compile(payload)


def test_query_stream_hash_is_deterministic_and_path_independent() -> None:
    first = _compile().to_dict()
    payload = _bound()
    for binding in payload["query_bindings"]:
        binding["query_spec_path"] = "relocated/query-spec.json"
    second = _compile(payload).to_dict()

    assert first == second
    assert len(first["query_stream_sha256"]) == 64


def test_query_stream_file_and_cli_are_side_effect_free(capsys) -> None:
    direct = compile_m15_query_stream_file(
        REGISTRY,
        session_id=SESSION_ID,
        expected_registry_spec_sha256=REGISTRY_SHA,
        expected_query_bound_schedule_sha256=SCHEDULE_SHA,
        repo_root=REPO_ROOT,
    ).to_dict()
    assert main(
        [
            "--registry",
            str(REGISTRY),
            "--session-id",
            SESSION_ID,
            "--expected-registry-spec-sha256",
            REGISTRY_SHA,
            "--expected-query-bound-schedule-sha256",
            SCHEDULE_SHA,
            "--repo-root",
            str(REPO_ROOT),
        ]
    ) == 0
    cli = json.loads(capsys.readouterr().out)
    assert cli == direct
    assert cli["claim_boundary"]["backend_calls_made"] == 0


def test_query_stream_write_is_immutable(tmp_path: Path) -> None:
    plan = _compile()
    output = tmp_path / "stream.json"
    write_m15_query_stream_plan(plan, output)
    assert json.loads(output.read_text(encoding="utf-8")) == plan.to_dict()
    with pytest.raises(FileExistsError, match="exists"):
        write_m15_query_stream_plan(plan, output)
