#!/usr/bin/env python3
"""Three gold semantic financial programs, estimated once, on split native stores.

Development only: 8 entities/16 relationships; no model, baseline, fitting or
alternative-plan execution. Records retain every selected query and failure.
"""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sys
import threading
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/'tests'))
from test_finbench_rdf import tiny_partition, parameters, expected_rows
from test_financial_binding import backends_for, deployment, MODEL
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.experiments.external_federation import deadline
from xgap.experiments.finbench_rdf import materialize_finbench_rdf, _pin
from xgap.experiments.finbench_semantic import financial_program
from xgap.experiments.m15_fixture_loader import FusekiGraphStoreFixtureLoader
from xgap.experiments.m15_native_services import (LoopbackPortReservations, ServiceSpec,
    _fuseki_server_configuration, _neo4j_configuration, start_service, stop_service, wait_for_service_health)
from xgap.experiments.m15_finbench_partition import NEO4J_BATCH_FILENAME
from xgap.experiments.one_shot_records import write_once, CapturingClient
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.one_shot_planning import prepare_one_shot_domain
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.semantic_planning import LogicalSource
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root',required=True,type=Path)
    parser.add_argument('--java',default='/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home/bin/java')
    parser.add_argument('--runtime-root',type=Path,default=Path('/Users/anthonyche/xgap-data/d202-local-native-20260910-diagnostic2/runtime'))
    args=parser.parse_args();root=args.output_root.resolve();root.mkdir(parents=True,exist_ok=False)
    receipt={'schema_version':'xgap-financial-binding-native-v1','success':False,'model_calls':0,
        'baseline_calls':0,'training_calls':0,'fit_calls':0,'current_query_probes':0,'retries':0,
        'input_profile':'gold_semantic_program','paper_result':False,'query_budget':3,'runs':[], 'loads':[], 'shutdown':[]}
    running=[];ports=None
    try:
        with deadline(240):
            started=time.perf_counter()
            partition=tiny_partition(root/'fixture');mapping_receipt=materialize_finbench_rdf(partition,root/'rdf')
            mapping=json.loads((root/'rdf/mapping.json').read_text());backends=backends_for(mapping)
            frozen=deployment(combined=False);frozen.save(root/'frozen_deployment.json')
            sources={s.source_id:LogicalSource(s.source_id,s.snapshot_version,(s.backend_id,)) for s in frozen.statistics.entries}
            policy=replace(OneShotPolicy.for_mode('performance'),max_parallelism=1)
            receipt['offline_input_preparation_ms']=(time.perf_counter()-started)*1000
            prepared=[]
            for index,p in enumerate(parameters()):
                family=f'F{index+1}';program,slots=financial_program(family,p)
                at=time.perf_counter()
                candidates,domain=prepare_one_shot_domain(program,operator_sources=slots,sources=sources,backends=backends,policy=policy)
                predictions=[(c,frozen.predict(c.plan)) for c in candidates]
                available=[(c,p) for c,p in predictions if p.estimated_ms is not None]
                if not available:raise ValueError(f'{family}: no available frozen estimate')
                winner,prediction=min(available,key=lambda item:(item[1].estimated_ms,item[0].strategy_id))
                plan_record={'family':family,'program':program.to_dict(),'operator_sources':slots,'domain':domain,
                    'predictions':[{'strategy_id':c.strategy_id,'prediction':p.to_dict()} for c,p in predictions],
                    'selected_strategy':winner.strategy_id,'plan':winner.plan.to_dict(),
                    'planning_ms':(time.perf_counter()-at)*1000,'estimated_ms':prediction.estimated_ms,
                    'selected_before_service_start':True,'selection_uses_execution_observations':False}
                write_once(root/(family+'-plan.json'),plan_record);prepared.append((family,winner.plan,plan_record))
            receipt['development_preparation_and_planning_ms']=(time.perf_counter()-started)*1000
            receipt['facts']={k:mapping_receipt[k] for k in ('entity_count','relationship_count','source_partition_sha256')}
            files=[Path(__file__),MODEL,root/'frozen_deployment.json',root/'rdf/manifest.json',root/'rdf'/NEO4J_BATCH_FILENAME,root/'rdf/control.ttl',
                REPO/'tests/test_financial_binding.py',REPO/'tests/test_finbench_rdf.py']
            files.extend(REPO/p for p in ('src/xgap/compilers/edge_match.py','src/xgap/experiments/finbench_semantic.py',
                'src/xgap/runtime/semantic_compiler.py','src/xgap/runtime/row_operations.py','src/xgap/runtime/binding_operations.py',
                'src/xgap/runtime/physical_strategies.py','src/xgap/planning/runtime_work_estimator.py','src/xgap/semantic/parameter_contract.py'))
            write_once(root/'input_seal.json',{'files':[_pin(p) for p in files],'model_calls':0,'final_executions':3,'alternative_executions':0})
            state=root/'state'
            for part in ('neo4j/data','neo4j/transactions','neo4j/logs','neo4j/run','neo4j/import','neo4j/plugins','fuseki'):
                (state/part).mkdir(parents=True)
            neo_root=args.runtime_root/'neo4j-community-5.26.30';rdf_root=args.runtime_root/'apache-jena-fuseki-5.6.0'
            conf=state/'neo4j-conf';shutil.copytree(neo_root/'conf',conf)
            ports=LoopbackPortReservations.acquire(3);np,bp,fp=ports.ports
            (conf/'neo4j.conf').write_text(_neo4j_configuration(neo4j_root=neo_root,state_root=state,http_port=np,bolt_port=bp,
                resource_profile={'heap_initial_size':'256m','heap_max_size':'512m','pagecache_size':'128m'},query_timeout_seconds=15))
            (state/'fuseki/config.ttl').write_text(_fuseki_server_configuration(query_timeout_seconds=15))
            nu,fu=f'http://127.0.0.1:{np}',f'http://127.0.0.1:{fp}'
            specs=(ServiceSpec('neo4j','neo4j','5.26.30',(str(neo_root/'bin/neo4j'),'console'),neo_root,
                {'JAVACMD':args.java,'NEO4J_CONF':str(conf),'NEO4J_HOME':str(neo_root)},nu+'/db/neo4j/tx/commit',root/'neo4j.log'),
                ServiceSpec('fuseki','fuseki','5.6.0',(str(rdf_root/'fuseki-server'),'--localhost','--ping','--port',str(fp),'--update','--mem','/tiny'),rdf_root,
                {'JAVA':args.java,'FUSEKI_HOME':str(rdf_root),'FUSEKI_BASE':str(state/'fuseki'),'JVM_ARGS':'-Xms128m -Xmx512m'},fu+'/$/ping',root/'fuseki.log'))
            at=time.perf_counter()
            for index,spec in enumerate(specs):
                for slot in ((0,1) if index==0 else (2,)):ports.release(slot)
                service=start_service(spec);running.append(service)
                write_once(root/(spec.service_id+'-owner.json'),{'pid':service.process.pid,'spec':spec.to_dict()})
                health=wait_for_service_health(service,timeout_seconds=45)
                write_once(root/(spec.service_id+'-health.json'),health.to_dict())
                if not health.success:raise RuntimeError('Owned service failed readiness; no restart')
            receipt['offline_startup_ms']=(time.perf_counter()-at)*1000
            neo=Neo4jClient(BackendDescriptor('neo4j','neo4j','cypher','property_graph',runtime={'timeout_seconds':20}))
            neo.http_url,neo.database=nu,'neo4j'
            desc=BackendDescriptor('fuseki','fuseki','sparql','rdf',runtime={'timeout_seconds':20})
            rdf=FusekiClient(desc);rdf.base_url,rdf.dataset=fu,'tiny'
            loader=FusekiGraphStoreFixtureLoader(desc);loader.base_url,loader.dataset=fu,'tiny'
            at=time.perf_counter()
            for index,line in enumerate((root/'rdf'/NEO4J_BATCH_FILENAME).read_text().splitlines()):
                batch=json.loads(line)
                if batch['kind']!='constraint' and not batch.get('parameters',{}).get('rows'):continue
                loaded=neo.execute(QueryArtifact('load-'+str(index),'cypher',batch['statement'],kind='native',parameters=batch.get('parameters',{})))
                write_once(root/f'load-{index:03}.json',loaded.to_dict());receipt['loads'].append({'kind':batch['kind'],'success':loaded.success})
                if not loaded.success:raise RuntimeError('Neo4j tiny fixture load failed')
            loaded=loader.load(root/'rdf/control.ttl');write_once(root/'load-control.json',loaded.to_dict())
            receipt['loads'].append({'kind':'control_rdf','success':loaded.success})
            if not loaded.success:raise RuntimeError('Fuseki tiny fixture load failed')
            receipt['offline_load_ms']=(time.perf_counter()-at)*1000
            for index,(family,plan,chosen) in enumerate(prepared):
                case_root=root/family;case_root.mkdir();records=[];registry=BackendPluginRegistry();lock=threading.Lock()
                for client in (neo,rdf):
                    capture=CapturingClient(client,case_root,records,lock)
                    registry.register(NativeBackendPlugin(client.backend_id,capture))
                write_once(case_root/'execution_intent.json',{'plan_id':plan.plan_id,'maximum_final_executions':1})
                result=FederatedScheduler(BackendInvokeTool(registry)).execute(plan)
                write_once(case_root/'result.json',result.to_dict())
                # Independent answer is accessed only after the execution record is sealed.
                expected=expected_rows()[index]
                evaluation={'family':family,'execution_success':result.success,'answer_exact':result.success and list(result.final_rows)==expected,
                    'actual':list(result.final_rows) if result.success else None,'expected':expected,'remote_calls':result.total_remote_calls,
                    'strategy':chosen['selected_strategy'],'estimated_ms':chosen['estimated_ms'],'planning_ms':chosen['planning_ms'],
                    'source_calls':{backend:sum(r['backend_id']==backend for r in records) for backend in ('neo4j','fuseki')}}
                write_once(case_root/'evaluation.json',evaluation);receipt['runs'].append(evaluation)
                if not result.success:break
            receipt['success']=len(receipt['runs'])==3 and all(r['answer_exact'] for r in receipt['runs'])
    except BaseException as error:
        receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        for service in reversed(running):receipt['shutdown'].append(stop_service(service).to_dict())
        if ports:ports.close()
        receipt['owned_processes_terminal']=all(s.process.poll() is not None for s in running)
        receipt['success'] &= receipt['owned_processes_terminal']
        write_once(root/'receipt.json',receipt)
    print(json.dumps(receipt));return 0 if receipt['success'] else 1


if __name__=='__main__':
    raise SystemExit(main())
