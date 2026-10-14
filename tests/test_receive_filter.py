"""Private reception filtering: exact results and late-error atomicity, no servers."""
import io
import json
from dataclasses import replace
from decimal import Decimal
import pytest
from xgap.runtime.contracts import RuntimeNode as N,RuntimeNodeKind as K,RuntimeNodeStatus as S,FederatedExecutionPlan
from xgap.runtime.stream_scheduler import StreamingScheduler
from xgap.runtime.execution_limits import ExecutionLimits
from xgap.runtime.scalars import stable_text
from test_adaptive_execution import Client,remote


def plan(condition=None,source=None,tail=(),roots=None):
    return FederatedExecutionPlan('receive',(source or remote(),N('filter',K.COORDINATOR_FILTER,('read',),
        {'condition':condition or {'op':'lt','field':'v','value':2}}),*tail),roots=roots or ('filter',),max_remote_calls=2)


def execute(p,client,**kwargs):
    return StreamingScheduler(None,clients={'local':client},**kwargs).execute(p)


def by_id(r):return {n.node_id:n for n in r.node_results}


@pytest.mark.parametrize('budget',[0,32768,8*1024**2])
def test_exact_typed_answers_and_raw_accounting(budget):
    rows=[{'v':v,'payload':'x'*300} for v in [1,1.,Decimal('1.00'),True,'1',None,2,3]]
    p=plan({'op':'eq','field':'v','value':1})
    limits=ExecutionLimits(intermediate_memory_bytes=budget)
    old=execute(p,Client(rows),pipeline=False,limits=limits)
    new=execute(p,Client(rows),limits=limits)
    assert old.success and new.success and old.final_rows==new.final_rows
    assert [(n.node_id,n.row_count,n.output_bytes) for n in old.node_results]==[(n.node_id,n.row_count,n.output_bytes) for n in new.node_results]
    assert new.total_remote_calls==1
    assert by_id(new)['read'].metadata['normalized_raw_rows_staged']==0
    assert new.retention['peak_intermediate_accounted_bytes']<=budget


@pytest.mark.parametrize('rows,condition',[
    ([{'v':(1,2)},{'v':(2,3)}],{'op':'is_not_null','field':'v'}),
    ([{1:'x','v':1},{1:'y','v':2}],{'op':'eq','field':'v','value':1}),
    ([{'v':0,'bad':object()}],{'op':'eq','field':'v','value':1}),
    ([{'v':0,'bad':float('nan')}],{'op':'eq','field':'v','value':1}),
])
def test_normalization_and_invalid_rejected_values_match_spool(rows,condition):
    old=execute(plan(condition),Client(rows),pipeline=False)
    new=execute(plan(condition),Client(rows))
    assert old.success==new.success and old.final_rows==new.final_rows
    assert [n.status for n in old.node_results]==[n.status for n in new.node_results]


@pytest.mark.parametrize('mode',['source-root','fanout','registered-budget'])
def test_shared_raw_outputs_and_registered_gate_keep_original_path(mode):
    p=plan(roots=('read','filter') if mode=='source-root' else ('filter','other') if mode=='fanout' else None,
        tail=(N('other',K.EXCHANGE,('read',)),) if mode=='fanout' else ())
    kwargs={'limits':ExecutionLimits(max_registered_bytes=5)} if mode=='registered-budget' else {}
    result=execute(p,Client([{'v':0},{'v':3}]),**kwargs)
    assert by_id(result)['read'].metadata.get('stream_transport')!='validated-reception-filter'
    if mode=='registered-budget':assert not result.success
    else:assert result.success


def test_chained_filters_and_fanout_publish_once_after_source_returns():
    ended=[]
    class Mutating(Client):
        def execute_stream(self,a,emit,control,workspace):
            row={'v':0};emit(row);row['v']=1;emit(row);row['v']=99
            ended.append(True)
    p=plan(tail=(N('second',K.COORDINATOR_FILTER,('filter',),{'condition':{'op':'eq','field':'v','value':1}}),
        N('a',K.EXCHANGE,('second',)),N('b',K.EXCHANGE,('second',))),roots=('a','b'))
    result=execute(p,Mutating([]))
    assert ended and result.success and result.root_rows=={'a':({'v':1},),'b':({'v':1},)}


def test_predicate_error_drains_but_late_source_error_takes_precedence():
    for late in (False,True):
        visited=[]
        class Broken(Client):
            def execute_stream(self,a,emit,control,workspace):
                for row in [{'v':0},{'bad':1},{'v':3}]:visited.append(row);emit(row)
                if late:raise ValueError('late source error')
        r=execute(plan(),Broken([]));nodes=by_id(r)
        assert len(visited)==3 and not r.success and not r.root_rows and r.total_remote_calls==1
        if late:assert nodes['read'].status is S.ERROR and nodes['filter'].status is S.SKIPPED
        else:
            assert nodes['read'].status is S.SUCCESS and nodes['filter'].status is S.ERROR
            assert nodes['read'].row_count==3 and 'missing field' in nodes['filter'].error


