"""Tiny D2-shaped replay of the full-source witness planning failure."""
import json
import sqlite3
import pytest
from dataclasses import replace

from test_ch6_fact_materialization import CoreMaterializationTest
from test_compact_roles_v2 import PARENT,PIN
from xgap.agent.intent_certificate import IntentCandidate,IntentFamily,fingerprint
from xgap.agent.intent_execution import snapshot_identity
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


@pytest.mark.parametrize('template',('incoming_minimum','witnessed_sum','witnessed_count'))
def test_anchor_and_nested_witness_reductions_preserve_independent_gold(tmp_path,template):
    fixture=CoreMaterializationTest();index=fixture.index(tmp_path)
    db=sqlite3.connect(tmp_path/'facts.sqlite')
    add_nodes(db,[dict(id='user:2',type='User')])
    db.execute('INSERT INTO edges VALUES(?,?,?,?,?,?)',(5,'witness','user:2','movie:1',5,1));db.commit()
    db.close();meta=json.loads(index.read_text());meta['database']=pin(tmp_path/'facts.sqlite');index.write_text(json.dumps(meta))
    _,graphs=fixture.generate(tmp_path/'facts',index)
    pp=publish(tmp_path/'facts/receipt.json',PARENT,PIN,tmp_path/'profile')
    profile=FrozenOneShotProfile.load(pp['path'],expected_sha256=pp['sha256'])
    doc,estimator,_,sources,backends,_,modes=profile.materialize();schema=revise_schema(doc['source_schema'])
    q=template_query(CORES['D2'],template,'user:1',0,cross=False)
    expected=evaluate(q,index)['rows'];assert expected
    program,assignment=lower_compact_query(q,schema,version='v2',optimize=True)
    family=IntentFamily('complete',(IntentCandidate.create(fingerprint(q),q),),(),
        snapshot_identity(sources,backends,schema),language_version='v2',coverage_basis='authored complete correctness query')
    physical=replace(modes['performance'][0],max_parallelism=1)
    seed=_baseline(program,assignment,sources,backends,physical,optimize_reads=False)
    moves=PhysicalMoves(family,schema,backends,physical,sources)
    calls=[]
    class Local(FusekiClient):
        def _post_query(self,text):
            calls.append(text)
            return json.loads(graphs[self.backend_id.removeprefix('rdf_')].query(text).serialize(format='json'))
    registry=BackendPluginRegistry()
    for name in backends:
        registry.register(NativeBackendPlugin(name,Local(BackendDescriptor(name,'fuseki','sparql','rdf'))))
    scheduler=FederatedScheduler(BackendInvokeTool(registry))
    anchors=[p for p in moves.neighbors(0,seed) if p.metadata['unified_rewrite']['proof'].get('kind')=='mandatory_anchor_fanout']
    assert len(anchors)==1 and not calls
    nested=[p for p in moves.neighbors(0,anchors[0]) if len(p.metadata['unified_rewrite']['proof'].get('chain',()))>1]
    assert nested and not calls
    # Only this tiny correctness oracle executes alternatives; the online
    # controller sees no outcomes and still executes just its selected plan.
    for plan in [anchors[0],*nested]:
        result=scheduler.execute(plan)
        assert result.success,result
        assert list(result.final_rows)==expected,plan.metadata['unified_rewrite']

    # Existential leaf reduction must select a real jointly satisfying witness
    # before the contribution projection, preserving parallel contributing edges.
    leaf=[p for parent in [anchors[0],*nested] for p in moves.neighbors(0,parent)
          if p.metadata['unified_rewrite']['rule']=='leaf_witness']
    assert leaf
    for plan in leaf:
        for node in plan.nodes:
            a=node.parameters.get('artifact',{})
            if a.get('parameters',{}).get('leaf_witness'):
                assert '?xgap_leaf_id' in a['text'] and 'OPTIONAL' not in a['text']
        result=scheduler.execute(plan)
        assert result.success,result
        assert list(result.final_rows)==expected,plan.metadata['unified_rewrite']

    # A synthetic larger-population contract exercises one online selection;
    # the executed correctness graph stays tiny. No observed result is a score.
    from xgap.planning.relative_source_work import FrozenSourceWorkRanker
    from xgap.planning.joint_cost import JointCostProfile
    from xgap.agent.unified_family import run_unified_family,UnifiedSettings
    from xgap.agent.scope_authority import ScopedQueryUser,private_query_intent
    from xgap.experiments.one_shot_records import write_once
    populations=tuple((s.backend_id,2000,998000 if s.source_id=='graph' else 0) for s in estimator.statistics.entries)
    totals={b:n+e for b,n,e in populations}
    stats=replace(estimator.statistics,entries=tuple(replace(s,total_rows=totals[s.backend_id]) for s in estimator.statistics.entries))
    ranker=FrozenSourceWorkRanker(stats,populations,('id','xgap_id'),'fixture:independent-synthetic-counts')
    question='frozen correctness request';private=write_once(tmp_path/'private.json',private_query_intent(question,q,language_version='v2'))
    user=ScopedQueryUser(family,private['path'],private['sha256']);selected=[];executed=[]
    def execute(plan):
        selected.append(plan);result=scheduler.execute(plan)
        executed.append(result)
        return dict(success=result.success,answer_rows=list(result.final_rows))
    report=run_unified_family(question,family,user,prepare_seed=lambda *_:seed,execute=execute,
        costs=JointCostProfile(),settings=UnifiedSettings(),estimator=ranker,moves=moves)
    assert report['success'] and len(selected)==report['final_plan_executions']==1,[(n.node_id,n.error) for r in executed for n in r.node_results if n.error]
    assert list(executed[0].final_rows)==expected
    assert report['external_calls_during_search']==0
    assert any(n.kind.value=='remote_bind_query' for n in selected[0].nodes)
