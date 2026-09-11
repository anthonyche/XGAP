"""Two post-execution scoring checks; no native driver entrypoint is run."""

from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def native_evaluation(monkeypatch):
    script = Path(__file__).resolve().parents[1] / "scripts/run_finbench_paid_selection_native.py"
    spec = importlib.util.spec_from_file_location("controlled_finbench_native_evaluation", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    opened = []

    def load_toy_answers(path):
        opened.append(path)
        return {
            "manifest": {"workload_sha256": "a" * 64},
            "sealed_oracles": {"queries": {
                f"m15-fb-confirmatory-48-f{family}-{index:02d}": {"final_rows": []}
                for family in (1, 2, 3) for index in range(1, 17)
            }},
        }

    monkeypatch.setattr(module, "load_finbench_primary_workload", load_toy_answers)
    return module, opened


def _action(role, *, status="not_attempted", success=None):
    return {
        "role": role,
        "status": status,
        "plan_id": f"controlled-{role}",
        "physical_strategy": "controlled-strategy",
        "runtime_result": None if success is None else {"success": success, "final_rows": []},
    }


def _measurement():
    queries = []
    for family in (1, 2, 3):
        family_id = (
            "f1_direct_transfer_control", "f2_temporal_path_control", "f3_aggregate_risk_ranking"
        )[family - 1]
        for index in range(1, 17):
            methods = []
            for method_id in ("fixed_hash", "fixed_bind", "paid_selection"):
                actions = []
                if index == 1:
                    if method_id == "paid_selection":
                        actions.extend([_action("acquisition"), _action("acquisition")])
                    actions.append(_action("final"))
                methods.append({"method_id": method_id, "executions": actions})
            queries.append({
                "query_id": f"m15-fb-confirmatory-48-f{family}-{index:02d}",
                "family_id": family_id,
                "split_role": "heldout_family" if family == 3 else "crossfit_seen_family",
                "integration_exposed": index == 1,
                "methods": methods,
            })
    return {"executions_sealed_before_evaluation": True, "queries": queries}


def test_unattempted_final_slots_keep_full_denominator_and_unknown_scores(native_evaluation, tmp_path):
    module, opened = native_evaluation
    measurement = _measurement()
    measurement["queries"][0]["methods"][0]["executions"] = [
        _action("final", status="completed", success=True)
    ]
    before = deepcopy(measurement)
    loaded_callbacks = []
    evaluation = module._evaluate(
        measurement, tmp_path / "toy-oracle", on_oracle_loaded=lambda: loaded_callbacks.append(True)
    )

    assert opened == [tmp_path / "toy-oracle"]
    assert loaded_callbacks == [True]
    assert measurement == before
    assert len(evaluation["queries"]) == 48
    assert [row["query_id"] for row in evaluation["queries"]] == [row["query_id"] for row in before["queries"]]
    assert evaluation["attempted_final_count"] == 1  # Eight reserved final slots have not run.
    assert evaluation["exact_final_count"] == 1
    assert evaluation["attempted_acquisition_count"] == 0
    assert evaluation["exact_acquisition_count"] == 0
    assert evaluation["attempted_plan_count"] == 1
    assert evaluation["exact_plan_count"] == 1
    first = evaluation["queries"][0]["methods"][0]
    assert first["exact"] is True and first["actual_rows"] == []
    others = [method for query in evaluation["queries"] for method in query["methods"]][1:]
    assert len(others) == 143
    assert all(method["execution_status"] == "not_attempted" and method["exact"] is None
               and method["actual_rows"] is None for method in others)
    acquisitions = [action for method in others for action in method["acquisitions"]]
    assert len(acquisitions) == 6
    assert all(action["exact"] is None and action["actual_rows"] is None for action in acquisitions)
    assert sum(query["split_role"] == "heldout_family" for query in evaluation["queries"]) == 16
    assert sum(query["integration_exposed"] for query in evaluation["queries"]) == 3


def test_final_and_acquisition_audits_separate_failure_empty_and_unknown(native_evaluation, tmp_path):
    module, opened = native_evaluation
    measurement = _measurement()
    fixed_hash, fixed_bind, paid = measurement["queries"][0]["methods"]
    fixed_hash["executions"] = [_action("final", status="completed", success=True)]
    fixed_bind["executions"] = [_action("final", status="failed", success=False)]
    paid["executions"] = [
        _action("acquisition", status="completed", success=True),
        _action("acquisition", status="failed", success=False),
        _action("final", status="unknown"),
    ]
    # A separate partial record contributes an unknown acquisition, never a free success.
    measurement["queries"][16]["methods"][2]["executions"][0] = _action(
        "acquisition", status="unknown"
    )
    before = deepcopy(measurement)
    evaluation = module._evaluate(measurement, tmp_path / "toy-oracle")

    assert opened == [tmp_path / "toy-oracle"]
    assert measurement == before
    assert evaluation["attempted_final_count"] == 3
    assert evaluation["exact_final_count"] == 1
    assert evaluation["attempted_acquisition_count"] == 3
    assert evaluation["exact_acquisition_count"] == 1
    assert evaluation["attempted_plan_count"] == 6
    assert evaluation["exact_plan_count"] == 2
    success, failed, unknown = evaluation["queries"][0]["methods"]
    assert success["exact"] is True and success["actual_rows"] == []
    assert failed["execution_status"] == "failed" and failed["exact"] is False
    assert failed["actual_rows"] is None
    assert unknown["execution_status"] == "unknown" and unknown["exact"] is None
    assert unknown["actual_rows"] is None
    acquired, failed_acquisition = unknown["acquisitions"]
    assert acquired["exact"] is True and acquired["actual_rows"] == []
    assert failed_acquisition["exact"] is False and failed_acquisition["actual_rows"] is None
    unknown_acquisition = evaluation["queries"][16]["methods"][2]["acquisitions"][0]
    assert unknown_acquisition["execution_status"] == "unknown"
    assert unknown_acquisition["exact"] is None and unknown_acquisition["actual_rows"] is None
