#!/usr/bin/env python3
"""One tiny three-family gate on two owned Fuseki instances; no model or refit."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'tests'))
from test_finbench_rdf import parameters, expected_rows
from xgap.experiments.external_federation import deadline
from xgap.experiments.financial_nl_profile import INPUT_ROOT, MANIFEST_HASH
from xgap.experiments.finbench_rdf import _pin
from xgap.experiments.finbench_rdf_profile import publish_rdf_profile
from xgap.experiments.finbench_serving_profile import publish_serving_profile
from xgap.experiments.finbench_semantic import financial_program
from xgap.experiments.m15_fixture_loader import FusekiGraphStoreFixtureLoader
from xgap.experiments.m15_native_services import (LoopbackPortReservations, ServiceSpec,
    _fuseki_server_configuration, start_service, stop_service, wait_for_service_health)
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, native_clients
from xgap.experiments.one_shot_records import write_once, CapturingClient
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.runtime.one_shot_planning import prepare_one_shot_domain
from xgap.runtime.scheduler import FederatedScheduler
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin

MODEL=Path('/Users/anthonyche/xgap-data/edge-bind-training-native-20260912-v1/frozen_work_estimator.json')
MODEL_HASH='80c3dc09856d1379b1bc28c63de19f23f42a2931b101926b83d334cc21322873'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root',type=Path,required=True)
    parser.add_argument('--java',default='/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home/bin/java')
    parser.add_argument('--runtime-root',type=Path,default=Path('/Users/anthonyche/xgap-data/d202-local-native-20260910-diagnostic2/runtime'))
    args=parser.parse_args();root=args.output_root.resolve();root.mkdir(parents=True,exist_ok=False)
    receipt={'schema_version':'xgap-rdf-instances-tiny-native-v1','success':False,
        'input_profile':'authored_semantic_program; deterministic integration only',
        'model_calls':0,'baseline_calls':0,'fit_calls':0,'training_calls':0,'current_query_probes':0,
        'alternative_executions':0,'retries':0,'data_rematerializations':0,'maximum_final_executions':3,
        'paper_result':False,'formal_campaign_ready':False,'runs':[],'loads':[],'shutdown':[]}
    running=[];ports=None
    try:
        with deadline(240):
            receipt['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
            if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):
                raise ValueError('Commit the gate implementation before the live boundary')
            at=time.perf_counter();ports=LoopbackPortReservations.acquire(2)
            endpoints={instance:f'http://127.0.0.1:{port}' for instance,port in zip(('rdf_graph','rdf_control'),ports.ports)}
            base=publish_serving_profile(rdf_root=INPUT_ROOT,manifest_sha256=MANIFEST_HASH,
                model_path=MODEL,model_sha256=MODEL_HASH,output=root/'native-base',dataset_id='rdf-instance-tiny',
                endpoints={'neo4j':'http://localhost:1','fuseki':'http://localhost:2'})
            pin=publish_rdf_profile(base_profile=base['path'],base_sha256=base['sha256'],output=root/'rdf-profile',endpoints=endpoints)
            profile=FrozenOneShotProfile.load(pin['path'],expected_sha256=pin['sha256'])
            doc,model,_,sources,backends,client_specs,modes=profile.materialize()
            receipt['offline_profile_preparation_ms']=(time.perf_counter()-at)*1000
            receipt['profile']=pin
            manifest=json.loads((INPUT_ROOT/'manifest.json').read_text())
            receipt['facts']={k:manifest[k] for k in ('entity_count','relationship_count','source_partition_sha256')}
            if (manifest['entity_count'],manifest['relationship_count'])!=(8,16):
                raise ValueError('This development gate must stay tiny')
            prepared=[];policy=replace(modes['performance'][0],max_parallelism=1)
            for index,p in enumerate(parameters()):
                family=f'F{index+1}';program,slots=financial_program(family,p);at=time.perf_counter()
                candidates,domain=prepare_one_shot_domain(program,operator_sources=slots,sources=sources,backends=backends,policy=policy)
                predictions=[(c,model.predict(c.plan)) for c in candidates]
                available=[(c,p) for c,p in predictions if p.estimated_ms is not None]
                if not available:raise ValueError(f'{family}: no available frozen estimate')
                selected,prediction=min(available,key=lambda x:(x[1].estimated_ms,x[0].strategy_id))
                record={'family':family,'program':program.to_dict(),'operator_sources':slots,'domain':domain,
                    'predictions':[{'strategy_id':c.strategy_id,'prediction':p.to_dict()} for c,p in predictions],
                    'selected_strategy':selected.strategy_id,'plan':selected.plan.to_dict(),
                    'planning_ms':(time.perf_counter()-at)*1000,'estimated_ms':prediction.estimated_ms,
                    'selected_before_service_start':True,'selection_uses_execution_observations':False}
                write_once(root/(family+'-plan.json'),record);prepared.append((family,selected.plan,record))
            files=[Path(__file__),MODEL,INPUT_ROOT/'manifest.json',INPUT_ROOT/'mapping.json',INPUT_ROOT/'graph.ttl',INPUT_ROOT/'control.ttl',
                root/'rdf-profile/profile.json',root/'rdf-profile/estimator.json',REPO/'tests/test_finbench_rdf.py']
            input_seal=[{**_pin(p),'path':str(p)} for p in files]
            write_once(root/'input_seal.json',{'files':input_seal,'maximum_final_executions':3,'alternative_executions':0})
            rdf_root=args.runtime_root/'apache-jena-fuseki-5.6.0';at=time.perf_counter()
            for index,instance in enumerate(('rdf_graph','rdf_control')):
                state=root/'state'/instance;state.mkdir(parents=True)
                (state/'config.ttl').write_text(_fuseki_server_configuration(query_timeout_seconds=15))
                spec=ServiceSpec(instance,'fuseki','5.6.0',
                    (str(rdf_root/'fuseki-server'),'--localhost','--ping','--port',str(ports.ports[index]),
                     '--update','--mem','/'+client_specs[instance]['database']),rdf_root,
                    {'JAVA':args.java,'FUSEKI_HOME':str(rdf_root),'FUSEKI_BASE':str(state),'JVM_ARGS':'-Xms128m -Xmx512m'},
                    endpoints[instance]+'/$/ping',root/(instance+'.log'))
                ports.release(index);service=start_service(spec);running.append(service)
                write_once(root/(instance+'-owner.json'),{'pid':service.process.pid,'spec':spec.to_dict()})
                health=wait_for_service_health(service,timeout_seconds=45)
                write_once(root/(instance+'-health.json'),health.to_dict())
                if not health.success:raise RuntimeError('Owned Fuseki failed readiness; no restart')
            receipt['offline_startup_ms']=(time.perf_counter()-at)*1000;at=time.perf_counter()
            clients=native_clients(client_specs)
            for instance,client in clients.items():
                loader=FusekiGraphStoreFixtureLoader(BackendDescriptor(instance,'fuseki','sparql','rdf',runtime={'timeout_seconds':20}))
                loader.base_url,loader.dataset=client.base_url,client.dataset
                result=loader.load(INPUT_ROOT/(instance.removeprefix('rdf_')+'.ttl'))
                write_once(root/('load-'+instance+'.json'),result.to_dict())
                receipt['loads'].append({'instance':instance,'success':result.success})
                if not result.success:raise RuntimeError('Owned Fuseki load failed; no retry')
            receipt['offline_load_ms']=(time.perf_counter()-at)*1000
            for index,(family,plan,chosen) in enumerate(prepared):
                case=root/family;case.mkdir();records=[];registry=BackendPluginRegistry();lock=threading.Lock()
                for instance,client in clients.items():
                    registry.register(NativeBackendPlugin(instance,CapturingClient(client,case,records,lock)))
                write_once(case/'execution_intent.json',{'plan_id':plan.plan_id,'maximum_final_executions':1})
                at=time.perf_counter();result=FederatedScheduler(BackendInvokeTool(registry)).execute(plan)
                execution_ms=(time.perf_counter()-at)*1000
                write_once(case/'result.json',result.to_dict())
                expected=expected_rows()[index]  # Read independent answers only after result sealing.
                evaluation={'family':family,'execution_success':result.success,
                    'answer_exact':result.success and list(result.final_rows)==expected,
                    'actual':list(result.final_rows) if result.success else None,'expected':expected,
                    'remote_calls':result.total_remote_calls,'source_calls':{
                        instance:sum(r['backend_id']==instance for r in records) for instance in clients},
                    'strategy':chosen['selected_strategy'],'estimated_ms':chosen['estimated_ms'],
                    'planning_ms':chosen['planning_ms'],'execution_ms':execution_ms}
                write_once(case/'evaluation.json',evaluation);receipt['runs'].append(evaluation)
                if not result.success:break  # Never advance after a failed external execution.
            receipt['input_seal_unchanged']=all(_pin(Path(p['path']))['sha256']==p['sha256'] for p in input_seal)
            receipt['success']=(len(receipt['runs'])==3 and all(r['answer_exact'] and
                all(v>0 for v in r['source_calls'].values()) for r in receipt['runs']) and receipt['input_seal_unchanged'])
    except BaseException as error:
        receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        for service in reversed(running):receipt['shutdown'].append(stop_service(service).to_dict())
        if ports:ports.close()
        receipt['owned_processes_terminal']=all(s.process.poll() is not None for s in running)
        receipt['success'] &= receipt['owned_processes_terminal']
        write_once(root/'receipt.json',receipt)
    print(json.dumps(receipt));return 0 if receipt['success'] else 1


if __name__=='__main__':raise SystemExit(main())
