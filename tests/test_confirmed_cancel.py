"""Database control protocol regressions; no network listeners or remote calls."""
import io,json
import pytest
from xgap.backends.request_control import RequestControl,controlled_call
from xgap.infrastructure.runtime import QueryArtifact
from xgap.backends.confirmed_cancel import fuseki_query


class Response(io.BytesIO):
    status=200
    def __init__(self,body):super().__init__(json.dumps(body).encode())


def test_neo4j_owned_handle_rollback_acknowledgement_and_metering(monkeypatch):
    from test_neo4j_http_errors import _client
    client=_client();control=RequestControl();control.database_cancellation=True;calls=[]
    base=f'{client.http_url}/db/{client.database}/tx'
    class Opener:
        def open(self,request,timeout):
            calls.append((request.method,request.full_url))
            if request.method=='DELETE':return Response({'errors':[]})
            return Response({'commit':base+'/71/commit','errors':[]})
    monkeypatch.setattr('urllib.request.build_opener',lambda *a:Opener())
    def query(request,timeout):
        assert request.full_url==base+'/71'
        control.cancel()
        raise TimeoutError('interrupted after database cancellation')
    monkeypatch.setattr('urllib.request.urlopen',query)
    report=controlled_call(control,client.execute,QueryArtifact('q','cypher','RETURN 1'))
    assert not report.success
    assert calls==[('POST',base),('DELETE',base+'/71')]
    assert control.lifecycle_calls==2
    assert control.receipts[0]['evidence']['backend_termination_confirmed'] is True


def test_neo4j_success_commits_once_and_failure_rolls_back(monkeypatch):
    from test_neo4j_http_errors import _client
    client=_client();base=f'{client.http_url}/db/{client.database}/tx';calls=[]
    class Opener:
        def open(self,request,timeout):
            calls.append((request.method,request.full_url))
            return Response({'errors':[],**({'commit':base+'/9/commit'} if request.full_url==base else {})})
    monkeypatch.setattr('urllib.request.build_opener',lambda *a:Opener())
    for success in [True,False]:
        calls.clear();control=RequestControl();control.database_cancellation=True
        monkeypatch.setattr('urllib.request.urlopen',lambda *a,**kw:Response({'results':[{'columns':['x'],'data':[{'row':[1]}]}],'errors':[] if success else [{'message':'invalid'}]}))
        report=controlled_call(control,client.execute,QueryArtifact('q','cypher','RETURN 1'))
        assert report.success is success
        assert calls==[('POST',base),('POST',base+'/9/commit') if success else ('DELETE',base+'/9')]
        assert control.lifecycle_calls==2


def test_fuseki_ack_requires_matching_owned_handle_and_completed_lifecycle(monkeypatch):
    from test_fuseki_http_errors import _client
    c=_client();handle='a'*64;calls=[];confirmed=False
    class Opener:
        def open(self,request,timeout):
            data=json.loads(request.data);calls.append(data['action'])
            return Response({'handle':handle,**({'backend_termination_confirmed':confirmed} if data['action']=='cancel' else {})})
    monkeypatch.setattr('urllib.request.build_opener',lambda *a:Opener())
    control=RequestControl()
    with fuseki_query(c,control):pass
    assert calls==['register','cancel'] and control.receipts[0]['status']=='failed'
    confirmed=True;control=RequestControl()
    with fuseki_query(c,control):pass
    assert control.receipts[0]['evidence']['backend_termination_confirmed']


def test_jena_owned_cancellation_in_process(tmp_path):
    """Optional local integration: compile extension + exercise actual Jena abort."""
    import os,subprocess
    from pathlib import Path
    jar=os.environ.get('XGAP_LOCAL_FUSEKI_JAR')
    if not jar:pytest.skip('Set XGAP_LOCAL_FUSEKI_JAR to run in-process Jena integration')
    root=Path(__file__).resolve().parents[1]/'services/fuseki-cancel'
    files=list(root.glob('src/**/*.java'))+list(root.glob('test/**/*.java'))
    subprocess.run(['javac','--release','17','-cp',jar,'-d',str(tmp_path),*map(str,files)],check=True,timeout=60)
    subprocess.run(['java','-cp',str(tmp_path)+os.pathsep+jar,'xgap.fuseki.OwnedQueriesTest'],check=True,timeout=30)
