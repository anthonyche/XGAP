"""New transport lifecycle and saved retirement-failure replay, no baseline run."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import pytest

from xgap.experiments.campaign_source_observer import CampaignSourceObserver, SourceObservationBudget
from xgap.experiments.one_shot_records import write_once


def exercise(tmp_path,*,stale=False):
    arrivals=[]
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*_):pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']));arrivals.append(self.client_address)
            self.send_response(200);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'ok');self.wfile.flush()
            if stale:self.close_connection=True
    source=ThreadingHTTPServer(('127.0.0.1',0),Handler);source.daemon_threads=True
    thread=threading.Thread(target=source.serve_forever,kwargs={'poll_interval':.01});thread.start()
    proxy=CampaignSourceObserver({'/source':f'http://127.0.0.1:{source.server_port}/query'},tmp_path/'observer',
        budget=SourceObservationBudget());client=http.client.HTTPConnection('127.0.0.1',proxy.server.server_port,timeout=3)
    try:
        proxy.set_phase('new-transport');statuses=[]
        for _ in range(2 if stale else 20):
            client.request('POST','/source',b'ASK {}',{'Content-Type':'application/sparql-query'})
            response=client.getresponse();statuses.append(response.status);response.read()
        sealed=proxy.seal_phase(proxy.phase)
        pin=write_once(tmp_path/'outcome.json',{'source_observations':sealed});proxy.release_phase(proxy.phase,pin)
        return statuses,sealed,arrivals
    finally:
        client.close();proxy.close();source.shutdown();source.server_close();thread.join()


def test_http11_reuses_connections_without_losing_request_ledger(tmp_path):
    statuses,s,arrivals=exercise(tmp_path)
    assert statuses==[200]*20 and s['requests']==20 and s['response_body_bytes']==40
    assert len(set(arrivals))==1 and s['upstream_connections_opened']==1 and s['upstream_connection_reuses']==19
    assert len(list((tmp_path/'observer').glob('*-result.json')))==20


def test_stale_upstream_connection_is_not_automatically_retried(tmp_path):
    statuses,s,arrivals=exercise(tmp_path,stale=True)
    assert statuses==[200,502] and len(arrivals)==1
    assert s['failure_categories']=={'source_transport':1} and s['upstream_connections_opened']==1


def test_saved_retirement_failure_detaches_and_halts_session(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    from run_rdf_campaign import Controller
    from xgap.experiments.campaign_budget import CampaignBudget
    saved=Path('/Users/anthonyche/xgap-data/finbench-rdf-fixed-campaign-20260913-v1/cells/fixed_semantics-00-000-1/terminal.json')
    terminal=json.loads(saved.read_text());assert terminal['error_type']=='PermissionError'
    class FailedClose:
        root=tmp_path
        def close(self):raise PermissionError(1,'Operation not permitted')
    c=Controller(tmp_path,tmp_path,{},None,None,CampaignBudget(tmp_path,maximum_cells=1))
    c.session=FailedClose();c.hosts=object()
    assert c.close_session('saved-cleanup-error')>=0 and c.session is None and c.hosts is None
    assert not c.ready({})['ready'] and c.events[0]['closure']['error_type']=='PermissionError'


def test_correction_epoch_preserves_inputs_and_prior_intents(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    from run_rdf_campaign import bind_campaign_identity
    old={'schedule':'frozen','prepared':'same','summary':'same','implementation_sha256':'old'}
    first=bind_campaign_identity(tmp_path,old);before=(tmp_path/'campaign.json').read_bytes()
    new={**old,'implementation_sha256':'corrected'}
    with pytest.raises(ValueError,match='documented harness'):bind_campaign_identity(tmp_path,new)
    epoch=bind_campaign_identity(tmp_path,new,'transport/retirement correction; no method query retry')
    d=json.loads(Path(epoch['path']).read_text());assert d['previous']['sha256']==first['sha256']
    assert d['prior_intents_retained_and_never_redispatched'] and (tmp_path/'campaign.json').read_bytes()==before
    assert bind_campaign_identity(tmp_path,new)['path']==epoch['path']
    with pytest.raises(ValueError,match='frozen evaluation'):bind_campaign_identity(tmp_path,{**new,'summary':'different'},'not allowed')
