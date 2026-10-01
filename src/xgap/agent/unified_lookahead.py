"""Pure fixed-depth lookahead with constructive completion reservations.

Domain methods are bounded local calculations. Only run_online's perform and
execute callbacks may cause effects. A domain's completion certificate is a
trusted, domain-specific polynomial proof, not a searched full policy tree.
"""
from dataclasses import asdict, dataclass, field
import math
import time


RESOURCE_NAMES = ('user_calls', 'model_calls', 'tokens', 'remote_calls', 'bytes', 'peak_bytes')


@dataclass(frozen=True)
class Resources:
    user_calls: int | None = 0
    model_calls: int | None = 0
    tokens: int | None = 0
    remote_calls: int | None = 0
    bytes: int | None = 0
    peak_bytes: int | None = 0

    def __post_init__(self):
        if any(v is not None and (type(v) is not int or not 0 <= v <= 2**63-1)
               for v in asdict(self).values()):
            raise ValueError('Resources require bounded nonnegative integers or explicit unknown')

    def then(self, other):
        values = {}
        for name in RESOURCE_NAMES:
            a, b = getattr(self, name), getattr(other, name)
            values[name] = None if a is None or b is None else max(a, b) if name == 'peak_bytes' else a+b
        return Resources(**values)

    def fits(self, bounds):
        return all(getattr(bounds, name) is None or
                   getattr(self, name) is not None and getattr(self, name) <= getattr(bounds, name)
                   for name in RESOURCE_NAMES)


UNBOUNDED = Resources(**{name: None for name in RESOURCE_NAMES})


