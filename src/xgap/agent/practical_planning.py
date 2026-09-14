"""Strong-policy domain over a trusted bounded semantic skeleton.

Validation records enter through trusted host/provider configuration, never a
model payload. The first release supports named binding holes; interpretation
structure validation and the discrepancy metric are separate research boundaries.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import hashlib
import json

from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.strong_planning import (AcquisitionAlternative, DeclaredOutcome,
    ResourceUsage, TerminalAlternative, _cost)
from xgap.compilers.errors import CompilerError
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.runtime.one_shot_planning import prepare_one_shot_domain
from xgap.runtime.semantic_compiler import compile_semantic_program, compile_semantic_source
from xgap.runtime.semantic_placement import _admit_expansion
from xgap.semantic.binding import bind_semantic_query
from xgap.semantic.program import SemanticOperatorKind as S, hard_constraints_sha256


AUTHORITIES = frozenset({"trusted_request", "frozen_catalog", "validated_mapping",
                         "deterministic_validation", "clarification"})


def program_identity(program):
    return hashlib.sha256(json.dumps(program.to_dict(), sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class BindingEvidence:
    slot: str
    candidate_id: str
    authority: str
    source_id: str
    version: str

    def __post_init__(self):
        if self.authority not in AUTHORITIES or any(not x for x in (self.slot, self.candidate_id, self.source_id, self.version)):
            raise ValueError("Validation needs a trusted scoped authority and version; LLM scores are not authority")


@dataclass(frozen=True)
class BindingState:
    choices: tuple[tuple[str, str], ...] = ()
    evidence: tuple[BindingEvidence, ...] = ()
    attempted_actions: tuple[str, ...] = ()

    def __post_init__(self):
        if len(dict(self.choices)) != len(self.choices) or len({e.slot for e in self.evidence}) != len(self.evidence):
            raise ValueError("Each slot has at most one binding and validation")
        known = dict(self.choices)
        if any(e.slot != "$structure" and known.get(e.slot) != e.candidate_id for e in self.evidence):
            raise ValueError("Evidence must validate the actual selected binding")


@dataclass(frozen=True)
class PracticalMode:
    mode: str = "exact"
    allowed_unvalidated: tuple[str, ...] = ()
    epsilon: float | None = None
    improve_physical: bool = True

    def __post_init__(self):
        if self.mode not in ("exact", "performance"):
            raise ValueError("Practical mode must be exact or performance")
        if self.mode == "exact" and self.allowed_unvalidated:
            raise ValueError("Exact mode does not authorize predicted bindings")
        if self.epsilon is not None:
            raise ValueError("The semantic discrepancy metric is deferred; epsilon certification is unavailable")
        if "$structure" in self.allowed_unvalidated:
            raise ValueError("This release requires a trusted query skeleton in both modes")


@dataclass(frozen=True)
class BindingAction:
    action_id: str
    slot: str
    tool_name: str
    # None is an explicit unknown/unavailable observation, not a success leaf.
    outcomes: tuple[tuple[str, str | None], ...]
    source_id: str
    version: str
    authority: str | None = None
    estimated_ms: float = 1.0
    resources: ResourceUsage = field(default_factory=ResourceUsage)
    outcomes_exhaustive: bool = True

    def __post_init__(self):
        _cost(self.estimated_ms)
        labels = [label for label, _ in self.outcomes]
        candidates = [candidate for _, candidate in self.outcomes if candidate is not None]
        if not labels or any(not label for label in labels) or len(set(labels)) != len(labels) or len(set(candidates)) != len(candidates):
            raise ValueError("Binding actions need distinct labels and unambiguous candidate outcomes")
        if self.authority is not None and self.authority not in AUTHORITIES:
            raise ValueError("An information action cannot self-promote a heuristic to authority")
        if not all((self.action_id, self.slot, self.tool_name, self.source_id, self.version)):
            raise ValueError("Actions require scoped provenance")
        if self.authority is not None and self.resources.model_calls:
            raise ValueError("Model proposal actions cannot produce authoritative validation")


def _baseline(program, operator_sources, sources, backends, profile):
    """Construct one feasible minimum-call placement without a product/domain cap.

    This reuses the existing compiler and independent replica admission. A later
    optional strategy-domain failure cannot erase this executable plan.
    """
    _admit_expansion(program)
    ops = [o for o in program.operators if o.kind in (S.MATCH, S.TRAVERSE)]
    if set(operator_sources) != {o.operator_id for o in ops}:
        raise ValueError("Sources must cover every source operator")
    placement, identities, total, remote = {}, {}, 0, 0
    for op in ops:
        source_id = operator_sources[op.operator_id]
        source = sources[source_id]
        if source.source_id != source_id:
            raise ValueError("Logical source identity mismatch")
        replicas = source.replica_backend_ids
        total += len(replicas)
        if total > profile.max_local_options:
            raise ValueError("Local-option admission bound exceeded")
        if len({backends[b].resource_namespace for b in replicas}) != 1:
            raise ValueError("Replicas require a common identity namespace")
        choices, schemas = [], set()
        for b in sorted(replicas):
            if backends[b].backend_id != b:
                raise ValueError("Backend identity mismatch")
            identity = {"source_id": source_id, "snapshot_version": source.snapshot_version}
            if b in identities and identities[b] != identity:
                raise ValueError("A backend must identify one source snapshot")
            identities[b] = identity
            try:
                fragment = compile_semantic_source(op, backends[b])
                choices.append((fragment.remote_calls, b))
                schemas.add(fragment.schema)
            except (ValueError, CompilerError):
                continue
        if not choices or len(schemas) != 1:
            raise ValueError("No schema-consistent executable local replica")
        calls, placement[op.operator_id] = min(choices)
        remote += calls
    if remote > profile.max_remote_calls:
        raise ValueError("No independent placement fits the remote-call budget")
    plan = compile_semantic_program(program, source_bindings=placement, backends=backends,
        max_remote_calls=profile.max_remote_calls, max_parallelism=profile.max_parallelism)
    used = {n.parameters["backend_id"] for n in plan.nodes if "backend_id" in n.parameters}
    return replace(plan, metadata={**plan.metadata,
        "source_identities": {b: identities[b] for b in used},
        "source_snapshot_versions": {b: identities[b]["snapshot_version"] for b in used},
        "source_bindings": placement, "planning_fallback": "minimum_call_feasible_placement"})


class PracticalSemanticDomain:
    def __init__(self, program, *, operator_sources, binding_values, sources, backends,
                 mode=PracticalMode(), actions=(), predictions=None, estimator=None,
                 physical_profile=OneShotPolicy()):
        if len(program.operators) > physical_profile.max_operators or len(program.holes) > physical_profile.max_holes:
            raise ValueError("Semantic input exceeds its finite profile")
        if physical_profile.retrieval_rows_per_relation is not None:
            raise ValueError("Unbounded-error row truncation is outside this strong-policy release")
        self.program, self.operator_sources, self.binding_values = program, operator_sources, binding_values
        self.sources, self.backends, self.mode = sources, backends, mode
        self.estimator, self.physical_profile = estimator, physical_profile
        self.action_specs = tuple(sorted(actions, key=lambda a: (a.estimated_ms, a.action_id)))
        if len(self.action_specs) > 128 or len({a.action_id for a in self.action_specs}) != len(self.action_specs):
            raise ValueError("At most 128 distinct acquisition actions are admitted")
        self.predictions = dict(predictions or {})
        self.slots = {h.hole_id: h for h in program.holes}
        if not set(mode.allowed_unvalidated) <= self.slots.keys() or not self.predictions.keys() <= self.slots.keys():
            raise ValueError("Unknown unvalidated/predicted slot")
        for action in self.action_specs:
            if action.slot not in self.slots or len(action.outcomes) > 256:
                raise ValueError("Action targets an unknown slot or has too many outcomes")
            for _, candidate in action.outcomes:
                if candidate is not None:
                    self._check_binding(action.slot, candidate)
        for slot, candidate in self.predictions.items():
            self._check_binding(slot, candidate)
        self.failures, self.plan_cache = [], {}
        self.compiled_states = self.estimator_calls = 0

    def _check_binding(self, slot, candidate):
        if slot not in self.slots or candidate not in self.binding_values or self.binding_values[candidate].kind != self.slots[slot].kind:
            raise ValueError("Binding candidate must have the declared slot type")

    def validate_state(self, state):
        evidence = {e.slot: e for e in state.evidence}
        structure = evidence.get("$structure")
        if structure is None or structure.candidate_id != program_identity(self.program):
            raise ValueError("A versioned trusted validation of this query skeleton is required")
        if set(evidence) - self.slots.keys() - {"$structure"}:
            raise ValueError("Validation targets an unknown slot")
        for slot, candidate in state.choices:
            self._check_binding(slot, candidate)

    def _terminal(self, plan, bound, state, unresolved):
        estimate, reason = None, "estimator_unavailable"
        if self.estimator is not None:
            stats = {e.backend_id: e for e in self.estimator.statistics.entries}
            compatible = all(b in stats and (stats[b].source_id, stats[b].snapshot_version) ==
                (v["source_id"], v["snapshot_version"]) for b, v in plan.metadata["source_identities"].items())
            if compatible:
                self.estimator_calls += 1
                try:
                    prediction = self.estimator.predict(plan).to_dict()
                    estimate = prediction.get("estimated_ms") if prediction["status"] == "estimated" else None
                    if estimate is not None:
                        _cost(estimate)
                    reason = prediction["status"]
                except (ValueError, KeyError, TypeError) as error:
                    reason = "estimator_error:" + type(error).__name__
                    estimate = None
            else:
                reason = "estimator_snapshot_mismatch"
        payload = {"query": bound.program.to_dict(), "physical_plan": plan.to_dict(),
            "bindings": dict(bound.bindings), "validation_records": [asdict(e) for e in state.evidence],
            "unvalidated_bindings": list(unresolved), "mode": self.mode.mode,
            "semantic_discrepancy_upper_bound": None, "discrepancy_status": "metric_deferred",
            "semantic_validation": "all_declared_slots" if not unresolved else "authorized_prediction",
            "optimality_certified": False, "estimate_status": reason}
        remote = sum(n.kind in (R.REMOTE_QUERY, R.REMOTE_BIND_QUERY) for n in plan.nodes)
        # Compiler plan IDs may be shared by distinct bindings of one template.
        # The policy terminal must identify its complete query AND evidence.
        identity = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                             allow_nan=False).encode()).hexdigest()
        return TerminalAlternative("practical-terminal:" + identity, estimate, payload, ResourceUsage(remote_calls=remote))

    def terminals(self, state):
        self.validate_state(state)
        values = dict(state.choices)
        validated = {e.slot for e in state.evidence}
        unresolved = tuple(slot for slot in self.slots if slot not in validated)
        if unresolved and (self.mode.mode == "exact" or not set(unresolved) <= set(self.mode.allowed_unvalidated)):
            return
        for slot in self.slots:
            if slot not in values:
                if slot not in self.predictions:
                    return
                values[slot] = self.predictions[slot]
        key = (tuple(sorted(values.items())), state.evidence)
        if key in self.plan_cache:
            yield from self.plan_cache[key]
            return
        resolution = {"program_id": self.program.program_id,
            "hard_constraints_sha256": hard_constraints_sha256(self.program), "hard_constraints_preserved": True,
            "candidate_sets": [{"hole_id": slot, "candidate_ids": [candidate],
                "authoritative": slot in validated, "selection_policy": "predicted_catalog_choice",
                "sources": [e.source_id for e in state.evidence if e.slot == slot]} for slot, candidate in values.items()]}
        try:
            bound = bind_semantic_query(self.program, resolution, binding_values=self.binding_values,
                operator_sources=self.operator_sources, allow_predicted_entities=self.mode.mode == "performance")
            baseline = _baseline(bound.program, bound.operator_sources, self.sources, self.backends, self.physical_profile)
        except (ValueError, KeyError, CompilerError) as error:
            self.failures.append({"bindings": values, "stage": "baseline", "error": str(error)})
            return
        self.compiled_states += 1
        seed = self._terminal(baseline, bound, state, unresolved)
        self.plan_cache[key] = (seed,)
        yield seed  # A legal fallback survives unknown estimates/strategy-domain caps.
        if not self.mode.improve_physical:
            return
        try:
            alternatives, _ = prepare_one_shot_domain(bound.program, operator_sources=bound.operator_sources,
                sources=self.sources, backends=self.backends, policy=self.physical_profile,
                progressive_bindings=True)
            scored = [self._terminal(c.plan, bound, state, unresolved) for c in alternatives]
            best = min([seed, *scored], key=lambda t: (t.estimated_cost is None, t.estimated_cost or 0))
            self.plan_cache[key] = (seed, best)
            yield best
        except (ValueError, KeyError, CompilerError) as error:
            self.failures.append({"bindings": values, "stage": "optional_physical_improvement", "error": str(error)})

    def actions(self, state):
        validated = {e.slot for e in state.evidence}
        for spec in self.action_specs:
            if spec.slot in validated or spec.action_id in state.attempted_actions:
                continue
            outcomes = []
            for label, candidate in spec.outcomes:
                choices, evidence = dict(state.choices), list(state.evidence)
                if candidate is not None:
                    choices[spec.slot] = candidate
                    if spec.authority is not None:
                        evidence.append(BindingEvidence(spec.slot, candidate, spec.authority, spec.source_id, spec.version))
                child = BindingState(tuple(sorted(choices.items())), tuple(evidence),
                                     (*state.attempted_actions, spec.action_id))
                outcomes.append(DeclaredOutcome(label, child))
            yield AcquisitionAlternative(spec.action_id, spec.tool_name,
                {"action_id": spec.action_id, "slot": spec.slot,
                 "program_sha256": program_identity(self.program),
                 "candidates": [v for _, v in spec.outcomes if v is not None],
                 "source_id": spec.source_id, "version": spec.version},
                tuple(outcomes), spec.estimated_ms, spec.resources, spec.outcomes_exhaustive)
