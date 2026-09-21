"""Finite tools and local rewrites: real portable execution, no trial selection."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from test_unified_family import invocation
from xgap.agent.intent_certificate import canonical
from xgap.agent.unified_family import UnifiedSettings,FamilyDomain,FamilyState
from xgap.agent.unified_information import InformationTarget
from xgap.agent.unified_lookahead import Limits,Resources,State,choose
from xgap.agent.unified_contract import UnifiedTerminalContract
from xgap.agent.intent_execution import family_runtime,snapshot_identity
from xgap.experiments.bounded_joint_toy import local_runtime,toy_scope
from xgap.infrastructure.runtime import QueryArtifact
from xgap.planning.joint_cost import JointCostProfile
from xgap.runtime.unified_physical import PhysicalMoves,identity
from xgap.semantic.intent_scope import construct_scope


def fixture():
    data,options,calls=local_runtime()
    family=replace(construct_scope([data['query_template']],toy_scope(),snapshot_identity(
        options['sources'],options['backends'],options['source_schema'])),coverage_basis='authored-test')
    prepare,execute,*_=family_runtime(family,**options,seed_only=True,stepwise=True)
    return data,options,calls,family,prepare,execute


def target(**options):
    return InformationTarget(name='graph-size',backend='graph',source_id='graph',version='tiny-v1',kind='probe',
        artifact_json=canonical(QueryArtifact('count','sparql','SELECT (COUNT(*) AS ?value) WHERE {?s ?p ?o}').to_dict()),**options)


def test_each_single_rewrite_matches_independent_answer_and_is_one_change():
    data,options,calls,family,prepare,execute=fixture()
    i=next(i for i,c in enumerate(family.candidates) if json.loads(c.query_json)==data['query_template'])
    seed=prepare(family.candidates[i],None)
    moves=PhysicalMoves(family,options['source_schema'],options['backends'],options['physical_profile'])
    proposals=list(moves.neighbors(i,seed))
    assert not calls and {p.metadata['unified_rewrite']['rule'] for p in proposals}=={'share_read','prefilter','entity_bind'}
    assert len({identity(p) for p in proposals})==len(proposals)
    # Development equivalence oracle executes each rewrite separately. The online
    # controller never uses this oracle or these measurements for selection.
    for plan in proposals:
        result=execute(plan)
        assert result['success'],result
        assert result['answer_rows']==data['expected'],plan.metadata['unified_rewrite']
        assert plan.metadata['unified_rewrite']['rewrite_count']==1


def test_pool_preserves_seed_and_actual_transform_executes_once(tmp_path):
    report,_=invocation(tmp_path,UnifiedSettings(limits=Limits(optional_ms=3000),plan_pool=2))
    assert report['success'] and report['physical_actions']>0
    core=report['joint_policy']
    assert core['final_plan_executions']==1 and core['external_calls_during_search']==0
    assert all(len(v)<=2 for v in core['retained_plans'].values())
    assert core['plan_registry_bytes']<=32*1024*1024


def test_declared_target_executes_only_on_invocation_and_versions_are_checked():
    data,options,calls,*_=fixture()
    item=target()
    assert not calls
    label,receipt=item.invoke(options['backend_clients'],options['sources'])
    assert label in item.labels and calls==['graph'] and receipt['semantic_authority'] is False
    assert item.category([{'value':'unparseable'}])=='unknown'
    with pytest.raises(ValueError,match='version'):
        replace(item,version='different').invoke(options['backend_clients'],options['sources'])
    assert calls==['graph']


def test_information_never_filters_queries_and_invalidates_only_dependent_estimates():
    _,options,calls,family,prepare,_=fixture()
    seeds={i:(prepare(c,None),1,Resources(remote_calls=32,bytes=None,peak_bytes=None)) for i,c in enumerate(family.candidates)}
    settings=UnifiedSettings(information_targets=(target(),))
    domain=FamilyDomain('q',UnifiedTerminalContract(family,(),epsilon='1'),seeds,JointCostProfile(),
        authority_name='user',authority_version=family.identity,settings=settings)
    state=FamilyState();key=domain.pool(state,0)[0]
    before=domain.score(state,key);count=domain.estimate_evaluations
    assert domain.score(state,key)==before and domain.estimate_evaluations==count
    action=next(domain.information_actions(state))
    child=action.outcomes[0].payload
    assert domain.contract.consistent(child.bindings)==domain.contract.consistent(state.bindings)
    assert domain.score(child,key)<before and domain.estimate_evaluations==count+1 and not calls
    assert action.outcomes[-1].payload==state


def test_metadata_unknown_preserves_seed_and_blocks_only_dependent_alternative():
    _,options,calls,family,prepare,_=fixture()
    i=0;seed=prepare(family.candidates[i],None)
    item=replace(target(),name='bind-capability',kind='metadata',gates_rule='entity_bind',gate_label='large')
    settings=UnifiedSettings(information_targets=(item,))
    domain=FamilyDomain('q',UnifiedTerminalContract(family,(),epsilon='1'),{i:(seed,1,Resources())},JointCostProfile(),
        authority_name='user',authority_version=family.identity,settings=settings,
        moves=PhysicalMoves(family,options['source_schema'],options['backends'],options['physical_profile']))
    action=next(a for a in domain.physical_actions(FamilyState()) if a.arguments['rule']=='entity_bind')
    child=action.outcomes[0].payload
    assert len(domain.terminals(child))==1 # seed, never the unverified optional plan
    informed=replace(child,facts=((item.name,'large'),))
    assert len(domain.terminals(informed))==2 and domain.completion(child) is not None and not calls


def test_expectation_needs_explicit_model_and_small_registry_falls_back(tmp_path):
    with pytest.raises(ValueError,match='positive support'):UnifiedSettings(candidate_weights=(0,1))
    report,_=invocation(tmp_path,UnifiedSettings(limits=Limits(aggregation='expectation')))
    assert not report['success'] and 'prior' in report['error']
    (tmp_path/'bounded').mkdir()
    report,_=invocation(tmp_path/'bounded',UnifiedSettings(max_plans=8))
    assert report['success'] and report['joint_policy']['plan_registry_count']==8
    assert report['joint_policy']['optional_plan_rejections']>0


def test_selected_probe_is_paid_once_with_real_response_and_one_final_plan(tmp_path):
    settings=UnifiedSettings(limits=Limits(depth=1,optional_ms=3000,aggregation='expectation'),
        candidate_weights=(1,)*8,information_targets=(target(probabilities=(.6,.3,.1)),))
    report,calls=invocation(tmp_path,settings)
    assert report['success'],report
    core=report['joint_policy']
    assert report['probe_calls']==1 and report['final_plan_executions']==1
    assert len(calls)==report['backend_remote_calls']+1
    assert len([r for r in core['information_ledger'] if r.get('target')=='graph-size'])==1
    assert core['selected_facts']['graph-size'] in ('small','large')
    assert core['external_calls_during_search']==0


def test_disclosure_budget_is_enforced_in_new_loop(tmp_path):
    from xgap.agent.intent_strong import FamilyInformationPolicy
    report,calls=invocation(tmp_path,information=FamilyInformationPolicy(max_disclosed_coordinates=0))
    assert not report['success'] and report['final_plan_executions']==0 and not calls


def test_one_source_replacement_has_equivalent_answer():
    from xgap.infrastructure.descriptors import BackendDescriptor
    from xgap.backends.fuseki_client import FusekiClient
    data,options,calls=local_runtime()
    # Same frozen relation, separate declared backend descriptor and report identity.
    client=options['backend_clients']['graph']
    class Replica(FusekiClient):
        def execute(self,artifact):return replace(client.execute(artifact),backend_id='replica')
    options['backend_clients']['replica']=Replica(BackendDescriptor('replica','fuseki','sparql','rdf'))
    options['backends']['replica']=replace(options['backends']['graph'],backend_id='replica',
        profile=replace(options['backends']['graph'].profile,backend_id='replica'))
    # Include backend-specific mapping entries needed by the unchanged compiler.
    from copy import deepcopy
    b=options['backends']['replica'];mapping=deepcopy(b.backend_mapping)
    for name in ('backends','term_mappings'):mapping[name]['replica']=mapping[name]['graph']
    options['backends']['replica']=replace(b,backend_mapping=mapping)
    options['sources']['graph']=replace(options['sources']['graph'],replica_backend_ids=('graph','replica'))
    family=replace(construct_scope([data['query_template']],toy_scope(),snapshot_identity(
        options['sources'],options['backends'],options['source_schema'])),coverage_basis='authored-test')
    prepare,execute,*_=family_runtime(family,**options,seed_only=True,stepwise=True)
    i=next(i for i,c in enumerate(family.candidates) if json.loads(c.query_json)==data['query_template'])
    moves=PhysicalMoves(family,options['source_schema'],options['backends'],options['physical_profile'],options['sources'])
    plan=next(p for p in moves.neighbors(i,prepare(family.candidates[i],None)) if p.metadata['unified_rewrite']['rule']=='source_placement')
    assert not calls and plan.metadata['unified_rewrite']['rewrite_count']==1
    result=execute(plan)
    assert result['success'] and result['answer_rows']==data['expected']
