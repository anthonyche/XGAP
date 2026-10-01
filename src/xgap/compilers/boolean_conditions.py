"""Total scalar Boolean expressions for the modern native compiler.

Property bindings stay inside atomic EXISTS expressions in RDF. Atomic truth
is totalized before NOT, preserving the audited missing-property semantics.
"""

from collections.abc import Iterator
from dataclasses import replace
import json

from xgap.algebra.conditions import (Condition, And, Or, Not, EdgeRef, NodeRef, LabelEquals,
    LengthEquals, NodeNotEquals, PropertyEquals, PropertyNotEquals,
    PropertyLessThan, PropertyLessThanOrEqual, PropertyGreaterThan, PropertyGreaterThanOrEqual)
from xgap.compilers import cypher, sparql
from xgap.compilers.features import BoundCondition


PROFILE = "total_scalar_boolean_v1"
MAX_FLOAT = "1.7976931348623157e308"
NUMERIC = {PropertyLessThan:"<", PropertyLessThanOrEqual:"<=",
           PropertyGreaterThan:">", PropertyGreaterThanOrEqual:">="}


def walk_conditions(condition: Condition) -> Iterator[Condition]:
    yield condition
    if isinstance(condition, (And, Or)):
        for child in condition.conditions:
            yield from walk_conditions(child)
    elif isinstance(condition, Not):
        yield from walk_conditions(condition.condition)


def condition_leaves(condition: Condition) -> Iterator[Condition]:
    return (item for item in walk_conditions(condition) if not isinstance(item, (And, Or, Not)))


def literal(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _equality(variable: str, value: object, language: str) -> str:
    terms = [f"{variable} = {literal(value)}"]
    # Python scalar equality treats bool as 0/1; do not redefine the reference.
    if type(value) is bool:
        terms.append(f"{variable} = {int(value)}")
    elif type(value) in (int, float) and value in (0, 1):
        terms.append(f"{variable} = {literal(bool(value))}")
    operator = " OR " if language == "cypher" else " || "
    return "(" + operator.join(f"coalesce({term}, false)" for term in terms) + ")"


def cypher_condition(bound: BoundCondition, backend_id: str) -> str:
    item = bound.condition
    child = lambda c: cypher_condition(replace(bound, condition=c), backend_id)
    if isinstance(item, (And, Or)):
        return "(" + (" AND " if isinstance(item, And) else " OR ").join(child(c) for c in item.conditions) + ")"
    if isinstance(item, Not):
        return "(NOT " + child(item.condition) + ")"
    if isinstance(item, LengthEquals):
        return "true" if item.value == bound.edge_count else "false"
    if isinstance(item, (PropertyEquals, PropertyNotEquals)) or type(item) in NUMERIC:
        subject = cypher._node_var(bound, item.ref) if isinstance(item.ref, NodeRef) else cypher._edge_var(bound, item.ref)
        prop = f"{subject}.{cypher._cypher_identifier(item.property_name)}"
        if type(item) in NUMERIC:
            numeric = f"({prop} IS :: INTEGER NOT NULL OR {prop} IS :: FLOAT NOT NULL)"
            return (f"(CASE WHEN {numeric} THEN coalesce(({prop} >= -{MAX_FLOAT} AND {prop} <= {MAX_FLOAT} AND "
                    f"{prop} {NUMERIC[type(item)]} {literal(item.value)}), false) ELSE false END)")
        equal = _equality(prop, item.value, "cypher")
        return equal if isinstance(item, PropertyEquals) else f"({prop} IS NOT NULL AND NOT {equal})"
    if isinstance(item, LabelEquals) and isinstance(item.ref, EdgeRef):
        return f"(type({cypher._edge_var(bound, item.ref)}) = {literal(item.value)})"
    return "coalesce(" + cypher._condition_to_cypher(bound, backend_id) + ", false)"


def sparql_condition(bound, *, backend_id, mapping, used, rdf_encoding=None, rdf_edge_encoding=None) -> str:
    index = 0

    def mapped(value, kind):
        return sparql._mapped_iri(value, kind, mapping, used, backend_id)

    def render(item):
        nonlocal index
        if isinstance(item, (And, Or)):
            return "(" + (" && " if isinstance(item, And) else " || ").join(render(c) for c in item.conditions) + ")"
        if isinstance(item, Not):
            return "(!" + render(item.condition) + ")"
        if isinstance(item, LengthEquals):
            return "true" if item.value == bound.edge_count else "false"
        if isinstance(item, NodeNotEquals):
            return f"(!sameTerm({sparql._node_var(bound,item.left)}, {sparql._node_var(bound,item.right)}))"
        subject = (sparql._node_var(bound,item.ref) if isinstance(item.ref,NodeRef)
                   else f"?e{bound.edge_index(item.ref)+1}")
        if isinstance(item, LabelEquals):
            if isinstance(item.ref, NodeRef):
                predicate = rdf_encoding.class_predicate_iri if rdf_encoding is not None else "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
                return f"EXISTS {{ {subject} <{predicate}> {mapped(item.value,'node_labels')} . }}"
            if rdf_edge_encoding is None:
                return f"sameTerm({subject}, {mapped(item.value,'edge_labels')})"
            label = (literal(item.value) if rdf_edge_encoding.label_encoding == "logical_string"
                     else mapped(item.value,'edge_labels'))
            return f"EXISTS {{ {subject} <{rdf_edge_encoding.label_predicate_iri}> {label} . }}"
        if rdf_encoding is not None and isinstance(item.ref, NodeRef) and item.property_name == rdf_encoding.identity_property:
            if not isinstance(item, (PropertyEquals,PropertyNotEquals)):
                raise ValueError("Resource identity supports equality/inequality only")
            iri = rdf_encoding.resource_iri(item.value)
            equal = f"sameTerm({subject}, <{iri}>)"
            if isinstance(item, PropertyEquals):
                return equal
            ns = literal(rdf_encoding.resource_namespace)
            present = (f"isIRI({subject}) && STRSTARTS(STR({subject}), {ns}) && "
                       f'REGEX(SUBSTR(STR({subject}), {len(rdf_encoding.resource_namespace)+1}), "^[A-Za-z0-9_][A-Za-z0-9_.-]*$")')
            return f"({present} && !{equal})"
        predicate = mapped(item.property_name, "properties")
        variable = f"?booleanValue{index}"
        index += 1
        if type(item) in NUMERIC:
            comparison = (f"coalesce((isNumeric({variable}) && ABS({variable}) <= {MAX_FLOAT} && "
                          f"{variable} {NUMERIC[type(item)]} {literal(item.value)}), false)")
        else:
            comparison = _equality(variable, item.value, "sparql")
            if isinstance(item, PropertyNotEquals):
                comparison = "(!" + comparison + ")"
        return f"EXISTS {{ {subject} {predicate} {variable} . FILTER({comparison}) }}"

    return render(bound.condition)
