"""Only identity-map transport equivalence and its affected wrapping boundaries."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from xgap.compilers.edge_match import compile_edge_match
from xgap.compilers.errors import UnsupportedCompilationError
from xgap.compilers.node_match import compile_node_match
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.infrastructure.runtime import QueryArtifact
from xgap.pattern.ast import EdgePattern, NodePattern
from xgap.runtime.physical_strategies import _bound_match_artifact
from xgap.runtime.row_operations import normalize_node_bindings
from xgap.runtime.semantic_compiler import compile_semantic_source
from xgap.semantic.program import SemanticGraphProgram

PROFILE=Path('/Users/anthonyche/xgap-data/financial-nl-native-20260912-compact-v1/profile/profile.json')
PROFILE_SHA='1b9af9d4e60e3428e8f5ac235bb5aab8237da1b329e91510a5992171deb78bd8'


def match(edge=False):
    p={'entity_field':'key','properties':{'value':'id','absent':'personName'}}
    p.update({'edge':{'label':'TRANSFERRED_TO','properties':{}},'source_field':'left','target_field':'right'} if edge else
             {'node':{'label':'XGAPFinBenchAccount','properties':{}}})
    return SemanticGraphProgram.from_dict({'program_id':'identity-projection','operators':[
        {'operator_id':'m','kind':'match','input_ids':[],'input_kinds':[],'output_kind':'binding_set','parameters':p}],
        'roots':['m']}).operators[0]


def test_projected_maps_preserve_parallel_edges_and_scalar_values():
    settings={'language':'cypher','identity_property':'key','resource_namespace':'urn:identity:',
        'entity_field':'edge','identity_fields':{'entity':'edge','source':'source','target':'target'},'scalar_fields':['amount','absent']}
    raw=[{'entity':{'key':e,'ignored':'wide'*100},'source':{'key':'a','payload':[1,2,3]},
          'target':{'key':'b','secret_property':'unused'},'amount':1.25,'absent':None} for e in ('e1','e2')]
    compact=[{**row,**{col:{'key':row[col]['key']} for col in ('entity','source','target')}} for row in raw]
    expected=({'edge':'urn:identity:e1','source':'urn:identity:a','target':'urn:identity:b','amount':1.25,'absent':None},
              {'edge':'urn:identity:e2','source':'urn:identity:a','target':'urn:identity:b','amount':1.25,'absent':None})
    assert normalize_node_bindings(raw,settings)==normalize_node_bindings(compact,settings)==expected
    assert len(json.dumps(compact))<len(json.dumps(raw))
    for bad in ({}, {'key':None}, {'key':17}, {'key':'not/canonical'}):
        with pytest.raises((KeyError,ValueError)):
            normalize_node_bindings([{**compact[0],'entity':bad}],settings)


def test_semantic_wiring_and_rdf_result_contract_are_preserved():
    _,_,_,_,backends,_,_=FrozenOneShotProfile.load(PROFILE,expected_sha256=PROFILE_SHA).materialize()
    for edge in (False,True):
        op=match(edge);native=compile_semantic_source(op,backends['neo4j']);rdf=compile_semantic_source(op,backends['fuseki'])
        q=native.nodes[0].parameters['artifact'];p=q['parameters']
        assert p['native_identity_projection']=='property-map-v1' and p['native_identity_property']=='xgap_id'
        assert native.nodes[1].parameters['scalar_fields']==['value','absent']
        legacy=(compile_edge_match(EdgePattern(label='TRANSFERRED_TO'),op.parameters['properties'],backend_id='neo4j') if edge else
                compile_node_match(NodePattern(label='XGAPFinBenchAccount'),op.parameters['properties'],backend_id='neo4j'))
        assert 'native_identity_projection' not in legacy.parameters and '{.xgap_id}' not in legacy.text
        rdf_spec=backends['fuseki'];kwargs={'backend_id':'fuseki','backend_mapping':rdf_spec.backend_mapping,
            'profile':rdf_spec.profile,'artifact_id':'m-match'}
        reference=(compile_edge_match(EdgePattern(label='TRANSFERRED_TO'),op.parameters['properties'],rdf_edge_encoding=rdf_spec.rdf_edge_encoding,**kwargs) if edge else
                   compile_node_match(NodePattern(label='XGAPFinBenchAccount'),op.parameters['properties'],rdf_node_classes=rdf_spec.rdf_node_classes,**kwargs))
        assert rdf.nodes[0].parameters['artifact']==reference.to_dict()


def test_bind_wrapping_retains_declared_identity_and_projection():
    _,_,_,_,backends,_,_=FrozenOneShotProfile.load(PROFILE,expected_sha256=PROFILE_SHA).materialize()
    for edge in (False,True):
        backend=backends['neo4j'];fragment=compile_semantic_source(match(edge),backend)
        a=QueryArtifact.from_dict(fragment.nodes[0].parameters['artifact'])
        for col in ('entity','source','target') if edge else ('entity',):
            bound,parameter=_bound_match_artifact(a,backend,max_bindings=16,max_binding_bytes=4096,identity_column=col)
            point=a.parameters['native_binding_checkpoint'];offset=point['offset']
            assert a.text[len('CALL {\n'):offset] in bound.text and a.text[offset:] in bound.text
            early=f'($xgap_strategy_entity_namespace + {point["variables"][col]}.xgap_id) IN $'+parameter
            assert bound.text.index(early)<bound.text.index('RETURN DISTINCT ')
            assert f'{col}.xgap_id' in bound.text  # final defensive identity filter remains
            anchored=edge and col in ('source','target')
            assert bound.parameters['native_binding_placement']==('endpoint-anchor-before-expand-v1' if anchored else 'before-innermost-distinct-v1')
            if anchored:
                v=point['variables'][col]
                assert bound.text.index('RETURN '+v+'\n}\n')<bound.text.index('MATCH (n0)-[e1]')
            assert bound.parameters['native_identity_projection']=='property-map-v1'
            assert bound.parameters['bound_entity_parameter']==parameter
            wrapped=replace(a,text='// independently wrapped artifact\n'+a.text)
            legacy,_=_bound_match_artifact(wrapped,backend,max_bindings=16,max_binding_bytes=4096,identity_column=col)
            assert wrapped.text in legacy.text and 'native_binding_placement' not in legacy.parameters


def test_identity_property_escaping_and_invalid_names():
    for prop in (None,'identity key','identity`key'):
        a=compile_node_match(NodePattern(),{},backend_id='neo4j',identity_property=prop)
        if prop is not None:assert a.parameters['native_identity_property']==prop and 'source{.`identity' in a.text
    for prop in ('',0,'unsafe\\u0060','line\nbreak'):
        with pytest.raises((ValueError,UnsupportedCompilationError)):
            compile_node_match(NodePattern(),{},backend_id='neo4j',identity_property=prop)


def test_rdf_singleton_anchor_uses_stored_direction_and_preserves_key_caps():
    from xgap.pattern.ast import Direction
    from xgap.backends.sparql_bindings import bind_sparql_iris
    _,_,_,_,backends,_,_=FrozenOneShotProfile.load(PROFILE,expected_sha256=PROFILE_SHA).materialize()
    backend=backends['fuseki'];encoding=backend.rdf_edge_encoding;key='https://example.test/key'
    for direction in (Direction.OUT,Direction.IN):
        a=compile_edge_match(EdgePattern(label='TRANSFERRED_TO',direction=direction),{},backend_id='fuseki',
            backend_mapping=backend.backend_mapping,rdf_edge_encoding=encoding,profile=backend.profile)
        for col in ('source','target'):
            bound,parameter=_bound_match_artifact(a,backend,max_bindings=16,max_binding_bytes=4096,identity_column=col)
            params={**bound.parameters,parameter:[key]}
            pred=encoding.source_predicate_iri if (col=='source')==(direction is Direction.OUT) else encoding.target_predicate_iri
            triple='?e1 <'+pred+'> <'+key+'> .'
            assert triple in bind_sparql_iris(bound.text,params)
            assert triple not in bind_sparql_iris(bound.text,{**params,parameter:[key,key+'/second']})
            small={**params,'sparql_iri_binding':{**params['sparql_iri_binding'],'max_bytes':1}}
            with pytest.raises(ValueError,match='byte budget'):bind_sparql_iris(bound.text,small)


@pytest.mark.parametrize('reverse',[False,True])
def test_native_index_requires_mandatory_position_label_and_same_identity_view(reverse):
    from xgap.pattern.ast import Direction
    from xgap.runtime.semantic_compiler import SemanticBackend
    backend=SemanticBackend('neo4j','https://test/',identity_property='xgap_id')
    labels=('Movie','User') if reverse else ('User','Movie')
    base=compile_edge_match(EdgePattern(label='RATED',direction=Direction.IN if reverse else Direction.OUT),{},
        source=NodePattern(label=labels[0]),target=NodePattern(label=labels[1]),
        backend_id='neo4j',identity_property='xgap_id')
    for column,variable,label in [('source','n0',labels[0]),('target','n1',labels[1])]:
        bound,_=_bound_match_artifact(base,backend,max_bindings=8,max_binding_bytes=4096,identity_column=column)
        assert f'MATCH ({variable}:{label})' in bound.text
        assert bound.parameters['native_identity_access']=='mandatory-label-local-key-membership-v1'
        assert 'STARTS WITH $xgap_strategy_entity_namespace' in bound.text
        assert f'($xgap_strategy_entity_namespace + {variable}.xgap_id) IN $xgap_strategy_entity_bindings' in bound.text
        assert 'LIMIT' not in bound.text and 'USING INDEX' not in bound.text
        for invalid in (replace(base,text='// wrapped\n'+base.text),
                replace(base,parameters={k:v for k,v in base.parameters.items() if k=='native_binding_checkpoint' or not k.startswith('native_identity_')})):
            fallback,_=_bound_match_artifact(invalid,backend,max_bindings=8,max_binding_bytes=4096,identity_column=column)
            assert 'native_identity_access' not in fallback.parameters
