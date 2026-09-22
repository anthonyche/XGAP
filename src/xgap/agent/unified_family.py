"""Bounded family, protected plan pools and selected information/physical actions.

Pure symbolic transitions share the online guarded controller. Only perform and
final execute callbacks invoke live tools; no current-query alternative trials.
"""
from dataclasses import asdict, dataclass, replace
import json
import math
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
    decision_order: str = 'joint'
    physical_moves: bool = True
    plan_pool: int = 4
    max_plan_bytes: int = 32*1024*1024
    max_plans: int = 1024
    transform_cost: float = 0.01
    candidate_weights: tuple[float, ...] | None = None
    information_targets: tuple = ()
    information_mode: str = 'all'
    action_objective: str = 'continuation'

    def __post_init__(self):
        rational(self.epsilon)
        if (not isinstance(self.relaxable, tuple) or len(self.relaxable) > 64
                or len(set(self.relaxable)) != len(self.relaxable)
                or any(not isinstance(x, str) or not x for x in self.relaxable)
                or not isinstance(self.limits, Limits)):
            raise ValueError('Lambda must list distinct declared requirement names')
        from xgap.agent.unified_information import InformationTarget
        from xgap.agent.unified_lookahead import cost
        cost(self.transform_cost)
        if self.decision_order not in ('joint','semantic_then_physical','two_stage'):raise ValueError('Unknown stage ordering')
        if self.information_mode not in ('all','no_probe') or self.action_objective not in ('continuation','myopic'):
            raise ValueError('Unknown information or action objective')
        if (type(self.physical_moves) is not bool or type(self.plan_pool) is not int or not 1<=self.plan_pool<=16
                or type(self.max_plans) is not int or not 1<=self.max_plans<=4096
                or type(self.max_plan_bytes) is not int or not 65536<=self.max_plan_bytes<=256*1024*1024
                or not isinstance(self.information_targets,tuple) or len(self.information_targets)>16
                or any(not isinstance(t,InformationTarget) for t in self.information_targets)
                or len({t.name for t in self.information_targets})!=len(self.information_targets)):
            raise ValueError('Invalid bounded plan pool/information registry')
        if self.candidate_weights is not None:
            if not isinstance(self.candidate_weights,tuple) or not 1<=len(self.candidate_weights)<=64:
                raise ValueError('Explicit bounded candidate prior required')
            for weight in self.candidate_weights:cost(weight)
            if any(w<=0 for w in self.candidate_weights):raise ValueError('Admitted family prior requires positive support')


@dataclass(frozen=True)
class FamilyState:
    bindings: tuple[ValidatedBinding, ...] = ()
    pools: tuple = ()
    facts: tuple = ()
    disclosed: int = 0
    fixed_candidate: int | None = None


