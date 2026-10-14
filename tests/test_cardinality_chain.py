"""Source-only estimates tested against actual local scheduler rows, not timings."""
from dataclasses import replace
from collections import Counter
import pytest
from test_relative_source_work import fixture
from xgap.planning.cardinality_synopsis import ColumnSynopsis,join_rows
from xgap.planning.runtime_work_estimator import frozen_estimator_from_dict
from xgap.runtime.contracts import RuntimeNode,RuntimeNodeKind as R,FederatedExecutionPlan
from xgap.runtime.scheduler import FederatedScheduler
from xgap.tools.backends import BackendPluginRegistry,BackendInvokeTool,NativeBackendPlugin
from xgap.infrastructure.runtime import ExecutionReport


def plans():
    # Same equality join and selection. IDs ensure distinct joined pairs.
    left=[dict(entity='l'+str(i),k=i%10,flag='rare' if i<10 else 'common') for i in range(1000)]
    right=[dict(other='r'+str(i),k=i%10) for i in range(1000)]
    model,old=fixture()
    model=replace(model,statistics=replace(model.statistics,entries=tuple(replace(s,total_rows=1000) for s in model.statistics.entries)),
        populations=(('neo4j',1000,0),('fuseki',1000,0)),unique_node_properties=())
    def remote(name,b,properties):
        return RuntimeNode(name,R.REMOTE_QUERY,parameters=dict(backend_id=b,artifact=dict(
            artifact_id=name,language='sparql',text='SELECT * WHERE {}',parameters=dict(
                compiler='semantic_node_match_v1',scalar_properties=properties))))
    a=remote('left','neo4j',dict(k='k',flag='flag'));b=remote('right','fuseki',dict(k='k'))
    select=lambda parent:RuntimeNode('filter',R.COORDINATOR_FILTER,(parent,),dict(condition=dict(op='eq',field='flag',value='rare')))
    join=lambda parent:RuntimeNode('join',R.COORDINATOR_JOIN,(parent,'right'),dict(left_on='k',right_on='k'))
    late=replace(old,plan_id='late',nodes=(a,b,join('left'),select('join')),roots=('filter',))
    early=replace(old,plan_id='early',nodes=(a,b,select('left'),join('filter')),roots=('join',))
    profiles=[]
    for backend,rows in [('neo4j',left),('fuseki',right)]:
        for field in ('k','flag') if backend=='neo4j' else ('k',):
            counts=Counter(r[field] for r in rows)
            profiles.append(ColumnSynopsis(backend,'node:property:'+field,field,len(rows),len(counts),tuple(counts.items())))
    aware=replace(model,cardinality_aware=True,column_synopses=tuple(profiles))
    registry=BackendPluginRegistry()
    class Client:
        def __init__(self,b,rows):self.backend_id=b;self.rows=rows
        def execute(self,artifact):return ExecutionReport(self.backend_id,artifact.artifact_id,artifact.language,True,rows=self.rows)
    registry.register(NativeBackendPlugin('neo4j',Client('neo4j',left)))
    registry.register(NativeBackendPlugin('fuseki',Client('fuseki',right)))
    return model,aware,late,early,BackendInvokeTool(registry)


def test_selectivity_changes_choice_and_reduces_real_join_intermediate():
    old,new,late,early,tool=plans()
    # Conservative legacy model cannot distinguish the selective predicate.
    assert old.predict(late).relative_cost==old.predict(early).relative_cost
    chosen=min((late,early),key=lambda p:new.predict(p).relative_cost)
    assert chosen.plan_id=='early'
    before=FederatedScheduler(tool,retention='roots').execute(late)
    after=FederatedScheduler(tool,retention='roots').execute(chosen)
    assert before.success and after.success
    assert before.root_rows['filter']==after.root_rows['join']
    counts=lambda r:{n.node_id:n.row_count for n in r.node_results}
    assert counts(before)['join']==100000
    assert counts(after)['join']==1000
    assert after.retention['peak_registered_rows']<before.retention['peak_registered_rows']/20
    assert before.total_remote_calls==after.total_remote_calls==2


