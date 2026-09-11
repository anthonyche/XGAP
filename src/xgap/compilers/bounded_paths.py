"""Bounded native path expansion with explicit coordinator selector placement.

Rel/Seq/Alt/Optional are compiled compositionally. Root Plus/Star/Bounded
repeat finite alternatives. Nested Bounded flattens only under WALK; other
scoped recursion remains explicit. No fixture IDs or gold enter compilation.
"""

from dataclasses import replace
from itertools import combinations

from xgap.algebra.conditions import And, EdgeRef, LengthEquals, NodeRef
from xgap.backends.rdf_terms import RDF_TERMS_V1, validate_iri
from xgap.compilers.directed import (
    MAX_EDGES, DirectedShape, _cypher, _fail, _required, _shape, _sparql,
    compile_directed_rows,
)
from xgap.compilers.features import BoundCondition, default_profile
from xgap.infrastructure.runtime import QueryArtifact
from xgap.pattern.ast import Alt, Bounded, Direction, EdgePattern, OptionalExpr, PathMode, Plus, Rel, Selector, SelectorKind, Seq, Star
from xgap.pattern.semantic_validation import type_check_semantic_path_pattern


def _alternatives(expr, limit, mode=PathMode.WALK, max_depth=None):
    if isinstance(expr, Rel):
        result = ([(replace(expr.edge, direction=direction),) for direction in (Direction.OUT, Direction.IN)]
                  if expr.edge.direction is Direction.UNDIRECTED else [(expr.edge,)])
    elif isinstance(expr, Alt):
        result = _alternatives(expr.left, limit, mode, max_depth) + _alternatives(expr.right, limit, mode, max_depth)
    elif isinstance(expr, Seq):
        left, right = _alternatives(expr.left, limit, mode, max_depth), _alternatives(expr.right, limit, mode, max_depth)
        if len(left) * len(right) > limit:
            raise ValueError("Native branch budget exceeded")
        result = [a + b for a in left for b in right]
    elif isinstance(expr, OptionalExpr):
        result = [()] + _alternatives(expr.child, limit, mode, max_depth)
    elif isinstance(expr, Bounded) and expr.max_repeats == 0:
        result = [()]
    elif isinstance(expr, (Bounded, Plus, Star)) and mode is PathMode.WALK:
        minimum = expr.min_repeats if isinstance(expr, Bounded) else (0 if isinstance(expr, Star) else 1)
        maximum = expr.max_repeats if isinstance(expr, Bounded) and expr.max_repeats is not None else max_depth
        if type(maximum) is not int or maximum < minimum or maximum < 0:
            raise ValueError("Native nested recursion requires a finite upper bound or query max_depth")
        result = _repeat_alternatives(_alternatives(expr.child, limit, mode, max_depth),
                                      minimum, maximum, limit)
    else:
        raise ValueError("Native expansion supports Rel/Seq/Alt/Optional and root bounded repetition; nested scoped recursion is unavailable")
    if len(result) > limit or any(len(branch) > MAX_EDGES for branch in result):
        raise ValueError("Native branch or edge budget exceeded")
    return result


def _repeat_alternatives(base, minimum, maximum, limit):
    result = [()] if minimum == 0 else []
    frontier = [()]
    for depth in range(1, maximum + 1):
        if len(frontier) * len(base) > limit:
            raise ValueError("Native branch budget exceeded")
        frontier = [a + b for a in frontier for b in base]
        if any(len(branch) > MAX_EDGES for branch in frontier):
            raise ValueError("Native edge budget exceeded")
        if depth >= minimum:
            result.extend(frontier)
            if len(result) > limit:
                raise ValueError("Native branch budget exceeded")
    return result


