"""Finite-family adapter for the guarded online planner, with protected seed plans.

This admission uses existing known capabilities and static seed plans. It does
not claim that live metadata/probes or single physical transformations are wired
yet. Those share the generic action protocol but need separate real admissions.
"""
from dataclasses import asdict, dataclass, replace
import json
import time

from xgap.agent.intent_certificate import canonical, fingerprint, rational
from xgap.agent.unified_contract import UnifiedTerminalContract, ValidationRequirement, ValidatedBinding
from xgap.agent.unified_lookahead import Action, ActionFailure, Completion, Limits, Observation, Outcome, Resources, Terminal, run_online
from xgap.runtime.contracts import RuntimeNodeKind
from xgap.tools import ToolRegistry
from xgap.tools.contracts import ToolContext, ToolStatus


@dataclass(frozen=True)
class UnifiedSettings:
    epsilon: str = '0'
    relaxable: tuple[str, ...] = ()
    limits: Limits = Limits()

    def __post_init__(self):
        rational(self.epsilon)
        if (not isinstance(self.relaxable, tuple) or len(self.relaxable) > 64
                or len(set(self.relaxable)) != len(self.relaxable)
                or any(not isinstance(x, str) or not x for x in self.relaxable)
                or not isinstance(self.limits, Limits)):
            raise ValueError('Lambda must list distinct declared requirement names')


@dataclass(frozen=True)
class FamilyState:
    bindings: tuple[ValidatedBinding, ...] = ()


class FamilyDomain:
    def __init__(self, question, contract, seeds, costs, *, authority_name, authority_version):
        self.question, self.contract, self.seeds, self.costs = question, contract, dict(seeds), costs
        self.authority_name, self.authority_version = authority_name, authority_version
        self.names = tuple(r.name for r in contract.requirements)

    def key(self, state):
        return fingerprint([self.contract.identity, [asdict(b) for b in state.bindings]])

    def knowledge_key(self, state):
        return fingerprint([self.contract.identity,
            [(b.name, b.value_json, b.source, b.version) for b in state.bindings]])

    def valid(self, state):
        try:
            return self.contract.family.coverage_basis is not None and bool(self.contract.consistent(state.bindings))
        except ValueError:
            return False

    def updated(self, state, names, answers):
        request = self.arguments(names)
        receipt = fingerprint([request, answers, self.authority_version])
        known = {b.name: b for b in state.bindings}
        for name in names:
            known[name] = ValidatedBinding(name, canonical(answers[name]), self.authority_name,
                                          self.authority_version, receipt)
        return FamilyState(tuple(known[n] for n in sorted(known)))

    def arguments(self, names):
        return dict(family_sha256=self.contract.family.identity, question_sha256=fingerprint(self.question), slots=list(names))

    def action(self, state, names):
        names = tuple(sorted(names))
        args = self.arguments(names)
        groups = {}
        for i in self.contract.consistent(state.bindings):
            answers = {n: json.loads(self.contract.values[i][n]) for n in names}
            label = fingerprint(answers)
            response_bytes = len(canonical({**args, 'answers': answers}).encode())
            groups[label] = Outcome(label, self.updated(state, names, answers), self.costs.information(names),
                                    Resources(user_calls=1, bytes=response_bytes, peak_bytes=None))
        # This adapter has no admitted probability model. The generic planner
        # supports one, but must not invent a uniform distribution here.
        return Action('validate:'+','.join(names), 'binding', tuple(groups[k] for k in sorted(groups)), args)

    def actions(self, state):
        unknown = tuple(n for n in self.names if n not in {b.name for b in state.bindings})
        if unknown:
            scopes = tuple(dict.fromkeys((unknown, *((n,) for n in unknown))))
            return tuple(self.action(state, names) for names in scopes)
        return ()

    def terminals(self, state):
        results = []
        for i in self.contract.consistent(state.bindings):
            if i not in self.seeds:
                continue
            cert = self.contract.check(i, state.bindings)
            if cert['eligible']:
                plan, estimate, resources = self.seeds[i]
                results.append(Terminal(self.contract.family.candidates[i].candidate_id+':'+plan.plan_id,
                    estimate, resources, dict(candidate_index=i, certificate=cert, plan=plan)))
        return tuple(sorted(results, key=lambda t: (t.estimated_cost, t.key)))

    def completion(self, state):
        if not self.valid(state):
            return None
        terminals = self.terminals(state)
        if terminals:
            first = terminals[0]
            return Completion('execute:'+first.key, self.key(state), 0, first.resources,
                              (('execution', first.estimated_cost),), first)
        remaining = self.contract.consistent(state.bindings)
        unknown = tuple(n for n in self.names if n not in {b.name for b in state.bindings})
        if not unknown or any(i not in self.seeds for i in remaining):
            return None
        first = self.action(state, unknown)
        # A linear scan of the explicit family proves every full disclosure
        # yields a certified retained seed. No recursive policy search.
        costs, bounds = [], []
        for outcome in first.outcomes:
            eligible = self.terminals(outcome.payload)
            if not eligible:
                return None
            selected = eligible[0]
            costs.append(selected.estimated_cost)
            bounds.append(outcome.resources.then(selected.resources))
        values = {}
        for name in asdict(Resources()):
            values[name] = None if any(getattr(b, name) is None for b in bounds) else max(getattr(b, name) for b in bounds)
        return Completion('full-validate:'+self.key(state), self.key(state), 1, Resources(**values),
                          (('required_validation', self.costs.information(unknown)), ('execution', max(costs))), first)

    def verify_completion(self, state, witness):
        # This is a direct reconstruction of the fixed one-step recipe over N
        # candidates, not recursive completion or enumeration over horizon H.
        return witness == self.completion(state)


