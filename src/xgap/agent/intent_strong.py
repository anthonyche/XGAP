"""Certified family terminals in the existing finite AND/OR strong solver.

Full-intent and scoped clarification share one action space in both modes.
Counterfactual outcomes are symbolic: no oracle/backend calls during search.
Physical plans are prepared only at certified leaves and cached per candidate.
"""
from dataclasses import asdict, dataclass
import json
import time

from xgap.agent.intent_certificate import canonical, fingerprint, fraction_view
from xgap.agent.strong_planning import (AcquisitionAlternative, DeclaredOutcome, ResourceUsage,
    StrongSearchLimits, TerminalAlternative, search_strong_policy)
from xgap.runtime.contracts import RuntimeNodeKind
from xgap.tools import ToolRegistry
from xgap.tools.contracts import ToolContext, ToolStatus


@dataclass(frozen=True)
class FamilyInformationPolicy:
    max_calls: int = 9
    max_disclosed_coordinates: int = 32
    cost_basis: str = 'interactions'
    additional_scopes: tuple[tuple[int, ...], ...] = ()

    def __post_init__(self):
        if (type(self.max_calls) is not int or not 0<=self.max_calls<=32 or
                type(self.max_disclosed_coordinates) is not int or not 0<=self.max_disclosed_coordinates<=1024 or
                self.cost_basis not in ('interactions','disclosed_coordinates')):
            raise ValueError('Invalid bounded information policy or declared burden unit')
        if not isinstance(self.additional_scopes,tuple) or len(self.additional_scopes)>31:
            raise ValueError('At most31 additional finite information scopes')

    def cost(self, scope):
        # Declared burden, NEVER milliseconds or an invented human waiting time.
        return 1 if self.cost_basis=='interactions' else len(scope)


@dataclass(frozen=True)
class FamilyState:
    observations: tuple = ()
    calls: int = 0
    disclosed: int = 0


class FamilyStrongDomain:
    def __init__(self, question, contract, information, prepare, *, tool_name, candidate_order=None, strategy='search', joint_cost=None,
                 execution_cost_feedback=True):
        if strategy not in ('search','full','fixed') or strategy=='full' and contract.mode!='exact':
            raise ValueError('Unknown strategy or non-exact full-clarification control')
        self.strategy=strategy
        self.joint_cost=joint_cost
        if type(execution_cost_feedback) is not bool:raise ValueError('Feedback switch must be boolean')
        self.execution_cost_feedback=execution_cost_feedback
        self.question=question; self.contract=contract; self.family=contract.family
        self.information=information; self.prepare=prepare; self.tool_name=tool_name
        n=len(self.family.slots); full=tuple(range(n))
        extra=information.additional_scopes
        if any(not isinstance(scope,tuple) or not scope or len(set(scope))!=len(scope) or
               any(type(j) is not int or not 0<=j<n for j in scope) for scope in extra):
            raise ValueError('Invalid information scope')
        # Full disclosure is always available, first as a feasible-policy seed.
        self.scopes=tuple(dict.fromkeys((full, *((j,) for j in range(n)), *(tuple(sorted(s)) for s in extra))))
        self.order=tuple(range(len(self.family.candidates))) if candidate_order is None else tuple(candidate_order)
        if sorted(self.order)!=list(range(len(self.family.candidates))):
            raise ValueError('Candidate order must be a permutation, never a truncated uncertainty set')
        self.plans={}; self.failed={}; self.prepare_ms=self.certificate_ms=0.0
        self.preparations=self.plan_cache_hits=0
        self.terminal_prefixes=[]

    def terminals(self, state):
        at=time.perf_counter()
        remaining=self.family.consistent(state.observations)
        self.certificate_ms+=(time.perf_counter()-at)*1000
        checked=0
        for i in self.order:
            if i not in remaining: continue
            at=time.perf_counter(); cert=self.contract.check(i,state.observations)
            self.certificate_ms+=(time.perf_counter()-at)*1000; checked+=1
            if not cert['eligible'] or i in self.failed: continue
            if i not in self.plans:
                at=time.perf_counter(); self.preparations+=1
                try:
                    plan=self.prepare(self.family.candidates[i],cert)
                    if plan is None: raise ValueError('No executable physical plan')
                    self.plans[i]=plan
                except Exception as error:
                    self.failed[i]=dict(candidate_id=self.family.candidates[i].candidate_id,
                        error_type=type(error).__name__,error=str(error))
                    continue
                finally:
                    self.prepare_ms+=(time.perf_counter()-at)*1000
            else: self.plan_cache_hits+=1
            plan=self.plans[i]
            remote=sum(n.kind in (RuntimeNodeKind.REMOTE_QUERY, RuntimeNodeKind.REMOTE_BIND_QUERY) for n in plan.nodes)
            self.terminal_prefixes.append(dict(state=fingerprint(asdict(state)),observations=len(state.observations),
                remaining_intents=len(remaining),checked=checked,candidate_id=self.family.candidates[i].candidate_id))
            # Historical profiles optimize information alone; the current
            # profile also accounts for estimated final execution work.
            cost = 0 if self.joint_cost is None or not self.execution_cost_feedback else plan.metadata['joint_execution_cost']
            yield TerminalAlternative(fingerprint([i,state.observations]),cost,
                dict(candidate_index=i,certificate=cert,plan=plan,observations=state.observations),
                resources=ResourceUsage(remote_calls=remote))
            if self.joint_cost is None: return

    def actions(self, state):
        # Controls share tool permissions and strong-outcome admission. Only
        # their choice rule differs; they never consult outcomes or costs.
        for action in self._actions(state):
            if self.strategy=='search':yield action
            elif self.strategy=='full':
                if len(action.arguments['slots'])==len(self.family.slots):
                    yield action;return
            elif len(action.arguments['slots'])==1:
                yield action;return

    def _actions(self, state):
        p=self.information
        if self.family.coverage_basis is None or state.calls>=p.max_calls: return
        remaining=self.family.consistent(state.observations)
        known=dict(state.observations)
        for scope in self.scopes:
            if state.disclosed+len(scope)>p.max_disclosed_coordinates: continue
            groups={}
            for i in remaining:
                answer=tuple((j,self.family.values[i][j]) for j in scope)
                groups.setdefault(answer,[]).append(i)
            if len(groups)<2: continue  # no needless paid reconfirmation
            outcomes=[]
            for answer in sorted(groups):
                observations=tuple(sorted({**known,**dict(answer)}.items()))
                outcomes.append(DeclaredOutcome(fingerprint(answer),
                    FamilyState(observations,state.calls+1,state.disclosed+len(scope))))
            yield AcquisitionAlternative('scope:'+','.join(map(str,scope)),self.tool_name,
                dict(family_sha256=self.family.identity,question_sha256=fingerprint(self.question),
                    slots=[self.family.slots[j].name for j in scope]),tuple(outcomes),
                self.joint_cost.information(scope) if self.joint_cost else p.cost(scope))


