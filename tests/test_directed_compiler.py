"""Directed compilation contract and independent SPARQL execution tests.

RDFLib checks run only with the optional test engine installed. They execute
the emitted query, not a canned client answer; no server or network is used.
"""

from copy import deepcopy
from dataclasses import replace
from itertools import product

import pytest

from xgap.algebra.conditions import (
    And,
    EdgeRef,
    LabelEquals,
    LengthEquals,
    NodeNotEquals,
    NodeRef,
    Not,
    Or,
    PropertyEquals,
    PropertyNotEquals,
    PropertyLessThan,
    PropertyLessThanOrEqual,
    PropertyGreaterThan,
    PropertyGreaterThanOrEqual,
)
from xgap.backends.capabilities import SupportLevel
from xgap.backends.mapping import RdfBackendMapping
from xgap.compilers import compile_cypher, compile_sparql, UnsupportedCompilationError
from xgap.compilers.directed import MAX_EDGES, PROFILE, compile_directed_rows
from xgap.compilers.features import default_profile
from xgap.infrastructure.runtime import ExecutionReport, QueryArtifact
from xgap.pattern.ast import (
    Alt,
    Bounded,
    Direction,
    EdgePattern,
    NodePattern,
    OptionalExpr,
    PathMode,
    PathPatternQuery,
    Plus,
    Rel,
    Selector,
    SelectorKind,
    Seq,
    Star,
    Var,
)
from xgap.pattern.semantic_validation import type_check_semantic_path_pattern
from xgap.pattern.typecheck import PatternTypeError
from xgap.runtime import (
    FederatedExecutionPlan,
    FederatedScheduler,
    FragmentCompilationError,
    RuntimeNode,
    RuntimeNodeKind,
    SemanticFragment,
)
from xgap.runtime.directed_fragments import DirectedRowFragmentCompiler
from xgap.tools.backends import (
    BackendInvokeTool,
    BackendPluginRegistry,
    NativeBackendPlugin,
)


OUT, IN = Direction.OUT, Direction.IN
NS = "urn:xgap:directed-test:"


def query(*directions, labels=None, **overrides):
    directions = directions or (OUT,)
    labels = labels or ("r",) * len(directions)
    parts = [
        Rel(EdgePattern(label=label, direction=direction))
        for label, direction in zip(labels, directions)
    ]
    expr = parts[0]
    for part in parts[1:]:
        expr = Seq(expr, part)
    return replace(
        PathPatternQuery(
            None,
            NodePattern(),
            expr,
            NodePattern(),
            Selector(SelectorKind.ALL),
            PathMode.WALK,
        ),
        **overrides,
    )


@pytest.fixture
def mapping():
    kinds = {
        "node_labels": ("class", ("Person", "Company")),
        "edge_labels": ("relation", ("r", "s")),
        "properties": ("property", ("name", "mid", "score", "active")),
    }
    return {
        "mapping_id": "directed-test-map",
        "version": "1",
        "backends": {
            "fuseki": {
                "namespace": NS,
                "compiler_tokens": {
                    key: {token: token for token in tokens}
                    for key, (_, tokens) in kinds.items()
                },
            }
        },
        "term_mappings": {
            "fuseki": {
                token: {"kind": kind, "representation": NS + token}
                for kind, tokens in kinds.values()
                for token in tokens
            }
        },
    }


def compile_rdf(value, mapping):
    return compile_directed_rows(value, backend_id="fuseki", backend_mapping=mapping)


@pytest.fixture
def rdf():
    return pytest.importorskip("rdflib", minversion="7.1.4")


def graph_from_edges(rdf, edges):
    graph = rdf.Graph()
    for source, relation, target in edges:
        graph.add(tuple(rdf.URIRef(NS + value) for value in (source, relation, target)))
    return graph


def actual_walks(graph, artifact):
    count = len(artifact.parameters["directions"])
    return {
        (
            tuple(str(row[f"n{i}"]) for i in range(count + 1)),
            tuple(str(row[f"e{i}"]) for i in range(1, count + 1)),
        )
        for row in graph.query(artifact.text)
    }


def expected_walks(edges, directions, labels):
    # Independent traversal reference over the input triples, not compiler
    # variables, compiled text, or a reversed copy of the stored graph.
    paths = {((node,), ()) for left, _, right in edges for node in (left, right)}
    for direction, label in zip(directions, labels):
        following = set()
        for nodes, relations in paths:
            for left, relation, right in edges:
                source, target = (left, right) if direction is OUT else (right, left)
                if nodes[-1] == source and (label is None or label == relation):
                    following.add((nodes + (target,), relations + (relation,)))
        paths = following
    return {
        (tuple(NS + n for n in nodes), tuple(NS + r for r in rels))
        for nodes, rels in paths
    }


