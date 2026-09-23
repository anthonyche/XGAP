from copy import deepcopy
from dataclasses import replace

import pytest

from xgap.experiments.ch6_fact_index import CORES
from xgap.experiments.ch6_heldout import template_query,ref
from xgap.runtime.leaf_witness import leaf_proofs,compile_leaf_bound
from xgap.compilers.edge_match import compile_edge_match
from xgap.pattern.ast import EdgePattern,NodePattern
from xgap.runtime.semantic_compiler import SemanticBackend
from xgap.backends.sparql_bindings import bind_sparql_iris,IRI_VALUES_MARKER


def test_leaf_admission_respects_contribution_and_joint_witness_constraints():
    query=template_query(CORES['D2'],'incoming_minimum','user:1',0)
    proof=list(leaf_proofs(query));assert len(proof)==1
    assert (proof[0]['edge'],proof[0]['leaf'],proof[0]['boundary'])==('f','c','b')
    for edit in ('project','contribute','couple','predicate','path'):
        q=deepcopy(query)
        if edit=='project':q['select']['witness']=ref('c')
        if edit=='contribute':q['contribution_by'].append('f')
        if edit=='couple':q['edges'].append(dict(var='g',type='RATED',source='c',target='a'))
        if edit=='predicate':q['where'].append(dict(left=ref('f','rating'),op='gt',right=ref('e','rating'),value_type='scalar'))
        if edit=='path':q['path']={'var':'p'}
        assert not list(leaf_proofs(q)),edit
    q=deepcopy(query);q['contribution_by']=None
    assert not list(leaf_proofs(q))
    assert not list(leaf_proofs(template_query(CORES['D2'],'outgoing_maximum','user:1',0)))


def test_native_representation_preserves_query_and_has_per_key_not_global_limit():
    query=template_query(CORES['D2'],'incoming_minimum','user:1',0)
    proof=next(leaf_proofs(query));backend=SemanticBackend('neo4j','https://test/',identity_property='xgap_id')
    base=compile_edge_match(EdgePattern(label='RATED'),{},backend_id='neo4j',identity_property='xgap_id',
        source=NodePattern(label='User'),target=NodePattern(label='Movie'))
    result=compile_leaf_bound(base,backend,proof,parameter='keys',max_bindings=50)
    assert 'UNWIND $keys AS xgap_leaf_key' in result.text
    assert result.text.index('MATCH (n1)')<result.text.index('MATCH (n0)-[e1]')
    assert '\nLIMIT 1\n}\nRETURN DISTINCT entity, source, target' in result.text
    assert result.parameters['leaf_witness']['adjacency_scan_bound'] is None
    assert 'native_binding_checkpoint' not in result.parameters
    with pytest.raises(ValueError,match='exact'):
        compile_leaf_bound(replace(base,text='// edited\n'+base.text),backend,proof,parameter='keys',max_bindings=50)


def test_rdf_branch_limit_and_full_expansion_bytes_are_bounded():
    text='SELECT ?entity ?source ?target WHERE { '+IRI_VALUES_MARKER+' ?entity <https://test/p> ?target . BIND(?entity AS ?source) }'
    spec=dict(parameter='keys',variable='target',max_bindings=3,max_bytes=4096,
        singleton_anchor=dict(subject='entity',predicate='https://test/p'),per_key_limit=1,projection=['entity','source','target'])
    p=dict(sparql_iri_binding=spec,keys=['https://test/a','https://test/b','https://test/a'])
    result=bind_sparql_iris(text,p)
    assert result.count('LIMIT 1')==2 and result.count(' UNION ')==1
    assert '?entity <https://test/p> <https://test/a>' in result
    assert 'FILTER(false)' in bind_sparql_iris(text,{**p,'keys':[]})
    with pytest.raises(ValueError,match='byte budget'):
        bind_sparql_iris(text,{**p,'sparql_iri_binding':{**spec,'max_bytes':200}})
    with pytest.raises(ValueError,match='excessive'):
        bind_sparql_iris(text,{**p,'keys':['https://test/'+str(i) for i in range(4)]})
