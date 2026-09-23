"""Only new per-phase observation/finalization risks; no model or database calls."""
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from xgap.experiments.campaign_source_observer import CampaignSourceObserver, SourceObservationBudget
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.source_failure_classification import classify_source_failure


@contextmanager
def source():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length',0)))
            payload=b'abcdefghij';self.send_response(503 if self.path=='/error' else 200)
            self.send_header('Content-Length',str(len(payload)+(2 if self.path=='/truncated' else 0)))
            self.end_headers();self.wfile.write(payload)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01});thread.start()
    try:yield 'http://127.0.0.1:'+str(server.server_port)
    finally:server.shutdown();server.server_close();thread.join()


@contextmanager
def observer(root,**limits):
    with source() as upstream:
        proxy=CampaignSourceObserver({'/ok':upstream+'/ok','/error':upstream+'/error','/truncated':upstream+'/truncated'},root,
            budget=replace(SourceObservationBudget(),**limits))
        try:yield proxy
        finally:proxy.close()


def call(proxy,path='/ok'):
    try:
        with urlopen(Request(proxy.base_url+path,data=b'ASK {}',headers={'Content-Type':'application/sparql-query'}),timeout=3) as r:
            return r.status,r.read()
    except HTTPError as e:return e.code,e.read()


def test_opt_in_connection_close_keeps_request_and_response_bytes(tmp_path):
    import http.client
    from urllib.parse import urlsplit
    with source() as upstream:
        proxy=CampaignSourceObserver({'/ok':upstream+'/ok'},tmp_path/'observer',
            budget=SourceObservationBudget(),downstream_keepalive=False)
        try:
            proxy.set_phase('client-compatibility');url=urlsplit(proxy.base_url)
            client=http.client.HTTPConnection(url.hostname,url.port,timeout=3)
            for _ in range(2):
                client.request('POST','/ok',b'ASK {}',{'Content-Type':'application/sparql-query'})
                response=client.getresponse()
                assert response.will_close and response.getheader('Connection')=='close'
                assert response.status==200 and response.read()==b'abcdefghij'
                assert client.sock is None
            client.close();sealed=proxy.seal_phase(proxy.phase)
            assert sealed['forwarded_requests']==2 and sealed['failed_requests']==0
            assert 'Connection: close' in sealed['transport_profile']
            for i in range(2):
                assert json.loads((proxy.root/f'{i:04}-intent.json').read_text())['query']=='ASK {}'
        finally:proxy.close()


def release(proxy,root):
    sealed=proxy.seal_phase(proxy.phase)
    pin=write_once(root/'outcome.json',{'source_observations':sealed})
    proxy.release_phase(proxy.phase,pin)
    return sealed


def test_admission_outcome_persists_phase_identity_before_next_case(tmp_path):
    with observer(tmp_path/'source',max_calls=1) as p:
        for i in range(2):
            phase='admission:'+str(i);p.set_phase(phase)
            assert call(p)==(200,b'abcdefghij')
            row,pin=p.persist_outcome(phase,tmp_path/f'case-{i}.json',{'case_id':str(i),'answer_em':1})
            saved=json.loads(Path(pin['path']).read_text())
            assert row==saved and saved['source_observations']['requests']==1
            assert saved['source_observations']['phase']==phase
            assert p.released and not p.records
            assert json.loads((p.root/f'phase-{p.generation:04}-released.json').read_text())['outcome']==pin


def test_two_phases_reset_quota_and_preserve_pins_before_release(tmp_path):
    with observer(tmp_path/'source',max_calls=1) as p:
        url=p.base_url;p.set_phase('same-question')
        assert call(p)==(200,b'abcdefghij')
        bad=write_once(tmp_path/'wrong.json',{'source_observations':{}})
        with pytest.raises(RuntimeError):p.release_phase(p.phase,bad)
        seal=p.seal_phase(p.phase)
        with pytest.raises(ValueError):p.release_phase(p.phase,bad)
        assert len(p.records)==1
        with pytest.raises(RuntimeError):p.set_phase('next')
        pin=write_once(tmp_path/'correct.json',{'source_observations':seal});p.release_phase(p.phase,pin)
        assert p.records==[]
        p.set_phase('same-question');assert p.base_url==url
        assert call(p)[0]==200
        second=release(p,tmp_path)
        assert (seal['first_index'],second['first_index'])==(0,1)
        assert second['requests']==1 and second['failed_requests']==0
        assert second['generation']==2 and not second['records_inline']
        for index in range(2):
            saved=json.loads((p.root/f'{index:04}-result.json').read_text())
            assert saved['query']=='ASK {}' and saved['response_complete']


