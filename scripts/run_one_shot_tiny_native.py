"""One new tiny NL request, with separate measured offline training and owned stores.

The default is a local, zero-call preflight. --execute starts fresh loopback
Neo4j/Fuseki stores and loads the existing five-node fixture. --estimator reuses
an accepted frozen model without training or fit; otherwise four declared
training plans are measured once and a ridge estimator frozen. Only B01 runs.
There are no benchmark loops, candidate probes, model retries or fallback runs.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.experiments.m15_fixture_loader import FusekiGraphStoreFixtureLoader
from xgap.experiments.m15_native_services import (
    LoopbackPortReservations, ServiceSpec, _fuseki_server_configuration,
    _neo4j_configuration, inspect_java_runtime, start_service, stop_service,
    wait_for_service_health,
)
from xgap.experiments.one_shot_toy import (
    BASE_URL, MODEL, load_one_shot_toy_provider, one_shot_toy_inputs,
    one_shot_toy_preflight, run_one_shot_toy,
)
from xgap.experiments.toy_backbone import DEFAULT_FIXTURE
from xgap.experiments.toy_binding import BUNDLE_FIXTURE, FIXTURE as BINDING_FIXTURE, INTAKE_FIXTURE
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import QueryArtifact
from xgap.planning.runtime_estimator import (
    FrozenRuntimeEstimator, FrozenSourceStatistics, SourceStatistics,
    RuntimeTrainingSample, fit_runtime_estimator,
)
from xgap.runtime.physical_strategies import prepare_physical_strategies
from xgap.runtime.scheduler import FederatedScheduler
from xgap.semantic.program import SemanticGraphProgram
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


PROFILE = "xgap-one-shot-owned-tiny-native-v1"
QUERY_ID = "B01"
EXCLUDED_IDS = ("B01", "B02", "B03", "B04", "B05")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _file(path):
    content = Path(path).read_bytes()
    return {"path": str(Path(path).resolve()), "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest()}


def _write_once(path, value, costs, category):
    started = time.perf_counter()
    try:
        with Path(path).open("x", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        costs[category] = costs.get(category, 0.0) + (time.perf_counter() - started) * 1000
    return _file(path)


def _fingerprints(products, java, estimator_path=None):
    paths = set((REPO / "src/xgap").rglob("*.py"))
    paths.add(Path(__file__).resolve())
    for directory in (DEFAULT_FIXTURE, BUNDLE_FIXTURE, BINDING_FIXTURE, INTAKE_FIXTURE,
                      REPO / "descriptors/backends", REPO / "prompts/interpretation"):
        paths.update(p for p in directory.rglob("*") if p.is_file())
    paths.update((products["neo4j"] / "bin/neo4j", products["fuseki"] / "fuseki-server",
                  REPO / "services/m15-native-runtime.lock.json", Path(java).resolve()))
    if estimator_path is not None:
        paths.add(Path(estimator_path).resolve())
    return {str(p.resolve()): _file(p) for p in sorted(paths)}


def _training_program(query_id, include_age_filter):
    """Independent declared Match shapes; neither B01's interpretation nor its gold."""
    match = {"operator_id": "people", "kind": "match", "input_ids": [], "input_kinds": [],
        "output_kind": "binding_set", "parameters": {"node": {"label": "Person"},
            "entity_field": "person", "properties": {"age": "age"} if include_age_filter else {}}}
    operators = [match]
    if include_age_filter:
        operators.append({"operator_id": "adult_filter", "kind": "filter", "input_ids": ["people"],
            "input_kinds": ["binding_set"], "output_kind": "binding_set",
            "parameters": {"condition": {"op": "ge", "field": "age", "value": 35}}})
    return SemanticGraphProgram.from_dict({"program_id": query_id, "operators": operators,
        "roots": [operators[-1]["operator_id"]]})


