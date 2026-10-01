"""Dataset-owned lowering of validated path intent to the RDF resource mirror.

This preserves the fixed-row semantics already defined by D195. A declared
scalar encoding is checked on reached resources before literal filtering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from types import MappingProxyType
from typing import Any, Mapping

from xgap.algebra.conditions import Or, Not, EdgeRef, LabelEquals, LengthEquals, NodeNotEquals, NodeRef, PropertyEquals, PropertyNotEquals
from xgap.backends.rdf_terms import RDF_TERMS_V1
from xgap.backends.sparql_bindings import IRI_ROWS_MARKER
from xgap.compilers.directed import _literal, _OPERATORS, _shape, compile_directed_rows
from xgap.compilers.features import default_profile
from xgap.compilers.rdf_encoding import RdfRowEncoding
from xgap.experiments.freebase_native_answers import EDGE_LABEL, RESOURCE_LABEL
from xgap.infrastructure.runtime import QueryArtifact
from xgap.pattern.ast import Direction, PathMode, PathPatternQuery
from xgap.pattern.semantic_validation import NUMERIC_CONDITIONS, PROPERTY_CONDITIONS
from xgap.runtime import FederatedExecutionPlan, RuntimeNode, RuntimeNodeKind


IDENTITY_PROPERTY = "type.object.id"
NS = "http://rdf.freebase.com/ns/"
XSD = "http://www.w3.org/2001/XMLSchema#"


class CandidateExecutionUnavailable(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class FreebaseExecutionMapping:
    mapping_id: str
    snapshot_sha256: str
    scalar_properties: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (not isinstance(self.mapping_id, str) or not self.mapping_id
                or not isinstance(self.snapshot_sha256, str)
                or not re.fullmatch(r"[a-f0-9]{64}", self.snapshot_sha256)
                or not isinstance(self.scalar_properties, Mapping)):
            raise ValueError("Execution mapping requires a source snapshot identity")
        for name, kind in self.scalar_properties.items():
            self.iri(name)
            if name == IDENTITY_PROPERTY or kind not in {"string", "numeric", "boolean"}:
                raise ValueError("Scalar mappings require explicit supported value types")
        object.__setattr__(self, "scalar_properties", MappingProxyType(dict(self.scalar_properties)))

    @property
    def rdf(self) -> RdfRowEncoding:
        return RdfRowEncoding(self.mapping_id, NS+"type.object.type", IDENTITY_PROPERTY, NS)

    def iri(self, identifier: object) -> str:
        return self.rdf.resource_iri(identifier)

    def to_dict(self) -> dict[str, Any]:
        return {"mapping_id": self.mapping_id, "snapshot_sha256": self.snapshot_sha256,
                "scalar_properties": dict(self.scalar_properties), "resource_encoding": "rdf-resource-edge-mirror-v1"}


@dataclass(frozen=True)
class ExecutionRequirements:
    require_entity_anchor: bool
    answer_position: int | str = "last"
    required_bindings: tuple[tuple[int, str], ...] = ()

    def __post_init__(self) -> None:
        if type(self.require_entity_anchor) is not bool:
            raise ValueError("The goal must explicitly declare entity-anchor requirements")
        if self.answer_position != "last" and (type(self.answer_position) is not int or self.answer_position <= 0):
            raise ValueError("Answer position must be last or a positive one-based position")
        for position, identity in self.required_bindings:
            if type(position) is not int or position <= 0 or not isinstance(identity, str) or not identity:
                raise ValueError("Required entity bindings must be explicit positions and IDs")
        bindings = tuple((position, identity) for position, identity in self.required_bindings)
        if len({position for position, _ in bindings}) != len(bindings):
            raise ValueError("A goal cannot declare duplicate or conflicting bindings at one position")
        object.__setattr__(self, "required_bindings", bindings)

    def to_dict(self) -> dict[str, Any]:
        return {"require_entity_anchor": self.require_entity_anchor, "answer_position": self.answer_position,
                "required_bindings": [list(item) for item in self.required_bindings]}


def check_execution_anchors(query: PathPatternQuery, requirements: ExecutionRequirements) -> tuple[tuple[int, str], ...]:
    shape = _shape(query, default_profile("neo4j"))
    # This frozen split adapter still partitions conjuncts between engines.
    # A broader shared shape validator must not let OR/NOT disappear here.
    if any(isinstance(bound.condition, (Or, Not)) for bound in shape.conditions):
        raise CandidateExecutionUnavailable("boolean_condition",
            "This dataset adapter requires conjunctive fixed rows; use the modern native path plan for Boolean conditions")
    if query.restrictor is PathMode.SIMPLE:
        unequal = {frozenset((b.node_index(c.left), b.node_index(c.right))) for b in shape.conditions
                   if isinstance(c := b.condition, NodeNotEquals)}
        if any(frozenset((i, j)) not in unequal for i in range(shape.edge_count+1)
               for j in range(i+1, shape.edge_count+1)):
            raise CandidateExecutionUnavailable("implicit_restrictor", "SIMPLE requires the existing parser's explicit node inequalities")
    elif query.restrictor is not PathMode.WALK:
        raise CandidateExecutionUnavailable("implicit_restrictor", "This dataset adapter requires WALK or explicitly constrained SIMPLE")
    if query.max_depth is not None and query.max_depth < shape.edge_count:
        raise CandidateExecutionUnavailable("depth_contract", "The fixed path exceeds the declared depth budget")
    anchors = tuple(sorted({(bound.node_index(c.ref)+1, c.value) for bound in shape.conditions
        if type(c := bound.condition) is PropertyEquals and isinstance(c.ref, NodeRef)
        and c.property_name == IDENTITY_PROPERTY and isinstance(c.value, str)}))
    if requirements.require_entity_anchor and not anchors:
        raise CandidateExecutionUnavailable("required_entity_anchor_missing",
            "The goal requires an entity anchor, but no node has a positive type.object.id equality. "
            "Declared entity_ids alone do not constrain execution; use an explicitly selected visible ID in the AST.")
    if any(binding not in anchors for binding in requirements.required_bindings):
        raise CandidateExecutionUnavailable("required_entity_binding_missing", "The query omits an explicit goal-owned entity/position binding")
    return anchors


@dataclass(frozen=True)
class CompiledCandidateExecution:
    plan: FederatedExecutionPlan
    baseline: QueryArtifact
    max_rows: int
    input_pattern_sha256: str
    mapping: FreebaseExecutionMapping


def compile_candidate_execution(query: PathPatternQuery, mapping: FreebaseExecutionMapping,
                                requirements: ExecutionRequirements, *, max_rows: int,
                                max_binding_bytes: int) -> CompiledCandidateExecution:
    if any(type(v) is not int or v <= 0 for v in (max_rows, max_binding_bytes)):
        raise ValueError("Candidate execution requires finite positive budgets")
    check_execution_anchors(query, requirements)
    shape = _shape(query, default_profile("neo4j"))
    answer_index = shape.edge_count if requirements.answer_position == "last" else requirements.answer_position-1
    if answer_index > shape.edge_count:
        raise CandidateExecutionUnavailable("answer_position", "Answer position is outside the fixed path")
    columns = [f"n{i}" for i in range(shape.edge_count+1)]
    tokens: dict[str, dict[str, str]] = {"node_labels": {}, "edge_labels": {}, "properties": {}}
    terms: dict[str, dict[str, str]] = {}
    filters, scalar_filters, checks = [], [], []
    neo_parameters: dict[str, Any] = {}

    def term(name: str, category: str) -> str:
        iri = mapping.iri(name)
        kind = {"node_labels":"class", "edge_labels":"relation", "properties":"property"}[category]
        if name in terms and terms[name]["kind"] != kind:
            raise CandidateExecutionUnavailable("mapping_kind", "One canonical ID has conflicting term roles")
        tokens[category][name] = name
        terms[name] = {"kind":kind,"representation":iri}
        return iri

    def parameter(value: object) -> str:
        name = f"p{len(neo_parameters)}"
        neo_parameters[name] = value
        return "$"+name

    for bound in shape.conditions:
        c = bound.condition
        if isinstance(c, LengthEquals):
            filters.append("true" if c.value == shape.edge_count else "false")
        elif isinstance(c, NodeNotEquals):
            filters.append(f"n{bound.node_index(c.left)} <> n{bound.node_index(c.right)}")
        elif isinstance(c, LabelEquals):
            if isinstance(c.ref, EdgeRef):
                filters.append(f"r{bound.edge_index(c.ref)}.predicate = {parameter(term(c.value,'edge_labels'))}")
            else:
                node = f"n{bound.node_index(c.ref)}"
                filters.append(f"EXISTS {{ MATCH ({node})-[:{EDGE_LABEL} {{predicate: {parameter(NS+'type.object.type')}}}]"
                               f"->(:{RESOURCE_LABEL} {{iri: {parameter(term(c.value,'node_labels'))}}}) }}")
        elif type(c) in PROPERTY_CONDITIONS:
            if not isinstance(c.ref, NodeRef):
                raise CandidateExecutionUnavailable("rdf_edge_property", "No RDF edge-property reification is declared")
            node = f"n{bound.node_index(c.ref)}"
            if c.property_name == IDENTITY_PROPERTY:
                if type(c) not in (PropertyEquals, PropertyNotEquals):
                    raise CandidateExecutionUnavailable("entity_identity_order", "Resource identity supports equality/inequality only")
                operator = "=" if type(c) is PropertyEquals else "<>"
                filters.append(f"{node}.iri {operator} {parameter(mapping.iri(c.value))}")
                if type(c) is PropertyNotEquals:
                    # Match the existing RDF encoding's logical-ID domain.
                    filters.append(f"{node}.iri STARTS WITH {parameter(NS)}")
                    filters.append(f"substring({node}.iri, {len(NS)}) =~ '[A-Za-z0-9_][A-Za-z0-9_.-]*'")
                continue
            kind = mapping.scalar_properties.get(c.property_name)
            if kind is None:
                raise CandidateExecutionUnavailable("scalar_encoding_undeclared", f"No functional scalar encoding for {c.property_name}")
            value_kind = "boolean" if type(c.value) is bool else "numeric" if type(c.value) in (int,float) else "string"
            if value_kind != kind or (type(c) in NUMERIC_CONDITIONS and kind != "numeric"):
                raise CandidateExecutionUnavailable("scalar_constant_type", "Query constant and declared scalar type disagree")
            if type(c.value) is float and not math.isfinite(c.value):
                raise CandidateExecutionUnavailable("nonfinite_scalar", "Numeric query constants must be finite")
            predicate = term(c.property_name, "properties")
            i = len(scalar_filters)
            scalar_filters.append(f"?{node} <{predicate}> ?v{i} . FILTER(?v{i} {_OPERATORS[type(c)]} {_literal(c.value)})")
            valid = {"string":f"isLiteral(?x) && DATATYPE(?x) = <{XSD}string>",
                     "boolean":f"isLiteral(?x) && DATATYPE(?x) = <{XSD}boolean> && (?x = true || ?x = false)",
                     "numeric":f'isNumeric(?x) && ?x > "-INF"^^<{XSD}double> && ?x < "INF"^^<{XSD}double>'}[kind]
            checks.append(f"EXISTS {{ ?{node} <{predicate}> ?a, ?b . FILTER(!sameTerm(?a,?b)) }} || "
                          f"EXISTS {{ ?{node} <{predicate}> ?x . FILTER(!COALESCE(({valid}), false)) }}")

    mapped = {"mapping_id":mapping.mapping_id,"version":"1", "backends":{"fuseki":{"namespace":NS,"compiler_tokens":tokens}},
              "term_mappings":{"fuseki":terms}}
    baseline_rows = compile_directed_rows(query, backend_id="fuseki", backend_mapping=mapped, rdf_encoding=mapping.rdf)
    pattern_hash = baseline_rows.parameters["input_pattern_sha256"]
    prefix = "candidate-"+pattern_hash[:16]
    baseline = QueryArtifact(prefix+"-baseline", "sparql",
        "SELECT DISTINCT ?answer WHERE { {\n"+baseline_rows.text+"\n} FILTER("+
        " && ".join(f"isIRI(?{c})" for c in columns)+f") BIND(?n{answer_index} AS ?answer) }} LIMIT {max_rows+1}",
        kind="compiled", parameters={"rdf_result_encoding":RDF_TERMS_V1,"expected_result_columns":["answer"]})
    matches = []
    for i, edge in enumerate(shape.edges):
        relation = f"-[r{i}:{EDGE_LABEL}]->" if edge.direction is Direction.OUT else f"<-[r{i}:{EDGE_LABEL}]-"
        matches.append(f"MATCH (n{i}:{RESOURCE_LABEL}){relation}(n{i+1}:{RESOURCE_LABEL})")
    neo_text = "\n".join(matches) + ("\nWHERE "+" AND ".join(filters) if filters else "")
    neo_text += "\nRETURN DISTINCT "+", ".join(f"{c}.iri AS {c}" for c in columns)
    neo_text += f", {{type: 'uri', value: n{answer_index}.iri}} AS answer LIMIT {max_rows+1}"
    neo = QueryArtifact(prefix+"-paths", "cypher", neo_text, kind="compiled", parameters=neo_parameters)
    nodes = [RuntimeNode("paths",RuntimeNodeKind.REMOTE_QUERY,parameters={"backend_id":"neo4j","artifact":neo.to_dict()}),
             RuntimeNode("path-rows",RuntimeNodeKind.EXCHANGE,("paths",))]
    parent = "path-rows"
    if scalar_filters:
        binding = {"parameter":"path_rows","columns":columns,"max_bindings":max_rows,"max_bytes":max_binding_bytes}
        common = {"sparql_iri_rows":binding,"rdf_result_encoding":RDF_TERMS_V1}
        guard = QueryArtifact(prefix+"-scalar-contract", "sparql", "SELECT DISTINCT "+" ".join("?"+c for c in columns)+
            " ?invalid WHERE { "+IRI_ROWS_MARKER+" BIND(("+" || ".join("("+v+")" for v in checks)+
            f") AS ?invalid) }} LIMIT {max_rows+1}", kind="compiled", parameters={**common,
                "expected_result_columns":[*columns,"invalid"],"xgap_scalar_guard_columns":columns})
        apply = QueryArtifact(prefix+"-literal-filter", "sparql", "SELECT DISTINCT ?answer WHERE { "+IRI_ROWS_MARKER+
            "\n"+"\n".join(scalar_filters)+f"\nBIND(?n{answer_index} AS ?answer) }} LIMIT {max_rows+1}",
            kind="compiled",parameters={**common,"expected_result_columns":["answer"]})
        for node_id, artifact in (("scalar-contract",guard),("literal-filter",apply)):
            nodes.append(RuntimeNode(node_id,RuntimeNodeKind.REMOTE_BIND_QUERY,(parent,),parameters={
                "backend_id":"fuseki","artifact":artifact.to_dict(),"bind_fields":columns,
                "parameter":"path_rows","max_bindings":max_rows}))
            parent = node_id
        nodes.append(RuntimeNode("rdf-rows",RuntimeNodeKind.EXCHANGE,(parent,)))
        parent = "rdf-rows"
    nodes.append(RuntimeNode("answer",RuntimeNodeKind.PROJECT,(parent,),parameters={"fields":["answer"]}))
    plan = FederatedExecutionPlan(prefix,tuple(nodes),("answer",),max_remote_calls=3,max_parallelism=1,
        metadata={"input_pattern_sha256":pattern_hash,"mapping":mapping.to_dict(),
                  "execution_requirements":requirements.to_dict(),"max_result_rows":max_rows})
    return CompiledCandidateExecution(plan,baseline,max_rows,pattern_hash,mapping)
