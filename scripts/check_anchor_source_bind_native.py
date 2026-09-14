#!/usr/bin/env python3
"""One predeclared binding component execution per tiny deployment; no probing."""
import argparse
import json
from pathlib import Path
import subprocess
import threading
import time

from check_compact_roles_native import PREPARED, PREPARED_SHA
from native_store_session import NativeStoreSession
from rdf_tdb_session import RdfTdbSession
from prepare_rdf_tdb import REPO, stream_pin
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.external_federation import deadline
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, native_clients
from xgap.experiments.one_shot_records import CapturingClient, write_once
from xgap.experiments.row_normalization import normalize_rows
from xgap.experiments.schema_source_routing import source_assignments
from xgap.runtime.one_shot_planning import prepare_one_shot_domain
from xgap.runtime.scheduler import FederatedScheduler
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


def main(output, strategy='anchor_fanout_bind', deployments=('native','rdf')):
    if strategy not in ('anchor_fanout_bind','progressive_entity_bind'):
        raise ValueError('Unknown component strategy')
    if not deployments or len(set(deployments))!=len(deployments) or set(deployments)-{'native','rdf'}:
        raise ValueError('Each supported deployment may run at most once')
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    result={'schema_version':('xgap-progressive-binding-native-component-v1' if strategy=='progressive_entity_bind'
                             else 'xgap-anchor-fanout-native-component-v1'),'success':False,
        'model_calls':0,'fit_calls':0,'data_loads':0,'catalog_builds':0,'baseline_calls':0,
        'maximum_plan_executions':len(deployments),'automatic_retries':0,'paper_result':False,
        'selection':f'predeclared {strategy} component gate, not online estimated selection',
        'cases':[],'closures':[]};session=None
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):
            raise ValueError('Commit before native component gate')
        result['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
        fixture=REPO/'tests/fixtures/compact_anchor_v1.json'
        case=json.loads(fixture.read_text())['cases'][0]
        result['intent']=write_once(root/'intent.json',{'fixture':stream_pin(fixture),
            'deployments':list(deployments),'strategy':strategy,
            'one_execution_each':True,'estimated_alternatives_executed':0})
        for deployment in deployments:
            target=root/deployment;target.mkdir()
            options={'root':target/'session','discard_serving_copies':True,
                'budget':SourceObservationBudget(max_calls=64,request_bytes=1024**2,
                    phase_request_bytes=4*1024**2,response_bytes=2*1024**2,
                    phase_response_bytes=8*1024**2,timeout_seconds=20)}
            if deployment=='native':
                session=NativeStoreSession(prepared_path=PREPARED,prepared_sha256=PREPARED_SHA,**options)
            else:
                session=RdfTdbSession(prepared_path='/Users/anthonyche/xgap-data/rdf-tdb-tiny-20260913-v1/receipt.json',
                    prepared_sha256='cf4190cb71ec7ad635c34ab9a852b3f6bfe14d649b2048c9f897905564e2577d',
                    prepared_input_sha256='5e8d77a2a70789e677258f31baddbda49a4ea67d972a8019c974df16bdef4c0c',**options)
            with deadline(120):session.start()
            at=time.perf_counter()
            doc,model,_,sources,backends,specs,modes=FrozenOneShotProfile.load(
                session.profile['path'],expected_sha256=session.profile['sha256']).materialize()
            program,_=lower_compact_query(case['gold_compact'],doc['source_schema'],version='v2')
            slots,_=source_assignments(program,doc['source_schema'],sources)
            candidates,domain=prepare_one_shot_domain(program,operator_sources=slots,sources=sources,
                backends=backends,policy=modes['performance'][0],
                progressive_bindings=strategy=='progressive_entity_bind')
            selected=next(c for c in candidates if c.strategy_id.endswith('/'+strategy))
            predictions=[{'strategy':c.strategy_id,'estimated_ms':model.predict(c.plan).estimated_ms} for c in candidates]
            available=[p for p in predictions if p['estimated_ms'] is not None]
            if not any(p['strategy']==selected.strategy_id for p in available):
                raise ValueError('Frozen model does not support the new component')
            write_once(target/'selection.json',{'domain':domain,'predictions':predictions,
                'selected_plan':selected.plan.to_dict(),'selected_strategy':selected.strategy_id,
                'selection_policy':'predeclared component test',
                'ordinary_estimated_winner':min(available,key=lambda p:(p['estimated_ms'],p['strategy']))['strategy']})
            registry=BackendPluginRegistry();records=[];lock=threading.Lock()
            for name,client in native_clients(specs).items():
                registry.register(NativeBackendPlugin(name,CapturingClient(client,target,records,lock)))
            phase=strategy+':'+deployment;session.observer.set_phase(phase)
            write_once(target/'execution-intent.json',{'selected_plan_id':selected.plan.plan_id,'maximum_final_executions':1})
            start=time.perf_counter()
            with deadline(120):execution=FederatedScheduler(BackendInvokeTool(registry)).execute(selected.plan)
            execution_ms=(time.perf_counter()-start)*1000
            result_pin=write_once(target/'execution.json',execution.to_dict())
            observed=session.observer.seal_phase(phase)
            outcome={'success':execution.success,'result':result_pin,'source_observations':observed,
                'execution_ms':execution_ms,'online_ms_before_outcome_seal':(time.perf_counter()-at)*1000,
                'source_calls':observed['requests'],'response_bytes':observed['response_body_bytes'],
                'candidate_count':len(candidates),'construction_bound':domain['construction_bound'],
                'selected_strategy':selected.strategy_id,'strategy_details':selected.plan.metadata['strategy_details'],
                'ordinary_estimated_winner':min(available,key=lambda p:(p['estimated_ms'],p['strategy']))['strategy']}
            outcome_pin=write_once(target/'outcome.json',outcome)
            session.observer.release_phase(phase,outcome_pin)
            # Reference comparison is after the original execution result is sealed.
            actual=normalize_rows(list(execution.final_rows),case['normalization']) if execution.success else None
            expected=normalize_rows(case['expected_rows'],case['normalization'])
            score=write_once(target/'score.json',{'answer_em':int(actual==expected),'actual':actual,'expected':expected,
                'reference':stream_pin(fixture),'scope':'tiny component correctness only'})
            result['cases'].append({'deployment':deployment,'outcome':outcome_pin,'score':score,
                'answer_em':int(actual==expected),'success':execution.success and actual==expected,
                'execution_ms':execution_ms,'source_calls':observed['requests'],'response_bytes':observed['response_body_bytes']})
            result['closures'].append(session.close());session=None
            if not result['cases'][-1]['success']:raise ValueError('Native component correctness failed')
        result['success']=len(result['cases'])==len(deployments) and all(c['success'] for c in result['cases'])
    except Exception as error:
        result.update(error_type=type(error).__name__,error=str(error))
    finally:
        if session:result['closures'].append(session.close())
        result['success'] &= all(all(c[k] for k in ('owned_groups_drained','owned_processes_terminal','observer_stopped'))
                                 for c in result['closures'])
        pin=write_once(root/'receipt.json',result)
    print(json.dumps({'success':result['success'],'receipt':pin,'cases':result['cases'],'error':result.get('error')}))
    return 0 if result['success'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    parser.add_argument('--strategy',choices=('anchor_fanout_bind','progressive_entity_bind'),default='anchor_fanout_bind')
    parser.add_argument('--deployments',nargs='+',choices=('native','rdf'),default=('native','rdf'))
    with deadline(600):raise SystemExit(main(**vars(parser.parse_args())))
