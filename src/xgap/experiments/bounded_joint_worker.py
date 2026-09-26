"""Current durable single-query worker. Ownership and study limits belong to its caller.

No evaluation labels enter this worker. Private intent is only accessed through
metered user actions; result scoring is a separate post-execution operation.
"""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import threading
import time

from xgap.api import answer, answer_controlled, answer_unified, answer_unified_controlled
from xgap.agent.scope_authority import QueryIntentAuthority, ScopedQueryUser
from xgap.agent.intent_strong import FamilyInformationPolicy
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.experiments.evidence_store import write_json_evidence
from xgap.experiments.interpretation_diagnostics import summarize_interpretation
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned, native_clients
from xgap.experiments.one_shot_records import CapturingClient, write_once
from xgap.experiments.one_shot_toy import _DurableRecordingProvider
from xgap.llm.compact_interpretation import CompactInterpretationProviderConfig
from xgap.planning.joint_cost import JointCostProfile
from xgap.semantic.intent_scope import ScopePolicy
from xgap.experiments.bounded_joint_contract import METHODS, TRACK, CONTROLLED_TRACK, METRICS, load_configuration
from xgap.experiments import unified_contract as unified_run


def run(*, profile_path, profile_sha256, request_path, request_sha256, scope_path, scope_sha256,
        oracle_path, oracle_sha256, mode, output, epsilon='0', provider_override=None,
        information=FamilyInformationPolicy(), limits=StrongSearchLimits(), costs=JointCostProfile(),
        method=None, joint_config_path=None, joint_config_sha256=None,controlled_state_path=None,controlled_state_sha256=None):
    unified=method in unified_run.METHODS
    root=Path(output);root.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter();captures=[];active=False;config={};controlled=None
    receipt=dict(schema_version='xgap-bounded-joint-worker-v1',success=False,status='preparing',mode=mode,
        request_sha256=request_sha256,profile_sha256=profile_sha256,scope_sha256=scope_sha256,
        oracle_sha256=oracle_sha256,model_calls=0,final_plan_executions=0,automatic_retries=0,
        reference_available_to_worker=False,source_ownership='caller must enforce study budgets and close services')
    try:
        if (unified and mode is not None) or (not unified and mode not in ('exact','performance')):raise ValueError('Unknown or mixed mode')
        if method is not None:
            if not unified and (method not in METHODS or method != 'xgap-bounded-joint-'+mode):
                raise ValueError('Current method/mode mismatch')
            receipt.update(schema_version='xgap-nl-method-worker-v1',method=method,
                track=(unified_run.CONTROLLED_TRACK if controlled_state_path else unified_run.TRACK) if unified else
                      CONTROLLED_TRACK if controlled_state_path else TRACK,controlled_state_sha256=controlled_state_sha256,
                joint_config_sha256=joint_config_sha256,top_level_attempts=0,
                alternative_executions=0,fit_calls=0,probe_calls=0)
        raw=json.loads(read_pinned(request_path,request_sha256))
        if set(raw)!={'schema_version','question_id','question','population','exposure'}:
            raise ValueError('Public input contains fields outside the NL request contract')
        receipt.update({k:raw[k] for k in ('question_id','population','exposure')})
        if controlled_state_path or controlled_state_sha256:
            if not controlled_state_path or not controlled_state_sha256:raise ValueError('Pinned controlled state required')
            from xgap.experiments.controlled_state import read_state
            controlled=read_state(json.loads(read_pinned(controlled_state_path,controlled_state_sha256)),raw['question'])
        if joint_config_path is not None or joint_config_sha256 is not None:
            if not joint_config_path or not joint_config_sha256 or provider_override is not None:
                raise ValueError('Pinned configuration requires both identity fields and no provider override')
            loader=unified_run.load_configuration if unified else load_configuration
            config,information,limits,costs=loader(joint_config_path,joint_config_sha256)
            if unified:unified_run.validate_method(method,limits)
            epsilon=limits.epsilon if unified else '0' if mode=='exact' else config['epsilon']
            if config['provider']=='development_toy_template' and controlled is None:
                if raw['exposure']!='development':
                    raise ValueError('Toy provider is restricted to explicit development requests')
                from xgap.experiments.bounded_joint_toy import TemplateProposalProvider, FIXTURE
                provider_override=TemplateProposalProvider(json.loads((FIXTURE/'fixture.json').read_text())['query_template'])
        receipt.update(epsilon=epsilon,execution_kind='configured_native',
            proposal_kind='frozen_compact_model' if provider_override is None else 'explicit_development_provider')
        profile=FrozenOneShotProfile.load(profile_path,expected_sha256=profile_sha256)
        materialized=profile.materialize()
        doc,estimator,_,sources,backends,specs,modes=materialized
        receipt['dataset']=doc['dataset']
        request=profile.request(raw,'performance',materialized)
        physical,provider=modes['performance']
        if config.get('provider') == 'frozen_compact_model_equivalence_v1':
            from xgap.experiments.compact_equivalence_profile import adapt_compact_provider
            if not unified or provider_override is not None or controlled is not None:
                raise ValueError('Compact equivalence adapter is for declared unified NL runs only')
            provider, adapter = adapt_compact_provider(provider, doc['source_schema'], backends)
            receipt['provider_adapter'] = adapter
        scope=ScopePolicy.from_dict(json.loads(read_pinned(scope_path,scope_sha256)))
        # No oracle preflight read: a scope confirmation is the first paid access.
        authority=QueryIntentAuthority(Path(oracle_path),oracle_sha256)
        if controlled is not None:
            receipt.update(proposal_kind='frozen_controlled_state',initial_state=controlled[2])
        elif provider_override is None:
            if not isinstance(provider.config, CompactInterpretationProviderConfig):
                raise ValueError('Current worker needs a frozen compact proposal provider')
            budget=provider.token_guard.check(provider.build_request_payload(request),call_kind='generation')
            if not budget['passed']:raise ValueError('Frozen proposal token budget exceeded')
            if not os.environ.get(provider.config.api_key_env):raise ValueError('Configured model credential unavailable')
            provider=_DurableRecordingProvider(provider,root/'interpretation.json')
        else:
            provider=provider_override
        write_once(root/'intent.json',dict(request=request.to_dict(),scope_policy=scope.to_dict(),
            information_policy=asdict(information),search_limits=asdict(limits),
            cost_profile=costs.to_dict(),provider_kind=receipt['proposal_kind'],
            controlled_state_sha256=controlled_state_sha256,execution_cost_feedback=config.get('execution_cost_feedback',True),
            epsilon=epsilon,mode=mode,maximum_final_plan_executions=1,maximum_user_calls=information.max_calls))
        lock=threading.Lock()
        clients={name:CapturingClient(client,root,captures,lock,retain_payloads=False,compress=True)
                 for name,client in native_clients(specs).items()}
        records=[]
        def observed(record):
            records.append(write_once(root/f'user-{len(records):02}.json',record))
        active=True
        options=dict(mode=mode,epsilon=epsilon,physical_profile=physical,sources=sources,backends=backends,backend_clients=clients,
            estimator=estimator,information=information,limits=limits,costs=costs,on_user_observation=observed,
            execution_cost_feedback=config.get('execution_cost_feedback',True))
        if unified:
            options=dict(physical_profile=physical,sources=sources,backends=backends,backend_clients=clients,
                estimator=estimator,information=information,costs=costs,on_user_observation=observed,settings=limits)
            if controlled is None:
                core=answer_unified(request,provider,scope_policy=scope,authority=authority,**options)
            else:
                family,initial,_=controlled
                clues={family.slots[i].name:json.loads(value) for i,value in initial}
                core=answer_unified_controlled(request.question,family,ScopedQueryUser(family,Path(oracle_path),oracle_sha256),
                    initial_clues=clues,source_schema=request.context['source_schema'],**options)
        elif controlled is None:
            core=answer(request,provider,scope_policy=scope,authority=authority,**options)
        else:
            family,initial,_=controlled
            core=answer_controlled(request.question,family,ScopedQueryUser(family,Path(oracle_path),oracle_sha256),
                initial_observations=initial,source_schema=request.context['source_schema'],**options)
        active=False
        receipt.update({k:core.get(k) for k in ('success','status','model_calls','input_tokens','output_tokens',
            'final_plan_executions',*METRICS,*(unified_run.METRICS if unified else ()))})
        receipt.update(top_level_attempts=core['final_plan_executions'],
            search=(core.get('joint_policy') or core).get('search'),
            controlled_processing_ms=core.get('controlled_processing_ms'),
            execution_cost_feedback=config.get('execution_cost_feedback',True),
            error=core.get('error'),error_type=core.get('error_type'),
            proposal_failure_category=core.get('proposal_failure_category'),
            interpretation_diagnostics=summarize_interpretation(core))
        if unified:
            receipt.update(unified_run.metric_values(core))
            receipt.update(algorithm_profile='unified-lookahead-v1',terminal_settings=config.get('settings'),
                search=None,execution_cost_feedback=None)
        receipt.update(dataset=doc['dataset'],question_id=raw['question_id'],user_observations=records,
            backend_calls=len(captures),core=write_json_evidence(root/'core.json.gz',core),
            result=write_json_evidence(root/'answer.json.gz',dict(answer_format='json_rows',answer=core['answer_rows'])))
    except Exception as error:
        receipt.update(success=False,status='worker_failed',error_type=type(error).__name__,error=str(error))
        if active:receipt.update(model_calls=None,input_tokens=None,output_tokens=None,
            final_plan_executions=None,top_level_attempts=None,usage_complete=False)
    finally:
        receipt['backend_calls']=len(captures)
        receipt['backend_ledger']=write_once(root/'backend-ledger.json',captures)
        receipt['worker_ms']=(time.perf_counter()-started)*1000
        write_once(root/'receipt.json',receipt)
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('profile','request','scope','oracle'):
        parser.add_argument('--'+name+'-path',required=True)
        parser.add_argument('--'+name+'-sha256',required=True)
    parser.add_argument('--mode',required=True,choices=('exact','performance'))
    parser.add_argument('--epsilon',default='0');parser.add_argument('--output',required=True)
    result=run(**vars(parser.parse_args()))
    print(json.dumps({k:result.get(k) for k in ('success','status','model_calls','final_plan_executions','backend_calls')}))
    return 0 if result['success'] else 1


if __name__=='__main__':raise SystemExit(main())
