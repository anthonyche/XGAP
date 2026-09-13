"""Polynomial-size, executable strategy alternatives for a bound semantic DAG.

The domain contains the coordinator plan, at most one entity-bind rewrite per
Join direction, and one deterministic proved-anchor fanout candidate. There
are at most 2 + 2J plans, not a product of local choices. Compilation and
candidate construction perform no data access, profiling, model call or cost
selection. An estimator can select its minimum over this explicit domain.

V1 binds a Match source (optionally behind entity-preserving Project/Filter)
using canonical entity keys from the other Join input. The original Join stays
in place, preserving columns and multiple distinct rows with the same key.
Other source shapes keep the baseline and receive an admission reason.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import hashlib
import json
import time
from typing import Any, Mapping

from xgap.backends.capabilities import SupportLevel
from xgap.backends.compatibility import check_backend_support
from xgap.backends.sparql_bindings import IRI_VALUES_MARKER
from xgap.compilers.cypher import _cypher_identifier
from xgap.compilers.features import default_profile
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNode, RuntimeNodeKind as R
from xgap.runtime.anchor_reduction import reduce_scalar_anchor, depends_on
from xgap.runtime.planning import FederatedPlanCandidate
from xgap.runtime.semantic_compiler import SemanticBackend, compile_semantic_program
from xgap.runtime.semantic_placement import _admit_expansion
from xgap.semantic.program import SemanticGraphProgram, SemanticOperatorKind as S, SemanticProgramError


STRATEGY_PROFILE = "semantic-anchor-fanout-and-single-bind-v3"
MAX_SEMANTIC_OPERATORS = 64
MAX_PROGRAM_BYTES = 1_048_576


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class PhysicalStrategyCandidate:
    strategy_id: str
    plan: FederatedExecutionPlan
    semantic_equivalence_key: str
    features: Mapping[str, int | float]
    assumptions: tuple[str, ...]

    @property
    def candidate(self) -> FederatedPlanCandidate:
        return FederatedPlanCandidate(self.plan, self.semantic_equivalence_key)

    def to_dict(self) -> dict[str, Any]:
        return {"strategy_id": self.strategy_id, "plan": self.plan.to_dict(),
                "semantic_equivalence_key": self.semantic_equivalence_key,
                "features": dict(self.features), "assumptions": list(self.assumptions)}


@dataclass(frozen=True)
class PhysicalStrategySpace:
    candidates: tuple[PhysicalStrategyCandidate, ...]
    rejected_strategies: tuple[dict[str, str], ...]
    preparation_ms: float
    semantic_equivalence_key: str
    join_count: int
    anchor_candidate_upper_bound: int = 0

    @property
    def candidate_count_upper_bound(self) -> int:
        return 1 + 2 * self.join_count + self.anchor_candidate_upper_bound

    def to_dict(self) -> dict[str, Any]:
        return {"profile": STRATEGY_PROFILE, "candidates": [c.to_dict() for c in self.candidates],
                "rejected_strategies": list(self.rejected_strategies),
                "preparation_ms": self.preparation_ms,
                "semantic_equivalence_key": self.semantic_equivalence_key,
                "candidate_count_upper_bound": self.candidate_count_upper_bound,
                "domain": "baseline_or_one_join_bind_or_one_anchor_fanout; fixed_source_bindings",
                "external_calls": 0, "combination_enumeration": False,
                "anchor_candidate_upper_bound": self.anchor_candidate_upper_bound,
                "actual_cost_optimality_claim": False}


class _NotAdmitted(ValueError):
    pass


def _with_exchanges(plan: FederatedExecutionPlan) -> FederatedExecutionPlan:
    exchanges = {n.node_id: n.node_id + "/strategy_exchange" for n in plan.nodes
                 if n.kind is R.REMOTE_QUERY}
    if set(exchanges.values()) & {n.node_id for n in plan.nodes}:
        raise SemanticProgramError("Generated strategy exchange IDs collide")
    nodes = []
    for node in plan.nodes:
        if node.kind is R.REMOTE_QUERY:
            nodes.extend((node, RuntimeNode(exchanges[node.node_id], R.EXCHANGE,
                (node.node_id,), semantic_operator_ids=node.semantic_operator_ids)))
        else:
            nodes.append(replace(node, inputs=tuple(exchanges.get(i, i) for i in node.inputs)))
    return replace(plan, nodes=tuple(nodes), roots=tuple(exchanges.get(r, r) for r in plan.roots))


def strategy_features(plan: FederatedExecutionPlan, program: SemanticGraphProgram) -> dict[str, int]:
    """Static, answer-blind features; no cardinalities or measured times invented."""
    kinds = Counter(n.kind for n in plan.nodes)
    remote = [n for n in plan.nodes if n.kind in (R.REMOTE_QUERY, R.REMOTE_BIND_QUERY)]
    by_id = {n.node_id: n for n in plan.nodes}
    depths: dict[str, int] = {}

    def depth(node_id):
        if node_id not in depths:
            depths[node_id] = 1 + max((depth(i) for i in by_id[node_id].inputs), default=0)
        return depths[node_id]

    return {"semantic_operator_count": len(program.operators), "runtime_node_count": len(plan.nodes),
            "remote_query_count": len(remote), "bind_query_count": kinds[R.REMOTE_BIND_QUERY],
            "exchange_count": kinds[R.EXCHANGE], "join_count": kinds[R.COORDINATOR_JOIN],
            "semi_join_count": kinds[R.COORDINATOR_SEMI_JOIN],
            "filter_count": kinds[R.COORDINATOR_FILTER],
            "aggregate_count": kinds[R.COORDINATOR_GROUP_AGGREGATE],
            "sort_limit_count": kinds[R.COORDINATOR_SORT_LIMIT],
            "traverse_count": sum(op.kind is S.TRAVERSE for op in program.operators),
            "backend_count": len({n.parameters["backend_id"] for n in remote}),
            "dag_depth": max(depth(n.node_id) for n in plan.nodes),
            "native_query_bytes": sum(len(n.parameters["artifact"]["text"].encode()) for n in remote),
            "max_parallelism": plan.max_parallelism}


def _entity_lineage(operators, schemas):
    """Conservative proof that an output field is a canonical resource IRI."""
    cache = {}

    def is_entity(identifier, field):
        key = identifier, field
        if key in cache:
            return cache[key]
        op = operators[identifier]
        p = op.parameters
        result = False
        if op.kind is S.MATCH:
            result = field == p.get("entity_field", "entity")
            if "edge" in p:
                result = result or field in (p.get("source_field", "source"), p.get("target_field", "target"))
        elif op.kind in (S.FILTER, S.ORDER_LIMIT):
            result = is_entity(op.input_ids[0], field)
        elif op.kind is S.AGGREGATE and field in p["group_by"]:
            result = is_entity(op.input_ids[0], field)
        elif op.kind is S.PROJECT:
            spec = p["projections"].get(field, {})
            if spec.get("kind") == "field":
                result = is_entity(op.input_ids[0], spec["field"])
            elif spec.get("kind") in ("path_node", "path_edge"):
                result = schemas[op.input_ids[0]]["path_namespace"] is not None
        elif op.kind is S.UNION:
            result = all(is_entity(i, field) for i in op.input_ids)
        elif op.kind is S.JOIN:
            left_fields = set(schemas[op.input_ids[0]]["fields"])
            if field in left_fields:
                result = is_entity(op.input_ids[0], field)
            else:
                prefix = p.get("right_prefix", "right_")
                for original in schemas[op.input_ids[1]]["fields"]:
                    renamed = (prefix + original if original in left_fields
                               and not (original == p["left_on"] == p["right_on"]) else original)
                    if renamed == field:
                        result = is_entity(op.input_ids[1], original)
                        break
        cache[key] = result
        return result

    return is_entity


def _target_match(identifier, field, operators, consumers, roots):
    chain = []
    while True:
        op = operators[identifier]
        if identifier in roots or consumers[identifier] != 1:
            raise _NotAdmitted("Target Match/Project/Filter chain is shared or a separate answer root")
        chain.append(identifier)
        if op.kind is S.MATCH:
            identities = {op.parameters.get("entity_field", "entity"): "entity"}
            if "edge" in op.parameters:
                identities.update({op.parameters.get("source_field", "source"): "source",
                    op.parameters.get("target_field", "target"): "target"})
            if field not in identities:
                raise _NotAdmitted("Target join key is not the Match entity identity")
            return op, tuple(chain), identities[field]
        if op.kind is S.PROJECT:
            spec = op.parameters["projections"].get(field, {})
            if spec.get("kind") != "field":
                raise _NotAdmitted("Target Project does not preserve a Match entity field")
            field = spec["field"]
        elif op.kind is not S.FILTER:
            raise _NotAdmitted("Target requires a Match source behind only Project/Filter")
        identifier = op.input_ids[0]


def _bound_match_artifact(artifact, backend, *, max_bindings, max_binding_bytes, identity_column="entity"):
    compiler = artifact.parameters.get("compiler")
    if compiler not in ("semantic_node_match_v1", "semantic_edge_match_v1"):
        raise _NotAdmitted("Target native artifact was not produced by the Match compiler")
    if identity_column not in ({"entity", "source", "target"} if compiler == "semantic_edge_match_v1" else {"entity"}):
        raise _NotAdmitted("Target native identity column is unavailable")
    profile = backend.profile or default_profile(backend.backend_id)
    language = artifact.language.lower()
    expected = {"cypher": ("neo4j", "labeled_property_graph"), "sparql": ("fuseki", "rdf_graph")}
    if (language not in expected or (profile.engine, profile.data_model) != expected[language]
            or profile.backend_id != backend.backend_id or profile.language.lower() != language):
        raise _NotAdmitted("No entity-bind adapter for the declared backend engine/language/model")
    if check_backend_support(profile, "native." + language).level is not SupportLevel.SUPPORTED:
        raise _NotAdmitted("Backend profile does not support the required native query interface")
    parameter = "xgap_strategy_entity_bindings"
    namespace_parameter = "xgap_strategy_entity_namespace"
    if {parameter, namespace_parameter, "sparql_iri_binding", "sparql_iri_rows"} & artifact.parameters.keys():
        raise _NotAdmitted("Target artifact has conflicting bind parameters")
    columns = artifact.parameters["output_columns"]
    parameters = dict(artifact.parameters)
    if language == "sparql":
        text = ("SELECT DISTINCT " + " ".join("?" + c for c in columns) + " WHERE {\n"
                + IRI_VALUES_MARKER + "\n{\n" + artifact.text + "\n}\n}")
        parameters["sparql_iri_binding"] = {"parameter": parameter, "variable": identity_column,
            "max_bindings": max_bindings, "max_bytes": max_binding_bytes}
    else:
        names = ", ".join(_cypher_identifier(c) for c in columns)
        native_identity = "entity" if identity_column == "entity" else _cypher_identifier(identity_column)
        text = ("CALL {\n" + artifact.text + "\n}\nWITH " + names
                + "\nWHERE ($" + namespace_parameter + " + " + native_identity + "."
                + _cypher_identifier(backend.identity_property) + ") IN $" + parameter
                + "\nRETURN DISTINCT " + names)
        parameters[namespace_parameter] = backend.resource_namespace
    parameters.update(physical_strategy_profile=STRATEGY_PROFILE,
                      bound_entity_parameter=parameter)
    if compiler == "semantic_edge_match_v1":
        parameters["bound_identity_column"] = identity_column
    return replace(artifact, artifact_id=artifact.artifact_id + "-entity-bind",
                   text=text, parameters=parameters), parameter


def prepare_physical_strategies(program: SemanticGraphProgram, *,
        source_bindings: Mapping[str, str], backends: Mapping[str, SemanticBackend],
        max_remote_calls: int = 16, max_parallelism: int = 4,
        max_bindings: int = 10000, max_binding_bytes: int = 1_048_576) -> PhysicalStrategySpace:
    """Compile the baseline, single binds and at most one anchor fanout.

    The binding-list count is enforced by the existing scheduler. SPARQL also
    enforces max_binding_bytes when serializing VALUES; this byte limit is not
    claimed for the Cypher client. Overflow is an execution failure, never
    truncation, hidden batching, a retry or a fallback plan.

    For J joins and compiled size L, at most 2+2J plans of O(L) size are built.
    Existing bounded-path admission runs before compilation. Apart from that
    compiler, construction/validation/serialization costs O((J+1)L + n^2) with
    cached field lineage, where n is the explicitly represented semantic input.
    One exact anchor normalization adds O(p*n*(n+e)+L) conservative work before
    constructing alternatives, for p predicate atoms and e DAG edges. The fanout
    adds O(n*L + generated query bytes), one candidate and no remote-call slots.
    There is no general join-order or actual-cost guarantee.
    """
    started = time.perf_counter()
    if not isinstance(program, SemanticGraphProgram):
        raise SemanticProgramError("Physical strategy preparation needs a typed semantic program")
    if len(program.operators) > MAX_SEMANTIC_OPERATORS:
        raise SemanticProgramError("Semantic strategy profile admits at most64 operators")
    if len(json.dumps(program.to_dict(), allow_nan=False).encode()) > MAX_PROGRAM_BYTES:
        raise SemanticProgramError("Semantic strategy input exceeds the1MiB program bound")
    for name, value in (("max_bindings", max_bindings), ("max_binding_bytes", max_binding_bytes)):
        if type(value) is not int or value <= 0:
            raise ValueError(name + " must be a positive integer")
    _admit_expansion(program)
    baseline = _with_exchanges(compile_semantic_program(program, source_bindings=source_bindings,
        backends=backends, max_remote_calls=max_remote_calls, max_parallelism=max_parallelism))
    baseline = reduce_scalar_anchor(program, baseline)
    operators = {op.operator_id: op for op in program.operators}
    consumers = Counter(i for op in program.operators for i in op.input_ids)
    joins = sorted((op for op in program.operators if op.kind is S.JOIN), key=lambda op: op.operator_id)
    semantic_key = _digest({"program": program.to_dict(), "source_bindings": dict(source_bindings),
                            "compiled_baseline": baseline.to_dict()})
    is_entity = _entity_lineage(operators, baseline.metadata["schemas"])
    candidates, rejected = [], []
    assumptions = ("Declared snapshots obey existing canonical node identity and scalar mapping contracts",
                   "Fixed source bindings; original hard constraints and answer operators preserved")

    def candidate(strategy_id, plan, details, extra_assumptions=()):
        plan = replace(plan, plan_id=baseline.plan_id + "/" + _digest(strategy_id)[:16],
            metadata={**dict(plan.metadata), "physical_strategy_profile": STRATEGY_PROFILE,
                "physical_strategy": strategy_id, "strategy_details": details,
                "semantic_equivalence_key": semantic_key, "current_query_profile_calls": 0})
        return PhysicalStrategyCandidate(strategy_id, plan, semantic_key,
            strategy_features(plan, program), assumptions + extra_assumptions)

    candidates.append(candidate("coordinator", baseline, {"rewrite_count": 0}))
    anchor = baseline.metadata.get("anchor_reduction")
    if anchor:
        try:
            identity = anchor["identity_field"]
            key_output = anchor["enforcing_filter"] + "/anchor_reduction/keys"
            by_id = {n.node_id: n for n in baseline.nodes}
            replacements = {}
            for target_id in anchor["target_matches"]:
                target = operators[target_id]
                identity_column = next((column for column in ("source", "target")
                    if target.parameters.get(column + "_field", column) == identity), None)
                if identity_column is None:
                    raise _NotAdmitted("Proved anchor is not an edge endpoint identity")
                remote_id = target_id + "/native"
                if depends_on(baseline, key_output, remote_id):
                    raise _NotAdmitted("Anchor fanout would create a cyclic native dependency")
                remote = by_id[remote_id]
                backend = backends[source_bindings[target_id]]
                artifact, parameter = _bound_match_artifact(
                    QueryArtifact.from_dict(remote.parameters["artifact"]), backend,
                    max_bindings=max_bindings, max_binding_bytes=max_binding_bytes,
                    identity_column=identity_column)
                replacements[remote_id] = replace(remote, kind=R.REMOTE_BIND_QUERY,
                    inputs=(key_output,), parameters={**dict(remote.parameters),
                        "artifact": artifact.to_dict(), "bind_field": identity,
                        "parameter": parameter, "max_bindings": max_bindings})
            plan = replace(baseline, nodes=tuple(replacements.get(n.node_id, n) for n in baseline.nodes))
            candidates.append(candidate("anchor_fanout_bind", plan, {
                "rewrite_count": len(replacements), "target_matches": list(anchor["target_matches"]),
                "driver": key_output, "driver_field": identity, "max_bindings": max_bindings,
                "sparql_max_binding_bytes": max_binding_bytes,
                "extra_remote_call_slots": 0, "combination_enumeration": False},
                ("All target uses require an identity in the proved anchor key set",
                 "Key overflow fails explicitly; no partial fanout, truncation, retry or fallback")))
        except _NotAdmitted as error:
            rejected.append({"strategy_id": "anchor_fanout_bind", "reason": str(error)})
    for join in joins:
        for driving_index in (0, 1):
            direction = "left_to_right" if driving_index == 0 else "right_to_left"
            strategy_id = "entity_bind/" + join.operator_id + "/" + direction
            driver_id, target_id = join.input_ids[driving_index], join.input_ids[1-driving_index]
            driver_field = join.parameters["left_on" if driving_index == 0 else "right_on"]
            target_field = join.parameters["right_on" if driving_index == 0 else "left_on"]
            try:
                if not is_entity(driver_id, driver_field):
                    raise _NotAdmitted("Driving join key has no canonical entity-IRI lineage")
                target, chain, identity_column = _target_match(target_id, target_field, operators, consumers, set(program.roots))
                backend = backends[source_bindings[target.operator_id]]
                remote_id = target.operator_id + "/native"
                if depends_on(baseline, baseline.metadata["operator_outputs"][driver_id], remote_id):
                    raise _NotAdmitted("Bind dependency would cycle after exact anchor reduction")
                remote = next(n for n in baseline.nodes if n.node_id == remote_id)
                artifact, parameter = _bound_match_artifact(QueryArtifact.from_dict(remote.parameters["artifact"]),
                    backend, max_bindings=max_bindings, max_binding_bytes=max_binding_bytes,
                    identity_column=identity_column)
                bound = replace(remote, kind=R.REMOTE_BIND_QUERY,
                    inputs=(baseline.metadata["operator_outputs"][driver_id],), parameters={
                        **dict(remote.parameters), "artifact": artifact.to_dict(), "bind_field": driver_field,
                        "parameter": parameter, "max_bindings": max_bindings})
                plan = replace(baseline, nodes=tuple(bound if n.node_id == remote_id else n for n in baseline.nodes))
                candidates.append(candidate(strategy_id, plan, {"rewrite_count": 1, "join": join.operator_id,
                    "driver": driver_id, "driver_field": driver_field, "target_match": target.operator_id,
                    "target_chain": list(chain), "max_bindings": max_bindings,
                    "sparql_max_binding_bytes": max_binding_bytes if artifact.language == "sparql" else None},
                    ("Only target rows with keys present in the driver can affect this exclusive Join branch",
                     "Binding-list overflow fails explicitly; no answer approximation or hidden fallback")))
            except _NotAdmitted as error:
                rejected.append({"strategy_id": strategy_id, "reason": str(error)})
    return PhysicalStrategySpace(tuple(candidates), tuple(rejected),
        (time.perf_counter() - started) * 1000, semantic_key, len(joins), int(bool(anchor)))
