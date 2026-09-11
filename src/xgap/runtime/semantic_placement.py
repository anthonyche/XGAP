"""Polynomial local-option placement, with model-relative quality certificates.

The exhaustive generator is deliberately not imported. Native fragments are
compiled once per operator/backend; assembling and scoring a plan is polynomial.
See docs/decisions/planning_ptime_contract_v1.md for assumptions and proofs.
"""

from dataclasses import dataclass, replace
import math
import time

from xgap.compilers.errors import CompilerError
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.runtime.planning import FederatedPlanSelector
from xgap.runtime.semantic_compiler import compile_semantic_program, compile_semantic_source
from xgap.runtime.semantic_planning import _hash, _instrument_semantic_plan, select_static_semantic_plan
from xgap.semantic.program import SemanticOperatorKind as S, SemanticProgramError
from xgap.tools.backends import BackendObservationCatalog
from xgap.llm.parser import parse_path_pattern_query
from xgap.pattern.ast import Alt, Bounded, OptionalExpr, Plus, Rel, Seq, Star
from xgap.pattern.semantic_validation import type_check_semantic_path_pattern


MAX_LOCAL_EXPANSION_WORK = 4096


def _admit_expansion(program):
    """Bound compact repetition before any lowerer can loop over binary counts.

    This is a declared compiler-input profile, not a placement-search cutoff.
    No semantic expression is truncated or rewritten to pass the profile.
    """
    def work(expr, depth):
        if isinstance(expr, Rel):
            result = 1
        elif isinstance(expr, (Seq, Alt)):
            result = 1 + work(expr.left, depth) + work(expr.right, depth)
        elif isinstance(expr, OptionalExpr):
            result = 1 + work(expr.child, depth)
        elif isinstance(expr, (Bounded, Plus, Star)):
            maximum = expr.max_repeats if isinstance(expr, Bounded) and expr.max_repeats is not None else depth
            if type(maximum) is not int or maximum < 0:
                raise SemanticProgramError("Polynomial path planning requires explicit finite repetition")
            result = 1 if maximum == 0 else 1 + (maximum + 1) * work(expr.child, depth)
        else:
            raise SemanticProgramError("Unknown path expression in polynomial planning")
        if result > MAX_LOCAL_EXPANSION_WORK:
            raise SemanticProgramError("Compact path expansion exceeds the polynomial compiler-input profile (4096)")
        return result
    for op in program.operators:
        if op.kind is S.TRAVERSE:
            query = parse_path_pattern_query(op.parameters["path_pattern"])
            type_check_semantic_path_pattern(query)
            work(query.expr, query.max_depth)


_COST_PARAMETERS = ("join_selectivity", "semi_join_selectivity", "group_reduction_fraction",
                    "allow_global", "group_by", "limit", "output_row_fraction", "width_fraction",
                    "operation", "max_depth")


def _cost_shape(plan):
    return tuple(sorted((n.node_id, n.kind.value, n.inputs,
        _hash({k: n.parameters[k] for k in _COST_PARAMETERS if k in n.parameters}))
        for n in plan.nodes))


def _score_key(estimate):
    return (estimate.predicted_latency_ms, estimate.predicted_transfer_bytes,
            estimate.remote_calls, estimate.plan_id)


