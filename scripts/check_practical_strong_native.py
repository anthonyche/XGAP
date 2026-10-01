#!/usr/bin/env python3
"""One strong-profile NL/template gate on a frozen five-node toy.

Catalog mode has eight edges; model mode has nine and one live predicate action.
One selected plan joins Neo4j and Fuseki, then independent authored gold scoring.
No benchmark, fit, current-query probe or retry.
"""
import argparse
from dataclasses import replace
import getpass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/'src'))
from xgap.agent.practical_execution import FrozenClarificationTool, run_practical_semantic_query
from xgap.agent.practical_planning import BindingAction, BindingEvidence, BindingState, PracticalMode, program_identity
from xgap.agent.practical_question import PracticalQuestionOptions
from xgap.agent.practical_tools import frozen_catalog_acquisition
from xgap.agent.question import run_question
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.catalog.bundle import FrozenResolutionBundle
from xgap.experiments.external_federation import deadline
from xgap.experiments.m15_fixture_loader import FusekiGraphStoreFixtureLoader
from xgap.experiments.m15_native_services import (LoopbackPortReservations, ServiceSpec,
    _fuseki_server_configuration, _neo4j_configuration, start_service, stop_service, wait_for_service_health)
from xgap.experiments.one_shot_records import write_once, CapturingClient
from xgap.experiments.toy_backbone import DEFAULT_FIXTURE, load_fixture
from xgap.experiments.toy_binding import BUNDLE_FIXTURE, INTAKE_FIXTURE, FIXTURE, load_binding_cases, interpretation_inputs
from xgap.experiments.toy_semantic import toy_backends
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.semantic_planning import LogicalSource
from xgap.semantic.program import SemanticGraphProgram
from xgap.tools import ToolRegistry


