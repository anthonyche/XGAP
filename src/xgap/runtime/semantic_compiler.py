"""Compose an executable semantic DAG from node/path sources and row operators.

Source placement is an explicit input, separate from meaning. This compiler
constructs plans, not calibrated costs or optimal source assignments. It never
executes a backend, calls an LLM, or builds a catalog.
"""

from dataclasses import dataclass, replace
import hashlib
import json
import math
from typing import Any, Mapping
from types import SimpleNamespace

from xgap.compilers.node_match import compile_node_match
from xgap.compilers.edge_match import compile_edge_match
from xgap.algebra.conditions import And
from xgap.backends.capabilities import BackendCapabilityProfile
from xgap.compilers.rdf_encoding import RdfEdgeEncoding, RdfRowEncoding, RdfResourceTripleEncoding
from xgap.llm.parser import parse_path_pattern_query, _parse_condition
from xgap.pattern.ast import NodePattern, EdgePattern
from xgap.runtime.bounded_paths import compile_bounded_path_plan
from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNode, RuntimeNodeKind as R
from xgap.runtime.row_operations import condition_fields
from xgap.runtime.scalars import PROFILE as BINDING_VALUE_PROFILE
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.semantic_capabilities import admit_semantic_capabilities
from xgap.semantic.program import SemanticGraphProgram, SemanticOperatorKind as S, SemanticProgramError, SemanticValueKind as V


@dataclass(frozen=True)
class SemanticBackend:
    backend_id: str
    resource_namespace: str
    identity_property: str = "id"
    backend_mapping: Mapping[str, Any] | None = None
    rdf_edge_encoding: RdfEdgeEncoding | None = None
    rdf_node_classes: tuple[str, ...] = ()
    profile: BackendCapabilityProfile | None = None
    rdf_resource_encoding: RdfResourceTripleEncoding | None = None

    def __post_init__(self):
        RdfRowEncoding("semantic-identity", "urn:xgap:class", self.identity_property, self.resource_namespace)
        if self.rdf_resource_encoding is not None:
            encoding = self.rdf_resource_encoding
            if not isinstance(encoding, RdfResourceTripleEncoding):
                raise ValueError("Resource triple encoding must be explicitly typed")
            if (self.identity_property, self.resource_namespace) != (encoding.identity_property, encoding.resource_namespace):
                raise ValueError("Semantic and resource triple identity declarations differ")
            if self.backend_mapping is not None or self.rdf_edge_encoding is not None or self.rdf_node_classes:
                raise ValueError("Resource triple encoding cannot be combined with other mapping/edge/node encodings")

    def path_options(self):
        return {"backend_id": self.backend_id, "resource_namespace": self.resource_namespace,
                "identity_property": self.identity_property, "backend_mapping": self.backend_mapping,
                "rdf_edge_encoding": self.rdf_edge_encoding, "rdf_node_classes": self.rdf_node_classes,
                "profile": self.profile,
                **({"rdf_resource_encoding": self.rdf_resource_encoding} if self.rdf_resource_encoding else {})}


@dataclass(frozen=True)
class ResultSchema:
    kind: V
    fields: frozenset[str]
    path_namespace: str | None = None
    path_edge_projection: bool = True


def _fields(required, available):
    if not set(required) <= available:
        raise SemanticProgramError(f"Unknown input fields: {sorted(set(required) - available)}")


def _projection_schema(projections, source):
    if not isinstance(projections, dict) or not projections:
        raise SemanticProgramError("Project requires nonempty projections")
    for name, spec in projections.items():
        if not isinstance(name, str) or not name or not isinstance(spec, dict):
            raise SemanticProgramError("Invalid Project output")
        kind = spec.get("kind")
        if kind == "field" and set(spec) == {"kind", "field"}:
            _fields((spec["field"],), source.fields)
        elif kind == "literal" and set(spec) == {"kind", "value"}:
            value = spec["value"]
            if value is not None and (type(value) not in (str, bool, int, float)
                    or type(value) is float and not math.isfinite(value)):
                raise SemanticProgramError("Project literal requires a finite scalar")
        elif kind == "path_length" and set(spec) == {"kind"} and source.kind is V.PATH_SET:
            pass
        elif kind in ("path_node", "path_edge") and set(spec) == {"kind", "position"} and source.kind is V.PATH_SET:
            if kind == "path_edge" and not source.path_edge_projection:
                raise SemanticProgramError("Resource triple edge identity is not a node IRI projection")
            position = spec["position"]
            if not (type(position) is int and position > 0) and not (
                    kind == "path_node" and position in ("first", "last")):
                raise SemanticProgramError("Invalid path projection position")
        else:
            raise SemanticProgramError("Project expression is outside this typed profile")
    return ResultSchema(V.BINDING_SET, frozenset(projections))


