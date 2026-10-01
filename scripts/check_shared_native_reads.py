#!/usr/bin/env python3
"""One practical strong request validating native duplicate-read elimination."""
import argparse
import json
from pathlib import Path
import subprocess
import threading

from check_compact_roles_native import PREPARED, PREPARED_SHA
from native_store_session import NativeStoreSession
from prepare_rdf_tdb import REPO, stream_pin
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.practical_execution import run_practical_semantic_query
from xgap.agent.practical_planning import BindingEvidence, BindingState, PracticalMode, program_identity
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.external_federation import deadline
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, native_clients
from xgap.experiments.one_shot_records import CapturingClient, write_once
from xgap.experiments.row_normalization import normalize_rows
from xgap.experiments.schema_source_routing import source_assignments
from xgap.semantic.compact_lowering import lower_compact_query


def main(output,check_prefilters=False):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False);session=None
    receipt={'schema_version':'xgap-shared-native-read-gate-v1','success':False,'model_calls':0,'fit_calls':0,
        'baseline_calls':0,'catalog_builds':0,'data_loads':0,'automatic_retries':0,'maximum_final_plans':1,
        'paper_result':False,'closures':[],'scope':'one deterministic strong tiny native gate, not paired timing'}
    if check_prefilters:
        receipt.update(schema_version='xgap-necessary-source-row-filter-gate-v1',
            scope='one tiny native string/boolean source-screening boundary; final typed filters retained')
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):raise ValueError('Commit first')
        receipt['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
        fixture=REPO/'tests/fixtures/compact_anchor_v1.json';case=json.loads(fixture.read_text())['cases'][0]
        receipt['intent']=write_once(root/'intent.json',{'fixture':stream_pin(fixture),'prepared':{'path':str(PREPARED),'sha256':PREPARED_SHA},
            'mode':'performance','improve_physical':False,'expected_source_calls':11,'maximum_final_plans':1,
            'expected_prefilter_source_operators':['cq18','cq19','cq24'] if check_prefilters else None,
            'selection':'feasible strong baseline with identical-source sharing; no candidate execution'})
        session=NativeStoreSession(root=root/'session',prepared_path=PREPARED,prepared_sha256=PREPARED_SHA,
            discard_serving_copies=True,budget=SourceObservationBudget(max_calls=16,request_bytes=1024**2,
                phase_request_bytes=4*1024**2,response_bytes=2*1024**2,phase_response_bytes=8*1024**2,timeout_seconds=20))
        with deadline(120):session.start()
        doc,model,_,sources,backends,specs,_=FrozenOneShotProfile.load(session.profile['path'],expected_sha256=session.profile['sha256']).materialize()
        program,_=lower_compact_query(case['gold_compact'],doc['source_schema'],version='v2')
        assignments,_=source_assignments(program,doc['source_schema'],sources)
        state=BindingState(evidence=(BindingEvidence('$structure',program_identity(program),'trusted_request','frozen-tiny-gold-program',stream_pin(fixture)['sha256']),))
        kwargs=dict(initial_state=state,mode=PracticalMode('performance',improve_physical=False),operator_sources=assignments,
            binding_values={},sources=sources,backends=backends,estimator=model,physical_profile=OneShotPolicy(),
            limits=StrongSearchLimits(improvement_actions=0))
        preflight=run_practical_semantic_query(program,backend_clients={b:object() for b in specs},execute=False,**kwargs)
        write_once(root/'preflight.json',preflight)
        if not preflight['search']['strong']:raise ValueError('No strong policy')
        records=[];lock=threading.Lock()
        clients={b:CapturingClient(c,root,records,lock,retain_payloads=False) for b,c in native_clients(specs).items()}
        session.observer.set_phase('one-practical-request')
        with deadline(120):result=run_practical_semantic_query(program,backend_clients=clients,**kwargs)
        result_pin=write_once(root/'result.json',result);observed=session.observer.seal_phase('one-practical-request')
        outcome=write_once(root/'outcome.json',{'result':result_pin,'source_observations':observed,'ledger':records})
        session.observer.release_phase('one-practical-request',outcome)
        actual=normalize_rows(result['answer_rows'],case['normalization']) if result['success'] else None
        expected=normalize_rows(case['expected_rows'],case['normalization'])
        prefilters=result.get('execution',{}).get('physical_plan',{}).get('metadata',{}).get('source_row_prefilters',{})
        prefilters_ok=(not check_prefilters or
            (prefilters.get('native_nodes')==['cq18','cq19','cq24'] and prefilters.get('original_filters_retained') is True))
        receipt.update(result=result_pin,outcome=outcome,answer_em=int(actual==expected),
            source_row_prefilters=prefilters,prefilters_ok=prefilters_ok,
            score=write_once(root/'score.json',{'actual':actual,'expected':expected,'answer_em':int(actual==expected),'reference':stream_pin(fixture)}),
            source_calls=observed['requests'],response_bytes=observed['response_body_bytes'],
            final_plan_executions=result['final_plan_executions'],model_calls=result['model_calls'],
            end_to_end_ms=result['end_to_end_ms'],serving=session.ready_pin,
            success=(result['success'] and prefilters_ok and actual==expected and observed['requests']==11 and
                result['backend_remote_calls']==11 and result['final_plan_executions']==1 and result['model_calls']==0))
    except Exception as error:receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        if session:receipt['closures'].append(session.close())
        receipt['success'] &= all(all(c[k] for k in ('owned_groups_drained','owned_processes_terminal','observer_stopped')) for c in receipt['closures'])
        pin=write_once(root/'receipt.json',receipt)
    print(json.dumps({'success':receipt['success'],'receipt':pin,'source_calls':receipt.get('source_calls'),
        'answer_em':receipt.get('answer_em'),'error':receipt.get('error')}),flush=True)
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    parser.add_argument('--check-prefilters',action='store_true',help='Verify the added native necessary-filter boundary')
    with deadline(300):raise SystemExit(main(**vars(parser.parse_args())))
