"""Necessary screening boundaries, using actual tiny SPARQL and independent gold."""
from dataclasses import replace
import json

import pytest

from test_anchor_reduction import tiny, PREFIX, NS
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.practical_execution import run_practical_semantic_query
from xgap.agent.practical_planning import BindingEvidence, BindingState, PracticalMode, program_identity
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.compilers.necessary_row_filters import add_necessary_row_filters
from xgap.experiments.tiny_work_training import op
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.runtime.semantic_compiler import compile_semantic_program
from xgap.runtime.semantic_planning import LogicalSource
from xgap.runtime.shared_native_reads import share_full_native_reads
from xgap.runtime.source_row_filters import prefilter_source_rows
from xgap.semantic.program import SemanticGraphProgram


def match(name):
    return op(name,'match',parameters={'node':{'label':'Person'},'entity_field':'person','properties':{'age':'age'}})


def setup(condition=None, middle=(), roots=('answer',), extra=()):
    _,_,backends,graphs,clients,scheduler,calls=tiny()
    child=middle[-1]['operator_id'] if middle else 'source'
    program=SemanticGraphProgram.from_dict({'program_id':'necessary-row-filter-tiny',
        'operators':[match('source'),*middle,op('answer','filter',(child,),parameters={
            'condition':condition or {'op':'eq','field':'age','value':'keep'}}),*extra], 'roots':list(roots)})
    placements={o.operator_id:'rdf_a' for o in program.operators if o.kind.value=='match'}
    plan=compile_semantic_program(program,source_bindings=placements,backends=backends,max_parallelism=1)
    plan=replace(plan,metadata={**plan.metadata,'source_identities':{'rdf_a':{'source_id':'graph','snapshot_version':'tiny-v1'}},
        'source_snapshot_versions':{'rdf_a':'tiny-v1'}})
    return program,plan,backends,graphs,clients,scheduler,calls


def native(plan):
    return QueryArtifact.from_dict(next(n for n in plan.nodes if n.node_id=='source/native').parameters['artifact'])


def test_string_screen_keeps_unknown_types_and_final_filter_handles_multivalue():
    p,plan,_,graphs,_,scheduler,calls=setup()
    graph=graphs['rdf_a'];graph.remove((None,None,None))
    graph.parse(data=PREFIX+'''t:a a t:Person; t:age "keep", "drop".
        t:b a t:Person; t:age "drop". t:c a t:Person; t:age 1.
        t:d a t:Person. t:e a t:Person; t:age "keep"@en.
        t:f a t:Person; t:age t:keep. t:g a t:Person; t:age true.
        t:h a t:Person; t:age "2020-01-01"^^<http://www.w3.org/2001/XMLSchema#date>.''',format='turtle')
    screened=prefilter_source_rows(p,plan)
    # Two known nonmatching strings disappear; every unknown native type remains.
    raw=json.loads(graph.query(native(screened).text).serialize(format='json'))['results']['bindings']
    assert len(raw)==7 and {r['entity']['value'] for r in raw}=={NS+n for n in 'acdefgh'}
    before=p.to_dict();result=scheduler.execute(screened)
    assert result.success and result.final_rows==({'person':NS+'a','age':'keep'},),result
    assert len(calls)==1 and p.to_dict()==before
    assert next(n for n in plan.nodes if n.node_id=='answer/filter')==next(n for n in screened.nodes if n.node_id=='answer/filter')


def test_boolean_screen_never_conflates_numeric_one_with_true():
    p,plan,_,graphs,_,scheduler,_=setup({'op':'eq','field':'age','value':True})
    graph=graphs['rdf_a'];graph.remove((None,None,None))
    graph.parse(data=PREFIX+'''t:a a t:Person; t:age true. t:b a t:Person; t:age false.
        t:c a t:Person; t:age 1. t:d a t:Person; t:age "true". t:e a t:Person.
        t:f a t:Person; t:age "1"^^<http://www.w3.org/2001/XMLSchema#boolean>.''',format='turtle')
    screened=prefilter_source_rows(p,plan)
    assert len(list(graph.query(native(screened).text)))==5
    result=scheduler.execute(screened)
    assert result.success and set(r['person'] for r in result.final_rows)=={NS+'a',NS+'f'}
    assert all(r['age'] is True for r in result.final_rows)


