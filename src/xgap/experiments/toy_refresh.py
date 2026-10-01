"""A1 mechanism gate on B04: actual queries with declared stale-history inputs.

This is not a measured natural drift or paper performance experiment. The
historical cost table intervention is explicit; current backend reports are raw.
"""

from copy import deepcopy
from dataclasses import replace

from xgap.agent.memory import InMemoryStore
from xgap.experiments.toy_binding import execute_binding_case
from xgap.runtime.planning import PlanObservationSnapshot
from xgap.runtime.semantic_memory import SemanticPlanMemory
from xgap.runtime.semantic_refresh import SemanticRefreshPolicy


def execute_refresh_ablation(case, mapping, *, clients, memory, record, on_update):
    if case["id"] != "B04":
        raise ValueError("The frozen A1 development gate contains only B04")
    history = memory.store.records()
    if len(history) != 1:
        raise ValueError("A1 requires the one complete cold B04 observation record")
    original = history[0]
    snapshot = PlanObservationSnapshot.from_dict(original.value["snapshot"])
    if {e.backend_id for e in snapshot.estimates} != {"neo4j", "fuseki"} or len(snapshot.estimates) != 2:
        raise ValueError("A1 requires both native replicas in its complete history")
    version = snapshot.version + "/synthetic-stale-A1"
    # Force a known old preference without rewriting any current observation.
    # Empty old rows versus the real nonempty B04 result make this an explicit
    # cardinality AND latency intervention, not a naturally observed drift.
    stale = replace(snapshot, version=version, estimates=tuple(replace(e,
        elapsed_ms=0.0 if e.backend_id == "neo4j" else 1e-9,
        row_count=0, row_width_bytes=1, source="A1 synthetic historical cost-table intervention",
        version=version) for e in snapshot.estimates))
    entry = replace(original, version=version, value={**deepcopy(original.value), "snapshot": stale.to_dict()},
        source="A1 controlled history; original acquisition retained separately")
    modes = ("refresh_reselect", "refresh_only", "no_refresh")
    record.update(success=False, paper_result=False, live_llm=False,
        intervention={"kind": "synthetic historical cardinality and latency",
            "old_rows": 0, "old_width_bytes": 1,
            "old_elapsed_ms": {"neo4j": 0.0, "fuseki": 1e-9},
            "current_backend_reports_modified": False,
            "performance_claim": False},
        original_history=original.to_dict(), shared_history=entry.to_dict(),
        arms=[{"mode": mode, "status": "not_attempted", "success": False,
               "contract_passed": False} for mode in modes])
    on_update()
    try:
        for arm in record["arms"]:
            store = InMemoryStore(clock=memory.clock)
            store.put(deepcopy(entry))
            arm_memory = SemanticPlanMemory(store, memory.environment_episode, memory.max_age_seconds, memory.clock)
            arm["status"] = "started"
            on_update()
            result = execute_binding_case(case, mapping, clients=clients, plan_memory=arm_memory,
                validate_candidates=False, refresh_policy=SemanticRefreshPolicy(arm["mode"]))
            arm.update(result, status="checking_contract", success=False,
                       execution_answer_success=result["success"])
            on_update()
            if not result["success"]:
                raise ValueError("A1 arm failed; retain the partial evidence without retry")
            run = result["agent_run"]["state"]["output"]["planning_run"]
            observed = 0 if arm["mode"] == "no_refresh" else 1
            expected_backend = "fuseki" if arm["mode"] == "refresh_reselect" else "neo4j"
            checks = {"one_or_zero_profile_attempts": run["observation_calls"] == observed,
                "one_execution_call": run["execution_calls"] == 1,
                "expected_backend": set(run["selected_plan"]["metadata"]["source_bindings"].values()) == {expected_backend},
                "expected_selection_count": run["refresh"]["selection_runs"] == (2 if arm["mode"] == "refresh_reselect" else 1),
                "historical_cost_retained": run["memory"]["historical_acquisition"] == original.value["acquisition"],
                "memory_read_only": run["memory"]["writes"] == 0 and store.records()[0].to_dict() == entry.to_dict()}
            arm["contract_checks"] = checks
            if not all(checks.values()):
                raise ValueError("A1 mechanism contract failed: " + ", ".join(k for k, ok in checks.items() if not ok))
            arm.update(contract_passed=True, success=True, status="completed")
            on_update()
        runs = [a["agent_run"]["state"]["output"]["planning_run"] for a in record["arms"]]
        assert len({r["refresh"]["initial_selection"]["selected_plan_id"] for r in runs}) == 1
        assert runs[0]["refresh"]["request"] == runs[1]["refresh"]["request"]
        record["current_method_remote_calls"] = sum(r["total_remote_calls"] for r in runs)
        record["success"] = True
    except Exception as error:
        record["error"] = f"{type(error).__name__}: {error}"
        for arm in record["arms"]:
            if arm["status"] in {"started", "checking_contract"}:
                arm["error"] = record["error"]
        raise
    finally:
        if not record["success"]:
            for arm in record["arms"]:
                if arm["status"] == "started":
                    arm["status"] = "failed"
                elif arm["status"] == "checking_contract":
                    arm["status"] = "contract_failed"
                elif arm["status"] == "completed" and not arm["contract_passed"]:
                    arm["status"] = "contract_failed"
                    arm["success"] = False
                elif arm["status"] == "not_attempted":
                    arm["status"] = "not_attempted_after_failure"
        on_update()
    return record
