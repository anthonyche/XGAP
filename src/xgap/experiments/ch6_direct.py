"""One proposal followed by the SAME fixed-query physical planner; no intent authority.

This baseline deliberately has no scope/loss guarantee. A syntactically valid
proposal is an input query, not evidence about the user's intended query.
"""
from dataclasses import replace
import json
import time

from xgap.agent.intent_execution import family_runtime,snapshot_identity
from xgap.agent.unified_family import FamilyDomain,FamilyState,UnifiedSettings
from xgap.agent.unified_lookahead import ActionFailure,Observation,Resources,run_online
from xgap.planning.joint_cost import JointCostProfile
from xgap.runtime.contracts import RuntimeNodeKind
from xgap.runtime.unified_physical import PhysicalMoves
from xgap.semantic.intent_scope import ScopePolicy,construct_scope
from xgap.semantic.interpretation_candidates import interpret_candidate_question


class ProposalContract:
    """Physical fixed-input eligibility only. Never called an intent certificate."""
    requirements=()
    def __init__(self,family):self.family=family;self.identity=family.identity
    def consistent(self,bindings=()):return (0,) if not bindings else ()
    def check(self,index,bindings):
        return dict(eligible=index==0 and not bindings,kind='fixed_query_physical_input',intent_guarantee=False)


class ProposalDomain(FamilyDomain):
    def valid(self,state):
        # Reuse representation checks WITHOUT supplying a coverage attestation.
        return self.valid_representation(state) and not state.bindings


def answer_direct(request,provider,*,settings=UnifiedSettings(),source_schema,sources,backends,backend_clients,
                  physical_profile,costs=JointCostProfile(),estimator=None,language_version='v1'):
    started=time.perf_counter()
    report=dict(schema_version='xgap-llm-direct-v1',method='xgap-llm-direct',success=False,status='preparing',
                model_calls=None,input_tokens=None,output_tokens=None,final_plan_executions=0,
                automatic_retries=0,clarification_calls=0,scope_confirmation_calls=0,
                intent_guarantee=False,loss_certificate=None,answer_rows=None)
    try:
        if settings.decision_order!='joint' or settings.information_mode!='all' or settings.action_objective!='continuation':
            raise ValueError('Direct baseline requires the common physical settings')
        if request.required_constraints:raise ValueError('Hard constraints must be in the public compact request')
        interpreted=interpret_candidate_question(request,provider,candidate_cap=1)
        report['interpretation']=interpreted
        report['model_calls']=interpreted['external_calls'] if interpreted['external_call_count_complete'] else None
        for name in ('input_tokens','output_tokens'):report[name]=interpreted[name] if interpreted['token_usage_complete'] else None
        if not interpreted['success']:
            report['status']='proposal_failed';return report
        if report['model_calls'] is not None and report['model_calls']>1:
            report['status']='one_call_contract_violated';return report
        raw=interpreted.get('provenance',{}).get('raw_compact_response',{})
        candidates=raw.get('candidates',[])
        if len(candidates)!=1 or len(interpreted['candidates'])!=1 or interpreted['candidates'][0]['status']!='admitted':
            report['status']='not_one_complete_proposal';return report
        query=candidates[0]['query'];report['selected_query']=query
        family=construct_scope([query],ScopePolicy('one-unvalidated-proposal',(),language_version=language_version),
                               snapshot_identity(sources,backends,source_schema))
        prepare,execute,capabilities,capability_ms=family_runtime(family,source_schema=source_schema,sources=sources,
            backends=backends,backend_clients=backend_clients,physical_profile=physical_profile,
            joint_cost=costs,estimator=estimator,seed_only=True,stepwise=settings.physical_moves)
        seed=prepare(family.candidates[0],None)
        if any(n.kind is RuntimeNodeKind.REMOTE_BIND_QUERY for n in seed.nodes):raise ValueError('Unproved seed calls')
        for target in settings.information_targets:
            source=sources.get(target.source_id)
            if source is None or source.snapshot_version!=target.version or target.backend not in source.replica_backend_ids:
                raise ValueError('Information target snapshot differs')
        domain=ProposalDomain(request.question,ProposalContract(family),{0:(seed,0,Resources())},costs,
            authority_name='none',authority_version='none',settings=settings,estimator=estimator,
            moves=PhysicalMoves(family,source_schema,backends,physical_profile,sources))
        actual=FamilyState()
        def perform(action):
            nonlocal actual
            if action.kind=='transform':
                match=next((a for a in domain.physical_actions(actual) if a.key==action.key),None)
                if match is None:raise ValueError('Physical transition no longer admissible')
                actual=match.outcomes[0].payload
                return Observation('applied',actual,Resources(),{'external_calls':0,'kind':'transform'})
            if action.kind not in ('probe','metadata'):raise ValueError('Direct baseline cannot clarify')
            target=domain.targets[action.arguments['target']]
            try:label,evidence=target.invoke(backend_clients,sources)
            except Exception as error:raise ActionFailure(str(error),Resources(remote_calls=1,bytes=None,peak_bytes=None)) from error
            facts=dict(actual.facts)
            if label!='unknown':facts[target.name]=label
            actual=replace(actual,facts=tuple(sorted(facts.items())))
            return Observation(label,actual,Resources(remote_calls=1,bytes=None,peak_bytes=None),evidence)
        report['initialization_ms']=(time.perf_counter()-started)*1000
        core=run_online(actual,domain,perform=perform,execute=lambda t:execute(t.payload['plan']),limits=settings.limits)
        report.update(core)
        report.update(schema_version='xgap-llm-direct-v1',model_calls=interpreted['external_calls'] if interpreted['external_call_count_complete'] else None,
            capability_lookup=capabilities,capability_lookup_ms=capability_ms,selected_query=query,
            intent_guarantee=False,loss_certificate=None,terminal_certificate=None)
    except Exception as error:
        report.update(status='direct_failed',error_type=type(error).__name__,error=str(error))
    finally:report['end_to_end_ms']=(time.perf_counter()-started)*1000
    return report
