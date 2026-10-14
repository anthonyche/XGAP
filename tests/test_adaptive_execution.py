"""Local semantic, resource-switching and genuine pull-pipeline regressions."""
from dataclasses import replace
import json
import random
import pytest
from xgap.backends.request_control import RequestControl
from xgap.runtime.spill_rows import SpillWorkspace,distinct
from xgap.runtime.spill_operators import operate
from xgap.runtime.contracts import RuntimeNode as N,RuntimeNodeKind as K,RuntimeNodeResult as R,RuntimeNodeStatus as S,FederatedExecutionPlan
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.stream_scheduler import StreamingScheduler
from xgap.runtime.execution_limits import ExecutionLimits


def remote(name='read'):
    return N(name,K.REMOTE_QUERY,parameters={'backend_id':'local','artifact':{'artifact_id':name,'language':'sparql','text':'fixture'}})


class Client:
    def __init__(self,rows):self.rows=rows;self.calls=0
    def execute_stream(self,a,emit,control,workspace):
        self.calls+=1
        for row in self.rows:emit(dict(row))


def test_buffered_small_result_has_no_database_files_and_promotes_exactly():
    with SpillWorkspace(RequestControl(),memory_bytes=32768) as work:
        store=work.store();rows=[{'x':i,'p':'z'*1000} for i in range(100)]
        for row in rows[:3]:store.append(row)
        assert not list(__import__('pathlib').Path(work.temp.name).iterdir())
        assert list(store)==rows[:3] and work.bytes==0
        for row in rows[3:]:store.append(row)
        store.finish()
        assert list(store)==rows and list(store)==rows
        assert work.spilled_stores>0 and work.peak_memory_bytes<=32768
        store.close();assert work.bytes==work.memory_bytes==0


@pytest.mark.parametrize('budget',[0,32768,8*1024**2])
def test_adaptive_algebra_matches_reference_with_typed_values_and_skew(budget):
    rng=random.Random(721);values=[None,True,False,1,1.0,'1',-1,2.5]
    rows=[{'k':rng.choice(values),'v':rng.choice([None,1,1.0,-2,3.5]),'p':'x'*160} for _ in range(150)]
    cases=[(K.COORDINATOR_JOIN,dict(left_on='k',right_on='k'),[rows,rows[:10]]),
        (K.COORDINATOR_SORT_LIMIT,dict(order_by=[dict(field='k',direction='desc')],limit=20),[rows])]
    for unique in (False,True):
        cases.append((K.COORDINATOR_GROUP_AGGREGATE,dict(group_by=['k'],aggregations={op:dict(op=op,field='v',distinct=unique) for op in ('count','sum','min','max')}),[rows]))
    for kind,parameters,inputs in cases:
        node=N('out',kind,tuple(str(i) for i in range(len(inputs))),parameters)
        records={str(i):R(str(i),K.REMOTE_QUERY,S.SUCCESS,rows=tuple(v)) for i,v in enumerate(inputs)}
        reference=FederatedScheduler(None)._execute_local(node,records)
        assert reference.status is S.SUCCESS
        with SpillWorkspace(RequestControl(),memory_bytes=budget) as work:
            assert tuple(operate(work,node,inputs))==reference.rows
            assert work.bytes==work.memory_bytes==0
            assert work.peak_memory_bytes<=budget


def test_compact_group_state_spills_without_replaying_input():
    rows=[{'k':i,'v':i} for i in range(120)]+[{'k':i,'v':1} for i in range(120)]
    visited=[]
    def source():
        for row in rows:visited.append(row);yield row
    node=N('sum',K.COORDINATOR_GROUP_AGGREGATE,('in',),dict(group_by=['k'],aggregations={'n':dict(op='sum',field='v')}))
    with SpillWorkspace(RequestControl(),memory_bytes=32768) as work:
        result=list(operate(work,node,[source()]))
        assert result==[{'k':i,'n':i+1} for i in range(120)]
        assert visited==rows and work.spilled_stores>0 and work.memory_bytes==work.bytes==0


def test_hash_collisions_do_not_merge_distinct_rows(monkeypatch):
    monkeypatch.setattr('xgap.runtime.spill_rows.distinct_bucket',lambda value:'collision')
    rows=[{'v':1.0},{'v':2},{'v':1},{'v':True},{'v':'1'}]
    from xgap.runtime.scalars import distinct_rows
    with SpillWorkspace(RequestControl()) as work:
        assert tuple(distinct(work,rows))==distinct_rows(rows)