DIRECTION_CASES = [
    dirs for length in (1, 2, 3, 4) for dirs in product((OUT, IN), repeat=length)
]


@pytest.mark.parametrize("directions", DIRECTION_CASES)
def test_direction_positions_and_hashes_are_exact(directions, mapping):
    value = query(*directions)
    before = deepcopy(value)
    cypher = compile_directed_rows(value, backend_id="neo4j")
    sparql = compile_rdf(value, mapping)
    for index, direction in enumerate(directions):
        arrow = f"-[e{index + 1}]->" if direction is OUT else f"<-[e{index + 1}]-"
        assert f"MATCH (n{index}){arrow}(n{index + 1})" in cypher.text
        left, right = (index, index + 1) if direction is OUT else (index + 1, index)
        assert f"?n{left} <{NS}r> ?n{right} ." in sparql.text
    assert cypher.text.count("MATCH ") == len(directions)
    for artifact in (cypher, sparql):
        assert artifact.kind == "compiled"
        assert artifact.parameters["compiler"] == PROFILE
        assert artifact.parameters["backend_execution_verified"] is False
        assert QueryArtifact.from_dict(artifact.to_dict()) == artifact
        assert len(artifact.parameters["input_pattern_sha256"]) == 64
    assert (
        cypher.parameters["input_pattern_sha256"]
        == sparql.parameters["input_pattern_sha256"]
    )
    assert value == before


@pytest.mark.parametrize("directions", DIRECTION_CASES)
def test_emitted_sparql_equals_independent_traversal(directions, mapping, rdf):
    edges = (
        ("a", "r", "b"),
        ("c", "r", "b"),
        ("b", "r", "d"),
        ("d", "r", "a"),
        ("b", "r", "b"),
        ("d", "s", "b"),
    )
    graph = graph_from_edges(rdf, edges)
    artifact = compile_rdf(query(*directions), mapping)
    assert actual_walks(graph, artifact) == expected_walks(
        edges, directions, ["r"] * len(directions)
    )
    for row in graph.query(artifact.text):
        assert row.source == row.n0
        assert row.target == row[f"n{len(directions)}"]
    assert len(graph) == len(edges)


def test_unlabeled_and_different_predicates(mapping, rdf):
    edges = (("a", "r", "b"), ("c", "s", "b"), ("b", "s", "d"))
    labels = ("r", None)
    artifact = compile_rdf(query(OUT, IN, labels=labels), mapping)
    assert actual_walks(graph_from_edges(rdf, edges), artifact) == expected_walks(
        edges, (OUT, IN), labels
    )


@pytest.mark.parametrize("mode", tuple(PathMode))
def test_fixed_restrictors_do_not_synthesize_uniqueness(mode, mapping, rdf):
    graph = graph_from_edges(rdf, [("a", "r", "b")])
    value = query(OUT, IN, restrictor=mode)
    artifact = compile_rdf(value, mapping)
    assert actual_walks(graph, artifact) == {
        ((NS + "a", NS + "b", NS + "a"), (NS + "r", NS + "r"))
    }
    explicit = replace(value, condition=NodeNotEquals(NodeRef.first(), NodeRef.last()))
    assert actual_walks(graph, compile_rdf(explicit, mapping)) == set()
    assert "!=" not in compile_directed_rows(value, backend_id="neo4j").text
    assert "n0 <> n2" in compile_directed_rows(explicit, backend_id="neo4j").text


def test_endpoint_middle_and_length_conditions_bind_traversal_positions(mapping, rdf):
    graph = graph_from_edges(rdf, [("b", "r", "a"), ("b", "s", "c"), ("b", "s", "d")])
    for node, predicate, value in [
        ("a", "name", "anchor"),
        ("b", "score", 7),
        ("c", "active", True),
    ]:
        graph.add(
            (rdf.URIRef(NS + node), rdf.URIRef(NS + predicate), rdf.Literal(value))
        )
    graph.add((rdf.URIRef(NS + "a"), rdf.RDF.type, rdf.URIRef(NS + "Person")))
    graph.add((rdf.URIRef(NS + "c"), rdf.RDF.type, rdf.URIRef(NS + "Company")))
    conditions = And(
        PropertyGreaterThan(NodeRef(2), "score", 6),
        And(PropertyEquals(NodeRef.last(), "active", True), LengthEquals(2)),
    )
    value = query(
        IN,
        OUT,
        labels=("r", "s"),
        source=NodePattern(label="Person", properties={"name": "anchor"}),
        target=NodePattern(label="Company"),
        condition=conditions,
    )
    assert actual_walks(graph, compile_rdf(value, mapping)) == {
        ((NS + "a", NS + "b", NS + "c"), (NS + "r", NS + "s"))
    }
    false_length = replace(value, condition=LengthEquals(3))
    assert actual_walks(graph, compile_rdf(false_length, mapping)) == set()
    assert "n1.score > 6" in compile_directed_rows(value, backend_id="neo4j").text


