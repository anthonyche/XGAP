"""Run tiny native fixtures in fresh owned stores using already prepared binaries."""

from __future__ import annotations

import argparse
import hashlib
import json
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
from xgap.experiments.toy_planning import execute_planned_semantic_case
from xgap.experiments.toy_binding import (FIXTURE as BINDING_FIXTURE, BUNDLE_FIXTURE, INTAKE_FIXTURE, load_binding_cases,
    execute_binding_case, reference_artifact, reference_rows)
from xgap.semantic.interpretation_replay import ReplayInterpretationProvider
from xgap.experiments.toy_orientation import FIXTURE as ORIENTATION_FIXTURE, load_orientation_cases
from xgap.experiments.toy_capabilities import (FIXTURE as CAPABILITY_FIXTURE,
    load_capability_cases, execute_capability_case)
from xgap.experiments.toy_repetition import FIXTURE as REPETITION_FIXTURE, load_repetition_cases
from xgap.experiments.toy_scoped import FIXTURE as SCOPED_FIXTURE, load_scoped_cases, execute_scoped_case
from xgap.experiments.toy_boolean import (FIXTURE as BOOLEAN_FIXTURE, load_boolean_cases,
    load_boolean_matches, execute_boolean_case, boolean_match_reference, boolean_match_reference_rows)
