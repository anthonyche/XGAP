#!/usr/bin/env python3
"""Fixed tiny physical-cost diagnostic, separate from ordinary query planning.

Default is offline preflight. --execute uses one owned frozen-store session and
the six predeclared phases; no fitting, model call, retry or result-driven plan.
"""
import argparse
import json
from pathlib import Path
import subprocess
import threading
import time

from check_compact_roles_native import PREPARED, PREPARED_SHA
from native_store_session import NativeStoreSession
from prepare_rdf_tdb import REPO, stream_pin
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.external_federation import deadline
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, native_clients, read_pinned
from xgap.experiments.one_shot_records import CapturingClient, write_once
from xgap.experiments.row_normalization import normalize_rows
from xgap.experiments.schema_source_routing import source_assignments
from xgap.runtime.one_shot_planning import prepare_one_shot_domain
from xgap.runtime.scheduler import FederatedScheduler
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


STRATEGIES=('coordinator','anchor_fanout_bind','progressive_entity_bind')
PHASES=tuple((f'first-{s}',s,'first_exposure') for s in STRATEGIES)+tuple(
    (f'measured-{s}',s,'after_all_three_first_exposures') for s in reversed(STRATEGIES))


def prepare():
    receipt=json.loads(read_pinned(PREPARED,PREPARED_SHA))
    parent=receipt['profile'];profile=FrozenOneShotProfile.load(parent['path'],expected_sha256=parent['sha256'])
    doc,model,_,sources,backends,_,modes=profile.materialize()
    fixture=REPO/'tests/fixtures/compact_anchor_v1.json';case=json.loads(fixture.read_text())['cases'][0]
    program,_=lower_compact_query(case['gold_compact'],doc['source_schema'],version='v2')
    slots,_=source_assignments(program,doc['source_schema'],sources)
    candidates,domain=prepare_one_shot_domain(program,operator_sources=slots,sources=sources,
        backends=backends,policy=modes['performance'][0],progressive_bindings=True)
    plans={s:next(c.plan for c in candidates if c.strategy_id=='placement-0/'+s) for s in STRATEGIES}
    predictions={s:model.predict(plan).to_dict() for s,plan in plans.items()}
    if any(sum(n.kind.value.startswith('remote_') for n in p.nodes)>16 for p in plans.values()):
        raise ValueError('Diagnostic source-call bound exceeded')
    if any(p['estimated_ms'] is None for p in predictions.values()):raise ValueError('Frozen model score unavailable')
    return case,plans,predictions,{'fixture':stream_pin(fixture),'profile':parent,'prepared':stream_pin(PREPARED),
        'domain':domain,'model_sha256':model.model_sha256,'source_statistics_sha256':model.statistics.sha256,
        'source_schema':doc['source_schema']}


