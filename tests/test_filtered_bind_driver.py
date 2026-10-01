"""Retain necessary unary filters when avoiding a join materialization for keys."""
from dataclasses import replace
import json
import sqlite3

import pytest

import test_ch6_fact_materialization as core_fixture
from test_compact_roles_v2 import PARENT,PIN
from xgap.agent.intent_certificate import IntentCandidate,IntentFamily,fingerprint
from xgap.agent.practical_planning import _baseline
from xgap.backends.fuseki_client import FusekiClient
from xgap.experiments.ch6_core_profile import publish
from xgap.experiments.ch6_fact_index import CORES,add_nodes,pin
from xgap.experiments.ch6_heldout import template_query
from xgap.experiments.ch6_profile_revision import revise_schema
from xgap.experiments.ch6_sql_reference import evaluate
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.unified_physical import PhysicalMoves
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.tools import BackendPluginRegistry,NativeBackendPlugin,BackendInvokeTool


@pytest.mark.parametrize('cut',[2,99])
def test_filtered_bind_preserves_cycle_answers_and_empty_keys_skip_source(tmp_path,cut):
    fixture=core_fixture.CoreMaterializationTest();index=fixture.index(tmp_path)
    db=sqlite3.connect(tmp_path/'facts.sqlite');add_nodes(db,[dict(id='user:2',type='User')])
    db.executemany('INSERT INTO edges VALUES(?,?,?,?,?,?)',[
        (5,'other1','user:2','movie:1',1,4.5),
        (6,'other2','user:2','movie:2',1,4.5),
        (7,'anchor2','user:1','movie:2',1,4.5)])
    db.commit();db.close();meta=json.loads(index.read_text());meta['database']=pin(tmp_path/'facts.sqlite');index.write_text(json.dumps(meta))
    _,graphs=fixture.generate(tmp_path/'facts',index)
    pp=publish(tmp_path/'facts/receipt.json',PARENT,PIN,tmp_path/'profile')
    doc,_,_,sources,backends,_,modes=FrozenOneShotProfile.load(pp['path'],expected_sha256=pp['sha256']).materialize()
    schema=revise_schema(doc['source_schema']);query=template_query(CORES['D2'],'cycle','user:1',cut,cross=False)
    expected=evaluate(query,index)['rows'];assert bool(expected)==(cut==2)
    program,assignment=lower_compact_query(query,schema,version='v2',optimize=True)
    family=IntentFamily('toy-filtered-driver',(IntentCandidate.create(fingerprint(query),query),),(),
        'toy',language_version='v2',coverage_basis='tiny complete correctness query')
    policy=replace(modes['performance'][0],max_parallelism=1)
    seed=_baseline(program,assignment,sources,backends,policy,optimize_reads=False)
    moves=PhysicalMoves(family,schema,backends,policy,sources)
    anchored=next(p for p in moves.neighbors(0,seed)
        if p.metadata['unified_rewrite']['rule']=='entity_bind'
        and p.metadata['unified_rewrite']['proof'].get('target')=='cq5'
        and p.metadata['unified_rewrite']['proof'].get('driver')=='cq4')
    proposals=[p for p in moves.neighbors(0,anchored)
        if p.metadata['unified_rewrite']['rule']=='entity_bind'
        and p.metadata['unified_rewrite']['proof'].get('early_driver',{}).get('producer')=='cq6']
    assert proposals
    # Freeze one syntactically identified next-edge reduction, no trial winner.
    refined=next(p for p in proposals if p.metadata['unified_rewrite']['proof']['target']=='cq7')
    target=next(n for n in refined.nodes if n.node_id=='cq7/native')
    assert target.inputs==(refined.metadata['operator_outputs']['cq6'],)
    assert target.parameters['bind_field']=='v1'
    # The pre-fix early driver intentionally discarded the same required filter.
    old=replace(refined,nodes=tuple(replace(n,inputs=(refined.metadata['operator_outputs']['cq5'],))
        if n.node_id==target.node_id else n for n in refined.nodes))
    class Local(FusekiClient):
        def _post_query(self,text):
            return json.loads(graphs[self.backend_id.removeprefix('rdf_')].query(text).serialize(format='json'))
    registry=BackendPluginRegistry()
    for name in backends:registry.register(NativeBackendPlugin(name,Local(BackendDescriptor(name,'fuseki','sparql','rdf'))))
    scheduler=FederatedScheduler(BackendInvokeTool(registry))
    results=[scheduler.execute(p) for p in (old,refined)]
    assert all(r.success and list(r.final_rows)==expected for r in results)
    old_node,new_node=[next(n for n in r.node_results if n.node_id==target.node_id) for r in results]
    assert old_node.remote_calls==1
    assert new_node.remote_calls==(1 if expected else 0)
    if expected:assert new_node.row_count<old_node.row_count


@pytest.mark.parametrize('shared',[False,True])
def test_early_driver_tracks_right_collision_and_projection_without_crossing_shared_read(shared):
    from types import SimpleNamespace as N
    from xgap.runtime.necessary_bind_moves import early_key_driver
    from xgap.runtime.contracts import RuntimeNodeKind as R
    from xgap.semantic.program import SemanticOperatorKind as S
    def op(name,kind,inputs=(),**parameters):
        return N(operator_id=name,kind=kind,input_ids=inputs,parameters=parameters)
    ops=[op('m',S.MATCH,node={},entity_field='key'),
         op('p',S.PROJECT,('m',),projections={'renamed':{'kind':'field','field':'key'}}),
         op('f',S.FILTER,('p',),condition={'op':'ne','field':'renamed','value':'excluded'}),
         op('left',S.MATCH,node={},entity_field='lk'),
         op('join',S.JOIN,('left','f'),left_on='lk',right_on='renamed',right_prefix='r_'),
         op('root',S.PROJECT,('join',),projections={})]
    if shared:ops.append(op('shared',S.PROJECT,('m',),projections={}))
    schemas={k:{'fields':v} for k,v in dict(m=['key'],p=['renamed'],f=['renamed'],
        left=['lk','renamed'],join=['lk','renamed','r_renamed']).items()}
    plan=N(nodes=[N(node_id='m/native',kind=R.REMOTE_BIND_QUERY,semantic_operator_ids=('m',),parameters={}),
                  *[N(node_id=k+'/out') for k in schemas]],
        metadata={'operator_outputs':{k:k+'/out' for k in schemas},'schemas':schemas})
    output,field,proof=early_key_driver('join','r_renamed',N(operators=ops,roots=('root',)),plan)
    if shared:assert (output,field,proof)==('join/out','r_renamed',None)
    else:
        assert (output,field)==('f/out','renamed')
        assert proof['restricted_match']=='m' and proof['producer']=='f'
