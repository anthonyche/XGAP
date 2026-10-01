"""Alias sharing must preserve real RDF joins, nulls, and distinct edge identity."""
from dataclasses import replace

import pytest
from rdflib import Literal, URIRef

from test_anchor_reduction import tiny
from test_physical_strategies import NS
from xgap.experiments.tiny_work_training import op
from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNodeKind as R
from xgap.runtime.semantic_compiler import compile_semantic_program
from xgap.runtime.shared_native_reads import share_full_native_reads
from xgap.runtime.shared_match_projections import PROFILE
from xgap.runtime.source_row_filters import pending_source_row_prefilters, prefilter_source_rows
from xgap.semantic.program import SemanticGraphProgram


def fixture():
    _,_,backends,graphs,_,scheduler,calls=tiny()
    for i in range(7):
        graphs['rdf_a'].add((URIRef(NS+f'e{i}'),URIRef(NS+'age'),Literal(i)))
    matches=[op(name,'match',parameters={'edge':{'label':'KNOWS'},
        'entity_field':f'{name}_edge','source_field':f'{name}_source','target_field':f'{name}_target',
        'properties':{f'{name}_age':'age'}}) for name in ('left','right')]
    join=op('join','join',('left','right'),parameters={'left_on':'left_target','right_on':'right_source'})
    program=SemanticGraphProgram.from_dict({'program_id':'projection-pairs','operators':[*matches,join],'roots':['join']})
    plan=compile_semantic_program(program,source_bindings={'left':'rdf_a','right':'rdf_a'},
                                  backends=backends,max_parallelism=1)
    plan=replace(plan,metadata={**plan.metadata,'source_identities':{'rdf_a':{'source_id':'graph','snapshot_version':'v1'}},
        'source_snapshot_versions':{'rdf_a':'v1'}})
    return program,plan,backends,scheduler,calls


def test_alias_sharing_preserves_independently_enumerated_edge_pairs_and_nulls():
    program,plan,backends,scheduler,calls=fixture()
    shared=share_full_native_reads(plan,program=program,backends=backends)
    assert not calls and shared.metadata[PROFILE]['saved_remote_calls']==1
    assert shared.metadata['schemas']==plan.metadata['schemas']
    before=scheduler.execute(plan);after=scheduler.execute(shared)
    links=[('a','b'),('a','c'),('b','c'),('c','d'),('d','e'),('e','a'),('a','b'),('a','a')]
    expected={(NS+f'e{i}',NS+f'e{j}',i if i<7 else None,j if j<7 else None)
              for i,(_,end) in enumerate(links) for j,(start,_) in enumerate(links) if end==start}
    columns=('left_edge','right_edge','left_age','right_age')
    assert before.success and after.success
    assert {tuple(r[c] for c in columns) for r in before.final_rows}==expected
    assert {tuple(r[c] for c in columns) for r in after.final_rows}==expected
    assert after.total_remote_calls==1 and len(calls)==3
    assert share_full_native_reads(shared,program=program,backends=backends).to_dict()==shared.to_dict()
    assert all('xgap_shared_scalar' not in text for _,text in calls)


@pytest.mark.parametrize('boundary',('native_filter','retrieval_limit','decoder','snapshot','extra_parameters'))
def test_modified_source_or_decoder_contract_is_not_canonicalized(boundary):
    program,plan,backends,_,_=fixture();raw=plan.to_dict()
    right=next(n for n in raw['nodes'] if n['node_id']=='right/native')
    if boundary=='native_filter':right['parameters']['artifact']['text']+=' LIMIT 1'
    elif boundary=='retrieval_limit':right['parameters']['artifact']['parameters']['retrieval_budget']={'rows':1}
    elif boundary=='decoder':next(n for n in raw['nodes'] if n['node_id']=='right/bindings')['parameters']['resource_namespace']='urn:other:'
    elif boundary=='snapshot':raw['metadata']['source_snapshot_versions']['rdf_a']='v2'
    else:
        right['parameters']['artifact']['parameters']['query_parameters']={'property':'different'}
    altered=FederatedExecutionPlan.from_dict(raw)
    assert share_full_native_reads(altered,program=program,backends=backends).to_dict()==altered.to_dict()


def test_real_source_predicate_difference_stays_independent():
    program,plan,backends,scheduler,_=fixture();raw=program.to_dict()
    raw['operators'][1]['parameters']['edge']['properties']={'age':3}
    different=SemanticGraphProgram.from_dict(raw)
    compiled=compile_semantic_program(different,source_bindings={'left':'rdf_a','right':'rdf_a'},
                                     backends=backends,max_parallelism=1)
    compiled=replace(compiled,metadata={**compiled.metadata,
        'source_identities':plan.metadata['source_identities'],
        'source_snapshot_versions':plan.metadata['source_snapshot_versions']})
    shared=share_full_native_reads(compiled,program=different,backends=backends)
    assert shared.to_dict()==compiled.to_dict()
    result=scheduler.execute(shared)
    assert result.success and len(result.final_rows)==2
    assert {r['right_edge'] for r in result.final_rows}=={NS+'e3'}