SOURCE_INPUT = "__source_input__"


@dataclass(frozen=True)
class SemanticSourceFragment:
    nodes: tuple[RuntimeNode, ...]
    output: str
    schema: ResultSchema

    @property
    def remote_calls(self):
        return sum(n.kind is R.REMOTE_QUERY for n in self.nodes)


def compile_semantic_source(op, backend: SemanticBackend) -> SemanticSourceFragment:
    """Compile one local choice; a bound Traverse input stays a symbolic port."""
    identifier, kind, backend_id = op.operator_id, op.kind, backend.backend_id
    if kind not in (S.MATCH, S.TRAVERSE):
        raise SemanticProgramError("Local source options require Match or Traverse")
    if any(c.predicate is None for c in op.constraints):
        raise SemanticProgramError("Opaque constraints require explicit typed predicates")
    p = dict(op.parameters)
    allowed = ({"node", "edge", "source", "target", "source_field", "target_field", "entity_field", "properties"} if kind is S.MATCH else
               {"path_pattern", "anchor_field", "anchor_position"})
    if set(p) - allowed:
        raise SemanticProgramError(f"Unknown source parameters: {sorted(set(p) - allowed)}")
    predicates = [dict(c.predicate) for c in op.constraints]
    nodes = []

    def add(op, suffix, kind, inputs=(), parameters=None):
        node_id = f"{op.operator_id}/{suffix}"
        nodes.append(RuntimeNode(node_id, kind, tuple(inputs), parameters or {}, (op.operator_id,)))
        return node_id

    if kind is S.MATCH:
        if backend.rdf_resource_encoding is not None:
            raise SemanticProgramError("Resource triple encoding currently requires Traverse sources")
        entity = p.get("entity_field", "entity")
        properties = p.get("properties", {})
        edge_form = "edge" in p
        if edge_form and "node" in p or not edge_form and set(p) & {"source", "target", "source_field", "target_field"}:
            raise SemanticProgramError("Node and edge Match parameters are mutually exclusive")
        identities = {"entity": entity}
        if edge_form:
            identities.update(source=p.get("source_field", "source"), target=p.get("target_field", "target"))
        if (any(not isinstance(f, str) or not f or f in properties for f in identities.values())
                or len(set(identities.values())) != len(identities)):
            raise SemanticProgramError("Match requires distinct identity output fields")
        schema = ResultSchema(V.BINDING_SET, frozenset((*identities.values(), *properties)))
        path_predicates, row_predicates = [], []
        for predicate in predicates:
            if "op" in predicate:
                if "kind" in predicate:
                    raise SemanticProgramError("Match predicates cannot mix path and row discriminators")
                _fields(condition_fields(predicate), schema.fields)
                row_predicates.append(predicate)
            else:
                path_predicates.append(predicate)
        for descriptor in ("node", "edge", "source", "target"):
            if descriptor in p and (not isinstance(p[descriptor], dict) or set(p[descriptor]) - {"label", "properties"}):
                raise SemanticProgramError("Match descriptors require label/properties")
        options = dict(backend_id=backend_id, backend_mapping=backend.backend_mapping,
            profile=backend.profile, artifact_id=f"{identifier}-match",
            identity_property=backend.identity_property,
            condition=And(*(_parse_condition(c) for c in path_predicates)) if path_predicates else None)
        if edge_form:
            artifact = compile_edge_match(EdgePattern(**p["edge"]), properties,
                source=NodePattern(**p.get("source", {})), target=NodePattern(**p.get("target", {})),
                rdf_edge_encoding=backend.rdf_edge_encoding, **options)
        else:
            artifact = compile_node_match(NodePattern(**p.get("node", {})), properties,
                rdf_node_classes=backend.rdf_node_classes, **options)
        remote = add(op, "native", R.REMOTE_QUERY, parameters={"backend_id": backend_id, "artifact": artifact.to_dict()})
        output = add(op, "bindings", R.NORMALIZE_NODE_BINDINGS, (remote,), {
            "language": artifact.language, "identity_property": backend.identity_property,
            "resource_namespace": backend.resource_namespace, "entity_field": entity,
            **({"identity_fields": identities} if edge_form else {}),
            "scalar_fields": list(properties)})
        if row_predicates:
            # Keep binding equality/null/numeric semantics after normalization.
            condition = (row_predicates[0] if len(row_predicates) == 1
                         else {"op": "and", "args": row_predicates})
            output = add(op, "row_filter", R.COORDINATOR_FILTER, (output,), {"condition": condition})
    elif kind is S.TRAVERSE:
        query = parse_path_pattern_query(p["path_pattern"])
        if predicates:
            conditions = ([query.condition] if query.condition is not None else []) + [_parse_condition(c) for c in predicates]
            query = replace(query, condition=And(*conditions))
        plan = compile_bounded_path_plan(query, **backend.path_options())
        ids = {n.node_id: f"{identifier}/{n.node_id}" for n in plan.nodes}
        nodes.extend(replace(n, node_id=ids[n.node_id], inputs=tuple(ids[i] for i in n.inputs),
                             semantic_operator_ids=(identifier,)) for n in plan.nodes)
        output = ids[plan.roots[0]]
        schema = ResultSchema(V.PATH_SET, frozenset(("path",)), backend.resource_namespace,
                              backend.rdf_resource_encoding is None)
        if op.input_ids:
            if op.input_kinds[0] is not V.BINDING_SET or p.get("anchor_position", "first") not in ("first", "last"):
                raise SemanticProgramError("Bound Traverse requires endpoint bindings")
            expanded = add(op, "anchor", R.COORDINATOR_ROW_PROJECT, (output,), {
                "resource_namespace": backend.resource_namespace, "projections": {
                    "path": {"kind": "field", "field": "path"},
                    "anchor": {"kind": "path_node", "position": p.get("anchor_position", "first")}}})
            matched = add(op, "bound", R.COORDINATOR_SEMI_JOIN, (expanded, SOURCE_INPUT),
                          {"left_on": "anchor", "right_on": p["anchor_field"]})
            output = add(op, "result", R.PROJECT, (matched,), {"fields": ["path"]})
        elif set(p) - {"path_pattern"}:
            raise SemanticProgramError("Anchor parameters require a Traverse input")
    if op.output_kind is not schema.kind:
        raise SemanticProgramError(f"{identifier} declares the wrong output kind for its executable semantics")
    admit_semantic_capabilities(SimpleNamespace(operators=(op,)), nodes, {backend_id: backend})
    return SemanticSourceFragment(tuple(nodes), output, schema)


