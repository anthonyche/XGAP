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
from test_native_semijoin import fixture, fused_plan


def run(runtime, fuseki, java, output):
    import threading
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    runtime=Path(runtime).resolve();fuseki=Path(fuseki).resolve();java=Path(java).resolve()
    ports=LoopbackPortReservations.acquire(3);http,bolt,rdfport=ports.ports
    processes=Processes(root);receipt=dict(success=False,cases=[],model_calls=0,paper_result=False,
        scope='tiny semantic equivalence only; two plans run for differential testing, not online plan selection')
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
          (c)-[:LINK {key:'c-bad'}]->(bad), (c)-[:LINK {key:'c-b'}]->(b),
          (c)-[:LINK {key:'c-copy'}]->(copy), (c)-[:LINK {key:'c-d'}]->(d),
          (c)-[:LINK {key:'c-n'}]->(n), (c)-[:LINK {key:'c-m'}]->(m),
          (alt)-[:LINK {key:'alt-copy'}]->(copy), (alt)-[:LINK {key:'alt-d'}]->(d)"""
        loaded=neo.execute(QueryArtifact('fixture','cypher',create));assert loaded.success,loaded.error
        ttl=root/'control.ttl';ttl.write_text('''@prefix t: <https://tiny/> .
          t:bad a t:Item; t:allowed false . t:b a t:Item; t:allowed false .
          t:copy a t:Item; t:allowed true, false . t:n a t:Item .''')
        loaded=loader.load(ttl);assert loaded.success,loaded.to_dict()
        q=fixture()[0];cases=[]
        for name in ('allowed','denied','early-exclusion-and-alternate-key','descending','empty','nullable-not-equal'):
            case=deepcopy(q)
            if name=='denied':case['where'][-1]['right']['value']=False
            if name=='early-exclusion-and-alternate-key':case['limit']=1
            if name=='descending':case['order_by'][0]['direction']='desc';case['limit']=1000
            if name=='empty':case['where'][0]['right']['value']='absent'
            if name=='nullable-not-equal':case['where'][-1]['op']='ne';case['where'][-1]['right']['value']=False
            cases.append((name,case))
        for name,q in cases:
            values,plan=fused_plan(q);original=values[4];target=root/name;target.mkdir()
            registry=BackendPluginRegistry();records=[];lock=threading.Lock()
            for b,client in [('neo4j',neo),('fuseki',rdf)]:
                registry.register(NativeBackendPlugin(b,CapturingClient(client,target,records,lock)))
            scheduler=FederatedScheduler(BackendInvokeTool(registry),retention='roots')
            before=scheduler.execute(original);after=scheduler.execute(plan)
            write_once(target/'plan.json',plan.to_dict());write_once(target/'original.json',before.to_dict())
            write_once(target/'fused.json',after.to_dict())
            assert before.success,before.to_dict();assert after.success,after.to_dict()
            assert list(before.final_rows)==list(after.final_rows),(name,before.final_rows,after.final_rows)
            if name=='early-exclusion-and-alternate-key':
                assert list(after.final_rows)==[dict(result='apple',other='aaa-alt',destination='omega')]
            if name=='empty':assert not after.final_rows
            receipt['cases'].append(dict(name=name,rows=len(after.final_rows),ordered_rows_equal=True))
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
    with deadline(300):raise SystemExit(run(**vars(parser.parse_args())))
