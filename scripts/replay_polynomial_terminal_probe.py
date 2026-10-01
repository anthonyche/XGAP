#!/usr/bin/env python3
"""Replay only P1's changed terminal-source branch and saved native decisions.

No backend calls or new exhaustive oracle runs. The original receipt pins the
inputs and unchanged compiler/cost-model code. Timings remain diagnostic only.
"""

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import random
import time
import tracemalloc

import run_polynomial_placement_probe as recipe

REPO = recipe.REPO


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reuse-model-replay", type=Path,
        help="Reuse all completed model cells from a pinned prior replay; rerun only saved native decisions")
    args = parser.parse_args()
    receipt_path = REPO / "experiments/artifacts/polynomial_planning_20260911.json"
    receipt = json.loads(receipt_path.read_text())
    inputs = {}
    for name in ("grid", "native"):
        path = Path(receipt[name]["path"])
        assert digest(path) == receipt[name]["sha256"], f"Changed frozen {name} input"
        inputs[name] = json.loads(path.read_text())
        assert inputs[name]["success"]
    changed = "src/xgap/runtime/semantic_placement.py"
    for file, sha in receipt["source_sha256"].items():
        if file != changed:
            assert digest(REPO / file) == sha, f"Changed dependency: {file}; cannot reuse the old oracle"
    record = {"schema": "p1-terminal-replay-result-v1", "success": False,
        "paper_result": False, "external_calls": 0, "new_exhaustive_oracle_runs": 0,
        "input_receipt_sha256": digest(receipt_path),
        "source_sha256": {file: digest(REPO / file) for file in receipt["source_sha256"]},
        "replay_script_sha256": digest(Path(__file__)),
        "input_sha256": {name: receipt[name]["sha256"] for name in inputs},
        "scope": "Only variable-row independent terminal cases; fixed-row runs retained unchanged",
        "timing_instrumentation": "tracemalloc during preparation/selection; diagnostic, not paper latency",
        "cells": [], "native_decision_replay": []}
    args.output.mkdir(parents=True, exist_ok=False)
    def save():
        (args.output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    began = time.monotonic()
    def budget():
        if time.monotonic() - began > 120:
            raise TimeoutError("P1 replay local 120-second budget exhausted")
    _, _, artifact = recipe.load_fixture()
    base = recipe.toy_backends(artifact)["fuseki"]
    mapping = recipe.RdfBackendMapping.from_artifact(artifact, backend_id="fuseki")
    if args.reuse_model_replay:
        prior = json.loads(args.reuse_model_replay.read_text())
        assert prior["source_sha256"] == record["source_sha256"]
        assert prior["input_sha256"] == record["input_sha256"]
        assert len(prior["cells"]) == 15
        for cell in prior["cells"]:
            assert len(cell["runs"]) == 10
            assert all(r["selection"]["certificate"]["kind"] == "exact_separable" for r in cell["runs"])
        record["cells"] = prior["cells"]
        record["reused_model_replay"] = {"path": str(args.reuse_model_replay),
            "sha256": digest(args.reuse_model_replay), "prior_success": prior["success"],
            "prior_error": prior.get("error"), "model_cells_complete": True}
    save()
    try:
        for original in (() if args.reuse_model_replay else inputs["grid"]["cells"]):
            budget()
            m, k = original["m"], original["k"]
            names = tuple(f"rdf_{i}" for i in range(k))
            backends = {b: replace(base, backend_id=b, backend_mapping=replace(mapping, backend_id=b),
                profile=replace(recipe.default_profile("fuseki"), backend_id=b)) for b in names}
            ops = tuple(recipe.SemanticOperator(f"s{i}", recipe.S.MATCH, (), (), recipe.V.BINDING_SET,
                {"node": {"label": "Person"}, "entity_field": "person"}) for i in range(m))
            program = recipe.SemanticGraphProgram("placement-scale", ops, tuple(op.operator_id for op in ops))
            tracemalloc.start()
            started = time.perf_counter()
            space = recipe.prepare_semantic_placements(program,
                operator_sources={op.operator_id: "toy" for op in ops},
                sources={"toy": recipe.LogicalSource("toy", "frozen-toy", names)}, backends=backends,
                max_local_options=m*k, max_observation_calls=m*k, max_remote_calls=m)
            cell = {"m": m, "k": k, "local_options": m*k, "product_domain": k**m,
                "preparation_ms_with_allocation_tracing": (time.perf_counter() - started) * 1000,
                "runs": []}
            record["cells"].append(cell)
            for old in original["runs"]:
                if not old["variable_row_estimates"]:
                    continue
                budget()
                seed = old["seed"]
                rng = random.Random(seed)
                snapshot = recipe.PlanObservationSnapshot("grid", str(seed), tuple(
                    recipe.RemoteEstimate(r.observation_key, r.backend_id, rng.randint(1, 100),
                        rng.randint(1, 40), rng.randint(1, 80), "controlled model table", str(seed))
                    for r in space.observation_requests), 1000, 0, 0.1)
                started = time.perf_counter()
                candidate, selected = space.select(snapshot)
                elapsed = (time.perf_counter() - started) * 1000
                cert = selected["certificate"]
                assert cert["baseline_ms"] == old["certificate"]["baseline_ms"]
                assert cert["kind"] == "exact_separable" and cert["ratio_bound"] == 1
                assert cert["upper_bound_ms"] <= old["certificate"]["upper_bound_ms"] + 1e-9
                assert selected["evaluated_plan_count"] <= 2
                assert selected["local_score_evaluations"] == m*k
                row = {"seed": seed, "snapshot": snapshot.to_dict(), "selection": selected,
                    "selected_source_bindings": candidate.plan.metadata["source_bindings"],
                    "selection_ms_with_allocation_tracing": elapsed,
                    "previous_upper_ms": old["certificate"]["upper_bound_ms"],
                    "previous_evaluated_plans": old["evaluated_plans"]}
                if "oracle_estimated_ms" in old:
                    optimum = old["oracle_estimated_ms"]
                    assert abs(cert["upper_bound_ms"] - optimum) <= 1e-9
                    row.update(reused_oracle_estimated_ms=optimum,
                               observed_model_regret_ratio=cert["upper_bound_ms"] / optimum)
                cell["runs"].append(row)
            assert len(cell["runs"]) == 10
            cell["peak_polynomial_traced_bytes"] = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()
            save()
        # Decisions only: no execution or service startup. The original native
        # timings/answers retain their original source checkpoint and provenance.
        for cold, warm in zip(inputs["native"]["binding_cases"], inputs["native"]["binding_warm_cases"]):
            budget()
            output = cold["agent_run"]["state"]["output"]
            old = output["planning_run"]
            plan = old["selected_plan"]
            identities = plan["metadata"]["logical_sources"]
            space = recipe.prepare_semantic_placements(
                recipe.SemanticGraphProgram.from_dict(output["bound_program"]),
                operator_sources=output["operator_sources"],
                sources={v["source_id"]: recipe.LogicalSource(**v, replica_backend_ids=("neo4j", "fuseki"))
                         for v in identities.values()}, backends=recipe.toy_backends(artifact),
                max_local_options=4, max_observation_calls=4,
                max_remote_calls=plan["max_remote_calls"], max_parallelism=plan["max_parallelism"])
            selected, decision = space.select(recipe.PlanObservationSnapshot.from_dict(old["observation"]["snapshot"]))
            for saved in (old, warm["agent_run"]["state"]["output"]["planning_run"]):
                assert selected.plan.to_dict() == saved["selected_plan"]
                assert decision["certificate"]["upper_bound_ms"] == saved["selection"]["certificate"]["upper_bound_ms"]
                if cold["query_id"] == "B04":
                    assert decision["certificate"]["kind"] == "exact_separable"
                    assert saved["selection"]["certificate"]["kind"] == "instance_gap"
                else:
                    assert decision == saved["selection"]
            record["native_decision_replay"].append({"id": cold["query_id"],
                "cold_and_warm_plans_and_primary_cost_unchanged": True, "external_calls": 0,
                "selection_unchanged": decision == old["selection"],
                "previous_certificate": old["selection"]["certificate"],
                "current_selection": decision})
        assert len(record["cells"]) == 15 and len(record["native_decision_replay"]) == 5
        record["success"] = True
    except Exception as error:
        record["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        record["elapsed_seconds"] = time.monotonic() - began
        save()
    print(json.dumps({"success": record["success"], "changed_model_runs": 150,
        "reused_oracle_values": 70, "native_decisions_replayed": 10, "external_calls": 0}))


if __name__ == "__main__":
    main()
