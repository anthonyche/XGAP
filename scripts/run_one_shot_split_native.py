"""One ordinary NL-only request over required split sources; zero new training.

Default prepares a frozen deployment and checks local inputs, with zero external
calls. --execute starts fresh owned stores, loads disjoint facts and makes one
model request plus at most one selected final execution. No retries or fallbacks.
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
from xgap.experiments.one_shot_split import FIXTURE, QUERY_ID, PROFILE, split_inputs, prepare_split_deployment
from xgap.experiments.one_shot_toy import load_one_shot_toy_provider, _DurableRecordingProvider
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import QueryArtifact
from xgap.planning.runtime_work_estimator import load_frozen_estimator


def now():
    return datetime.now(timezone.utc).isoformat()


def run(args):
    root = Path(args.output).resolve()
    if root == REPO or REPO in root.parents:
        raise ValueError("Native evidence must live outside the repository")
    root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    costs, running, handlers, ports, initial = {}, [], {}, None, None
    receipt = {"schema_version": PROFILE, "started_at": now(), "operation": "execute" if args.execute else "preflight",
        "success": False, "status": "preparing", "phase": "preflight", "external_model_calls": 0,
        "backend_calls": 0, "final_plan_executions": 0, "current_query_probe_calls": 0,
        "training_calls": 0, "fit_calls": 0, "automatic_retries": 0, "paper_result": False,
        "loads": [], "owned_services": [], "shutdown": [], "offline": {}, "evaluation": None}

    def write(name, data):
        return _write_once(root / name, data, costs, "persistence_ms")

    def fingerprints(products):
        files = _fingerprints(products, args.java, args.estimator)
        for path in [Path(__file__).resolve(), *sorted(p for p in FIXTURE.rglob("*") if p.is_file())]:
            files[str(path.resolve())] = _file(path)
        return files

    try:
        request, statistics, inputs, manifest = split_inputs(mode=args.mode)
        provider = load_one_shot_toy_provider(mode=args.mode, wire_profile="envelope-schema-v1",
            disable_thinking=args.disable_thinking)
        budget = provider.token_guard.check(provider.build_request_payload(request), call_kind="generation")
        if not budget["passed"]:
            raise ValueError("Split request exceeds the bounded model profile")
        if args.execute and not os.environ.get(provider.config.api_key_env):
            raise ValueError("The configured API-key environment variable is unset")
        products = {"neo4j": Path(args.runtime_root).resolve() / "neo4j-community-5.26.30",
                    "fuseki": Path(args.runtime_root).resolve() / "apache-jena-fuseki-5.6.0"}
        for binary in (products["neo4j"] / "bin/neo4j", products["fuseki"] / "fuseki-server", Path(args.java)):
            if not binary.is_file() or not os.access(binary, os.X_OK):
                raise ValueError("Prepared local runtime is missing")
        initial = fingerprints(products)
        write("input_fingerprints.json", initial)
        deploy_at = time.perf_counter()
        deployed = prepare_split_deployment(args.estimator, root / "frozen_deployment.json")
        frozen = load_frozen_estimator(root / "frozen_deployment.json")
        if frozen.to_dict() != deployed.to_dict():
            raise RuntimeError("Offline deployment did not round-trip")
        receipt["offline"].update(deployment_prepare_reload_ms=(time.perf_counter()-deploy_at)*1000,
            deployment_model_sha256=frozen.model_sha256,
            parent_model_sha256=frozen.trained_model.model_sha256,
            training_cost_scope="historical parent collection/fit; not incurred again",
            parent_training=frozen.to_dict()["training_provenance"],
            catalog_preparation_ms=None, catalog_cost_scope="previous offline fixture publication; unmeasured separately")
        write("manifest.json", {"fixture": manifest, "request": request.to_dict(),
            "statistics": statistics.to_dict(), "model_budget": budget, "provider_config": provider.config.safe_dict(),
            "maximum_model_calls": 1, "maximum_final_executions": 1,
            "max_final_remote_calls": request.context["one_shot_profile"]["max_remote_calls"],
            "training_calls": 0, "fit_calls": 0, "input_profile": "NL-only plus frozen source schema",
            "model_sha256": frozen.model_sha256, "source_replication": False})
        receipt["offline"]["preparation_ms"] = (time.perf_counter()-started)*1000
        if not args.execute:
            receipt.update(success=True, status="preflight_passed")
            return receipt

        def expired(signum, frame):
            raise TimeoutError("Split gate interrupted or reached its five-minute wall limit")
        for sig in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM):
            handlers[sig] = signal.signal(sig, expired)
        signal.alarm(300)
        write("execution_intent.json", {"maximum_model_calls": 1, "maximum_final_executions": 1,
            "training_calls": 0, "fit_calls": 0, "automatic_retries": 0})
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
            service = start_service(spec)
            running.append(service)
            owner = {"service_id": spec.service_id, "pid": service.process.pid, "started_at": now()}
            receipt["owned_services"].append(owner)
            write(spec.service_id + "-owner.json", owner)
            health = wait_for_service_health(service, timeout_seconds=60)
            write(spec.service_id + "-health.json", health.to_dict())
            if not health.success:
                raise RuntimeError("Owned split service failed readiness; no restart")
        receipt["offline"]["service_setup_ms"] = (time.perf_counter()-setup_at)*1000
        neo = Neo4jClient(BackendDescriptor("neo4j", "neo4j", "cypher", "property_graph", runtime={"timeout_seconds": 35}))
        descriptor = BackendDescriptor("fuseki", "fuseki", "sparql", "rdf", runtime={"timeout_seconds": 35})
        rdf, loader = FusekiClient(descriptor), FusekiGraphStoreFixtureLoader(descriptor)
        neo.http_url, neo.database = nu, "neo4j"
        rdf.base_url, rdf.dataset = fu, "toy"
        loader.base_url, loader.dataset = fu, "toy"
        load_at = time.perf_counter()
        for name, action in (("neo4j", lambda: neo.execute(QueryArtifact("split-profiles-load", "cypher",
                (FIXTURE / "load.cypher").read_text(), kind="native"))),
                ("fuseki", lambda: loader.load(FIXTURE / "load.ttl"))):
            write(name + "-load-intent.json", {"status": "started"})
            result = action()
            receipt["loads"].append(write(name + "-load.json", result.to_dict()))
            if not result.success:
                raise RuntimeError("Split fixture loading failed")
        receipt["offline"]["fixture_load_ms"] = (time.perf_counter()-load_at)*1000
        write("offline_receipt.json", receipt["offline"])
        receipt["phase"] = "ordinary_nl_request"
        write("request_intent.json", {"request": request.to_dict(), "model_sha256": frozen.model_sha256,
            "maximum_model_calls": 1, "maximum_final_executions": 1, "gold_accessed": False})
        recorder = _DurableRecordingProvider(provider, root / "interpretation.json")
        result = run_question(request, recorder, mode=args.mode, estimator=frozen,
            **inputs, backend_clients={"neo4j": neo, "fuseki": rdf})
        sealed = write("result.json", result)
        receipt.update(external_model_calls=result["interpretation_external_calls"],
            backend_calls=result["backend_remote_calls"], final_plan_executions=result["final_plan_executions"],
            input_tokens=result["input_tokens"], output_tokens=result["output_tokens"],
            online_end_to_end_ms=result["end_to_end_ms"], status=result["status"])
        # First semantic/answer gold read occurs after the complete result is sealed.
        expected = json.loads((FIXTURE / "gold/expected_rows.json").read_text())
        canonical = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
        exact = result["success"] and canonical(result["answer_rows"]) == canonical(expected)
        identities = result.get("selected_plan", {}).get("metadata", {}).get("source_identities", {})
        required_sources = set(identities) == {"neo4j", "fuseki"}
        receipt["evaluation"] = {"execution_success": result["success"], "answer_exact": exact,
            "required_sources_in_selected_plan": required_sources, "expected_rows": expected,
            "sealed_result_sha256": sealed["sha256"], "paper_result": False}
        write("evaluation.json", receipt["evaluation"])
        receipt.update(success=bool(exact and required_sources),
            status="completed" if exact and required_sources else result["status"] + ":gate_not_accepted")
    except BaseException as error:
        receipt.update(success=False, status="failed", error_type=type(error).__name__, error=str(error))
        if receipt["phase"] == "ordinary_nl_request" and not (root / "result.json").is_file():
            receipt.update(external_model_calls=None, backend_calls=None, final_plan_executions=None)
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
                after = fingerprints(products)
                receipt["input_unchanged"] = after == initial
                write("input_fingerprints_after.json", after)
                if after != initial:
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
    parser.add_argument("--estimator", required=True, help="Unchanged trained v2 model")
    parser.add_argument("--output", required=True)
    parser.add_argument("--mode", choices=("precision", "performance"), default="performance")
    parser.add_argument("--disable-thinking", action="store_true")
    parser.add_argument("--execute", action="store_true")
    receipt = run(parser.parse_args())
    print(json.dumps({k: receipt.get(k) for k in ("success", "status", "external_model_calls", "backend_calls", "final_plan_executions")}))
    return 0 if receipt["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
