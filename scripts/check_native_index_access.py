"""Tiny Neo4j identity-index equivalence gate; never large-data performance evidence."""
import os,sys,json,signal,subprocess
from pathlib import Path
from dataclasses import replace
from prepare_native_stores import discovery_ready
from xgap.experiments.m15_native_services import LoopbackPortReservations,_neo4j_configuration
from xgap.backends.neo4j_client import Neo4jClient
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import QueryArtifact
from xgap.compilers.edge_match import compile_edge_match
from xgap.pattern.ast import EdgePattern,NodePattern,Direction
from xgap.runtime.semantic_compiler import SemanticBackend
from xgap.runtime.physical_strategies import _bound_match_artifact
import argparse
parser=argparse.ArgumentParser(description=__doc__)
for key in ('runtime','java','output'):parser.add_argument('--'+key,required=True)
args=parser.parse_args()
root=Path(args.output).resolve();root.mkdir(exist_ok=False)
runtime=Path(args.runtime).resolve();java=Path(args.java).resolve()
conf=root/'conf';conf.mkdir()
for part in ('data','transactions','logs','run','import','plugins'):(root/'neo4j'/part).mkdir(parents=True)
ports=LoopbackPortReservations.acquire(2);http,bolt=ports.ports
(conf/'neo4j.conf').write_text(_neo4j_configuration(neo4j_root=runtime,state_root=root,http_port=http,bolt_port=bolt,resource_profile=dict(heap_initial_size='128m',heap_max_size='512m',pagecache_size='64m'),query_timeout_seconds=15))
ports.release(0);ports.release(1);log=(root/'service.log').open('w');process=None;receipt=dict(success=False,cases=[],model_calls=0,paper_result=False)
try:
 process=subprocess.Popen([str(runtime/'bin/neo4j'),'console'],cwd=runtime,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env={**os.environ,'JAVACMD':str(java),'NEO4J_CONF':str(conf),'NEO4J_HOME':str(runtime)})
 discovery_ready(process,'http://127.0.0.1:'+str(http)+'/')
 client=Neo4jClient(BackendDescriptor('neo4j','neo4j','cypher','lpg',runtime=dict(http_url_env='XGAP_INDEX_TEST_UNUSED',default_http_url='http://127.0.0.1:'+str(http),default_password='',timeout_seconds=15)))
 for text in ["CREATE CONSTRAINT idx_movie FOR (n:Movie) REQUIRE n.xgap_id IS UNIQUE", "CREATE CONSTRAINT idx_user FOR (n:User) REQUIRE n.xgap_id IS UNIQUE", "CREATE (a:User {xgap_id:'u1'}),(c:User {xgap_id:'u2'}),(b:Movie {xgap_id:'m1'}),(d:Movie {xgap_id:'m2'}),(s:User:Movie {xgap_id:'self'}),(z:Other {xgap_id:'other'}),(a)-[:RATED {xgap_id:'e1',rating:1}]->(b),(a)-[:RATED {xgap_id:'e2'}]->(b),(c)-[:RATED {xgap_id:'e3',rating:2}]->(b),(c)-[:RATED {xgap_id:'e4',rating:3}]->(d),(s)-[:RATED {xgap_id:'loop',rating:4}]->(s),(a)-[:RATED {xgap_id:'wrongtype'}]->(z)"]:
  r=client.execute(QueryArtifact('fixture','cypher',text));assert r.success,r.error
 backend=SemanticBackend('neo4j','https://test/',identity_property='xgap_id')
 def canon(rows):return sorted(json.dumps(r,sort_keys=True) for r in rows)
 for i,(direction,column,keys) in enumerate([(Direction.OUT,'target',['m1','m1','self','https://else/m2']),(Direction.OUT,'source',['u1','self']),(Direction.IN,'source',['m1','self']),(Direction.IN,'target',[]) ]):
  labels=('User','Movie') if direction==Direction.OUT else ('Movie','User')
  base=compile_edge_match(EdgePattern(label='RATED',direction=direction),{'score':'rating'},backend_id='neo4j',identity_property='xgap_id',source=NodePattern(label=labels[0]),target=NodePattern(label=labels[1]))
  indexed,key=_bound_match_artifact(base,backend,max_bindings=8,max_binding_bytes=4096,identity_column=column)
  # The old compiler had no mandatory-label checkpoint metadata. Its exact
  # generated text and all original predicates remain the comparison oracle.
  oldpoint={k:v for k,v in base.parameters['native_binding_checkpoint'].items() if k!='node_labels'}
  oldbase=replace(base,parameters={**base.parameters,'native_binding_checkpoint':oldpoint})
  original,_=_bound_match_artifact(oldbase,backend,max_bindings=8,max_binding_bytes=4096,identity_column=column)
  keys=[k if k.startswith('https://') else 'https://test/'+k for k in keys]
  original=replace(original,parameters={**original.parameters,key:keys})
  indexed=replace(indexed,parameters={**indexed.parameters,key:keys})
  results=[client.execute(q) for q in (original,indexed)]
  assert all(r.success for r in results),[r.error for r in results]
  assert canon(results[0].rows)==canon(results[1].rows)
  receipt['cases'].append(dict(direction=direction.name,column=column,keys=keys,rows=len(results[0].rows),equivalent=True))
  if i==0:
   for name,q in [('original',original),('indexed',indexed)]:
    r=client.explain(q);assert r.success,r.error;(root/(name+'-plan.json')).write_text(json.dumps(r.to_dict(),indent=2))
    def operators(p):
     yield p.get('operatorType','')
     for child in p.get('children',[]):yield from operators(child)
    ops=list(operators(r.metadata['native_plan']['root']))
    if name=='indexed':assert any('IndexSeek' in op for op in ops),ops
    else:assert any('AllNodesScan' in op for op in ops),ops
 receipt['success']=True
except Exception as e:receipt.update(error=str(e),error_type=type(e).__name__)
finally:
 if process and process.poll() is None:
  os.killpg(process.pid,signal.SIGTERM)
  try:process.wait(timeout=15)
  except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
 log.close();receipt['source_stopped']=process is None or process.poll() is not None
 (root/'receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
raise SystemExit(0 if receipt['success'] else 2)
