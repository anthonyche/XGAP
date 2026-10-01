"""New source lexical risk only; no live model, full-data rerun or estimator fit."""
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path

from rdflib import Graph, Literal, URIRef

from xgap.compilers.global_semantic_sparql import condition, literal
from xgap.runtime.row_operations import filter_rows
from xgap.runtime.binding_operations import aggregate_rows
from xgap.semantic.calendar_time import canonical_timestamp_ms


def cases():
    base='2020-02-29 12:34:56'
    return [
        (base, base+'.000', 'eq', True),
        (base+'.0', base, 'eq', True),
        (base+'.00', base+'.000', 'eq', True),
        (base+'.14', base+'.140', 'eq', True),
        (base+'.1', base+'.100', 'lt', False),
        (base+'.099', base+'.1', 'lt', True),
        (base+'.14', base+'.140', 'ne', False),
        (base+'.141', base+'.14', 'gt', True),
        ('0001-01-01 00:00:00', '0001-01-01 00:00:00.000', 'eq', True),
        ('9999-12-31 23:59:59.999','9999-12-31 23:59:59.99','gt',True),
        *[(v,base+'.000','ne',False) for v in (
            None, 42, '2021-02-29 00:00:00', '2020-04-31 00:00:00',
            '0000-01-01 00:00:00', '2020-02-29 24:00:00',
            '2020-02-29 23:59:60',base+'.',base+'.1400',base+'Z',
            base+'.14+00:00',base.replace(' ','T'),base+'\n')]]


def test_omitted_zero_equivalence_boundaries_and_strict_path_order():
    for left,right,op,expected in cases():
        c={'op':op,'field':'a','right_field':'b','value_type':'timestamp_ms'}
        assert bool(filter_rows([{'a':left,'b':right}],c)) is expected,(left,right,op)
        assert bool(filter_rows([{'a':left,'b':right}],{'op':'not','arg':c})) is not expected
    assert canonical_timestamp_ms('2020-02-29 12:34:56.14')=='2020-02-29 12:34:56.140'
    # Legacy scalar comparisons remain separate; strings do not gain numeric order.
    assert not filter_rows([{'a':'2020-02-29 12:34:56','b':'2020-03-01 00:00:00'}],
        {'op':'lt','field':'a','right_field':'b'})


def test_global_time_predicate_matches_coordinator_including_invalid_calendar():
    graph=Graph()
    for left,right,op,expected in cases():
        c={'op':op,'field':'a','right_field':'b','value_type':'timestamp_ms'}
        values=['UNDEF' if v is None else literal(v) for v in (left,right)]
        body='VALUES (?a ?b) { ('+' '.join(values)+') }'
        query='SELECT (1 AS ?kept) WHERE { '+body+' FILTER('+condition(c,{'a':'?a','b':'?b'})+') }'
        assert bool(list(graph.query(query))) is expected,(left,right,op)


def test_saved_ten_rejected_transfers_replay_preserves_parallel_contributions():
    saved=json.loads(Path('tests/fixtures/financial_timestamp_failure_v1.json').read_text())
    c={'op':'and','args':[
        {'op':'ge','field':'timestamp','value':saved['start_time'],'value_type':'timestamp_ms'},
        {'op':'lt','field':'timestamp','value':saved['end_time'],'value_type':'timestamp_ms'}]}
    rows=filter_rows(saved['rows'],c)
    assert len(rows)==10 and len({r['transfers_edge'] for r in rows})==10
    totals=aggregate_rows({'group_by':['company_id'],
        'aggregations':{'total':{'op':'sum','field':'amount'}}},rows)
    assert {r['company_id']:Decimal(str(r['total'])) for r in totals}=={
        c:Decimal(v) for c,v in saved['expected_missing_totals'].items()}
    # Independent equality at inclusive lower / exclusive upper, regardless of lexeme width.
    short={'t':'2020-01-01 00:00:00.14'}
    assert filter_rows([short],{'op':'ge','field':'t','value':'2020-01-01 00:00:00.140','value_type':'timestamp_ms'})==(short,)
    assert filter_rows([short],{'op':'lt','field':'t','value':'2020-01-01 00:00:00.140','value_type':'timestamp_ms'})==()


def test_tiny_estimated_single_plan_with_short_fraction_source_values(tmp_path):
    from test_finbench_rdf import prepared, parameters, expected_rows
    from test_financial_binding import backends_for, deployment
    from xgap.agent.one_shot_policy import OneShotPolicy
    from xgap.backends.fuseki_client import FusekiClient
    from xgap.experiments.finbench_semantic import financial_program
    from xgap.infrastructure.descriptors import BackendDescriptor
    from xgap.runtime.one_shot_planning import prepare_one_shot_domain
    from xgap.runtime.semantic_planning import LogicalSource
    from xgap.runtime.scheduler import FederatedScheduler
    from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin
    _,root,graph,_=prepared(tmp_path)
    timestamp=URIRef('https://xgap.dev/benchmark/finbench/v0.1.0/schema/createTime')
    changed=0
    for s,p,o in list(graph.triples((None,timestamp,None))):
        text=str(o)
        short=text.rstrip('0').rstrip('.') if '.' in text else text
        if short!=text:
            graph.remove((s,p,o));graph.add((s,p,Literal(short,datatype=o.datatype)));changed+=1
    assert changed>0
    program,slots=financial_program('F3',parameters()[2])
    policy=replace(OneShotPolicy.for_mode('performance'),max_parallelism=1)
    candidates,domain=prepare_one_shot_domain(program,operator_sources={op:'tiny' for op in slots},
        sources={'tiny':LogicalSource('tiny','financial-tiny-v1',('fuseki',))},
        backends=backends_for(json.loads((root/'mapping.json').read_text())),policy=policy)
    estimator=deployment();predictions=[(c,estimator.predict(c.plan)) for c in candidates]
    selected,_=min(((c,p) for c,p in predictions if p.estimated_ms is not None),
        key=lambda i:(i[1].estimated_ms,i[0].strategy_id))
    calls=[]
    class FixtureRdf(FusekiClient):
        def _post_query(self,text):
            calls.append(text)
            return json.loads(graph.query(text).serialize(format='json'))
    registry=BackendPluginRegistry()
    registry.register(NativeBackendPlugin('fuseki',FixtureRdf(BackendDescriptor('fuseki','fuseki','sparql','rdf'))))
    assert not calls
    result=FederatedScheduler(BackendInvokeTool(registry)).execute(selected.plan)
    assert result.success,result.to_dict()
    assert list(result.final_rows)==expected_rows()[2]
    assert result.total_remote_calls==len(calls)==len(slots)==5
    assert domain['candidate_count']<=domain['construction_bound']
