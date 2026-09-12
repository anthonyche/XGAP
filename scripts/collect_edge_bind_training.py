#!/usr/bin/env python3
"""Collect exactly four independent endpoint-bind plans; reuse old labels once."""

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import time

from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.experiments.edge_bind_training import (PROFILE, EXCLUDED_IDS, PARENT_ROOT,
    fixture, prepare_entries, expected_rows, verified_parent_records)
from xgap.experiments.external_federation import deadline
from xgap.experiments.m15_fixture_loader import FusekiGraphStoreFixtureLoader
from xgap.experiments.m15_native_services import (LoopbackPortReservations, ServiceSpec,
    _fuseki_server_configuration, _neo4j_configuration, start_service, stop_service, wait_for_service_health)
from xgap.experiments.one_shot_records import write_once
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import QueryArtifact
from xgap.planning.runtime_estimator import RuntimeTrainingSample
from xgap.planning.runtime_work_deployment import FrozenWorkDeployment
from xgap.planning.runtime_work_estimator import fit_work_estimator, load_frozen_estimator
from xgap.runtime.one_shot_planning import prepare_one_shot_domain
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.semantic_compiler import SemanticBackend
from xgap.runtime.semantic_planning import LogicalSource
from xgap.compilers.rdf_encoding import RdfEdgeEncoding
from xgap.semantic.program import SemanticGraphProgram
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


class RecordingClient:
    """Record in memory during timing, persist after the training plan returns."""
    def __init__(self,client,records):
        self.client,self.backend_id,self.records=client,client.backend_id,records
    def execute(self,artifact):
        record={'backend_id':self.backend_id,'artifact':artifact.to_dict(),'status':'started'}
        self.records.append(record)
        result=self.client.execute(artifact)
        record.update(status='returned',execution=result.to_dict())
        return result


