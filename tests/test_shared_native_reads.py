"""Same-plan source sharing: independent edge-pair gold and admission boundaries."""
from dataclasses import replace

import pytest

from test_anchor_reduction import tiny
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.practical_execution import run_practical_semantic_query
from xgap.agent.practical_planning import BindingEvidence, BindingState, PracticalMode, program_identity
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.experiments.tiny_work_training import op
from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNode, RuntimeNodeKind as R
from xgap.runtime.one_shot_planning import prepare_one_shot_domain
from xgap.runtime.semantic_compiler import compile_semantic_program
from xgap.runtime.semantic_planning import LogicalSource
from xgap.runtime.shared_native_reads import share_full_native_reads
from xgap.semantic.program import SemanticGraphProgram


def case():
    _,_,backends,_,clients,scheduler,calls=tiny()
    matches=[op(n,'match',parameters={'edge':{'label':'KNOWS'},'entity_field':'edge',
        'source_field':'source','target_field':'target','properties':{}}) for n in ('left','right')]
    join=op('join','join',('left','right'),parameters={'left_on':'target','right_on':'source','right_prefix':'next_'})
    count=op('count','aggregate',('join',),output='grouped_bindings',parameters={'group_by':[],
        'aggregations':{'n':{'op':'count','field':'next_edge','distinct':False}}})
    program=SemanticGraphProgram.from_dict({'program_id':'shared-edge-pairs','operators':[*matches,join,count],'roots':['count']})
    placements={n:'rdf_a' for n in ('left','right')}
    source=LogicalSource('graph','independent-five-node-v1',('rdf_a',))
    plan=compile_semantic_program(program,source_bindings=placements,backends=backends,max_parallelism=1)
    plan=replace(plan,metadata={**plan.metadata,'source_identities':{'rdf_a':{'source_id':source.source_id,'snapshot_version':source.snapshot_version}},
        'source_snapshot_versions':{'rdf_a':source.snapshot_version}})
    return program,plan,backends,clients,scheduler,calls,{'graph':source}


def test_shared_read_keeps_parallel_edge_pairs_and_all_consumer_schemas():
    program,plan,_,_,scheduler,calls,_=case();before=plan.to_dict()
    shared=share_full_native_reads(plan)
    assert not calls and plan.to_dict()==before
    assert shared.metadata['shared_native_reads']['saved_remote_calls']==1
    assert shared.metadata['schemas']==plan.metadata['schemas'] and shared.roots==plan.roots
    assert share_full_native_reads(shared).to_dict()==shared.to_dict()
    result=scheduler.execute(shared)
    # Independently counted edge pairs: 2+1+1+1+1+4+4 =14, including parallel a->b and a->a.
    assert result.success and result.final_rows==({'n':14},) and len(calls)==1
    nodes={n.node_id:n for n in shared.nodes}
    assert nodes['left/native'].semantic_operator_ids==('left','right')
    assert nodes['right/bindings'].inputs==('left/native',)


@pytest.mark.parametrize('mode',('exact','performance'))
def test_strong_feasible_fallback_uses_one_source_call_without_optional_search(mode):
    program,_,backends,clients,_,calls,sources=case()
    state=BindingState(evidence=(BindingEvidence('$structure',program_identity(program),'trusted_request','independent-tiny','v1'),))
    result=run_practical_semantic_query(program,initial_state=state,mode=PracticalMode(mode,improve_physical=False),
        operator_sources={'left':'graph','right':'graph'},binding_values={},sources=sources,backends=backends,
        backend_clients=clients,physical_profile=replace(OneShotPolicy(),max_parallelism=1),
        limits=StrongSearchLimits(improvement_actions=0))
    assert result['success'] and result['answer_rows']==[{'n':14}],result
    assert result['final_plan_executions']==1 and result['backend_remote_calls']==len(calls)==1
    assert result['model_calls']==0 and result['search']['external_calls_during_search']==0


def test_optional_domain_shares_before_estimation_but_legacy_candidates_stay_identical():
    program,_,backends,_,_,calls,sources=case()
    args=dict(operator_sources={'left':'graph','right':'graph'},sources=sources,backends=backends,
        policy=replace(OneShotPolicy(),max_parallelism=1),progressive_bindings=True)
    old,old_meta=prepare_one_shot_domain(program,**args)
    same,_=prepare_one_shot_domain(program,**args,shared_native_reads=False)
    new,new_meta=prepare_one_shot_domain(program,**args,shared_native_reads=True)
    assert [c.to_dict() for c in old]==[c.to_dict() for c in same]
    assert len(new)==len(old) and old_meta['construction_bound']==new_meta['construction_bound']
    assert old[0].features['remote_query_count']==2 and new[0].features['remote_query_count']==1
    assert old[0].semantic_equivalence_key==new[0].semantic_equivalence_key and not calls


@pytest.mark.parametrize('boundary',('snapshot','descriptor','value','budget','backend'))
def test_no_sharing_across_unverified_snapshot_or_distinct_execution_contract(boundary):
    _,plan,_,_,_,_,_=case();raw=plan.to_dict()
    a=next(n for n in raw['nodes'] if n['node_id']=='right/native')['parameters']
    if boundary=='snapshot':raw['metadata']['source_snapshot_versions']['rdf_a']='different'
    elif boundary=='descriptor':a['artifact']['parameters']['compiler']='caller-authored-query'
    elif boundary=='value':a['artifact']['parameters']['query_parameters']={'minimum':999}
    elif boundary=='budget':a['artifact']['parameters']['retrieval_budget']={'rows':1}
    else:
        a['backend_id']='rdf_b';a['artifact']['parameters']['target_backend_id']='rdf_b'
        raw['metadata']['source_identities']['rdf_b']={'source_id':'different-source','snapshot_version':'v1'}
        raw['metadata']['source_snapshot_versions']['rdf_b']='v1'
    altered=FederatedExecutionPlan.from_dict(raw)
    assert share_full_native_reads(altered).to_dict()==altered.to_dict()


def test_named_roots_and_duplicate_direct_input_ports_remain_independent():
    _,plan,_,_,_,_,_=case()
    remote=tuple(n for n in plan.nodes if n.kind is R.REMOTE_QUERY)
    named=replace(plan,nodes=remote,roots=tuple(n.node_id for n in remote))
    assert share_full_native_reads(named).to_dict()==named.to_dict()
    merge=RuntimeNode('union',R.MERGE,tuple(n.node_id for n in remote))
    direct=replace(plan,nodes=(*remote,merge),roots=('union',))
    assert share_full_native_reads(direct).to_dict()==direct.to_dict()


def test_failed_shared_source_is_not_retried_for_another_consumer():
    _,plan,_,clients,scheduler,calls,_=case();attempts=[]
    def fail(artifact):attempts.append(artifact.artifact_id);raise OSError('shared source failed')
    clients['rdf_a'].execute=fail
    result=scheduler.execute(share_full_native_reads(plan))
    assert not result.success and len(attempts)==1 and not calls
    assert all(n.status.value=='skipped' for n in result.node_results if n.node_id in ('left/bindings','right/bindings','count/aggregate'))