def test_pipeline_consumes_before_upstream_finishes_and_fanout_runs_once(monkeypatch):
    import xgap.runtime.row_pipeline as module
    events=[];original=module.operate
    def observed(work,node,inputs,**kwargs):
        for row in original(work,node,inputs,**kwargs):events.append((node.node_id,row['v']));yield row
    monkeypatch.setattr(module,'operate',observed)
    client=Client([{'v':i} for i in range(5)])
    nodes=(remote(),N('filter',K.COORDINATOR_FILTER,('read',),dict(condition={'op':'ge','field':'v','value':0})),
        N('exchange',K.EXCHANGE,('filter',)),N('a',K.EXCHANGE,('exchange',)),N('b',K.EXCHANGE,('exchange',)))
    plan=FederatedExecutionPlan('pipeline',nodes,roots=('a','b'),max_remote_calls=1)
    result=StreamingScheduler(None,clients={'local':client}).execute(plan)
    assert result.success and client.calls==1
    assert events.index(('exchange',0))<events.index(('filter',4))
    assert result.root_rows['a']==result.root_rows['b']==tuple(client.rows)
    assert all(n.row_count==5 for n in result.node_results)
    assert result.retention['peak_spill_bytes']==0
    assert result.node_results[1].metadata['intermediate_payload_materialized'] is False


def test_late_pipeline_failure_returns_no_partial_answer_and_metering_survives():
    client=Client([{'v':1},{'v':2},{'bad':3}])
    plan=FederatedExecutionPlan('error',(remote(),N('sum',K.COORDINATOR_GROUP_AGGREGATE,('read',),
        dict(group_by=[],allow_global=True,aggregations={'n':dict(op='sum',field='v')})),N('root',K.EXCHANGE,('sum',))),roots=('root',),max_remote_calls=1)
    result=StreamingScheduler(None,clients={'local':client}).execute(plan)
    assert not result.success and not result.root_rows and result.total_remote_calls==1
    assert result.node_results[1].status is S.ERROR and result.node_results[2].status is S.SKIPPED


def test_promoted_sort_keeps_custom_collation_and_failure_cleans_resources():
    node=N('sort',K.COORDINATOR_SORT_LIMIT,('in',),dict(order_by=[dict(field='v',direction='desc')],limit=3))
    rows=[{'v':i,'payload':'x'*5000} for i in range(40)]
    with SpillWorkspace(RequestControl(),memory_bytes=32768) as work:
        assert list(operate(work,node,[rows]))==list(reversed(rows[-3:]))
        assert work.spilled_stores and work.memory_bytes==work.bytes==0
    with SpillWorkspace(RequestControl(),max_bytes=16384,memory_bytes=32768) as work:
        with pytest.raises(ValueError,match='spill'):list(operate(work,node,[rows]))
        assert work.memory_bytes==work.bytes==0


def test_memory_limit_validation():
    for value in (-1,False,None,1.5):
        with pytest.raises(ValueError):ExecutionLimits(intermediate_memory_bytes=value)


@pytest.mark.parametrize('unique',[False,True])
def test_single_structured_minimum_is_rejected_like_reference(unique):
    node=N('min',K.COORDINATOR_GROUP_AGGREGATE,('in',),dict(group_by=[],allow_global=True,aggregations={'n':dict(op='min',field='v',distinct=unique)}))
    with SpillWorkspace(RequestControl(),memory_bytes=32768) as work:
        with pytest.raises(ValueError,match='scalar'):list(operate(work,node,[[{'v':[1]}]]))
        assert work.bytes==work.memory_bytes==0


@pytest.mark.parametrize('budget',[0,32768,8*1024**2])
def test_unordered_join_elision_requires_injective_schemas(budget):
    from xgap.runtime.scalars import stable_text
    cases=[
        ([{'k':1,'a':2},{'k':1.0,'a':2},{'k':2,'a':3}],[{'k':1.0,'b':4},{'k':1,'b':4},{'k':2,'b':5}]),
        ([{'k':1,'x':1},{'k':1,'x':2}],[{'k':1,'x':3},{'k':1,'x':4}]),
        ([{'k':1,'x':1,'right.x':0},{'k':1,'x':1,'right.x':2}],[{'k':1,'x':3}]),
        ([{'k':1,'a':2},{'k':1,'b':3}],[{'k':1,'b':4}]),
    ]
    for left,right in cases:
        node=N('join',K.COORDINATOR_JOIN,('a','b'),dict(left_on='k',right_on='k'))
        records={'a':R('a',K.REMOTE_QUERY,S.SUCCESS,rows=left),'b':R('b',K.REMOTE_QUERY,S.SUCCESS,rows=right)}
        expected=FederatedScheduler(None)._execute_local(node,records)
        with SpillWorkspace(RequestControl(),memory_bytes=budget) as work:
            actual=list(operate(work,node,[left,right],unordered=True))
            assert sorted(actual,key=stable_text)==sorted(expected.rows,key=stable_text)
            assert work.bytes==work.memory_bytes==0



def test_deep_pipeline_is_partitioned_without_python_recursion_failure():
    client=Client([{'x':1}]);nodes=[remote()]
    for i in range(400):nodes.append(N('n'+str(i),K.EXCHANGE,(nodes[-1].node_id,)))
    plan=FederatedExecutionPlan('deep',tuple(nodes),roots=(nodes[-1].node_id,),max_remote_calls=1)
    result=StreamingScheduler(None,clients={'local':client}).execute(plan)
    assert result.success and result.final_rows==({'x':1},) and client.calls==1
    assert all(n.row_count==1 for n in result.node_results)



