"""Tiny Neo4j + Fuseki differential gate for exact external membership."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

from prepare_native_stores import discovery_ready
from run_external_federation_tiny import Processes, ready
from xgap.backends.neo4j_client import Neo4jClient
from xgap.backends.fuseki_client import FusekiClient
from xgap.experiments.external_federation import deadline
from xgap.experiments.m15_fixture_loader import FusekiGraphStoreFixtureLoader
from xgap.experiments.m15_native_services import LoopbackPortReservations, _neo4j_configuration
from xgap.experiments.one_shot_records import write_once, CapturingClient
from xgap.experiments.process_guard import _stop_group, ProcessBudget
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.scheduler import FederatedScheduler
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_native_semijoin import fixture, fused_plan, refine_driver


def run(runtime, fuseki, java, output, closed_edges_only=False, only_case=None):
    import threading
    if only_case is not None and not closed_edges_only:
        raise ValueError('Single closed-edge case requires --closed-edges-only')
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    runtime=Path(runtime).resolve();fuseki=Path(fuseki).resolve();java=Path(java).resolve()
    ports=LoopbackPortReservations.acquire(3);http,bolt,rdfport=ports.ports
    processes=Processes(root);receipt=dict(success=False,cases=[],model_calls=0,paper_result=False,
        scope='tiny semantic equivalence and driver traffic; three plans run for differential testing, not online plan selection')
    try:
        conf=root/'conf';conf.mkdir()
        for part in ('data','transactions','logs','run','import','plugins'):(root/'neo4j'/part).mkdir(parents=True)
        (conf/'neo4j.conf').write_text(_neo4j_configuration(neo4j_root=runtime,state_root=root,http_port=http,bolt_port=bolt,
            resource_profile=dict(heap_initial_size='128m',heap_max_size='512m',pagecache_size='64m'),query_timeout_seconds=20))
        ports.release(0);ports.release(1)
        process=processes.start('neo4j',[str(runtime/'bin/neo4j'),'console'],cwd=runtime,
            env={'JAVACMD':str(java),'NEO4J_CONF':str(conf),'NEO4J_HOME':str(runtime)})
        discovery_ready(process,'http://127.0.0.1:'+str(http)+'/')
        ports.release(2)
        rdf_process=processes.start('fuseki',[str(java),'-Xms128m','-Xmx256m','-jar',str(fuseki),
            '--localhost','--port',str(rdfport),'--update','--mem','/tiny'],cwd=fuseki.parent,
            env={'FUSEKI_BASE':str(root/'rdf-state')})
        ready(rdf_process,rdfport)
        neo=Neo4jClient(BackendDescriptor('neo4j','neo4j','cypher','lpg',runtime=dict(timeout_seconds=20)))
        neo.http_url='http://127.0.0.1:'+str(http);neo.database='neo4j';neo.password=''
        rdf_desc=BackendDescriptor('fuseki','fuseki','sparql','rdf',runtime=dict(timeout_seconds=20))
        rdf=FusekiClient(rdf_desc);rdf.base_url='http://127.0.0.1:'+str(rdfport);rdf.dataset='tiny'
        loader=FusekiGraphStoreFixtureLoader(rdf_desc);loader.base_url=rdf.base_url;loader.dataset=rdf.dataset
        create="""CREATE (a:Actor {key:'a',name:'anchor'}), (c:Actor {key:'c',name:'other'}),
          (c2:Actor {key:'c',name:'otherCopy'}), (alt:Actor {key:'alt',name:'aaa-alt'}),
          (bad:Item {key:'bad',name:'000-denied'}), (b:Item {key:'b',name:'apple'}),
          (copy:Item {key:'copy',name:'apple'}), (d:Item {key:'d',name:'omega'}),
          (n:Item {key:'n',name:'null-flag'}), (m:Item {key:'m',name:'missing-flag'}),
          (a)-[:LINK {key:'a-bad',score:1}]->(bad), (a)-[:LINK {key:'a-b',score:1}]->(b),
          (a)-[:LINK {key:'a-copy',score:1}]->(copy), (a)-[:LINK {key:'a-copy2',score:2}]->(copy),
          (a)-[:LINK {key:'a-n',score:1}]->(n), (a)-[:LINK {key:'a-m',score:1}]->(m),
          (a)-[:LINK {key:'a-d',score:1}]->(d),
          (c)-[:LINK {key:'c-bad'}]->(bad), (c)-[:LINK {key:'c-b'}]->(b),
          (c)-[:LINK {key:'c-copy'}]->(copy), (c)-[:LINK {key:'c-d'}]->(d),
          (c)-[:LINK {key:'c-n'}]->(n), (c)-[:LINK {key:'c-m'}]->(m),
          (alt)-[:LINK {key:'alt-copy'}]->(copy), (alt)-[:LINK {key:'alt-d'}]->(d)"""
        loaded=neo.execute(QueryArtifact('fixture','cypher',create));assert loaded.success,loaded.error
        if closed_edges_only:
            # Only duplicate-ID nodes carry the closing edge. Aliasing a
            # previously bound native node would silently lose these answers.
            adversary="""MATCH (a:Actor {key:'a'})-[r:LINK]->(d:Item {key:'d'}) DELETE r
              CREATE (ac:Actor {key:'a',name:'anchorCopy'}),
              (dc:Item {key:'d',name:'omegaCopy'}),
              (ac)-[:LINK {key:'closure-1'}]->(dc),
              (ac)-[:LINK {key:'closure-2'}]->(dc)"""
            loaded=neo.execute(QueryArtifact('duplicate-endpoint-closure','cypher',adversary))
            assert loaded.success,loaded.error
            for label in ('Actor','Item'):
                loaded=neo.execute(QueryArtifact('nonunique-key-index','cypher',
                    'CREATE INDEX FOR (n:'+label+') ON (n.key)'))
                assert loaded.success,loaded.error
            loaded=neo.execute(QueryArtifact('await-indexes','cypher','CALL db.awaitIndexes(15)'))
            assert loaded.success,loaded.error
        noise="UNWIND range(1,64) AS i CREATE (:Actor {key:'unused-a'+toString(i),name:'unused'}), (:Item {key:'unused-b'+toString(i),name:'unused'})"
        loaded=neo.execute(QueryArtifact('irrelevant-nodes','cypher',noise));assert loaded.success,loaded.error
        ttl=root/'control.ttl';ttl.write_text('''@prefix t: <https://tiny/> .
          t:bad a t:Item; t:allowed false . t:b a t:Item; t:allowed false .
          t:copy a t:Item; t:allowed true, false . t:n a t:Item .''')
        loaded=loader.load(ttl);assert loaded.success,loaded.to_dict()
        q=fixture()[0];cases=[]
        names=('cycle-membership','cycle-empty','cycle-descending','cycle-edge-identities') if closed_edges_only else (
            'allowed','denied','early-exclusion-and-alternate-key','descending','empty','nullable-not-equal',
            'cycle-membership','cycle-empty')
        for name in names:
            if only_case is not None and name!=only_case:continue
            case=deepcopy(q)
            if name=='denied':case['where'][-1]['right']['value']=False
            if name=='early-exclusion-and-alternate-key':case['limit']=1
            if name=='descending':case['order_by'][0]['direction']='desc';case['limit']=1000
            if name=='empty':case['where'][0]['right']['value']='absent'
            if name=='nullable-not-equal':case['where'][-1]['op']='ne';case['where'][-1]['right']['value']=False
            if name.startswith('cycle-'):case['edges'].append(dict(var='h',type='LINK',source='a',target='d'))
            if name=='cycle-empty':case['where'][0]['right']['value']='absent'
            if name=='cycle-descending':case['order_by'][0]['direction']='desc';case['limit']=1
            if name=='cycle-edge-identities':
                case['where'].append(dict(left=dict(var='d',property='name'),op='eq',
                    right={'value':'omega'},value_type='scalar'))
                case['select']['closing_edge']=dict(var='h',property=None)
                case['order_by'].append(dict(field='closing_edge',direction='asc'));case['limit']=100
            cases.append((name,case))
        for name,q in cases:
            values,plan=fused_plan(q);original=values[4];refined=refine_driver(plan,values[-1]);target=root/name;target.mkdir()
            registry=BackendPluginRegistry();records=[];lock=threading.Lock()
            for b,client in [('neo4j',neo),('fuseki',rdf)]:
                registry.register(NativeBackendPlugin(b,CapturingClient(client,target,records,lock)))
            scheduler=FederatedScheduler(BackendInvokeTool(registry),retention='roots')
            before=scheduler.execute(original)
            fused_start=len(records);after=scheduler.execute(plan)
            refined_start=len(records);optimized=scheduler.execute(refined)
            write_once(target/'plan.json',plan.to_dict());write_once(target/'original.json',before.to_dict())
            write_once(target/'fused.json',after.to_dict())
            write_once(target/'refined-plan.json',refined.to_dict());write_once(target/'refined.json',optimized.to_dict())
            assert before.success,before.to_dict();assert after.success,after.to_dict()
            assert optimized.success,optimized.to_dict()
            assert list(before.final_rows)==list(after.final_rows),(name,before.final_rows,after.final_rows)
            assert list(before.final_rows)==list(optimized.final_rows),(name,before.final_rows,optimized.final_rows)
            if name=='early-exclusion-and-alternate-key':
                assert list(after.final_rows)==[dict(result='apple',other='aaa-alt',destination='omega')]
            if name in ('empty','cycle-empty'):assert not after.final_rows
            if name=='cycle-membership':assert after.final_rows
            explanation=None
            if closed_edges_only:
                native=refined.nodes[-1];a=native.parameters['artifact']
                # Keys come from this development fixture, never formal gold.
                raw,_=FederatedScheduler._bind_artifact(native,a,[{native.parameters['bind_field']:'https://tiny/copy'}])
                explanation=neo.explain(QueryArtifact.from_dict(raw))
                assert explanation.success,explanation.error
                write_once(target/'explain.json',explanation.to_dict())
                def walk(n):
                    yield n
                    for child in n.get('children',[]):yield from walk(child)
                edges={e['edge'] for e in a['parameters']['source_pushdown']['closed_endpoint_access']['edges']}
                expansions=[n for n in walk(explanation.metadata['native_plan']['root'])
                    if 'Expand' in n.get('operatorType','') and any('['+e+':' in n.get('Details','') for e in edges)]
                assert expansions and all('Expand(Into)' in n['operatorType'] for n in expansions),expansions
                if name=='cycle-edge-identities':
                    assert {r['closing_edge'] for r in after.final_rows}=={'https://tiny/closure-1','https://tiny/closure-2'}
            def traffic(calls):
                return dict(calls=len(calls),returned_rows=sum(len(r['execution']['rows']) for r in calls),
                    decoded_rows_json_bytes=sum(len(json.dumps(r['execution']['rows'],sort_keys=True).encode()) for r in calls))
            receipt['cases'].append(dict(name=name,rows=len(after.final_rows),ordered_rows_equal=True,
                fused_traffic=traffic(records[fused_start:refined_start]),refined_traffic=traffic(records[refined_start:]),
                byte_scope='serialized decoded result rows, not wire bytes; same tiny source and final answer'))
            if explanation:
                receipt['cases'][-1]['closing_edge_expand_into']=True
        # A star exposes a Cartesian-size intermediate even though each edge
        # input is small. Compare both physical binding and execution streaming.
        from test_streaming_star import star_plans
        for descending in (() if closed_edges_only else (False,True)):
            original,refined,proofs=star_plans(descending=descending)
            name='star-desc' if descending else 'star-asc';target=root/name;target.mkdir()
            registry=BackendPluginRegistry();records=[];lock=threading.Lock()
            registry.register(NativeBackendPlugin('neo4j',CapturingClient(neo,target,records,lock)))
            tool=BackendInvokeTool(registry)
            materialized=FederatedScheduler(tool,retention='roots',stream_topk=False)
            before=materialized.execute(original);middle=materialized.execute(refined)
            after=FederatedScheduler(tool,retention='roots').execute(refined)
            assert before.success and middle.success and after.success
            assert before.final_rows==middle.final_rows==after.final_rows
            assert len(after.final_rows)==3 and after.retention['streaming_topk']
            for label,plan,result in [('original',original,before),('refined',refined,middle),('streamed',refined,after)]:
                write_once(target/(label+'-plan.json'),plan.to_dict());write_once(target/(label+'.json'),result.to_dict())
            receipt['cases'].append(dict(name=name,rows=len(after.final_rows),ordered_rows_equal=True,
                early_driver_proofs=[p['early_driver'] for p in proofs if 'early_driver' in p],
                materialized_peak_registered_rows=middle.retention['peak_registered_rows'],
                streamed_peak_registered_rows=after.retention['peak_registered_rows'],
                streaming=after.retention['streaming_topk']))
        receipt['success']=True
    except Exception as error:receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        receipt['closure']=[]
        for name,process in reversed(processes.owned):
            cleanup=_stop_group(process,ProcessBudget())
            if cleanup['complete'] and process.poll() is None:process.wait(timeout=2)
            receipt['closure'].append(dict(name=name,returncode=process.poll(),**cleanup))
        for log in processes.logs:log.close()
        ports.close()
        receipt['success'] &= all(c['complete'] and c['returncode'] is not None for c in receipt['closure'])
        write_once(root/'receipt.json',receipt)
    print(json.dumps(receipt));return 0 if receipt['success'] else 2


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('runtime','fuseki','java','output'):parser.add_argument('--'+key,required=True)
    parser.add_argument('--closed-edges-only',action='store_true')
    parser.add_argument('--only-case',choices=('cycle-membership','cycle-empty','cycle-descending','cycle-edge-identities'))
    with deadline(300):raise SystemExit(run(**vars(parser.parse_args())))