def test_skew_overlap_not_cartesian_or_uniform_and_snapshot_roundtrip():
    _,new,late,_,_=plans()
    hot=ColumnSynopsis('neo4j','node:property:k','k',1000,2,((0,990),(1,10)))
    cold=ColumnSynopsis('fuseki','node:property:k','k',1000,2,((0,10),(1,990)))
    skew=replace(new,column_synopses=(hot,cold))
    estimate=skew.predict(late)
    join=next(n for n in estimate.provenance['nodes'] if n['node']=='join')
    assert join['estimated_rows']==19800
    assert join_rows(hot.distribution(1000),hot.distribution(1000))==980200
    assert frozen_estimator_from_dict(skew.to_dict()).predict(late).relative_cost==estimate.relative_cost
    assert join_rows(hot.distribution(1000),replace(cold,domain='different').distribution(1000)) is None


def test_range_nulls_and_repeated_predicate_are_not_double_discounted():
    c=ColumnSynopsis('a','node:property:x','x',100,3,((1,10),(2,20),(3,30)),40).distribution(100)
    d=c.filtered('ge',2)
    assert d.rows==50 and d.filtered('ge',2).rows==50
    assert c.filtered('eq',7).rows==0
    partial=ColumnSynopsis('a','x','x',100,10,((1,10),)).distribution(100)
    assert partial.filtered('ge',2).filtered('ge',2).rows==partial.filtered('ge',2).rows
    assert c.filtered('eq',1.0).rows==c.filtered('eq',1).rows
    with pytest.raises(ValueError):ColumnSynopsis('a','x','x',2,1,((1,3),))


def test_probe_category_propagates_through_join_and_subplan_reuse_invalidates_only_dependents():
    _,model,late,early,_=plans();session=model.for_request()
    a=session.predict(early)
    stats=session.diagnostics();session.predict(late)
    assert session.hits>=2 # same source reads reused across different physical plans
    small=session.predict_conditioned(early,{'left':10})
    large=session.predict_conditioned(early,{'left':1000})
    assert small.relative_cost<large.relative_cost
    small_join=next(n['estimated_rows'] for n in small.provenance['nodes'] if n['node']=='join')
    large_join=next(n['estimated_rows'] for n in large.provenance['nodes'] if n['node']=='join')
    assert small_join<large_join
    assert session.predict(early).relative_cost==a.relative_cost
    changed=replace(early,metadata={**early.metadata,'source_identities':{}})
    with pytest.raises(ValueError,match='snapshot'):session.predict(changed)
    assert session.diagnostics()['entries']<2048