from xgap.experiments.toy_typed import (FIXTURE as TYPED_FIXTURE, load_typed_fixture,
    typed_sources, typed_reference, typed_reference_rows, typed_rows_match)
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import QueryArtifact


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--java", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--interpretation-recordings",
        help="With --agentic-semantic, replay the five recorded model responses; zero new model calls")
    parser.add_argument("--static-backend-order", nargs="+", choices=("neo4j", "fuseki"),
        help="With --agentic-semantic, use fixed backend priority without planning observations")
    parser.add_argument("--memory-roundtrip", action="store_true",
        help="With --agentic-semantic, execute each question cold then warm after JSONL memory reload")
    adaptation = parser.add_mutually_exclusive_group()
    adaptation.add_argument("--refresh-ablation", action="store_true",
        help="With --agentic-semantic, run only the B04 warm one-refresh mechanism arms")
    adaptation.add_argument("--prefix-ablation", action="store_true",
        help="With --agentic-semantic, run only the two-source A2 native prefix mechanism arms")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--compiled-directed", action="store_true",
        help="Run the production-compiled fixed-path cases instead of independent reference targets")
    selection.add_argument("--compiled-bounded", action="store_true",
        help="Run all toy queries through bounded native compilation and coordinator selectors")
    selection.add_argument("--semantic-dag", action="store_true",
        help="Compile the typed semantic programs and composed two-backend DAGs")
    selection.add_argument("--planned-semantic", action="store_true",
        help="Generate placements, collect native observations, select and execute semantic DAGs")
    selection.add_argument("--agentic-semantic", action="store_true",
        help="Resolve frozen toy semantic slots, bind constraints, plan and execute with GoalLoop")
    selection.add_argument("--orientation", action="store_true",
        help="Check mixed/undirected/recursive orientation witnesses against independent native targets")
    selection.add_argument("--capability-semantic", action="store_true",
        help="Admit declared semantic capabilities before observing and executing placements")
    selection.add_argument("--repetition", action="store_true",
        help="Check optional and finite repetition against independently authored native targets")
    selection.add_argument("--scoped", action="store_true",
        help="Run nested scopes through semantic Traverse and candidate planning")
    selection.add_argument("--boolean", action="store_true",
        help="Run scalar Boolean paths, Match, independent targets and normal planning")
    selection.add_argument("--typed-bindings", action="store_true",
        help="Run exact typed aggregates, nullable ordering, joins and explicit source placement")
    parser.add_argument("--typed-query-ids", nargs="+",
        choices=[c["id"] for c in load_typed_fixture()[1]],
        help="With --typed-bindings, run only these cases for a bounded failure follow-up")
    parser.add_argument("--scoped-planning-only", action="store_true",
        help="With --scoped, run only the remaining planning checks and retained slice")
    parser.add_argument("--boolean-followup-only", action="store_true",
        help="With --boolean, verify Match, planning and retained slice without repeating path targets")
    args = parser.parse_args(argv)
    if args.interpretation_recordings and not args.agentic_semantic:
        parser.error("--interpretation-recordings requires --agentic-semantic")
    if args.static_backend_order and (not args.agentic_semantic or
            set(args.static_backend_order) != {"neo4j", "fuseki"} or len(args.static_backend_order) != 2):
        parser.error("--static-backend-order requires --agentic-semantic and both backend IDs exactly once")
    if args.memory_roundtrip and (not args.agentic_semantic or args.static_backend_order):
        parser.error("--memory-roundtrip requires --agentic-semantic without static selection")
    if args.refresh_ablation and (not args.agentic_semantic or args.memory_roundtrip
                                 or args.static_backend_order or args.interpretation_recordings):
        parser.error("--refresh-ablation requires only --agentic-semantic and controlled interpretation")
    if args.prefix_ablation and (not args.agentic_semantic or args.memory_roundtrip
                                or args.static_backend_order or args.interpretation_recordings):
        parser.error("--prefix-ablation requires only --agentic-semantic and fixed semantic input")
    binding_cases = [] if args.prefix_ablation else [c for c in load_binding_cases()
        if not args.refresh_ablation or c["id"] == "B04"]
    if args.typed_query_ids and not args.typed_bindings:
        parser.error("--typed-query-ids requires --typed-bindings")
    typed_cases = [c for c in load_typed_fixture()[1]
                   if not args.typed_query_ids or c["id"] in args.typed_query_ids]
    if args.boolean_followup_only and not args.boolean:
        parser.error("--boolean-followup-only requires --boolean")
    if args.scoped_planning_only and not args.scoped:
        parser.error("--scoped-planning-only requires --scoped")
    if not args.execute:
        parser.error("Fresh owned native execution requires --execute")
    products = {"neo4j": Path(args.runtime_root).resolve() / "neo4j-community-5.26.30",
                "fuseki": Path(args.runtime_root).resolve() / "apache-jena-fuseki-5.6.0"}
    for product, executable in (("neo4j", "bin/neo4j"), ("fuseki", "fuseki-server")):
        if not (products[product] / executable).is_file():
            parser.error("Prepare the pinned native distributions before running toy tests")
    java = inspect_java_runtime(java_command=args.java, required_major=21)
    data, cases, mapping = load_fixture()
    load_root = TYPED_FIXTURE if args.typed_bindings else BOOLEAN_FIXTURE if args.boolean else DEFAULT_FIXTURE
    if args.typed_bindings:
        data, _, mapping = load_typed_fixture()
    if args.boolean:
        data, _, mapping = load_fixture(BOOLEAN_FIXTURE)
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
    if args.orientation:
        source_files.extend(REPO / relative for relative in (
            "src/xgap/algebra/ops.py", "src/xgap/algebra/validation.py",
            "src/xgap/pattern/lowering.py", "src/xgap/compilers/features.py",
            "src/xgap/experiments/toy_orientation.py"))
    if args.semantic_dag or args.planned_semantic or args.agentic_semantic or args.capability_semantic or args.scoped or args.boolean or args.typed_bindings:
        source_files.extend(REPO / relative for relative in (
            "src/xgap/experiments/toy_semantic.py", "src/xgap/compilers/node_match.py",
            "src/xgap/runtime/semantic_compiler.py", "src/xgap/runtime/row_operations.py",
            "src/xgap/semantic/program.py", "src/xgap/runtime/semantic_capabilities.py"))
    if args.planned_semantic or args.agentic_semantic or args.capability_semantic or args.scoped or args.boolean or args.typed_bindings:
        source_files.extend(REPO / relative for relative in (
            "src/xgap/runtime/semantic_planning.py", "src/xgap/runtime/planning.py",
            "src/xgap/runtime/observations.py", "src/xgap/runtime/tool.py",
            "src/xgap/runtime/semantic_memory.py", "src/xgap/agent/memory.py",
            "src/xgap/runtime/semantic_placement.py", "src/xgap/runtime/semantic_refresh.py",
            "src/xgap/tools/backends.py", "src/xgap/experiments/toy_planning.py"))
    if args.agentic_semantic:
        source_files.extend(REPO / relative for relative in (
            "src/xgap/semantic/binding.py", "src/xgap/agent/semantic_execution.py",
            "src/xgap/agent/resolution.py", "src/xgap/agent/loop.py",
            "src/xgap/tools/artifact_resolution.py", "src/xgap/tools/resolution.py",
            "src/xgap/experiments/toy_binding.py", "src/xgap/catalog/bundle.py",
            "src/xgap/agent/question.py", "src/xgap/semantic/intake.py",
            "src/xgap/semantic/interpretation.py", "src/xgap/semantic/interpretation_replay.py"))
    if args.capability_semantic:
        source_files.append(REPO / "src/xgap/experiments/toy_capabilities.py")
    if args.refresh_ablation:
        source_files.append(REPO / "src/xgap/experiments/toy_refresh.py")
    if args.prefix_ablation:
        source_files.extend(REPO / relative for relative in (
            "src/xgap/experiments/toy_prefix.py", "src/xgap/runtime/semantic_adaptive.py",
            "src/xgap/runtime/adaptive.py"))
    if args.repetition:
        source_files.extend(REPO / relative for relative in (
            "src/xgap/pattern/lowering.py", "src/xgap/pattern/typecheck.py",
            "src/xgap/llm/parser.py", "src/xgap/experiments/toy_repetition.py"))
    if args.scoped or args.boolean:
        source_files.extend(REPO / relative for relative in (
            "src/xgap/pattern/lowering.py", "src/xgap/pattern/typecheck.py", "src/xgap/llm/parser.py",
            "src/xgap/runtime/scoped_paths.py", "src/xgap/runtime/path_composition.py",
            "src/xgap/experiments/toy_scoped.py"))
    if args.boolean:
        source_files.extend(REPO / relative for relative in (
            "src/xgap/compilers/boolean_conditions.py", "src/xgap/experiments/toy_boolean.py"))
    if args.typed_bindings:
        source_files.extend(REPO / relative for relative in (
            "src/xgap/runtime/scalars.py", "src/xgap/runtime/binding_operations.py",
            "src/xgap/experiments/toy_typed.py", "src/xgap/compilers/boolean_conditions.py"))
    record = {"success": False, "scope": ("T1 typed binding values" if args.typed_bindings else
                                           "T1 total scalar Boolean conditions" if args.boolean else
                                           "T1 finite nested path scopes" if args.scoped else
                                           "T1 optional and finite repetition" if args.repetition else
                                           "T1 semantic capability admission" if args.capability_semantic else
                                           "T1 logical and native path orientation" if args.orientation else
                                           "T1 semantic binding and bounded agent execution" if args.agentic_semantic else
                                           "T1 semantic candidate planning" if args.planned_semantic else
                                           "T1 semantic DAG execution" if args.semantic_dag else
                                           "T1 bounded path execution" if args.compiled_bounded else
                                           "T1 compiled directed paths" if args.compiled_directed
                                           else "T0 tiny native development fixture"),
        "live_llm": False, "paper_result": False, "java": java.to_dict(),
        "nodes": len(data["nodes"]), "edges": len(data["edges"]), "query_ids": [c["id"] for c in cases],
        "fixture_sha256": {str(p.relative_to(DEFAULT_FIXTURE)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        "source_sha256": {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files},
        "health": [], "loads": [], "targets": [], "shutdown": [], "automatic_retries": 0}
    if args.semantic_dag or args.planned_semantic or args.capability_semantic:
        record.update(semantic_cases=[], semantic_reference_targets=[], planned_cases=[],
            semantic_fixture_sha256={str(p.relative_to(SEMANTIC_FIXTURE)):
                hashlib.sha256(p.read_bytes()).hexdigest()
                for p in SEMANTIC_FIXTURE.rglob("*") if p.is_file()})
    if args.capability_semantic:
        record.update(query_ids=[c["id"] for c in load_capability_cases()],
            capability_fixture_sha256={str(p.relative_to(CAPABILITY_FIXTURE)):
                hashlib.sha256(p.read_bytes()).hexdigest()
                for p in CAPABILITY_FIXTURE.rglob("*") if p.is_file()})
    if args.agentic_semantic:
        record.update(binding_cases=[], binding_reference_targets=[],
            memory_roundtrip=args.memory_roundtrip,
            static_backend_order=args.static_backend_order,
            binding_query_ids=[c["id"] for c in binding_cases],
            interpretation_mode="recorded_response" if args.interpretation_recordings else "controlled_template",
            interpretation_fixture_sha256={str(p.relative_to(INTAKE_FIXTURE)):
                hashlib.sha256(p.read_bytes()).hexdigest()
                for p in INTAKE_FIXTURE.rglob("*") if p.is_file()},
            binding_bundle_sha256={str(p.relative_to(BUNDLE_FIXTURE)):
                hashlib.sha256(p.read_bytes()).hexdigest()
                for p in BUNDLE_FIXTURE.rglob("*") if p.is_file()},
            binding_fixture_sha256={str(p.relative_to(BINDING_FIXTURE)):
                hashlib.sha256(p.read_bytes()).hexdigest()
                for p in BINDING_FIXTURE.rglob("*") if p.is_file()})
        if args.refresh_ablation:
            record.update(scope="A1 B04 pre-execution refresh mechanism", refresh_ablation={})
        if args.prefix_ablation:
            record.update(scope="A2 two-source execution-prefix mechanism", prefix_ablation={},
                query_ids=["A2-prefix"], interpretation_mode="fixed_semantic_program",
                track="deterministic_planning", interpretation_exercised=False, goal_loop_exercised=False)
        if args.interpretation_recordings:
            record["binding_cases"] = [{"query_id": c["id"], "status": "not_attempted", "success": False}
                                       for c in load_binding_cases()]
            record["interpretation_recording_sha256"] = {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (Path(args.interpretation_recordings) / (c["id"] + ".json")
                          for c in load_binding_cases()) if p.is_file()}
    if args.orientation:
        record.update(orientation_reference_targets=[],
            query_ids=[c["id"] for c in load_orientation_cases()],
            orientation_fixture_sha256={str(p.relative_to(ORIENTATION_FIXTURE)):
                hashlib.sha256(p.read_bytes()).hexdigest()
                for p in ORIENTATION_FIXTURE.rglob("*") if p.is_file()})
    if args.repetition:
        record.update(repetition_reference_targets=[],
            query_ids=[c["id"] for c in load_repetition_cases()],
            repetition_fixture_sha256={str(p.relative_to(REPETITION_FIXTURE)):
                hashlib.sha256(p.read_bytes()).hexdigest()
                for p in REPETITION_FIXTURE.rglob("*") if p.is_file()})

    if args.boolean:
        record.update(boolean_reference_targets=[], boolean_matches=[], boolean_match_references=[], boolean_planned_cases=[],
            boolean_followup_only=args.boolean_followup_only,
            query_ids=([c["id"] for c in load_boolean_matches()] + ["C04", "C14"] if args.boolean_followup_only
                       else [c["id"] for c in load_boolean_cases()]),
            boolean_fixture_sha256={str(p.relative_to(BOOLEAN_FIXTURE)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in BOOLEAN_FIXTURE.rglob("*") if p.is_file()})
    if args.typed_bindings:
        record.update(typed_planned_cases=[], typed_reference_targets=[],
            query_ids=[c["id"] for c in typed_cases],
            typed_fixture_sha256={str(p.relative_to(TYPED_FIXTURE)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in TYPED_FIXTURE.rglob("*") if p.is_file()},
            logical_sources={name: {"version": source.snapshot_version, "replicas": source.replica_backend_ids}
                for name, source in typed_sources().items()})
    if args.scoped:
        record.update(scoped_reference_targets=[], scoped_planned_cases=[],
            scoped_planning_only=args.scoped_planning_only,
            query_ids=[c["id"] for c in load_scoped_cases()
                       if not args.scoped_planning_only or c["id"] in ("N01", "N08", "N13")],
            scoped_fixture_sha256={str(p.relative_to(SCOPED_FIXTURE)):
                hashlib.sha256(p.read_bytes()).hexdigest()
                for p in SCOPED_FIXTURE.rglob("*") if p.is_file()})

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
        loaded = neo.execute(QueryArtifact("toy-create", "cypher", (load_root / "load.cypher").read_text(), kind="native"))
        record["loads"].append(loaded.to_dict())
        save()
        if not loaded.success:
            raise RuntimeError("Tiny Neo4j load failed; preserve the fresh output without retry")
        loaded_rdf = loader.load(load_root / "load.ttl")
        record["loads"].append(loaded_rdf.to_dict())
        save()
        if not loaded_rdf.success:
            raise RuntimeError("Tiny Fuseki load failed; no retry")
        record["phase"] = ("scoped" if args.scoped else "repetition" if args.repetition else
                           "orientation" if args.orientation else
                           "semantic-dag" if args.semantic_dag else
                           "compiled-bounded" if args.compiled_bounded else
                           "compiled-directed" if args.compiled_directed else "independent-targets")
        selected = [case for case in cases if not args.compiled_directed
                    or case["id"] in DIRECTED_TOY_QUERY_IDS]
        if args.planned_semantic or args.agentic_semantic or args.capability_semantic:
            selected = []  # Changed planning boundary uses the composition cases below.
        if args.orientation:
            selected = load_orientation_cases()
        if args.repetition:
            selected = load_repetition_cases()
        if args.scoped:
            selected = [] if args.scoped_planning_only else load_scoped_cases()
        if args.boolean:
            selected = [] if args.boolean_followup_only else load_boolean_cases()
        if args.typed_bindings:
            selected = []
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
                if args.compiled_directed or args.compiled_bounded or args.orientation or args.repetition or args.scoped or args.boolean:
                    execute_case = execute_bounded_toy_case if args.compiled_bounded or args.orientation or args.repetition else execute_directed_toy_case
                    if args.scoped:
                        execute_case = execute_scoped_case
                    if args.boolean:
                        execute_case = execute_boolean_case
                    item.update(execute_case(case, mapping, client=client), status="completed")
                    save()
                    if not item["success"]:
                        raise RuntimeError(f"Compiled target failed: {case['id']} / {backend}; retained without retry")
                    if args.orientation or args.repetition or args.scoped or args.boolean:
                        target = (BOOLEAN_FIXTURE if args.boolean else SCOPED_FIXTURE if args.scoped else REPETITION_FIXTURE if args.repetition else ORIENTATION_FIXTURE) / case["reference_target_queries"][backend]
                        result = client.execute(QueryArtifact(case["id"] + "-reference-" + backend,
                            "cypher" if backend == "neo4j" else "sparql", target.read_text(), kind="native"))
                        actual = sorted({row["path"] for row in result.rows}) if result.success else None
                        reference = {"query_id": case["id"], "backend": backend,
                            "execution": result.to_dict(), "actual_paths": actual,
                            "success": result.success and actual == case["expected_paths"]}
                        record["boolean_reference_targets" if args.boolean else "scoped_reference_targets" if args.scoped else "repetition_reference_targets" if args.repetition else "orientation_reference_targets"].append(reference)
                        save()
                        if not reference["success"]:
                            raise RuntimeError(f"Independent path reference failed: {case['id']} / {backend}; no retry")
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
        if args.planned_semantic or args.capability_semantic:
            planning_cases = load_capability_cases() if args.capability_semantic else load_semantic_cases()
            execute_planning = execute_capability_case if args.capability_semantic else execute_planned_semantic_case
            for case in planning_cases:
                record["phase"] = ("capability-semantic-" if args.capability_semantic else "planned-semantic-") + case["id"]
                item = {"query_id": case["id"], "status": "started", "success": False}
                record["planned_cases"].append(item)
                save()
                item.update(execute_planning(case, mapping, clients={"neo4j": neo, "fuseki": rdf}),
                            status="completed")
                save()
                if not item["success"]:
                    raise RuntimeError(f"Semantic planning failed: {case['id']}; no retry")
        if args.prefix_ablation:
            from xgap.experiments.toy_prefix import execute_prefix_ablation
            record["phase"] = "A2-native-prefix-arms-and-references"
            save()
            execute_prefix_ablation(mapping, clients={"neo4j": neo, "fuseki": rdf},
                record=record["prefix_ablation"], on_update=save)
        if args.agentic_semantic:
            if args.memory_roundtrip or args.refresh_ablation:
                from xgap.agent.memory import JsonlMemoryStore
                from xgap.runtime.semantic_memory import SemanticPlanMemory
                memory_path = root / "planning_memory.jsonl"
                memory = SemanticPlanMemory(JsonlMemoryStore(memory_path), str(root.resolve()), 3600)
                if args.memory_roundtrip:
                    record["binding_warm_cases"] = [{"query_id": c["id"], "status": "not_attempted", "success": False}
                                                     for c in binding_cases]
            for case_index, case in enumerate(binding_cases):
                record["phase"] = "agentic-semantic-" + case["id"]
                if args.interpretation_recordings:
                    item = record["binding_cases"][case_index]
                    item["status"] = "started"
                else:
                    item = {"query_id": case["id"], "status": "started", "success": False}
                    record["binding_cases"].append(item)
                save()
                provider = (ReplayInterpretationProvider.from_path(
                    Path(args.interpretation_recordings) / (case["id"] + ".json"))
                    if args.interpretation_recordings else None)
                item.update(execute_binding_case(case, mapping, clients={"neo4j": neo, "fuseki": rdf},
                            interpretation_provider=provider,
                            plan_memory=memory if args.memory_roundtrip or args.refresh_ablation else None,
                            validate_candidates=not args.refresh_ablation,
                            static_backend_order=tuple(args.static_backend_order) if args.static_backend_order else None),
                            status="completed")
                if provider is not None:
                    provider.assert_consumed()
                save()
                if not item["success"]:
                    raise RuntimeError(f"Semantic binding failed: {case['id']}; no retry")
                if args.refresh_ablation:
                    from xgap.experiments.toy_refresh import execute_refresh_ablation
                    record["phase"] = "A1-B04-refresh-arms"
                    execute_refresh_ablation(case, mapping, clients={"neo4j": neo, "fuseki": rdf},
                        memory=memory, record=record["refresh_ablation"], on_update=save)
                if args.memory_roundtrip:
                    warm = record["binding_warm_cases"][case_index]
                    warm["status"] = "started"
                    record["phase"] = "agentic-semantic-memory-warm-" + case["id"]
                    save()
                    reload_at = time.perf_counter()
                    reloaded = SemanticPlanMemory(JsonlMemoryStore(memory_path), str(root.resolve()), 3600)
                    warm["memory_store_reload_ms"] = (time.perf_counter() - reload_at) * 1000
                    warm_provider = (ReplayInterpretationProvider.from_path(
                        Path(args.interpretation_recordings) / (case["id"] + ".json"))
                        if args.interpretation_recordings else None)
                    warm.update(execute_binding_case(case, mapping, clients={"neo4j": neo, "fuseki": rdf},
                        interpretation_provider=warm_provider, plan_memory=reloaded, validate_candidates=False),
                        status="completed")
                    if warm_provider is not None:
                        warm_provider.assert_consumed()
                    cold_plan = item["agent_run"]["state"]["output"]["planning_run"]
                    warm_plan = (warm["agent_run"].get("state", {}).get("output") or {}).get("planning_run", {})
                    warm["memory_contract_passed"] = (
                        cold_plan["memory"]["state"] == "miss_stored"
                        and warm_plan.get("memory", {}).get("state") == "hit"
                        and warm_plan.get("observation_calls") == 0
                        and cold_plan["selected_plan"] == warm_plan.get("selected_plan")
                        and warm_plan["memory"]["historical_acquisition"]["remote_calls"] == cold_plan["observation_calls"])
                    warm["success"] = warm["success"] and warm["memory_contract_passed"]
                    save()
                    if not warm["success"]:
                        raise RuntimeError(f"Warm semantic execution failed: {case['id']}; no retry")
                for backend, client in (("neo4j", neo), ("fuseki", rdf)):
                    result = client.execute(reference_artifact(case, backend))
                    reference = {"query_id": case["id"], "backend": backend,
                        "execution": result.to_dict(), "success": False}
                    record["binding_reference_targets"].append(reference)
                    save()
                    actual = reference_rows(result, backend)
                    canonical = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
                    reference.update(actual_rows=actual,
                        success=result.success and canonical(actual) == canonical(case["expected_rows"]))
                    save()
                    if not reference["success"]:
                        raise RuntimeError(f"Independent binding reference failed: {case['id']} / {backend}; no retry")
        if args.scoped:
            scoped_cases = load_scoped_cases()
            for case in (scoped_cases[0], scoped_cases[7], scoped_cases[12]):
                record["phase"] = "scoped-planning-" + case["id"]
                wrapper = wrap_path_case(case, "fuseki")
                wrapper["expected_remote_calls"] = case["expected_remote_calls"]
                item = execute_planned_semantic_case(wrapper, mapping,
                    clients={"neo4j": neo, "fuseki": rdf},
                    max_observation_calls=2 * case["expected_remote_calls"])
                record["scoped_planned_cases"].append(item)
                save()
                if not item["success"]:
                    raise RuntimeError(f"Scoped planning failed: {case['id']}; retained without retry")
        if args.boolean:
            for case in load_boolean_matches():
                for backend, client in (("neo4j", neo), ("fuseki", rdf)):
                    record["phase"] = "boolean-match-" + case["id"] + "-" + backend
                    item = {"query_id": case["id"], "backend": backend, "success": False, "status": "started"}
                    record["boolean_matches"].append(item)
                    save()
                    item.update(execute_semantic_case(case, mapping, clients={backend: client},
                        source_bindings={"people": backend}), status="completed")
                    save()
                    if not item["success"]:
                        raise RuntimeError(f"Boolean Match failed: {case['id']} / {backend}; no retry")
                    execution = client.execute(boolean_match_reference(case, backend))
                    reference = {"query_id": case["id"], "backend": backend,
                        "execution": execution.to_dict(), "success": False}
                    record["boolean_match_references"].append(reference)
                    save()
                    actual = boolean_match_reference_rows(execution, backend)
                    canonical = lambda rows: sorted(json.dumps(r, sort_keys=True) for r in rows)
                    reference.update(actual_rows=actual, success=execution.success and
                        canonical(actual) == canonical(case["expected_rows"]))
                    save()
                    if not reference["success"]:
                        raise RuntimeError(f"Independent Boolean Match failed: {case['id']} / {backend}; no retry")
            boolean_cases = load_boolean_cases()
            planning_cases = []
            for case in (boolean_cases[3], boolean_cases[13]):
                wrapper = wrap_path_case(case, "fuseki")
                wrapper["expected_remote_calls"] = case["expected_remote_calls"]
                planning_cases.append(wrapper)
            planning_cases.append(load_boolean_matches()[0])
            for case in planning_cases:
                record["phase"] = "boolean-planning-" + case["id"]
                item = {"query_id": case["id"], "success": False, "status": "started"}
                record["boolean_planned_cases"].append(item)
                save()
                item.update(execute_planned_semantic_case(case, mapping,
                    clients={"neo4j": neo, "fuseki": rdf}, fixture_root=BOOLEAN_FIXTURE,
                    max_observation_calls=2 * case["expected_remote_calls"]), status="completed")
                save()
                if not item["success"]:
                    raise RuntimeError(f"Boolean planning failed: {case['id']}; no retry")
        if args.typed_bindings:
            for case in typed_cases:
                record["phase"] = "typed-planning-" + case["id"]
                item = {"query_id": case["id"], "success": False, "status": "started"}
                record["typed_planned_cases"].append(item)
                save()
                item.update(execute_planned_semantic_case(case, mapping,
                    clients={"neo4j": neo, "fuseki": rdf}, logical_sources=typed_sources(),
                    operator_sources=case["operator_sources"], max_observation_calls=8), status="completed")
                save()
                if not item["success"]:
                    raise RuntimeError(f"Typed planning failed: {case['id']}; no retry")
                for backend in case["reference_target_queries"]:
                    record["phase"] = "typed-reference-" + case["id"] + "-" + backend
                    reference = {"query_id": case["id"], "backend": backend, "success": False}
                    record["typed_reference_targets"].append(reference)
                    save()
                    artifact = typed_reference(case, backend)
                    execution = {"neo4j": neo, "fuseki": rdf}[backend].execute(artifact)
                    actual = typed_reference_rows(execution, backend, case["reference_columns"])
                    reference.update(artifact=artifact.to_dict(), execution=execution.to_dict(),
                        actual_rows=actual, success=execution.success and typed_rows_match(case, actual))
                    save()
                    if not reference["success"]:
                        raise RuntimeError(f"Typed independent reference failed: {case['id']}/{backend}; no retry")
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
        for item in [*record.get("binding_cases", []), *record.get("binding_warm_cases", [])]:
            if item["status"] in {"started", "not_attempted"}:
                item["status"] = "failed" if item["status"] == "started" else "not_attempted_after_failure"
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
        "planned_cases_passed": sum(x["success"] for x in record.get("planned_cases", [])),
        "binding_cases_passed": sum(x["success"] for x in record.get("binding_cases", [])),
        "binding_warm_cases_passed": sum(x["success"] for x in record.get("binding_warm_cases", [])),
        "refresh_ablation_passed": record.get("refresh_ablation", {}).get("success"),
        "prefix_ablation_passed": record.get("prefix_ablation", {}).get("success"),
        "prefix_references_passed": sum(x["success"] for x in record.get("prefix_ablation", {}).get("references", [])),
        "binding_references_passed": sum(x["success"] for x in record.get("binding_reference_targets", [])),
        "orientation_references_passed": sum(x["success"] for x in record.get("orientation_reference_targets", [])),
        "repetition_references_passed": sum(x["success"] for x in record.get("repetition_reference_targets", [])),
        "typed_planned_passed": sum(x["success"] for x in record.get("typed_planned_cases", [])),
        "typed_references_passed": sum(x["success"] for x in record.get("typed_reference_targets", [])),
        "boolean_references_passed": sum(x["success"] for x in record.get("boolean_reference_targets", [])),
        "boolean_matches_passed": sum(x["success"] for x in record.get("boolean_matches", [])),
        "boolean_match_references_passed": sum(x["success"] for x in record.get("boolean_match_references", [])),
        "boolean_planned_passed": sum(x["success"] for x in record.get("boolean_planned_cases", [])),
        "scoped_references_passed": sum(x["success"] for x in record.get("scoped_reference_targets", [])),
        "scoped_planned_passed": sum(x["success"] for x in record.get("scoped_planned_cases", [])),
        "compiled_slice_passed": record.get("vertical_slice", {}).get("success"), "output": str(root)}))
    return 0 if record["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
