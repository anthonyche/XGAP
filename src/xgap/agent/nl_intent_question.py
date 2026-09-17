"""NL proposal plus an explicit public intent family -> shared strong policy.

The complete family is a separate host contract, never inferred from top-K or
model confidence. Legacy unrestricted-NL workers retain their prior behavior.
"""
from dataclasses import replace
import json
import time

from xgap.agent.intent_certificate import IntentFamily, TerminalContract, canonical, fingerprint, rational
from xgap.agent.intent_execution import family_runtime
from xgap.agent.intent_strong import FamilyInformationPolicy, run_strong_intent
from xgap.agent.strong_planning import ResourceUsage, StrongSearchLimits
from xgap.semantic.interpretation_candidates import interpret_candidate_question


PROFILE='nl-finite-family-strong-v1'


def family_configuration(raw, question):
    if (set(raw)!={'schema_version','question_sha256','family','information_policy','search_limits',
                    'performance_epsilon','propose_with_model'} or raw['schema_version']!='xgap-family-strong-profile-v1'
            or raw['question_sha256']!=fingerprint(question) or type(raw['propose_with_model']) is not bool):
        raise ValueError('Family profile schema or question identity mismatch')
    family=IntentFamily.from_dict(raw['family'])
    info=dict(raw['information_policy'])
    if 'additional_scopes' in info:info['additional_scopes']=tuple(tuple(s) for s in info['additional_scopes'])
    limits=dict(raw['search_limits'])
    if 'resources' in limits:limits['resources']=ResourceUsage(**limits['resources'])
    epsilon=rational(raw['performance_epsilon'])
    return family,FamilyInformationPolicy(**info),StrongSearchLimits(**limits),epsilon,raw['propose_with_model']


def run_nl_family_question(request, provider, *, mode, policy, family, user_oracle,
                            information=FamilyInformationPolicy(), epsilon='0',
                            limits=StrongSearchLimits(), propose_with_model=True,
                            sources, backends, backend_clients, on_user_observation=None):
    started=time.perf_counter()
    r=dict(schema_version='xgap-nl-strong-answer-v1',profile_id=PROFILE,mode=mode,success=False,status='preparing',
        answer_rows=None,model_calls=0,input_tokens=0,output_tokens=0,final_plan_executions=0,
        backend_remote_calls=0,probe_calls=0,fit_calls=0,automatic_retries=0,
        interpretation=None,interpretation_ms=0.0,grounding_ms=0.0,usage_complete=True,
        user_intent_verified=False,answer_quality_verified=False,clarification_calls=0,
        input_scope='NL plus a public finite intent contract and private metered authority; not open-domain NL')
    try:
        if mode not in ('exact','performance') or type(propose_with_model) is not bool:
            raise ValueError('Explicit mode and proposal policy required')
        if request.required_constraints or not isinstance(request.context.get('source_schema'),dict):
            raise ValueError('Family profile needs generic schema and its own frozen hard-constraint skeleton')
        if user_oracle.family.identity!=family.identity:
            raise ValueError('Private oracle and public family differ')
        r['oracle_preflight']=user_oracle.preflight(request.question)
        prepare,execute,capabilities,capability_ms=family_runtime(family,source_schema=request.context['source_schema'],
            sources=sources,backends=backends,backend_clients=backend_clients,physical_profile=policy)
        r.update(capability_lookup=capabilities,capability_lookup_ms=capability_ms)
        # One common optional proposal. It never removes possibilities or adds
        # authority. Paying it here is reported; no claim to saving this call.
        if propose_with_model:
            if provider is None:raise ValueError('Configured NL proposal requires a provider')
            proposed=interpret_candidate_question(request,provider,candidate_cap=policy.candidate_cap)
            known=not proposed.get('usage_unavailable',False)
            r.update(interpretation=proposed,interpretation_ms=proposed['elapsed_ms'],
                model_calls=proposed['external_calls'] if proposed.get('external_call_count_complete',True) else None,
                input_tokens=proposed['input_tokens'] if known else None,
                output_tokens=proposed['output_tokens'] if known else None,
                usage_complete=known and proposed.get('external_call_count_complete',True))
        else:
            r['interpretation_status']='explicit public-family deterministic entry; model proposal disabled'
        # Frozen structural work ordering is an ordinal heuristic, not measured
        # latency, semantic belief or a trained estimator. All meanings survive.
        def work(i):
            query=json.loads(family.candidates[i].query_json)
            return ((query['path'] or {}).get('max_hops',0),len(query['edges']),i)
        order=tuple(sorted(range(len(family.candidates)),key=work))
        core=run_strong_intent(request.question,TerminalContract(family,mode=mode,epsilon=epsilon),user_oracle,
            prepare=prepare,execute=execute,information=information,candidate_order=order,limits=limits,
            on_observation=on_user_observation)
        usage={k:r[k] for k in ('model_calls','input_tokens','output_tokens','usage_complete')}
        r.update(core);r.update(usage);r['schema_version']='xgap-nl-strong-answer-v1'
        r['profile_id']=PROFILE;r['family_strong']=core
        cert=core.get('terminal_certificate')
        r.update(semantic_discrepancy_upper_bound=cert['upper_bound'] if cert else None,
            discrepancy_status='certified_structured_intent' if cert else 'not_certified',
            acquisition_policy_scope='same full/scoped actions and bounded AND/OR search; terminal contract differs',
            physical_ranking_scope='fixed path-depth/edge-count ordinal; not calibrated latency',
            clarification_ledger=core['ledger'],structure_validation='public_finite_family_contract')
    except Exception as error:
        r.update(status='family_configuration_or_execution_failed',error_type=type(error).__name__,error=str(error))
    finally:r['end_to_end_ms']=(time.perf_counter()-started)*1000
    return r