class FamilyDomain:
    def __init__(self, question, contract, seeds, costs, *, authority_name, authority_version, settings=UnifiedSettings(), moves=None, estimator=None, information=None):
        self.question, self.contract, self.seeds, self.costs = question, contract, dict(seeds), costs
        self.authority_name, self.authority_version = authority_name, authority_version
        self.names = tuple(r.name for r in contract.requirements)
        from xgap.agent.intent_strong import FamilyInformationPolicy
        self.information=information or FamilyInformationPolicy()
        if any(not scope or len(set(scope))!=len(scope) or any(type(i) is not int or not 0<=i<len(self.names)
               for i in scope) for scope in self.information.additional_scopes):raise ValueError('Invalid additional information scope')
        self.settings,self.moves,self.estimator = settings,moves,estimator
        self.plans = {}
        self.plan_bytes = 0
        self.optional_plan_rejections = 0
        self.targets = {t.name:t for t in settings.information_targets}
        self.estimate_cache = {}
        self.move_cache = {}
        # Request-local, bounded caches. Keys include bindings/receipts, facts,
        # retained pools and disclosure state; no reuse across source snapshots.
        self.key_cache, self.terminal_cache, self.completion_cache = {}, {}, {}
        self.completion_cache_hits = 0
        self.completion_evaluations = 0
        self.estimate_evaluations = 0
        self.estimate_cache_hits = 0
        self.seed_keys = {i:self.store(i,plan,protected=True) for i,(plan,_,_) in self.seeds.items()}
        if settings.limits.aggregation=='expectation':
            if settings.candidate_weights is None or len(settings.candidate_weights)!=len(contract.family.candidates):
                raise ValueError('Expectation requires a frozen prior for every candidate')
            if any(t.probabilities is None for t in self.targets.values()):
                raise ValueError('Expectation requires all information outcome probabilities')

    def store(self,index,plan,protected=False):
        from xgap.runtime.unified_physical import identity
        key = str(index)+':'+identity(plan)
        if key in self.plans:return key
        size = len(canonical(plan.to_dict()).encode())
        if size>1048576 or len(self.plans)>=self.settings.max_plans or self.plan_bytes+size>self.settings.max_plan_bytes:
            if protected:raise ValueError('Protected seeds exceed plan representation budget')
            self.optional_plan_rejections+=1
            return None
        self.plans[key]=(index,plan)
        self.plan_bytes+=size
        return key

    def pool(self,state,index):
        if index not in self.seeds:return ()
        seed=self.seed_keys[index]
        return (seed,)+tuple(k for k in dict(state.pools).get(index,()) if k!=seed)

    def score(self,state,key):
        plan=self.plans[key][1]
        backend_ids={n.parameters.get('backend_id') for n in plan.nodes}
        facts=dict(state.facts)
        relevant=tuple((t.identity,facts.get(t.name,'unknown')) for t in self.targets.values() if t.backend in backend_ids)
        cache_key=(key,relevant)
        if cache_key in self.estimate_cache:
            self.estimate_cache_hits+=1
            return self.estimate_cache[cache_key]
        base,_=self.costs.execution(plan,self.estimator)
        for target in self.targets.values():
            if target.kind!='probe':continue
            label=facts.get(target.name,'unknown')
            rows=target.row_estimates[target.labels.index(label)]
            for node in plan.nodes:
                if node.parameters.get('backend_id')!=target.backend:continue
                if node.kind is RuntimeNodeKind.REMOTE_QUERY:base+=rows*target.row_cost
                elif node.kind is RuntimeNodeKind.REMOTE_BIND_QUERY:
                    base+=target.bind_startup+rows*target.row_cost*target.bind_fraction
        self.estimate_evaluations+=1
        if len(self.estimate_cache)>=4096:self.estimate_cache.pop(next(iter(self.estimate_cache)))
        self.estimate_cache[cache_key]=base
        return base

    def required_facts(self,plan):
        rewrite=plan.metadata.get('unified_rewrite',{})
        backends={n.parameters.get('backend_id') for n in plan.nodes}
        inherited=tuple(tuple(p) for p in plan.metadata.get('unified_required_facts',()))
        return tuple(sorted(set(inherited+tuple((t.name,t.gate_label) for t in self.targets.values()
            if t.gates_rule==rewrite.get('rule') and t.backend in backends))))

    def physical_actions(self,state):
        if self.moves is None or not self.settings.physical_moves or self.settings.plan_pool==1:return
        emitted=set()
        for i in self.contract.consistent(state.bindings):
            if state.fixed_candidate is not None and i!=state.fixed_candidate:continue
            current=self.pool(state,i)
            for parent in current:
                cache_key=(i,parent)
                if cache_key not in self.move_cache:
                    generated=[]
                    for plan in self.moves.neighbors(i,self.plans[parent][1]):
                        required=self.required_facts(plan)
                        plan=replace(plan,metadata={**plan.metadata,'unified_required_facts':required})
                        key=self.store(i,plan)
                        if key is not None:generated.append(key)
                    if len(self.move_cache)>=128:self.move_cache.pop(next(iter(self.move_cache)))
                    self.move_cache[cache_key]=tuple(dict.fromkeys(generated))
                for key in self.move_cache[cache_key]:
                    plan=self.plans[key][1]
                    if key is None or key in current or key in emitted:continue
                    # The protected seed is never pruned. Keep K-1 scored alternatives.
                    eligible=sorted(set(current[1:]+(key,)),key=lambda k:(self.score(state,k),k))
                    retained=(current[0],)+tuple(eligible[:self.settings.plan_pool-1])
                    if key not in retained:continue
                    pools=dict(state.pools);pools[i]=retained
                    child=replace(state,pools=tuple(sorted(pools.items())))
                    # Distinct parents can reach the same executable DAG. Its
                    # child pool and price are identical; retain the first proof
                    # deterministically, rather than emitting duplicate actions.
                    emitted.add(key)
                    yield Action('transform:'+key,'transform',(Outcome('applied',child,self.settings.transform_cost,
                        Resources(),1.0),),dict(candidate=i,parent=parent,plan_key=key,
                        rule=plan.metadata['unified_rewrite']['rule']))

    def information_actions(self,state):
        for target in self.targets.values():
            if self.settings.information_mode=='no_probe' and target.kind=='probe':continue
            if target.name in dict(state.facts):continue
            outcomes=[]
            for j,label in enumerate(target.labels):
                facts=dict(state.facts)
                if label!='unknown':facts[target.name]=label
                child=replace(state,facts=tuple(sorted(facts.items())))
                outcomes.append(Outcome(label,child,target.action_cost,Resources(remote_calls=1,bytes=None,peak_bytes=None),
                    target.probabilities[j] if target.probabilities is not None else None))
            yield Action('information:'+target.identity,target.kind,tuple(outcomes),dict(target=target.name,identity=target.identity))

    def key(self, state):
        if state not in self.key_cache:
            self.remember(self.key_cache,state,fingerprint([self.contract.identity,
                [asdict(b) for b in state.bindings],state.pools,state.facts,state.disclosed,state.fixed_candidate]))
        return self.key_cache[state]

    @staticmethod
    def remember(cache,key,value):
        if len(cache)>=128:cache.pop(next(iter(cache)))
        cache[key]=value
        return value

    def semantic_only(self,state):
        return self.settings.decision_order=='two_stage' and state.fixed_candidate is None

    def settle(self,state):
        """Freeze the first eligible ID without consulting execution estimates.

        This is a zero-cost phase boundary, not a binding or extra H action.
        Keep the original consistent family intact for all discrepancy checks.
        """
        if not self.semantic_only(state):return state
        eligible=[i for i in self.contract.consistent(state.bindings) if self.contract.check(i,state.bindings)['eligible']]
        if not eligible:return state
        index=min(eligible,key=lambda i:self.contract.family.candidates[i].candidate_id)
        return replace(state,fixed_candidate=index)

    def knowledge_key(self, state):
        return fingerprint([self.contract.identity,
            [(b.name, b.value_json, b.source, b.version) for b in state.bindings],state.facts])

    def action_knowledge_key(self,state,action):
        if action.kind in ('probe','metadata'):
            target=self.targets[action.arguments['target']]
            return fingerprint([target.identity,dict(state.facts).get(target.name)])
        return self.knowledge_key(state)

    def valid(self, state):
        return self.contract.family.coverage_basis is not None and self.valid_representation(state)

    def valid_representation(self, state):
        """Shared bounded physical state checks, independent of intent coverage."""
        try:
            return (bool(self.contract.consistent(state.bindings))
                and (state.fixed_candidate is None or self.settings.decision_order=='two_stage'
                     and state.fixed_candidate in self.contract.consistent(state.bindings)
                     and self.contract.check(state.fixed_candidate,state.bindings)['eligible'])
                and 0<=state.disclosed<=self.information.max_disclosed_coordinates
                and len(dict(state.pools))==len(state.pools) and len(dict(state.facts))==len(state.facts)
                and all(n in self.targets and label in self.targets[n].labels[:-1] for n,label in state.facts)
                and all(i in self.seeds and len(keys)<=self.settings.plan_pool and
                    all(k in self.plans and self.plans[k][0]==i for k in keys) for i,keys in state.pools))
        except ValueError:
            return False

    def updated(self, state, names, answers):
        request = self.arguments(names)
        receipt = fingerprint([request, answers, self.authority_version])
        known = {b.name: b for b in state.bindings}
        for name in names:
            known[name] = ValidatedBinding(name, canonical(answers[name]), self.authority_name,
                                          self.authority_version, receipt)
        return self.settle(replace(state,bindings=tuple(known[n] for n in sorted(known)),disclosed=state.disclosed+len(names)))

    def arguments(self, names):
        return dict(family_sha256=self.contract.family.identity, question_sha256=fingerprint(self.question), slots=list(names))

    def action(self, state, names):
        names = tuple(sorted(names))
        args = self.arguments(names)
        groups = {}
        remaining=self.contract.consistent(state.bindings)
        weights=self.settings.candidate_weights
        masses={}
        for i in remaining:
            answers = {n: json.loads(self.contract.values[i][n]) for n in names}
            label = fingerprint(answers)
            response_bytes = len(canonical({**args, 'answers': answers}).encode())
            masses[label]=masses.get(label,0)+(weights[i] if weights else 1)
            groups[label] = Outcome(label, self.updated(state, names, answers), self.costs.information(names),
                                    Resources(user_calls=1, bytes=response_bytes, peak_bytes=None))
        if self.settings.limits.aggregation=='expectation':
            total=sum(masses.values())
            groups={k:replace(v,probability=masses[k]/total) for k,v in groups.items()}
        return Action('validate:'+','.join(names), 'binding', tuple(groups[k] for k in sorted(groups)), args)

    def actions(self, state):
        unknown = tuple(n for n in self.names if n not in {b.name for b in state.bindings})
        if unknown and self.settings.decision_order=='semantic_then_physical':
            yield self.action(state,unknown)
            return
        if unknown and not (self.settings.decision_order=='two_stage' and state.fixed_candidate is not None):
            scopes = tuple(dict.fromkeys((unknown, *((n,) for n in unknown),
                *(tuple(self.names[i] for i in scope if self.names[i] in unknown) for scope in self.information.additional_scopes))))
            yield from (self.action(state,names) for names in scopes if names)
        if self.semantic_only(state):return
        yield from self.physical_actions(state)
        yield from self.information_actions(state)

    def terminals(self, state):
        if state not in self.terminal_cache:
            self.remember(self.terminal_cache,state,self._terminals(state))
        return self.terminal_cache[state]

    def _terminals(self, state):
        if self.settings.decision_order=='semantic_then_physical' and len(state.bindings)<len(self.names):return ()
        results = []
        for i in self.contract.consistent(state.bindings):
            if state.fixed_candidate is not None and i!=state.fixed_candidate:continue
            if i not in self.seeds:
                continue
            cert = self.contract.check(i, state.bindings)
            if cert['eligible']:
                for key in self.pool(state,i):
                    plan=self.plans[key][1]
                    if any(dict(state.facts).get(n)!=label for n,label in self.required_facts(plan)):continue
                    # Scheduler invokes once per native node, with no batching/retry.
                    # Bind key overflow remains an explicit execution failure.
                    calls=sum(n.kind in (RuntimeNodeKind.REMOTE_QUERY,RuntimeNodeKind.REMOTE_BIND_QUERY) for n in plan.nodes)
                    resources=Resources(remote_calls=calls,bytes=None,peak_bytes=None)
                    results.append(Terminal(self.contract.family.candidates[i].candidate_id+':'+plan.plan_id,
                        self.score(state,key), resources, dict(candidate_index=i, certificate=cert, plan=plan)))
        return tuple(sorted(results, key=lambda t: (t.estimated_cost, t.key)))

    def completion(self, state):
        if state in self.completion_cache:
            self.completion_cache_hits+=1
            return self.completion_cache[state]
        self.completion_evaluations+=1
        return self.remember(self.completion_cache,state,self._completion(state))

    def _completion(self, state):
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
                          (('required_validation', self.costs.information(unknown)), ('execution',
                           max(costs) if self.settings.limits.aggregation=='max' else
                           sum(o.probability*c for o,c in zip(first.outcomes,costs)))), first)

    def check_terminal(self,state,terminal):
        # Bounded direct check, independent of optional terminal-enumeration caps.
        index=terminal.payload['candidate_index']
        if state.fixed_candidate is not None and index!=state.fixed_candidate:return False
        if self.settings.decision_order=='semantic_then_physical' and len(state.bindings)<len(self.names):return False
        cert=self.contract.check(index,state.bindings)
        for key in self.pool(state,index):
            plan=self.plans[key][1]
            if self.contract.family.candidates[index].candidate_id+':'+plan.plan_id!=terminal.key:continue
            if any(dict(state.facts).get(n)!=label for n,label in self.required_facts(plan)):return False
            calls=sum(n.kind in (RuntimeNodeKind.REMOTE_QUERY,RuntimeNodeKind.REMOTE_BIND_QUERY) for n in plan.nodes)
            expected=Terminal(terminal.key,self.score(state,key),Resources(remote_calls=calls,bytes=None,peak_bytes=None),
                dict(candidate_index=index,certificate=cert,plan=plan))
            return cert['eligible'] and terminal==expected
        return False

    def verify_completion(self, state, witness):
        # This is a direct reconstruction of the fixed one-step recipe over N
        # candidates, not recursive completion or enumeration over horizon H.
        return witness == self.completion(state)