def test_sparql_alias_that_collides_with_internal_variable_is_declined():
    _,plan,backends,_,_=fixture()
    operators=[op(name,'match',parameters={'node':{'label':'Person'},'entity_field':'person',
        'properties':{alias:'age'}}) for name,alias in [('left','n0'),('right','value')]]
    program=SemanticGraphProgram.from_dict({'program_id':'collision','operators':operators,'roots':['left','right']})
    compiled=compile_semantic_program(program,source_bindings={'left':'rdf_a','right':'rdf_a'},backends=backends)
    compiled=replace(compiled,metadata={**compiled.metadata,
        'source_identities':plan.metadata['source_identities'],
        'source_snapshot_versions':plan.metadata['source_snapshot_versions']})
    assert share_full_native_reads(compiled,program=program,backends=backends).to_dict()==compiled.to_dict()


def test_shared_failure_does_not_retry_or_deliver_partial_join():
    program,plan,backends,scheduler,_=fixture()
    shared=share_full_native_reads(plan,program=program,backends=backends)
    remote=next(n for n in shared.nodes if n.kind is R.REMOTE_QUERY)
    bad=replace(remote,parameters={**remote.parameters,'artifact':{**remote.parameters['artifact'],'text':'INVALID SPARQL'}})
    shared=replace(shared,nodes=tuple(bad if n.node_id==remote.node_id else n for n in shared.nodes))
    result=scheduler.execute(shared)
    assert not result.success and result.total_remote_calls==1
    assert not result.final_rows


def test_alias_sharing_retains_anchor_screening_without_filtering_witness_rows():
    """An anchor and a distinct witness may project the same source property."""
    from test_anchor_reduction import PREFIX
    _,_,backends,graphs,_,scheduler,calls=tiny()
    graphs['rdf_a'].remove((None,None,None))
    graphs['rdf_a'].parse(data=PREFIX+'''t:a a t:Person; t:age "anchor".
        t:c a t:Person; t:age "witness".
        t:e a t:Edge; t:label "KNOWS"; t:source t:a; t:target t:c.''',format='turtle')
    operators=[op(name,'match',parameters={'node':{'label':'Person'},
        'entity_field':name,'properties':{name+'_id':'age'}}) for name in ('anchor','witness')]
    operators += [op('edge','match',parameters={'edge':{'label':'KNOWS'},
        'entity_field':'edge','source_field':'anchor','target_field':'witness'}),
        op('anchor_filter','filter',('anchor',),parameters={'condition':{'op':'eq','field':'anchor_id','value':'anchor'}}),
        op('join_anchor','join',('anchor_filter','edge'),parameters={'left_on':'anchor','right_on':'anchor'}),
        op('join_witness','join',('join_anchor','witness'),parameters={'left_on':'witness','right_on':'witness'})]
    program=SemanticGraphProgram.from_dict({'program_id':'different-necessary-domains',
        'operators':operators,'roots':['join_witness']})
    # This is a semantic equivalence oracle, not a concurrency test. RDFLib's
    # lazy SPARQL parser initialization is not safe across cold parallel calls.
    plan=compile_semantic_program(program,source_bindings={n:'rdf_a' for n in ('anchor','witness','edge')},
                                  backends=backends,max_parallelism=1)
    plan=replace(plan,metadata={**plan.metadata,'source_identities':{'rdf_a':{'source_id':'graph','snapshot_version':'v1'}},
        'source_snapshot_versions':{'rdf_a':'v1'}})
    assert pending_source_row_prefilters(program,plan)==frozenset({'anchor/native'})
    shared=share_full_native_reads(plan,program=program,backends=backends)
    assert shared.to_dict()==plan.to_dict() and not calls
    screened=prefilter_source_rows(program,shared)
    assert screened.metadata['source_row_prefilters']['native_nodes']==['anchor']
    witness=next(n for n in screened.nodes if n.node_id=='witness/native')
    assert not witness.parameters['artifact']['parameters'].get('necessary_row_filters')
    result=scheduler.execute(screened)
    assert result.success and len(result.final_rows)==1
    assert result.final_rows[0]['anchor_id']=='anchor'
    assert result.final_rows[0]['witness_id']=='witness'
    assert result.total_remote_calls==3


def test_exact_sharing_waits_for_identical_necessary_conditions_to_be_applied():
    from test_source_row_filters import setup,match
    # Unlike alias projection sharing, these artifacts are byte-identical.
    program,plan,backends,_,_,_,calls=setup(middle=[match('second'),
        op('both','union',('source','second'))])
    assert pending_source_row_prefilters(program,plan)==frozenset({'source/native','second/native'})
    assert share_full_native_reads(plan,program=program,backends=backends).to_dict()==plan.to_dict()
    screened=prefilter_source_rows(program,plan)
    assert not pending_source_row_prefilters(program,screened)
    shared=share_full_native_reads(screened,program=program,backends=backends)
    assert shared.metadata['shared_native_reads']['saved_remote_calls']==1
    assert not calls