def main(output,execute=False):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter();session=None
    receipt={'schema_version':'xgap-practical-cost-diagnostic-v1','success':False,'execute':execute,
        'model_calls':0,'fit_calls':0,'baseline_calls':0,'data_loads':0,'catalog_builds':0,
        'automatic_retries':0,'paper_result':False,'phases':[],'closures':[],
        'scope':'predeclared development diagnostic, never current-query observed-winner planning'}
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):
            raise ValueError('Commit the fixed diagnostic before preflight or native execution')
        receipt['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
        case,plans,predictions,inputs=prepare()
        receipt['intent']=write_once(root/'intent.json',{'inputs':inputs,'phases':PHASES,
            'maximum_plan_executions':6 if execute else 0,'maximum_source_calls':96 if execute else 0,
            'predictions':predictions,'plans':{s:p.to_dict() for s,p in plans.items()},
            'estimated_rank':sorted(STRATEGIES,key=lambda s:predictions[s]['estimated_ms']),
            'first_exposure_cost_policy':'retained separately; no claim this warms every engine state',
            'timing_policy':'same owned session, reverse second order, one measured observation per strategy',
            'labels_not_used_for_selection_or_fit':True,'formal_statistical_inference':False})
        if not execute:
            receipt.update(success=True,status='preflight_passed',source_calls=0)
            return 0
        session=NativeStoreSession(root=root/'session',prepared_path=PREPARED,prepared_sha256=PREPARED_SHA,
            discard_serving_copies=True,budget=SourceObservationBudget(max_calls=16,request_bytes=1024**2,
                phase_request_bytes=4*1024**2,response_bytes=2*1024**2,phase_response_bytes=8*1024**2,timeout_seconds=20))
        with deadline(120):session.start()
        serving=FrozenOneShotProfile.load(session.profile['path'],expected_sha256=session.profile['sha256']).materialize()
        if serving[1].model_sha256!=inputs['model_sha256'] or serving[0]['source_schema']!=inputs['source_schema']:
            raise ValueError('Serving session differs from the frozen diagnostic')
        receipt['serving']=session.ready_pin
        for phase,strategy,exposure in PHASES:
            target=root/phase;target.mkdir();plan=plans[strategy]
            registry=BackendPluginRegistry();records=[];lock=threading.Lock()
            for name,client in native_clients(serving[5]).items():
                registry.register(NativeBackendPlugin(name,CapturingClient(client,target,records,lock,retain_payloads=False)))
            write_once(target/'intent.json',{'phase':phase,'strategy':strategy,'plan_id':plan.plan_id,
                'maximum_plan_executions':1,'exposure':exposure})
            session.observer.set_phase(phase);at=time.perf_counter()
            with deadline(120):result=FederatedScheduler(BackendInvokeTool(registry)).execute(plan)
            elapsed=(time.perf_counter()-at)*1000
            pin=write_once(target/'execution.json',result.to_dict())
            observed=session.observer.seal_phase(phase)
            out={'strategy':strategy,'phase':phase,'exposure':exposure,'success':result.success,
                'execution':pin,'execution_ms':elapsed,'scheduler_ms':result.elapsed_ms,
                'source_observations':observed,'source_calls':observed['requests'],
                'response_bytes':observed['response_body_bytes'],'ledger':records}
            outcome=write_once(target/'outcome.json',out);session.observer.release_phase(phase,outcome)
            # Gold is checked only after the original outcome has been sealed.
            actual=normalize_rows(list(result.final_rows),case['normalization']) if result.success else None
            expected=normalize_rows(case['expected_rows'],case['normalization'])
            score=write_once(target/'score.json',{'answer_em':int(actual==expected),'actual':actual,'expected':expected,
                'reference':inputs['fixture'],'scope':'deterministic tiny component, not interpretation effectiveness'})
            receipt['phases'].append({k:v for k,v in out.items() if k not in ('ledger','source_observations')}|
                {'outcome':outcome,'score':score,'answer_em':int(actual==expected)})
            print(json.dumps({'phase':phase,'success':result.success,'answer_em':int(actual==expected),
                'execution_ms':elapsed,'source_calls':observed['requests']}),flush=True)
            if not result.success or actual!=expected:raise ValueError('Fixed diagnostic stopped after failed phase')
        measured=[p for p in receipt['phases'] if p['exposure']=='after_all_three_first_exposures']
        receipt.update(success=True,status='completed',source_calls=sum(p['source_calls'] for p in receipt['phases']),
            measured_rank=sorted((p['strategy'] for p in measured),key=lambda s:next(p['execution_ms'] for p in measured if p['strategy']==s)),
            general_ranking_verified=False)
    except Exception as error:
        receipt.update(status='failed',error_type=type(error).__name__,error=str(error))
    finally:
        if session:receipt['closures'].append(session.close())
        receipt['success'] &= all(all(c[k] for k in ('owned_groups_drained','owned_processes_terminal','observer_stopped')) for c in receipt['closures'])
        receipt['elapsed_ms']=(time.perf_counter()-started)*1000
        pin=write_once(root/'receipt.json',receipt)
        print(json.dumps({'success':receipt['success'],'receipt':pin,'error':receipt.get('error')}),flush=True)
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    parser.add_argument('--execute',action='store_true')
    with deadline(600):raise SystemExit(main(**vars(parser.parse_args())))
