"""Differential SPJ streaming, shared consumers and explicit semantic barriers."""
from dataclasses import replace
import random
import pytest

from xgap.runtime.contracts import (FederatedExecutionPlan,RuntimeNode as N,RuntimeNodeKind as R,
    RuntimeNodeResult,RuntimeNodeStatus as S)
from xgap.runtime.scheduler import FederatedScheduler


def plan(limit=3,ordering=None):
    return FederatedExecutionPlan('star',(
        N('left',R.REMOTE_QUERY),N('right',R.REMOTE_QUERY),
        N('join',R.COORDINATOR_JOIN,('left','right'),dict(left_on='a',right_on='a')),
        N('filter',R.COORDINATOR_FILTER,('join',),dict(condition=dict(op='lt',field='b',right_field='c',value_type='lexical_string'))),
        N('project',R.COORDINATOR_ROW_PROJECT,('filter',),dict(projections={n:dict(kind='field',field=n) for n in ('b','c')})),
        N('top',R.COORDINATOR_SORT_LIMIT,('project',),dict(limit=limit,order_by=ordering or [dict(field='b'),dict(field='c')]))),
        ('top',),max_remote_calls=2)


def execute(p,left,right,*,stream=True,failure=False):
    class Fixture(FederatedScheduler):
        def _execute_remote(self,node,goal_id,results):
            rows=left if node.node_id=='left' else right
            return RuntimeNodeResult(node.node_id,node.kind,S.ERROR if failure and node.node_id=='right' else S.SUCCESS,
                rows=tuple(rows),error='source failure' if failure and node.node_id=='right' else None,remote_calls=1)
    return Fixture(None,retention='roots',stream_topk=stream).execute(p)


@pytest.mark.parametrize('direction',('asc','desc'))
@pytest.mark.parametrize('nulls',('first','last'))
def test_exact_order_nulls_duplicates_eviction_and_permutations(direction,nulls):
    order=[dict(field='b',direction=direction,nulls=nulls),dict(field='c',direction=direction,nulls=nulls)]
    p=plan(4,order)
    # Include non-output numeric witnesses, repeated projected tuples and nulls.
    left=[dict(a='anchor',b=v,w=i%2) for i,v in enumerate(['2','10','a','z',None,'2','é','中'])]
    right=[dict(a='anchor',c=v) for v in ['z','2','10','é','中',None,'z']]+[dict(a=None,c='zzz')]
    rng=random.Random(61)
    for _ in range(8):
        rng.shuffle(left);rng.shuffle(right)
        old=execute(p,left,right,stream=False);new=execute(p,left,right)
        assert new.success and old.final_rows==new.final_rows
        assert old.total_remote_calls==new.total_remote_calls==2
        assert new.retention['streaming_topk'][0]['maximum_answer_rows']==4
        assert new.retention['streaming_topk'][0]['retained_answer_rows']<=4
        assert next(n for n in new.node_results if n.node_id=='join').rows is None


def test_product_memory_is_not_retained_and_boundaries_stay_alive():
    p=plan(20);left=[dict(a='anchor',b=str(i)) for i in range(80)]
    right=[dict(a='anchor',c=str(i)) for i in range(80)]
    old=execute(p,left,right,stream=False);new=execute(p,left,right)
    assert new.final_rows==old.final_rows and len(new.final_rows)==20
    assert new.retention['peak_registered_rows']<=180
    assert old.retention['peak_registered_rows']>=6400
    receipt=new.retention['streaming_topk'][0]
    assert receipt['streamed_rows']['join']==6400 and receipt['scan_bound'] is None
    assert receipt['maximum_single_join_index_rows']==80
    # Shared join is retained for the other root and cannot be absorbed.
    shared=execute(replace(p,roots=('top','join')),left,right)
    assert shared.success and len(shared.root_rows['join'])==6400
    assert shared.retention['streaming_topk']==[]


@pytest.mark.parametrize('case',('numeric','partial_order','empty','collision','calendar','bad_filter','error'))
def test_unsupported_or_error_path_uses_original_semantics(case):
    p=plan();left=[dict(a='a',b='1')];right=[dict(a='a',c='2')]
    nodes=list(p.nodes)
    if case=='numeric':left=[dict(a='a',b=1)]
    if case=='partial_order':nodes[-1]=replace(nodes[-1],parameters=dict(limit=3,order_by=[dict(field='b')]))
    if case=='empty':right=[]
    if case=='collision':right=[dict(a='a',b='different',c='2')]
    if case=='calendar':nodes[3]=replace(nodes[3],parameters=dict(condition=dict(op='lt',field='b',right_field='c',value_type='timestamp_ms')))
    if case=='bad_filter':nodes[3]=replace(nodes[3],parameters=dict(condition=dict(op='eq',field='missing',value=1)))
    p=replace(p,nodes=tuple(nodes))
    old=execute(p,left,right,stream=False,failure=case=='error');new=execute(p,left,right,failure=case=='error')
    assert old.final_rows==new.final_rows and old.success==new.success
    assert new.retention['streaming_topk']==[]
    assert [(r.node_id,r.status,r.error) for r in old.node_results]==[(r.node_id,r.status,r.error) for r in new.node_results]
