"""Full-denominator schedule and stopping checks without native services."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from test_finbench_paid_selection import ControlledScheduler, prepared, public_workload

from xgap.experiments import finbench_paid_selection as paid
from xgap.experiments import finbench_paid_journal as journal_module


PERMUTATIONS = [
    ["fixed_hash", "fixed_bind", "paid_selection"],
    ["fixed_hash", "paid_selection", "fixed_bind"],
    ["fixed_bind", "fixed_hash", "paid_selection"],
    ["fixed_bind", "paid_selection", "fixed_hash"],
    ["paid_selection", "fixed_hash", "fixed_bind"],
    ["paid_selection", "fixed_bind", "fixed_hash"],
]


@pytest.fixture
def driver():
    script = Path(__file__).resolve().parents[1] / "scripts/run_finbench_paid_selection_native.py"
    spec = importlib.util.spec_from_file_location("controlled_finbench_balanced_driver", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def balanced(prepared):
    public, _, _ = prepared
    ids = [row["query_id"] for row in public["public_instances"]["instances"]]
    full = paid.prepare_finbench_paid_selection(public["root"], query_ids=ids)
    _, candidates, _ = full
    blocks = []
    for block_index in range(6):
        methods, acquisitions = {}, {}
        for query_index, query_id in enumerate(ids):
            slot = (query_index + block_index) % 6
            methods[query_id] = list(PERMUTATIONS[slot])
            strategies = [candidate.plan.metadata["physical_strategy"] for candidate in candidates[query_id]]
            reverse = [0, 0, 1, 1, 0, 1][slot] ^ (query_index % 2)
            acquisitions[query_id] = strategies[::-1] if reverse else strategies
        blocks.append({
            "block_id": f"controlled-block-{block_index}",
            "query_ids": ids[block_index:] + ids[:block_index],
            "method_orders": methods, "acquisition_orders": acquisitions,
        })
    orders = {
        "schema_version": "xgap-finbench-paid-selection-balanced-v1", "query_ids": ids,
        "blocks": blocks, "maximum_plan_runs": 1440, "maximum_query_calls": 2880,
    }
    return full, orders


def test_full48_schedule_pairs_acquisition_direction_at_every_paid_position(driver, balanced):
    (public, candidates, _), orders = balanced
    before = deepcopy(orders)
    blocks = driver._schedule(orders, candidates, public)
    assert orders == before
    assert len(blocks) == 6
    assert orders["maximum_plan_runs"] == 6 * 48 * 5 == 1440
    assert orders["maximum_query_calls"] == 6 * 48 * 10 == 2880
    ids = orders["query_ids"]
    assert len(ids) == len(set(ids)) == 48
    assert all(len(block["query_ids"]) == 48 and set(block["query_ids"]) == set(ids) for block in blocks)
    for query_id in ids:
        assert {tuple(block["method_orders"][query_id]) for block in blocks} == {
            tuple(order) for order in PERMUTATIONS
        }
        assert sorted(Counter(block["acquisition_orders"][query_id][0] for block in blocks).values()) == [3, 3]
        for position in range(3):
            pair = [block["acquisition_orders"][query_id] for block in blocks
                    if block["method_orders"][query_id].index("paid_selection") == position]
            assert len(pair) == 2 and pair[0] == pair[1][::-1]
    campaign = driver._campaign_record(public, blocks)
    assert campaign["population_count"] == 48
    assert len(campaign["blocks"]) == 6
    for block in campaign["blocks"]:
        assert [query["query_id"] for query in block["queries"]] == ids
        assert sum(query["split_role"] == "heldout_family" for query in block["queries"]) == 16
        assert {query["query_id"] for query in block["queries"] if query["integration_exposed"]} == set(paid.FIXED_QUERY_IDS)
        assert all(method["status"] == "not_attempted" and method["wall_ms"] is None
                   for query in block["queries"] for method in query["methods"])


@pytest.mark.parametrize("drift", ["population", "method-permutation", "paired-direction", "budget"])
def test_invalid_balanced_protocol_is_rejected_before_execution(driver, balanced, monkeypatch, drift):
    (public, candidates, _), original = balanced
    orders = deepcopy(original)
    query_id = orders["query_ids"][0]
    if drift == "population":
        orders["query_ids"][-1] = "m15-fb-confirmatory-48-f3-17"
    elif drift == "method-permutation":
        orders["blocks"][1]["method_orders"][query_id] = list(PERMUTATIONS[0])
    elif drift == "paired-direction":
        # Global 3/3 counts survive, while the position-specific pair is broken.
        first = orders["blocks"][0]["acquisition_orders"]
        fourth = orders["blocks"][3]["acquisition_orders"]
        first[query_id], fourth[query_id] = fourth[query_id], first[query_id]
        assert sorted(Counter(block["acquisition_orders"][query_id][0] for block in orders["blocks"]).values()) == [3, 3]
    else:
        orders["maximum_query_calls"] = 2879

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid schedule reached execution, service startup, or answer access")

    monkeypatch.setattr(driver, "run_finbench_paid_selection", forbidden)
    monkeypatch.setattr(driver, "start_service", forbidden)
    monkeypatch.setattr(driver, "load_finbench_primary_workload", forbidden)
    with pytest.raises(ValueError):
        driver._schedule(orders, candidates, public)


@pytest.mark.parametrize("boundary", ["backend-failure", "dispatch-indeterminate"])
def test_first_failed_block_seals_every_unattempted_slot_before_one_oracle_read(
    driver, balanced, tmp_path, monkeypatch, boundary
):
    (public, candidates, preparation), orders = balanced
    blocks = driver._schedule(orders, candidates, public)
    campaign = driver._campaign_record(public, blocks)
    output = tmp_path / "campaign"
    output.mkdir()
    reads = []

    def load_toy_oracle(path):
        assert campaign["all_blocks_sealed"] is True
        assert all(block["sealed"] for block in campaign["blocks"])
        reads.append(path)
        return {
            "manifest": {"workload_sha256": public["manifest"]["workload_sha256"]},
            "sealed_oracles": {"queries": {
                query_id: {"final_rows": []} for query_id in orders["query_ids"]
            }},
        }

    monkeypatch.setattr(driver, "load_finbench_primary_workload", load_toy_oracle)
    with pytest.raises(ValueError, match="sealed"):
        driver._evaluate_blocks(campaign, output, tmp_path / "toy-oracle")
    assert reads == []
    if boundary == "dispatch-indeterminate":
        class InterruptedJournal(driver.PaidSelectionJournal):
            def __call__(self):
                dispatching = any(action["status"] == "started"
                                  for query in self.record.get("queries", [])
                                  for method in query["methods"] for action in method["executions"])
                if not dispatching:
                    return super().__call__()

                def failure(_fd):
                    raise OSError("controlled fsync failure before backend dispatch")

                with monkeypatch.context() as fault:
                    fault.setattr(journal_module.os, "fsync", failure)
                    return super().__call__()

        monkeypatch.setattr(driver, "PaidSelectionJournal", InterruptedJournal)
    scheduler = ControlledScheduler([{"success": False, "calls": 1, "bytes": 17, "elapsed_ms": 2.0}])
    updates = []
    result = driver._run_blocks(
        public=public, candidates=candidates, preparation=preparation,
        scheduler=scheduler, blocks=blocks, output=output,
        deadline=driver.time.perf_counter() + 60.0, record=campaign,
        on_update=lambda: updates.append(deepcopy(campaign)),
    )
    assert result is campaign
    assert reads == []
    attempts = int(boundary == "backend-failure")
    assert len(scheduler.calls) == attempts
    assert campaign["completed"] is False
    assert campaign["all_blocks_sealed"] is True
    assert campaign["attempted_plan_runs"] == attempts
    assert campaign["total_remote_calls"] is None
    assert campaign["known_total_remote_calls"] == attempts
    assert campaign["known_remote_calls"] == attempts
    assert campaign["stop_reason"]
    for block in campaign["blocks"]:
        assert len(block["queries"]) == 48
        assert len([method for query in block["queries"] for method in query["methods"]]) == 144
        assert block["full_ledger_seal_in_method_wall"] is False
        assert block["full_ledger_seal_ms"] >= 0
        assert block["full_ledger_seal_bytes"] == (output / block["measurement_file"]).stat().st_size
    for block in campaign["blocks"][1:]:
        assert block["status"] == "not_attempted"
        raw = json.loads((output / block["measurement_file"]).read_text())
        assert raw["total_remote_calls"] is None
        assert all(method["status"] == "not_attempted" and method["final_rows"] is None
                   and method["wall_ms"] is None and method["total_remote_calls"] is None
                   for query in raw["queries"] for method in query["methods"])
    before = deepcopy(campaign)
    evaluation = driver._evaluate_blocks(campaign, output, tmp_path / "toy-oracle")
    assert reads == [tmp_path / "toy-oracle"]
    assert campaign == before
    assert evaluation["oracle_load_count"] == 1
    assert len(evaluation["blocks"]) == 6
    assert all(len(block["queries"]) == 48 for block in evaluation["blocks"])
    assert evaluation["attempted_plan_count"] == attempts
    assert evaluation["attempted_final_count"] == attempts
    assert evaluation["indeterminate_plan_count"] == 1 - attempts
    assert evaluation["indeterminate_final_count"] == 1 - attempts
    assert evaluation["exact_plan_count"] == 0  # A failed empty result is not a correct empty answer.
    assert all(block["attempted_plan_count"] == 0 for block in evaluation["blocks"][1:])
    if not attempts:
        first = evaluation["blocks"][0]["queries"][0]["methods"][0]
        assert first["dispatch_status"] == "indeterminate"
        assert first["exact"] is None and first["actual_rows"] is None