def native(monkeypatch,engine,body,*,condition=None,limits=None,parameters=None):
    from test_neo4j_http_errors import _client as neo
    from test_fuseki_http_errors import _client as rdf
    lifecycle=[];read=[]
    class Body(io.BytesIO):
        def read(self,n=-1):
            assert 0<n<=65536
            data=super().read(min(n,16384));read.append(len(data));return data
    def control(c,url,method,payload,headers,timeout):
        lifecycle.append(method)
        return {'errors':[],**({'commit':url+'/123/commit'} if url.endswith('/tx') else {})}
    monkeypatch.setattr('xgap.backends.confirmed_cancel.lifecycle',control)
    monkeypatch.setattr('urllib.request.urlopen',lambda *a,**kw:Body(body))
    source=replace(remote(),parameters={'backend_id':'local','artifact':{'artifact_id':'read','language':engine,'text':'fixture','parameters':parameters or {}}})
    result=execute(plan(condition,source),neo() if engine=='cypher' else rdf(),limits=limits)
    return result,sum(read),lifecycle


def envelope(engine,rows,headers_first=True):
    if engine=='cypher':
        parts=[('columns',['v','payload']),('data',[{'row':[r['v'],r.get('payload','')]} for r in rows])]
        return {'results':[dict(parts if headers_first else reversed(parts))],'errors':[]}
    parts=[('head',{'vars':['v','payload']}),('results',{'bindings':[
        {'v':{'type':'literal','value':str(r['v'])},'payload':{'type':'literal','value':r.get('payload','')}} for r in rows]})]
    return dict(parts if headers_first else reversed(parts))


@pytest.mark.parametrize('engine',['cypher','sparql'])
@pytest.mark.parametrize('headers_first',[False,True])
def test_native_response_header_order_exact_and_bounded(monkeypatch,engine,headers_first):
    rows=[{'v':i,'payload':'x'*1200} for i in range(1200)]
    body=json.dumps(envelope(engine,rows,headers_first)).encode()
    condition={'op':'eq','field':'v','value':0 if engine=='cypher' else '0'}
    result,read,life=native(monkeypatch,engine,body,condition=condition,limits=ExecutionLimits(intermediate_memory_bytes=32768))
    assert result.success and len(result.final_rows)==1 and read==len(body)
    source=by_id(result)['read'];assert source.row_count==1200
    assert source.metadata['native_arrays_filtered']==int(headers_first)
    assert source.metadata['native_arrays_spooled']==int(not headers_first)
    assert result.retention['peak_intermediate_accounted_bytes']<=32768
    if headers_first:assert result.retention['peak_spill_bytes']==0
    else:assert result.retention['peak_spill_bytes']>0
    if engine=='cypher':assert life==['POST','POST']


@pytest.mark.parametrize('engine',['cypher','sparql'])
@pytest.mark.parametrize('suffix',[b' garbage',b'\xff',b' {}'])
def test_all_rejected_still_validate_tail(monkeypatch,engine,suffix):
    raw=json.dumps(envelope(engine,[{'v':1}])).encode()+suffix
    result,read,life=native(monkeypatch,engine,raw,condition={'op':'eq','field':'v','value':-1})
    assert not result.success and not result.root_rows and result.total_remote_calls==1
    assert by_id(result)['read'].status is S.ERROR
    if engine=='cypher':assert life==['POST','DELETE']


def test_late_backend_error_and_duplicate_key_discard_private_prefix(monkeypatch):
    value=envelope('cypher',[{'v':0}]);value['errors']=[{'message':'late error'}]
    for body in (json.dumps(value).encode(),b'{"results":[{"columns":["v"],"data":[{"row":[0]}]}],"errors":[],"errors":[]}'):
        result,read,life=native(monkeypatch,'cypher',body)
        assert not result.success and not result.root_rows
        assert by_id(result)['filter'].status is S.SKIPPED
        assert life==['POST','DELETE']


def test_discarded_native_rows_still_checked_and_multi_result_order(monkeypatch):
    value=envelope('cypher',[{'v':0}]);value['results'][0]['data'].append({'row':None})
    result,read,life=native(monkeypatch,'cypher',json.dumps(value).encode())
    assert not result.success and not result.root_rows and 'TypeError' in by_id(result)['read'].error
    first=envelope('cypher',[{'v':1}])['results'][0]
    second=envelope('cypher',[{'v':0}],False)['results'][0]
    third=envelope('cypher',[{'v':1}])['results'][0]
    result,read,life=native(monkeypatch,'cypher',json.dumps({'results':[first,second,third],'errors':[]}).encode())
    assert result.success and [r['v'] for r in result.final_rows]==[1,0,1]
    assert by_id(result)['read'].metadata['native_arrays_spooled']==2


