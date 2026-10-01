"""One bounded offline tiny collection, freeze, and excluded deterministic request.

Default is a zero-call preflight. Explicit --execute starts two owned local stores,
loads the unchanged tiny graph, warms each endpoint once, executes the 28 declared
training plans once, fits/freezes v2 and runs one new excluded ordinary request.
No LLM, current-query probing, alternative test runs, retries or benchmark sweep.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from run_one_shot_tiny_native import _file, _fingerprints, _write_once
from xgap.agent.question import run_question
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.experiments.m15_fixture_loader import FusekiGraphStoreFixtureLoader
from xgap.experiments.m15_native_services import (LoopbackPortReservations, ServiceSpec,
    _fuseki_server_configuration, _neo4j_configuration, inspect_java_runtime,
    start_service, stop_service, wait_for_service_health)
from xgap.experiments.tiny_work_training import (PROFILE, HELDOUT_ID, EXCLUDED_IDS,
    prepare_tiny_work_training, heldout_expected_rows)
from xgap.experiments.toy_backbone import DEFAULT_FIXTURE
from xgap.experiments.toy_binding import BUNDLE_FIXTURE
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import QueryArtifact
from xgap.planning.runtime_estimator import RuntimeTrainingSample
from xgap.planning.runtime_work_estimator import fit_work_estimator, load_frozen_estimator
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.semantic_planning import LogicalSource
from xgap.semantic.interpretation import InterpretationRequest, InterpretationResponse
from xgap.semantic.interpretation_candidates import SCHEMA as CANDIDATE_SCHEMA
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


def now():
    return datetime.now(timezone.utc).isoformat()


class DeclaredSemanticRequest:
    """Controlled input for the deterministic chain; not an LLM-quality result."""
    provider_id = "declared-independent-tiny-semantic-request"

    def __init__(self, program):
        self.program, self.calls = program, 0

    def interpret(self, request):
        if self.calls:
            raise ValueError("The declared semantic request can be read only once")
        self.calls += 1
        return InterpretationResponse({"schema_version": CANDIDATE_SCHEMA, "candidates": [{
            "candidate_id": "declared", "quality_proxy": None, "program": self.program.to_dict(),
            "operator_sources": {"walk": "toy", "profiles": "toy"}}]},
            external_calls=0, input_tokens=0, output_tokens=0,
            provenance={"kind": "declared_semantic_input", "usage_reported": True,
                        "interpretation_quality_evaluated": False})


def run(args):
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    costs, running, handlers, ports, initial = {}, [], {}, None, None
    receipt = {"schema_version": PROFILE, "started_at": now(), "operation": "execute" if args.execute else "preflight",
        "success": False, "status": "preparing", "phase": "preflight", "external_model_calls": 0,
        "current_query_probe_calls": 0, "automatic_retries": 0, "paper_result": False,
        "training": [], "warmup": [], "loads": [], "owned_services": [], "shutdown": [], "offline": {},
        "heldout_final_executions": 0, "heldout_backend_calls": 0}

    def write(name, data, category="persistence_ms"):
        return _write_once(root / name, data, costs, category)

    try:
        statistics, entries, heldout, backends = prepare_tiny_work_training()
        products = {"neo4j": Path(args.runtime_root).resolve() / "neo4j-community-5.26.30",
                    "fuseki": Path(args.runtime_root).resolve() / "apache-jena-fuseki-5.6.0"}
        for binary in (products["neo4j"] / "bin/neo4j", products["fuseki"] / "fuseki-server", Path(args.java)):
            if not binary.is_file() or not os.access(binary, os.X_OK):
                raise ValueError("Prepared local native runtime is missing")
        pin = json.loads((BUNDLE_FIXTURE / "reference.json").read_text())
        initial = _fingerprints(products, args.java)
        initial[str(Path(__file__).resolve())] = _file(__file__)
        write("input_fingerprints.json", initial)
        max_training_calls = sum(sum(n.kind in (R.REMOTE_QUERY, R.REMOTE_BIND_QUERY) for n in e["plan"].nodes) for e in entries)
        manifest = {"schema_version": PROFILE, "statistics": statistics.to_dict(),
            "training": [{**e, "plan": e["plan"].to_dict()} for e in entries],
            "excluded_query_ids": list(EXCLUDED_IDS), "heldout_program": heldout.to_dict(),
            "training_plan_count": len(entries), "maximum_training_calls": max_training_calls,
            "maximum_warmup_calls": 2, "maximum_heldout_final_executions": 1,
            "maximum_heldout_backend_calls": 2, "maximum_model_calls": 0,
            "warmup_scope": "one constant query per endpoint before training; timed/counted separately",
            "fit": {"algorithm": "fixed_sweep_nonnegative_relative_ridge_v1", "sweeps": 128, "ridge": 1e-4},
            "order_seed": 2026091202, "fixture_reused_unchanged": True,
            "query_cache_order_scope": "one fixed interleaving, no repetitions; cold-specific effects not removed",
            "heldout_input_scope": "declared semantic program through ordinary performance entry; not model interpretation"}
        receipt["manifest"] = write("manifest.json", manifest)
        receipt["offline"]["preparation_ms"] = (time.perf_counter()-started)*1000
        if not args.execute:
            receipt.update(success=True, status="preflight_passed")
            return receipt

        def expired(signum, frame):
            raise TimeoutError("Tiny independent collection interrupted or reached its five-minute limit")
        for sig in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM):
            handlers[sig] = signal.signal(sig, expired)
        signal.alarm(300)
        write("execution_intent.json", {"manifest_sha256": receipt["manifest"]["sha256"],
            "maximum_training_calls": max_training_calls, "maximum_warmup_calls": 2,
            "maximum_heldout_final_executions": 1, "automatic_retries": 0})
        setup_at = time.perf_counter()
        receipt["phase"] = "owned_service_setup"
        write("java.json", inspect_java_runtime(args.java, required_major=21).to_dict())
        state = root / "state"
        for relative in ("neo4j/data", "neo4j/transactions", "neo4j/logs", "neo4j/run", "neo4j/import", "neo4j/plugins", "fuseki"):
            (state / relative).mkdir(parents=True)
        conf = state / "neo4j-conf"
        shutil.copytree(products["neo4j"] / "conf", conf)
        ports = LoopbackPortReservations.acquire(3)
        np, bp, fp = ports.ports
        (conf / "neo4j.conf").write_text(_neo4j_configuration(neo4j_root=products["neo4j"], state_root=state,
            http_port=np, bolt_port=bp, resource_profile={"heap_initial_size": "256m", "heap_max_size": "512m",
            "pagecache_size": "128m"}, query_timeout_seconds=30))
        (state / "fuseki/config.ttl").write_text(_fuseki_server_configuration(query_timeout_seconds=30))
        nu, fu = f"http://127.0.0.1:{np}", f"http://127.0.0.1:{fp}"
        specs = (
            ServiceSpec("neo4j", "neo4j", "5.26.30", (str(products["neo4j"] / "bin/neo4j"), "console"),
                products["neo4j"], {"JAVACMD": args.java, "NEO4J_CONF": str(conf), "NEO4J_HOME": str(products["neo4j"])},
                nu + "/db/neo4j/tx/commit", root / "neo4j.log"),
            ServiceSpec("fuseki", "fuseki", "5.6.0", (str(products["fuseki"] / "fuseki-server"),
                "--localhost", "--ping", "--port", str(fp), "--update", "--mem", "/toy"),
                products["fuseki"], {"JAVA": args.java, "FUSEKI_HOME": str(products["fuseki"]),
                    "FUSEKI_BASE": str(state / "fuseki"), "JVM_ARGS": "-Xms128m -Xmx512m"},
                fu + "/$/ping", root / "fuseki.log"))
        write("service_specs.json", [s.to_dict() for s in specs])
        for i, spec in enumerate(specs):
            for slot in ((0, 1) if i == 0 else (2,)):
                ports.release(slot)
            service = start_service(spec); running.append(service)
            owner = {"service_id": spec.service_id, "pid": service.process.pid, "started_at": now()}
            receipt["owned_services"].append(owner); write(spec.service_id + "-owner.json", owner)
            health = wait_for_service_health(service, timeout_seconds=60)
            write(spec.service_id + "-health.json", health.to_dict())
            if not health.success:
                raise RuntimeError("Owned tiny service failed readiness; no restart")
        receipt["offline"]["service_setup_ms"] = (time.perf_counter()-setup_at)*1000
        neo = Neo4jClient(BackendDescriptor("neo4j", "neo4j", "cypher", "property_graph", runtime={"timeout_seconds": 35}))
        descriptor = BackendDescriptor("fuseki", "fuseki", "sparql", "rdf", runtime={"timeout_seconds": 35})
        rdf, loader = FusekiClient(descriptor), FusekiGraphStoreFixtureLoader(descriptor)
        neo.http_url, neo.database = nu, "neo4j"
        rdf.base_url, rdf.dataset = fu, "toy"
        loader.base_url, loader.dataset = fu, "toy"
        load_at = time.perf_counter()
        for name, action in (("neo4j", lambda: neo.execute(QueryArtifact("independent-tiny-load", "cypher",
                (DEFAULT_FIXTURE / "load.cypher").read_text(), kind="native"))),
                ("fuseki", lambda: loader.load(DEFAULT_FIXTURE / "load.ttl"))):
            write(name + "-load-intent.json", {"status": "started"})
            result = action(); receipt["loads"].append(write(name + "-load.json", result.to_dict()))
            if not result.success:
                raise RuntimeError("Unchanged tiny graph loading failed")
        receipt["offline"]["fixture_load_ms"] = (time.perf_counter()-load_at)*1000
        for name, client, language, query in (("neo4j", neo, "cypher", "RETURN 1 AS ready"),
                                            ("fuseki", rdf, "sparql", "SELECT (1 AS ?ready) WHERE {}")):
            before = time.perf_counter()
            write(name + "-warmup-intent.json", {"status": "started", "query": query})
            result = client.execute(QueryArtifact("independent-constant-warmup", language, query, kind="native"))
            receipt["warmup"].append({"backend": name, "elapsed_ms": (time.perf_counter()-before)*1000,
                "query_calls": 1, "success": result.success, "measurement": write(name + "-warmup.json", result.to_dict())})
            if not result.success:
                raise RuntimeError("Constant warmup failed; no retry")
        plugins = BackendPluginRegistry()
        for client in (neo, rdf):
            plugins.register(NativeBackendPlugin(client.backend_id, client))
        scheduler = FederatedScheduler(BackendInvokeTool(plugins))
        samples, collection_at = [], time.perf_counter()
        for index, entry in enumerate(entries):
            receipt["phase"] = f"training-{index+1:02}"
            current = {"query_id": entry["query_id"], "status": "started"}
            receipt["training"].append(current)
            write(f"training-{index+1:02}-intent.json", current)
            result = scheduler.execute(entry["plan"], goal_id=entry["query_id"])
            evidence = write(f"training-{index+1:02}-measurement.json", {"query_id": entry["query_id"],
                "split_role": "training", "runtime_result": result.to_dict(), "gold_used": False})
            current.update(status="completed" if result.success else "failed", measurement=evidence,
                elapsed_ms=result.elapsed_ms, remote_calls=result.total_remote_calls)
            if not result.success:
                raise RuntimeError("Independent training plan failed; no retry or later fit")
            samples.append(RuntimeTrainingSample(f"training-{index+1:02}", entry["query_id"], entry["plan"],
                result.elapsed_ms, evidence["sha256"]))
        collection_ms = (time.perf_counter()-collection_at)*1000
        calls = sum(t["remote_calls"] for t in receipt["training"])
        collection = write("training_collection.json", {"training": receipt["training"], "excluded_query_ids": list(EXCLUDED_IDS),
            "collection_elapsed_ms": collection_ms, "collection_remote_calls": calls, "manifest": receipt["manifest"]})
        receipt["phase"] = "offline_fit_and_freeze"
        model = fit_work_estimator(samples, statistics=statistics, training_id=PROFILE,
            model_version="tiny-work-measured-v2", training_kind="measured_training", excluded_query_ids=EXCLUDED_IDS,
            collection_ref="training_collection.json#sha256="+collection["sha256"],
            collection_elapsed_ms=collection_ms, collection_remote_calls=calls)
        write("frozen_work_estimator.json", model.to_dict())
        reload_at = time.perf_counter()
        frozen = load_frozen_estimator(root / "frozen_work_estimator.json")
        if frozen.to_dict() != model.to_dict():
            raise RuntimeError("Frozen work estimator failed round-trip")
        receipt["offline"].update(collection_elapsed_ms=collection_ms, collection_remote_calls=calls,
            estimator_reload_ms=(time.perf_counter()-reload_at)*1000,
            fit=model.to_dict()["training_provenance"]["offline_cost"], model_sha256=model.model_sha256)
        write("offline_receipt.json", receipt["offline"])
        receipt["phase"] = "excluded_ordinary_request"
        request = InterpretationRequest("For source node id c, return outgoing KNOWS person and edge where target age is at least 28.",
            {"query_id": HELDOUT_ID, "requested_output": {"kind": "binding_set", "fields": ["person", "edge"]}})
        write("heldout_intent.json", {"query_id": HELDOUT_ID, "model_sha256": frozen.model_sha256,
            "input_scope": "independent declared semantic input, no live interpretation", "maximum_final_executions": 1})
        result = run_question(request, DeclaredSemanticRequest(heldout), mode="performance", estimator=frozen,
            catalog_root=BUNDLE_FIXTURE / pin["root"], catalog_hash=pin["bundle_hash"],
            sources={"toy": LogicalSource("toy", statistics.entries[0].snapshot_version, ("neo4j", "fuseki"))},
            backends=backends, backend_clients={"neo4j": neo, "fuseki": rdf})
        sealed = write("heldout_result.json", result)
        receipt.update(heldout_final_executions=result["final_plan_executions"], heldout_backend_calls=result["backend_remote_calls"])
        canonical = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
        # First access to the independent expected answer follows the sealed return.
        expected = heldout_expected_rows()
        exact = result["success"] and canonical(result["answer_rows"]) == canonical(expected)
        evaluation = {"query_id": HELDOUT_ID, "execution_success": result["success"], "answer_exact": exact,
            "expected_rows": expected, "inference_result_sealed_sha256": sealed["sha256"], "paper_result": False}
        write("heldout_evaluation.json", evaluation)
        receipt.update(success=bool(exact), status="completed" if exact else "heldout_failed", heldout_evaluation=evaluation)
    except BaseException as error:
        receipt.update(success=False, status="failed", error_type=type(error).__name__, error=str(error))
        for entry in receipt["training"]:
            if entry["status"] == "started":
                entry["status"] = "indeterminate"
        if receipt["phase"] == "excluded_ordinary_request" and not (root / "heldout_result.json").is_file():
            receipt.update(heldout_final_executions=None, heldout_backend_calls=None)
        write("failure.json", {k: receipt[k] for k in ("phase", "error_type", "error")})
    finally:
        try:
            write("before_cleanup.json", receipt)
        finally:
            if handlers:
                signal.alarm(0)
            for sig, previous in handlers.items():
                signal.signal(sig, previous)
            for service in reversed(running):
                try:
                    receipt["shutdown"].append(stop_service(service, timeout_seconds=30).to_dict())
                except Exception as error:
                    receipt["shutdown"].append({"pid": service.process.pid, "success": False, "error_type": type(error).__name__})
            if ports:
                ports.close()
            if initial is not None:
                after = _fingerprints(products, args.java)
                after[str(Path(__file__).resolve())] = _file(__file__)
                receipt["input_unchanged"] = after == initial
                write("input_fingerprints_after.json", after)
                if not receipt["input_unchanged"]:
                    receipt.update(success=False, status="input_changed")
            receipt["owned_processes_terminal"] = all(s.process.poll() is not None for s in running)
            if not receipt["owned_processes_terminal"]:
                receipt.update(success=False, status="cleanup_incomplete")
            receipt.update(finished_at=now(), lifecycle_ms=(time.perf_counter()-started)*1000,
                harness_persistence_ms=dict(costs))
            write("receipt.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--java", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--execute", action="store_true")
    r = run(parser.parse_args())
    print(json.dumps({k: r.get(k) for k in ("success", "status", "operation", "external_model_calls", "heldout_final_executions", "heldout_backend_calls")}))
    return 0 if r["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