@dataclass
class PolynomialSemanticPlanSpace:
    program: object
    backends: dict
    identities: dict
    equivalence_key: str
    fragments: dict
    options: dict
    baseline: object
    observation_requests: tuple
    observation_catalogs: dict
    rejected_placements: tuple
    enumeration_ms: float
    max_remote_calls: int
    max_parallelism: int
    local_nodes: dict
    same_cost_topology: bool

    @property
    def candidates(self):
        # Compatibility with observation collection: this is just the incumbent,
        # never a materialized Cartesian candidate space.
        return (self.baseline,)

    @property
    def local_option_count(self):
        return sum(map(len, self.options.values()))

    @property
    def possible_placement_count(self):
        # A domain upper bound: remote-call budgets may rule out combinations.
        return math.prod(map(len, self.options.values()))

    def memory_context(self):
        return {"schema": "polynomial-semantic-placement-v1", "program": self.program.to_dict(),
            "identities": self.identities, "options": self.options,
            "limits": [self.max_remote_calls, self.max_parallelism],
            "compiler_expansion_work_limit": MAX_LOCAL_EXPANSION_WORK,
            "fragments": [{"operator": op, "backend": backend, "output": fragment.output,
                "nodes": [n.to_dict() for n in fragment.nodes]}
                for (op, backend), fragment in sorted(self.fragments.items())]}

    def compile(self, placement):
        plan = compile_semantic_program(self.program, source_bindings=placement,
            backends=self.backends, max_remote_calls=self.max_remote_calls,
            max_parallelism=self.max_parallelism, _source_cache=self.fragments)
        return _instrument_semantic_plan(plan, self.identities, self.equivalence_key)[0]

    def static_select(self, backend_order):
        # Validate priority over the full local domain, not just the chosen plan.
        if (not isinstance(backend_order, tuple) or not backend_order
                or any(not isinstance(b, str) or not b.strip() for b in backend_order)
                or len(set(backend_order)) != len(backend_order)
                or not {b for opts in self.options.values() for b in opts} <= set(backend_order)):
            raise ValueError("Static priority must uniquely cover all admitted backends")
        priority = {b: i for i, b in enumerate(backend_order)}
        placement = self._budget_feasible_priority(priority)
        candidate = self.compile(placement)
        return candidate, select_static_semantic_plan((candidate,), backend_order)

    def _budget_feasible_priority(self, priority):
        minimum = {op: min(self.fragments[op, b].remote_calls for b in opts)
                   for op, opts in self.options.items()}
        remaining, used, placement = sum(minimum.values()), 0, {}
        for op, opts in self.options.items():
            remaining -= minimum[op]
            chosen = next(b for b in sorted(opts, key=lambda b: (priority[b], b))
                          if used + self.fragments[op, b].remote_calls + remaining <= self.max_remote_calls)
            placement[op] = chosen
            used += self.fragments[op, chosen].remote_calls
        return placement

    def _remote_alternatives(self, node):
        op = node.semantic_operator_ids[0]
        return [next(n for n in self.local_nodes[op, b] if n.node_id == node.node_id)
                for b in self.options[op]]

    def _lower_bound(self, snapshot):
        if not self.same_cost_topology:
            return None, "local alternatives change the cost DAG topology/parameters"
        estimates = dict(snapshot.by_key)
        for node in self.baseline.plan.nodes:
            if node.kind is not R.REMOTE_QUERY:
                continue
            alternatives = [snapshot.by_key[n.parameters["observation_key"]]
                            for n in self._remote_alternatives(node)]
            key = node.parameters["observation_key"]
            # Repeated observation keys may occur at multiple homologous nodes;
            # taking an additional minimum remains a valid optimistic relaxation.
            values = [estimates[key], *alternatives]
            estimates[key] = replace(estimates[key], elapsed_ms=min(e.elapsed_ms for e in values),
                row_count=min(e.row_count for e in values),
                row_width_bytes=min(e.row_width_bytes for e in values))
        relaxed = replace(snapshot, estimates=tuple(estimates.values()))
        return FederatedPlanSelector().estimate(self.baseline.plan, relaxed).predicted_latency_ms, None

    def _separable(self, snapshot):
        if not self.same_cost_topology:
            return False
        source_ids = set(self.options)
        if any(op.input_ids for op in self.program.operators if op.operator_id in source_ids):
            return False
        # Every independent combination must fit the execution-call budget.
        if sum(max(self.fragments[op, b].remote_calls for b in opts)
               for op, opts in self.options.items()) > self.max_remote_calls:
            return False
        consumed = {input_id for op in self.program.operators for input_id in op.input_ids}
        for node in self.baseline.plan.nodes:
            # Terminal fragments include all their row/width-dependent work in
            # their local readiness. Only consumed outputs can change downstream
            # durations. A source may be both a root and another operator's input.
            if node.kind is R.REMOTE_QUERY and node.semantic_operator_ids[0] in consumed:
                values = [snapshot.by_key[n.parameters["observation_key"]]
                          for n in self._remote_alternatives(node)]
                if len({(e.row_count, e.row_width_bytes) for e in values}) != 1:
                    return False
        return True

    def select(self, snapshot):
        for request in self.observation_requests:
            estimate = snapshot.by_key.get(request.observation_key)
            if estimate is None or estimate.backend_id != request.backend_id:
                raise ValueError("Polynomial planning needs every admitted local observation")
        selector = FederatedPlanSelector()
        evaluated = {}

        def evaluate(candidate):
            if candidate.plan.plan_id not in evaluated:
                evaluated[candidate.plan.plan_id] = selector.estimate(candidate.plan, snapshot)
            return evaluated[candidate.plan.plan_id]

        incumbent = self.baseline
        baseline_score = evaluate(incumbent)
        local_evaluations = 0
        exact = self._separable(snapshot)
        if exact:
            placement = {}
            for op, opts in self.options.items():
                scores = []
                for b in opts:
                    local_plan = replace(self.baseline.plan, plan_id=f"local:{op}:{b}",
                        nodes=self.local_nodes[op, b], roots=(self.fragments[op, b].output,), metadata={})
                    scores.append((selector.estimate(local_plan, snapshot).predicted_latency_ms, b))
                    local_evaluations += 1
                placement[op] = min(scores)[1]
            candidate = self.compile(placement)
            # The primary objective is exact; preserve the incumbent on an
            # equal-primary but worse secondary score.
            if _score_key(evaluate(candidate)) < _score_key(evaluate(incumbent)):
                incumbent = candidate
        else:
            for _ in range(2):
                for op, opts in self.options.items():
                    best = incumbent
                    for b in opts:
                        placement = {**incumbent.plan.metadata["source_bindings"], op: b}
                        if sum(self.fragments[i, target].remote_calls for i, target in placement.items()) > self.max_remote_calls:
                            continue
                        candidate = self.compile(placement)
                        if _score_key(evaluate(candidate)) < _score_key(evaluate(best)):
                            best = candidate
                    incumbent = best
        upper = evaluate(incumbent).predicted_latency_ms
        lower, reason = self._lower_bound(snapshot)
        if exact:
            lower, reason = upper, None
        if lower is not None and lower > upper:
            raise ValueError("Computed planning lower bound exceeds the feasible upper bound")
        certificate = {"objective": "estimated_critical_path_ms", "actual_latency_bound": False,
            "kind": "exact_separable" if exact else ("instance_gap" if lower is not None else "baseline_only"),
            "lower_bound_ms": lower, "upper_bound_ms": upper,
            "baseline_ms": baseline_score.predicted_latency_ms,
            "additive_gap_ms": upper - lower if lower is not None else None,
            "ratio_bound": upper / lower if lower else (1.0 if lower == upper == 0 else None),
            "unavailable_reason": reason, "full_local_domain_covered": lower is not None,
            "constant_factor_claim": False}
        return incumbent, {"semantic_equivalence_key": self.equivalence_key,
            "selected_plan_id": incumbent.plan.plan_id,
            "snapshot_id": snapshot.snapshot_id, "snapshot_version": snapshot.version,
            "estimates": [e.to_dict() for e in evaluated.values()],
            "algorithm": "independent_source_minimum" if exact else "coordinate_two_passes",
            "evaluated_plan_count": len(evaluated), "local_score_evaluations": local_evaluations,
            "evaluation_bound": 2 if exact else 1 + 2 * self.local_option_count,
            "total_score_evaluation_bound": self.local_option_count + 2 if exact else 1 + 2 * self.local_option_count,
            "certificate": certificate}