def prepare(args):
    """Only files, frozen catalog reads and pure compilation; no subprocess or fit."""
    runtime = Path(args.runtime_root).resolve()
    products = {"neo4j": runtime / "neo4j-community-5.26.30", "fuseki": runtime / "apache-jena-fuseki-5.6.0"}
    for path in (products["neo4j"] / "bin/neo4j", products["fuseki"] / "fuseki-server", Path(args.java)):
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError("Prepared executable is missing or not executable: " + str(path))
    request, inputs = one_shot_toy_inputs(QUERY_ID, args.mode)
    provider = load_one_shot_toy_provider(mode=args.mode, base_url=args.base_url, model=args.model,
        api_key_env=args.api_key_env, disable_thinking=args.disable_thinking, output_tokens=args.output_tokens,
        wire_profile=args.wire_profile)
    check = provider.token_guard.check(provider.build_request_payload(request), call_kind="generation")
    if not check["passed"]:
        raise ValueError("One-shot request exceeds the prepared development budget")
    graph = json.loads((DEFAULT_FIXTURE / "graph.json").read_text())
    version = inputs["sources"]["toy"].snapshot_version
    records = [*graph["nodes"], *graph["edges"]]
    mean_bytes = sum(len(json.dumps(row, sort_keys=True, separators=(",", ":")).encode())
                     for row in records) / len(records)
    graph_file = _file(DEFAULT_FIXTURE / "graph.json")
    statistics = FrozenSourceStatistics("original-tiny-logical-source", version, tuple(
        SourceStatistics(backend, "toy", version, len(records), mean_bytes,
            "graph.json#sha256=" + graph_file["sha256"] + ";logical-node-and-edge-records")
        for backend in ("neo4j", "fuseki")))
    training, reused = [], None
    if args.estimator:
        checked, _, _, frozen = one_shot_toy_preflight(provider,
            estimator_path=args.estimator, query_id=QUERY_ID, mode=args.mode)
        if not checked["success"] or frozen.statistics.to_dict() != statistics.to_dict():
            raise ValueError("Reused estimator does not match the exact original tiny source statistics")
        reused = {"estimator_file": _file(args.estimator), "model_sha256": frozen.model_sha256,
            "training_provenance": frozen.to_dict()["training_provenance"],
            "cost_scope": "historical one-time collection/fit; not incurred again by this gate",
            "planned_current_training_calls": 0, "planned_current_fit_calls": 0}
    for backend in (() if args.estimator else ("neo4j", "fuseki")):
        for filtered in (False, True):
            qid = "OS-TRAIN-" + backend + ("-match-age35" if filtered else "-match-entities")
            program = _training_program(qid, filtered)
            space = prepare_physical_strategies(program, source_bindings={"people": backend},
                backends=inputs["backends"], max_remote_calls=1, max_parallelism=1)
            if len(space.candidates) != 1:
                raise ValueError("An independent Match training input unexpectedly produced alternatives")
            plan = space.candidates[0].plan
            plan = replace(plan, metadata={**plan.metadata, "query_id": qid,
                "source_snapshot_versions": {backend: version},
                "source_identities": {backend: {"source_id": "toy", "snapshot_version": version}}})
            training.append({"query_id": qid, "program": program.to_dict(), "plan": plan})
    preflight = {"schema_version": PROFILE, "success": True, "operation": "preflight",
        "external_calls": 0, "backend_calls": 0, "processes_started": 0, "fit_calls": 0,
        "query_id": QUERY_ID, "mode": args.mode, "request": request.to_dict(),
        "request_budget": check, "provider_config": provider.config.safe_dict(),
        "source_snapshot_version": version, "graph_file": graph_file,
        "statistics": statistics.to_dict(), "statistics_scope":
            "Logical nodes+edges and mean JSON record size of the replicated fixture; not result cardinality or wire bytes",
        "training": [{**item, "plan": item["plan"].to_dict()} for item in training],
        "training_calls_maximum": len(training), "final_plan_executions_maximum": 1,
        "estimator_mode": "reuse_frozen" if args.estimator else "collect_and_fit",
        "reused_estimator": reused,
        "model_requests_maximum": 1, "current_query_probe_calls": 0, "automatic_retries": 0,
        "excluded_query_ids": list(EXCLUDED_IDS), "paper_result": False,
        "live_endpoint_verified": False, "loaded_backend_facts_verified": False,
        "model_created": False, "java_version_checked": False,
        "limitations": [("Reuses historical independent tiny training; no current training or fit"
                         if args.estimator else "Four separate tiny training executions only; not a calibrated model"),
            "No join/bind training coverage; B01 may extrapolate outside training features",
            "Shared local caches evolve during loading/training/query; no performance comparison",
            "Gold is used only by the independent evaluator after the one-shot result is sealed"]}
    return preflight, products, provider, statistics, training


