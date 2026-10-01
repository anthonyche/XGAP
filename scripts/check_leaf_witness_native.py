#!/usr/bin/env python3
"""Tiny real Neo4j equivalence gate, with a new private store and no LLM calls."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import signal
import subprocess

from prepare_native_stores import discovery_ready
from xgap.agent.intent_certificate import IntentCandidate,IntentFamily,fingerprint
from xgap.agent.practical_planning import _baseline
from xgap.backends.neo4j_client import Neo4jClient
from xgap.compilers.features import default_profile
from xgap.experiments.ch6_fact_index import CORES
from xgap.experiments.ch6_heldout import template_query
from xgap.experiments.m15_native_services import LoopbackPortReservations,_neo4j_configuration
from xgap.experiments.one_shot_records import write_once
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.semantic_compiler import SemanticBackend
from xgap.runtime.semantic_planning import LogicalSource
from xgap.runtime.unified_physical import PhysicalMoves
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.tools import BackendPluginRegistry,NativeBackendPlugin,BackendInvokeTool


def run(runtime,java,output):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False);runtime=Path(runtime).resolve()
    conf=root/'conf';conf.mkdir()
    for part in ('data','transactions','logs','run','import','plugins'):(root/'neo4j'/part).mkdir(parents=True)
    ports=LoopbackPortReservations.acquire(2);http,bolt=ports.ports
    (conf/'neo4j.conf').write_text(_neo4j_configuration(neo4j_root=runtime,state_root=root,http_port=http,bolt_port=bolt,
        resource_profile=dict(heap_initial_size='128m',heap_max_size='512m',pagecache_size='64m'),query_timeout_seconds=20))
    ports.release(0);ports.release(1);log=(root/'service.log').open('w');process=None;receipt={}
    try:
        process=subprocess.Popen([str(runtime/'bin/neo4j'),'console'],cwd=runtime,stdout=log,stderr=subprocess.STDOUT,
            start_new_session=True,env={**os.environ,'JAVACMD':str(java),'NEO4J_CONF':str(conf),'NEO4J_HOME':str(runtime)})
        discovery_ready(process,'http://127.0.0.1:'+str(http)+'/')
        client=Neo4jClient(BackendDescriptor('neo4j','neo4j','cypher','lpg',runtime={
            'http_url_env':'XGAP_TOY_WITNESS_UNUSED_URL','default_http_url':'http://127.0.0.1:'+str(http),
            'default_password':'','timeout_seconds':20}))
        load=QueryArtifact('tiny-load','cypher',
            "CREATE (a:User {xgap_id:'u1',id:'user:1'}),(c:User {xgap_id:'u2',id:'user:2'}),"
            "(d:User {xgap_id:'u3',id:'user:3'}),(b:Movie {xgap_id:'m1',id:'movie:1'}),"
            "(z:Movie {xgap_id:'m2',id:'movie:2'}),"
            "(a)-[:RATED {xgap_id:'e1',rating:2,timestamp:1}]->(b),"
            "(a)-[:RATED {xgap_id:'e2',rating:3,timestamp:2}]->(b),"
            "(a)-[:RATED {xgap_id:'e3',rating:7,timestamp:3}]->(z),"
            "(c)-[:RATED {xgap_id:'f1',rating:9,timestamp:4}]->(b),"
            "(d)-[:RATED {xgap_id:'f2',rating:8,timestamp:5}]->(b)")
        loaded=client.execute(load)
        if not loaded.success:raise ValueError(str(loaded))
        schema=dict(identity_property='xgap_id',graph=dict(nodes={k:dict(properties=['id']) for k in ('User','Movie')},
            edges=[dict(label='RATED',source='User',target='Movie',properties=['rating','timestamp'])]))
        backend=SemanticBackend('neo4j','https://test/',identity_property='xgap_id',profile=default_profile('neo4j'))
        sources={'graph':LogicalSource('graph','tiny-v1',('neo4j',))};backends={'neo4j':backend}
        policy=replace(OneShotPolicy.for_mode('performance'),max_parallelism=1)
        registry=BackendPluginRegistry();registry.register(NativeBackendPlugin('neo4j',client))
        scheduler=FederatedScheduler(BackendInvokeTool(registry));cases=[]
        for name,total in [('incoming_minimum',2),('witnessed_sum',5),('witnessed_count',2),('outgoing_maximum',3)]:
            q=template_query(CORES['D2'],name,'user:1',0)
            program,assignment=lower_compact_query(q,schema,version='v2',optimize=True)
            family=IntentFamily('native-leaf',(IntentCandidate.create(fingerprint(q),q),),(),'tiny-v1',language_version='v2',coverage_basis='tiny authored gate')
            seed=_baseline(program,assignment,sources,backends,policy,optimize_reads=False)
            moves=PhysicalMoves(family,schema,backends,policy,sources)
            first=list(moves.neighbors(0,seed));parents=[seed]+[p for p in first if p.metadata['unified_rewrite']['proof'].get('kind')=='mandatory_anchor_fanout']
            leaf=[p for parent in parents for p in moves.neighbors(0,parent) if p.metadata['unified_rewrite']['rule']=='leaf_witness']
            if name=='outgoing_maximum':
                if leaf:raise ValueError('Correlated non-boundary witness was reduced unsafely')
                cases.append(dict(query=name,success=True,admission='declined: witness depends on another retained node'))
                continue
            if not leaf:raise ValueError('No native leaf rewrite for '+name)
            baseline=scheduler.execute(seed);expected=[dict(result='movie:1',total=total)]
            if not baseline.success or list(baseline.final_rows)!=expected:raise ValueError('Baseline differs: '+str(baseline))
            plan=leaf[0];result=scheduler.execute(plan)
            write_once(root/(name+'-plan.json'),plan.to_dict());write_once(root/(name+'-execution.json'),result.to_dict())
            if not result.success or list(result.final_rows)!=expected:raise ValueError('Leaf differs: '+str(result))
            cases.append(dict(query=name,expected=expected,baseline=list(baseline.final_rows),actual=list(result.final_rows),success=True))
        receipt=dict(success=True,cases=cases,model_calls=0,scope='tiny exact-equivalence gate, not performance evidence')
    except Exception as e:receipt=dict(success=False,error=str(e),error_type=type(e).__name__)
    finally:
        if process and process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
        log.close()
        receipt['source_stopped']=process is None or process.poll() is not None
        write_once(root/'receipt.json',receipt)
    print(json.dumps(receipt));return 0 if receipt['success'] else 2


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for k in ('runtime','java','output'):parser.add_argument('--'+k,required=True)
    args=parser.parse_args();raise SystemExit(run(args.runtime,args.java,args.output))