@pytest.mark.parametrize(
    "cls,expected",
    [
        (PropertyEquals, {"b"}),
        (PropertyNotEquals, {"a", "c"}),
        (PropertyLessThan, {"a"}),
        (PropertyLessThanOrEqual, {"a", "b"}),
        (PropertyGreaterThan, {"c"}),
        (PropertyGreaterThanOrEqual, {"b", "c"}),
    ],
)
def test_scalar_condition_operators(cls, expected, mapping, rdf):
    graph = graph_from_edges(rdf, [(n, "r", "z") for n in "abcd"])
    for node, score in [("a", 1), ("b", 2), ("c", 3.5)]:
        graph.add((rdf.URIRef(NS + node), rdf.URIRef(NS + "score"), rdf.Literal(score)))
    value = query(condition=cls(NodeRef.first(), "score", 2))
    rows = graph.query(compile_rdf(value, mapping).text)
    assert {str(row.source) for row in rows} == {NS + n for n in expected}


@pytest.mark.parametrize("value", [False, True, "3", "unknown"])
def test_ordering_does_not_accept_nonnumeric_property_values(value, mapping, rdf):
    graph = graph_from_edges(rdf, [("a", "r", "b")])
    graph.add((rdf.URIRef(NS + "a"), rdf.URIRef(NS + "score"), rdf.Literal(value)))
    value = query(condition=PropertyGreaterThan(NodeRef.first(), "score", 1))
    assert list(graph.query(compile_rdf(value, mapping).text)) == []
    assert (
        "IS :: INTEGER NOT NULL"
        in compile_directed_rows(value, backend_id="neo4j").text
    )


@pytest.mark.parametrize(
    "text",
    [
        'Alice "Smith"',
        "quote\\line\nnext",
        "汉字",
        "emoji 🧪",
        '" . } SERVICE <https://invalid/> { ?s ?p ?o } #',
    ],
)
def test_literals_are_data_not_query_structure(text, mapping, rdf):
    graph = graph_from_edges(rdf, [("a", "r", "b"), ("c", "r", "b")])
    graph.add((rdf.URIRef(NS + "a"), rdf.URIRef(NS + "name"), rdf.Literal(text)))
    graph.add((rdf.URIRef(NS + "c"), rdf.URIRef(NS + "name"), rdf.Literal("other")))
    value = query(source=NodePattern(properties={"name": text}))
    assert {
        str(row.source) for row in graph.query(compile_rdf(value, mapping).text)
    } == {NS + "a"}


@pytest.mark.parametrize(
    "value", [None, [], {}, 2**63, -(2**63) - 1, float("inf"), float("nan")]
)
def test_unsupported_constants_fail_closed(value):
    with pytest.raises(UnsupportedCompilationError):
        compile_directed_rows(
            query(source=NodePattern(properties={"name": value})), backend_id="neo4j"
        )


@pytest.mark.parametrize("value", ["name\\u0060", "line\nname", "tab\tname", "nul\x00"])
def test_identifier_escapes_are_refused(value):
    with pytest.raises(UnsupportedCompilationError, match="Identifiers"):
        compile_directed_rows(
            query(source=NodePattern(properties={value: 1})), backend_id="neo4j"
        )


def test_cypher_backtick_identifier_is_quoted():
    artifact = compile_directed_rows(
        query(source=NodePattern(label="r` MATCH (n)")), backend_id="neo4j"
    )
    assert "n0:`r`` MATCH (n)`" in artifact.text


@pytest.mark.parametrize("location", ["property", "label", "identifier"])
def test_lone_surrogates_are_not_valid_native_unicode(location):
    if location == "property":
        value = query(source=NodePattern(properties={"name": "\ud800"}))
    elif location == "label":
        value = query(source=NodePattern(label="\ud800"))
    else:
        value = query(source=NodePattern(properties={"\ud800": "x"}))
    with pytest.raises(UnsupportedCompilationError, match="Unicode scalar"):
        compile_directed_rows(value, backend_id="neo4j")


