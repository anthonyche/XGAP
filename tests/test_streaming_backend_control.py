"""In-process transport doubles: no remote databases, jobs, or model calls."""
import io
import json
import time
from threading import Event
import pytest
from xgap.backends.json_stream import JsonStream,read_json
from xgap.backends.request_control import RequestControl,controlled_call
from xgap.runtime.execution_limits import ExecutionLimits
from xgap.runtime.scheduler import FederatedScheduler
from xgap.tools.backends import NativeBackendPlugin,BackendPluginRegistry,BackendInvokeTool
from xgap.infrastructure.runtime import ExecutionReport
from test_scheduler_progress import remote
from xgap.runtime.contracts import FederatedExecutionPlan


class Chunked(io.BytesIO):
    def __init__(self,data,chunk=7):super().__init__(data);self.chunk=chunk;self.requests=[]
    def read(self,n=-1):
        assert 0<n<=65536
        self.requests.append(n)
        return super().read(min(n,self.chunk))


@pytest.mark.parametrize('chunk',[1,2,7,65536])
def test_incremental_json_keeps_unicode_numbers_and_escapes(chunk):
    value={'results':[{'columns':['x'],'data':[{'row':[i,'雪\\\"😀',True,None,-3.14159e33]} for i in range(200)]}], 'errors':[]}
    raw=json.dumps(value,ensure_ascii=False).encode()
    parser=JsonStream(Chunked(raw,chunk))
    assert parser.read()==value
    assert parser.bytes==len(raw)
    assert parser.peak_buffer<=65536+100


@pytest.mark.parametrize('raw',[b'{"a":',b'[1,]',b'{"a":1} false',b'{"a":"truncated',b'{"a":NaN}'])
def test_malformed_or_trailing_json_never_becomes_partial_success(raw):
    with pytest.raises(ValueError):JsonStream(Chunked(raw)).read()


def test_response_budget_stops_transport_early_without_returning_prefix():
    raw=json.dumps({'results':[{'value':'x'*100} for _ in range(1000)]}).encode()
    stream=Chunked(raw,65536)
    control=RequestControl(max_response_bytes=4096)
    with pytest.raises(ValueError,match='byte budget'):
        controlled_call(control,read_json,stream)
    assert control.response_bytes==4097
    assert stream.tell()==4097<len(raw)/20


def test_scheduler_cancels_owned_adapter_invocation_and_keeps_actual_call():
    started=Event();cancelled=Event()
    class Client:
        def execute_controlled(self,artifact,control):
            def cancel():cancelled.set();return dict(query_id='owned',acknowledged=True)
            with control.cancellation(cancel):
                started.set()
                assert cancelled.wait(2), 'scheduler did not cancel owned backend work'
                return ExecutionReport('fake',artifact.artifact_id,artifact.language,False,error='cancelled')
    registry=BackendPluginRegistry();registry.register(NativeBackendPlugin('fake',Client()))
    plan=FederatedExecutionPlan('cancel',(remote('a'),),roots=('a',),max_remote_calls=1)
    result=FederatedScheduler(BackendInvokeTool(registry),limits=ExecutionLimits(dispatch_timeout_s=.1)).execute(plan)
    assert started.is_set() and cancelled.is_set() and not result.success
    assert result.total_remote_calls==1
    assert result.retention['backend_cancellation'][0]['evidence']['acknowledged']
    assert result.elapsed_ms<1500


def test_controls_do_not_cancel_another_request_and_no_double_callback():
    a,b=RequestControl(),RequestControl();seen=[]
    with a.cancellation(lambda:seen.append('a')),b.cancellation(lambda:seen.append('b')):
        a.cancel();a.cancel()
        assert seen==['a'] and not b.cancelled.is_set()
    b.cancel();assert seen==['a']


def test_http_deadline_and_fuseki_server_timeout_forwarding(monkeypatch):
    from test_fuseki_http_errors import _client
    from xgap.infrastructure.runtime import QueryArtifact
    import urllib.parse
    calls=[]
    def opened(request,timeout):
        calls.append((urllib.parse.parse_qs(request.data.decode()),timeout))
        return Chunked(b'{"head":{"vars":["x"]},"results":{"bindings":[{"x":{"type":"literal","value":"1"}}]}}')
    monkeypatch.setattr('urllib.request.urlopen',opened)
    report=controlled_call(RequestControl(deadline=time.perf_counter()+5),_client().execute,QueryArtifact('q','sparql','SELECT ?x WHERE {}'))
    assert report.success and report.rows==[{'x':'1'}]
    assert 0<calls[0][1]<=5 and calls[0][0]['timeout']==['5']


def test_native_http_response_limit_fails_with_no_partial_answers(monkeypatch):
    from test_neo4j_http_errors import _client
    from xgap.infrastructure.runtime import QueryArtifact
    streams=[]
    def opened(request,timeout):
        stream=Chunked(json.dumps(dict(results=[dict(columns=['x'],data=[dict(row=['x'*100]) for _ in range(100)])],errors=[])).encode(),65536)
        streams.append(stream);return stream
    monkeypatch.setattr('urllib.request.urlopen',opened)
    result=controlled_call(RequestControl(max_response_bytes=1000),_client().execute,QueryArtifact('q','cypher','RETURN 1'))
    assert not result.success and result.rows==[] and 'byte budget' in result.error
    assert streams[0].closed


def test_cancel_interrupts_blocked_owned_socket_read_without_claiming_server_termination():
    import socket
    from types import SimpleNamespace
    from concurrent.futures import ThreadPoolExecutor
    ready=Event();control=RequestControl()
    reader,writer=socket.socketpair()
    class Response:
        fp=SimpleNamespace(raw=SimpleNamespace(_sock=reader))
        def read(self,n):ready.set();return reader.recv(n)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(controlled_call,control,read_json,Response())
            assert ready.wait(2)
            control.cancel()
            with pytest.raises(TimeoutError):future.result(timeout=2)
        assert control.receipts[0]['evidence']==dict(transport_interrupted=True,backend_termination_confirmed=False)
    finally:reader.close();writer.close()


def test_exception_signals_cancellation_before_owned_work_is_drained():
    from xgap.backends.request_control import cancel_on_error
    c=RequestControl();seen=[]
    with c.cancellation(lambda:seen.append('cancelled')):
        with pytest.raises(KeyboardInterrupt):
            with cancel_on_error(c):raise KeyboardInterrupt
    assert seen==['cancelled']