def compile_semantic_program(program: SemanticGraphProgram, *,
        source_bindings: Mapping[str, str], backends: Mapping[str, SemanticBackend],
        max_remote_calls: int = 16, max_parallelism: int = 4,
        _source_cache: dict | None = None) -> FederatedExecutionPlan:
    """Compile every reachable operator once, preserving fan-out and DAG roots."""
    if not isinstance(program, SemanticGraphProgram):
        raise SemanticProgramError("Compilation requires a typed SemanticGraphProgram")
    if program.holes:
        raise SemanticProgramError("Resolve and bind semantic holes before compilation")
    operators = {op.operator_id: op for op in program.operators}
    nodes, outputs, schemas = [], {}, {}
    supported_params = {
        S.TRAVERSE: {"path_pattern", "anchor_field", "anchor_position"},
        S.MATCH: {"node", "edge", "source", "target", "source_field", "target_field", "entity_field", "properties"}, S.PROJECT: {"projections"},
        S.FILTER: {"condition"}, S.JOIN: {"left_on", "right_on", "right_prefix"},
        S.UNION: set(), S.AGGREGATE: {"group_by", "aggregations"},
        S.ORDER_LIMIT: {"order_by", "limit"}, S.ALIGN: {"field", "output_field", "mapping", "on_missing"},
    }

    def add(op, suffix, kind, inputs=(), parameters=None):
        node_id = f"{op.operator_id}/{suffix}"
        nodes.append(RuntimeNode(node_id, kind, tuple(inputs), parameters or {}, (op.operator_id,)))
        return node_id

    def visit(identifier):
        if identifier in outputs:
            return
        op = operators[identifier]
        if any(c.predicate is None for c in op.constraints):
            raise SemanticProgramError("Opaque constraints require explicit typed predicates")
        predicates = [dict(c.predicate) for c in op.constraints]
        if predicates and op.kind not in (S.MATCH, S.TRAVERSE, S.FILTER):
            raise SemanticProgramError("Place executable constraints on Match, Traverse or Filter")
        p = dict(op.parameters)
        if set(p) - supported_params[op.kind]:
            raise SemanticProgramError(f"Unknown {op.kind.value} parameters: {sorted(set(p) - supported_params[op.kind])}")
        for child in op.input_ids:
            visit(child)
        inputs = [outputs[child] for child in op.input_ids]
        sources = [schemas[child] for child in op.input_ids]
        kind = op.kind
        if kind in (S.MATCH, S.TRAVERSE):
            backend_id = source_bindings.get(identifier)
            if backend_id not in backends or backends[backend_id].backend_id != backend_id:
                raise SemanticProgramError(f"No declared backend placement for {identifier}")
            backend = backends[backend_id]
        if kind in (S.MATCH, S.TRAVERSE):
            key = (identifier, backend_id)
            fragment = _source_cache.get(key) if _source_cache is not None else None
            if fragment is None:
                fragment = compile_semantic_source(op, backend)
                if _source_cache is not None:
                    _source_cache[key] = fragment
            if kind is S.TRAVERSE and inputs:
                _fields((p["anchor_field"],), sources[0].fields)
            nodes.extend(replace(n, inputs=tuple(inputs[0] if i == SOURCE_INPUT else i for i in n.inputs))
                         for n in fragment.nodes)
            output, schema = fragment.output, fragment.schema
        elif kind is S.PROJECT:
            schema = _projection_schema(p["projections"], sources[0])
            output = add(op, "project", R.COORDINATOR_ROW_PROJECT, inputs,
                         {**p, "resource_namespace": sources[0].path_namespace})
        elif kind is S.FILTER:
            if sources[0].kind not in (V.BINDING_SET, V.GROUPED_BINDINGS):
                raise SemanticProgramError("Project path fields before row Filter")
            conditions = ([p["condition"]] if "condition" in p else []) + predicates
            if not conditions:
                raise SemanticProgramError("Filter requires a condition or a typed constraint")
            p["condition"] = conditions[0] if len(conditions) == 1 else {"op": "and", "args": conditions}
            _fields(condition_fields(p["condition"]), sources[0].fields)
            output, schema = add(op, "filter", R.COORDINATOR_FILTER, inputs, p), sources[0]
        elif kind is S.UNION:
            if sources[0] != sources[1]:
                raise SemanticProgramError("Union inputs must have the same schema and path identity namespace")
            output, schema = add(op, "union", R.MERGE, inputs), sources[0]
        elif kind is S.JOIN:
            if any(s.kind not in (V.BINDING_SET, V.GROUPED_BINDINGS) for s in sources):
                raise SemanticProgramError("Join requires binding rows; project path keys first")
            _fields((p["left_on"],), sources[0].fields)
            _fields((p["right_on"],), sources[1].fields)
            prefix = p.get("right_prefix", "right_")
            renamed = {f: (prefix + f if f in sources[0].fields
                       and not (f == p["left_on"] == p["right_on"]) else f) for f in sources[1].fields}
            if len(set(renamed.values())) != len(renamed) or any(
                    target in sources[0].fields and target != p["left_on"]
                    for field, target in renamed.items() if target != field):
                raise SemanticProgramError("Join right prefix produces conflicting columns")
            right = add(op, "right_columns", R.COORDINATOR_ROW_PROJECT, (inputs[1],),
                        {"projections": {target: {"kind": "field", "field": source} for source, target in renamed.items()}})
            params = {"left_on": p["left_on"], "right_on": renamed[p["right_on"]], "right_prefix": prefix}
            output = add(op, "join", R.COORDINATOR_JOIN, (inputs[0], right), params)
            schema = ResultSchema(V.BINDING_SET, sources[0].fields | frozenset(renamed.values()))
        elif kind is S.AGGREGATE:
            if sources[0].kind not in (V.BINDING_SET, V.GROUPED_BINDINGS):
                raise SemanticProgramError("Aggregate requires binding rows")
            _fields(p["group_by"], sources[0].fields)
            for spec in p["aggregations"].values():
                if spec.get("field") is not None:
                    _fields((spec["field"],), sources[0].fields)
            params = {**p, "allow_global": True}
            node = RuntimeNode("validate-aggregate", R.COORDINATOR_GROUP_AGGREGATE, ("input",), params)
            FederatedScheduler._group_aggregate(node, ())
            output = add(op, "aggregate", R.COORDINATOR_GROUP_AGGREGATE, inputs, params)
            schema = ResultSchema(V.GROUPED_BINDINGS, frozenset((*p["group_by"], *p["aggregations"])))
        elif kind is S.ORDER_LIMIT:
            if sources[0].kind not in (V.BINDING_SET, V.GROUPED_BINDINGS):
                raise SemanticProgramError("OrderLimit requires binding rows")
            _fields((spec["field"] for spec in p["order_by"]), sources[0].fields)
            FederatedScheduler._sort_limit(RuntimeNode("validate-sort", R.COORDINATOR_SORT_LIMIT, ("input",), p), ())
            output, schema = add(op, "order", R.COORDINATOR_SORT_LIMIT, inputs, p), sources[0]
        elif kind is S.ALIGN:
            if sources[0].kind is not V.BINDING_SET:
                raise SemanticProgramError("Align requires binding rows")
            _fields((p["field"],), sources[0].fields)
            FederatedScheduler._align(RuntimeNode("validate-align", R.ALIGN, ("input",), p), ())
            output = add(op, "align", R.ALIGN, inputs, p)
            schema = ResultSchema(V.BINDING_SET, sources[0].fields | {p.get("output_field", p["field"])})
        else:
            raise SemanticProgramError(f"Unsupported semantic operator {kind.value}")
        if op.output_kind is not schema.kind:
            raise SemanticProgramError(f"{identifier} declares the wrong output kind for its executable semantics")
        outputs[identifier], schemas[identifier] = output, schema

    for root in program.roots:
        visit(root)
    if set(outputs) != set(operators):
        raise SemanticProgramError("Semantic program contains unreachable operators")
    if set(source_bindings) != {op.operator_id for op in program.operators if op.kind in (S.MATCH, S.TRAVERSE)}:
        raise SemanticProgramError("Source bindings must exactly cover Match/Traverse operators")
    admission = admit_semantic_capabilities(program, nodes, backends)
    serialized = json.dumps(program.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return FederatedExecutionPlan(program.program_id, tuple(nodes), tuple(outputs[r] for r in program.roots),
        max_remote_calls, max_parallelism, {"compiler": "semantic_dag_v1", "binding_value_profile": BINDING_VALUE_PROFILE,
        "semantic_program_sha256": hashlib.sha256(serialized.encode()).hexdigest(),
        "source_bindings": dict(source_bindings), "operator_outputs": outputs,
        **({"capability_admission": admission} if admission else {}),
        "schemas": {key: {"kind": s.kind.value, "fields": sorted(s.fields),
                          "path_namespace": s.path_namespace} for key, s in schemas.items()}})