def run_unified_family(question, family, user, *, prepare_seed, execute, costs, settings=UnifiedSettings(),
                       on_observation=None, estimator=None):
    started = time.perf_counter()
    requirements = tuple(ValidationRequirement(s.name, s.path, user.spec.name, family.identity) for s in family.slots)
    contract = UnifiedTerminalContract(family, requirements, relaxable=settings.relaxable, epsilon=settings.epsilon)
    if settings.limits.aggregation != 'max':
        raise ValueError('Family adapter has no declared outcome distribution; expectation is unavailable')
    seeds, failures = {}, []
    for i, candidate in enumerate(family.candidates):
        try:
            plan = prepare_seed(candidate, None)
            # Seed admission has one adapter invocation per REMOTE_QUERY node.
            # Batched/bind plans need their own proved call bound before admission.
            if any(n.kind is RuntimeNodeKind.REMOTE_BIND_QUERY for n in plan.nodes):
                raise ValueError('Seed binding calls lack an admitted completion resource proof')
            calls = sum(n.kind is RuntimeNodeKind.REMOTE_QUERY for n in plan.nodes)
            estimate, _ = costs.execution(plan, estimator)
            seeds[i] = (plan, estimate, Resources(remote_calls=calls, bytes=None, peak_bytes=None))
        except (ValueError, TypeError, KeyError) as error:
            failures.append(dict(candidate_id=candidate.candidate_id, error_type=type(error).__name__, error=str(error)))
    initialization_ms = (time.perf_counter()-started)*1000
    domain = FamilyDomain(question, contract, seeds, costs, authority_name=user.spec.name, authority_version=family.identity)
    registry = ToolRegistry()
    registry.register(user)
    actual = FamilyState()
    receipts = []

    def perform(action):
        nonlocal actual
        result = registry.invoke(user.spec.name, action.arguments, ToolContext('unified-family', len(receipts), str(len(receipts))))
        record = dict(action_id=action.key, request=action.arguments, response=result.to_dict())
        receipts.append(record)
        if on_observation is not None:
            on_observation(record)
        if result.status is not ToolStatus.SUCCESS:
            raise ActionFailure('Authoritative binding request failed',
                                Resources(user_calls=1, bytes=result.metrics.get('reply_bytes'), peak_bytes=None), record)
        reply = result.value
        if (not isinstance(reply, dict) or set(reply) != {*action.arguments, 'answers'}
                or any(reply[k] != v for k, v in action.arguments.items())
                or not isinstance(reply['answers'], dict) or set(reply['answers']) != set(action.arguments['slots'])):
            raise ValueError('Malformed authoritative reply or scope/version mismatch')
        actual = domain.updated(actual, action.arguments['slots'], reply['answers'])
        return Observation(fingerprint(reply['answers']), actual,
                           Resources(user_calls=1, bytes=result.metrics.get('reply_bytes'), peak_bytes=None), record)

    def dispatch(terminal):
        cert = contract.check(terminal.payload['candidate_index'], actual.bindings)
        if not cert['eligible']:
            raise ValueError('Actual validation and loss contract no longer permits execution')
        return execute(terminal.payload['plan'])

    result = run_online(actual, domain, perform=perform, execute=dispatch, limits=settings.limits)
    selected = (next((t for t in domain.terminals(actual) if t.key == result.get('selected_terminal')), None)
                if result['success'] and domain.valid(actual) else None)
    result.update(clarification_calls=len(receipts), ledger=receipts, initialization_ms=initialization_ms,
                  physical_prepare_attempts=len(family.candidates), preparation_failures=failures,
                  terminal_certificate=selected.payload['certificate'] if selected else None,
                  certificate_checks=contract.checks, model_calls=0,
                  disclosed_coordinates=sum(r['response'].get('metrics', {}).get('disclosed_coordinates', 0) for r in receipts),
                  backend_remote_calls=result.get('execution', {}).get('result', {}).get('metrics', {}).get('remote_calls'),
                  adapter_end_to_end_ms=(time.perf_counter()-started)*1000,
                  resource_scope='online phase after initialization; remote_calls are runtime adapter invocations; bytes/peak unknown',
                  action_scope='authoritative validation and execution; known-capability protected seeds only')
    return result