@pytest.mark.parametrize('unique',[False,True])
def test_decimal_sum_preserves_full_power_of_two_denominator(unique):
    from decimal import Decimal,localcontext
    with localcontext() as context:
        context.prec=2000
        value={'type':'literal','datatype':'http://www.w3.org/2001/XMLSchema#decimal','value':format(Decimal(1)/Decimal(2**1000),'f')}
    node=N('sum',K.COORDINATOR_GROUP_AGGREGATE,('in',),dict(group_by=[],allow_global=True,aggregations={'n':dict(op='sum',field='v',distinct=unique)}))
    rows=[{'v':value},{'v':value}]
    expected=FederatedScheduler(None)._execute_local(node,{'in':R('in',K.REMOTE_QUERY,S.SUCCESS,rows=rows)})
    with SpillWorkspace(RequestControl(),memory_bytes=32768) as work:
        assert tuple(operate(work,node,[rows]))==expected.rows


@pytest.mark.parametrize('budget',[0,32768,8*1024**2])
@pytest.mark.parametrize('ordered',[False,True])
def test_distinct_spill_buckets_preserve_typed_representatives(budget,ordered,monkeypatch):
    from decimal import Decimal
    from xgap.runtime.scalars import distinct_rows,stable_text
    monkeypatch.setattr('xgap.runtime.spill_rows.distinct_bucket',lambda value:'collision')
    rows=[{'v':v,'payload':'x'*2000} for v in [1.0,2,True,'1',Decimal('1.00'),1,2.0,None]]*4
    expected=distinct_rows(rows)
    # Serialization normalizes Decimal to RDF decimal bindings, as before.
    expected=json.loads(stable_text(expected))
    with SpillWorkspace(RequestControl(),memory_bytes=budget) as work:
        actual=list(distinct(work,rows,ordered_output=ordered))
        assert sorted(actual,key=stable_text)==sorted(expected,key=stable_text)
        if ordered:assert actual==expected
        assert work.bytes==work.memory_bytes==0


def test_row_size_matches_canonical_encoding_and_rejects_invalid_values():
    from decimal import Decimal
    from xgap.runtime.row_size import encoded_row_size
    from xgap.runtime.scalars import stable_text
    rows=[{}, {'a':None,'b':True,'c':False,'d':-12345678901234567890},
        {'escape\\\"\n':'你好\u0000\ud800😀','float':-0.0,'d':Decimal('1.25')},
        {'nested':[{'a':'é'},None,False,Decimal('2.5')],'tuple':(1,2)},
        {1:'fallback'}]
    for row in rows:assert encoded_row_size(row)==len(stable_text(row).encode())
    row={'v':'original'};encoded_row_size(row);row['v']='mutated\n'
    assert encoded_row_size(row)==len(stable_text(row).encode())
    for value in (float('nan'),float('inf'),object()):
        with pytest.raises((ValueError,TypeError)):encoded_row_size({'v':value})


@pytest.mark.parametrize('budget',[0,32768,8*1024**2])
def test_integer_accumulator_promotes_exactly_and_group_keys_remain_typed(budget):
    from decimal import Decimal
    rows=[{'k':i,'v':2**80+i} for i in range(120)]
    rows += [{'k':float(i),'v':Decimal('0.125')} for i in range(120)]
    rows += [{'k':i,'v':-2**80} for i in range(120)]
    rows += [{'k':True,'v':2},{'k':'1','v':3},{'k':None,'v':4}]
    node=N('sum',K.COORDINATOR_GROUP_AGGREGATE,('in',),dict(group_by=['k'],aggregations={'n':dict(op='sum',field='v')}))
    expected=FederatedScheduler(None)._execute_local(node,{'in':R('in',K.REMOTE_QUERY,S.SUCCESS,rows=rows)})
    with SpillWorkspace(RequestControl(),memory_bytes=budget) as work:
        assert tuple(operate(work,node,[rows]))==expected.rows
        assert work.peak_memory_bytes<=budget and work.bytes==work.memory_bytes==0


def test_replay_store_omits_unused_index_and_adds_it_when_needed():
    with SpillWorkspace(RequestControl(),memory_bytes=32768) as work:
        store=work.store(buffered=False);store.append({'v':1})
        assert not list(store.db.execute("SELECT name FROM sqlite_master WHERE type='index'"))
        store.append({'v':2},lookup='two')
        assert list(store.select('SELECT payload FROM rows WHERE lookup=?',('two',)))==[{'v':2}]
        for i in range(80):store.append({'v':i,'wide':'x'*2000},lookup=str(i))
        assert store.in_memory is False
        assert list(store.select('SELECT payload FROM rows WHERE lookup=?',('two',)))==[{'v':2}]
        store.close();assert work.bytes==work.memory_bytes==0
