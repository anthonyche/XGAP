#!/usr/bin/env python3
"""First ordinary NL/RDF-instance and shared NL/FedX boundary, two model calls max."""
import argparse
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
import time

REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO/'scripts'))
from check_common_rdf_trial import JAVA, FUSEKI, JARS, PINS
from run_external_federation_tiny import Processes, ready, fingerprint
from xgap.experiments.common_method_trial import run_nl_trial
from xgap.experiments.common_row_score import score_trial
from xgap.experiments.external_federation import SourceObserver, deadline
from xgap.experiments.finbench_one_shot_population import normalization
from xgap.experiments.finbench_rdf import FAMILIES
from xgap.experiments.m15_native_services import LoopbackPortReservations, _fuseki_server_configuration
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.owned_resources import OwnedProcess
from xgap.experiments.process_guard import ProcessBudget

BASE=Path('/Users/anthonyche/xgap-data/disjoint-rdf-trial-20260913-v2/rdf-profile-v2/profile.json')
BASE_SHA='ef8131b3316f2ea83921a3b857576347f4d6058d4d52285b32b7a461cfa7ed89'
FIXTURE=REPO/'datasets/financial_nl_tiny_v1'
REQUEST_SHA='e16e8ef2a97fac5f636921d5060562c883ce9e388f9daf701b2f842753b960f0'
REFERENCE_SHA='1e617d2be66bf93bfc372b14e4cc04388476fdb7ce45f1f231044bacb56a3691'


