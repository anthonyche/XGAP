"""Two real tiny scalar probes through the production observer; no model calls."""
import argparse
import json
from pathlib import Path
import sys

from prepare_native_stores import discovery_ready
from run_external_federation_tiny import Processes,ready
from xgap.agent.live_probe import LiveProbePolicy,bind_live_probes
from xgap.agent.unified_family import UnifiedSettings
from xgap.agent.unified_lookahead import Limits,Resources
from xgap.backends.neo4j_client import Neo4jClient
from xgap.backends.fuseki_client import FusekiClient
from xgap.experiments.campaign_source_observer import CampaignSourceObserver,SourceObservationBudget
from xgap.experiments.external_federation import deadline
from xgap.experiments.m15_fixture_loader import FusekiGraphStoreFixtureLoader
from xgap.experiments.m15_native_services import LoopbackPortReservations,_neo4j_configuration
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.process_guard import _stop_group,ProcessBudget
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.semantic_planning import LogicalSource

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_native_semijoin import fixture


def run(runtime,fuseki,java,output):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    runtime,fuseki,java=map(lambda p:Path(p).resolve(),(runtime,fuseki,java))
    processes=Processes(root);ports=None;observer=None
    receipt=dict(success=False,model_calls=0,paper_result=False,probe_calls=0,cases=[],
        scope='Two source-adapter/proxy syntax gates on a fresh tiny graph; no performance comparison')
    try:
        ports=LoopbackPortReservations.acquire(3);http,bolt,rdfport=ports.ports
        conf=root/'conf';conf.mkdir()
        for part in ('data','transactions','logs','run','import','plugins'):(root/'neo4j'/part).mkdir(parents=True)
        (conf/'neo4j.conf').write_text(_neo4j_configuration(neo4j_root=runtime,state_root=root,
            http_port=http,bolt_port=bolt,resource_profile=dict(heap_initial_size='128m',heap_max_size='512m',
            pagecache_size='64m'),query_timeout_seconds=20))
        ports.release(0);ports.release(1)
        neo_proc=processes.start('neo4j',[str(runtime/'bin/neo4j'),'console'],cwd=runtime,
            env={'JAVACMD':str(java),'NEO4J_CONF':str(conf),'NEO4J_HOME':str(runtime)})
        discovery_ready(neo_proc,'http://127.0.0.1:'+str(http)+'/')
        ports.release(2)
        rdf_proc=processes.start('fuseki',[str(java),'-Xms64m','-Xmx256m','-jar',str(fuseki),
            '--localhost','--port',str(rdfport),'--update','--mem','/tiny'],cwd=fuseki.parent,
            env={'FUSEKI_BASE':str(root/'rdf-state')})
        ready(rdf_proc,rdfport)
        neo=Neo4jClient(BackendDescriptor('neo4j','neo4j','cypher','lpg',runtime=dict(timeout_seconds=20)))
        neo.http_url='http://127.0.0.1:'+str(http);neo.password='';neo.database='neo4j'
        rdf_desc=BackendDescriptor('fuseki','fuseki','sparql','rdf',runtime=dict(timeout_seconds=20))
        rdf=FusekiClient(rdf_desc);rdf.base_url='http://127.0.0.1:'+str(rdfport);rdf.dataset='tiny'
        loaded=neo.execute(QueryArtifact('offline-fixture','cypher',
            "UNWIND range(1,4) AS i CREATE (:Actor {key:toString(i),name:'actor'}),"
            "(:Item {key:toString(i),name:'item'})"))
        if not loaded.success:raise ValueError(loaded.error)
        ttl=root/'fixture.ttl';ttl.write_text('@prefix t: <https://tiny/> .\n'+
            '\n'.join(f't:i{i} a t:Item; t:allowed true; t:key "{i}" .' for i in range(1,5)))
        loader=FusekiGraphStoreFixtureLoader(rdf_desc);loader.base_url=rdf.base_url;loader.dataset='tiny'
        loaded=loader.load(ttl)
        if not loaded.success:raise ValueError(str(loaded))
        receipt['offline_fixture_loads']=2
        observer=CampaignSourceObserver({'/db/neo4j/tx/commit':neo.http_url+'/db/neo4j/tx/commit',
            '/tiny/sparql':rdf.base_url+'/tiny/sparql'},root/'observations',
            budget=SourceObservationBudget(max_calls=2,timeout_seconds=20,capture_compression='gzip'))
        observer.set_phase('two-real-statistics-probes')
        neo.http_url=observer.base_url;rdf.base_url=observer.base_url
        _,_,_,_,seed,_,moves=fixture()
        settings=UnifiedSettings(limits=Limits(aggregation='expectation'),live_probe_policy=LiveProbePolicy(
            'tiny-real-engine-capped-count-v1','Syntax/category validation only, not fitted estimates',
            max_targets=16,threshold=2,sparse_rows=1,dense_rows=10))
        sources={v['source_id']:LogicalSource(v['source_id'],v['snapshot_version'],(backend,))
                 for backend,v in seed.metadata['source_identities'].items()}
        bound,binding=bind_live_probes(settings,moves.family,{0:(seed,0,Resources())},sources)
        clients={'neo4j':neo,'fuseki':rdf}
        for backend in ('neo4j','fuseki'):
            target=next(t for t in bound.information_targets if t.backend==backend
                and json.loads(t.artifact_json)['parameters'].get('compiler')=='semantic_node_match_v1')
            pin=write_once(root/(backend+'-target.json'),json.loads(target.artifact_json))
            label,result=target.invoke(clients,sources)
            receipt['probe_calls']+=1
            if not result['success'] or label!='large' or str(result['rows'][0]['value'])!='3':
                raise ValueError(str(result))
            receipt['cases'].append(dict(backend=backend,target=pin,expected_capped_count=3,
                expected_category='large',result=result))
        receipt['binding']=write_once(root/'binding.json',binding)
        receipt['source_observations']=observer.seal_phase('two-real-statistics-probes')
        receipt['success']=(receipt['source_observations']['requests']==2
            and receipt['source_observations']['forwarded_requests']==2
            and not receipt['source_observations']['failure_categories'])
    except Exception as error:receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        if observer:
            observer.close();receipt['observer_stopped']=not observer.thread.is_alive() and observer.inflight==0
        receipt['closure']=[]
        for name,process in reversed(processes.owned):
            cleanup=_stop_group(process,ProcessBudget())
            if cleanup['complete'] and process.poll() is None:process.wait(timeout=2)
            receipt['closure'].append(dict(name=name,returncode=process.poll(),**cleanup))
        for log in processes.logs:log.close()
        if ports:ports.close()
        receipt['success'] &= all(c['complete'] and c['returncode'] is not None for c in receipt['closure'])
        receipt['receipt']=write_once(root/'receipt.json',receipt)
    print(json.dumps(receipt));return 0 if receipt['success'] else 2


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('runtime','fuseki','java','output'):parser.add_argument('--'+key,required=True)
    with deadline(240):raise SystemExit(run(**vars(parser.parse_args())))