def run(args):
    started = time.perf_counter()
    root = Path(args.output).resolve()
    if root == REPO or REPO in root.parents:
        raise ValueError("Native/preflight artifacts must live outside the repository")
    root.mkdir(parents=True, exist_ok=False)
    costs = {}
    record = {"schema_version": PROFILE, "started_at": _now(), "success": False,
        "operation": "execute" if args.execute else "preflight", "status": "preparing",
        "phase": "local_preflight",
        "query_id": QUERY_ID, "mode": args.mode, "paper_result": False, "automatic_retries": 0,
        "health": [], "loads": [], "training": [], "shutdown": [], "owned_services": [],
        "offline": {}, "online": None, "evaluation": None, "input_unchanged": None,
        "external_model_calls": 0, "online_backend_calls": 0, "final_plan_executions": 0}
    ports, running, previous_handlers, initial_inputs = None, [], {}, None
    try:
        prepare_at = time.perf_counter()
        preflight, products, provider, statistics, training = prepare(args)
        record["estimator_mode"] = preflight["estimator_mode"]
        record["offline"]["input_preparation_ms"] = (time.perf_counter() - prepare_at) * 1000
        record["training"] = [{"query_id": item["query_id"], "status": "not_attempted",
            "elapsed_ms": None, "remote_calls": None} for item in training]
        record["preflight"] = _write_once(root / "preflight.json", preflight, costs, "preflight_ms")
        initial_inputs = _fingerprints(products, args.java, args.estimator)
        _write_once(root / "input_fingerprints.json", initial_inputs, costs, "preflight_ms")
        if not args.execute:
            record.update(success=True, status="preflight_passed", input_unchanged=True)
            return record

        def expired(signum, _frame):
            raise TimeoutError("Owned tiny gate interrupted or exceeded its five-minute work bound")

        for signum in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, expired)
        signal.alarm(300)
        _write_once(root / "execution_intent.json", {"started_at": _now(),
            "preflight_sha256": record["preflight"]["sha256"], "maximum_training_plans": len(training),
            "training_query_ids": [item["query_id"] for item in training],
            "estimator_mode": preflight["estimator_mode"], "reused_estimator": preflight["reused_estimator"],
            "current_query_id": QUERY_ID, "maximum_model_requests": 1,
            "maximum_final_plan_executions": 1, "maximum_current_query_probes": 0,
            "work_seconds": 300, "cleanup_seconds_per_service": 30,
            "readiness_polling": "bounded startup readiness only; never retries a training/model/query failure"}, costs, "preflight_ms")
        setup_at = time.perf_counter()
        record["phase"] = "service_setup"
        record["java"] = inspect_java_runtime(args.java, required_major=21).to_dict()
        state = root / "state"
        for relative in ("neo4j/data", "neo4j/transactions", "neo4j/logs", "neo4j/run",
                         "neo4j/import", "neo4j/plugins", "fuseki"):
            (state / relative).mkdir(parents=True)
        conf = state / "neo4j-conf"
        shutil.copytree(products["neo4j"] / "conf", conf)
        ports = LoopbackPortReservations.acquire(3)
        neo_port, bolt_port, rdf_port = ports.ports
        (conf / "neo4j.conf").write_text(_neo4j_configuration(neo4j_root=products["neo4j"],
            state_root=state, http_port=neo_port, bolt_port=bolt_port,
            resource_profile={"heap_initial_size": "256m", "heap_max_size": "512m", "pagecache_size": "128m"},
            query_timeout_seconds=30))
        (state / "fuseki/config.ttl").write_text(_fuseki_server_configuration(query_timeout_seconds=30))
        neo_url, rdf_url = f"http://127.0.0.1:{neo_port}", f"http://127.0.0.1:{rdf_port}"
        specs = (
            ServiceSpec("neo4j", "neo4j", "5.26.30", (str(products["neo4j"] / "bin/neo4j"), "console"),
                products["neo4j"], {"JAVACMD": args.java, "NEO4J_CONF": str(conf), "NEO4J_HOME": str(products["neo4j"])},
                neo_url + "/db/neo4j/tx/commit", root / "neo4j.log"),
            ServiceSpec("fuseki", "fuseki", "5.6.0", (str(products["fuseki"] / "fuseki-server"),
                "--localhost", "--ping", "--port", str(rdf_port), "--update", "--mem", "/toy"),
                products["fuseki"], {"JAVA": args.java, "FUSEKI_HOME": str(products["fuseki"]),
                    "FUSEKI_BASE": str(state / "fuseki"), "JVM_ARGS": "-Xms128m -Xmx512m"},
                rdf_url + "/$/ping", root / "fuseki.log"))
        _write_once(root / "service_specs.json", [spec.to_dict() for spec in specs], costs, "setup_ms")
        for index, spec in enumerate(specs):
            for slot in ((0, 1) if index == 0 else (2,)):
                ports.release(slot)
            service = start_service(spec)
            running.append(service)
            ownership = {"service_id": spec.service_id, "pid": service.process.pid, "started_at": _now()}
            record["owned_services"].append(ownership)
            _write_once(root / (spec.service_id + "-owner.json"), ownership, costs, "setup_ms")
            health = wait_for_service_health(service, timeout_seconds=60)
            record["health"].append(health.to_dict())
            _write_once(root / (spec.service_id + "-health.json"), health.to_dict(), costs, "setup_ms")
            if not health.success:
                raise RuntimeError("Owned service failed readiness; no restart")
        record["offline"]["service_setup_ms"] = (time.perf_counter() - setup_at) * 1000
        neo = Neo4jClient(BackendDescriptor("neo4j", "neo4j", "cypher", "property_graph", runtime={"timeout_seconds": 35}))
        rdf_descriptor = BackendDescriptor("fuseki", "fuseki", "sparql", "rdf", runtime={"timeout_seconds": 35})
        rdf = FusekiClient(rdf_descriptor)
        neo.http_url, neo.database = neo_url, "neo4j"
        rdf.base_url, rdf.dataset = rdf_url, "toy"
        loader = FusekiGraphStoreFixtureLoader(rdf_descriptor)
        loader.base_url, loader.dataset = rdf_url, "toy"
        load_at = time.perf_counter()
        record["phase"] = "fixture_load"
        for name, perform in (("neo4j", lambda: neo.execute(QueryArtifact("one-shot-tiny-load", "cypher",
                (DEFAULT_FIXTURE / "load.cypher").read_text(), kind="native"))),
                ("fuseki", lambda: loader.load(DEFAULT_FIXTURE / "load.ttl"))):
            _write_once(root / (name + "-load-intent.json"), {"status": "started", "backend": name}, costs, "offline_load_ms")
            loaded = perform()
            record["loads"].append(_write_once(root / (name + "-load.json"), loaded.to_dict(), costs, "offline_load_ms"))
            if not loaded.success:
                raise RuntimeError("Original tiny fixture load failed; no retry")
        record["offline"]["fixture_load_ms"] = (time.perf_counter() - load_at) * 1000
        _write_once(root / "source_statistics.json", statistics.to_dict(), costs, "offline_statistics_ms")

        if args.estimator:
            record["phase"] = "reload_accepted_estimator"
            estimator_path = Path(args.estimator).resolve()
            reuse = preflight["reused_estimator"]
            load_at = time.perf_counter()
            reloaded = FrozenRuntimeEstimator.load(estimator_path)
            if (_file(estimator_path) != reuse["estimator_file"]
                    or reloaded.model_sha256 != reuse["model_sha256"]):
                raise RuntimeError("Accepted estimator changed after preflight")
            record["offline"].update(estimator_mode="reuse_frozen", training_reused=True,
                training_collection_ms=0.0, training_remote_calls=0, fit_ms=0.0, fit_calls=0,
                estimator_reload_ms=(time.perf_counter() - load_at) * 1000,
                estimator_file=reuse["estimator_file"], estimator_model_sha256=reloaded.model_sha256)
            record["historical_estimator_preparation"] = reuse
            _write_once(root / "reused_estimator_receipt.json", reuse, costs, "offline_model_reuse_ms")
        else:
            registry = BackendPluginRegistry()
            for client in (neo, rdf):
                registry.register(NativeBackendPlugin(client.backend_id, client))
            scheduler = FederatedScheduler(BackendInvokeTool(registry))
            training_at = time.perf_counter()
            samples = []
            for index, item in enumerate(training):
                prefix = f"training-{index + 1:02d}"
                record["phase"] = prefix
                observed = record["training"][index]
                observed["status"] = "started"
                _write_once(root / (prefix + "-intent.json"), {"query_id": item["query_id"],
                    "split_role": "training", "status": "started", "plan": item["plan"].to_dict()}, costs, "offline_training_ms")
                result = scheduler.execute(item["plan"], goal_id=item["query_id"])
                measurement = _write_once(root / (prefix + "-measurement.json"), {
                    "query_id": item["query_id"], "split_role": "training", "runtime_result": result.to_dict(),
                    "label_field": "runtime_result.elapsed_ms", "label_scope": "actual complete scheduler execution only",
                    "gold_used": False, "automatic_retries": 0}, costs, "offline_training_ms")
                observed.update(status="completed" if result.success else "failed", measurement=measurement,
                    success=result.success, elapsed_ms=result.elapsed_ms, remote_calls=result.total_remote_calls)
                if not result.success:
                    raise RuntimeError("Independent tiny training execution failed; no retry or query request")
                samples.append(RuntimeTrainingSample(prefix, item["query_id"], item["plan"],
                    result.elapsed_ms, measurement["sha256"]))
            collection_ms = (time.perf_counter() - training_at) * 1000
            collection_calls = sum(item["remote_calls"] for item in record["training"])
            collection = _write_once(root / "training_collection.json", {"training": record["training"],
                "excluded_query_ids": list(EXCLUDED_IDS), "collection_elapsed_ms": collection_ms,
                "collection_remote_calls": collection_calls, "source_statistics_sha256": statistics.sha256,
                "kind": "measured_training_on_original_tiny_graph", "paper_result": False}, costs, "offline_training_ms")
            fit_at = time.perf_counter()
            record["phase"] = "offline_fit_and_freeze"
            estimator = fit_runtime_estimator(samples, statistics=statistics,
                training_id="one-shot-independent-tiny-match-v1", model_version="tiny-measured-ridge-v1",
                training_kind="measured_training", excluded_query_ids=EXCLUDED_IDS,
                collection_ref="training_collection.json#sha256=" + collection["sha256"],
                collection_elapsed_ms=collection_ms, collection_remote_calls=collection_calls)
            fit_ms = (time.perf_counter() - fit_at) * 1000
            estimator_path = root / "frozen_estimator.json"
            serialized = _write_once(estimator_path, estimator.to_dict(), costs, "offline_model_freeze_ms")
            load_at = time.perf_counter()
            reloaded = FrozenRuntimeEstimator.load(estimator_path)
            if reloaded.to_dict() != estimator.to_dict():
                raise RuntimeError("Frozen estimator did not round-trip")
            record["offline"].update(training_collection_ms=collection_ms, training_remote_calls=collection_calls,
                fit_ms=fit_ms, estimator_reload_ms=(time.perf_counter() - load_at) * 1000,
                estimator_file=serialized, estimator_model_sha256=reloaded.model_sha256)
        _write_once(root / "offline_receipt.json", record["offline"], costs,
                    "offline_model_reuse_ms" if args.estimator else "offline_model_freeze_ms")

        online_at = time.perf_counter()
        record.update(status="one_shot_started", phase="one_shot", external_model_calls=None,
                      online_backend_calls=None, final_plan_executions=None)
        online = run_one_shot_toy(estimator_path=estimator_path, output=root / "one-shot",
            query_id=QUERY_ID, mode=args.mode, execute=True, backend_clients={"neo4j": neo, "fuseki": rdf},
            provider=provider, evaluate=True)
        wall = (time.perf_counter() - online_at) * 1000
        record["online"] = {"receipt": online, "online_wall_including_persistence_ms": wall,
            "scope": "one-shot wrapper preflight, online request, post-return recording/evaluation/receipt",
            "core_online_ms": online.get("online_end_to_end_ms"),
            "additional_wrapper_ms": (max(0, wall - online["online_end_to_end_ms"])
                                      if online.get("online_end_to_end_ms") is not None else None)}
        record.update(success=online["success"], status=online["status"],
            external_model_calls=online.get("external_calls"), online_backend_calls=online.get("backend_calls"),
            final_plan_executions=online.get("final_plan_executions"))
        if (root / "one-shot/evaluation.json").is_file():
            record["evaluation"] = json.loads((root / "one-shot/evaluation.json").read_text())
        _write_once(root / "one-shot-wrapper-receipt.json", record["online"], costs, "post_return_ms")
    except BaseException as error:
        # Read only the explicitly named credential to remove it from a failure
        # message; never write, log or expose its value or the environment.
        message = str(error)
        credential = os.environ.get(args.api_key_env, "")
        if credential:
            message = message.replace(credential, "[REDACTED]")
        record.update(success=False, status="gate_failed", error_type=type(error).__name__,
                      error=message)
        for item in record["training"]:
            if item["status"] == "started":
                item["status"] = "indeterminate"
        _write_once(root / "failure.json", {"error_type": type(error).__name__, "error": message,
            "status": record["status"], "phase": record["phase"],
            "completed_training": sum(item["status"] == "completed" for item in record["training"]),
            "online_started": record["external_model_calls"] is None,
            "automatic_retries": 0}, costs, "failure_ms")
    finally:
        # Save observed work before cleanup. Every service started by this call
        # remains owned even when a recording write or the global deadline fails.
        try:
            _write_once(root / "before_cleanup.json", record, costs, "post_return_ms")
        finally:
            if previous_handlers:
                signal.alarm(0)
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)
            for service in reversed(running):
                try:
                    record["shutdown"].append(stop_service(service, timeout_seconds=30).to_dict())
                except Exception as error:
                    record["shutdown"].append({"service_id": service.spec.service_id,
                        "pid": service.process.pid, "success": False, "error_type": type(error).__name__})
            if ports is not None:
                ports.close()
            if initial_inputs is not None:
                after = _fingerprints(products, args.java, args.estimator)
                record["input_unchanged"] = after == initial_inputs
                _write_once(root / "input_fingerprints_after.json", after, costs, "post_return_ms")
                if not record["input_unchanged"]:
                    record.update(success=False, status="input_changed_during_gate")
            record["owned_processes_terminal"] = all(service.process.poll() is not None for service in running)
            if not record["owned_processes_terminal"]:
                record.update(success=False, status="owned_service_cleanup_incomplete")
            record["finished_at"] = _now()
            record["elapsed_ms"] = (time.perf_counter() - started) * 1000
            record["harness_persistence_ms"] = dict(costs)
            record["persistence_scope"] = "this script's JSON writes/fsyncs; excludes nested one-shot writer and final receipt itself"
            _write_once(root / "receipt.json", record, {}, "final_receipt_ms")
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--java", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--estimator", help="Reuse an accepted frozen tiny estimator; skip all collection and fit")
    parser.add_argument("--mode", choices=("precision", "performance"), default="precision")
    parser.add_argument("--wire-profile", choices=("json-schema-v1", "json-object-v1", "envelope-schema-v1"), default="json-schema-v1",
                        help="Explicit provider wire profile; never changed automatically after a failure")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--api-key-env", default="XGAP_EXTERNAL_LLM_API_KEY")
    parser.add_argument("--disable-thinking", action="store_true")
    parser.add_argument("--output-tokens", type=int, choices=(4096, 6144))
    args = parser.parse_args(argv)
    record = run(args)
    print(json.dumps({"success": record["success"], "status": record["status"],
        "operation": record["operation"], "external_model_calls": record["external_model_calls"],
        "online_backend_calls": record["online_backend_calls"], "output": str(Path(args.output).resolve())}))
    return 0 if record["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