def prepare_semantic_placements(program, *, operator_sources, sources, backends,
        max_local_options=64, max_observation_calls=128, max_remote_calls=16, max_parallelism=4):
    started = time.perf_counter()
    for value in (max_local_options, max_observation_calls, max_remote_calls, max_parallelism):
        if type(value) is not int or value <= 0:
            raise ValueError("Polynomial placement budgets must be positive integers")
    if program.holes:
        raise SemanticProgramError("Resolve semantic holes before placement")
    _admit_expansion(program)
    source_ops = sorted((op for op in program.operators if op.kind in (S.MATCH, S.TRAVERSE)),
                        key=lambda op: op.operator_id)
    if set(operator_sources) != {op.operator_id for op in source_ops}:
        raise SemanticProgramError("Logical source bindings must cover every Match/Traverse exactly")
    identities, domains = {}, {}
    for op in source_ops:
        source_id = operator_sources[op.operator_id]
        source = sources.get(source_id)
        if source is None or source.source_id != source_id:
            raise SemanticProgramError(f"Unknown logical source for {op.operator_id}")
        opts = tuple(sorted(source.replica_backend_ids))
        if any(b not in backends or backends[b].backend_id != b for b in opts):
            raise SemanticProgramError("Every replica needs matching backend configuration")
        if len({backends[b].resource_namespace for b in opts}) != 1:
            raise SemanticProgramError("Equivalent replicas must share an identity namespace")
        domains[op.operator_id] = opts
        identities[op.operator_id] = {"source_id": source_id, "snapshot_version": source.snapshot_version}
    if sum(map(len, domains.values())) > max_local_options:
        raise SemanticProgramError("Local placement options exceed the declared local-option budget")
    fragments, options, rejected = {}, {}, []
    for op in source_ops:
        admitted = []
        for b in domains[op.operator_id]:
            try:
                fragments[op.operator_id, b] = compile_semantic_source(op, backends[b])
                admitted.append(b)
            except (ValueError, CompilerError) as error:
                rejected.append({"operator": op.operator_id, "backend": b, "reason": str(error)})
        if not admitted:
            raise SemanticProgramError(f"No executable local option for {op.operator_id}: {rejected}")
        if len({fragments[op.operator_id, b].schema for b in admitted}) != 1:
            raise SemanticProgramError("Replica options disagree on the semantic output schema")
        options[op.operator_id] = tuple(admitted)
    minima = {op: min(fragments[op, b].remote_calls for b in opts) for op, opts in options.items()}
    if sum(minima.values()) > max_remote_calls:
        raise SemanticProgramError("No placement fits the execution-call budget")
    for op, opts in options.items():
        options[op] = tuple(b for b in opts if fragments[op, b].remote_calls
                            + sum(minima.values()) - minima[op] <= max_remote_calls)
        for b in set(opts) - set(options[op]):
            rejected.append({"operator": op, "backend": b, "reason": "cannot fit execution-call budget"})
            del fragments[op, b]
    placement = {op: min(opts, key=lambda b: (fragments[op, b].remote_calls, b)) for op, opts in options.items()}
    equivalence = _hash({"program": program.to_dict(), "logical_sources": identities})
    space = PolynomialSemanticPlanSpace(program, backends, identities, equivalence, fragments,
        options, None, (), {}, tuple(rejected), 0.0, max_remote_calls, max_parallelism, {}, True)
    space.baseline = space.compile(placement)
    base_shape = _cost_shape(space.baseline.plan)
    artifacts, requests = {}, {}
    # At most K representative plans cover every native local option. The rest
    # of each plan comes from the feasible minimum-call baseline.
    for op, opts in options.items():
        for b in opts:
            raw = compile_semantic_program(program, source_bindings={**placement, op: b}, backends=backends,
                max_remote_calls=max_remote_calls, max_parallelism=max_parallelism, _source_cache=fragments)
            candidate, found, needed = _instrument_semantic_plan(raw, identities, equivalence)
            space.same_cost_topology &= _cost_shape(candidate.plan) == base_shape
            space.local_nodes[op, b] = tuple(n for n in candidate.plan.nodes if op in n.semantic_operator_ids)
            for backend, queries in found.items():
                artifacts.setdefault(backend, {}).update(queries)
            requests.update(needed)
    if len(requests) > max_observation_calls:
        raise SemanticProgramError("Local observations exceed the finite observation budget")
    space.observation_requests = tuple(requests[k] for k in sorted(requests))
    space.observation_catalogs = {b: BackendObservationCatalog("semantic-native-observations", equivalence,
        query_artifacts=queries) for b, queries in artifacts.items()}
    space.enumeration_ms = (time.perf_counter() - started) * 1000
    return space