def test_all_rejected_native_response_still_has_byte_budget(monkeypatch):
    body=json.dumps(envelope('cypher',[{'v':3,'payload':'x'*1000} for _ in range(100)])).encode()
    result,read,life=native(monkeypatch,'cypher',body,limits=ExecutionLimits(max_response_bytes=2000))
    assert not result.success and not result.root_rows and 'byte budget' in by_id(result)['read'].error
    assert read==2001 and life==['POST','DELETE']


def test_cancelled_private_prefix_never_reaches_root():
    class Cancelled(Client):
        def execute_stream(self,a,emit,control,workspace):
            emit({'v':0});control.cancel();emit({'v':1})
    result=execute(plan(),Cancelled([]))
    assert not result.success and not result.root_rows and result.total_remote_calls==1


def test_relationship_budget_precedes_filter_and_detects_overfetch():
    import hashlib
    from xgap.runtime.retrieval_budget import PROFILE
    text='fixture\nLIMIT 3'
    source=replace(remote(),parameters={'backend_id':'local','artifact':{'artifact_id':'read','language':'sparql','text':text,
        'parameters':{'compiler':'semantic_edge_match_v1','retrieval_budget':{'profile':PROFILE,'rows':2,'fetch_rows':3,'template_sha256':hashlib.sha256(text.encode()).hexdigest()}}}})
    for rows in ([{'v':3},{'v':0},{'v':1}],[{'v':3},{'v':0},{'v':1},{'v':1}]):
        old=execute(plan(source=source),Client(rows),pipeline=False)
        new=execute(plan(source=source),Client(rows))
        assert old.success==new.success and old.final_rows==new.final_rows
        if new.success:
            assert new.final_rows==({'v':0},) and by_id(new)['read'].row_count==2
            assert by_id(new)['read'].metadata['retrieval_budget']==by_id(old)['read'].metadata['retrieval_budget']


def test_typed_rdf_rejected_row_still_validates_term(monkeypatch):
    from xgap.backends.rdf_terms import RDF_TERMS_V1
    value=envelope('sparql',[{'v':0},{'v':3}])
    value['results']['bindings'][1]['payload']={'type':'unknown','value':'bad'}
    result,read,life=native(monkeypatch,'sparql',json.dumps(value).encode(),parameters={'rdf_result_encoding':RDF_TERMS_V1})
    assert not result.success and not result.root_rows
    assert by_id(result)['read'].status is S.ERROR


def test_public_native_emit_never_receives_prefix_before_validation(monkeypatch):
    from test_neo4j_http_errors import _client
    from xgap.infrastructure.runtime import QueryArtifact
    from xgap.backends.request_control import RequestControl
    from xgap.runtime.spill_rows import SpillWorkspace
    value=envelope('cypher',[{'v':0}]);value['errors']=[{'message':'late error'}]
    monkeypatch.setattr('urllib.request.urlopen',lambda *a,**kw:io.BytesIO(json.dumps(value).encode()))
    rows=[];control=RequestControl()
    with SpillWorkspace(control) as workspace:
        with pytest.raises(ValueError,match='late error'):
            _client().execute_stream(QueryArtifact('q','cypher','fixture'),rows.append,control,workspace)
    assert rows==[]


@pytest.mark.parametrize('empty',[False,True])
def test_filter_after_binding_query_preserves_bound_calls(empty):
    class Bound(Client):
        def execute_stream(self,a,emit,control,workspace):
            self.calls+=1
            if a.artifact_id=='seed':
                if not empty:emit({'key':7})
            else:
                assert a.parameters['ids']==[7]
                emit({'v':0});emit({'v':3})
    seed=remote('seed')
    source=N('read',K.REMOTE_BIND_QUERY,('seed',),{**remote().parameters,'bind_field':'key','parameter':'ids','max_bindings':4})
    p=plan();p=replace(p,nodes=(seed,source,*p.nodes[1:]))
    new=execute(p,Bound([]));old=execute(p,Bound([]),pipeline=False)
    assert new.success and new.final_rows==old.final_rows
    assert new.total_remote_calls==old.total_remote_calls==(1 if empty else 2)
    assert by_id(new)['read'].metadata['binding_count']==int(not empty)


def test_parallel_receptions_keep_filter_state_request_local():
    from threading import Barrier
    gate=Barrier(2)
    class Parallel(Client):
        def execute_stream(self,a,emit,control,workspace):
            gate.wait(timeout=2)
            for i in range(10):emit({'v':i})
    nodes=tuple(remote(name) for name in ('a','b'))+tuple(
        N('filter'+name,K.COORDINATOR_FILTER,(name,),{'condition':{'op':'eq','field':'v','value':v}})
        for name,v in [('a',1),('b',2)])
    p=FederatedExecutionPlan('parallel',nodes,roots=('filtera','filterb'),max_remote_calls=2,max_parallelism=2)
    r=execute(p,Parallel([]))
    assert r.success and r.total_remote_calls==2
    assert r.root_rows=={'filtera':({'v':1},),'filterb':({'v':2},)}