def _branches(query, limit):
    recursive = isinstance(query.expr, (Plus, Star, Bounded))
    if not recursive:
        return _alternatives(query.expr, limit, query.restrictor, query.max_depth), False, False
    minimum = query.expr.min_repeats if isinstance(query.expr, Bounded) else (0 if isinstance(query.expr, Star) else 1)
    depth = (query.expr.max_repeats if isinstance(query.expr, Bounded)
             and query.expr.max_repeats is not None else query.max_depth)
    if type(depth) is not int or depth < minimum or depth < 0:
        raise ValueError("Native recursion requires an explicit finite positive max_depth")
    if depth == 0:
        return [()], True, False
    base = _alternatives(query.expr.child, limit, query.restrictor, query.max_depth)
    finite_range = isinstance(query.expr, Bounded) and (query.expr.max_repeats is not None or minimum >= 2)
    if not finite_range and query.restrictor is PathMode.SHORTEST and len({len(b) for b in base}) != 1:
        raise ValueError("SHORTEST native expansion currently requires equal-length child alternatives")
    return _repeat_alternatives(base, minimum, depth, limit), True, () in base


def _fixed_expr(edges):
    result = Rel(edges[0])
    for edge in edges[1:]:
        result = Seq(result, Rel(edge))
    return result


def _restrictions(count, mode, prefix):
    node = lambda i: f"{prefix}n{i}"
    edge = lambda i: f"{prefix}e{i}"
    if mode is PathMode.TRAIL:
        pairs = [(edge(a), edge(b)) for a, b in combinations(range(1, count + 1), 2)]
    elif mode in (PathMode.SIMPLE, PathMode.ACYCLIC):
        pairs = [(node(a), node(b)) for a, b in combinations(range(count + 1), 2)
                 if mode is PathMode.ACYCLIC or (a, b) != (0, count)]
    else:
        pairs = []
    operator = "!=" if prefix else "<>"
    return [f"{a} {operator} {b}" for a, b in pairs]


def _shortest_condition(condition):
    """Keep length filters above SHORTEST; endpoint filters commute with it."""
    atoms = list(condition.conditions) if isinstance(condition, And) else ([condition] if condition else [])
    native, lengths = [], []
    while atoms:
        atom = atoms.pop(0)
        if isinstance(atom, And):
            atoms[0:0] = atom.conditions
        elif isinstance(atom, LengthEquals):
            lengths.append(atom.value)
        else:
            refs = [getattr(atom, key, None) for key in ("ref", "left", "right")]
            if any(isinstance(ref, EdgeRef) or (isinstance(ref, NodeRef)
                   and ref.position not in ("first", "last")) for ref in refs):
                raise ValueError("SHORTEST requires endpoint or length predicates in this profile")
            native.append(atom)
    return (And(*native) if len(native) > 1 else native[0] if native else None), lengths