def test_controller_pays_one_useful_probe_and_avoids_wide_transfer():
    """Fixed semantic input; cost-dependent physical intersection order only."""
    import json
    from types import SimpleNamespace
    from test_unified_actions import fixture as family_fixture,target
    from xgap.agent.unified_family import FamilyDomain,FamilyState,UnifiedSettings
    from xgap.agent.unified_contract import UnifiedTerminalContract
    from xgap.agent.unified_lookahead import Limits,Resources,State,choose,run_online,Observation,Terminal
    from xgap.planning.joint_cost import JointCostProfile
    _,model,base,_,_=plans();_,_,_,family,_,_=family_fixture()
    a,b=base.nodes[:2]
    a=replace(a,semantic_operator_ids=('left-op',));b=replace(b,semantic_operator_ids=('right-op',))
    def bound(node,parent):
        return replace(node,kind=R.REMOTE_BIND_QUERY,inputs=(parent,),parameters={**node.parameters,
            'bind_field':'entity','parameter':'keys','max_bindings':100000})
    def project(parent):return RuntimeNode('ids',R.COORDINATOR_ROW_PROJECT,(parent,),
        dict(projections={'entity':dict(kind='field',field='entity')}))
    left=replace(base,plan_id='left-first',nodes=(a,bound(b,'left'),project('right')),roots=('ids',))
    right=replace(base,plan_id='right-first',nodes=(b,bound(a,'right'),project('left')),roots=('ids',))
    model=replace(model,column_synopses=(),transfer_byte_quantum=1024,populations=(('neo4j',100000,0),('fuseki',1000,0)),
        statistics=replace(model.statistics,entries=tuple(replace(s,total_rows=100000 if s.backend_id=='neo4j' else 1000,
            mean_row_bytes=10 if s.backend_id=='neo4j' else 10000) for s in model.statistics.entries)))
    t=replace(target(probabilities=(.045,.855,.1)),backend='neo4j',
        source_id=base.metadata['source_identities']['neo4j']['source_id'],version=base.metadata['source_identities']['neo4j']['snapshot_version'],bindings=((family.candidates[0].candidate_id,'left-op'),),
        prior_rows=50005,row_estimates=(10,100000,50005),action_cost=.1)
    settings=UnifiedSettings(information_targets=(t,),physical_moves=False,candidate_weights=(1,)*8,
        limits=Limits(depth=1,aggregation='expectation',optional_ms=10000))
    class Client:
        def __init__(self,backend,rows):self.backend_id=backend;self.rows=rows;self.calls=0;self.transferred=0
        def execute(self,artifact):
            self.calls+=1
            rows=([{'value':len(self.rows)}] if artifact.artifact_id=='count' else
                  [r for r in self.rows if 'keys' not in artifact.parameters or r['entity'] in artifact.parameters['keys']])
            self.transferred+=len(json.dumps(rows).encode())
            return ExecutionReport(self.backend_id,artifact.artifact_id,artifact.language,True,rows=rows)
    def run(mode):
        clients={'neo4j':Client('neo4j',[dict(entity=i) for i in range(10)]),
                 'fuseki':Client('fuseki',[dict(entity=i,payload='x'*10000) for i in range(1000)])}
        registry=BackendPluginRegistry()
        for k,c in clients.items():registry.register(NativeBackendPlugin(k,c))
        domain=FamilyDomain('fixed intersection',UnifiedTerminalContract(family,(),epsilon='1'),
            {0:(left,1,Resources())},JointCostProfile(),authority_name='fixture',authority_version='v',
            settings=replace(settings,information_mode=mode),estimator=model)
        l=domain.seed_keys[0];r=domain.store(0,right);initial=FamilyState(pools=((0,(l,r)),))
        def perform(action):
            assert action.kind=='probe'
            label,evidence=t.invoke(clients,{t.source_id:SimpleNamespace(snapshot_version=t.version,replica_backend_ids=('neo4j',))})
            child=next(o.payload for o in action.outcomes if o.label==label)
            return Observation(label,child,Resources(remote_calls=1),evidence)
        def execute(terminal):
            result=FederatedScheduler(BackendInvokeTool(registry),retention='roots').execute(terminal.payload['plan'])
            return dict(success=result.success,answer_rows=list(result.root_rows.get('ids',())))
        report=run_online(initial,domain,perform=perform,execute=execute,limits=settings.limits)
        assert report['success'] and report['final_plan_executions']==1
        return report,sum(c.transferred for c in clients.values()),sum(c.calls for c in clients.values()),domain,initial
    np,np_bytes,np_calls,_,_=run('no_probe')
    xgap,xgap_bytes,xgap_calls,domain,state=run('all')
    assert np['answer_rows']==xgap['answer_rows']==[{'entity':i} for i in range(10)]
    assert np_calls==2 and xgap_calls==3
    assert xgap_bytes<np_bytes/90
    assert len(xgap['trace'])==1 and xgap['trace'][0]['kind']=='probe'
    # Expensive information and a singleton physical pool must not trigger probes.
    costly=replace(t,action_cost=100000)
    for info,pools in [(costly,state.pools),(t,())]:
        d=FamilyDomain('fixed',domain.contract,{0:(left,1,Resources())},JointCostProfile(),authority_name='f',authority_version='v',
            settings=replace(settings,information_targets=(info,)),estimator=model)
        if pools:
            key=d.store(0,right);s=FamilyState(pools=((0,(d.seed_keys[0],key)),))
        else:s=FamilyState()
        assert isinstance(choose(State(s),d,limits=settings.limits)['choice'],Terminal)