def cost(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('Cost must be a finite nonnegative estimate in the common units')


@dataclass(frozen=True)
class Terminal:
    key: str
    estimated_cost: float
    resources: Resources
    payload: object = None

    def __post_init__(self):
        cost(self.estimated_cost)
        if not self.key:
            raise ValueError('Terminal identity required')


@dataclass(frozen=True)
class Outcome:
    label: str
    payload: object
    estimated_cost: float
    resources: Resources = field(default_factory=Resources)
    probability: float | None = None

    def __post_init__(self):
        cost(self.estimated_cost)
        if not self.label:
            raise ValueError('Outcome label required')
        if self.probability is not None:
            cost(self.probability)
            if self.probability > 1:
                raise ValueError('Probability exceeds one')


@dataclass(frozen=True)
class Action:
    key: str
    kind: str
    outcomes: tuple[Outcome, ...]
    arguments: object = None
    exhaustive: bool = True
    retry_limit: int = 1

    def __post_init__(self):
        if (not self.key or self.kind not in ('binding', 'metadata', 'probe', 'transform')
                or not isinstance(self.outcomes, tuple) or not self.outcomes
                or len({o.label for o in self.outcomes}) != len(self.outcomes)
                or type(self.exhaustive) is not bool or type(self.retry_limit) is not int
                or not 1 <= self.retry_limit <= 32):
            raise ValueError('Invalid bounded action contract')


@dataclass(frozen=True)
class Completion:
    key: str
    state_key: str
    remaining_steps: int
    resources: Resources
    costs: tuple[tuple[str, float], ...]
    first: Action | Terminal

    def __post_init__(self):
        if (not self.key or not self.state_key or type(self.remaining_steps) is not int
                or not 0 <= self.remaining_steps <= 64 or not self.costs
                or len({k for k, _ in self.costs}) != len(self.costs)
                or isinstance(self.first, Terminal) != (self.remaining_steps == 0)):
            raise ValueError('Invalid compact completion witness')
        for _, value in self.costs:
            cost(value)

    @property
    def estimated_cost(self):
        return math.fsum(v for _, v in self.costs)


@dataclass(frozen=True)
class Limits:
    depth: int = 1
    horizon: int = 16
    max_states: int = 4096
    max_actions: int = 128
    max_outcomes: int = 64
    max_terminals: int = 64
    optional_ms: float = 1000.0
    aggregation: str = 'max'
    resources: Resources = UNBOUNDED

    def __post_init__(self):
        for name, lo, hi in (('depth', 1, 10), ('horizon', 0, 64), ('max_states', 1, 8192),
                             ('max_actions', 1, 256), ('max_outcomes', 1, 1024), ('max_terminals', 1, 4096)):
            if type(getattr(self, name)) is not int or not lo <= getattr(self, name) <= hi:
                raise ValueError('Invalid fixed-depth/representation limit: '+name)
        cost(self.optional_ms)
        if self.aggregation not in ('max', 'expectation'):
            raise ValueError('Choose one aggregation rule for the request')


@dataclass(frozen=True)
class State:
    payload: object
    steps: int = 0
    used: Resources = field(default_factory=Resources)
    attempts: tuple = ()

    def __post_init__(self):
        if type(self.steps) is not int or not 0 <= self.steps <= 65 or not isinstance(self.used, Resources):
            raise ValueError('State needs bounded actual action count and resources')
        if (not isinstance(self.attempts, tuple) or len(self.attempts) > 64
                or len(dict(self.attempts)) != len(self.attempts)
                or any(not isinstance(k, tuple) or len(k) != 2
                       or any(not isinstance(x, str) or not x for x in k)
                       or type(v) is not int or not 1 <= v <= 32 for k, v in self.attempts)):
            raise ValueError('Invalid bounded no-progress attempt ledger')


@dataclass(frozen=True)
class Observation:
    label: str
    payload: object
    used: Resources
    evidence: object = None


class SearchLimit(Exception):
    pass


class ActionFailure(Exception):
    """A failed actual tool call can still supply authoritative spend evidence."""
    def __init__(self, message, used, evidence=None):
        super().__init__(message)
        self.used, self.evidence = used, evidence


def choose(state, domain, *, limits=Limits(), clock=time.perf_counter, action_objective='continuation'):
    """Return one action plus checked immediate completion tails, not a full tree.

    Required domain methods: valid, key, knowledge_key, terminals, actions,
    completion, verify_completion. All must be polynomial local functions with
    the declared input bounds. verify_completion must certify the ENTIRE compact
    routine using domain rules, not recursively call this search.
    """
    started = clock()
    if action_objective not in ('continuation','myopic'):raise ValueError('Unknown action objective')
    semantic_phase = bool(getattr(domain,'semantic_only',lambda s:False)(state.payload))
    def terminal_price(t):
        return 0.0 if semantic_phase else t.estimated_cost
    def completion_price(w):
        return sum(value for name,value in w.costs if name!='execution') if semantic_phase else w.estimated_cost
    records = []
    expanded = 0
    stop = 'completed'

    def bounded(items, cap):
        found = []
        for item in items:
            if len(found) == cap:
                raise SearchLimit('representation_limit')
            found.append(item)
        return found

    def witness(s):
        if not domain.valid(s.payload) or s.steps > limits.horizon or not s.used.fits(limits.resources):
            return None
        w = domain.completion(s.payload)
        if (w is None or w.state_key != domain.key(s.payload)
                or not domain.verify_completion(s.payload, w)
                or s.steps+w.remaining_steps > limits.horizon
                or not s.used.then(w.resources).fits(limits.resources)):
            return None
        return w

    def successors(s, action):
        if not action.exhaustive or len(action.outcomes) > limits.max_outcomes:
            return None, 'nonexhaustive_or_oversized_outcomes'
        if limits.aggregation == 'expectation' and (
                any(o.probability is None for o in action.outcomes)
                or not math.isclose(math.fsum(o.probability for o in action.outcomes), 1, abs_tol=1e-12, rel_tol=0)):
            return None, 'missing_or_invalid_probability_model'
        history = dict(s.attempts)
        knowledge = (domain.action_knowledge_key(s.payload,action) if hasattr(domain,'action_knowledge_key')
                     else domain.knowledge_key(s.payload))
        attempt_key = (action.key, knowledge)
        if action.kind in ('probe', 'metadata'):
            if history.get(attempt_key, 0) >= action.retry_limit:
                return None, 'no_progress_repeat'
            history[attempt_key] = history.get(attempt_key, 0)+1
        children = []
        for outcome in action.outcomes:
            child = State(outcome.payload, s.steps+1, s.used.then(outcome.resources), tuple(sorted(history.items())))
            w = witness(child)
            if w is None:
                return None, 'completion_reserve_lost'
            children.append((outcome, child, w))
        return children, None

    def base(s):
        w = witness(s)
        if w is None:
            return None
        if isinstance(w.first, Terminal):
            # Recheck actual eligibility even for a purported terminal witness.
            if hasattr(domain, 'check_terminal'):
                admitted = domain.check_terminal(s.payload, w.first)
            else:
                from itertools import islice
                admitted = w.first in tuple(islice(domain.terminals(s.payload), limits.max_terminals))
            if not admitted or not s.used.then(w.first.resources).fits(limits.resources):
                return None
            return w.first, completion_price(w), (), w
        children, reason = successors(s, w.first)
        if children is None or any(t.remaining_steps >= w.remaining_steps for _, _, t in children):
            return None
        # First-step consumption and each tail must be covered by the declared
        # whole-recipe certificate, not just by the request's loose budget.
        if any(not o.resources.then(t.resources).fits(w.resources) for o, _, t in children):
            return None
        return w.first, completion_price(w), tuple(children), w

    initial = base(state)
    if initial is None:
        return dict(choice=None, status='completion_witness_unavailable', records=[], expanded_states=0,
                    elapsed_ms=(clock()-started)*1000, tails=(), witness=None, estimated_cost=None)
    # Preparation above is mandatory bounded certificate work. The optional
    # deadline cannot prevent executing this independently retained fallback.
    deadline = clock()+limits.optional_ms/1000
    incumbent = initial[:3]
    completed_root_actions = 0

    def retain(value, picked, checked):
        nonlocal incumbent
        if picked is not None and (value < incumbent[1] or
                value == incumbent[1] and isinstance(picked,Terminal)):
            incumbent = (picked,value,checked)

    def evaluate(s, j, fallback=None):
        nonlocal expanded, completed_root_actions
        if clock() >= deadline or expanded >= limits.max_states:
            raise SearchLimit('optional_deadline_or_state_limit')
        expanded += 1
        fallback = fallback or base(s)
        if fallback is None:
            return math.inf, None, ()
        terminals = bounded(domain.terminals(s.payload), limits.max_terminals)
        terminals = [t for t in terminals if s.used.then(t.resources).fits(limits.resources)]
        terminal = min(terminals, key=lambda t: (terminal_price(t), t.key), default=None)
        best = terminal_price(terminal) if terminal else math.inf
        selected, tails = terminal, ()
        if s is state:retain(best,selected,tails)
        # A semantic-stage leaf ends at eligibility; do not optimize a physical
        # continuation or use execution prices to choose an interpretation.
        if semantic_phase and terminal is not None:return best, selected, tails
        if s.steps == limits.horizon:
            return best, selected, tails
        if j == 0:
            return min(best, fallback[1]), None, ()
        actions = bounded(domain.actions(s.payload), limits.max_actions)
        if len({a.key for a in actions}) != len(actions):
            raise ValueError('Duplicate action identity')
        # A sound fallback need not be rediscovered in optional generation.
        if isinstance(fallback[0], Action):
            actions = [fallback[0]]+[a for a in actions if a.key != fallback[0].key]
        if len(actions) > limits.max_actions:
            raise SearchLimit('representation_limit')
        for action in actions:
            if clock() >= deadline:
                raise SearchLimit('optional_deadline')
            if len(records) >= limits.max_states:
                raise SearchLimit('decision_record_limit')
            children, reason = successors(s, action)
            record = dict(state=domain.key(s.payload), action=action.key, status=reason or 'pending')
            records.append(record)
            if children is None:
                continue
            values = [o.estimated_cost+(0 if action_objective=='myopic' else evaluate(child, j-1)[0])
                      for o, child, _ in children]
            score = (math.inf if any(v == math.inf for v in values) else max(values)
                     if limits.aggregation == 'max' else math.fsum(o.probability*v for (o, _, _), v in zip(children, values)))
            record['estimated_cost'] = score if math.isfinite(score) else None
            record['status'] = 'evaluated'
            # Strict comparison preserves terminal ties and fallback-first ties.
            if score < best:
                best, selected, tails = score, action, tuple(children)
            if s is state:
                completed_root_actions += 1
                # Commit only after every outcome is certified AND scored.
                # A later timeout must not erase this completed root option.
                retain(best,selected,tails)
        return best, selected, tails

    choice, score, tails, saved = initial
    try:
        value, picked, checked = evaluate(state, min(limits.depth, limits.horizon-state.steps), initial)
        if picked is not None:
            choice, score, tails = picked, value, checked
    except SearchLimit as error:
        stop = str(error)
        choice, score, tails = incumbent
        for record in records:
            if record['status']=='pending':record['status']='interrupted'
    return dict(choice=choice, status=stop, estimated_cost=score, tails=tails, witness=saved,
                records=records, expanded_states=expanded, elapsed_ms=(clock()-started)*1000,
                completed_root_actions=completed_root_actions,
                selection_basis=('full_lookahead' if stop=='completed' else
                    'completed_root_incumbent' if choice is not initial[0] else 'completion_fallback'),
                objective='acquisition_only' if semantic_phase else action_objective)


def run_online(initial, domain, *, perform, execute, limits=Limits(), action_objective='continuation'):
    """Observe one selected action and replan; never execute hypothetical leaves."""
    started = time.perf_counter()
    state = State(initial)
    spent = Resources()
    report = dict(schema_version='xgap-unified-online-v1', success=False, status='planning',
                  rounds=[], trace=[], final_plan_executions=0, answer_rows=None,
                  strong_plan=False, root_gap=None, planning_ms=0.0, planning_cpu_ms=0.0,
                  acquisition_ms=0.0, local_action_ms=0.0, execution_ms=0.0, attempted_actions=0, external_calls_during_search=0)
    try:
        for _ in range(limits.horizon+1):
            cpu = time.process_time()
            decision = choose(state, domain, limits=limits, action_objective=action_objective)
            report['planning_cpu_ms'] += (time.process_time()-cpu)*1000
            report['planning_ms'] += decision['elapsed_ms']
            choice, w = decision['choice'], decision['witness']
            report['rounds'].append(dict(step=state.steps, status=decision['status'],
                objective=decision.get('objective'),
                selection_basis=decision.get('selection_basis'),
                completed_root_actions=decision.get('completed_root_actions',0),
                choice=choice.key if choice else None, estimated_cost=decision['estimated_cost'],
                completion=w.key if w else None, reserved_steps=w.remaining_steps if w else None,
                reserved_resources=asdict(w.resources) if w else None,
                completion_costs=dict(w.costs) if w else None, records=decision['records'],
                expanded_states=decision['expanded_states']))
            if choice is None:
                report['status'] = decision['status']
                return report
            if isinstance(choice, Terminal):
                eligible = (domain.check_terminal(state.payload,choice) if hasattr(domain,'check_terminal')
                            else choice in tuple(domain.terminals(state.payload)))
                if (not domain.valid(state.payload) or not eligible
                        or not state.used.then(choice.resources).fits(limits.resources)):
                    raise ValueError('Actual state no longer supports the selected terminal')
                report['final_plan_executions'] = 1
                report['selected_terminal'] = choice.key
                report['selected_execution_cost_estimate'] = choice.estimated_cost
                at = time.perf_counter()
                try:
                    result = execute(choice)
                finally:
                    report['execution_ms'] = (time.perf_counter()-at)*1000
                report.update(success=bool(result['success']), status='answered' if result['success'] else 'execution_failed',
                              execution=result, answer_rows=result.get('answer_rows'), selected_terminal=choice.key,
                              terminal_resource_reservation=asdict(choice.resources))
                return report
            at = time.perf_counter()
            report['attempted_actions'] += 1
            try:
                observed = perform(choice)
            except ActionFailure as error:
                spent = spent.then(error.used)
                report['trace'].append(dict(action=choice.key, kind=choice.kind, label=None,
                                            used=asdict(error.used), evidence=error.evidence, failed=True))
                raise
            except Exception:
                spent = UNBOUNDED  # An entered effect with no receipt cannot prove zero spend.
                raise
            finally:
                report['local_action_ms' if choice.kind=='transform' else 'acquisition_ms'] += (time.perf_counter()-at)*1000
            spent = spent.then(observed.used)
            report['trace'].append(dict(action=choice.key, kind=choice.kind, label=observed.label,
                                        used=asdict(observed.used), evidence=observed.evidence))
            selected = next((x for x in decision['tails'] if x[0].label == observed.label), None)
            if selected is None or observed.payload != selected[1].payload:
                raise ValueError('Actual response does not match a declared checked transition')
            outcome, predicted, tail = selected
            report['trace'][-1]['declared_action_cost'] = outcome.estimated_cost
            if not observed.used.fits(outcome.resources):
                raise ValueError('Actual action resource use violates its certified bound')
            actual = State(observed.payload, state.steps+1, state.used.then(observed.used), predicted.attempts)
            if (not domain.valid(actual.payload) or tail.state_key != domain.key(actual.payload)
                    or not domain.verify_completion(actual.payload, tail)
                    or actual.steps+tail.remaining_steps > limits.horizon
                    or not actual.used.then(tail.resources).fits(limits.resources)):
                raise ValueError('Actual observation invalidates the reserved completion')
            state = actual
        raise ValueError('No execution within the declared action horizon')
    except Exception as error:
        report.update(status='unified_failed', error_type=type(error).__name__, error=str(error))
        return report
    finally:
        costs=[t.get('declared_action_cost') for t in report['trace']]
        report['realized_acquisition_cost_estimate'] = (sum(costs) if all(v is not None for v in costs) else None)
        report['consumed_nonterminal_resources'] = asdict(spent)
        report['completed_actions'] = state.steps
        report['end_to_end_ms'] = (time.perf_counter()-started)*1000