def availability_after_freeze(model, financial_root, output_root):
    """No observed financial latency/answer reads and no model fitting here."""
    financial_root=Path(financial_root)
    old=load_frozen_estimator(financial_root/'frozen_deployment.json')
    deployed=FrozenWorkDeployment('edge-bind-to-financial-tiny-v1',model,old.statistics,'post-freeze-only:financial-tiny-manifest')
    deployed.save(output_root/'financial_frozen_deployment.json')
    mapping=json.loads((financial_root/'rdf/mapping.json').read_text())
    backends={'neo4j':SemanticBackend('neo4j',mapping['resource_namespace'],mapping['identity_property']),
        'fuseki':SemanticBackend('fuseki',mapping['resource_namespace'],mapping['identity_property'],
            backend_mapping=mapping['backend_mapping'],rdf_edge_encoding=RdfEdgeEncoding(**mapping['rdf_edge_encoding']),
            rdf_node_classes=tuple(mapping['rdf_node_classes']))}
    sources={s.source_id:LogicalSource(s.source_id,s.snapshot_version,(s.backend_id,)) for s in old.statistics.entries}
    results=[]
    for family in ('F1','F2','F3'):
        # This file contains declared programs/estimated plans, never observed answer/latency.
        raw=json.loads((financial_root/(family+'-plan.json')).read_text())
        candidates,domain=prepare_one_shot_domain(SemanticGraphProgram.from_dict(raw['program']),
            operator_sources=raw['operator_sources'],sources=sources,backends=backends,
            policy=replace(OneShotPolicy.for_mode('performance'),max_parallelism=1))
        predictions=[{'strategy_id':c.strategy_id,'prediction':deployed.predict(c.plan).to_dict()} for c in candidates]
        results.append({'family':family,'domain':domain,'predictions':predictions,
            'available_count':sum(p['prediction']['estimated_ms'] is not None for p in predictions),
            'candidate_count':len(candidates),'backend_calls':0,'financial_observed_labels_read':False})
    write_once(output_root/'financial_availability.json',results)
    return [{'family':r['family'],'available':r['available_count'],'total':r['candidate_count']} for r in results]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root',required=True,type=Path)
    parser.add_argument('--parent-root',type=Path,default=PARENT_ROOT)
    parser.add_argument('--financial-root',type=Path,default=Path('/Users/anthonyche/xgap-data/financial-binding-native-20260912-v1'))
    parser.add_argument('--java',default='/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home/bin/java')
    parser.add_argument('--runtime-root',type=Path,default=Path('/Users/anthonyche/xgap-data/d202-local-native-20260910-diagnostic2/runtime'))
    args=parser.parse_args();root=args.output_root.resolve();root.mkdir(parents=True,exist_ok=False)
    receipt={'schema_version':PROFILE,'success':False,'phase':'preparation','model_calls':0,'baseline_calls':0,
        'old_training_executions':0,'current_financial_query_executions':0,'training':[],'loads':[],'shutdown':[],
        'new_fit_calls':0,'retries':0,'warmup_calls':0,'paper_result':False}
    running=[];ports=None
    try:
        with deadline(240):
            at=time.perf_counter();parent,old_samples,imported=verified_parent_records(args.parent_root)
            stats,entries,_=prepare_entries();data,_,_,ttl,loads=fixture()
            write_once(root/'parent_import.json',imported);write_once(root/'graph.json',data)
            (root/'load.ttl').write_text(ttl)
            write_once(root/'manifest.json',{'statistics':stats.to_dict(),'parent_model_sha256':parent.model_sha256,
                'training':[dict(e,plan=e['plan'].to_dict()) for e in entries],'maximum_new_training_calls':8,
                'excluded_query_ids':list(EXCLUDED_IDS),'order_fixed_before_observation':True,'old_observations_reused':28,
                'fit':{'sweeps':128,'ridge':1e-4},'warmup_calls':0,'cold_effects':'retained; tiny category coverage, not latency calibration'})
            repo=Path(__file__).resolve().parents[1]
            files=[Path(__file__),repo/'src/xgap/experiments/edge_bind_training.py',repo/'src/xgap/planning/runtime_work_estimator.py',root/'manifest.json',root/'load.ttl']
            write_once(root/'input_seal.json',{'files':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}})
            receipt['offline_preparation_ms']=(time.perf_counter()-at)*1000
            state=root/'state'
            for part in ('neo4j/data','neo4j/transactions','neo4j/logs','neo4j/run','neo4j/import','neo4j/plugins','fuseki'):(state/part).mkdir(parents=True)
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
            for i,spec in enumerate(specs):
                for slot in ((0,1) if i==0 else (2,)):ports.release(slot)
                service=start_service(spec);running.append(service)
                write_once(root/(spec.service_id+'-owner.json'),{'pid':service.process.pid,'spec':spec.to_dict()})
                health=wait_for_service_health(service,timeout_seconds=45)
                write_once(root/(spec.service_id+'-health.json'),health.to_dict())
                if not health.success:raise RuntimeError('Owned service readiness failed; no restart')
            receipt['offline_startup_ms']=(time.perf_counter()-at)*1000
            neo=Neo4jClient(BackendDescriptor('neo4j','neo4j','cypher','property_graph',runtime={'timeout_seconds':20}))
            neo.http_url,neo.database=nu,'neo4j'
            desc=BackendDescriptor('fuseki','fuseki','sparql','rdf',runtime={'timeout_seconds':20})
            rdf=FusekiClient(desc);rdf.base_url,rdf.dataset=fu,'tiny'
            loader=FusekiGraphStoreFixtureLoader(desc);loader.base_url,loader.dataset=fu,'tiny'
            at=time.perf_counter()
            for load in loads:
                outcome=neo.execute(QueryArtifact('load-'+load['id'],'cypher',load['text'],kind='native',parameters=load['parameters']))
                write_once(root/('load-'+load['id']+'.json'),outcome.to_dict());receipt['loads'].append({'id':load['id'],'success':outcome.success})
                if not outcome.success:raise RuntimeError('Neo4j training fixture load failed')
            outcome=loader.load(root/'load.ttl');write_once(root/'load-rdf.json',outcome.to_dict())
            receipt['loads'].append({'id':'rdf','success':outcome.success})
            if not outcome.success:raise RuntimeError('RDF training fixture load failed')
            receipt['offline_load_ms']=(time.perf_counter()-at)*1000
            samples=list(old_samples);assignments={s.observation_id:parent.statistics for s in old_samples}
            collection_at=time.perf_counter();receipt['phase']='new_training'
            for index,entry in enumerate(entries):
                case=root/f'new-{index+1:02}';case.mkdir();records=[];registry=BackendPluginRegistry()
                for client in (neo,rdf):registry.register(NativeBackendPlugin(client.backend_id,RecordingClient(client,records)))
                write_once(case/'intent.json',{'query_id':entry['query_id'],'maximum_executions':1,'plan_id':entry['plan'].plan_id})
                result=FederatedScheduler(BackendInvokeTool(registry)).execute(entry['plan'])
                evidence=write_once(case/'measurement.json',{'query_id':entry['query_id'],'split_role':'training',
                    'statistics_sha256':stats.sha256,'runtime_result':result.to_dict(),'backend_records':records})
                canonical=lambda rows:sorted(json.dumps(r,sort_keys=True) for r in rows)
                exact=result.success and canonical(result.final_rows)==canonical(expected_rows(entry['endpoint']))
                current={'query_id':entry['query_id'],'endpoint':entry['endpoint'],'target_backend':entry['target_backend'],
                    'answer_exact':exact,'elapsed_ms':result.elapsed_ms,'remote_calls':result.total_remote_calls,'measurement':evidence}
                write_once(case/'evaluation.json',current);receipt['training'].append(current)
                if not exact:raise RuntimeError('Independent endpoint-bind training failed; no retry/fit')
                observation='edge-bind-'+str(index+1)
                samples.append(RuntimeTrainingSample(observation,entry['query_id'],entry['plan'],result.elapsed_ms,evidence['sha256']))
                assignments[observation]=stats
            new_ms=(time.perf_counter()-collection_at)*1000;new_calls=sum(t['remote_calls'] for t in receipt['training'])
            receipt['offline_collection']={'new_elapsed_ms':new_ms,'new_remote_calls':new_calls,
                'reused_elapsed_ms':imported['original_collection_elapsed_ms'],'reused_remote_calls':imported['original_collection_remote_calls'],
                'reused_observations':len(old_samples),'new_observations':len(entries),'old_measurements_reexecuted':0}
            collection=write_once(root/'collection.json',receipt['offline_collection'])
            receipt['phase']='offline_fit';receipt['new_fit_calls']=1
            model=fit_work_estimator(samples,statistics=parent.statistics,sample_statistics=assignments,
                training_id=PROFILE,model_version='tiny-work-edge-bind-v3',training_kind='measured_training',excluded_query_ids=EXCLUDED_IDS,
                collection_ref='collection.json#sha256='+collection['sha256'],collection_elapsed_ms=new_ms+imported['original_collection_elapsed_ms'],
                collection_remote_calls=new_calls+imported['original_collection_remote_calls'])
            model.save(root/'frozen_work_estimator.json');frozen=load_frozen_estimator(root/'frozen_work_estimator.json')
            if model.to_dict()!=frozen.to_dict():raise ValueError('New frozen model round-trip differs')
            receipt['model_sha256']=frozen.model_sha256;receipt['training_sample_count']=len(samples)
            write_once(root/'freeze.json',{'model_sha256':frozen.model_sha256,'parent_model_sha256':parent.model_sha256,
                'new_fit_calls':1,'prior_financial_query_observations_used':False})
            receipt['phase']='post_freeze_availability'
            receipt['financial_availability']=availability_after_freeze(frozen,args.financial_root,root)
            receipt['success']=all(r['available']==r['total'] for r in receipt['financial_availability'])
            receipt['phase']='completed'
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
