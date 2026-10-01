#!/usr/bin/env python3
"""One corrected-representation boundary, same public input, unchanged FedX."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'scripts'))
from check_common_rdf_trial import JAVA, FUSEKI, JARS, PINS
from run_external_federation_tiny import Processes, ready, fingerprint
from xgap.experiments.common_method_trial import run_fixed_trial
from xgap.experiments.common_row_score import score_trial
from xgap.experiments.disjoint_rdf_profile import publish_disjoint_profile
from xgap.experiments.external_federation import SourceObserver, deadline
from xgap.experiments.m15_native_services import LoopbackPortReservations, _fuseki_server_configuration
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.owned_resources import OwnedProcess
from xgap.experiments.process_guard import ProcessBudget

BASE=Path('/Users/anthonyche/xgap-data/rdf-instances-native-20260913-v1/rdf-profile/profile.json')
BASE_SHA='a636cc548c6c11c6181f6a2745fbd9d7903a10417d271c57040fbc63d55bd72a'
OLD=Path('/Users/anthonyche/xgap-data/common-rdf-trial-20260913-v1')
INPUT_PINS={'fixed-request.json':'1f8b5084d1bbcafe3df3becb02e7a5a0d378aed37bc5c8a433465bab11ade4eb',
            'reference.json':'b62816c924a87a923bcfdec98dc4e2d095665c077d3663839465e369c251bd3f'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-root',type=Path,required=True)
    root=parser.parse_args().output_root.resolve();root.mkdir(parents=True,exist_ok=False)
    processes=Processes(root);observer=None;ports=None
    receipt={'schema_version':'xgap-disjoint-rdf-native-boundary-v2','success':False,'runs':[],
        'model_calls':0,'fit_calls':0,'current_query_probes':0,'automatic_retries':0,
        'baseline_algorithm_changes':0,'baseline_query_changes':0,'maximum_top_level_queries':2,
        'fedup_known_failure_reruns':0,'catalog_rebuilds':0,'paper_result':False,'formal_campaign_ready':False,
        'scope':'same exposed fixed meaning under corrected shared representation; not a performance comparison'}
    try:
        with deadline(120):
            if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):raise ValueError('Commit implementation before native gate')
            receipt['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
            if fingerprint(JARS['fedx'])['sha256']!=PINS['fedx']:raise ValueError('Pinned author FedX artifact changed')
            inputs={}
            for name,pin in INPUT_PINS.items():
                data=read_pinned(OLD/name,pin)
                with (root/name).open('xb') as target:target.write(data)
                inputs[name]=fingerprint(root/name)
            request,reference=inputs['fixed-request.json'],inputs['reference.json']
            before=[fingerprint(p) for p in [BASE,JARS['fedx'],*(OLD/name for name in INPUT_PINS)]]
            at=time.perf_counter();ports=LoopbackPortReservations.acquire(3)
            routes={'/'+name+'/sparql':f'http://127.0.0.1:{ports.ports[i]}/{name}/sparql'
                    for i,name in enumerate(('graph','control'))}
            observer=SourceObserver(routes,root/'source-observations',max_calls=256,timeout_seconds=3)
            profile=publish_disjoint_profile(base_profile=BASE,base_sha256=BASE_SHA,output=root/'rdf-profile-v2',
                endpoints={'rdf_graph':observer.base_url,'rdf_control':observer.base_url})
            doc=json.loads(read_pinned(profile['path'],profile['sha256']));loads=doc['offline']['rdf_loads']
            before.extend(fingerprint(loads[name]['path']) for name in ('graph','control'))
            write_once(root/'input-seal.json',{'files':before,'profile':profile,'request':request,'reference':reference,
                'reference_only_for_post_seal_scoring':True,'source_assignment_from_gold':False,
                'shared_loads':loads,'representation':doc['offline']['rdf_representation']})
            handles=[]
            for i,name in enumerate(('graph','control')):
                state=root/('fuseki-'+name);state.mkdir()
                (state/'config.ttl').write_text(_fuseki_server_configuration(query_timeout_seconds=15))
                port=ports.ports[i];ports.release(i)
                process=processes.start('source-'+name,[str(FUSEKI/'fuseki-server'),'--localhost','--port',str(port),
                    '--file',loads[name]['path'],'/'+name],cwd=FUSEKI,
                    env={'JAVA':JAVA,'FUSEKI_HOME':str(FUSEKI),'FUSEKI_BASE':str(state),'JVM_ARGS':'-Xms128m -Xmx512m'})
                ready(process,port);handles.append(OwnedProcess(name,'source',process))
            receipt['offline_source_and_profile_ms']=(time.perf_counter()-at)*1000
            endpoints=[observer.base_url+'/'+name+'/sparql' for name in ('graph','control')]
            for method in ('xgap-rdf','fedx'):
                owned=list(handles);host=None;endpoint=None;at=time.perf_counter()
                if method=='fedx':
                    observer.set_phase(method+':initialization');port=ports.ports[2];ports.release(2)
                    host=processes.start(method,[JAVA,'-Xms128m','-Xmx512m','-jar',str(JARS['fedx']),str(port),'30',*endpoints])
                    ready(host,port);owned.append(OwnedProcess(method,'method_host',host))
                    endpoint=f'http://127.0.0.1:{port}/sparql'
                    write_once(root/'fedx-initialization.json',observer.snapshot(method+':initialization'))
                initialization_ms=(time.perf_counter()-at)*1000
                result=run_fixed_trial(request_path=request['path'],request_sha256=request['sha256'],method=method,
                    output=root/method,owned_services=owned,observer=observer,profile_path=profile['path'],
                    profile_sha256=profile['sha256'],endpoint=endpoint,budget=ProcessBudget(wall_seconds=30))
                score=score_trial(result['receipt']['path'],receipt_sha256=result['receipt']['sha256'],
                    reference_path=reference['path'],reference_sha256=reference['sha256'],output=root/method/'score.json')
                receipt['runs'].append({'method':method,'status':result['status'],'execution_success':result['success'],
                    'answer_em':score['answer_em'],'bag_f1':score['answer_row_multiset_f1'],
                    'total_online_ms':result['timing']['total_online_ms'],'recovery_ms':result['recovery_ms'],
                    'offline_method_initialization_ms':initialization_ms,'source_requests':(result['source_observations'] or {}).get('requests'),
                    'quiescence':result['quiescence'],'resources':result['resources']})
                if host:processes.stop(host)
                if not result['can_continue_session']:break
                if method=='xgap-rdf' and not score['answer_em']:break
            receipt['inputs_unchanged']=[fingerprint(p['path']) for p in before]==before
            # Gate records faithful baseline outcomes, including a wrong answer.
            receipt['success']=(len(receipt['runs'])==2 and receipt['runs'][0]['answer_em']==1 and
                all(r['quiescence']['complete'] for r in receipt['runs']) and receipt['inputs_unchanged'])
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
