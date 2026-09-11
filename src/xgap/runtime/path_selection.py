"""Normalize native path bindings and apply the existing selector algebra."""

from collections.abc import Mapping
import json
import re

from xgap.algebra.evaluator import group_paths, order_paths, project_paths
from xgap.algebra.ops import NodesOp, GroupByOp, OrderByOp, ProjectionOp
from xgap.algebra.types import Path, PathSet
from xgap.backends.rdf_terms import RdfTerm
from xgap.compilers.rdf_encoding import RdfRowEncoding
from xgap.pattern.ast import Selector, SelectorKind
from xgap.pattern.lowering import apply_selector


def _decode_native_paths(rows, parameters):
    mode = parameters["language"]
    if mode not in ("cypher", "sparql"):
        raise ValueError("Path selection requires cypher or sparql bindings")
    max_edges = parameters["max_edges"]
    namespace = parameters["resource_namespace"]
    ids = RdfRowEncoding("path-identities", "urn:xgap:class", parameters["identity_property"], namespace)

    def identifier(value):
        if mode == "sparql":
            term = RdfTerm.from_binding(value)
            if term.kind != "uri" or not term.value.startswith(namespace):
                raise ValueError("Path identity is outside the declared resource namespace")
            result = term.value[len(namespace):]
        else:
            result = value[ids.identity_property]
        ids.resource_iri(result)  # Same explicit canonical ID contract on both engines.
        return result

    paths = PathSet()
    for row in rows:
        length = row["length"]
        if mode == "sparql":
            term = RdfTerm.from_binding(length)
            if term.kind != "literal" or term.datatype != "http://www.w3.org/2001/XMLSchema#integer":
                raise ValueError("Native path length must be an integer")
            length = int(term.value)
        if type(length) is not int or not 0 <= length <= max_edges:
            raise ValueError("Native path length is outside the compiled bound")
        sequence = [identifier(row["n0"])]
        for i in range(1, length + 1):
            sequence.extend((identifier(row[f"e{i}"]), identifier(row[f"n{i}"])))
        paths.add(Path(tuple(sequence)))

    return paths


def normalized_pathset(rows):
    paths = PathSet()
    for row in rows:
        sequence = row["path"]
        if not isinstance(sequence, (list, tuple)) or any(not isinstance(x, str) or not x for x in sequence):
            raise ValueError("Normalized paths require nonempty string identities")
        paths.add(Path(tuple(sequence)))
    return paths


def _decode_resource_triple_paths(rows, parameters):
    """Normalize fixed resource paths, identifying edges by stored URI triples."""
    required = {"language", "max_edges", "resource_namespace", "identity_property",
                "directions", "max_rows", "selector"}
    if not required <= parameters.keys():
        raise ValueError("Resource paths require their complete decoding contract")
    language = parameters["language"]
    count, maximum = parameters["max_edges"], parameters["max_rows"]
    directions = parameters["directions"]
    if language not in ("cypher", "sparql"):
        raise ValueError("Resource paths require cypher or sparql bindings")
    if type(count) is not int or not 1 <= count <= 3:
        raise ValueError("Resource paths require a fixed length in 1..3")
    if (not isinstance(directions, list) or len(directions) != count
            or any(direction not in ("OUT", "IN") for direction in directions)):
        raise ValueError("Resource paths require one explicit direction per edge")
    if type(maximum) is not int or maximum <= 0:
        raise ValueError("Resource paths require a positive row budget")
    if (parameters["selector"] != "ALL" or parameters.get("k") is not None
            or parameters.get("recursive_shortest") or parameters.get("post_shortest_lengths")):
        raise ValueError("Resource paths support only the fixed ALL selector")
    namespace = parameters["resource_namespace"]
    ids = RdfRowEncoding("resource-path-identities", "urn:xgap:class",
                         parameters["identity_property"], namespace)
    columns = {"length", *(f"n{i}" for i in range(count + 1)),
               *(f"e{i}" for i in range(1, count + 1))}

    def iri(value):
        term = (RdfTerm.from_binding(value) if language == "sparql"
                else RdfTerm("uri", value))
        if term.kind != "uri":
            raise ValueError("Resource path nodes and predicates must be IRIs")
        return term.value

    paths = PathSet()
    for row_number, row in enumerate(rows, 1):
        if row_number > maximum:
            raise ValueError("Complete resource path result exceeds the row budget")
        if not isinstance(row, Mapping) or set(row) != columns:
            raise ValueError("Resource path result columns do not match the fixed path")
        length = row["length"]
        if language == "sparql":
            term = RdfTerm.from_binding(length)
            if (term.kind != "literal" or term.datatype != "http://www.w3.org/2001/XMLSchema#integer"
                    or not re.fullmatch(r"[+-]?[0-9]+", term.value)):
                raise ValueError("Resource path length must be a typed integer")
            length = int(term.value)
        if type(length) is not int or length != count:
            raise ValueError("Resource path length disagrees with the compiled fixed path")
        nodes = [iri(row[f"n{i}"]) for i in range(count + 1)]
        local_ids = []
        for node in nodes:
            if not node.startswith(namespace):
                raise ValueError("Resource path node is outside the declared namespace")
            local = node[len(namespace):]
            ids.resource_iri(local)
            local_ids.append(local)
        sequence = [local_ids[0]]
        for i, direction in enumerate(directions, 1):
            predicate = iri(row[f"e{i}"])
            source, target = nodes[i - 1], nodes[i]
            if direction == "IN":
                source, target = target, source
            edge = "rdf-triple-v1:" + json.dumps([source, predicate, target],
                ensure_ascii=False, separators=(",", ":"))
            sequence.extend((edge, local_ids[i]))
        paths.add(Path(tuple(sequence)))
    return paths


def select_native_paths(rows, parameters):
    if parameters.get("input_model") == "rdf-resource-triples-v1":
        paths = _decode_resource_triple_paths(rows, parameters)
    elif parameters.get("input_model") == "paths":
        paths = normalized_pathset(rows)
    else:
        paths = _decode_native_paths(rows, parameters)
    if any(len(p) > parameters["max_edges"] for p in paths):
        raise ValueError("Path exceeds its compiled finite edge bound")

    if parameters.get("recursive_shortest"):
        best = {}
        include_zero = parameters.get("shortest_includes_zero", False)
        for path in paths:
            if len(path) == 0 and not include_zero:
                continue  # Star is Union(Nodes, Recursive); zero paths do not suppress cycles.
            pair = (path.first(), path.last())
            best[pair] = min(best.get(pair, len(path)), len(path))
        paths = PathSet(p for p in paths if (len(p) == 0 and not include_zero)
                        or len(p) == best[(p.first(), p.last())])
    for length in parameters.get("post_shortest_lengths", ()):
        paths = PathSet(p for p in paths if len(p) == length)

    base = NodesOp()
    plan = apply_selector(base, Selector(SelectorKind[parameters["selector"]], parameters.get("k")))

    def evaluate_stage(op):
        if op is base:
            return paths
        child = evaluate_stage(op.child)
        if isinstance(op, GroupByOp):
            return group_paths(child, op.group_key())
        if isinstance(op, OrderByOp):
            return order_paths(child, op.order_key())
        if isinstance(op, ProjectionOp):
            return project_paths(child, op.num_partitions, op.num_groups, op.num_paths)
        raise ValueError("Unexpected selector algebra stage")

    return tuple({"path": list(path.sequence)} for path in evaluate_stage(plan))
