"""Differential algebra regressions and bounded intermediate storage, entirely local."""
from dataclasses import replace
from decimal import Decimal
import io,json,itertools,random
import pytest
from xgap.backends.request_control import RequestControl
from xgap.runtime.spill_rows import SpillWorkspace
from xgap.runtime.spill_operators import operate
from xgap.runtime.contracts import RuntimeNode,RuntimeNodeKind as K,RuntimeNodeResult,RuntimeNodeStatus as S
from xgap.runtime.scheduler import FederatedScheduler


def compare(kind,p,inputs):
    node=RuntimeNode('out',kind,tuple(str(i) for i in range(len(inputs))),p)
    results={str(i):RuntimeNodeResult(str(i),K.REMOTE_QUERY,S.SUCCESS,rows=tuple(rows)) for i,rows in enumerate(inputs)}
    reference=FederatedScheduler(None)._execute_local(node,results)
    with SpillWorkspace(RequestControl()) as work:
        if reference.status is S.ERROR:
            with pytest.raises((ValueError,KeyError,TypeError)):tuple(operate(work,node,inputs))
        else:assert tuple(operate(work,node,inputs))==reference.rows
        assert work.bytes==0


def test_group_sort_join_and_projection_typed_equivalence():
    rows=[dict(k=k,v=v) for k in [None,1,1.0,'1',True] for v in [None,1,1.0,2,-1]]*2
    for distinct in [False,True]:
        specs={op:dict(op=op,field='v',distinct=distinct) for op in ['count','sum','min','max']}
        specs['rows']=dict(op='count',distinct=distinct)
        for groups in [[],['k']]:compare(K.COORDINATOR_GROUP_AGGREGATE,dict(group_by=groups,allow_global=True,aggregations=specs),[rows])
    for direction,nulls in itertools.product(['asc','desc'],['first','last']):
        compare(K.COORDINATOR_SORT_LIMIT,dict(order_by=[dict(field='k',direction=direction,nulls=nulls)],limit=7),[rows])
    compare(K.COORDINATOR_JOIN,dict(left_on='k',right_on='k'),[rows,rows])
    compare(K.COORDINATOR_SEMI_JOIN,dict(left_on='k',right_on='k'),[rows,rows])
    compare(K.MERGE,{},[rows,rows])
    compare(K.COORDINATOR_FILTER,dict(condition=dict(op='eq',field='v',value=1)),[rows])
    compare(K.COORDINATOR_ROW_PROJECT,dict(projections={'x':dict(kind='field',field='v')}),[rows])
    compare(K.COORDINATOR_GROUP_AGGREGATE,dict(group_by=[],allow_global=True,aggregations={'x':dict(op='sum',field='v',distinct=True)}),[[{'v':Decimal('1.00')},{'v':1.0},{'v':2}]])


def test_path_selectors_and_recursive_modes_match_finite_algebra():
    rows=[{'path':p} for p in [['a'],['a','e1','b'],['b','e2','c'],['c','e3','a'],['a','e4','b']]]
    for mode in ['WALK','TRAIL','SIMPLE','ACYCLIC','SHORTEST']:
        compare(K.COORDINATOR_PATH_COMPOSE,dict(operation='recursive',mode=mode,max_depth=3,max_edges=5),[rows])
    compare(K.COORDINATOR_PATH_COMPOSE,dict(operation='join',max_edges=3),[rows,rows])
    candidates=rows+[{'path':['a','e1','b','e2','c']},{'path':['a','e5','c']}]
    for selector in ['ALL','ANY','ANY_K','ANY_SHORTEST','ALL_SHORTEST','SHORTEST_K','SHORTEST_K_GROUP']:
        for shortest in [True,False]:
            p=dict(input_model='paths',max_edges=4,selector=selector,recursive_shortest=shortest)
            if '_K' in selector:p['k']=2
            compare(K.COORDINATOR_PATH_SELECT,p,[candidates])


def test_disk_limit_and_failure_cleanup():
    with SpillWorkspace(RequestControl(),max_bytes=16384) as work:
        with pytest.raises(ValueError,match='spill'):
            with __import__('xgap.runtime.spill_rows',fromlist=['managed']).managed(work) as store:
                for _ in range(100):store.append({'x':'a'*10000})
        assert not work.stores and work.bytes==0


def test_native_envelope_spills_rows_and_retains_error_atomicity(monkeypatch):
    from test_neo4j_http_errors import _client
    from xgap.infrastructure.runtime import QueryArtifact
    from test_streaming_backend_control import Chunked
    client=_client();control=RequestControl();seen=[]
    data=dict(results=[dict(columns=['x'],data=[dict(row=[i]) for i in range(400)])],errors=[])
    monkeypatch.setattr('urllib.request.urlopen',lambda *a,**k:Chunked(json.dumps(data).encode(),65536))
    with SpillWorkspace(control) as work:
        client.execute_stream(QueryArtifact('q','cypher','RETURN x'),seen.append,control,work)
        assert seen==[{'x':i} for i in range(400)] and work.peak_bytes>0 and work.bytes==0
        data['errors']=[dict(message='transaction failed')];seen.clear()
        with pytest.raises(ValueError,match='transaction failed'):client.execute_stream(QueryArtifact('q','cypher','RETURN x'),seen.append,control,work)
        assert not seen and work.bytes==0


