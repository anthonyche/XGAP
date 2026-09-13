#!/usr/bin/env python3
"""One common fixed-input boundary on accepted tiny facts; preserve baseline failures."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'tests'));sys.path.insert(0,str(REPO/'scripts'))
from test_finbench_rdf import parameters, expected_rows
from run_external_federation_tiny import Processes, ready, fingerprint
from xgap.experiments.common_method_trial import run_fixed_trial
from xgap.experiments.common_row_score import score_trial
from xgap.experiments.external_federation import SourceObserver, deadline
from xgap.experiments.financial_nl_profile import INPUT_ROOT
from xgap.experiments.finbench_one_shot_population import normalization
from xgap.experiments.finbench_rdf import FAMILIES, fixed_semantics_query
from xgap.experiments.finbench_rdf_profile import publish_rdf_profile
from xgap.experiments.finbench_semantic import financial_program
from xgap.experiments.fixed_semantic_worker import REQUEST_SCHEMA
from xgap.experiments.m15_native_services import LoopbackPortReservations, _fuseki_server_configuration
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.owned_resources import OwnedProcess
from xgap.experiments.process_guard import ProcessBudget

JAVA='/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home/bin/java'
FUSEKI=Path('/Users/anthonyche/xgap-data/d202-local-native-20260910-diagnostic2/runtime/apache-jena-fuseki-5.6.0')
BUILD=Path('/Users/anthonyche/xgap-data/fedup-build-20260912-v1')
JARS={'fedup':BUILD/'fedup-server.jar','summary':BUILD/'summarizer.jar',
      'fedx':Path('/Users/anthonyche/xgap-data/fedx-adapter-build-20260912-matched/fedx-endpoint-adapter-matched.jar')}
PINS={'fedup':'64989a0ac220fc56fb5f57184df2195cad73326c796938afcc92b147bb150a05',
      'summary':'4e25ff950ebfaa97e120daa09105ea409e4d7ba65b9bcc30a2c1b25d06bd6d56',
      'fedx':'2e12c2630a94e017401ca8287b20ab90c0550a6607d19030a843a7d42d5f1290'}
BASE=Path('/Users/anthonyche/xgap-data/rdf-instances-native-20260913-v1/native-base/profile.json')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-root',type=Path,required=True)
    root=parser.parse_args().output_root.resolve();root.mkdir(parents=True,exist_ok=False)
    processes=Processes(root);observer=None;ports=None
    receipt={'schema_version':'xgap-common-rdf-trial-tiny-v1','success':False,'runs':[],'model_calls':0,
        'fit_calls':0,'current_query_probes':0,'automatic_retries':0,'baseline_algorithm_changes':0,
        'paper_result':False,'formal_campaign_ready':False,'maximum_top_level_queries':3,
        'scope':'new fixed-semantics common-runner boundary on one exposed meaning; no comparative performance claim'}
    try:
        with deadline(300):
            if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):raise ValueError('Commit implementation before native gate')
            receipt['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
            for name,path in JARS.items():
                if fingerprint(path)['sha256']!=PINS[name]:raise ValueError('Pinned author artifact changed: '+name)
            doc=json.loads(BASE.read_text());dataset=doc['dataset'];p=parameters()[0]
            program,_=financial_program('F1',p)
            request=write_once(root/'fixed-request.json',{'schema_version':REQUEST_SCHEMA,'question_id':'COMMON-TINY-TRANSFER',
                'dataset':dataset,'population':'tiny_development','exposure':'previously exposed financial meaning; new common-runner boundary',
                'program':program.to_dict(),'sparql':fixed_semantics_query(FAMILIES[0],p)})
            reference=write_once(root/'reference.json',{'schema_version':'xgap-normalized-row-reference-v1',
                'question_id':'COMMON-TINY-TRANSFER','dataset':dataset,'ordered':True,
                'rows':expected_rows()[0],'normalization':normalization(FAMILIES[0])})
            before=[fingerprint(p) for p in [*JARS.values(),BASE,INPUT_ROOT/'manifest.json',INPUT_ROOT/'graph.ttl',INPUT_ROOT/'control.ttl']]
            write_once(root/'input-seal.json',{'files':before,'request':request,'reference':reference,
                'reference_read_only_by_post_seal_scorer':True,'source_assignment_from_gold':False})
            at=time.perf_counter();ports=LoopbackPortReservations.acquire(4);source_handles=[];routes={}
            for index,name in enumerate(('graph','control')):
                state=root/('fuseki-'+name);state.mkdir()
                (state/'config.ttl').write_text(_fuseki_server_configuration(query_timeout_seconds=15))
                port=ports.ports[index];ports.release(index)
                process=processes.start('source-'+name,[str(FUSEKI/'fuseki-server'),'--localhost','--port',str(port),
                    '--file',str(INPUT_ROOT/(name+'.ttl')),'/'+name],cwd=FUSEKI,
                    env={'JAVA':JAVA,'FUSEKI_HOME':str(FUSEKI),'FUSEKI_BASE':str(state),'JVM_ARGS':'-Xms128m -Xmx512m'})
                ready(process,port);source_handles.append(OwnedProcess(name,'source',process))
                routes['/'+name+'/sparql']=f'http://127.0.0.1:{port}/{name}/sparql'
            observer=SourceObserver(routes,root/'source-observations',max_calls=256,timeout_seconds=3)
            endpoints=[observer.base_url+'/'+name+'/sparql' for name in ('graph','control')]
            profile=publish_rdf_profile(base_profile=BASE,base_sha256=hashlib.sha256(BASE.read_bytes()).hexdigest(),output=root/'rdf-profile',
                endpoints={'rdf_graph':observer.base_url,'rdf_control':observer.base_url})
            receipt['offline_source_and_profile_ms']=(time.perf_counter()-at)*1000
            # Author summary from these exact named RDF graphs; build once offline.
            at=time.perf_counter();prefixes=set();graphs=[]
            for name,endpoint in zip(('graph','control'),endpoints):
                body=[]
                for line in (INPUT_ROOT/(name+'.ttl')).read_text().splitlines():
                    if line.startswith('@prefix '):prefixes.add(line)
                    else:body.append(line)
                graphs.append('<'+endpoint+'> {\n'+'\n'.join(body)+'\n}')
            trig=root/'summary-input.trig';trig.write_text('\n'.join(sorted(prefixes))+'\n'+'\n'.join(graphs)+'\n')
            summary=root/'frozen-summary';summary.mkdir()
            processes.command('offline-tdb-load',[JAVA,'-Xmx512m','-cp',str(JARS['fedup']),'tdb2.tdbloader',
                '--loc',str(root/'summary-input'),str(trig)],seconds=40)
            processes.command('offline-summary',[JAVA,'-Xmx512m','-jar',str(JARS['summary']),
                '--input',str(root/'summary-input'),'--output',str(summary),'--hash','1'],seconds=40)
            summary_pins=[fingerprint(p) for p in sorted(summary.rglob('*')) if p.is_file()]
            write_once(root/'summary-seal.json',{'files':summary_pins,'hash_modulo':1,'offline_builds':1})
            shutil.copytree(summary,root/'serving-summary');receipt['offline_author_summary_ms']=(time.perf_counter()-at)*1000
            for index,method in enumerate(('xgap-rdf','fedx','fedup')):
                owned=list(source_handles);host=None;endpoint=None;at=time.perf_counter()
                if method!='xgap-rdf':
                    observer.set_phase(method+':initialization');port=ports.ports[index+1];ports.release(index+1)
                    if method=='fedx':
                        command=[JAVA,'-Xms128m','-Xmx512m','-jar',str(JARS[method]),str(port),'30',*endpoints]
                        endpoint=f'http://127.0.0.1:{port}/sparql'
                    else:
                        command=[JAVA,'-Xms128m','-Xmx512m','-jar',str(JARS[method]),'--port',str(port),
                            '--summaries',str(root/'serving-summary'),'--engine','FedX','--modify','(e) -> e']
                        endpoint=f'http://127.0.0.1:{port}/serving-summary/sparql'
                    host=processes.start(method,command);ready(host,port);owned.append(OwnedProcess(method,'method_host',host))
                    write_once(root/(method+'-initialization.json'),observer.snapshot(method+':initialization'))
                initialization_ms=(time.perf_counter()-at)*1000
                result=run_fixed_trial(request_path=request['path'],request_sha256=request['sha256'],method=method,
                    output=root/method,owned_services=owned,observer=observer,profile_path=profile['path'],profile_sha256=profile['sha256'],
                    endpoint=endpoint,budget=ProcessBudget(wall_seconds=30))
                score=score_trial(result['receipt']['path'],receipt_sha256=result['receipt']['sha256'],
                    reference_path=reference['path'],reference_sha256=reference['sha256'],output=root/method/'score.json')
                receipt['runs'].append({'method':method,'status':result['status'],'execution_success':result['success'],
                    'answer_em':score['answer_em'],'bag_f1':score['answer_row_multiset_f1'],
                    'total_online_ms':result['timing']['total_online_ms'],'recovery_ms':result['recovery_ms'],
                    'offline_method_initialization_ms':initialization_ms,'source_requests':(result['source_observations'] or {}).get('requests'),
                    'quiescence':result['quiescence'],'resources':result['resources']})
                if host:processes.stop(host)
                if not result['can_continue_session']:break  # No old session reuse after a failed query.
                if method=='xgap-rdf' and not score['answer_em']:break
            receipt['inputs_unchanged']=[fingerprint(p['path']) for p in before]==before
            receipt['frozen_summary_unchanged']=[fingerprint(p['path']) for p in summary_pins]==summary_pins
            receipt['success']=(len(receipt['runs'])==3 and receipt['runs'][0]['answer_em']==1 and
                all(r['quiescence']['complete'] for r in receipt['runs']) and receipt['inputs_unchanged'] and receipt['frozen_summary_unchanged'])
    except BaseException as error:receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        receipt['processes']=processes.close()
        if observer:
            observer.close();receipt['observer_stopped']=not observer.thread.is_alive() and observer.inflight==0
        if ports:ports.close()
        receipt['owned_processes_terminal']=all(p['returncode'] is not None for p in receipt['processes'])
        receipt['success'] &= receipt['owned_processes_terminal'] and receipt.get('observer_stopped',False)
        write_once(root/'receipt.json',receipt)
    print(json.dumps(receipt));return 0 if receipt['success'] else 1


if __name__=='__main__':raise SystemExit(main())