@pytest.mark.parametrize('boundary',('root','side_consumer','limit','rename','or','timestamp','field_comparison','aggregate'))
def test_no_early_filter_across_unproved_semantic_boundary(boundary):
    kwargs={}
    if boundary=='root':kwargs['roots']=('source','answer')
    elif boundary=='side_consumer':
        kwargs['extra']=[op('side','project',('source',),parameters={'projections':{'person':{'kind':'field','field':'person'}}})]
        kwargs['roots']=('side','answer')
    elif boundary=='limit':kwargs['middle']=[op('limit','order_limit',('source',),parameters={'order_by':[{'field':'person','direction':'asc'}],'limit':1})]
    elif boundary=='rename':
        kwargs['middle']=[op('rename','project',('source',),parameters={'projections':{'age':{'kind':'field','field':'person'}}})]
    elif boundary=='or':kwargs['condition']={'op':'or','args':[{'op':'eq','field':'age','value':'keep'},{'op':'eq','field':'age','value':'drop'}]}
    elif boundary=='timestamp':kwargs['condition']={'op':'eq','field':'age','value':'2020-01-01','value_type':'timestamp_ms'}
    elif boundary=='field_comparison':kwargs['condition']={'op':'eq','field':'age','right_field':'person'}
    elif boundary=='aggregate':
        # Aggregate with a retained group key is intentionally outside this proof.
        kwargs['middle']=[op('groups','aggregate',('source',),output='grouped_bindings',parameters={
            'group_by':['age'],'aggregations':{'n':{'op':'count','field':'person','distinct':False}}}),
            op('project','project',('groups',),input_kind='grouped_bindings',parameters={'projections':{'age':{'kind':'field','field':'age'}}})]
    p,plan,*_=setup(**kwargs)
    assert prefilter_source_rows(p,plan) is plan


def test_union_join_identity_projection_are_safe_but_shadowed_right_field_is_not():
    middle=[match('second'),op('union','union',('source','second')),
        op('project','project',('union',),parameters={'projections':{f:{'kind':'field','field':f} for f in ('person','age')}}),
        match('right'),op('join','join',('project','right'),parameters={'left_on':'person','right_on':'person'})]
    p,plan,_,graphs,_,scheduler,calls=setup(middle=middle)
    graph=graphs['rdf_a'];graph.remove((None,None,None))
    graph.parse(data=PREFIX+'t:a a t:Person; t:age "keep", "drop". t:b a t:Person; t:age "drop".',format='turtle')
    screened=prefilter_source_rows(p,plan)
    assert set(screened.metadata['source_row_prefilters']['native_nodes'])=={'source','second'}
    shared=share_full_native_reads(screened)
    assert shared.metadata['shared_native_reads']['saved_remote_calls']==1
    result=scheduler.execute(shared)
    # The right field is renamed and must retain both values; filtering it loses a gold row.
    assert result.success and len(calls)==2
    assert {r['right_age'] for r in result.final_rows}=={'keep','drop'} and len(result.final_rows)==2


@pytest.mark.parametrize('mode',('exact','performance'))
def test_both_strong_modes_keep_feasible_slice_and_one_execution(mode):
    p,_,backends,graphs,clients,_,calls=setup()
    graphs['rdf_a'].remove((None,None,None))
    graphs['rdf_a'].parse(data=PREFIX+'t:a a t:Person; t:age "keep". t:b a t:Person; t:age "drop".',format='turtle')
    state=BindingState(evidence=(BindingEvidence('$structure',program_identity(p),'trusted_request','independent-tiny','v1'),))
    result=run_practical_semantic_query(p,initial_state=state,mode=PracticalMode(mode,improve_physical=False),
        operator_sources={'source':'graph'},binding_values={},sources={'graph':LogicalSource('graph','tiny-v1',('rdf_a',))},
        backends=backends,backend_clients=clients,physical_profile=replace(OneShotPolicy(),max_parallelism=1),
        limits=StrongSearchLimits(improvement_actions=0))
    assert result['success'] and result['answer_rows']==[{'person':NS+'a','age':'keep'}],result
    assert len(calls)==result['backend_remote_calls']==result['final_plan_executions']==1
    assert result['model_calls']==0 and result['search']['external_calls_during_search']==0
    assert 'necessary-primitive-row-equality-v1' in json.dumps(result)


def test_budgeted_or_unknown_artifact_declines_and_binding_marker_is_preserved():
    p,plan,backends,graphs,clients,_,calls=setup();artifact=native(plan);condition={'op':'eq','field':'age','value':'keep'}
    for params in ({**artifact.parameters,'retrieval_budget':{'rows':1}},{**artifact.parameters,'compiler':'unknown'}):
        with pytest.raises(ValueError):add_necessary_row_filters(replace(artifact,parameters=params),[condition])
    # Exercise the real native bind serializer after wrapping, including an excluded matching entity.
    from xgap.runtime.physical_strategies import _bound_match_artifact
    bound,parameter=_bound_match_artifact(artifact,backends['rdf_a'],max_bindings=3,max_binding_bytes=4096)
    screened=add_necessary_row_filters(bound,[condition])
    graphs['rdf_a'].remove((None,None,None))
    graphs['rdf_a'].parse(data=PREFIX+'t:a a t:Person; t:age "keep". t:b a t:Person; t:age "drop". t:c a t:Person; t:age "keep".',format='turtle')
    result=clients['rdf_a'].execute(replace(screened,parameters={**screened.parameters,parameter:[NS+'a',NS+'b']}))
    assert result.success and len(result.rows)==1 and result.rows[0]['entity']['value']==NS+'a'
    assert len(calls)==1