def run_cell(root,method,request,reference):
    root.mkdir();processes=Processes(root);observer=None;ports=None
    record={'method':method,'outcome_recorded':False,'success':False};at=time.perf_counter()
    try:
        doc=json.loads(read_pinned(BASE,BASE_SHA));loads=doc['offline']['rdf_loads']
        ports=LoopbackPortReservations.acquire(3)
        routes={'/'+name+'/sparql':f'http://127.0.0.1:{ports.ports[i]}/{name}/sparql' for i,name in enumerate(('graph','control'))}
        observer=SourceObserver(routes,root/'source-observations',max_calls=256,timeout_seconds=3)
        for spec in doc['backends'].values():spec['client']['url']=observer.base_url
        doc['estimator']['path']=str(BASE.parent/doc['estimator']['path'])
        doc['offline']['serving_endpoint_parent']={'path':str(BASE),'sha256':BASE_SHA}
        profile=write_once(root/'profile.json',doc)
        FrozenOneShotProfile.load(profile['path'],expected_sha256=profile['sha256'])
        handles=[]
        for i,name in enumerate(('graph','control')):
            state=root/('fuseki-'+name);state.mkdir()
            (state/'config.ttl').write_text(_fuseki_server_configuration(query_timeout_seconds=15))
            port=ports.ports[i];ports.release(i)
            process=processes.start('source-'+name,[str(FUSEKI/'fuseki-server'),'--localhost','--port',str(port),
                '--file',loads[name]['path'],'/'+name],cwd=FUSEKI,
                env={'JAVA':JAVA,'FUSEKI_HOME':str(FUSEKI),'FUSEKI_BASE':str(state),'JVM_ARGS':'-Xms128m -Xmx512m'})
            ready(process,port);handles.append(OwnedProcess(name,'source',process))
        endpoint=None
        if method=='fedx':
            observer.set_phase(method+':initialization');port=ports.ports[2];ports.release(2)
            endpoints=[observer.base_url+'/'+n+'/sparql' for n in ('graph','control')]
            host=processes.start('fedx',[JAVA,'-Xms128m','-Xmx512m','-jar',str(JARS['fedx']),str(port),'120',*endpoints])
            ready(host,port);handles.append(OwnedProcess('fedx','method_host',host))
            endpoint=f'http://127.0.0.1:{port}/sparql'
            write_once(root/'initialization.json',observer.snapshot(method+':initialization'))
        record['offline_fresh_serving_ms']=(time.perf_counter()-at)*1000
        result=run_nl_trial(request_path=request['path'],request_sha256=request['sha256'],profile_path=profile['path'],
            profile_sha256=profile['sha256'],method=method,output=root/'trial',owned_services=handles,observer=observer,
            endpoint=endpoint,budget=ProcessBudget(wall_seconds=180))
        score=score_trial(result['receipt']['path'],receipt_sha256=result['receipt']['sha256'],
            reference_path=reference['path'],reference_sha256=reference['sha256'],output=root/'score.json')
        record.update(outcome_recorded=True,success=result['success'],status=result['status'],answer_em=score['answer_em'],
            bag_f1=score['answer_row_multiset_f1'],trial_receipt=result['receipt'],total_online_ms=result['timing']['total_online_ms'],
            model_calls=result['model_calls'],input_tokens=result.get('input_tokens'),output_tokens=result.get('output_tokens'),
            source_requests=(result['source_observations'] or {}).get('requests'),
            source_ask_requests=(result['source_observations'] or {}).get('ask_requests'),
            quiescence=result['quiescence'],recovery_ms=result['recovery_ms'],resources=result['resources'])
    except Exception as error:record.update(error_type=type(error).__name__,error=str(error))
    finally:
        record['processes']=processes.close()
        if observer:
            observer.close();record['observer_stopped']=not observer.thread.is_alive() and observer.inflight==0
        if ports:ports.close()
        record['owned_processes_terminal']=all(p['returncode'] is not None for p in record['processes'])
        write_once(root/'cell.json',record)
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-root',required=True,type=Path)
    parser.add_argument('--read-key',action='store_true')
    parser.add_argument('--method',choices=('xgap-performance','fedx'),help='Run only this explicitly selected new boundary')
    args=parser.parse_args();methods=(args.method,) if args.method else ('xgap-performance','fedx')
    if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):raise ValueError('Commit implementation before native boundary')
    key=getpass.getpass('LLM credential (not recorded): ') if args.read_key else os.environ.get('XGAP_EXTERNAL_LLM_API_KEY')
    if not key:raise ValueError('Model credential required; no external action started')
    root=args.output_root.resolve();root.mkdir(parents=True,exist_ok=False)
    receipt={'schema_version':'xgap-shared-nl-native-v1','success':False,'runs':[],
        'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        'maximum_model_calls':len(methods),'maximum_final_queries_per_method':1,'fit_calls':0,'probe_calls':0,'automatic_retries':0,
        'baseline_algorithm_changes':0,'catalog_rebuilds':0,'summary_rebuilds':0,'paper_result':False,'formal_campaign_ready':False,
        'scope':'first two new NL boundaries on one exposed tiny meaning, independent actual model invocation per method'}
    previous=os.environ.get('XGAP_EXTERNAL_LLM_API_KEY')
    try:
        with deadline(420):
            if fingerprint(JARS['fedx'])['sha256']!=PINS['fedx']:raise ValueError('Pinned author artifact changed')
            doc=json.loads(read_pinned(BASE,BASE_SHA))
            data=read_pinned(FIXTURE/'request.json',REQUEST_SHA)
            with (root/'request.json').open('xb') as f:f.write(data)
            request=fingerprint(root/'request.json')
            ref=json.loads(read_pinned(FIXTURE/'reference.json',REFERENCE_SHA))
            ref.update(dataset=doc['dataset'],normalization=normalization(FAMILIES[0]),
                original_reference={'path':str(FIXTURE/'reference.json'),'sha256':REFERENCE_SHA},
                representation_derivation='same canonical financial facts verified in disjoint v2; reference rows unchanged')
            reference=write_once(root/'reference.json',ref)
            before=[fingerprint(p) for p in [BASE,JARS['fedx'],FIXTURE/'request.json',FIXTURE/'reference.json',
                *(Path(p['path']) for p in doc['offline']['rdf_loads'].values())]]
            write_once(root/'input-seal.json',{'files':before,'request':request,'reference':reference,
                'worker_receives_no_reference_or_gold':True,'fresh_source_session_per_method':True,
                'modes':{'xgap-performance':'K1 estimated one-plan','fedx':'shared K3 quality-first frontend, original FedX'},
                'query_budget_seconds':180,'native_fedx_query_timeout_seconds':120})
            os.environ['XGAP_EXTERNAL_LLM_API_KEY']=key;key=None
            for method in methods:
                receipt['runs'].append(run_cell(root/method,method,request,reference))
            receipt['inputs_unchanged']=[fingerprint(p['path']) for p in before]==before
            receipt['success']=all(r['outcome_recorded'] and r['owned_processes_terminal'] and r.get('observer_stopped')
                for r in receipt['runs']) and receipt['inputs_unchanged']
            receipt['all_selected_answers_exact']=all(r.get('answer_em')==1 for r in receipt['runs'])
    except BaseException as error:receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        if previous is None:os.environ.pop('XGAP_EXTERNAL_LLM_API_KEY',None)
        else:os.environ['XGAP_EXTERNAL_LLM_API_KEY']=previous
        key=None;write_once(root/'receipt.json',receipt)
    print(json.dumps(receipt));return 0 if receipt['success'] else 1


if __name__=='__main__':raise SystemExit(main())
