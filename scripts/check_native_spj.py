"""Tiny real-Neo4j differential admission for native SPJ, never a paper result."""
import argparse
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

from prepare_native_stores import discovery_ready
from xgap.experiments.m15_native_services import LoopbackPortReservations, _neo4j_configuration
from xgap.backends.neo4j_client import Neo4jClient
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.contracts import RuntimeNode,RuntimeNodeKind
from xgap.tools.backends import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from test_native_spj import compile_query, native_cases


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('runtime','java','output'):parser.add_argument('--'+key,required=True)
    parser.add_argument('--prefix-topk',action='store_true')
    args=parser.parse_args();root=Path(args.output).resolve();root.mkdir(exist_ok=False)
    runtime=Path(args.runtime).resolve();java=Path(args.java).resolve()
    conf=root/'conf';conf.mkdir()
    for part in ('data','transactions','logs','run','import','plugins'):(root/'neo4j'/part).mkdir(parents=True)
    ports=LoopbackPortReservations.acquire(2);http,bolt=ports.ports
    (conf/'neo4j.conf').write_text(_neo4j_configuration(neo4j_root=runtime,state_root=root,http_port=http,bolt_port=bolt,
        resource_profile=dict(heap_initial_size='128m',heap_max_size='512m',pagecache_size='64m'),query_timeout_seconds=15))
    ports.release(0);ports.release(1)
    log=(root/'service.log').open('w');process=None
    receipt=dict(success=False,cases=[],model_calls=0,paper_result=False,prefix_topk_requested=args.prefix_topk)
    try:
        process=subprocess.Popen([str(runtime/'bin/neo4j'),'console'],cwd=runtime,stdout=log,stderr=subprocess.STDOUT,
            start_new_session=True,env={**os.environ,'JAVACMD':str(java),'NEO4J_CONF':str(conf),'NEO4J_HOME':str(runtime)})
        discovery_ready(process,'http://127.0.0.1:'+str(http)+'/')
        client=Neo4jClient(BackendDescriptor('neo4j','neo4j','cypher','lpg',runtime=dict(http_url_env='XGAP_SPJ_TEST_UNUSED',
            default_http_url='http://127.0.0.1:'+str(http),default_password='',timeout_seconds=15)))
        # Duplicate logical IDs intentionally exercise property equality joins;
        # a compiler that merges native node variables would change these rows.
        create="""CREATE (a:Actor {key:'a',name:'anchor'}), (c:Actor {key:'c',name:'other'}),
          (c2:Actor {key:'c',name:'otherCopy'}), (b:Item {key:'b',name:'apple'}),
          (d:Item {key:'d',name:'Ω'}), (e:Item {key:'e',name:'😀'}),
          (f:Item {key:'f',name:''}), (n:Item {key:'n'}), (z:Actor {key:'z'}), (s:Actor:Item {key:'s',name:'self'}),
          (a)-[:LINK {key:'ab1',score:0}]->(b), (a)-[:LINK {key:'ab2',score:1.5}]->(b),
          (a)-[:LINK {key:'ab3'}]->(b), (a)-[:LINK {key:'an',score:2}]->(n),
          (c)-[:LINK {key:'cb'}]->(b), (c)-[:LINK {key:'cd'}]->(d),
          (c)-[:LINK {key:'ce'}]->(e), (c)-[:LINK {key:'cf'}]->(f),
          (c)-[:LINK {key:'cn'}]->(n), (c2)-[:LINK {key:'c2d'}]->(d),
          (s)-[:LINK {key:'ss'}]->(s), (a)-[:LINK {key:'as',score:-1}]->(s),
          (z)-[:LINK {key:'zb',score:2}]->(b), (z)-[:LINK {key:'zd',score:2}]->(d)"""
        loaded=client.execute(QueryArtifact('fixture','cypher',create));assert loaded.success,loaded.error
        registry=BackendPluginRegistry();registry.register(NativeBackendPlugin('neo4j',client))
        scheduler=FederatedScheduler(BackendInvokeTool(registry),retention='roots')
        cases=[(name,q,s,b,None) for name,q,s,b in native_cases()]
        _,q,s,b,_=cases[0]
        q=deepcopy(q);q['where']=q['where'][:1];q['limit']=1000
        cases.extend((name,q,s,b,name) for name in ('not','or-null'))
        if args.prefix_topk:
            # A lexicographically earlier prefix exists locally but has no
            # complete witness. A second equal-valued prefix has other valid
            # witnesses that cannot be discarded by choosing one native node.
            extra="""MATCH (a:Actor {key:'a'}), (d:Item {key:'d'})
              CREATE (dead:Item {key:'dead',name:'000-dead'}),
              (z:Actor {key:'dead-user',name:'000-other'}),
              (a)-[:LINK {key:'a-dead',score:2}]->(dead),
              (z)-[:LINK {key:'z-dead',score:2}]->(dead),
              (copy:Item {key:'bCopy',name:'apple'}),
              (alt:Actor {key:'alt',name:'aaa-alt'}),
              (a)-[:LINK {key:'a-copy',score:2}]->(copy),
              (alt)-[:LINK {key:'alt-copy',score:2}]->(copy),
              (alt)-[:LINK {key:'alt-d',score:2}]->(d)"""
            result=client.execute(QueryArtifact('prefix-adversaries','cypher',extra));assert result.success,result.error
            from test_native_spj import fixture
            q,s,b=fixture();q['limit']=1;cases.append(('dead-prefix-and-alternate-witness',q,s,b,None))
            q=deepcopy(q);q['limit']=5
            cases.append(('null-first-prefix',q,s,b,None))
            q=fixture()[0];q['order_by']=list(reversed(q['order_by']));q['limit']=5
            cases.append(('late-output-prefix',q,s,b,None))
            q=fixture()[0];q['select']={'result':q['select']['result']};q['order_by']=q['order_by'][:1]
            cases.append(('one-column-prefix',q,s,b,None))
        for name,q,s,b,wrapper in cases:
            artifact,original=compile_query(q,s,b,condition_wrapper=wrapper,prefix_topk=args.prefix_topk,
                nulls='first' if name=='null-first-prefix' else None)
            fused=replace(original,nodes=(RuntimeNode(original.roots[0],RuntimeNodeKind.REMOTE_QUERY,
                parameters=dict(backend_id='neo4j',artifact=artifact.to_dict())),))
            before=scheduler.execute(original);after=scheduler.execute(fused)
            assert before.success,before.to_dict()
            assert after.success,after.to_dict()
            (root/(name+'-query.json')).write_text(json.dumps(artifact.to_dict(),indent=2))
            assert list(before.final_rows)==list(after.final_rows),(name,before.final_rows,after.final_rows)
            if args.prefix_topk and name=='dead-prefix-and-alternate-witness':
                assert dict(after.final_rows[0])=={'result':'apple','other':'aaa-alt','destination':'Ω'}
            if args.prefix_topk and name=='zigzag':
                explanation=client.explain(artifact);assert explanation.success,explanation.error
                (root/'prefix-explain.json').write_text(json.dumps(explanation.to_dict(),indent=2))
            receipt['cases'].append(dict(name=name,rows=len(after.final_rows),ordered_rows_equal=True,
                original_remote_calls=len([n for n in original.nodes if n.kind.value=='remote_query']),
                fused_remote_calls=1))
        receipt['success']=True
    except Exception as error:
        receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        if process and process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
        log.close();receipt['source_stopped']=process is None or process.poll() is not None
        (root/'receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
    return 0 if receipt['success'] else 2


if __name__=='__main__':raise SystemExit(main())