def compile_bounded_paths(query, *, backend_id, backend_mapping=None,
                          rdf_edge_encoding=None, rdf_node_classes=(),
                          identity_property="id", resource_namespace,
                          max_branches=128, artifact_id="bounded-paths", profile=None):
    """Compile exact bounded candidates; selectors execute in the runtime plan.

    RDF requires explicit node-domain classes and reified edge identity. Stable
    canonical local IDs align with resource_namespace and property-graph IDs.
    The caller supplies the identity contract, never inferred from query gold.
    """
    profile = profile or default_profile(backend_id)
    try:
        type_check_semantic_path_pattern(query)
        if type(max_branches) is not int or max_branches <= 0:
            raise ValueError("Native branch budget must be positive")
        validate_iri(resource_namespace)
        if not isinstance(identity_property, str) or not identity_property:
            raise ValueError("Native paths require an explicit identity property")
        branches, recursive, positive_zero = _branches(query, max_branches)
        shortest = recursive and query.restrictor is PathMode.SHORTEST
        condition, lengths = (_shortest_condition(query.condition) if shortest
                              else (query.condition, []))
        language = profile.language.lower()
        if language not in ("cypher", "sparql") or profile.backend_id != backend_id:
            raise ValueError("Native path target must match a Cypher or SPARQL profile")
        if language == "sparql":
            from xgap.compilers.rdf_encoding import RdfEdgeEncoding
            if not isinstance(rdf_edge_encoding, RdfEdgeEncoding):
                raise ValueError("PathSet compilation requires explicit RDF edge identity")
            if not rdf_node_classes:
                raise ValueError("RDF Nodes(G) requires explicit node-domain classes")
            for iri in rdf_node_classes:
                validate_iri(iri)
    except ValueError as error:
        raise _fail(profile, "bounded_path", str(error)) from error

    maximum = max(map(len, branches))
    columns = ["length", "n0"]
    for i in range(1, maximum + 1):
        columns.extend((f"e{i}", f"n{i}"))
    native = []
    artifacts = []
    mode = query.restrictor if recursive else PathMode.WALK
    for edges in branches:
        count = len(edges)
        fixed = replace(query, expr=_fixed_expr(edges) if edges else Rel(EdgePattern()),
                        condition=condition, selector=Selector(SelectorKind.ALL),
                        restrictor=PathMode.WALK)
        if edges:
            artifact = compile_directed_rows(fixed, backend_id=backend_id, profile=profile,
                backend_mapping=backend_mapping,
                rdf_edge_encoding=rdf_edge_encoding if language == "sparql" else None)
        else:
            # The zero-length branch has the same node descriptors and conditions,
            # with references rebound to its single node. It has no dummy edge.
            shaped = _shape(fixed, profile)
            shape = DirectedShape((), tuple(BoundCondition(b.condition, 0, 0, 0)
                                            for b in shaped.conditions))
            required = _required(shape, profile, rdf_edge_encoding)
            if language == "cypher":
                text, extra = _cypher(shape, profile)
                text = "MATCH (n0)\n" + text
            else:
                text, extra = _sparql(shape, profile, backend_mapping, None, rdf_edge_encoding)
                classes = " ".join(f"<{iri}>" for iri in rdf_node_classes)
                domain = (f"?n0 <{rdf_edge_encoding.class_predicate_iri}> ?nodeClass . "
                          f"VALUES ?nodeClass {{ {classes} }}")
                text = text.replace("WHERE {", "WHERE {\n  " + domain, 1)
            artifact = QueryArtifact("zero-path", language, text, kind="compiled",
                parameters={"required_features": list(required), **extra})
        artifacts.append(artifact)
        restrictions = _restrictions(count, mode, "?" if language == "sparql" else "")
        if language == "cypher":
            text = "CALL {\n" + artifact.text + "\n}\n"
            if restrictions:
                text += "WITH * WHERE " + " AND ".join(restrictions) + "\n"
            terms = [f"{count} AS length", "n0 AS n0"]
            for i in range(1, maximum + 1):
                terms.extend((f"{'e'+str(i) if i <= count else 'null'} AS e{i}",
                              f"{'n'+str(i) if i <= count else 'null'} AS n{i}"))
            native.append(text + "RETURN DISTINCT " + ", ".join(terms))
        else:
            text = "{ {\n" + artifact.text + "\n}\n"
            if restrictions:
                text += "FILTER(" + " && ".join(restrictions) + ")\n"
            native.append(text + f"BIND({count} AS ?length)\n}}")
    text = ("\nUNION\n".join(native) if language == "cypher" else
            "SELECT DISTINCT " + " ".join("?"+c for c in columns) + " WHERE {\n"
            + "\nUNION\n".join(native) + "\n}")
    selector = {"language": language, "identity_property": identity_property,
        "resource_namespace": resource_namespace, "max_edges": maximum,
        "selector": query.selector.kind.name, "k": query.selector.k,
        "recursive_shortest": shortest, "post_shortest_lengths": lengths}
    if shortest and positive_zero:
        selector["shortest_includes_zero"] = True
    return QueryArtifact(artifact_id, language, text, kind="compiled", parameters={
        "compiler": "bounded_native_paths_v1", "result_model": "path_candidates",
        "target_backend_id": backend_id, "output_columns": columns,
        "branch_count": len(branches), "branch_edge_counts": list(map(len, branches)),
        "path_selection": selector,
        "required_features": sorted({f for a in artifacts for f in a.parameters["required_features"]}),
        "backend_execution_verified": False,
        **({"rdf_result_encoding": RDF_TERMS_V1, "expected_result_columns": columns,
            "rdf_edge_encoding_sha256": rdf_edge_encoding.identity,
            "rdf_node_classes": list(rdf_node_classes)} if language == "sparql" else {}),
    })
