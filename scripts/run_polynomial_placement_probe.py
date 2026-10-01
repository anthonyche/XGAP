#!/usr/bin/env python3
"""P1 model-only grid: polynomial planning versus small exhaustive oracles.

No graph service, model or network call. This is planner development evidence,
not a real-data latency experiment. Grid frozen in research_experiment_plan_20260911.
"""

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import random
import sys
import time
import tracemalloc

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from xgap.backends.mapping import RdfBackendMapping
from xgap.compilers.features import default_profile
from xgap.experiments.toy_backbone import load_fixture
from xgap.experiments.toy_semantic import toy_backends
from xgap.runtime.planning import FederatedPlanSelector, PlanObservationSnapshot, RemoteEstimate
from xgap.runtime.semantic_placement import prepare_semantic_placements
from xgap.runtime.semantic_planning import LogicalSource, enumerate_semantic_plans
from xgap.semantic.program import SemanticGraphProgram, SemanticOperator, SemanticOperatorKind as S, SemanticValueKind as V


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-seconds", type=float, default=600)
    args = parser.parse_args()
    if not 0 < args.max_seconds <= 3600:
        parser.error("--max-seconds must be positive and at most3600")
    began = time.monotonic()
    def budget():
        if time.monotonic() - began > args.max_seconds:
            raise TimeoutError("P1 local probe time budget exhausted")
    args.output.mkdir(parents=True, exist_ok=False)
    _, _, mapping_artifact = load_fixture()
    base = toy_backends(mapping_artifact)["fuseki"]
    mapping = RdfBackendMapping.from_artifact(mapping_artifact, backend_id="fuseki")
    files = [Path(__file__), *(REPO / p for p in (
        "src/xgap/runtime/semantic_placement.py", "src/xgap/runtime/semantic_planning.py",
        "src/xgap/runtime/semantic_compiler.py", "src/xgap/runtime/planning.py",
        "src/xgap/runtime/contracts.py"))]
    record = {"experiment": "P1", "success": False, "paper_result": False,
        "external_calls": 0, "seeds": list(range(10)), "oracle_limit": 4096,
        "time_budget_seconds": args.max_seconds,
        "timing_instrumentation": "polynomial runs include tracemalloc overhead; oracle outside traced region",
        "source_sha256": {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        "cells": []}
    save = lambda: (args.output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    save()
    try:
        for m in (2, 4, 8, 16, 32):
            for k in (2, 4, 8):
                budget()
                names = tuple(f"rdf_{i}" for i in range(k))
                backends = {b: replace(base, backend_id=b, backend_mapping=replace(mapping, backend_id=b),
                    profile=replace(default_profile("fuseki"), backend_id=b)) for b in names}
                operators = tuple(SemanticOperator(f"s{i}", S.MATCH, (), (), V.BINDING_SET,
                    {"node": {"label": "Person"}, "entity_field": "person"}) for i in range(m))
                program = SemanticGraphProgram("placement-scale", operators, tuple(o.operator_id for o in operators))
                options = dict(operator_sources={o.operator_id: "toy" for o in operators},
                    sources={"toy": LogicalSource("toy", "frozen-toy", names)}, backends=backends,
                    max_observation_calls=m*k, max_remote_calls=m)
                cell = {"m": m, "k": k, "product_domain": k**m, "local_options": m*k,
                        "status": "running", "runs": []}
                record["cells"].append(cell); save()
                oracle = (enumerate_semantic_plans(program, max_candidates=4096, **options)
                          if k**m <= 4096 else None)
                tracemalloc.start()
                start = time.perf_counter()
                space = prepare_semantic_placements(program, max_local_options=m*k, **options)
                cell["preparation_ms_with_allocation_tracing"] = (time.perf_counter() - start) * 1000
                for variable in (False, True):
                    for seed in range(10):
                        budget()
                        rng = random.Random(seed)
                        snapshot = PlanObservationSnapshot("grid", str(seed), tuple(
                            RemoteEstimate(r.observation_key, r.backend_id, rng.randint(1, 100),
                                rng.randint(1, 40) if variable else 5, rng.randint(1, 80) if variable else 40,
                                "controlled model table", str(seed)) for r in space.observation_requests), 1000, 0, 0.1)
                        start = time.perf_counter(); _, selected = space.select(snapshot)
                        elapsed = (time.perf_counter() - start) * 1000
                        cert = selected["certificate"]
                        assert cert["upper_bound_ms"] <= cert["baseline_ms"]
                        assert selected["evaluated_plan_count"] <= selected["evaluation_bound"]
                        row = {"seed": seed, "variable_row_estimates": variable,
                            "selection_ms_with_allocation_tracing": elapsed,
                            "evaluated_plans": selected["evaluated_plan_count"],
                            "local_score_evaluations": selected["local_score_evaluations"],
                            "algorithm": selected["algorithm"], "certificate": cert}
                        cell["runs"].append(row)
                cell["peak_polynomial_traced_bytes"] = tracemalloc.get_traced_memory()[1]
                tracemalloc.stop()
                # Score the oracle after the measured region. It is never used
                # to build the online problem, snapshots, or selected plans.
                if oracle is not None:
                    for row in cell["runs"]:
                        budget()
                        rng = random.Random(row["seed"])
                        snapshot = PlanObservationSnapshot("grid", str(row["seed"]), tuple(
                            RemoteEstimate(r.observation_key, r.backend_id, rng.randint(1, 100),
                                rng.randint(1, 40) if row["variable_row_estimates"] else 5,
                                rng.randint(1, 80) if row["variable_row_estimates"] else 40,
                                "controlled model table", str(row["seed"])) for r in space.observation_requests), 1000, 0, 0.1)
                        optimum = min(FederatedPlanSelector().estimate(c.plan, snapshot).predicted_latency_ms for c in oracle.candidates)
                        cert = row["certificate"]
                        assert cert["lower_bound_ms"] <= optimum + 1e-9 <= cert["upper_bound_ms"] + 1e-9
                        if cert["kind"] == "exact_separable":
                            assert abs(cert["upper_bound_ms"] - optimum) <= 1e-9
                        row["oracle_estimated_ms"] = optimum
                        row["observed_model_regret_ratio"] = cert["upper_bound_ms"] / optimum
                cell["status"] = "passed"; save()
                print(json.dumps({"m": m, "k": k, "runs": 20, "oracle": oracle is not None,
                                  "peak_bytes": cell["peak_polynomial_traced_bytes"]}), flush=True)
        record["success"] = True
    except Exception as error:
        record["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if tracemalloc.is_tracing(): tracemalloc.stop()
        save()
    print(json.dumps({"success": record["success"], "cells": len(record["cells"]), "external_calls": 0}), flush=True)


if __name__ == "__main__":
    main()
