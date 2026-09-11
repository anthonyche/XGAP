"""One tiny resource-triple gate against caller-owned, already running stores.

Five semantic programs run once per engine (ten queries), after one load per
engine. This script starts no services, retries no calls, and builds no catalog.
Use fresh isolated stores; the loader adds triples and never clears existing data.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.compilers.rdf_encoding import RdfResourceTripleEncoding
from xgap.experiments.m15_fixture_loader import FusekiGraphStoreFixtureLoader
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.contracts import RuntimeNodeKind
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.semantic_compiler import SemanticBackend, compile_semantic_program
from xgap.semantic.program import SemanticGraphProgram
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


NAMESPACE = "http://rdf.freebase.com/ns/"
IDENTITY = "type.object.id"
CLASS_PREDICATE = NAMESPACE + "type.object.type"
BACKENDS = ("neo4j", "fuseki")
CALL_BUDGET = 12


def _write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _gold_edge(subject, predicate, object_):
    # Independently authored from stored triples, never from compiler/decoder rows.
    return "rdf-triple-v1:" + json.dumps(
        [NAMESPACE + subject, NAMESPACE + predicate, NAMESPACE + object_],
        ensure_ascii=False, separators=(",", ":"))


def resource_triple_fixture():
    """Return source facts, controlled semantic inputs, and independent gold."""
    triples = [
        ["m.a", "test.p", "m.b"],
        ["m.a", "test.p", "m.b"],  # Deliberate duplicate input occurrence.
        ["m.a", "test.q", "m.b"],  # Same endpoints, distinct predicate/edge.
        ["m.c", "test.q", "m.b"],
        ["m.a", "test.r", "m.d"],
        ["m.c", "test.r", "m.d"],
        *[[node, "type.object.type", "test.person"]
          for node in ("m.a", "m.b", "m.c", "m.d")],
    ]
    source = {"schema": "xgap_resource_triple_native_fixture_v1",
              "resource_namespace": NAMESPACE, "class_predicate_iri": CLASS_PREDICATE,
              "triples": [[NAMESPACE + term for term in triple] for triple in triples]}
    # A stored foreign IRI must be filtered before decoding by identity != z.
    source["triples"].append(["http://outside.invalid/x", NAMESPACE + "test.foreign", NAMESPACE + "b"])

    def rel(label, direction):
        return {"kind": "rel", "edge": {"label": label, "direction": direction}}

    def seq(left, right):
        return {"kind": "seq", "left": left, "right": right}

    def node(identifier=None):
        return {"label": "test.person", "properties": (
            {IDENTITY: identifier} if identifier is not None else {})}

    def case(identifier, description, source_id, target_id, expr, paths, endpoints,
             *, restrictor="WALK", condition=None):
        pattern = {"source": node(source_id), "target": node(target_id), "expr": expr,
                   "selector": {"kind": "ALL"}, "restrictor": restrictor,
                   "condition": condition}
        return {"id": identifier, "description": description, "program": {
            "program_id": identifier, "operators": [
                {"operator_id": "paths", "kind": "traverse", "input_ids": [],
                 "input_kinds": [], "output_kind": "path_set",
                 "parameters": {"path_pattern": pattern}},
                {"operator_id": "endpoints", "kind": "project", "input_ids": ["paths"],
                 "input_kinds": ["path_set"], "output_kind": "binding_set",
                 "parameters": {"projections": {
                     "start": {"kind": "path_node", "position": "first"},
                     "endpoint": {"kind": "path_node", "position": "last"}}}}],
            "roots": ["paths", "endpoints"]},
            "gold": {"paths": [{"path": path} for path in paths],
                     "endpoints": [{"start": NAMESPACE + source_id,
                                    "endpoint": NAMESPACE + end} for end in endpoints]}}

    ab_p = _gold_edge("m.a", "test.p", "m.b")
    ab_q = _gold_edge("m.a", "test.q", "m.b")
    cb_q = _gold_edge("m.c", "test.q", "m.b")
    cd_r = _gold_edge("m.c", "test.r", "m.d")
    mixed = seq(rel("test.p", "OUT"), rel("test.q", "IN"))
    inequalities = {"kind": "and", "conditions": [
        {"kind": "node_not_equals", "left": {"kind": "node", "position": left},
         "right": {"kind": "node", "position": right}}
        for left in range(1, 5) for right in range(left + 1, 5)]}
    cases = [
        case("RT01", "Unlabeled OUT: duplicate folds, p/q edge identities remain distinct",
             "m.a", "m.b", rel(None, "OUT"),
             [["m.a", ab_p, "m.b"], ["m.a", ab_q, "m.b"]], ["m.b"]),
        case("RT02", "IN preserves the stored OUT edge identity and reverses endpoints",
             "m.b", "m.a", rel("test.p", "IN"), [["m.b", ab_p, "m.a"]], ["m.a"]),
        case("RT03", "Two-hop mixed WALK includes the branch returning to its start",
             "m.a", None, mixed,
             [["m.a", ab_p, "m.b", ab_q, "m.a"],
              ["m.a", ab_p, "m.b", cb_q, "m.c"]], ["m.a", "m.c"]),
        case("RT04", "Three-hop mixed SIMPLE with all-pairs node inequalities",
             "m.a", "m.d", seq(mixed, rel("test.r", "OUT")),
             [["m.a", ab_p, "m.b", cb_q, "m.c", cd_r, "m.d"]], ["m.d"],
             restrictor="SIMPLE", condition=inequalities),
    ]
    foreign = case("RT05", "Identity inequality retains the canonical namespace domain",
                   "z", "b", rel("test.foreign", "OUT"), [], [], condition={
                       "kind": "property_not_equals", "ref": {"kind": "node", "position": "first"},
                       "property": IDENTITY, "value": "z"})
    foreign_pattern = foreign["program"]["operators"][0]["parameters"]["path_pattern"]
    foreign_pattern["source"] = {}
    foreign_pattern["target"] = {"properties": {IDENTITY: "b"}}
    cases.append(foreign)
    return source, cases


def run_resource_triple_gate(*, clients, fuseki_loader, output):
    """Load and run exactly one gate; persist failure evidence before propagating it.

    The caller owns service lifetime and supplies fresh isolated Neo4j/Fuseki
    stores. Each supplied client performs its normal, unmodified native request.
    """
    if set(clients) != set(BACKENDS) or any(clients[key].backend_id != key for key in BACKENDS):
        raise ValueError("The native gate requires explicit neo4j and fuseki clients")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    source, cases = resource_triple_fixture()
    source_path = output / "source_triples.json"
    _write_json(source_path, source)
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    ttl_path = output / "source_triples.ttl"
    ttl_path.write_text("".join(" ".join(f"<{term}>" for term in triple) + " .\n"
                                for triple in source["triples"]), encoding="utf-8")
    _write_json(output / "cases_and_independent_gold.json", cases)
    encoding = RdfResourceTripleEncoding("int1-resource-triples-v1", "sha256:" + source_sha,
        NAMESPACE, identity_property=IDENTITY, class_predicate_iri=CLASS_PREDICATE, max_rows=100)
    record = {"schema": "xgap_resource_triple_native_gate_v1", "status": "preparing",
        "started_at": datetime.now(timezone.utc).isoformat(), "success": False,
        "paper_result": False, "live_llm": False, "catalog_build": False,
        "source": {"path": str(source_path), "sha256": source_sha,
                   "input_triple_count": len(source["triples"]),
                   "unique_triple_count": len({tuple(t) for t in source["triples"]}),
                   "turtle_path": str(ttl_path),
                   "turtle_sha256": hashlib.sha256(ttl_path.read_bytes()).hexdigest()},
        "encoding": {**asdict(encoding), "identity": encoding.identity},
        "call_budget": CALL_BUDGET, "calls_attempted": 0,
        "loads": [{"backend_id": backend, "status": "not_attempted"} for backend in BACKENDS],
        "runs": [{"case_id": case["id"], "backend_id": backend, "status": "not_attempted",
                  "gold": case["gold"]} for case in cases for backend in BACKENDS],
        "calls": []}

    def persist():
        record["elapsed_ms"] = (time.perf_counter() - started) * 1000
        _write_json(output / "report.json", record)

    def invoke(backend, kind, action, artifact=None):
        if record["calls_attempted"] >= CALL_BUDGET:
            raise RuntimeError("native_call_budget_exceeded")
        call = {"backend_id": backend, "kind": kind, "status": "attempted",
                "sequence": record["calls_attempted"] + 1}
        if artifact is not None:
            call["artifact"] = artifact.to_dict()
        record["calls"].append(call)
        record["calls_attempted"] += 1
        persist()
        call_started = time.perf_counter()
        try:
            result = action()
            call.update(status="success" if result.success else "failed", report=result.to_dict())
            return result
        except Exception as exc:
            call.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            call["wall_elapsed_ms"] = (time.perf_counter() - call_started) * 1000
            persist()

    class RecordedClient:
        def __init__(self, backend):
            self.backend_id = backend

        def execute(self, artifact):
            return invoke(self.backend_id, "query", lambda: clients[self.backend_id].execute(artifact), artifact)

    active = None
    persist()
    try:
        backends = {backend: SemanticBackend(backend, NAMESPACE, identity_property=IDENTITY,
                    rdf_resource_encoding=encoding) for backend in BACKENDS}
        plans = []
        # Admit all ten ordinary semantic plans before the first external call.
        for case in cases:
            program = SemanticGraphProgram.from_dict(case["program"])
            for backend in BACKENDS:
                active = record["runs"][len(plans)]
                plan = compile_semantic_program(program, source_bindings={"paths": backend},
                    backends=backends, max_remote_calls=1, max_parallelism=1)
                if sum(n.kind is RuntimeNodeKind.REMOTE_QUERY for n in plan.nodes) != 1:
                    raise RuntimeError("expected_one_remote_query_per_program")
                active["plan"] = plan.to_dict()
                plans.append(plan)
        record["status"] = "running"
        create = QueryArtifact("int1-resource-triple-load", "cypher",
            "UNWIND $triples AS triple\n"
            "MERGE (s:XgapRdfResource {iri: triple[0]})\n"
            "MERGE (o:XgapRdfResource {iri: triple[2]})\n"
            "MERGE (s)-[:XGAP_RDF_RESOURCE_EDGE {predicate: triple[1]}]->(o)\n"
            "RETURN count(*) AS input_rows", parameters={"triples": source["triples"]})
        for backend, action, artifact in (
            ("neo4j", lambda: clients["neo4j"].execute(create), create),
            ("fuseki", lambda: fuseki_loader.load(ttl_path), None),
        ):
            active = record["loads"][BACKENDS.index(backend)]
            active["status"] = "attempted"
            loaded = invoke(backend, "load", action, artifact)
            active["report"] = loaded.to_dict()
            if not loaded.success:
                raise RuntimeError(f"{backend}_load_failed")
            active.update(status="success", success=True)
            persist()
        plugins = BackendPluginRegistry()
        for backend in BACKENDS:
            plugins.register(NativeBackendPlugin(backend, RecordedClient(backend)))
        scheduler = FederatedScheduler(BackendInvokeTool(plugins))
        canonical = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
        for plan, active in zip(plans, record["runs"]):
            active["status"] = "attempted"
            persist()
            result = scheduler.execute(plan)
            active["runtime"] = result.to_dict()
            active["execution_success"] = result.success
            actual = {semantic_id: list(result.root_rows.get(runtime_id, ()))
                      for semantic_id, runtime_id in plan.metadata["operator_outputs"].items()}
            active["actual"] = actual
            checks = {"execution_success": result.success,
                      "one_remote_call": result.total_remote_calls == 1,
                      "gold_paths": canonical(actual["paths"]) == canonical(active["gold"]["paths"]),
                      "gold_endpoints": canonical(actual["endpoints"]) == canonical(active["gold"]["endpoints"])}
            active["checks"] = checks
            failed = [name for name, passed in checks.items() if not passed]
            if failed:
                active["status"] = "contract_failed"
                raise RuntimeError(f"{active['case_id']}/{active['backend_id']}: {', '.join(failed)}")
            active.update(status="success", success=True)
            persist()
        if record["calls_attempted"] != CALL_BUDGET:
            raise RuntimeError("expected_twelve_native_calls")
        record.update(status="success", success=True)
    except Exception as exc:
        record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        if active is not None and active["status"] != "success":
            active.update(status="contract_failed" if active["status"] == "contract_failed" else "failed",
                          success=False, error=record["error"])
        for item in record["loads"] + record["runs"]:
            if item["status"] == "not_attempted":
                item["status"] = "not_attempted_after_failure"
        raise
    finally:
        persist()
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--neo4j-http-url", required=True)
    parser.add_argument("--neo4j-database", default="neo4j")
    parser.add_argument("--fuseki-base-url", required=True)
    parser.add_argument("--fuseki-dataset", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error("--execute is required; use caller-owned fresh isolated stores")
    neo = Neo4jClient(BackendDescriptor("neo4j", "neo4j", "cypher", "property_graph",
                                      runtime={"timeout_seconds": 35}))
    rdf_descriptor = BackendDescriptor("fuseki", "fuseki", "sparql", "rdf",
                                       runtime={"timeout_seconds": 35})
    rdf = FusekiClient(rdf_descriptor)
    loader = FusekiGraphStoreFixtureLoader(rdf_descriptor)
    neo.http_url, neo.database = args.neo4j_http_url.rstrip("/"), args.neo4j_database
    rdf.base_url = loader.base_url = args.fuseki_base_url.rstrip("/")
    rdf.dataset = loader.dataset = args.fuseki_dataset
    report = run_resource_triple_gate(clients={"neo4j": neo, "fuseki": rdf},
                                     fuseki_loader=loader, output=args.output)
    print(json.dumps({"success": report["success"], "calls_attempted": report["calls_attempted"],
                      "report": str(Path(args.output).resolve() / "report.json")}))


if __name__ == "__main__":
    main()
