"""Exact, bounded use of one mandatory scalar anchor before edge expansion.

This is a physical semijoin reduction. It reuses existing source reads, keeps
all final constraints, and neither rewrites the semantic input nor probes data.
See docs/decisions/anchor_reduction_v1.md for the admission proof and bounds.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from functools import lru_cache

from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNode, RuntimeNodeKind as R
from xgap.semantic.program import SemanticGraphProgram, SemanticOperatorKind as S


PROFILE = "mandatory-scalar-anchor-distinct-key-join-v1"


def _equalities(condition):
    if condition.get("op") == "and":
        for child in condition["args"]:
            yield from _equalities(child)
    elif (condition.get("op") == "eq" and "field" in condition
          and "value" in condition and condition["value"] is not None
          and "right_field" not in condition
          and condition.get("value_type", "scalar") == "scalar"):
        yield condition


def anchor_binding_slot(program: SemanticGraphProgram) -> int:
    """Conservative pre-compilation slot bound; no data or schema inference."""
    return int(any(next(_equalities(op.parameters.get("condition", {})), None) is not None
                   for op in program.operators if op.kind is S.FILTER))


def reduce_scalar_anchor(program: SemanticGraphProgram,
                         plan: FederatedExecutionPlan) -> FederatedExecutionPlan:
    operators = {op.operator_id: op for op in program.operators}
    schemas = plan.metadata["schemas"]
    outputs = plan.metadata["operator_outputs"]
    consumers = defaultdict(set)
    roots = set(program.roots)
    for op in program.operators:
        for child in op.input_ids:
            consumers[child].add(op.operator_id)

    @lru_cache(None)
    def read_shape(identifier, field):
        op = operators[identifier]
        if op.kind is S.MATCH and "node" in op.parameters:
            prop = op.parameters.get("properties", {}).get(field)
            if prop is not None:
                return op.parameters.get("entity_field", "entity"), prop
        elif op.kind is S.UNION:
            shapes = [read_shape(i, field) for i in op.input_ids]
            if shapes and shapes[0] is not None and all(s == shapes[0] for s in shapes):
                return shapes[0]
        return None

    @lru_cache(None)
    def mandatory_read(identifier, field):
        shape = read_shape(identifier, field)
        if shape is not None:
            return identifier, shape[0]
        op = operators[identifier]
        if op.kind is S.FILTER:
            return mandatory_read(op.input_ids[0], field)
        if op.kind is S.JOIN:
            sides = [i for i in op.input_ids if field in schemas[i]["fields"]]
            # Reject ambiguous provenance and right-column renaming.
            if len(sides) == 1:
                return mandatory_read(sides[0], field)
        return None

    @lru_cache(None)
    def preserved_to(identifier, field, stop):
        if identifier == stop:
            return True
        if identifier in roots or not consumers[identifier]:
            return False
        for parent_id in consumers[identifier]:
            parent = operators[parent_id]
            if field not in schemas[parent_id]["fields"]:
                return False
            if parent.kind is S.PROJECT:
                if parent.parameters["projections"].get(field) != {"kind": "field", "field": field}:
                    return False
            elif parent.kind is S.JOIN:
                left, right = parent.input_ids
                if (right == identifier and field in schemas[left]["fields"]
                        and not parent.parameters["left_on"] == parent.parameters["right_on"] == field):
                    return False
            elif parent.kind not in (S.FILTER, S.UNION):
                return False
            if not preserved_to(parent_id, field, stop):
                return False
        return True

    for enforcing in program.operators:
        if enforcing.kind is not S.FILTER:
            continue
        for condition in _equalities(enforcing.parameters.get("condition", {})):
            driver = mandatory_read(enforcing.input_ids[0], condition["field"])
            if driver is None:
                continue
            driver_id, identity = driver
            if not preserved_to(driver_id, identity, enforcing.operator_id):
                continue
            targets = []
            for op in program.operators:
                if op.kind is not S.MATCH or "edge" not in op.parameters:
                    continue
                identities = {op.parameters.get("source_field", "source"),
                              op.parameters.get("target_field", "target")}
                if identity in identities and preserved_to(op.operator_id, identity, enforcing.operator_id):
                    targets.append(op.operator_id)
            if not targets:
                continue
            prefix = enforcing.operator_id + "/anchor_reduction/"
            anchor_id = prefix + "keys"
            filter_id = prefix + "filter"
            replacements = {outputs[t]: prefix + t for t in targets}
            added_ids = {anchor_id, filter_id, *replacements.values()}
            if added_ids & {n.node_id for n in plan.nodes}:
                # A user-defined identifier collision cannot justify a rewrite.
                continue
            additions = [RuntimeNode(filter_id, R.COORDINATOR_FILTER,
                (outputs[driver_id],), {"condition": dict(condition)}, (enforcing.operator_id,)),
                RuntimeNode(anchor_id, R.COORDINATOR_ROW_PROJECT, (filter_id,),
                    {"projections": {identity: {"kind": "field", "field": identity}}},
                    (enforcing.operator_id,))]
            # Projection is DISTINCT in this runtime. The one-column right side
            # has one row per identity, so the existing inner join is an exact
            # semijoin without duplicate amplification or a new work category.
            additions.extend(RuntimeNode(replacements[outputs[t]], R.COORDINATOR_JOIN,
                (outputs[t], anchor_id), {"left_on": identity, "right_on": identity},
                (t, enforcing.operator_id)) for t in targets)
            nodes = tuple(replace(n, inputs=tuple(replacements.get(i, i) for i in n.inputs))
                          for n in plan.nodes) + tuple(additions)
            details = {"profile": PROFILE, "driver": driver_id, "identity_field": identity,
                "condition": dict(condition), "enforcing_filter": enforcing.operator_id,
                "target_matches": targets, "added_runtime_nodes": len(additions),
                "extra_remote_calls": 0, "source_queries_unchanged": True,
                "physical_form": "join_with_distinct_single_column_identity_keys",
                "selection": "first provably admissible equality in semantic input order",
                "original_final_constraints_preserved": True}
            return replace(plan, nodes=nodes, metadata={**dict(plan.metadata),
                "operator_outputs": {k: replacements.get(v, v) for k, v in outputs.items()},
                "anchor_reduction": details})
    return plan


def depends_on(plan: FederatedExecutionPlan, output: str, target: str) -> bool:
    """Check a prospective bind dependency before constructing a cyclic plan."""
    nodes = {n.node_id: n for n in plan.nodes}
    pending, seen = [output], set()
    while pending:
        identifier = pending.pop()
        if identifier == target:
            return True
        if identifier not in seen:
            seen.add(identifier)
            pending.extend(nodes[identifier].inputs)
    return False
