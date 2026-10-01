"""Independent tiny deterministic cost workload, declared before collection.

No B01 program, response, answer or measured label is read. This prepares 28
training plans and one excluded semantic request, not an evaluation campaign.
"""

from dataclasses import replace
import hashlib
import json
import random

from xgap.experiments.toy_backbone import DEFAULT_FIXTURE
from xgap.experiments.toy_semantic import toy_backends
from xgap.planning.runtime_estimator import FrozenSourceStatistics, SourceStatistics
from xgap.planning.runtime_work_estimator import extract_work_features
from xgap.runtime.physical_strategies import prepare_physical_strategies
from xgap.semantic.program import SemanticGraphProgram


PROFILE = "xgap-independent-tiny-work-training-v2"
HELDOUT_ID = "WORK-HOLDOUT-01"
EXCLUDED_IDS = ("B01", "B02", "B03", "B04", "B05", HELDOUT_ID)


def op(identifier, kind, inputs=(), output="binding_set", parameters=None, input_kind="binding_set"):
    return {"operator_id": identifier, "kind": kind, "input_ids": list(inputs),
        "input_kinds": [input_kind] * len(inputs), "output_kind": output,
        "parameters": parameters or {}, "constraints": [], "required_capabilities": []}


def match(identifier, *, age=None):
    node = {"label": "Person", "properties": {} if age is None else {"age": age}}
    return op(identifier, "match", parameters={"node": node,
        "entity_field": "person", "properties": {"age": "age"}})


def path(identifier, source, length):
    edge = {"kind": "rel", "edge": {"label": "KNOWS", "direction": "OUT", "properties": {}}}
    expression = edge if length == 1 else {"kind": "seq", "left": edge, "right": edge}
    return op(identifier, "traverse", output="path_set", parameters={"path_pattern": {
        "path_var": None, "source": {"properties": {"id": source}}, "target": {},
        "expr": expression, "selector": {"kind": "ALL", "k": None},
        "restrictor": "WALK", "condition": None, "max_depth": None}})


def path_match_program(query_id, *, source="b", length=1, threshold=18):
    operators = [path("walk", source, length),
        op("reached", "project", ("walk",), input_kind="path_set", parameters={"projections": {
            "person": {"kind": "path_node", "position": "last"},
            "edge": {"kind": "path_edge", "position": 1}}}), match("profiles"),
        op("adult", "filter", ("profiles",), parameters={"condition": {"op": "ge", "field": "age", "value": threshold}}),
        op("join", "join", ("reached", "adult"), parameters={"left_on": "person", "right_on": "person"}),
        op("answer", "project", ("join",), parameters={"projections": {
            "person": {"kind": "field", "field": "person"}, "edge": {"kind": "field", "field": "edge"}}})]
    return SemanticGraphProgram.from_dict({"program_id": query_id, "operators": operators,
        "roots": ["answer"], "holes": [], "metadata": {}})


def _program(query_id, operators):
    return SemanticGraphProgram.from_dict({"program_id": query_id, "operators": operators,
        "roots": [operators[-1]["operator_id"]], "holes": [], "metadata": {}})


