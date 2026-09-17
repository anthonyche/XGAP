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

from xgap.api import answer
from xgap.agent.scope_authority import QueryIntentAuthority
from xgap.agent.intent_strong import FamilyInformationPolicy
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.experiments.evidence_store import write_json_evidence
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned, native_clients
from xgap.experiments.one_shot_records import CapturingClient, write_once
from xgap.experiments.one_shot_toy import _DurableRecordingProvider
from xgap.llm.compact_interpretation import CompactInterpretationProviderConfig
from xgap.planning.joint_cost import JointCostProfile
from xgap.semantic.intent_scope import ScopePolicy


def run(*, profile_path, profile_sha256, request_path, request_sha256, scope_path, scope_sha256,
        oracle_path, oracle_sha256, mode, output, epsilon='0', provider_override=None,
        information=FamilyInformationPolicy(), limits=StrongSearchLimits(), costs=JointCostProfile()):
    root=Path(output);root.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter();captures=[];active=False
    receipt=dict(schema_version='xgap-bounded-joint-worker-v1',success=False,status='preparing',mode=mode,
        request_sha256=request_sha256,profile_sha256=profile_sha256,scope_sha256=scope_sha256,
        oracle_sha256=oracle_sha256,model_calls=0,final_plan_executions=0,automatic_retries=0,
        reference_available_to_worker=False,source_ownership='caller must enforce study budgets and close services')
    try:
        if mode not in ('exact','performance'):raise ValueError('Unknown mode')
        profile=FrozenOneShotProfile.load(profile_path,expected_sha256=profile_sha256)
        materialized=profile.materialize()
        doc,estimator,_,sources,backends,specs,modes=materialized
        raw=json.loads(read_pinned(request_path,request_sha256))
        if set(raw)!={'schema_version','question_id','question','population','exposure'}:
            raise ValueError('Public input contains fields outside the NL request contract')
        request=profile.request(raw,'performance',materialized)
        physical,provider=modes['performance']
        scope=ScopePolicy.from_dict(json.loads(read_pinned(scope_path,scope_sha256)))
        # No oracle preflight read: a scope confirmation is the first paid access.
        authority=QueryIntentAuthority(Path(oracle_path),oracle_sha256)
        if provider_override is None:
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
            cost_profile=costs.to_dict(),provider_kind='frozen_compact_model' if provider_override is None else 'explicit_development_provider',
            epsilon=epsilon,mode=mode,maximum_final_plan_executions=1,maximum_user_calls=information.max_calls))
        lock=threading.Lock()
        clients={name:CapturingClient(client,root,captures,lock,retain_payloads=False,compress=True)
                 for name,client in native_clients(specs).items()}
        records=[]
        def observed(record):
            records.append(write_once(root/f'user-{len(records):02}.json',record))
        active=True
        core=answer(request,provider,mode=mode,epsilon=epsilon,scope_policy=scope,authority=authority,
            physical_profile=physical,sources=sources,backends=backends,backend_clients=clients,
            estimator=estimator,information=information,limits=limits,costs=costs,on_user_observation=observed)
        active=False
        receipt.update({k:core.get(k) for k in ('success','status','model_calls','input_tokens','output_tokens',
            'final_plan_executions','total_user_calls','clarification_calls','disclosed_coordinates','planning_cpu_ms',
            'execution_ms','end_to_end_ms','scope_confirmed','candidate_count','terminal_certificate','strong_plan')})
        receipt.update(dataset=doc['dataset'],question_id=raw['question_id'],user_observations=records,
            backend_calls=len(captures),core=write_json_evidence(root/'core.json.gz',core),
            result=write_json_evidence(root/'answer.json.gz',dict(answer_format='json_rows',answer=core['answer_rows'])))
    except Exception as error:
        receipt.update(success=False,status='worker_failed',error_type=type(error).__name__,error=str(error))
        if active:receipt.update(model_calls=None,final_plan_executions=None,usage_complete=False)
    finally:
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
