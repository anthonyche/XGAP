"""Focused paid-selection checks with synthetic costs and existing tiny plans.

No original answer oracle, model, or backend service is opened by these tests.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from test_m15_finbench_federation import _scheduler, public_workload

from xgap.experiments import finbench_paid_selection as paid
from xgap.runtime.contracts import (
    FederatedRunResult,
    RuntimeNodeKind,
    RuntimeNodeResult,
    RuntimeNodeStatus,
)


@pytest.fixture
def prepared(public_workload, monkeypatch):
    root, public = public_workload
    # Preserve the original ID/family/split denominator shape, using only the
    # existing authored tiny public parameters; these are not measured inputs.
    instances = []
    for family_index, prototype in enumerate(
        public["public_instances"]["instances"], start=1
    ):
        for index in range(1, 17):
            instance = deepcopy(prototype)
            instance.update(
                query_id=f"m15-fb-confirmatory-48-f{family_index}-{index:02d}",
                split_role=(
                    "heldout_family" if family_index == 3 else "crossfit_seen_family"
                ),
            )
            instances.append(instance)
    public["public_instances"]["instances"] = instances
    public["manifest"].update(
        population_id="m15-finbench-confirmatory-48-v1",
        instance_count=48,
        source_archive_sha256="b" * 64,
    )
    monkeypatch.setattr(paid, "load_finbench_primary_public_workload", lambda _: public)
    return paid.prepare_finbench_paid_selection(root)


class ControlledScheduler:
    """Return explicit synthetic reports without interpreting native queries."""

    def __init__(self, outcomes=(), before_execute=None):
        self.outcomes = list(outcomes)
        self.before_execute = before_execute
        self.calls = []

    def execute(self, plan, *, goal_id):
        if self.before_execute:
            self.before_execute(plan, len(self.calls))
        index = len(self.calls)
        self.calls.append((plan, goal_id))
        outcome = self.outcomes[index] if index < len(self.outcomes) else {}
        if isinstance(outcome, Exception):
            raise outcome
        success = outcome.get("success", True)
        family = plan.metadata["family_id"]
        rows = [{"company_id": f"execution-{index + 1}", "total_amount": index + 1}]
        if family.startswith("f1"):
            rows[0]["account_id"] = "A1"
        elif family.startswith("f2"):
            rows = [{
                "other_id": f"execution-{index + 1}",
                "account_distance": 1,
                "medium_id": "M1",
                "medium_type": "PHONE",
            }]
        return FederatedRunResult(
            plan_id=plan.plan_id,
            success=success,
            root_rows={plan.roots[0]: tuple(rows) if success else ()},
            node_results=(RuntimeNodeResult(
                node_id="controlled-cost-report",
                kind=RuntimeNodeKind.REMOTE_QUERY,
                status=RuntimeNodeStatus.SUCCESS if success else RuntimeNodeStatus.ERROR,
                remote_calls=outcome.get("calls", 2),
                bytes_moved=outcome.get("bytes", 100 + index),
                error=None if success else "controlled backend failure",
            ),),
            elapsed_ms=outcome.get("elapsed_ms", 10.0 + index),
        )


def _orders(candidates, query_ids):
    return (
        {query_id: ["fixed_hash", "fixed_bind", "paid_selection"] for query_id in query_ids},
        {
            query_id: [
                item.plan.metadata["physical_strategy"] for item in candidates[query_id]
            ]
            for query_id in query_ids
        },
    )


def _run(prepared, scheduler, *, query_ids=None, on_update=None, **overrides):
    public, candidates, preparation = prepared
    selected = tuple(query_ids or paid.FIXED_QUERY_IDS)
    methods, acquisitions = _orders(candidates, selected)
    record = {}
    updates = []

    def update():
        updates.append(deepcopy(record))
        if on_update:
            on_update(record)

    arguments = dict(
        public_workload=public,
        candidates_by_query=candidates,
        preparation_receipt=preparation,
        scheduler=scheduler,
        method_orders=methods,
        acquisition_orders=acquisitions,
        record=record,
        on_update=update,
        query_ids=selected,
    )
    arguments.update(overrides)
    result = paid.run_finbench_paid_selection(**arguments)
    return result, updates


def _query(record, query_id):
    return next(row for row in record["queries"] if row["query_id"] == query_id)


def _method(record, query_id, method_id):
    return next(
        row for row in _query(record, query_id)["methods"]
        if row["method_id"] == method_id
    )


def test_three_methods_pay_for_acquisition_and_seal_before_fresh_final(prepared, monkeypatch):
    snapshots = []
    original_selection = paid._selection

    def select_costs_only(costs):
        assert len(costs) == 2
        assert all(set(cost) == {
            "action_id", "plan_id", "physical_strategy", "elapsed_ms", "total_bytes_moved"
        } for cost in costs)
        return original_selection(costs)

    monkeypatch.setattr(paid, "_selection", select_costs_only)

    def inspect_dispatch(plan, index):
        if index % 5 != 4:
            return
        row = _method(snapshots[-1], plan.metadata["query_id"], "paid_selection")
        assert row["selection"]["selected_plan_id"] == plan.plan_id
        assert len([x for x in row["executions"] if x["role"] == "acquisition"]) == 2
        assert all(x["runtime_result"] is not None for x in row["executions"][:2])
        assert row["selection"]["cost_inputs"]
        assert any(
            all(a["status"] == "completed" for a in _method(
                s, plan.metadata["query_id"], "paid_selection"
            )["executions"][:2])
            and _method(s, plan.metadata["query_id"], "paid_selection")["selection"] is None
            for s in snapshots
        )

    scheduler = ControlledScheduler(before_execute=inspect_dispatch)
    result, _ = _run(prepared, scheduler, on_update=lambda row: snapshots.append(deepcopy(row)))

    assert result["success"] is True
    assert result["executions_sealed_before_evaluation"] is True
    assert result["answers_evaluated"] is False
    assert result["paper_result"] is False
    assert result["total_remote_calls"] == 30
    assert result["max_plan_runs"] == 15
    assert result["max_query_calls"] == 30
    assert len(scheduler.calls) == 15
    assert len(result["queries"]) == 48
    assert len({row["query_id"] for row in result["queries"]}) == 48
    for family_index, query_id in enumerate(paid.FIXED_QUERY_IDS):
        methods = _query(result, query_id)["methods"]
        assert [x["method_id"] for x in methods] == ["fixed_hash", "fixed_bind", "paid_selection"]
        assert [len(x["executions"]) for x in methods] == [1, 1, 3]
        assert [x["total_remote_calls"] for x in methods] == [2, 2, 6]
        selected = methods[-1]
        assert [x["role"] for x in selected["executions"]] == ["acquisition", "acquisition", "final"]
        assert selected["total_bytes_moved"] == sum(x["total_bytes_moved"] for x in selected["executions"])
        assert selected["selection"]["answer_values_consulted"] is False
        assert all(
            set(cost) == {"action_id", "plan_id", "physical_strategy", "elapsed_ms", "total_bytes_moved"}
            for cost in selected["selection"]["cost_inputs"]
        )
        # Each controlled execution has distinct rows, making sample reuse visible.
        assert selected["final_rows"] != selected["executions"][0]["runtime_result"]["final_rows"]
        assert selected["final_rows"] != selected["executions"][1]["runtime_result"]["final_rows"]
        identity_field = "other_id" if family_index == 1 else "company_id"
        assert selected["final_rows"][0][identity_field] == f"execution-{5 * (family_index + 1)}"
    unselected = [row for row in result["queries"] if row["query_id"] not in paid.FIXED_QUERY_IDS]
    assert len(unselected) == 45
    assert all(not method["executions"] for row in unselected for method in row["methods"])
    assert all(method["status"] == "not_attempted" and method["wall_ms"] is None
               and method["total_remote_calls"] is None
               for row in unselected for method in row["methods"])
    assert {row["query_id"] for row in result["queries"] if row["integration_exposed"]} == set(paid.FIXED_QUERY_IDS)
    assert sum(row["split_role"] == "crossfit_seen_family" for row in result["queries"]) == 32
    assert sum(row["split_role"] == "heldout_family" for row in result["queries"]) == 16


@pytest.mark.parametrize("failure_index", [2, 4], ids=["first-acquisition", "fresh-final"])
def test_failed_backend_attempt_keeps_cost_and_stops_without_retry(prepared, failure_index):
    outcomes = [{} for _ in range(failure_index)] + [
        {"success": False, "calls": 1, "bytes": 17, "elapsed_ms": 23.0}
    ]
    scheduler = ControlledScheduler(outcomes)
    result, updates = _run(prepared, scheduler)

    assert result["success"] is False
    assert len(scheduler.calls) == failure_index + 1
    row = _method(result, paid.FIXED_QUERY_IDS[0], "paid_selection")
    failed = next(action for action in row["executions"] if action["status"] == "failed")
    assert failed["status"] == "failed"
    assert failed["total_remote_calls"] == 1
    assert failed["total_bytes_moved"] == 17
    assert failed["elapsed_ms"] == 23.0
    assert failed["runtime_result"]["success"] is False
    assert row["final_rows"] is None
    assert row["total_remote_calls"] == (1 if failure_index == 2 else 5)
    assert updates[-1] == result
    assert all(
        all(action["status"] == "not_attempted" for action in method["executions"])
        for query_id in paid.FIXED_QUERY_IDS[1:]
        for method in _query(result, query_id)["methods"]
    )


@pytest.mark.parametrize(
    "failure",
    [{"elapsed_ms": None}, RuntimeError("controlled transport disappeared")],
    ids=["unknown-returned-cost", "scheduler-exception"],
)
def test_unknown_attempt_is_not_fabricated_as_zero_cost(prepared, failure):
    scheduler = ControlledScheduler([{}, {}, failure])
    result, updates = _run(prepared, scheduler)

    assert result["success"] is False
    assert len(scheduler.calls) == 3
    method = _method(result, paid.FIXED_QUERY_IDS[0], "paid_selection")
    action = next(action for action in method["executions"] if action["status"] == "unknown")
    assert action["status"] == "unknown"
    assert action["call_wall_ms"] >= 0
    assert method["final_rows"] is None
    assert method["selection"] is None
    assert method["total_remote_calls"] is None
    assert result["total_remote_calls"] is None
    assert result["known_remote_calls"] == 4
    if isinstance(failure, Exception):
        assert action["runtime_result"] is None
        assert action["total_remote_calls"] is None
        assert action["total_bytes_moved"] is None
        assert action["error_type"] == "RuntimeError"
    else:
        assert action["runtime_result"]["elapsed_ms"] is None
    assert updates[-1] == result


@pytest.mark.parametrize(
    "invalid",
    ["duplicate-method", "duplicate-acquisition", "unknown-acquisition"],
)
def test_invalid_frozen_order_is_rejected_before_dispatch(prepared, invalid):
    _, candidates, _ = prepared
    methods, acquisitions = _orders(candidates, paid.FIXED_QUERY_IDS)
    query_id = paid.FIXED_QUERY_IDS[0]
    if invalid == "duplicate-method":
        methods[query_id] = ["fixed_hash", "fixed_hash", "paid_selection"]
    elif invalid == "duplicate-acquisition":
        acquisitions[query_id] = [acquisitions[query_id][0]] * 2
    else:
        acquisitions[query_id][1] = "unregistered-strategy"
    scheduler = ControlledScheduler()
    with pytest.raises(ValueError):
        _run(prepared, scheduler, method_orders=methods, acquisition_orders=acquisitions)
    assert scheduler.calls == []


@pytest.mark.parametrize("tie_break", ["bytes", "strategy"])
def test_acquisition_ties_use_only_bytes_then_strategy(prepared, tie_break):
    public, _, _ = prepared
    query_ids = paid.FIXED_QUERY_IDS[:1]
    single = paid.prepare_finbench_paid_selection(public["root"], query_ids=query_ids)
    _, candidates, _ = single
    _, acquisitions = _orders(candidates, query_ids)
    hash_strategy, bind_strategy = acquisitions[query_ids[0]]
    # Put the lexically later hash route first: ordinal position cannot settle a tie.
    assert hash_strategy > bind_strategy
    outcomes = [{}, {}, {"elapsed_ms": 5.0, "bytes": 10},
                {"elapsed_ms": 5.0, "bytes": 20 if tie_break == "bytes" else 10}, {}]
    scheduler = ControlledScheduler(outcomes)
    result, _ = _run(single, scheduler, query_ids=query_ids)
    expected = hash_strategy if tie_break == "bytes" else bind_strategy
    chosen = _method(result, query_ids[0], "paid_selection")["selection"]
    assert result["success"] is True
    assert chosen["selected_physical_strategy"] == expected
    assert scheduler.calls[-1][0].metadata["physical_strategy"] == expected
    assert len(scheduler.calls) == 5


def test_method_wall_includes_paid_acquisition_selection_and_persistence(prepared, monkeypatch):
    public, _, _ = prepared
    query_ids = paid.FIXED_QUERY_IDS[:1]
    single = paid.prepare_finbench_paid_selection(public["root"], query_ids=query_ids)
    clock = {"seconds": 0.0}
    monkeypatch.setattr(paid, "time", SimpleNamespace(perf_counter=lambda: clock["seconds"]))
    original_selection = paid._selection

    def choose(actions):
        clock["seconds"] += 0.25  # Explicitly synthetic selection CPU time.
        return original_selection(actions)

    def persist(_record):
        clock["seconds"] += 0.005

    def execute_time(_plan, _index):
        clock["seconds"] += 1.0  # Deliberately differs from reported backend elapsed.

    monkeypatch.setattr(paid, "_selection", choose)
    result, _ = _run(single, ControlledScheduler(before_execute=execute_time),
                     query_ids=query_ids, on_update=persist)
    fixed_hash, fixed_bind, adaptive = _query(result, query_ids[0])["methods"]
    assert 1000 <= fixed_hash["wall_ms"] < 1100
    assert 1000 <= fixed_bind["wall_ms"] < 1100
    assert 3250 <= adaptive["wall_ms"] < 3400
    assert adaptive["selection"]["selection_ms"] == pytest.approx(250)
    assert sum(action["call_wall_ms"] for action in adaptive["executions"]) == pytest.approx(3000)
    assert result["compilation_cost_in_method_wall"] is False
    assert result["preparation_receipt"]["compilation_ms"] >= 0


def test_existing_tiny_finbench_adapter_runs_real_coordinator_for_all_methods(prepared):
    public, _, _ = prepared
    query_ids = paid.FIXED_QUERY_IDS[:1]
    single = paid.prepare_finbench_paid_selection(public["root"], query_ids=query_ids)
    scheduler = _scheduler({
        "neo4j-full": [
            {"company_id": "C1", "account_id": "A1", "total_amount": 7.0},
            {"company_id": "C2", "account_id": "A2", "total_amount": 9.0},
        ],
        "neo4j-bound": [{"company_id": "C1", "account_id": "A1", "total_amount": 7.0}],
        "fuseki-control": [{"account_id": "A1"}],
    })
    result, _ = _run(single, scheduler, query_ids=query_ids)

    assert result["success"] is True
    assert result["attempted_plan_runs"] == 5
    assert result["total_remote_calls"] == 10
    expected = [{"company_id": "C1", "account_id": "A1", "total_amount": "7.000"}]
    assert [method["final_rows"] for method in _query(result, query_ids[0])["methods"]] == [expected] * 3
    full = _method(result, query_ids[0], "fixed_hash")["executions"][0]["runtime_result"]
    assert any(node["kind"] == "coordinator_semi_join" for node in full["node_results"])
    assert result["oracle_content_parsed"] is False
    assert result["answers_evaluated"] is False