def pin(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def prepare(root):
    graph, _, mapping = load_fixture()
    case = load_binding_cases()[0]
    request, provider = interpretation_inputs(case)
    # Two equivalent logical snapshot aliases restrict each operator to a different
    # physical engine. The semantic skeleton, constraints and gold are unchanged.
    provider = replace(provider, operator_sources={'paths':{'$hole':'source'},'people':'toy-people'})
    program = SemanticGraphProgram.from_dict(provider.interpret(request).payload['program'])
    ref = json.loads((BUNDLE_FIXTURE/'reference.json').read_text())
    bundle = FrozenResolutionBundle.load(BUNDLE_FIXTURE/ref['root'], expected_bundle_hash=ref['bundle_hash'])
    snapshot = hashlib.sha256(json.dumps(graph, sort_keys=True).encode()).hexdigest()
    sources = {'toy':LogicalSource('toy',snapshot,('neo4j',)),
               'toy-people':LogicalSource('toy-people',snapshot,('fuseki',))}
    values = {}
    # Explicit fixed request/template slots, not the expected binding or answer oracle.
    for slot, scalar in {'predicate':'KNOWS','type':'Person','age':30,'source':'toy'}.items():
        kind = next(h.kind for h in program.holes if h.hole_id == slot)
        values[slot] = next(c for c,v in bundle.bindings.items() if v.kind == kind and v.value == scalar)
    evidence = (BindingEvidence('$structure',program_identity(program),'trusted_request','toy-template','v1'),
        *(BindingEvidence(s,c,'trusted_request','toy-request','v1') for s,c in values.items()))
    initial = BindingState(tuple(sorted(values.items())), evidence)
    action, tool = frozen_catalog_acquisition(program,'person',('entity:alice','entity:bob'),
        bundle.catalog, question=request.question)
    clarification = BindingAction('clarify-person','person','practical.clarify',
        (('alice','entity:alice'),('bob','entity:bob')),'toy-clarification','v1','clarification',2)
    answer_file = root/'clarification-bindings-only.json'
    write_once(answer_file, {'schema_version':'xgap-clarification-bindings-v1',
        'program_sha256':program_identity(program),'source_id':'toy-clarification','version':'v1',
        'bindings':{'person':'entity:alice'}})
    registry = ToolRegistry(); registry.register(tool); registry.register(FrozenClarificationTool(answer_file))
    options = PracticalQuestionOptions(initial, mode=PracticalMode(improve_physical=False),
        actions=(action,clarification),resolution_tools=registry,limits=StrongSearchLimits(improvement_actions=0))
    return case,request,provider,program,bundle,ref,sources,toy_backends(mapping),options


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root',required=True,type=Path)
    parser.add_argument('--profile',choices=('catalog','model'),default='catalog')
    parser.add_argument('--read-key',action='store_true')
    parser.add_argument('--java',default='/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home/bin/java')
    parser.add_argument('--runtime-root',type=Path,default=Path('/Users/anthonyche/xgap-data/d202-local-native-20260910-diagnostic2/runtime'))
    args = parser.parse_args(); root = args.output_root.resolve(); root.mkdir(parents=True,exist_ok=False)
    receipt = {'schema_version':'xgap-practical-strong-native-v1','success':False,'query_budget':1,
        'nodes':5,'edges':8,'live_llm':False,'paper_result':False,'baseline_calls':0,'fit_calls':0,
        'current_query_probes':0,'automatic_retries':0,'loads':[],'shutdown':[],
        'input_profile':'trusted template NL; fixed source deployment aliases; frozen catalog',
        'estimator':'unavailable; feasible fallback only'}
    running=[]; ports=None; captured=[]; proposal=None
    key_name='XGAP_EXTERNAL_LLM_API_KEY'; previous=os.environ.get(key_name)
    try:
        with deadline(240):
            if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):
                raise ValueError('Commit before a real native gate')
            receipt['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
            fixture_root=DEFAULT_FIXTURE
            if args.profile=='model':
                from practical_model_fixture import FIXTURE as MODEL_FIXTURE, model_provider, prepare_model
                key=getpass.getpass('LLM credential (not recorded): ') if args.read_key else previous
                if not key: raise ValueError('Missing configured model credential')
                os.environ[key_name]=key; key=None
                proposal=model_provider(); fixture_root=MODEL_FIXTURE
                prepared=prepare_model(root,proposal)
                receipt.update(edges=9,live_llm=True,model_call_budget=1,
                    input_profile='trusted bounded NL template; live non-authoritative predicate choice',
                    acquisition_search='frozen model-before-experiment-clarification priority; no latency estimates')
            else:
                prepared=prepare(root)
            case,request,provider,program,bundle,ref,sources,backends,options = prepared
            bundle_root=Path(ref.get('base_root',BUNDLE_FIXTURE))/ref['root']
            paths = [Path(__file__), *[REPO/'src/xgap/agent'/n for n in
                ('strong_planning.py','practical_planning.py','practical_execution.py','practical_question.py','practical_tools.py','question.py')]]
            directories=((fixture_root,) if proposal else (DEFAULT_FIXTURE,FIXTURE,INTAKE_FIXTURE,BUNDLE_FIXTURE))
            paths += [p for directory in directories
                      for p in sorted(directory.rglob('*')) if p.is_file()]
            if proposal: paths.append(REPO/'scripts/practical_model_fixture.py')
            write_once(root/'input-seal.json', {'files':[pin(p) for p in paths], 'request':request.to_dict(),
                'program':program.to_dict(),'operator_sources':provider.operator_sources,
                'declared_gold_source':case.get('gold_path',str(FIXTURE/'cases.json')),'selection_reads_gold':False,
                'model_config':proposal.config.safe_dict() if proposal else None})
            # Adapter objects are opaque to planning; no health or query I/O here.
            planned = run_practical_semantic_query(program,initial_state=options.initial_state,
                resolution_tools=options.resolution_tools,actions=options.actions,mode=options.mode,
                limits=options.limits,operator_sources=provider.operator_sources,binding_values=bundle.bindings,
                sources=sources,backends=backends,backend_clients={'neo4j':object(),'fuseki':object()},
                estimator=None,execute=False)
            write_once(root/'preflight.json',planned)
            if not planned['search']['strong']: raise ValueError('No strong policy before service startup')
            if proposal and planned['search']['policy']['action_id']!='llm:predicate':
                raise ValueError('Declared profile did not select model action; do not make an incidental live call')
            state = root/'state'
            for part in ('neo4j/data','neo4j/transactions','neo4j/logs','neo4j/run','neo4j/import','neo4j/plugins','fuseki'):
                (state/part).mkdir(parents=True)
            neo_root = args.runtime_root/'neo4j-community-5.26.30'; rdf_root = args.runtime_root/'apache-jena-fuseki-5.6.0'
            conf = state/'neo4j-conf'; shutil.copytree(neo_root/'conf',conf)
            ports = LoopbackPortReservations.acquire(3); np,bp,fp = ports.ports
            (conf/'neo4j.conf').write_text(_neo4j_configuration(neo4j_root=neo_root,state_root=state,http_port=np,bolt_port=bp,
                resource_profile={'heap_initial_size':'256m','heap_max_size':'512m','pagecache_size':'128m'},query_timeout_seconds=15))
            (state/'fuseki/config.ttl').write_text(_fuseki_server_configuration(query_timeout_seconds=15))
            nu,fu = f'http://127.0.0.1:{np}',f'http://127.0.0.1:{fp}'
            specs = (ServiceSpec('neo4j','neo4j','5.26.30',(str(neo_root/'bin/neo4j'),'console'),neo_root,
                {'JAVACMD':args.java,'NEO4J_CONF':str(conf),'NEO4J_HOME':str(neo_root)},nu+'/db/neo4j/tx/commit',root/'neo4j.log'),
                ServiceSpec('fuseki','fuseki','5.6.0',(str(rdf_root/'fuseki-server'),'--localhost','--ping','--port',str(fp),'--update','--mem','/toy'),rdf_root,
                {'JAVA':args.java,'FUSEKI_HOME':str(rdf_root),'FUSEKI_BASE':str(state/'fuseki'),'JVM_ARGS':'-Xms128m -Xmx512m'},fu+'/$/ping',root/'fuseki.log'))
            at = time.perf_counter()
            for index,spec in enumerate(specs):
                for slot in ((0,1) if index == 0 else (2,)): ports.release(slot)
                service = start_service(spec); running.append(service)
                write_once(root/(spec.service_id+'-owner.json'),{'pid':service.process.pid,'spec':spec.to_dict()})
                health = wait_for_service_health(service,timeout_seconds=45)
                write_once(root/(spec.service_id+'-health.json'),health.to_dict())
                if not health.success: raise RuntimeError('Owned service readiness failed; no restart')
            receipt['offline_startup_ms'] = (time.perf_counter()-at)*1000
            neo = Neo4jClient(BackendDescriptor('neo4j','neo4j','cypher','property_graph',runtime={'timeout_seconds':20}))
            neo.http_url,neo.database = nu,'neo4j'
            desc = BackendDescriptor('fuseki','fuseki','sparql','rdf',runtime={'timeout_seconds':20})
            rdf = FusekiClient(desc); rdf.base_url,rdf.dataset = fu,'toy'
            loader = FusekiGraphStoreFixtureLoader(desc); loader.base_url,loader.dataset = fu,'toy'
            at = time.perf_counter()
            loaded = neo.execute(QueryArtifact('load-tiny','cypher',(fixture_root/'load.cypher').read_text(),kind='native'))
            write_once(root/'load-neo4j.json',loaded.to_dict()); receipt['loads'].append(loaded.success)
            if not loaded.success: raise RuntimeError('Tiny Neo4j fixture load failed')
            loaded = loader.load(fixture_root/'load.ttl')
            write_once(root/'load-fuseki.json',loaded.to_dict()); receipt['loads'].append(loaded.success)
            if not loaded.success: raise RuntimeError('Tiny Fuseki fixture load failed')
            receipt['offline_load_ms'] = (time.perf_counter()-at)*1000
            lock = threading.Lock()
            clients = {c.backend_id:CapturingClient(c,root,captured,lock) for c in (neo,rdf)}
            write_once(root/'query-intent.json',{'query_budget':1,'question':request.question,
                'input_profile':receipt['input_profile'],'alternative_executions':0})
            result = run_question(request,provider,practical_options=options,
                catalog_root=bundle_root,catalog_hash=ref['bundle_hash'],
                sources=sources,backends=backends,backend_clients=clients,estimator=None)
            receipt['result'] = write_once(root/'result.json',result)
            # Score only after durable capture; no additional reference query execution.
            expected=(json.loads(Path(case['gold_path']).read_text())['gold_rows'] if proposal else case['expected_rows'])
            outcome = {'expected_rows':expected,'actual_rows':result['answer_rows'],
                'rows_equal':result['answer_rows']==expected,
                'used_backends':sorted({r['backend_id'] for r in captured}),
                'final_plan_executions':result['final_plan_executions'],
                'backend_remote_calls':result['backend_remote_calls'],'model_calls':result['model_calls'],
                'catalog_observations':sum(o['kind']=='tool_result' and o['source']=='practical.catalog:person'
                    for o in result.get('execution_state',{}).get('observations',[])),
                'model_observations':sum(o['kind']=='tool_result' and o['source']=='practical.llm:predicate'
                    for o in result.get('execution_state',{}).get('observations',[])),
                'clarification_calls':result.get('clarification_calls'),
                'selected_unvalidated':result.get('execution',{}).get('unvalidated_bindings'),
                'model_statuses':[o['payload']['status'] for o in result.get('execution_state',{}).get('observations',[])
                    if o['kind']=='tool_result' and o['source']=='practical.llm:predicate']}
            receipt['outcome'] = write_once(root/'outcome.json',outcome)
            receipt['success'] = (result['success'] and outcome['rows_equal'] and
                outcome['used_backends']==['fuseki','neo4j'] and outcome['final_plan_executions']==1 and
                outcome['backend_remote_calls']==len(captured)==2 and
                (outcome['catalog_observations']==1 if not proposal else
                 outcome['model_observations']==outcome['model_calls']==1))
            if proposal:
                receipt['same_request_model_proposal_accepted']=(outcome['model_statuses']==['success'] and
                    outcome['selected_unvalidated']==['predicate'] and outcome['clarification_calls']==0)
                receipt['success'] = receipt['success'] and receipt['same_request_model_proposal_accepted']
    except Exception as error:
        receipt['error'] = f'{type(error).__name__}: {error}'
    finally:
        if previous is None: os.environ.pop(key_name,None)
        else: os.environ[key_name]=previous
        for service in reversed(running):
            receipt['shutdown'].append(stop_service(service).to_dict())
        if ports: ports.close()
        receipt['owned_processes_terminal'] = all(s.process.poll() is not None for s in running)
        receipt['success'] = receipt['success'] and receipt['owned_processes_terminal']
        receipt['captured_backend_calls'] = len(captured)
        if proposal is not None and proposal.last_invocation is not None:
            receipt['model_invocation']=write_once(root/'model-invocation.json',proposal.last_invocation.to_dict())
        write_once(root/'receipt.json',receipt)
    print(json.dumps(receipt,ensure_ascii=False,default=str))
    return 0 if receipt['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
