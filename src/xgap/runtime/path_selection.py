"""Normalize native path bindings and apply the existing selector algebra."""

from xgap.algebra.evaluator import group_paths, order_paths, project_paths
from xgap.algebra.ops import NodesOp, GroupByOp, OrderByOp, ProjectionOp
from xgap.algebra.types import Path, PathSet
from xgap.backends.rdf_terms import RdfTerm
from xgap.compilers.rdf_encoding import RdfRowEncoding
from xgap.pattern.ast import Selector, SelectorKind
from xgap.pattern.lowering import apply_selector


def select_native_paths(rows, parameters):
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
