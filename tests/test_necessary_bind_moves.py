"""Tiny D2-shaped replay of the full-source witness planning failure."""
import json
import sqlite3
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


def test_anchor_and_nested_witness_reductions_preserve_independent_gold(tmp_path):
    fixture=CoreMaterializationTest();index=fixture.index(tmp_path)
    db=sqlite3.connect(tmp_path/'facts.sqlite')
    add_nodes(db,[dict(id='user:2',type='User')])
    db.execute('INSERT INTO edges VALUES(?,?,?,?,?,?)',(5,'witness','user:2','movie:1',5,1));db.commit()
    db.close();meta=json.loads(index.read_text());meta['database']=pin(tmp_path/'facts.sqlite');index.write_text(json.dumps(meta))
    _,graphs=fixture.generate(tmp_path/'facts',index)
    pp=publish(tmp_path/'facts/receipt.json',PARENT,PIN,tmp_path/'profile')
    profile=FrozenOneShotProfile.load(pp['path'],expected_sha256=pp['sha256'])
    doc,_,_,sources,backends,_,modes=profile.materialize();schema=revise_schema(doc['source_schema'])
    q=template_query(CORES['D2'],'incoming_minimum','user:1',0,cross=False)
    expected=evaluate(q,index)['rows'];assert expected
    program,assignment=lower_compact_query(q,schema,version='v2',optimize=True)
    family=IntentFamily('complete',(IntentCandidate.create(fingerprint(q),q),),(),
        snapshot_identity(sources,backends,schema),language_version='v2')
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