def prepare_tiny_work_training():
    graph_path = DEFAULT_FIXTURE / "graph.json"
    graph = json.loads(graph_path.read_text())
    mapping = json.loads((DEFAULT_FIXTURE / "mapping.json").read_text())
    backends = toy_backends(mapping)
    version = hashlib.sha256(json.dumps(graph, sort_keys=True).encode()).hexdigest()
    rows = [*graph["nodes"], *graph["edges"]]
    width = sum(len(json.dumps(r, sort_keys=True, separators=(",", ":")).encode()) for r in rows) / len(rows)
    statistics = FrozenSourceStatistics("original-tiny-logical-source", version, tuple(
        SourceStatistics(b, "toy", version, len(rows), width,
            "graph.json#sha256=" + hashlib.sha256(graph_path.read_bytes()).hexdigest() + ";logical-node-and-edge-records")
        for b in ("neo4j", "fuseki")))
    entries = []

    def add(query_id, program, placement, strategy="coordinator"):
        domain = prepare_physical_strategies(program, source_bindings=placement, backends=backends)
        candidates = [c for c in domain.candidates if c.strategy_id == strategy]
        if len(candidates) != 1:
            raise ValueError(f"Training strategy not uniquely available: {query_id}/{strategy}")
        plan = candidates[0].plan
        plan = replace(plan, metadata={**plan.metadata, "query_id": query_id,
            "source_snapshot_versions": {b: version for b in set(placement.values())},
            "source_identities": {b: {"source_id": "toy", "snapshot_version": version} for b in set(placement.values())}})
        features = extract_work_features(plan, statistics)
        if features.unknown_fields:
            raise ValueError(f"Training features unavailable: {query_id}: {features.unknown_fields}")
        entries.append({"query_id": query_id, "split_role": "training", "plan": plan,
            "program": program.to_dict(), "placement": placement, "strategy": strategy,
            "features": features.to_dict()})

    for backend in ("neo4j", "fuseki"):
        for age in (19, 40):
            q = f"WORK-TRAIN-M-{backend}-{age}"
            add(q, _program(q, [match("profiles", age=age)]), {"profiles": backend})
        for length in (1, 2):
            q = f"WORK-TRAIN-P-{backend}-{length}"
            add(q, _program(q, [path("walk", "d", length)]), {"walk": backend})
        q = f"WORK-TRAIN-A-{backend}"
        operators = [match("profiles"), op("totals", "aggregate", ("profiles",), output="grouped_bindings",
            parameters={"group_by": ["person"], "aggregations": {"total": {"op": "sum", "field": "age"}}}),
            op("top", "order_limit", ("totals",), output="grouped_bindings", input_kind="grouped_bindings",
                parameters={"order_by": [{"field": "total", "direction": "desc"}], "limit": 3})]
        add(q, _program(q, operators), {"profiles": backend})
        q = f"WORK-TRAIN-U-{backend}"
        operators = [match("left", age=22), match("right", age=50),
            op("both", "union", ("left", "right")),
            op("aligned", "align", ("both",), parameters={"field": "person", "mapping": {}, "on_missing": "keep"})]
        add(q, _program(q, operators), {"left": backend, "right": backend})
    for left, right in (("neo4j", "neo4j"), ("fuseki", "fuseki"), ("neo4j", "fuseki"), ("fuseki", "neo4j")):
        for variant, strategy in (("C", "coordinator"), ("B", "entity_bind/join/left_to_right")):
            q = f"WORK-TRAIN-MM-{left}-{right}-{variant}"
            operators = [match("left", age=30), match("right"),
                op("join", "join", ("left", "right"), parameters={"left_on": "person", "right_on": "person"}),
                op("answer", "project", ("join",), parameters={"projections": {"person": {"kind": "field", "field": "person"}}})]
            add(q, _program(q, operators), {"left": left, "right": right}, strategy)
            q = f"WORK-TRAIN-PM-{left}-{right}-{variant}"
            program = path_match_program(q, source="d" if left == right else "b", length=2 if left == right else 1)
            add(q, program, {"walk": left, "profiles": right}, strategy)
    # One fixed interleaving, before timing any execution. Never search an order.
    random.Random(2026091202).shuffle(entries)
    heldout = path_match_program(HELDOUT_ID, source="c", threshold=28)
    return statistics, entries, heldout, backends


def heldout_expected_rows():
    """Independent fixture reference, used only after sealing the selected result."""
    graph = json.loads((DEFAULT_FIXTURE / "graph.json").read_text())
    nodes = {n["id"]: n for n in graph["nodes"]}
    ns = "https://xgap.test/toy/"
    return [{"person": ns + e["target"], "edge": ns + e["id"]} for e in graph["edges"]
            if e["source"] == "c" and e["label"] == "KNOWS"
            and nodes[e["target"]]["label"] == "Person" and nodes[e["target"]]["properties"]["age"] >= 28]