@pytest.mark.parametrize('limits',[
    {'response_bytes':4}, {'phase_response_bytes':4}, {'max_calls':1},
])
def test_finite_budgets_retain_partial_evidence_and_classify(tmp_path,limits):
    with observer(tmp_path/'source',**limits) as p:
        p.set_phase('bounded')
        if 'max_calls' in limits:assert call(p)[0]==200
        assert call(p)[0]==502
        s=release(p,tmp_path)
        assert classify_source_failure(s)['status']=='harness_budget_censored'
        if 'max_calls' not in limits:
            assert s['partial_response_bytes']>=5
            saved=p.root/'0000-response.bin'
            assert len(saved.read_bytes())==s['response_body_bytes']
        else:assert s['requests']==2 and s['forwarded_requests']==1


def test_upstream_failure_and_late_arrival_are_distinct(tmp_path):
    with observer(tmp_path/'source') as p:
        p.set_phase('error');assert call(p,'/error')[0]==503
        s=p.seal_phase(p.phase)
        assert s['failure_categories']=={'upstream_http_failure':1}
        assert classify_source_failure(s)['status']=='upstream_source_failure'
        assert call(p)[0]==502
        now=p.snapshot(p.phase)
        assert now['late_calls']==1 and now['failure_categories']['harness_late_source_call']==1
        pin=write_once(tmp_path/'outcome.json',{'source_observations':s})
        with pytest.raises(RuntimeError):p.release_phase(p.phase,pin)
        with pytest.raises(RuntimeError):p.set_phase('next')


def test_network_oserror_is_not_disk_failure(tmp_path,monkeypatch):
    import xgap.experiments.campaign_source_observer as module
    def broken(*args,**kwargs):raise OSError('controlled upstream failure')
    with observer(tmp_path/'source') as p:
        p.set_phase('network');monkeypatch.setattr(module.http.client.HTTPConnection,'connect',broken)
        # urllib also uses HTTPConnection: use its saved connection method on the
        # client via a separate class so only the proxy's upstream is faulted.
        import http.client
        class Client(http.client.HTTPConnection):
            connect=original_connect
        c=Client('127.0.0.1',p.server.server_port,timeout=3)
        try:
            c.request('POST','/ok',b'ASK {}',{'Content-Type':'application/sparql-query'})
            result=c.getresponse();assert result.status==502;result.read()
        finally:c.close()
        s=release(p,tmp_path)
        assert s['failure_categories']=={'source_transport':1}


import http.client
original_connect=http.client.HTTPConnection.connect


def test_common_trial_seals_outcome_then_releases_and_allows_next(tmp_path,monkeypatch):
    import xgap.experiments.common_method_trial as common
    class Resources:
        def __init__(self,*a,**k):pass
        def summary(self):return {'test_fixture':True}
        def stop(self):return {'complete':True,'recovery_ms':0}
    monkeypatch.setattr(common,'OwnedResources',Resources)
    request=write_once(tmp_path/'request.json',{'schema_version':common.REQUEST_SCHEMA,
        'question_id':'controlled','population':'development','exposure':'new-boundary-test',
        'dataset':{'dataset_id':'tiny','version':'test'}})
    with observer(tmp_path/'source',max_calls=1) as p:
        def guarded(command,**kwargs):
            assert call(p)[0]==200
            root=Path(command[command.index('--output')+1]);root.mkdir()
            write_once(root/'receipt.json',{'schema_version':'xgap-fixed-semantics-worker-v1',
                'method':'fedx','question_id':'controlled','request_sha256':request['sha256'],
                'success':True,'status':'executed','result':None})
            return {'success':True,'status':'completed'}
        monkeypatch.setattr(common,'run_guarded_command',guarded)
        for index in range(2):
            result=common.run_fixed_trial(request_path=request['path'],request_sha256=request['sha256'],
                method='fedx',endpoint='http://fixture',output=tmp_path/f'run-{index}',observer=p,
                owned_services=[SimpleNamespace(role='source'),SimpleNamespace(role='method_host')])
            assert result['success'] and result['can_continue_session'] and not p.records
            release_record=json.loads((p.root/f'phase-{index+1:04}-released.json').read_text())
            assert release_record['outcome']==result['receipt']
            assert result['timing']['session_finalization']['records_released']


