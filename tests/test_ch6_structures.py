import pytest
from xgap.experiments.ch6_structures import extract,instantiate
from xgap.experiments.ch6_metrics import trace_cost


def record(q):return extract({'uid':1,'sparql_wikidata':q},source_version='test')


def test_parser_preserves_aggregation_order_and_literal_types():
    r=record('SELECT ?x (SUM(?v) AS ?total) WHERE { ?x <urn:amount> ?v . FILTER(?v > 2) } GROUP BY ?x HAVING(SUM(?v)>3) ORDER BY DESC(?total) ?x LIMIT 10')
    assert r['status']=='extracted_pending_domain_admission',r.get('error')
    assert {'S07','S08'}<=set(r['structure_categories'])
    assert r['output_semantics']['HavingClause'] and r['output_semantics']['OrderClause']
    assert record('SELECT DISTINCT ?x WHERE { ?x <urn:p> <urn:a> }')['structure_hash']!=record('SELECT ?x WHERE { ?x <urn:p> <urn:a> }')['structure_hash']
    p=next(x for x in r['parameters'] if x['term']['term']=='literal')
    bindings={x['name']:dict(x['term']) for x in r['parameters']}
    bindings[p['name']]['value']='bad-number'
    with pytest.raises(ValueError):instantiate(r,bindings)


def test_variable_renaming_and_typed_instantiation_do_not_drop_topology():
    a=record('SELECT ?x WHERE { ?x <urn:p> <urn:a> . ?x <urn:q> ?y }')
    b=record('SELECT ?foo WHERE { ?foo <urn:p> <urn:a> . ?foo <urn:q> ?bar }')
    assert a['structure_hash']==b['structure_hash']
    params={p['name']:p['term'] for p in a['parameters']}
    assert instantiate(a,params)['resolved_algebra']==a['resolved_algebra']
    assert len(a['triples'])==2


@pytest.mark.parametrize('body',['?x <urn:p> ?y OPTIONAL { ?y <urn:q> ?z }',
    '?x <urn:p>* ?y','?x <http://www.wikidata.org/prop/qualifier/P1> ?y',
    '?x <urn:p> ?y MINUS { ?x <urn:q> ?y }'])
def test_unsupported_patterns_keep_raw_evidence(body):
    r=record('SELECT ?x WHERE { '+body+' }')
    assert r['status']=='rejected' and r['raw_query'] and r['raw_ast'] and r['reasons']


def test_actual_work_cost_ignores_estimates_and_propagates_missing():
    actual={'clarification_calls':2,'execution_backend_calls':3,'selected_execution_cost_estimate':999999}
    assert trace_cost(actual,{'clarification_calls':1,'execution_backend_calls':2})['trace_cost']==8
    assert trace_cost(actual,{'transferred_bytes':1})['trace_cost'] is None
    assert trace_cost(actual,{'transferred_bytes':0})['trace_cost']==0


def test_directed_chain_and_outgoing_star_have_different_catalog_categories():
    chain=record('SELECT ?a WHERE {?a <urn:p> ?b . ?b <urn:q> ?c}')
    star=record('SELECT ?a WHERE {?a <urn:p> ?b . ?a <urn:q> ?c}')
    assert chain['structure_categories']==['S02']
    assert star['structure_categories']==['S03']
