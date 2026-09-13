"""Finite existing source-serializer adapter risks, independent of any workload."""
from prepare_finbench_equality_bounds import extract_ids
import pytest

MAPPING={'Person':{'representation':'urn:type:Person'},'id':{'representation':'urn:prop:id'}}
OPTIONS={'term_mappings':MAPPING,'namespace':'urn:node:','expected_counts':{'Person':2}}


def test_native_graph_and_auxiliary_control_serializations_preserve_duplicate_values():
    graph=['<urn:node:a> a <urn:type:Person> ; <urn:prop:id> "001" .',
           '<urn:node:a> <urn:prop:name> "Not an ID" .',
           '<urn:node:b> a <urn:type:Person> ; <urn:prop:id> "001" .',
           '<urn:edge:1> a <urn:type:Edge> ; <urn:prop:source> <urn:node:a> .']
    control=['@prefix aux: <urn:type:> .','@prefix prop: <urn:prop:> .',
             '@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .',
             '<urn:node:a> rdf:type aux:Person .','<urn:node:a> prop:id "001" .',
             '<urn:node:b> rdf:type aux:Person .','<urn:node:b> prop:id "001" .']
    expected=[{'label':'Person','properties':{'id':'001'}}]*2
    assert extract_ids(graph,**OPTIONS)==extract_ids(control,**OPTIONS)==expected


@pytest.mark.parametrize('bad',['missing','duplicate','numeric','count','namespace'])
def test_changed_or_incomplete_entity_id_coverage_fails(bad):
    text=['<urn:node:a> a <urn:type:Person> ; <urn:prop:id> "1" .',
          '<urn:node:b> a <urn:type:Person> ; <urn:prop:id> "2" .']
    if bad=='missing':text[1]='<urn:node:b> a <urn:type:Person> ; <urn:prop:other> "2" .'
    elif bad=='duplicate':text[1]=text[0]
    elif bad=='numeric':text[1]=text[1].replace('"2"','2')
    elif bad=='count':text.pop()
    else:text[1]=text[1].replace('urn:node:b','urn:wrong:b')
    with pytest.raises(ValueError):extract_ids(text,**OPTIONS)
