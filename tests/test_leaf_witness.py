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


@pytest.mark.parametrize('reverse',[False,True])
def test_correlated_leaf_guard_rejects_missing_or_unrelated_values(reverse):
    from rdflib import Graph,Namespace,Literal,RDF
    from xgap.pattern.ast import Direction
    from xgap.compilers.rdf_encoding import RdfEdgeEncoding
    from xgap.runtime.leaf_witness import compile_rdf_leaf_bound
    ns=Namespace('https://test/');g=Graph()
    terms={k:dict(kind=kind,representation=str(ns[k])) for k,kind in
           [('User','class'),('Movie','class'),('RATED','relation'),('id','property')]}
    # Variable-looking text in a mapped IRI must not be alpha-renamed.
    terms['User']['representation']=str(ns['User?n0'])
    mapping=dict(mapping_id='leaf-test',version='1',backends={'fuseki':dict(namespace=str(ns))},
                 term_mappings={'fuseki':terms})
    encoding=RdfEdgeEncoding('leaf-test',str(ns.Edge),str(ns.source),str(ns.target),str(ns.edgeLabel))
    backend=SemanticBackend('fuseki',str(ns),backend_mapping=mapping,rdf_edge_encoding=encoding)
    base=compile_edge_match(EdgePattern(label='RATED',direction=Direction.IN if reverse else Direction.OUT),{},
        backend_id='fuseki',backend_mapping=mapping,rdf_edge_encoding=encoding,
        source=NodePattern(label='Movie' if reverse else 'User'),target=NodePattern(label='User' if reverse else 'Movie'))
    proof=next(leaf_proofs(template_query(CORES['D2'],'incoming_minimum','user:1',0)))
    if reverse:
        proof['boundary_column']='source'
        for guard in proof['guards']:
            for term in (guard['left'],guard['right']):
                if 'endpoint' in term:term['endpoint']={'source':'target','target':'source'}[term['endpoint']]
    artifact=compile_rdf_leaf_bound(base,backend,proof,parameter='keys',max_bindings=4,max_bytes=20000)
    assert artifact.text.count('SELECT')==1 and 'DISTINCT' not in artifact.text
    assert 'BIND(' not in artifact.text and '<https://test/User?n0>' in artifact.text
    assert 'singleton_anchor' not in artifact.parameters['sparql_iri_binding']
    assert 'flat_body' not in artifact.parameters
    for i in range(4):
        g.add((ns['u'+str(i)],RDF.type,ns['User?n0']));g.add((ns['m'+str(i)],RDF.type,ns.Movie))
    for u,value in [('u1','user:1'),('u2','user:1'),('u2','user:2'),('u3','unrelated')]:
        g.add((ns[u],ns.id,Literal(value)))
    for edge,u,m in [('e0','u0','m0'),('e1','u1','m1'),('e2','u2','m2'),('e3','u2','m2')]:
        for p,o in [(RDF.type,ns.Edge),(ns.source,ns[u]),(ns.target,ns[m]),(ns.edgeLabel,ns.RATED)]:
            g.add((ns[edge],p,o))
    rows=list(g.query(bind_sparql_iris(artifact.text,{**artifact.parameters,
                      'keys':[str(ns['m'+str(i)]) for i in range(4)]})))
    assert len(rows)==1
    assert (rows[0].source,rows[0].target)==((ns.m2,ns.u2) if reverse else (ns.u2,ns.m2))
    assert rows[0].entity in (ns.e2,ns.e3)


def test_many_witness_keys_have_bounded_algebra_depth_without_lost_keys():
    from rdflib import Graph,URIRef
    from rdflib.plugins.sparql.algebra import translateQuery
    from rdflib.plugins.sparql.parser import parseQuery
    keys=['https://test/key'+str(i) for i in range(65)]
    text='SELECT ?entity ?source ?target WHERE { '+IRI_VALUES_MARKER+' ?entity <https://test/p> ?target . BIND(?entity AS ?source) }'
    spec=dict(parameter='keys',variable='target',max_bindings=66,max_bytes=100000,
        singleton_anchor=dict(subject='entity',predicate='https://test/p'),per_key_limit=1,projection=['entity','source','target'])
    query=bind_sparql_iris(text,dict(sparql_iri_binding=spec,keys=keys+[keys[0]]))
    def union_depth(value):
        if isinstance(value,dict):
            return int(getattr(value,'name',None)=='Union')+max(map(union_depth,value.values()),default=0)
        if isinstance(value,(list,tuple)):return max(map(union_depth,value),default=0)
        return 0
    assert union_depth(translateQuery(parseQuery(query)).algebra)<=7
    g=Graph()
    for key in keys:
        for suffix in ('a','b'):g.add((URIRef(key+suffix),URIRef('https://test/p'),URIRef(key)))
    rows=list(g.query(query))
    assert len(rows)==len(keys) and {str(row.target) for row in rows}==set(keys)