def test_saved_legacy_cap_failure_is_replay_only():
    path=Path('/Users/anthonyche/xgap-data/shared-nl-native-20260913-fedx-first-query/fedx/trial/receipt.json')
    saved=json.loads(path.read_text())
    classified=classify_source_failure(saved['source_observations'])
    assert classified['status']=='harness_budget_censored'
    assert classified['categories']['harness_call_budget']==5
    assert not classified['intrinsic_method_incorrectness_established']


def test_explicit_http_proxy_preserves_model_request_and_does_not_log_credentials(tmp_path):
    seen=[]
    class Proxy(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_POST(self):
            body=self.rfile.read(int(self.headers['Content-Length']))
            seen.append((self.path,self.headers.get('Authorization'),body))
            result=b'{"choices":[],"usage":{"prompt_tokens":2,"completion_tokens":1}}'
            self.send_response(200);self.send_header('Content-Length',str(len(result)))
            self.end_headers();self.wfile.write(result)
    server=ThreadingHTTPServer(('127.0.0.1',0),Proxy)
    thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01});thread.start()
    proxy='http://127.0.0.1:'+str(server.server_port)
    observer=None
    try:
        observer=CampaignSourceObserver({'/model':'http://model.invalid:9018/v1/chat/completions'},tmp_path/'records',
            budget=SourceObservationBudget(),upstream_http_proxy=proxy)
        observer.set_phase('transport')
        body=b'{"model":"unchanged-model","messages":[]}'
        with urlopen(Request(observer.base_url+'/model',data=body,
                headers={'Content-Type':'application/json','Authorization':'Bearer local-test-secret'}),timeout=3) as r:
            assert r.status==200
            r.read()
        seal=observer.seal_phase('transport')
        assert seen==[('http://model.invalid:9018/v1/chat/completions','Bearer local-test-secret',body)]
        assert seal['forwarded_requests']==1 and seal['upstream_http_proxy']==proxy
        assert all('local-test-secret' not in f.read_text() for f in (tmp_path/'records').glob('*.json'))
    finally:
        if observer:observer.close()
        server.shutdown();server.server_close();thread.join()
    with pytest.raises(ValueError):
        CampaignSourceObserver({'/model':'http://model.invalid'},tmp_path/'reject',
            budget=SourceObservationBudget(),upstream_http_proxy='http://user:secret@localhost:99')


def test_truncated_response_is_partial_transport_evidence(tmp_path):
    with observer(tmp_path/'source') as p:
        p.set_phase('truncated');assert call(p,'/truncated')[0]==502
        s=release(p,tmp_path)
        assert s['failure_categories']=={'source_transport':1} and s['partial_response_bytes']==10


def test_failed_phase_is_sealed_and_cannot_reuse_common_session(tmp_path,monkeypatch):
    import xgap.experiments.common_method_trial as common
    stopped=[]
    class Resources:
        def __init__(self,*a,**k):pass
        def summary(self):return {'test_fixture':True}
        def stop(self):stopped.append(True);return {'complete':True,'recovery_ms':0}
    monkeypatch.setattr(common,'OwnedResources',Resources)
    request=write_once(tmp_path/'request.json',{'schema_version':common.REQUEST_SCHEMA,
        'question_id':'bounded','population':'development','exposure':'new-boundary-test',
        'dataset':{'dataset_id':'tiny','version':'test'}})
    with observer(tmp_path/'source',response_bytes=4) as p:
        def guarded(command,**kwargs):
            assert call(p)[0]==502
            return {'success':False,'status':'nonzero_exit'}
        monkeypatch.setattr(common,'run_guarded_command',guarded)
        r=common.run_fixed_trial(request_path=request['path'],request_sha256=request['sha256'],
            method='fedx',endpoint='http://fixture',output=tmp_path/'run',observer=p,
            owned_services=[SimpleNamespace(role='source'),SimpleNamespace(role='method_host')])
        assert r['status']=='harness_budget_censored' and not r['success'] and not r['can_continue_session']
        assert stopped==[True] and r['source_observations']['phase_seal'] and not p.records