def test_stream_scheduler_fanout_spill_budget_and_actual_calls():
    from xgap.runtime.stream_scheduler import StreamingScheduler
    from xgap.runtime.execution_limits import ExecutionLimits
    from xgap.runtime.contracts import FederatedExecutionPlan
    from test_scheduler_progress import remote
    class Client:
        def __init__(self):self.calls=0
        def execute_stream(self,a,emit,control,workspace):
            self.calls+=1
            for i in range(50):emit({'x':i,'payload':'a'*2000})
    client=Client()
    nodes=(remote('read'),RuntimeNode('a',K.COORDINATOR_ROW_PROJECT,('read',),dict(projections={'x':dict(kind='field',field='x')})),
        RuntimeNode('b',K.COORDINATOR_GROUP_AGGREGATE,('read',),dict(group_by=[],allow_global=True,aggregations={'n':dict(op='count')})))
    plan=FederatedExecutionPlan('fanout',nodes,roots=('a','b'),max_remote_calls=1)
    result=StreamingScheduler(None,clients={'fake':client}).execute(plan)
    assert result.success and client.calls==result.total_remote_calls==1
    assert result.root_rows['b']==({'n':50},) and len(result.root_rows['a'])==50
    assert result.node_results[0].rows is None and result.node_results[0].row_count==50
    failed=StreamingScheduler(None,clients={'fake':client},limits=ExecutionLimits(max_spill_bytes=16384)).execute(plan)
    assert not failed.success and failed.total_remote_calls==1
    assert 'spill' in failed.node_results[0].error and not failed.root_rows


def test_stream_scheduler_deadline_retains_accounting():
    from xgap.runtime.stream_scheduler import StreamingScheduler
    from xgap.runtime.execution_limits import ExecutionLimits
    from xgap.runtime.contracts import FederatedExecutionPlan
    from test_scheduler_progress import remote
    from threading import Event
    done=Event()
    class Client:
        def execute_stream(self,a,emit,control,workspace):
            with control.cancellation(lambda:done.set() or {'backend_termination_confirmed':True}):
                assert done.wait(2)
                control.check()
    result=StreamingScheduler(None,clients={'fake':Client()},limits=ExecutionLimits(dispatch_timeout_s=.05)).execute(
        FederatedExecutionPlan('timeout',(remote('a'),),roots=('a',),max_remote_calls=1))
    assert not result.success and result.total_remote_calls==1 and not result.final_rows
    assert result.retention['backend_cancellation'][0]['evidence']['backend_termination_confirmed']


def test_remaining_unary_operators_and_collection_semijoin():
    rows=[{'x':'a','v':1},{'x':'b','v':2},{'x':'a','v':1}]
    compare(K.EXCHANGE,{},[rows])
    compare(K.ALIGN,dict(field='x',output_field='id',mapping={'a':'A'},on_missing='drop'),[rows])
    compare(K.PROJECT,dict(fields=['x']),[rows])
    compare(K.COORDINATOR_SEMI_JOIN,dict(left_on='x',right_on='x',left_value_mode='collection'),
        [[{'x':['a','b']},{'x':[]},{'x':['c']}],rows])
    compare(K.NORMALIZE_NODE_BINDINGS,dict(language='cypher',entity_field='id',identity_property='id',resource_namespace='urn:test:',scalar_fields=['v']),
        [[{'entity':{'id':'a'},'v':1},{'entity':{'id':'a'},'v':1}]])
    compare(K.NORMALIZE_NODE_BINDINGS,dict(language='sparql',entity_field='id',identity_property='id',resource_namespace='urn:test:',scalar_fields=['v']),
        [[{'entity':{'type':'uri','value':'urn:test:a'},'v':{'type':'literal','value':'1','datatype':'http://www.w3.org/2001/XMLSchema#integer'}}]])


def test_blocking_sql_operators_observe_cancellation_before_next_output_row():
    import sqlite3
    control=RequestControl()
    with SpillWorkspace(control) as workspace:
        store=workspace.store();control.cancel()
        with pytest.raises(sqlite3.OperationalError,match='interrupted'):
            store.db.execute('WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<100000000) SELECT SUM(x) FROM n').fetchone()


def test_decimal_exponent_sum_does_not_depend_on_integer_string_limit():
    value={'type':'literal','datatype':'http://www.w3.org/2001/XMLSchema#decimal','value':'0.'+'0'*4500+'1'}
    compare(K.COORDINATOR_GROUP_AGGREGATE,dict(group_by=[],allow_global=True,aggregations={'n':dict(op='sum',field='v')}),[[{'v':value},{'v':value}]])