def test_subplan_memo_is_bounded_isolated_and_retains_small_cost_contributions():
    from xgap.planning.estimate_session import EstimateSession
    _,model,late,early,_=plans()
    session=EstimateSession(model,max_entries=2,max_bytes=50000)
    for p in (late,early,late):
        assert session.predict(p).relative_cost==pytest.approx(model.predict(p).relative_cost)
        assert session.diagnostics()['entries']<=2
    tiny=EstimateSession(model,max_bytes=1)
    tiny.predict(late);assert tiny.diagnostics()['entries']==0
    a=model.for_request();b=model.for_request()
    a.predict(late);assert b.diagnostics()['entries']==0
    # A huge unrelated prefix must not zero out a reusable small contribution.
    big=replace(late.nodes[0],node_id='aaa-huge')
    q=replace(late,nodes=(big,*late.nodes),roots=late.roots)
    inflated=replace(model,statistics=replace(model.statistics,entries=tuple(
        replace(s,total_rows=10**25) if s.backend_id=='neo4j' else s for s in model.statistics.entries)),
        populations=(('neo4j',10**25,0),('fuseki',1000,0)))
    memo=inflated.for_request();memo.predict(q)
    only_right=replace(late,nodes=(late.nodes[1],),roots=('right',))
    assert memo.predict(only_right).relative_cost==inflated.predict(only_right).relative_cost


def test_duplicate_heavy_join_does_not_enumerate_redundant_pairs(monkeypatch):
    import xgap.runtime.scheduler as scheduler
    examined=[0];original=scheduler.value_key
    def counted(v):examined[0]+=1;return original(v)
    monkeypatch.setattr(scheduler,'value_key',counted)
    node=RuntimeNode('j',R.COORDINATOR_JOIN,('a','b'),dict(left_on='k',right_on='k'))
    rows=({'k':1,'payload':'same'},)*1000
    result=FederatedScheduler._join(node,rows,rows)
    assert result==({'k':1,'payload':'same'},)
    assert examined[0]<100 # rather than millions of pair comparisons


def test_probed_pushed_filter_is_applied_once_and_cache_tracks_its_scope():
    _,model,late,_,_=plans()
    from copy import deepcopy
    condition=dict(op='eq',field='flag',value='rare')
    p=deepcopy(late.nodes[0].parameters)
    p['artifact']['parameters']['necessary_row_filters']={'conditions':[condition]}
    node=replace(late.nodes[0],parameters=p)
    plan=replace(late,nodes=(node,),roots=('left',))
    session=model.for_request()
    filtered=session.predict_conditioned(plan,{'left':10},observed_filters={'left':[condition]})
    unfiltered=session.predict_conditioned(plan,{'left':10})
    assert filtered.provenance['nodes'][0]['estimated_rows']==10
    assert unfiltered.provenance['nodes'][0]['estimated_rows']==pytest.approx(.1)
    assert filtered.relative_cost>unfiltered.relative_cost
    with pytest.raises(ValueError,match='predicate scope'):
        session.predict_conditioned(plan,{'left':10},observed_filters={'left':[dict(op='eq',field='k',value=3)]})
    # A filtered probe cannot price an unfiltered source read after a rewrite,
    # nor silently fall back to the old backend-wide additive row penalty.
    import json
    from types import SimpleNamespace
    from xgap.planning.conditioned_work import conditioned_cost
    target=SimpleNamespace(kind='probe',bindings=(('candidate','op'),),name='filtered',
        artifact_json=json.dumps({'parameters':{'necessary_row_filters':{'conditions':[condition]}}}),
        applies=lambda candidate,node:node.node_id=='left')
    assert conditioned_cost(model,late,'candidate',[target],{})==(None,{'filtered'})
