"""M13-C GrailQA fragment audit and frozen evaluation artifacts."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
from typing import Any, Iterable, Mapping, Sequence

from xgap.algebra.conditions import (
    And,
    Condition,
    NodeNotEquals,
    NodeRef,
    PropertyEquals,
    PropertyGreaterThan,
    PropertyGreaterThanOrEqual,
    PropertyLessThan,
    PropertyLessThanOrEqual,
)
from xgap.algebra.ops import RecursiveMode
from xgap.algebra.pretty import format_plan
from xgap.backends import registry
from xgap.backends.mapping import RdfBackendMapping
from xgap.compilers import compile_cypher, compile_sparql
from xgap.experiments.grailqa_audit import (
    COMPARISON_FUNCTIONS,
    DATASET_FILES,
    SUPERLATIVE_FUNCTIONS,
    OntologyResources,
    analyze_s_expression,
    load_ontology_resources,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.semantic import (
    OntologyGraph,
    SemanticDeviationConfig,
)
from xgap.llm.parser import path_pattern_query_to_dict
from xgap.pattern.ast import (
    Direction,
    EdgePattern,
    NodePattern,
    PathPatternQuery,
    Rel,
    Selector,
    SelectorKind,
    Seq,
    Var,
)
from xgap.pattern.lowering import lower_to_logical_plan
from xgap.planning.topology import index_logical_plan


SCHEMA_VERSION = "m13c-grailqa-audit-v2"
FREEBASE_NAMESPACE = "http://rdf.freebase.com/ns/"
REFERENCE_EPSILONS = (0.0, 0.05, 0.1, 0.25)
RECOMMENDED_EPSILON = 0.1
ALTERNATIVES_PER_SLOT = 8
_NUMERIC_LITERAL_RE = re.compile(
    r"^(.+?)\^\^http://www\.w3\.org/2001/XMLSchema#"
    r"(int|integer|float|double|decimal)$"
)


@dataclass(frozen=True)
class NormalizedOntology:
    graph: OntologyGraph
    term_to_representative: Mapping[str, str]
    artifact: Mapping[str, Any]


@dataclass(frozen=True)
class GrailQAV2Conversion:
    record: dict[str, Any]
    query: PathPatternQuery | None

    @property
    def supported(self) -> bool:
        return self.query is not None


def normalize_ontology(ontology: OntologyResources) -> NormalizedOntology:
    """Condense every class-hierarchy SCC to a deterministic representative."""

    adjacency: dict[str, set[str]] = {term: set() for term in ontology.classes}
    for child, parent in ontology.hierarchy_edges:
        adjacency.setdefault(child, set()).add(parent)
        adjacency.setdefault(parent, set())
    components = _strongly_connected_components(adjacency)
    representative = {
        term: min(component)
        for component in components
        for term in component
    }
    normalized_edges = {
        (representative[child], representative[parent])
        for child, parent in ontology.hierarchy_edges
        if representative[child] != representative[parent]
    }
    parents: dict[str, list[str]] = defaultdict(list)
    for child, parent in sorted(normalized_edges):
        parents[child].append(parent)
    domain_range = {
        relation: {
            "domain": representative.get(domain, domain),
            "range": representative.get(range_term, range_term),
        }
        for relation, (domain, range_term) in ontology.domain_range.items()
        if relation in ontology.relations
    }
    graph = OntologyGraph(
        ontology_id="grailqa-freebase-processed-normalized",
        version="grailqa-v1.0-official-ontology-scc-v1",
        classes=tuple(sorted(ontology.classes)),
        relations=tuple(sorted(ontology.relations)),
        properties=tuple(sorted(ontology.properties)),
        parents={key: tuple(values) for key, values in sorted(parents.items())},
        domain_range=domain_range,
        max_relaxation_hops=3,
        sibling_rule_reference=None,
    )
    cyclic = tuple(
        component
        for component in components
        if len(component) > 1
        or (len(component) == 1 and component[0] in adjacency[component[0]])
    )
    original_payload = {
        "classes": sorted(ontology.classes),
        "relations": sorted(ontology.relations),
        "properties": sorted(ontology.properties),
        "hierarchy_edges": [list(item) for item in ontology.hierarchy_edges],
        "domain_range": {
            key: list(value) for key, value in sorted(ontology.domain_range.items())
        },
        "source_hashes": dict(sorted(ontology.source_hashes.items())),
    }
    artifact = {
        "schema_version": "m13c-grailqa-ontology-normalization-v1",
        "policy": "deterministic_scc_condensation_with_lexicographic_representative",
        "original_ontology_hash": content_hash(original_payload),
        "normalized_ontology_hash": graph.ontology_hash,
        "source_hashes": dict(sorted(ontology.source_hashes.items())),
        "counts": {
            "original_hierarchy_edges": len(ontology.hierarchy_edges),
            "normalized_hierarchy_edges": len(normalized_edges),
            "scc_count": len(components),
            "cyclic_scc_count": len(cyclic),
            "terms_in_cyclic_sccs": sum(len(item) for item in cyclic),
            "self_edges_removed": sum(
                1 for child, parent in ontology.hierarchy_edges if child == parent
            ),
        },
        "cyclic_components": [
            {
                "representative": min(component),
                "members": list(component),
            }
            for component in cyclic
        ],
        "term_to_representative": dict(sorted(representative.items())),
        "resulting_dag_hierarchy": [list(item) for item in sorted(normalized_edges)],
        "provenance": {
            "source": "GrailQA official processed Freebase ontology",
            "source_repository": "https://github.com/dki-lab/GrailQA",
            "edges_invented": False,
            "edges_silently_deleted": False,
            "internal_scc_edges_replaced_by_equivalence_mapping": True,
        },
    }
    return NormalizedOntology(graph, dict(sorted(representative.items())), artifact)


def _strongly_connected_components(
    adjacency: Mapping[str, set[str]],
) -> tuple[tuple[str, ...], ...]:
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for neighbor in sorted(adjacency.get(node, ())):
            if neighbor not in indices:
                visit(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[neighbor])
        if lowlinks[node] != indices[node]:
            return
        component: list[str] = []
        while True:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == node:
                break
        components.append(tuple(sorted(component)))

    for node in sorted(adjacency):
        if node not in indices:
            visit(node)
    return tuple(sorted(components, key=lambda item: item[0]))


def convert_question_v2(
    question: Mapping[str, Any],
    split: str,
    ontology: OntologyResources,
    *,
    normalized_ontology: NormalizedOntology | None = None,
    cypher_profile: object | None = None,
    sparql_profile: object | None = None,
    rdf_mapping: RdfBackendMapping | None = None,
) -> GrailQAV2Conversion:
    """Convert the selected M13-C fragment through the real XGAP boundaries."""

    question_id = str(question.get("qid", ""))
    base: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "question_id": question_id,
        "split": split,
        "level": str(question.get("level", "not_available")),
        "status": "unsupported",
    }
    expression = question.get("s_expression")
    graph_query = question.get("graph_query")
    if not isinstance(expression, str) or not isinstance(graph_query, Mapping):
        return _unsupported(base, "missing_gold_logical_form", "public annotation is masked")
    try:
        expression_analysis = analyze_s_expression(expression)
    except (TypeError, ValueError) as error:
        return _unsupported(base, "parser_failure", str(error))
    base["gold_operators"] = list(expression_analysis.operators)

    function = str(question.get("function", "none"))
    if function == "count":
        return _unsupported(base, "unsupported_aggregation", "COUNT")
    if function in SUPERLATIVE_FUNCTIONS:
        return _unsupported(base, "unsupported_ordering", function)
    if function not in {"none", *COMPARISON_FUNCTIONS}:
        return _unsupported(base, "unsupported_operator", function)

    raw_nodes = graph_query.get("nodes")
    raw_edges = graph_query.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        return _unsupported(base, "parser_failure", "graph_query nodes/edges are malformed")
    if not all(isinstance(item, Mapping) for item in (*raw_nodes, *raw_edges)):
        return _unsupported(base, "parser_failure", "graph_query entries must be objects")
    nodes = [dict(item) for item in raw_nodes]
    edges = [dict(item) for item in raw_edges]

    comparison: tuple[str, object, str] | None = None
    if function in COMPARISON_FUNCTIONS:
        comparison_result = _extract_comparison(function, nodes, edges, ontology)
        if isinstance(comparison_result, str):
            return _unsupported(base, "unsupported_comparison", comparison_result)
        nodes, edges, property_node_id, property_name, value = comparison_result
        comparison = (property_node_id, value, property_name)
        base["comparison_operator"] = function
        base["comparison_property"] = property_name
        base["comparison_value"] = value
    elif any(node.get("node_type") == "literal" for node in nodes):
        return _unsupported(base, "unsupported_path_semantics", "literal constraint")

    path_result = _linear_path(nodes, edges)
    if isinstance(path_result, str):
        reason = (
            "missing_entity_mapping"
            if path_result.startswith("expected one entity")
            else "unsupported_path_semantics"
        )
        return _unsupported(base, reason, path_result)
    node_by_id, entity_id, answer_id, endpoints, adjacency = path_result
    if len(edges) > 3:
        return _unsupported(base, "unsupported_path_semantics", "selected fragment has at most three edges")

    missing_classes = sorted(
        {
            str(node.get("class") or node.get("id") or "")
            for node in nodes
        }
        - set(ontology.classes)
    )
    if missing_classes:
        return _unsupported(base, "missing_ontology_term", ",".join(missing_classes))

    candidates: list[tuple[int, int, list[str], list[str], list[bool]]] = []
    for start in sorted(endpoints):
        order, ordered_edges = _walk_path(start, adjacency)
        orientation = _orient_relations(order, ordered_edges, ontology)
        if orientation is None:
            continue
        relations, reverse_flags = orientation
        anchor_tiebreak = 0 if start == entity_id else 1
        candidates.append(
            (sum(reverse_flags), anchor_tiebreak, order, relations, reverse_flags)
        )
    if not candidates:
        relations = sorted(str(edge.get("relation") or "") for edge in edges)
        return _unsupported(
            base,
            "missing_relation_mapping",
            "no realizable direct/declared-reverse orientation: " + ",".join(relations),
        )
    _, _, order, relations, reverse_flags = min(candidates)
    position_by_id = {node_id: index for index, node_id in enumerate(order, 1)}

    source_node = node_by_id[order[0]]
    target_node = node_by_id[order[-1]]
    source_pattern = _node_pattern(source_node, answer_id, entity_id)
    target_pattern = _node_pattern(target_node, answer_id, entity_id)
    regex = _relation_sequence(relations)
    conditions: list[Condition] = [
        NodeNotEquals(NodeRef(left), NodeRef(right))
        for left in range(1, len(order) + 1)
        for right in range(left + 1, len(order) + 1)
    ]
    if comparison is not None:
        property_node_id, value, property_name = comparison
        conditions.append(
            _comparison_condition(
                function,
                NodeRef(position_by_id[property_node_id]),
                property_name,
                value,
            )
        )
    condition = conditions[0] if len(conditions) == 1 else And(*conditions)
    query = PathPatternQuery(
        path_var=Var("path"),
        source=source_pattern,
        expr=regex,
        target=target_pattern,
        selector=Selector(SelectorKind.ALL),
        restrictor=RecursiveMode.SIMPLE,
        condition=condition,
    )

    try:
        plan = lower_to_logical_plan(query)
        indexed = index_logical_plan(plan)
        cypher = compile_cypher(
            query,
            profile=cypher_profile,  # type: ignore[arg-type]
            artifact_id=f"grailqa-{question_id}-neo4j",
        )
        sparql = compile_sparql(
            query,
            profile=sparql_profile,  # type: ignore[arg-type]
            backend_mapping=rdf_mapping or _rdf_mapping_for_terms(ontology),
            artifact_id=f"grailqa-{question_id}-fuseki",
        )
    except (NotImplementedError, TypeError, ValueError) as error:
        return _unsupported(base, "pipeline_failure", str(error))

    answer_position = position_by_id[answer_id]
    original_slots = _query_slots(order, node_by_id, relations, comparison)
    normalizer = normalized_ontology or normalize_ontology(ontology)
    normalized_slots = [
        {
            **slot,
            "normalized_term": normalizer.term_to_representative.get(
                str(slot["term"]), str(slot["term"])
            ),
        }
        for slot in original_slots
    ]
    result = dict(base)
    result.update(
        {
            "status": "supported",
            "function": function,
            "path_length": len(edges),
            "node_order": order,
            "source_entity_id": str(node_by_id[entity_id].get("id") or ""),
            "source_entity_class": str(node_by_id[entity_id].get("class") or ""),
            "answer_class": str(node_by_id[answer_id].get("class") or ""),
            "answer_path_position": answer_position,
            "answer_column": "source" if answer_position == 1 else "target",
            "traversal_relations": relations,
            "reverse_property_used": any(reverse_flags),
            "reverse_property_count": sum(reverse_flags),
            "ontology_slots": normalized_slots,
            "reference_interpretation": path_pattern_query_to_dict(query),
            "formatted_logical_plan": format_plan(plan),
            "operators": [item.operator_name for item in indexed.operators],
            "logical_plan_size": len(indexed.operators) + len(indexed.dependencies),
            "logical_operator_count": len(indexed.operators),
            "logical_dependency_count": len(indexed.dependencies),
            "logical_plan_id": indexed.logical_plan_id,
            "native_compilation": {
                "neo4j": {
                    "artifact_id": cypher.artifact_id,
                    "language": cypher.language,
                    "query_sha256": hashlib.sha256(cypher.text.encode()).hexdigest(),
                },
                "fuseki": {
                    "artifact_id": sparql.artifact_id,
                    "language": sparql.language,
                    "query_sha256": hashlib.sha256(sparql.text.encode()).hexdigest(),
                },
            },
            "mapping_contract": (
                "canonical Freebase IDs; type.object.id entity property; "
                "type-as-label; public direct/reverse predicates"
            ),
        }
    )
    return GrailQAV2Conversion(result, query)


def _extract_comparison(
    function: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    ontology: OntologyResources,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, str, object] | str:
    literal_nodes = [item for item in nodes if item.get("node_type") == "literal"]
    if len(literal_nodes) != 1:
        return "selected comparison fragment requires exactly one literal"
    literal = literal_nodes[0]
    literal_id = str(literal.get("nid"))
    incident = [
        edge
        for edge in edges
        if str(edge.get("start")) == literal_id or str(edge.get("end")) == literal_id
    ]
    if len(incident) != 1:
        return "comparison literal must be a single property leaf"
    edge = incident[0]
    property_name = str(edge.get("relation") or "")
    if property_name not in ontology.properties:
        return "comparison edge is not a declared scalar property"
    try:
        value = parse_numeric_literal(
            str(literal.get("id") or ""), str(literal.get("class") or "")
        )
    except ValueError as error:
        return str(error)
    property_node_id = (
        str(edge.get("end"))
        if str(edge.get("start")) == literal_id
        else str(edge.get("start"))
    )
    remaining_nodes = [item for item in nodes if str(item.get("nid")) != literal_id]
    remaining_edges = [item for item in edges if item is not edge]
    if not remaining_edges:
        return "focus-only comparison is outside the selected path fragment"
    return remaining_nodes, remaining_edges, property_node_id, property_name, value


def parse_numeric_literal(value: str, datatype: str) -> int | float:
    match = _NUMERIC_LITERAL_RE.fullmatch(value)
    if match is None or datatype not in {"type.int", "type.float"}:
        raise ValueError("comparison literal is not a supported numeric XSD value")
    lexical, xsd_type = match.groups()
    try:
        parsed: int | float
        if datatype == "type.int" and xsd_type in {"int", "integer"}:
            parsed = int(lexical)
        elif datatype == "type.float" and xsd_type in {"float", "double", "decimal"}:
            parsed = float(lexical)
        else:
            raise ValueError
    except ValueError as error:
        raise ValueError("numeric literal datatype and lexical form disagree") from error
    if isinstance(parsed, bool) or not math.isfinite(parsed):
        raise ValueError("numeric literal must be finite and non-bool")
    return parsed


def _linear_path(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],
    str,
    str,
    tuple[str, str],
    dict[str, list[tuple[str, dict[str, Any]]]],
] | str:
    node_by_id = {str(item.get("nid")): item for item in nodes}
    if len(node_by_id) != len(nodes) or not node_by_id:
        return "node IDs must be present and unique"
    if len(edges) != len(nodes) - 1 or not edges:
        return "graph query is not a nonempty tree path"
    adjacency: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for edge in edges:
        start, end = str(edge.get("start")), str(edge.get("end"))
        if start not in node_by_id or end not in node_by_id or start == end:
            return "edge endpoints are malformed"
        adjacency[start].append((end, edge))
        adjacency[end].append((start, edge))
    if any(len(adjacency[node_id]) > 2 for node_id in node_by_id):
        return "branching graph query is outside the path fragment"
    endpoints = tuple(sorted(node_id for node_id in node_by_id if len(adjacency[node_id]) == 1))
    if len(endpoints) != 2:
        return "graph query is disconnected or cyclic"
    order, _ = _walk_path(endpoints[0], adjacency)
    if len(order) != len(nodes):
        return "graph query is disconnected"
    entities = [
        node_id for node_id, node in node_by_id.items() if node.get("node_type") == "entity"
    ]
    answers = [
        node_id for node_id, node in node_by_id.items() if node.get("question_node") == 1
    ]
    if len(entities) != 1:
        return "expected one entity anchor"
    if len(answers) != 1 or node_by_id[answers[0]].get("node_type") != "class":
        return "expected one class-valued question node"
    if entities[0] not in endpoints or answers[0] not in endpoints:
        return "entity anchor and question node must be path endpoints"
    if any(node.get("node_type") not in {"entity", "class"} for node in nodes):
        return "selected path fragment contains an unsupported node kind"
    return node_by_id, entities[0], answers[0], endpoints, adjacency


def _walk_path(
    start: str,
    adjacency: Mapping[str, list[tuple[str, dict[str, Any]]]],
) -> tuple[list[str], list[dict[str, Any]]]:
    order = [start]
    ordered_edges: list[dict[str, Any]] = []
    previous: str | None = None
    current = start
    while True:
        choices = [item for item in adjacency[current] if item[0] != previous]
        if not choices:
            break
        next_node, edge = min(choices, key=lambda item: item[0])
        ordered_edges.append(edge)
        order.append(next_node)
        previous, current = current, next_node
    return order, ordered_edges


def _orient_relations(
    order: list[str],
    edges: list[dict[str, Any]],
    ontology: OntologyResources,
) -> tuple[list[str], list[bool]] | None:
    relations: list[str] = []
    reverse_flags: list[bool] = []
    for index, edge in enumerate(edges):
        relation = str(edge.get("relation") or "")
        if relation not in ontology.relations:
            return None
        start, end = order[index], order[index + 1]
        if str(edge.get("start")) == start and str(edge.get("end")) == end:
            traversal = relation
            reverse = False
        else:
            traversal = ontology.reverse_relations.get(relation, "")
            reverse = True
        if traversal not in ontology.relations:
            return None
        relations.append(traversal)
        reverse_flags.append(reverse)
    return relations, reverse_flags


def _node_pattern(
    node: Mapping[str, Any], answer_id: str, entity_id: str
) -> NodePattern:
    node_id = str(node.get("nid"))
    if node_id == answer_id:
        var = Var("answer")
    elif node_id == entity_id:
        var = Var("anchor")
    else:
        var = Var(f"node_{node_id}")
    properties = (
        {"type.object.id": str(node.get("id"))} if node_id == entity_id else {}
    )
    return NodePattern(
        var=var,
        label=str(node.get("class") or node.get("id") or ""),
        properties=properties,
    )


def _relation_sequence(relations: Sequence[str]):
    expressions = [
        Rel(EdgePattern(var=Var(f"edge_{index}"), label=relation, direction=Direction.OUT))
        for index, relation in enumerate(relations, 1)
    ]
    result = expressions[0]
    for expression in expressions[1:]:
        result = Seq(result, expression)
    return result


def _comparison_condition(
    function: str, ref: NodeRef, property_name: str, value: object
) -> Condition:
    classes = {
        "<": PropertyLessThan,
        "<=": PropertyLessThanOrEqual,
        ">": PropertyGreaterThan,
        ">=": PropertyGreaterThanOrEqual,
    }
    return classes[function](ref, property_name, value)


def _query_slots(
    order: Sequence[str],
    nodes: Mapping[str, Mapping[str, Any]],
    relations: Sequence[str],
    comparison: tuple[str, object, str] | None,
) -> list[dict[str, str]]:
    slots: list[dict[str, str]] = []
    for index, node_id in enumerate(order, 1):
        slots.append(
            {
                "slot_id": f"node-{index}-class",
                "kind": "class",
                "term": str(nodes[node_id].get("class") or nodes[node_id].get("id") or ""),
            }
        )
    for index, relation in enumerate(relations, 1):
        slots.append(
            {"slot_id": f"edge-{index}-relation", "kind": "relation", "term": relation}
        )
    if comparison is not None:
        slots.append(
            {
                "slot_id": "comparison-property",
                "kind": "property",
                "term": comparison[2],
            }
        )
    return slots


def reference_ambiguity(
    record: Mapping[str, Any],
    normalized: NormalizedOntology,
    *,
    epsilons: Sequence[float] = REFERENCE_EPSILONS,
    alternatives_per_slot: int = ALTERNATIVES_PER_SLOT,
) -> dict[str, Any]:
    """Count bounded deterministic ontology alternatives using frozen c_sem."""

    raw_slots = record.get("ontology_slots")
    if not isinstance(raw_slots, list) or not raw_slots:
        raise ValueError("Supported record has no ontology slots.")
    graph = normalized.graph
    children: dict[str, list[str]] = defaultdict(list)
    for child, parents in graph.parents.items():
        for parent in parents:
            children[parent].append(child)
    exact = tuple(str(item["normalized_term"]) for item in raw_slots)
    alternatives = {exact}
    for index, term in enumerate(exact):
        neighbors = {
            *graph.parents.get(term, ()),
            *children.get(term, ()),
        }
        # OntologyGraph validation guarantees hierarchy edges stay within one kind.
        same_kind = sorted(neighbors)[:alternatives_per_slot]
        for alternative in same_kind:
            values = list(exact)
            values[index] = alternative
            alternatives.add(tuple(values))

    config = SemanticDeviationConfig(max_relaxation_hops=3)
    scored: list[tuple[tuple[str, ...], float]] = []
    for values in sorted(alternatives):
        changed = [
            index for index, value in enumerate(values) if value != exact[index]
        ]
        if not changed:
            scored.append((values, 0.0))
            continue
        if len(changed) != 1:
            raise AssertionError("M13-C reference alternatives change at most one slot.")
        index = changed[0]
        query_term = exact[index]
        aligned_term = values[index]
        if aligned_term in graph.parents.get(query_term, ()):
            multiplier = config.generalization_penalty
        elif query_term in graph.parents.get(aligned_term, ()):
            multiplier = config.specialization_penalty
        else:
            raise AssertionError("Reference alternative is not a direct hierarchy neighbor.")
        value = multiplier * (1.0 / config.max_relaxation_hops) / len(exact)
        scored.append((values, value))
    counts = {
        _epsilon_key(epsilon): sum(1 for _, value in scored if value <= epsilon + 1e-12)
        for epsilon in epsilons
    }
    return {
        "schema_version": "m13c-grailqa-reference-ambiguity-v1",
        "question_id": str(record["question_id"]),
        "candidate_space": "exact_plus_single_slot_direct_hierarchy_neighbors",
        "alternatives_per_slot_limit": alternatives_per_slot,
        "semantic_deviation_definition": "frozen_m12_directional_ontology_hop",
        "normalized_ontology_hash": str(
            normalized.artifact["normalized_ontology_hash"]
        ),
        "counts_by_epsilon": counts,
        "recommended_epsilon_not_frozen": RECOMMENDED_EPSILON,
        "A_recommended": counts[_epsilon_key(RECOMMENDED_EPSILON)],
        "finite_deviations": sorted({round(value, 12) for _, value in scored}),
        "alternative_count": len(scored),
    }


def normalize_answers(answers: object) -> list[dict[str, Any]]:
    """Normalize GrailQA answers without conflating IDs and display labels."""

    if not isinstance(answers, list):
        raise ValueError("GrailQA answers must be a list.")
    normalized: dict[str, dict[str, Any]] = {}
    for answer in answers:
        if not isinstance(answer, Mapping):
            raise ValueError("Every GrailQA answer must be an object.")
        answer_type = str(answer.get("answer_type", ""))
        argument = answer.get("answer_argument")
        if argument is None:
            raise ValueError("Every GrailQA answer requires answer_argument.")
        if answer_type == "Entity":
            record = {
                "kind": "entity",
                "id": str(argument),
                "label": (
                    str(answer["entity_name"])
                    if answer.get("entity_name") is not None
                    else None
                ),
                "equivalence_key": f"entity:{argument}",
            }
        elif answer_type == "Value":
            record = {
                "kind": "scalar",
                "lexical_value": str(argument),
                "equivalence_key": f"scalar:{argument}",
            }
        else:
            raise ValueError(f"Unsupported GrailQA answer_type {answer_type!r}.")
        key = record["equivalence_key"]
        previous = normalized.get(key)
        if previous is not None and record["kind"] == "entity":
            labels = sorted(
                str(label)
                for label in (previous.get("label"), record.get("label"))
                if label is not None
            )
            record["label"] = labels[0] if labels else None
        normalized[key] = record
    return [normalized[key] for key in sorted(normalized)]


def build_backend_mapping(
    ontology: OntologyResources,
    terms: Iterable[str] | None = None,
) -> dict[str, Any]:
    selected = set(terms or ontology.classes | ontology.relations | ontology.properties)
    selected.add("type.object.id")

    def kind(term: str) -> str:
        if term in ontology.classes:
            return "class"
        if term in ontology.relations:
            return "relation"
        if term in ontology.properties:
            return "property"
        raise ValueError(f"Cannot map unknown Freebase term {term!r}.")

    records = {
        term: {"kind": kind(term), "representation": f"fb:{term}"}
        for term in sorted(selected)
    }
    native = {
        term: {
            "kind": kind(term),
            "representation": (
                f"label:{term}" if kind(term) == "class"
                else f"relationship:{term}" if kind(term) == "relation"
                else term
            ),
        }
        for term in sorted(selected)
    }
    return {
        "schema_version": "m13c-grailqa-backend-mapping-v1",
        "mapping_id": "grailqa-freebase-canonical-v1",
        "version": "grailqa-v1.0-public-processed-ontology",
        "provenance": {
            "canonical_terms": "GrailQA official fb_roles/fb_types",
            "rdf_namespace": FREEBASE_NAMESPACE,
            "entity_identity_property": "type.object.id",
            "inference_gold_used": False,
        },
        "backends": {
            "reference_evaluator": {
                "class_property": "labels",
                "relation_property": "edge_labels",
            },
            "neo4j": {
                "class_property": "escaped canonical Freebase label",
                "relation_property": "escaped canonical Freebase relationship type",
                "property_keys": "escaped canonical Freebase property ID",
            },
            "fuseki": {
                "namespace": FREEBASE_NAMESPACE,
                "prefixes": {"fb": FREEBASE_NAMESPACE},
                "compiler_tokens": {
                    "node_labels": {},
                    "edge_labels": {},
                    "properties": {},
                },
            },
        },
        "term_mappings": {
            "reference_evaluator": native,
            "neo4j": native,
            "fuseki": records,
        },
    }


def _rdf_mapping_for_terms(ontology: OntologyResources) -> RdfBackendMapping:
    return RdfBackendMapping.from_artifact(build_backend_mapping(ontology))


def run_audit_v2(
    dataset_root: str | Path,
    ontology_root: str | Path,
    output_root: str | Path,
    *,
    ontology_revision: str | None = None,
) -> dict[str, Any]:
    dataset_path = Path(dataset_root)
    output_path = Path(output_root)
    ontology = load_ontology_resources(ontology_root)
    normalized = normalize_ontology(ontology)
    mapping_artifact = build_backend_mapping(ontology)
    rdf_mapping = RdfBackendMapping.from_artifact(mapping_artifact)
    registry.load_descriptors(Path(__file__).resolve().parents[3] / "descriptors" / "backends")
    cypher_profile = registry.get_capability_profile("neo4j")
    sparql_profile = registry.get_capability_profile("fuseki")

    supported: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    ambiguities: list[dict[str, Any]] = []
    by_split: dict[str, Counter[str]] = defaultdict(Counter)
    by_function: dict[str, Counter[str]] = defaultdict(Counter)
    reasons: Counter[str] = Counter()
    operators: Counter[str] = Counter()
    path_lengths: Counter[int] = Counter()
    q_values: list[int] = []
    dataset_sources: dict[str, Any] = {}

    for split, filename in DATASET_FILES.items():
        source_path = dataset_path / filename
        questions = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(questions, list):
            raise ValueError(f"{source_path} must contain a JSON array.")
        dataset_sources[split] = {
            "file": filename,
            "sha256": _sha256(source_path),
            "question_count": len(questions),
            "gold_annotations": split != "test_public",
        }
        for question in questions:
            result = convert_question_v2(
                question,
                split,
                ontology,
                normalized_ontology=normalized,
                cypher_profile=cypher_profile,
                sparql_profile=sparql_profile,
                rdf_mapping=rdf_mapping,
            )
            function = str(question.get("function", "not_available"))
            for bucket in (by_split[split], by_function[function]):
                bucket["total"] += 1
            if result.supported:
                ambiguity = reference_ambiguity(result.record, normalized)
                result.record["ambiguity"] = {
                    "A_recommended": ambiguity["A_recommended"],
                    "counts_by_epsilon": ambiguity["counts_by_epsilon"],
                }
                supported.append(result.record)
                ambiguities.append(ambiguity)
                for bucket in (by_split[split], by_function[function]):
                    bucket["supported"] += 1
                operators.update(result.record["operators"])
                path_lengths[int(result.record["path_length"])] += 1
                q_values.append(int(result.record["logical_plan_size"]))
            else:
                unsupported.append(result.record)
                reasons[str(result.record["reason"])] += 1
                for bucket in (by_split[split], by_function[function]):
                    bucket["unsupported"] += 1

    total = sum(item["question_count"] for item in dataset_sources.values())
    gold_available = sum(
        item["question_count"]
        for item in dataset_sources.values()
        if item["gold_annotations"]
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M13-C GrailQA Paper Vertical Slice",
        "benchmark_integration_complete": False,
        "totals": {
            "public_questions": total,
            "gold_available_questions": gold_available,
            "supported_questions": len(supported),
            "unsupported_questions": len(unsupported),
            "gold_available_unsupported_questions": gold_available - len(supported),
            "supported_ratio_public": len(supported) / total,
            "supported_ratio_gold_available": len(supported) / gold_available,
        },
        "m13a_baseline": {
            "supported_questions": 23156,
            "supported_ratio_gold_available": 23156 / 51100,
            "supported_ratio_public": 23156 / 64331,
            "Q_histogram": {"13": 23156},
        },
        "unsupported_reasons": dict(sorted(reasons.items())),
        "by_split": _bucket_summary(by_split),
        "by_query_type": _bucket_summary(by_function),
        "operator_distribution": dict(sorted(operators.items())),
        "path_length_distribution": {
            str(key): value for key, value in sorted(path_lengths.items())
        },
        "complexity": _distribution(q_values),
        "mapping": {
            "mapping_id": mapping_artifact["mapping_id"],
            "mapping_version": mapping_artifact["version"],
            "canonical_class_terms": len(ontology.classes),
            "canonical_relation_terms": len(ontology.relations),
            "canonical_property_terms": len(ontology.properties),
            "missing_or_unrealizable_relation_questions": reasons.get(
                "missing_relation_mapping", 0
            ),
            "per_question_gold_ids_exposed_to_inference": False,
        },
        "source": {
            "dataset_files": dataset_sources,
            "ontology_revision": ontology_revision,
            "ontology_source_hashes": dict(sorted(ontology.source_hashes.items())),
        },
    }
    ambiguity_summary = summarize_ambiguity(ambiguities)
    complexity = {
        "schema_version": SCHEMA_VERSION,
        "definition": "Q(u)=|Omega_u^gold|+|D_u^gold|",
        "xgap_logical_plans": _distribution(q_values),
        "operator_distribution": dict(sorted(operators.items())),
        "path_length_distribution": {
            str(key): value for key, value in sorted(path_lengths.items())
        },
    }
    mapping_summary = {
        "schema_version": "m13c-grailqa-backend-mapping-summary-v1",
        "mapping_id": mapping_artifact["mapping_id"],
        "version": mapping_artifact["version"],
        "mapping_hash": content_hash(mapping_artifact),
        "term_counts": {
            "classes": len(ontology.classes),
            "relations": len(ontology.relations),
            "properties": len(ontology.properties),
        },
        "backends": ["reference_evaluator", "neo4j", "fuseki"],
        "compiler_mapping_is_single_source_of_truth": True,
        "namespace_hard_coded_in_compiler": False,
    }

    output_path.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_path / "supported_questions.jsonl", supported)
    _write_jsonl(output_path / "unsupported_questions.jsonl", unsupported)
    _write_jsonl(output_path / "ambiguity.jsonl", ambiguities)
    _write_json(output_path / "audit_summary.json", summary)
    _write_json(output_path / "complexity_distribution.json", complexity)
    _write_json(output_path / "ambiguity_summary.json", ambiguity_summary)
    _write_json(output_path / "ontology_normalization.json", normalized.artifact)
    (output_path / "normalized_ontology.yaml").write_text(
        yaml_text(normalized.graph.to_dict()), encoding="utf-8"
    )
    _write_json(output_path / "backend_mapping_summary.json", mapping_summary)
    return summary


def summarize_ambiguity(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "m13c-grailqa-reference-ambiguity-summary-v1",
        "definition": "A(u)=distinct bounded reference interpretations with c_sem<=epsilon_amb",
        "candidate_space": "exact_plus_single_slot_direct_hierarchy_neighbors",
        "alternatives_per_slot_limit": ALTERNATIVES_PER_SLOT,
        "epsilon_recommendation": {
            "value": RECOMMENDED_EPSILON,
            "status": "recommended_for_pilot_not_frozen_for_paper",
        },
        "by_epsilon": {},
    }
    for epsilon in REFERENCE_EPSILONS:
        key = _epsilon_key(epsilon)
        values = [int(item["counts_by_epsilon"][key]) for item in records]
        counts = Counter(values)
        result["by_epsilon"][key] = {
            **_distribution(values),
            "fraction_A_1": counts[1] / len(values) if values else 0.0,
            "fraction_A_2": counts[2] / len(values) if values else 0.0,
            "fraction_A_3": counts[3] / len(values) if values else 0.0,
            "fraction_A_ge_4": (
                sum(count for value, count in counts.items() if value >= 4) / len(values)
                if values
                else 0.0
            ),
        }
    all_deviations = sorted(
        {
            float(value)
            for item in records
            for value in item.get("finite_deviations", ())
        }
    )
    result["finite_deviation_values"] = all_deviations
    recommended = result["by_epsilon"][_epsilon_key(RECOMMENDED_EPSILON)]
    result["degeneracy_note"] = (
        "A(u) is degenerate at the recommended pilot epsilon."
        if recommended["fraction_A_1"] > 0.95
        else "A(u) is non-degenerate enough for pilot stratification."
    )
    return result


def _unsupported(base: Mapping[str, Any], reason: str, detail: str) -> GrailQAV2Conversion:
    return GrailQAV2Conversion(
        {**base, "status": "unsupported", "reason": reason, "detail": detail},
        None,
    )


def _epsilon_key(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _bucket_summary(buckets: Mapping[str, Counter[str]]) -> dict[str, Any]:
    return {
        key: {
            "total": bucket["total"],
            "supported": bucket["supported"],
            "unsupported": bucket["total"] - bucket["supported"],
            "supported_ratio": (
                bucket["supported"] / bucket["total"] if bucket["total"] else 0.0
            ),
        }
        for key, bucket in sorted(buckets.items())
    }


def _distribution(values: Sequence[int]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "distinct": 0,
            "mean": None,
            "median": None,
            "p90": None,
            "max": None,
            "histogram": {},
        }
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "distinct": len(set(ordered)),
        "mean": statistics.fmean(ordered),
        "median": statistics.median(ordered),
        "p90": ordered[math.ceil(0.9 * len(ordered)) - 1],
        "max": max(ordered),
        "histogram": {
            str(key): value for key, value in sorted(Counter(ordered).items())
        },
    }


def yaml_text(value: Mapping[str, Any]) -> str:
    """Emit the mapping/list/scalar YAML subset accepted by XGAP's loader."""

    lines: list[str] = []

    def emit(mapping: Mapping[str, Any], indent: int) -> None:
        prefix = " " * indent
        for key, item in mapping.items():
            if isinstance(item, Mapping):
                lines.append(f"{prefix}{key}:")
                emit(item, indent + 2)
            elif isinstance(item, (list, tuple)):
                encoded = json.dumps(list(item), ensure_ascii=True, separators=(",", ":"))
                lines.append(f"{prefix}{key}: {encoded}")
            else:
                encoded = json.dumps(item, ensure_ascii=True, separators=(",", ":"))
                lines.append(f"{prefix}{key}: {encoded}")

    emit(value, 0)
    return "\n".join(lines) + "\n"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for value in values:
            handle.write(
                json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False)
                + "\n"
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the M13-C GrailQA v2 audit.")
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--ontology-root", required=True)
    parser.add_argument("--output", default="datasets/grailqa_audit_v2")
    parser.add_argument("--ontology-revision")
    args = parser.parse_args(argv)
    summary = run_audit_v2(
        args.dataset_root,
        args.ontology_root,
        args.output,
        ontology_revision=args.ontology_revision,
    )
    print(json.dumps(summary["totals"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
