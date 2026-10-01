#!/usr/bin/env python3
"""One financial NL-only request on owned tiny Neo4j/Fuseki; no retry or fitting."""

import argparse
import getpass
import json
import os
from pathlib import Path
import shutil
import time

from xgap.backends.neo4j_client import Neo4jClient
from xgap.experiments.external_federation import deadline
from xgap.experiments.financial_nl_profile import publish_profile, sha, QUERY_ID
from xgap.experiments.m15_finbench_partition import NEO4J_BATCH_FILENAME
from xgap.experiments.m15_fixture_loader import FusekiGraphStoreFixtureLoader
from xgap.experiments.m15_native_services import (LoopbackPortReservations, ServiceSpec,
    _fuseki_server_configuration, _neo4j_configuration, start_service, stop_service, wait_for_service_health)
from xgap.experiments.one_shot_records import write_once, run_record, evaluate_record
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import QueryArtifact


REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO/'datasets/financial_nl_tiny_v1'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', required=True, type=Path)
    parser.add_argument('--read-key', action='store_true', help='Read model credential with terminal echo disabled; never store it')
    parser.add_argument('--syntax-profile', choices=('v1','v2','v3'), default='v1')
    parser.add_argument('--interpretation-profile', choices=('semantic-dag-v1','compact-graph-v1'), default='semantic-dag-v1')
    parser.add_argument('--java', default='/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home/bin/java')
    parser.add_argument('--runtime-root', type=Path, default=Path('/Users/anthonyche/xgap-data/d202-local-native-20260910-diagnostic2/runtime'))
    args = parser.parse_args()
    if args.interpretation_profile == 'compact-graph-v1' and args.syntax_profile != 'v1':
        parser.error('Legacy syntax options cannot be combined with compact interpretation')
    key = getpass.getpass('LLM credential: ') if args.read_key else os.environ.get('XGAP_EXTERNAL_LLM_API_KEY')
    if not key: raise ValueError('Configured model credential is unset; no external action')
    root = args.output_root.resolve(); root.mkdir(parents=True, exist_ok=False)
    receipt = {'schema_version':'xgap-financial-nl-native-v1', 'success':False, 'phase':'preparation',
        'question_id':QUERY_ID, 'maximum_model_calls':1, 'maximum_final_executions':1,
        'fit_calls':0, 'training_calls':0, 'baseline_calls':0, 'probe_calls':0, 'retries':0,
        'paper_result':False, 'loads':[], 'shutdown':[], 'interpretation_profile':args.interpretation_profile}
    running, ports = [], None
    try:
        with deadline(240):
            ports = LoopbackPortReservations.acquire(3); np,bp,fp = ports.ports
            nu,fu = f'http://127.0.0.1:{np}',f'http://127.0.0.1:{fp}'
            at = time.perf_counter()
            pin = publish_profile(root/'profile', endpoints={'neo4j':nu, 'fuseki':fu}, syntax_profile=args.syntax_profile,
                interpretation_profile=args.interpretation_profile)
            # Reference is not read by publication or inference; its hash is sealed below
            # with the authored fixture before dispatch, independently of any result.
            reference_hash = sha(FIXTURE/'reference.json')
            request_hash = sha(FIXTURE/'request.json')
            sealed = [Path(__file__), REPO/'src/xgap/experiments/financial_nl_profile.py',
                FIXTURE/'request.json', FIXTURE/'reference.json', root/'profile/profile.json',
                root/'profile'/NEO4J_BATCH_FILENAME, root/'profile/control.ttl']
            if args.interpretation_profile == 'compact-graph-v1':
                sealed += [REPO/'src/xgap'/name for name in ('semantic/compact_query.py', 'semantic/compact_lowering.py',
                    'llm/compact_interpretation.py', 'experiments/compact_profile.py', 'experiments/one_shot_profile.py')]
                sealed.append(REPO/'prompts/interpretation/compact_graph_v1.txt')
            write_once(root/'input_seal.json', {'files':{str(p):sha(p) for p in sealed},
                'reference_consumption':'hash before dispatch; scoring after terminal record only'})
            receipt['offline_preparation_ms'] = (time.perf_counter()-at)*1000
            state = root/'state'
            for part in ('neo4j/data','neo4j/transactions','neo4j/logs','neo4j/run','neo4j/import','neo4j/plugins','fuseki'):
                (state/part).mkdir(parents=True)
            neo_root=args.runtime_root/'neo4j-community-5.26.30'; rdf_root=args.runtime_root/'apache-jena-fuseki-5.6.0'
            conf=state/'neo4j-conf'; shutil.copytree(neo_root/'conf',conf)
            (conf/'neo4j.conf').write_text(_neo4j_configuration(neo4j_root=neo_root,state_root=state,http_port=np,bolt_port=bp,
                resource_profile={'heap_initial_size':'256m','heap_max_size':'512m','pagecache_size':'128m'},query_timeout_seconds=15))
            (state/'fuseki/config.ttl').write_text(_fuseki_server_configuration(query_timeout_seconds=15))
            specs=(ServiceSpec('neo4j','neo4j','5.26.30',(str(neo_root/'bin/neo4j'),'console'),neo_root,
                {'JAVACMD':args.java,'NEO4J_CONF':str(conf),'NEO4J_HOME':str(neo_root)},nu+'/db/neo4j/tx/commit',root/'neo4j.log'),
                ServiceSpec('fuseki','fuseki','5.6.0',(str(rdf_root/'fuseki-server'),'--localhost','--ping','--port',str(fp),'--update','--mem','/tiny'),rdf_root,
                {'JAVA':args.java,'FUSEKI_HOME':str(rdf_root),'FUSEKI_BASE':str(state/'fuseki'),'JVM_ARGS':'-Xms128m -Xmx512m'},fu+'/$/ping',root/'fuseki.log'))
            at = time.perf_counter(); receipt['phase']='owned_startup'
            for index,spec in enumerate(specs):
                for slot in ((0,1) if index==0 else (2,)): ports.release(slot)
                service=start_service(spec); running.append(service)
                write_once(root/(spec.service_id+'-owner.json'), {'pid':service.process.pid,'spec':spec.to_dict()})
                health=wait_for_service_health(service,timeout_seconds=45)
                write_once(root/(spec.service_id+'-health.json'),health.to_dict())
                if not health.success: raise RuntimeError('Owned service failed readiness; no restart')
            receipt['offline_startup_ms']=(time.perf_counter()-at)*1000
            neo=Neo4jClient(BackendDescriptor('neo4j','neo4j','cypher','property_graph',runtime={'timeout_seconds':20}))
            neo.http_url,neo.database=nu,'neo4j'
            desc=BackendDescriptor('fuseki','fuseki','sparql','rdf',runtime={'timeout_seconds':20})
            loader=FusekiGraphStoreFixtureLoader(desc); loader.base_url,loader.dataset=fu,'tiny'
            at=time.perf_counter(); receipt['phase']='owned_load'
            for index,line in enumerate((root/'profile'/NEO4J_BATCH_FILENAME).read_text().splitlines()):
                batch=json.loads(line)
                if batch['kind']!='constraint' and not batch.get('parameters',{}).get('rows'): continue
                loaded=neo.execute(QueryArtifact('load-'+str(index),'cypher',batch['statement'],kind='native',parameters=batch.get('parameters',{})))
                write_once(root/f'load-{index:03}.json',loaded.to_dict()); receipt['loads'].append({'kind':batch['kind'],'success':loaded.success})
                if not loaded.success: raise RuntimeError('Neo4j tiny load failed')
            loaded=loader.load(root/'profile/control.ttl'); write_once(root/'load-control.json',loaded.to_dict())
            receipt['loads'].append({'kind':'control_rdf','success':loaded.success})
            if not loaded.success: raise RuntimeError('Fuseki tiny load failed')
            receipt['offline_load_ms']=(time.perf_counter()-at)*1000
            receipt['phase']='ordinary_nl_request'
            original_key=os.environ.get('XGAP_EXTERNAL_LLM_API_KEY')
            os.environ['XGAP_EXTERNAL_LLM_API_KEY']=key
            try:
                run=run_record(profile_path=pin['path'],profile_sha256=pin['sha256'],
                    request_path=FIXTURE/'request.json',request_sha256=request_hash,
                    mode='performance',output=root/'request',operation='execute')
            finally:
                if original_key is None: os.environ.pop('XGAP_EXTERNAL_LLM_API_KEY',None)
                else: os.environ['XGAP_EXTERNAL_LLM_API_KEY']=original_key
                key=None
            receipt['request']=run
            receipt['phase']='post_seal_evaluation'
            evaluation=evaluate_record(root/'request/receipt.json',receipt_sha256=sha(root/'request/receipt.json'),
                reference_path=FIXTURE/'reference.json',reference_sha256=reference_hash,output=root/'evaluation.json')
            receipt['evaluation']=evaluation
            receipt['success']=run['success'] and evaluation['answer_em']==1.0
            receipt['phase']='completed'
    except BaseException as error:
        receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        key=None
        for service in reversed(running): receipt['shutdown'].append(stop_service(service).to_dict())
        if ports: ports.close()
        receipt['owned_processes_terminal']=all(s.process.poll() is not None for s in running)
        receipt['success'] &= receipt['owned_processes_terminal']
        write_once(root/'receipt.json',receipt)
    print(json.dumps({'success':receipt['success'],'phase':receipt['phase'],'receipt':str(root/'receipt.json'),
        'request_status':receipt.get('request',{}).get('status'),'owned_processes_terminal':receipt['owned_processes_terminal']}))
    return 0 if receipt['success'] else 1


if __name__=='__main__': raise SystemExit(main())