def run_unified_family(question, family, user, *, prepare_seed, execute, costs, settings=UnifiedSettings(),
                       on_observation=None, estimator=None, moves=None, backend_clients=None, sources=None, information=None, initial_clues=None):
    started = time.perf_counter()
    initial_clues=dict(initial_clues or {})
    if set(initial_clues)-{s.name for s in family.slots}:raise ValueError('Unknown public initial clue')
    requirements = tuple(ValidationRequirement(s.name, s.path,
        'authored-request' if s.name in initial_clues else user.spec.name,
        family.identity) for s in family.slots)
    contract = UnifiedTerminalContract(family, requirements, relaxable=settings.relaxable, epsilon=settings.epsilon)
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
    domain = FamilyDomain(question, contract, seeds, costs, authority_name=user.spec.name, authority_version=family.identity, settings=settings, moves=moves, estimator=estimator, information=information)
    registry = ToolRegistry()
    registry.register(user)
    actual = FamilyState(bindings=tuple(ValidatedBinding(name,canonical(value),'authored-request',family.identity,
        fingerprint(['public-initial-clue',family.identity,name,value])) for name,value in sorted(initial_clues.items())))
    actual = domain.settle(actual)
    receipts = []
    tool_receipts = []

    def perform(action):
        nonlocal actual
        if action.kind=='transform':
            # Reconstruct the selected local transformation; never trust a hypothetical effect.
            matching=next((a for a in domain.physical_actions(actual) if a.key==action.key),None)
            if matching is None:raise ValueError('Selected physical rewrite no longer admitted')
            actual=matching.outcomes[0].payload
            record=dict(action_id=action.key,kind=action.kind,arguments=action.arguments,external_calls=0)
            tool_receipts.append(record)
            if on_observation is not None:on_observation(record)
            return Observation('applied',actual,Resources(),record)
        if action.kind in ('metadata','probe'):
            target=domain.targets[action.arguments['target']]
            if target.identity!=action.arguments['identity']:raise ValueError('Information target changed')
            try:
                label,record=target.invoke(backend_clients,sources)
            except Exception as error:
                raise ActionFailure(str(error),Resources(remote_calls=1,bytes=None,peak_bytes=None)) from error
            tool_receipts.append(record)
            if on_observation is not None:on_observation(record)
            facts=dict(actual.facts)
            if label!='unknown':facts[target.name]=label
            actual=replace(actual,facts=tuple(sorted(facts.items())))
            return Observation(label,actual,Resources(remote_calls=1,bytes=None,peak_bytes=None),record)
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

    result = run_online(actual, domain, perform=perform, execute=dispatch, limits=settings.limits,
                        action_objective=settings.action_objective)
    selected = (next((t for t in domain.terminals(actual) if t.key == result.get('selected_terminal')), None)
                if result.get('selected_terminal') and domain.valid(actual) else None)
    result.update(clarification_calls=len(receipts), ledger=receipts, initialization_ms=initialization_ms,
                  physical_prepare_attempts=len(family.candidates), preparation_failures=failures,
                  terminal_certificate=selected.payload['certificate'] if selected else None,
                  certificate_checks=contract.checks, certificate_cache_hits=contract.cache_hits,
                  certificate_ms=contract.elapsed_ms, model_calls=0,
                  expanded_states=sum(r['expanded_states'] for r in result['rounds']),
                  disclosed_coordinates=sum(r['response'].get('metrics', {}).get('disclosed_coordinates', 0) for r in receipts),
                  backend_remote_calls=result.get('execution', {}).get('result', {}).get('metrics', {}).get('remote_calls'),
                  adapter_end_to_end_ms=(time.perf_counter()-started)*1000,
                  resource_scope='online phase after initialization; remote_calls are runtime adapter invocations; bytes/peak unknown',
                  action_scope='unified validation, single physical rewrites, registered metadata/statistics, one execution',
                  selected_query=json.loads(family.candidates[selected.payload['candidate_index']].query_json) if selected else None,
                  physical_actions=sum(t['kind']=='transform' for t in result['trace']),
                  probe_calls=sum(t['kind']=='probe' for t in result['trace']),
                  metadata_calls=sum(t['kind']=='metadata' for t in result['trace']),
                  information_ledger=tool_receipts,plan_registry_count=len(domain.plans),plan_registry_bytes=domain.plan_bytes,
                  optional_plan_rejections=domain.optional_plan_rejections,
                  completion_cache_hits=domain.completion_cache_hits,
                  completion_evaluations=domain.completion_evaluations,
                  completion_cache_entries=len(domain.completion_cache),
                  retained_plans={str(i):list(domain.pool(actual,i)) for i in seeds},
                  estimate_evaluations=domain.estimate_evaluations,estimate_cache_hits=domain.estimate_cache_hits,
                  selected_facts=dict(actual.facts),
                  decision_order=settings.decision_order, fixed_candidate=actual.fixed_candidate,
                  information_mode=settings.information_mode, action_objective=settings.action_objective,
                  estimator_basis='frozen numerical model plus declared category work costs; not measured latency')
    return result
