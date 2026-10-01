"""New global compiler boundary, independent authored meanings and saved tiny facts."""
from dataclasses import replace
import json
from pathlib import Path

import pytest
from rdflib import Graph

from test_compact_lowering import financial_intents, EXPECTED
from xgap.agent.one_shot_grounding import ground_interpretation
from xgap.catalog.bundle import FrozenResolutionBundle
from xgap.compilers.global_semantic_sparql import compile_global_program, condition
from xgap.experiments.common_row_score import sparql_values
from xgap.experiments.finbench_rdf import FAMILIES
from xgap.experiments.finbench_one_shot_population import normalization
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.experiments.row_normalization import normalize_rows
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.program import SemanticOperatorKind as S

ROOT=Path('/Users/anthonyche/xgap-data/disjoint-rdf-trial-20260913-v2/rdf-profile-v2')
PIN='ef8131b3316f2ea83921a3b857576347f4d6058d4d52285b32b7a461cfa7ed89'


@pytest.fixture(scope='module')
def inputs():
    profile=FrozenOneShotProfile.load(ROOT/'profile.json',expected_sha256=PIN)
    doc=json.loads(profile.document_json)
    bundle=FrozenResolutionBundle.load(doc['catalog']['path'],expected_bundle_hash=doc['catalog']['bundle_hash'])
    mapping=json.loads((ROOT/'mapping.json').read_text());graph=Graph()
    for p in doc['offline']['rdf_loads'].values():graph.parse(p['path'])
    return doc,bundle,mapping,graph


def grounded(inputs,index=0):
    doc,bundle,_,_=inputs
    program,slots=lower_compact_query(financial_intents()[index],doc['source_schema'])
    bound,_=ground_interpretation(program,slots,bundle,'Independently authored financial tiny meaning.')
    return bound.program


@pytest.mark.parametrize('index',[0,1,2],ids=['transfer-sum','bounded-temporal-path','risk-distinct-ranking'])
def test_three_grounded_meanings_one_global_query_preserves_independent_answers(inputs,tmp_path,index):
    _,_,mapping,graph=inputs;program=grounded(inputs,index)
    artifact=compile_global_program(program,mapping)
    (tmp_path/'emitted.sparql').write_text(artifact.text)
    assert 'SERVICE' not in artifact.text and '127.0.0.1' not in artifact.text and '/aux/' not in artifact.text
    result=json.loads(graph.query(artifact.text).serialize(format='json'))
    spec=normalization(FAMILIES[index])
    assert normalize_rows(sparql_values(result,spec),spec)==normalize_rows(EXPECTED[index],spec)
    assert artifact.parameters['expanded_relations']<=4096 and artifact.parameters['query_bytes']<=1048576


def test_total_null_boolean_numeric_and_invalid_timestamp_filters():
    # Different kinds must not compare as equal, nor cast numeric-looking strings.
    graph=Graph()
    cases=[({'op':'eq','field':'a','value':True},'1',False),
           ({'op':'ne','field':'a','value':True},'1',True),
           ({'op':'ne','field':'a','value':False},'UNDEF',False),
           ({'op':'lt','field':'a','value':3},'"2"',False),
           ({'op':'not','arg':{'op':'eq','field':'a','value':3}},'UNDEF',True),
           ({'op':'eq','field':'a','value':None},'"null"',False),
           ({'op':'lt','field':'a','value':'2020-03-01 00:00:00.000','value_type':'timestamp_ms'},
            '"2020-02-30 00:00:00.000"',False),
           ({'op':'lt','field':'a','value':'2020-03-01 00:00:00.000','value_type':'timestamp_ms'},
            '"2020-02-29 00:00:00.000"',True)]
    for c,value,expected in cases:
        q='SELECT (1 AS ?kept) WHERE { VALUES ?a { '+value+' } FILTER('+condition(c,{'a':'?a'})+') }'
        assert bool(list(graph.query(q))) is expected,(c,value)


def test_compiler_rejects_expansion_bytes_unbound_and_internal_order(inputs):
    mapping=inputs[2];program=grounded(inputs)
    for kwargs,message in [({'max_expanded_nodes':2},'expansion bound'),({'max_query_bytes':200},'byte bound')]:
        with pytest.raises(ValueError,match=message):compile_global_program(program,mapping,**kwargs)
    unresolved,_=lower_compact_query(financial_intents()[0],inputs[0]['source_schema'])
    with pytest.raises(ValueError,match='grounded bounded'):compile_global_program(unresolved,mapping)
    order=program.operators[-1]
    assert order.kind is S.ORDER_LIMIT
    projection=replace(order,operator_id='new-final',kind=S.PROJECT,input_ids=(order.operator_id,),
        parameters={'projections':{'company_id':{'kind':'field','field':'company_id'}}})
    modified=replace(program,operators=(*program.operators,projection),roots=(projection.operator_id,))
    with pytest.raises(ValueError,match='final semantic'):compile_global_program(modified,mapping)
