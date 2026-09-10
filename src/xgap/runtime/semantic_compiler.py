"""Compose an executable semantic DAG from node/path sources and row operators.

Source placement is an explicit input, separate from meaning. This compiler
constructs plans, not calibrated costs or optimal source assignments. It never
executes a backend, calls an LLM, or builds a catalog.
"""

from dataclasses import dataclass, replace
import hashlib
import json
from typing import Any, Mapping

from xgap.compilers.node_match import compile_node_match
from xgap.algebra.conditions import And
from xgap.backends.capabilities import BackendCapabilityProfile
from xgap.compilers.rdf_encoding import RdfEdgeEncoding, RdfRowEncoding
from xgap.llm.parser import parse_path_pattern_query, _parse_condition
from xgap.pattern.ast import NodePattern
from xgap.runtime.bounded_paths import compile_bounded_path_plan
from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNode, RuntimeNodeKind as R
from xgap.runtime.row_operations import condition_fields
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

    def __post_init__(self):
        RdfRowEncoding("semantic-identity", "urn:xgap:class", self.identity_property, self.resource_namespace)

    def path_options(self):
        return {"backend_id": self.backend_id, "resource_namespace": self.resource_namespace,
                "identity_property": self.identity_property, "backend_mapping": self.backend_mapping,
                "rdf_edge_encoding": self.rdf_edge_encoding, "rdf_node_classes": self.rdf_node_classes,
                "profile": self.profile}


@dataclass(frozen=True)
class ResultSchema:
    kind: V
    fields: frozenset[str]
    path_namespace: str | None = None


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
        elif kind == "path_length" and set(spec) == {"kind"} and source.kind is V.PATH_SET:
            pass
        elif kind in ("path_node", "path_edge") and set(spec) == {"kind", "position"} and source.kind is V.PATH_SET:
            position = spec["position"]
            if not (type(position) is int and position > 0) and not (
                    kind == "path_node" and position in ("first", "last")):
                raise SemanticProgramError("Invalid path projection position")
        else:
            raise SemanticProgramError("Project expression is outside this typed profile")
    return ResultSchema(V.BINDING_SET, frozenset(projections))


def compile_semantic_program(program: SemanticGraphProgram, *,
        source_bindings: Mapping[str, str], backends: Mapping[str, SemanticBackend],
        max_remote_calls: int = 16, max_parallelism: int = 4) -> FederatedExecutionPlan:
    """Compile every reachable operator once, preserving fan-out and DAG roots."""
    if not isinstance(program, SemanticGraphProgram):
        raise SemanticProgramError("Compilation requires a typed SemanticGraphProgram")
    if program.holes:
        raise SemanticProgramError("Resolve and bind semantic holes before compilation")
    operators = {op.operator_id: op for op in program.operators}
    nodes, outputs, schemas = [], {}, {}
    supported_params = {
        S.TRAVERSE: {"path_pattern", "anchor_field", "anchor_position"},
        S.MATCH: {"node", "entity_field", "properties"}, S.PROJECT: {"projections"},
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
        if kind is S.MATCH:
            entity = p.get("entity_field", "entity")
            properties = p.get("properties", {})
            if not isinstance(entity, str) or not entity or entity in properties:
                raise SemanticProgramError("Match requires a distinct entity output field")
            raw_node = p.get("node", {})
            if set(raw_node) - {"label", "properties"}:
                raise SemanticProgramError("Match node descriptors require label/properties")
            artifact = compile_node_match(NodePattern(**raw_node), properties, backend_id=backend_id,
                backend_mapping=backend.backend_mapping, rdf_node_classes=backend.rdf_node_classes,
                profile=backend.profile,
                artifact_id=f"{identifier}-match",
                condition=And(*(_parse_condition(c) for c in predicates)) if predicates else None)
            remote = add(op, "native", R.REMOTE_QUERY, parameters={"backend_id": backend_id, "artifact": artifact.to_dict()})
            output = add(op, "bindings", R.NORMALIZE_NODE_BINDINGS, (remote,), {
                "language": artifact.language, "identity_property": backend.identity_property,
                "resource_namespace": backend.resource_namespace, "entity_field": entity,
                "scalar_fields": list(properties)})
            schema = ResultSchema(V.BINDING_SET, frozenset((entity, *properties)))
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
            schema = ResultSchema(V.PATH_SET, frozenset(("path",)), backend.resource_namespace)
            if inputs:
                if sources[0].kind is not V.BINDING_SET or p.get("anchor_position", "first") not in ("first", "last"):
                    raise SemanticProgramError("Bound Traverse requires endpoint bindings")
                _fields((p["anchor_field"],), sources[0].fields)
                expanded = add(op, "anchor", R.COORDINATOR_ROW_PROJECT, (output,), {
                    "resource_namespace": backend.resource_namespace, "projections": {
                        "path": {"kind": "field", "field": "path"},
                        "anchor": {"kind": "path_node", "position": p.get("anchor_position", "first")}}})
                matched = add(op, "bound", R.COORDINATOR_SEMI_JOIN, (expanded, inputs[0]),
                              {"left_on": "anchor", "right_on": p["anchor_field"]})
                output = add(op, "result", R.PROJECT, (matched,), {"fields": ["path"]})
            elif set(p) - {"path_pattern"}:
                raise SemanticProgramError("Anchor parameters require a Traverse input")
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
                if spec.get("op") == "count" and spec.get("field") is not None:
                    raise SemanticProgramError("This count profile counts rows, not nullable fields")
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
        max_remote_calls, max_parallelism, {"compiler": "semantic_dag_v1",
        "semantic_program_sha256": hashlib.sha256(serialized.encode()).hexdigest(),
        "source_bindings": dict(source_bindings), "operator_outputs": outputs,
        **({"capability_admission": admission} if admission else {}),
        "schemas": {key: {"kind": s.kind.value, "fields": sorted(s.fields),
                          "path_namespace": s.path_namespace} for key, s in schemas.items()}})