def run_strong_intent(question, contract, oracle, *, prepare, execute,
                      information=FamilyInformationPolicy(), candidate_order=None,
                      limits=StrongSearchLimits(), on_observation=None, strategy='search', joint_cost=None,
                      initial_observations=(),execution_cost_feedback=True,include_policy=False):
    started=time.perf_counter(); registry=ToolRegistry(); registry.register(oracle)
    domain=FamilyStrongDomain(question,contract,information,prepare,
        tool_name=oracle.spec.name,candidate_order=candidate_order,strategy=strategy,joint_cost=joint_cost,
        execution_cost_feedback=execution_cost_feedback)
    r=dict(schema_version='xgap-family-strong-answer-v1',success=False,status='planning',
        mode=contract.mode,strategy=strategy,family_sha256=contract.family.identity,epsilon=fraction_view(contract.epsilon),
        acquisition_policy=asdict(information),cost_basis='declared '+information.cost_basis+'; not wall time',
        final_plan_executions=0,clarification_calls=0,disclosed_coordinates=0,oracle_reply_bytes=0,
        oracle_processing_ms=0.0,acquisition_ms=0.0,execution_ms=0.0,model_calls=0,tokens=0,
        backend_remote_calls=0,answer_rows=None,user_intent_verified=False,answer_quality_verified=False,
        terminal_certificate=None,ledger=[],realized_prefixes=[],root_gap=None,
        strong_plan=False,execution_cost_feedback=execution_cost_feedback,
        observed_policy_state_ids=[],strong_scope='declared complete family and truthful scoped replies; '
            'compiled continuation for every selected outcome; backend availability remains conditional')
    checks=contract.checks; hits=contract.cache_hits
    try:
        initial=tuple(sorted(initial_observations))
        contract.family.consistent(initial)  # Keep the full metric and filter only the state.
        root_state=FamilyState(initial)
        r['initial_observations']=list(initial)
        at=time.process_time()
        search=search_strong_policy(root_state,domain,limits=limits,terminal_first=joint_cost is None,
            prune_nonimproving_actions=True)
        r['planning_cpu_ms']=(time.process_time()-at)*1000
        r['search']=search.to_dict();r['planning_ms']=search.elapsed_ms;r['strong_plan']=search.policy is not None
        r['search']['cost_objective']='declared information burden plus worst-outcome remaining information burden'
        r['search']['terminal_first']=True
        if joint_cost is not None:
            r['cost_profile']=joint_cost.to_dict()
            r['cost_basis']='declared_work_units; not measured latency'
            r['search']['cost_objective']='clarification cost plus worst-outcome estimated final execution cost'
            r['search']['stop_at_first_certified_terminal']=False
            if not execution_cost_feedback:
                r['search']['cost_objective']='clarification cost; execution feedback disabled; physical ranking unchanged'
        if search.policy is None:
            r['status']='unknown_coverage' if contract.family.coverage_basis is None else 'no_feasible_strong_policy'
            return r
        if include_policy:
            from xgap.agent.policy_evidence import export_intent_policy
            at=time.perf_counter();r['policy_evidence']=export_intent_policy(search.policy,contract.family)
            r['policy_export_ms']=(time.perf_counter()-at)*1000
        current=search.policy; state=root_state
        for step in range(information.max_calls+1):
            r['observed_policy_state_ids'].append(current.state_id)
            r['realized_prefixes'].append(dict(calls=state.calls,observations=len(state.observations),
                remaining_intents=len(contract.family.consistent(state.observations))))
            if current.terminal is not None:
                payload=current.terminal.payload
                # A counterfactual leaf certificate becomes actual only after
                # its scoped replies were really received and checked.
                at=time.perf_counter()
                cert=contract.check(payload['candidate_index'],state.observations)
                domain.certificate_ms+=(time.perf_counter()-at)*1000
                if not cert['eligible'] or state.observations!=payload['observations']:
                    raise ValueError('Realized state does not justify the selected terminal')
                r['terminal_certificate']=cert;r['user_intent_verified']=cert['upper_bound']['numerator']==0
                if include_policy:
                    r['selected_query']=json.loads(contract.family.candidates[payload['candidate_index']].query_json)
                r['final_plan_executions']=1;at=time.perf_counter()
                try: result=execute(payload['plan'])
                finally: r['execution_ms']=(time.perf_counter()-at)*1000
                r.update(execution=result,success=bool(result['success']),
                    status='answered' if result['success'] else 'execution_failed',answer_rows=result.get('answer_rows'))
                r['backend_remote_calls']=result.get('result',{}).get('metrics',{}).get('remote_calls',0)
                return r
            action=current.action
            if step>=information.max_calls or action.tool_name!=oracle.spec.name:
                raise ValueError('Realized information action exceeds its allowlist or budget')
            at=time.perf_counter();r['clarification_calls']+=1
            result=registry.invoke(action.tool_name,action.arguments,ToolContext('family-strong',step,str(step)))
            r['acquisition_ms']+=(time.perf_counter()-at)*1000
            record=dict(action_id=action.action_id,request=action.arguments,response=result.to_dict(),
                category='required_for_execution' if any(s.hard and s.name in action.arguments['slots']
                    for s in contract.family.slots) else 'required_for_exactness')
            r['ledger'].append(record)
            r['oracle_processing_ms']+=result.metrics.get('elapsed_ms',0)
            r['disclosed_coordinates']+=result.metrics.get('disclosed_coordinates',0)
            r['oracle_reply_bytes']+=result.metrics.get('reply_bytes',0)
            if on_observation is not None: on_observation(record)
            if result.status is not ToolStatus.SUCCESS:
                r['status']='oracle_failed';return r
            reply=result.value;args=action.arguments
            if (not isinstance(reply,dict) or set(reply)!={*args,'answers'} or
                    any(reply[k]!=v for k,v in args.items()) or not isinstance(reply['answers'],dict) or
                    set(reply['answers'])!=set(args['slots'])):
                raise ValueError('Oracle scope, family or question mismatch')
            names=[s.name for s in contract.family.slots]
            answer=tuple((names.index(name),canonical(reply['answers'][name])) for name in args['slots'])
            labels={o.outcome_id:o.state for o in action.outcomes};label=fingerprint(answer)
            if label not in labels: raise ValueError('Oracle outcome is outside the declared complete family')
            observed=labels[label]
            if (observed.calls!=r['clarification_calls'] or observed.disclosed!=r['disclosed_coordinates'] or
                    observed.disclosed>information.max_disclosed_coordinates):
                raise ValueError('Observed information usage differs from declared budget')
            current=dict(current.children)[label];state=observed
        raise ValueError('No terminal within the bounded realized policy')
    except Exception as error:
        r.update(status='family_strong_failed',error_type=type(error).__name__,error=str(error));return r
    finally:
        r.update(physical_prepare_attempts=domain.preparations,physical_plan_cache_hits=domain.plan_cache_hits,
            physical_preparation_ms=domain.prepare_ms,preparation_failures=list(domain.failed.values()),
            certificate_ms=domain.certificate_ms,certificate_checks=contract.checks-checks,
            certificate_cache_hits=contract.cache_hits-hits,hypothetical_terminal_prefixes=domain.terminal_prefixes,
            end_to_end_ms=(time.perf_counter()-started)*1000)
