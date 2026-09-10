"""Run tiny native fixtures in fresh owned stores using already prepared binaries."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import signal
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.experiments.m15_fixture_loader import FusekiGraphStoreFixtureLoader
from xgap.experiments.m15_native_services import (
    LoopbackPortReservations, ServiceSpec, _neo4j_configuration,
    _fuseki_server_configuration, inspect_java_runtime, start_service,
    stop_service, wait_for_service_health,
)
from xgap.experiments.toy_backbone import (
    DEFAULT_FIXTURE, DIRECTED_TOY_QUERY_IDS, execute_directed_toy_case, execute_bounded_toy_case,
    execute_vertical_slice, load_fixture,
)
from xgap.experiments.toy_semantic import (
    FIXTURE as SEMANTIC_FIXTURE, execute_semantic_case, load_semantic_cases, wrap_path_case,
)
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import QueryArtifact


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--java", required=True)
    parser.add_argument("--execute", action="store_true")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--compiled-directed", action="store_true",
        help="Run the production-compiled fixed-path cases instead of independent reference targets")
    selection.add_argument("--compiled-bounded", action="store_true",
        help="Run all toy queries through bounded native compilation and coordinator selectors")
    selection.add_argument("--semantic-dag", action="store_true",
        help="Compile the typed semantic programs and composed two-backend DAGs")
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error("Fresh owned native execution requires --execute")
    products = {"neo4j": Path(args.runtime_root).resolve() / "neo4j-community-5.26.30",
                "fuseki": Path(args.runtime_root).resolve() / "apache-jena-fuseki-5.6.0"}
    for product, executable in (("neo4j", "bin/neo4j"), ("fuseki", "fuseki-server")):
        if not (products[product] / executable).is_file():
            parser.error("Prepare the pinned native distributions before running toy tests")
    java = inspect_java_runtime(java_command=args.java, required_major=21)
    data, cases, mapping = load_fixture()
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    state = root / "state"
    for relative in ("neo4j/data", "neo4j/transactions", "neo4j/logs", "neo4j/run",
                     "neo4j/import", "neo4j/plugins", "fuseki"):
        (state / relative).mkdir(parents=True)
    conf = state / "neo4j-conf"
    shutil.copytree(products["neo4j"] / "conf", conf)
    files = [p for p in DEFAULT_FIXTURE.rglob("*") if p.is_file()]
    source_files = [REPO / relative for relative in (
        "src/xgap/experiments/toy_backbone.py", "src/xgap/compilers/directed.py",
        "src/xgap/compilers/rdf_encoding.py", "src/xgap/runtime/directed_fragments.py",
        "src/xgap/compilers/bounded_paths.py", "src/xgap/runtime/bounded_paths.py",
        "src/xgap/runtime/path_selection.py", "src/xgap/runtime/contracts.py",
        "src/xgap/runtime/scheduler.py", "src/xgap/algebra/evaluator.py")]
    source_files.append(Path(__file__))
    if args.semantic_dag:
        source_files.extend(REPO / relative for relative in (
            "src/xgap/experiments/toy_semantic.py", "src/xgap/compilers/node_match.py",
            "src/xgap/runtime/semantic_compiler.py", "src/xgap/runtime/row_operations.py",
            "src/xgap/semantic/program.py"))
    record = {"success": False, "scope": ("T1 semantic DAG execution" if args.semantic_dag else
                                           "T1 bounded path execution" if args.compiled_bounded else
                                           "T1 compiled directed paths" if args.compiled_directed
                                           else "T0 tiny native development fixture"),
        "live_llm": False, "paper_result": False, "java": java.to_dict(),
        "nodes": len(data["nodes"]), "edges": len(data["edges"]), "query_ids": [c["id"] for c in cases],
        "fixture_sha256": {str(p.relative_to(DEFAULT_FIXTURE)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        "source_sha256": {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files},
        "health": [], "loads": [], "targets": [], "shutdown": [], "automatic_retries": 0}
    if args.semantic_dag:
        record.update(semantic_cases=[], semantic_reference_targets=[],
            semantic_fixture_sha256={str(p.relative_to(SEMANTIC_FIXTURE)):
                hashlib.sha256(p.read_bytes()).hexdigest()
                for p in SEMANTIC_FIXTURE.rglob("*") if p.is_file()})

    def save():
        (root / "result.json").write_text(json.dumps(record, indent=2) + "\n")

    ports = None
    running = []
    previous = signal.getsignal(signal.SIGALRM)

    def expired(_signum, _frame):
        raise TimeoutError("Toy native run exceeded its five-minute wall-clock bound")

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(300)
    save()
    try:
        ports = LoopbackPortReservations.acquire(3)
        neo_port, bolt_port, rdf_port = ports.ports
        (conf / "neo4j.conf").write_text(_neo4j_configuration(neo4j_root=products["neo4j"],
            state_root=state, http_port=neo_port, bolt_port=bolt_port,
            resource_profile={"heap_initial_size": "256m", "heap_max_size": "512m", "pagecache_size": "128m"},
            query_timeout_seconds=30).replace("one job-owned XGAP M15 allocation", "one owned tiny local fixture"))
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
                rdf_url + "/$/ping", root / "fuseki.log"),
        )
        record["services"] = [spec.to_dict() for spec in specs]
        save()
        for i, spec in enumerate(specs):
            for j in ((0, 1) if i == 0 else (2,)):
                ports.release(j)
            service = start_service(spec)
            running.append(service)
            health = wait_for_service_health(service, timeout_seconds=60)
            record["health"].append(health.to_dict())
            save()
            if not health.success:
                raise RuntimeError("Owned toy backend failed readiness; no retry")
        neo = Neo4jClient(BackendDescriptor("neo4j", "neo4j", "cypher", "property_graph", runtime={"timeout_seconds": 35}))
        rdf_descriptor = BackendDescriptor("fuseki", "fuseki", "sparql", "rdf", runtime={"timeout_seconds": 35})
        rdf = FusekiClient(rdf_descriptor)
        neo.http_url, neo.database = neo_url, "neo4j"
        rdf.base_url, rdf.dataset = rdf_url, "toy"
        loader = FusekiGraphStoreFixtureLoader(rdf_descriptor)
        loader.base_url, loader.dataset = rdf_url, "toy"
        record["phase"] = "load-fresh-toy-stores"
        save()
        loaded = neo.execute(QueryArtifact("toy-create", "cypher", (DEFAULT_FIXTURE / "load.cypher").read_text(), kind="native"))
        record["loads"].append(loaded.to_dict())
        save()
        if not loaded.success:
            raise RuntimeError("Tiny Neo4j load failed; preserve the fresh output without retry")
        loaded_rdf = loader.load(DEFAULT_FIXTURE / "load.ttl")
        record["loads"].append(loaded_rdf.to_dict())
        save()
        if not loaded_rdf.success:
            raise RuntimeError("Tiny Fuseki load failed; no retry")
        record["phase"] = ("semantic-dag" if args.semantic_dag else
                           "compiled-bounded" if args.compiled_bounded else
                           "compiled-directed" if args.compiled_directed else "independent-targets")
        selected = [case for case in cases if not args.compiled_directed
                    or case["id"] in DIRECTED_TOY_QUERY_IDS]
        for case in selected:
            for backend, client in (("neo4j", neo), ("fuseki", rdf)):
                item = {"query_id": case["id"], "backend": backend, "status": "started", "success": False}
                record["targets"].append(item)
                save()
                if args.semantic_dag:
                    item.update(execute_semantic_case(wrap_path_case(case, backend), mapping,
                        clients={backend: client}), status="completed")
                    save()
                    if not item["success"]:
                        raise RuntimeError(f"Semantic path failed: {case['id']} / {backend}; no retry")
                    continue
                if args.compiled_directed or args.compiled_bounded:
                    execute_case = execute_bounded_toy_case if args.compiled_bounded else execute_directed_toy_case
                    item.update(execute_case(case, mapping, client=client), status="completed")
                    save()
                    if not item["success"]:
                        raise RuntimeError(f"Compiled target failed: {case['id']} / {backend}; retained without retry")
                    continue
                language = "cypher" if backend == "neo4j" else "sparql"
                target = DEFAULT_FIXTURE / case["reference_target_queries"][backend]
                result = client.execute(QueryArtifact(case["id"] + "-reference-" + backend, language, target.read_text(), kind="native"))
                actual = sorted({row["path"] for row in result.rows}) if result.success else None
                item.update(status="completed", execution=result.to_dict(), actual_paths=actual,
                            success=result.success and actual == case["expected_paths"])
                save()
                if not item["success"]:
                    raise RuntimeError(f"Independent target failed: {case['id']} / {backend}; retained without retry")
        if args.semantic_dag:
            for case in load_semantic_cases():
                record["phase"] = "semantic-composition-" + case["id"]
                item = {"query_id": case["id"], "status": "started", "success": False}
                record["semantic_cases"].append(item)
                save()
                item.update(execute_semantic_case(case, mapping, clients={"neo4j": neo, "fuseki": rdf}),
                            status="completed")
                save()
                if not item["success"]:
                    raise RuntimeError(f"Semantic composition failed: {case['id']}; no retry")
                target = SEMANTIC_FIXTURE / case["reference_target_queries"]["neo4j"]
                result = neo.execute(QueryArtifact(case["id"] + "-reference-neo4j", "cypher",
                    target.read_text(), kind="native"))
                actual = list(result.rows) if result.success else None
                expected = case["expected_rows"]
                canonical = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
                matched = actual == expected if case["ordered"] else (
                    actual is not None and canonical(actual) == canonical(expected))
                reference = {"query_id": case["id"], "backend": "neo4j", "execution": result.to_dict(),
                    "actual_rows": actual, "success": result.success and matched}
                record["semantic_reference_targets"].append(reference)
                save()
                if not reference["success"]:
                    raise RuntimeError(f"Independent semantic reference failed: {case['id']}; no retry")
        record["phase"] = "compiled-federated-slice"
        save()
        record["vertical_slice"] = execute_vertical_slice(cases[-1], mapping, neo4j=neo, fuseki=rdf)
        save()
        if not record["vertical_slice"]["success"]:
            raise RuntimeError("Compiled two-engine slice did not match the independent expected answer")
        record["success"] = True
        record["phase"] = "completed"
    except Exception as error:
        record["error"] = f"{type(error).__name__}: {error}"
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
        for service in reversed(running):
            record["shutdown"].append(stop_service(service, timeout_seconds=30).to_dict())
        if ports is not None:
            ports.close()
        save()
    print(json.dumps({"success": record["success"], "target_attempts": len(record["targets"]),
        "targets_passed": sum(x["success"] for x in record["targets"]),
        "semantic_compositions_passed": sum(x["success"] for x in record.get("semantic_cases", [])),
        "semantic_references_passed": sum(x["success"] for x in record.get("semantic_reference_targets", [])),
        "compiled_slice_passed": record.get("vertical_slice", {}).get("success"), "output": str(root)}))
    return 0 if record["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
