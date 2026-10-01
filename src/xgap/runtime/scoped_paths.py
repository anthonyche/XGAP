"""Compile finite regex scopes to native fragments and explicit path operations."""

from dataclasses import replace

from xgap.compilers.bounded_paths import compile_bounded_paths
from xgap.compilers.errors import UnsupportedCompilationError
from xgap.pattern.ast import (Alt, Bounded, EdgePattern, NodePattern, OptionalExpr,
    PathMode, Plus, Rel, Selector, SelectorKind, Seq, Star)
from xgap.pattern.lowering import lower_regex
from xgap.pattern.semantic_validation import type_check_semantic_path_pattern
from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNode, RuntimeNodeKind as R


def compile_scoped_path_plan(query, *, backend_id, plan_id="scoped-path-plan", **options):
    type_check_semantic_path_pattern(query)
    # This is a finite native superset, never an external retry or a local graph load.
    all_selector = Selector(SelectorKind.ALL)
    filtered = compile_bounded_paths(replace(query, restrictor=PathMode.WALK,
        selector=all_selector), backend_id=backend_id, **options)
    lower_regex(query.expr, query.restrictor, query.max_depth)  # Preserve logical admission.
    maximum = filtered.parameters["path_selection"]["max_edges"]
    nodes, outputs = [], {}

    def add(kind, inputs=(), parameters=None):
        identifier = f"scope{len(nodes)}"
        nodes.append(RuntimeNode(identifier, kind, tuple(inputs), parameters or {}))
        return identifier

    def native(artifact):
        remote = add(R.REMOTE_QUERY, parameters={"backend_id": backend_id, "artifact": artifact.to_dict()})
        return add(R.COORDINATOR_PATH_SELECT, (remote,), artifact.parameters["path_selection"])

    def union(*children):
        unique = tuple(dict.fromkeys(children))
        return unique[0] if len(unique) == 1 else add(R.MERGE, unique)

    def join(left, right):
        return add(R.COORDINATOR_PATH_COMPOSE, tuple(dict.fromkeys((left, right))),
                   {"operation": "join", "max_edges": maximum})

    def recursive(child, depth):
        return add(R.COORDINATOR_PATH_COMPOSE, (child,), {
            "operation": "recursive", "mode": query.restrictor.value,
            "max_depth": depth, "max_edges": maximum})

    def zero():
        return visit(Bounded(Rel(EdgePattern()), 0, 0))

    def visit(expr):
        key = repr(expr)
        if key in outputs:
            return outputs[key]
        inner = replace(query, expr=expr, source=NodePattern(), target=NodePattern(),
                        condition=None, selector=all_selector)
        try:
            artifact = compile_bounded_paths(inner, backend_id=backend_id, **options)
        except UnsupportedCompilationError:
            if isinstance(expr, Seq):
                output = join(visit(expr.left), visit(expr.right))
            elif isinstance(expr, Alt):
                output = union(visit(expr.left), visit(expr.right))
            elif isinstance(expr, OptionalExpr):
                output = union(zero(), visit(expr.child))
            elif isinstance(expr, (Plus, Star)):
                output = recursive(visit(expr.child), query.max_depth)
                if isinstance(expr, Star):
                    output = union(zero(), output)
            elif isinstance(expr, Bounded):
                if expr.max_repeats is None and expr.min_repeats <= 1:
                    output = visit(Star(expr.child) if expr.min_repeats == 0 else Plus(expr.child))
                elif expr.max_repeats == 0:
                    raise  # A native node-domain failure cannot be bypassed.
                else:
                    depth = expr.max_repeats if expr.max_repeats is not None else query.max_depth
                    child = visit(expr.child)
                    power, admitted = child, []
                    for count in range(1, depth + 1):
                        if count > 1:
                            power = join(power, child)
                        if count >= max(1, expr.min_repeats):
                            admitted.append(power)
                    output = recursive(union(*admitted), 1)
                    if expr.min_repeats == 0:
                        output = union(zero(), output)
            else:
                raise  # Unsupported native leaves/profile constraints remain unavailable.
        else:
            output = native(artifact)
        outputs[key] = output
        return output

    output = visit(query.expr)
    if query.source != NodePattern() or query.target != NodePattern() or query.condition is not None:
        eligible = native(filtered)
        output = add(R.COORDINATOR_SEMI_JOIN, (output, eligible), {"left_on": "path", "right_on": "path"})
    output = add(R.COORDINATOR_PATH_SELECT, (output,), {"input_model": "paths", "max_edges": maximum,
        "selector": query.selector.kind.name, "k": query.selector.k})
    calls = sum(node.kind is R.REMOTE_QUERY for node in nodes)
    return FederatedExecutionPlan(plan_id, tuple(nodes), (output,), max_remote_calls=calls, metadata={
        "compiler": "scoped_finite_paths_v1", "candidate_placement": backend_id,
        "selector_placement": "coordinator", "scope_placement": "native_and_coordinator",
        "native_fragment_count": calls, "branch_count": filtered.parameters["branch_count"],
        "max_edges": maximum})