@pytest.mark.parametrize(
    "expr",
    [
        Alt(Rel(EdgePattern()), Rel(EdgePattern())),
        Plus(Rel(EdgePattern())),
        Star(Rel(EdgePattern())),
        OptionalExpr(Rel(EdgePattern())),
        Bounded(Rel(EdgePattern()), 1, 2),
        Rel(EdgePattern(direction=Direction.UNDIRECTED)),
    ],
)
def test_non_fixed_directed_expressions_are_explicitly_unavailable(expr):
    with pytest.raises(UnsupportedCompilationError) as caught:
        compile_directed_rows(query(expr=expr, max_depth=4), backend_id="neo4j")
    assert caught.value.failure.support_level is SupportLevel.UNSUPPORTED
    assert caught.value.failure.metadata["compiler"] == PROFILE


@pytest.mark.parametrize(
    "condition",
    [
        Or(LengthEquals(1)),
        Not(LengthEquals(1)),
        LabelEquals(NodeRef.first(), None),
        PropertyEquals(NodeRef(3), "name", "x"),
        PropertyEquals(EdgeRef(2), "name", "x"),
        NodeNotEquals(EdgeRef(1), NodeRef(1)),
    ],
)
def test_unsupported_or_invalid_conditions_do_not_disappear(condition):
    with pytest.raises(UnsupportedCompilationError):
        compile_directed_rows(query(condition=condition), backend_id="neo4j")


def test_invalid_node_identity_reference_is_a_typed_error():
    value = query(condition=NodeNotEquals(EdgeRef(1), NodeRef(1)))
    with pytest.raises(PatternTypeError, match="wrong node/edge kind"):
        type_check_semantic_path_pattern(value)


def test_bound_and_selector_are_checked():
    assert (
        compile_directed_rows(
            query(*([IN] * MAX_EDGES)), backend_id="neo4j"
        ).text.count("MATCH ")
        == MAX_EDGES
    )
    with pytest.raises(UnsupportedCompilationError, match="exceed"):
        compile_directed_rows(query(*([IN] * (MAX_EDGES + 1))), backend_id="neo4j")
    with pytest.raises(UnsupportedCompilationError, match="ALL"):
        compile_directed_rows(
            query(selector=Selector(SelectorKind.ANY)), backend_id="neo4j"
        )
    with pytest.raises(UnsupportedCompilationError, match="typed PathPatternQuery"):
        compile_directed_rows("MATCH (n) RETURN n", backend_id="neo4j")


def test_required_capability_and_backend_identity():
    profile = default_profile("neo4j")
    features = {
        key: item
        for key, item in profile.features.items()
        if key != "graph_model.directed_edges"
    }
    with pytest.raises(UnsupportedCompilationError, match="directed_edges"):
        compile_directed_rows(
            query(IN), backend_id="neo4j", profile=replace(profile, features=features)
        )
    with pytest.raises(UnsupportedCompilationError, match="identity/language"):
        compile_directed_rows(query(), backend_id="fuseki", profile=profile)
    original = compile_directed_rows(query(), backend_id="neo4j", profile=profile)
    changed = compile_directed_rows(
        query(),
        backend_id="neo4j",
        profile=replace(profile, version=profile.version + 1),
    )
    assert (
        original.parameters["backend_profile_sha256"]
        != changed.parameters["backend_profile_sha256"]
    )
    assert (
        original.parameters["input_pattern_sha256"]
        == changed.parameters["input_pattern_sha256"]
    )


def test_rdf_mapping_identity_terms_and_safety(mapping):
    with pytest.raises(UnsupportedCompilationError, match="explicit backend mapping"):
        compile_directed_rows(query(IN), backend_id="fuseki")
    with pytest.raises(UnsupportedCompilationError):
        compile_rdf(query(labels=("not-mapped",)), mapping)
    normalized = RdfBackendMapping.from_artifact(mapping)
    with pytest.raises(UnsupportedCompilationError, match="different backend"):
        compile_rdf(query(), replace(normalized, backend_id="other"))
    malicious = deepcopy(mapping)
    malicious["term_mappings"]["fuseki"]["r"][
        "representation"
    ] = "xgap:r> . } SERVICE <https://invalid/> {"
    with pytest.raises(UnsupportedCompilationError):
        compile_rdf(query(), malicious)
    changed = deepcopy(mapping)
    changed["term_mappings"]["fuseki"]["r"]["representation"] = NS + "s"
    a, b = compile_rdf(query(), mapping), compile_rdf(query(), changed)
    assert (
        a.parameters["backend_mapping"]["mapping_hash"]
        != b.parameters["backend_mapping"]["mapping_hash"]
    )
    assert a.text != b.text


