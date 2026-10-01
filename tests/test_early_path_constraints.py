"""Small-graph failure replay: late start/time filters must not build all paths."""
from copy import deepcopy
from decimal import Decimal
import json
import tracemalloc

import pytest
from rdflib import Literal, Namespace, URIRef
from rdflib.namespace import RDF

import test_compact_lowering as legacy
from test_compact_lowering import inputs, execute, financial_intents, EXPECTED, pred, RESOURCE, SCHEMA
from test_compact_contribution_v2 import intent as contribution_intent
from xgap.runtime.contracts import RuntimeNode, RuntimeNodeKind
from xgap.runtime.scheduler import FederatedScheduler, _deduplicate, _encoded_size
from xgap.semantic.compact_lowering import lower_compact_query


@pytest.mark.parametrize('index', [0,1,2])
def test_optimized_compiler_preserves_independent_financial_answers(inputs, index):
    q=financial_intents()[index]; before=deepcopy(q)
    rows, program, _=execute(q,inputs,optimize=True)
    assert rows==EXPECTED[index] and q==before
    assert program.metadata['compact_lowering']['execution_rewrite']=='early-path-constraints-v1'


@pytest.mark.parametrize('check', [legacy.test_equal_valued_parallel_edges_survive_medium_dedup,
    legacy.test_every_repeated_endpoint_is_a_join_equality,
    legacy.test_temporal_boundary_rejects_equal_times_and_window_endpoint,
    legacy.test_closed_temporal_cycle_is_walk_but_not_acyclic])
def test_new_rewrite_preserves_path_identity_and_boundary_counterexamples(inputs, monkeypatch, check):
    original=legacy.lower_compact_query
    monkeypatch.setattr(legacy,'lower_compact_query',lambda *a,**kw: original(*a,**(kw|{'optimize':True})))
    check(inputs)


def test_contribution_grain_is_not_changed_by_filter_pushdown(inputs):
    rows,_,_=execute(contribution_intent(),inputs,version='v2',optimize=True)
    assert rows==[{'company_id':'1','total_amount':56.0,'transfer_count':6}]


def test_rewrite_budget_retains_the_admitted_legacy_plan(inputs):
    schema=deepcopy(inputs[0]);schema['extra']=deepcopy(schema['graph'])
    q=financial_intents()[1];q['nodes'][0]['entity']=None;q['where'].append(pred('start','id','eq','1'))
    legacy_program,legacy_sources=lower_compact_query(q,schema)
    optimized,sources=lower_compact_query(q,schema,optimize=True)
    assert optimized.operators==legacy_program.operators and sources==legacy_sources
    assert len(optimized.operators)==56
    assert optimized.metadata['compact_lowering']['execution_rewrite']=='legacy-budget-fallback'


def fanout_case(inputs, *, outside_window=False):
    """Eight disconnected accounts and64 edges: no change to reference answers."""
    q=financial_intents()[1]
    q['nodes'][0]['entity']=None
    q['where'].append(pred('start','id','eq','1'))
    g=inputs[-1]['graph'];fb=Namespace(SCHEMA)
    nodes=[URIRef(RESOURCE+'noise-account-'+str(i)) for i in range(8)]
    for i,n in enumerate(nodes):
        g.add((n,RDF.type,fb.Account));g.add((n,fb.xgap_id,Literal('noise-account-'+str(i))))
        g.add((n,fb.sourceId,Literal('noise-'+str(i))))
    for i,s in enumerate(nodes):
        for j,t in enumerate(nodes):
            e=URIRef(RESOURCE+f'noise-edge-{i}-{j}')
            for prop,value in [(RDF.type,fb.Edge),(fb.edgeLabel,fb.TRANSFERRED_TO),
                    (fb.source,s),(fb.target,t),(fb.xgap_id,Literal(f'noise-edge-{i}-{j}')),
                    (fb.createTime,Literal('2019-01-01 00:00:00.000' if outside_window else '2020-01-02 00:00:00.000'))]:
                g.add((e,prop,value))
    return q


def work(result):
    counts=[n.row_count for n in result.node_results]
    return dict(total_intermediate_rows=sum(counts),max_operator_rows=max(counts),
        retention=dict(result.retention),source_calls=result.total_remote_calls)


@pytest.mark.parametrize('outside', [False, True])
def test_business_id_anchor_and_early_time_remove_disconnected_fanout(inputs, outside):
    q=fanout_case(inputs,outside_window=outside)
    a=execute(q,inputs,return_runtime=True)
    b=execute(q,inputs,optimize=True,return_runtime=True)
    assert a[0]==b[0]==EXPECTED[1]
    before,after=work(a[-1]),work(b[-1])
    assert after['max_operator_rows'] < before['max_operator_rows']/10, (before,after)
    assert after['total_intermediate_rows'] < before['total_intermediate_rows']/2, (before,after)
    assert before['source_calls']==after['source_calls']  # this compiler gate does not claim fewer source reads


def test_streaming_join_removes_quadratic_raw_pair_buffer():
    node=RuntimeNode('join',RuntimeNodeKind.COORDINATOR_JOIN,('l','r'),{'left_on':'k','right_on':'k'})
    left=tuple({'k':1,'a':'x'} for _ in range(120));right=tuple({'k':1,'b':'y'} for _ in range(120))
    def peak(fn):
        tracemalloc.start()
        try:
            rows=fn();return rows,tracemalloc.get_traced_memory()[1]
        finally:tracemalloc.stop()
    old,old_peak=peak(lambda:_deduplicate([{**l,**r} for l in left for r in right]))
    new,new_peak=peak(lambda:FederatedScheduler._join(node,left,right))
    assert old==new==({'k':1,'a':'x','b':'y'},)
    assert new_peak < old_peak/5, (old_peak,new_peak)


def test_streamed_byte_accounting_keeps_exact_json_array_size():
    rows=[{'unicode':'账户','decimal':Decimal('1.20'),'nested':[None,True,{'x':2}]},{}]
    expected=len(json.dumps(rows,sort_keys=True,separators=(',',':'),default=str).encode('utf-8'))
    assert _encoded_size(iter(rows))==expected
    assert _encoded_size(iter(()))==2