def test_edge_property_is_position_bound_and_rdf_reification_is_unavailable(mapping):
    value = query(IN, OUT, condition=PropertyGreaterThan(EdgeRef(1), "score", 2))
    assert "e1.score > 2" in compile_directed_rows(value, backend_id="neo4j").text
    with pytest.raises(UnsupportedCompilationError, match="reification"):
        compile_rdf(value, mapping)


def test_legacy_direction_boundary_does_not_silently_change(mapping):
    for compile_legacy in (
        lambda value: compile_cypher(value),
        lambda value: compile_sparql(value, backend_mapping=mapping),
    ):
        with pytest.raises(UnsupportedCompilationError, match="Reverse"):
            compile_legacy(query(IN))


def test_fragment_declared_schema_cannot_invent_projection(mapping):
    compiler = DirectedRowFragmentCompiler(backend_mappings={"fuseki": mapping})
    fragment = SemanticFragment("path", "fuseki", query(IN), ("traverse",))
    compiled = compiler.compile(fragment)
    assert compiled.output_schema == ("source", "target", "n0", "n1", "e1")
    assert (
        compiler.compile(replace(fragment, output_schema=compiled.output_schema))
        == compiled
    )
    with pytest.raises(FragmentCompilationError, match="no implicit projection"):
        compiler.compile(replace(fragment, output_schema=("answer",)))


def test_compiled_fragment_runs_through_real_scheduler_and_engine(mapping, rdf):
    graph = graph_from_edges(rdf, [("b", "r", "a"), ("b", "s", "c")])
    compiler = DirectedRowFragmentCompiler(backend_mappings={"fuseki": mapping})
    value = query(IN, OUT, labels=("r", "s"))
    compiled = compiler.compile(
        SemanticFragment("path", "fuseki", value, ("traverse",))
    )
    calls = []

    class Client:
        backend_id = "fuseki"

        def execute(self, artifact):
            calls.append(artifact)
            rows = tuple(
                {str(k): str(v) for k, v in row.asdict().items()}
                for row in graph.query(artifact.text)
            )
            return ExecutionReport(
                backend_id=self.backend_id,
                artifact_id=artifact.artifact_id,
                language="sparql",
                success=True,
                rows=rows,
                elapsed_ms=0.0,
                metadata={"transport": "independent-offline-rdflib"},
            )

    plugins = BackendPluginRegistry()
    plugins.register(NativeBackendPlugin("fuseki", Client()))
    project = RuntimeNode(
        "answer",
        RuntimeNodeKind.PROJECT,
        inputs=("path",),
        parameters={"fields": ["target"]},
    )
    plan = FederatedExecutionPlan(
        "directed",
        (compiled.to_runtime_node(), project),
        ("answer",),
        max_remote_calls=1,
    )
    result = FederatedScheduler(BackendInvokeTool(plugins)).execute(
        plan, goal_id="directed-check"
    )
    assert result.success, result.to_dict()
    assert result.final_rows == ({"target": NS + "c"},)
    assert result.total_remote_calls == 1
    assert len(calls) == 1
    assert calls[0] == compiled.artifact


def test_failed_backend_is_not_retried_or_reported_as_empty_success():
    compiled = DirectedRowFragmentCompiler().compile(
        SemanticFragment("path", "neo4j", query(IN), ("traverse",))
    )
    calls = []

    class FailedClient:
        backend_id = "neo4j"

        def execute(self, artifact):
            calls.append(artifact)
            return ExecutionReport(
                backend_id="neo4j",
                artifact_id=artifact.artifact_id,
                language="cypher",
                success=False,
                error="explicit test failure",
            )

    plugins = BackendPluginRegistry()
    plugins.register(NativeBackendPlugin("neo4j", FailedClient()))
    plan = FederatedExecutionPlan(
        "failure", (compiled.to_runtime_node(),), ("path",), max_remote_calls=1
    )
    result = FederatedScheduler(BackendInvokeTool(plugins)).execute(plan)
    assert result.success is False
    assert len(calls) == 1
    assert result.total_remote_calls == 1
    assert "explicit test failure" in result.node_results[0].error


def test_public_exports_select_new_compiler_explicitly():
    from xgap.compilers import compile_directed_rows as exported_compile
    from xgap.runtime import DirectedRowFragmentCompiler as exported_adapter

    assert exported_compile is compile_directed_rows
    assert exported_adapter is DirectedRowFragmentCompiler
