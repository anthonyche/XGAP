"""New native source/worker/order edges only; no accepted RDF gates rerun."""
from collections import Counter
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from xgap.experiments.campaign_schedule import freeze_schedule
from xgap.experiments.campaign_source_observer import CampaignSourceObserver, SourceObservationBudget
from xgap.experiments.one_shot_records import write_once


def test_native_schedule_preserves_denominator_and_omits_rdf_baselines(tmp_path):
    dataset={'dataset_id':'tiny-order-only','version':'v1'}
    population=write_once(tmp_path/'population.json',{'schema_version':'xgap-finbench-one-shot-population-v1',
        'dataset':dataset,'artifacts':[{'question_id':str(i),'split':'evaluation','family':'synthetic',
            'files':{k:{'path':'must-not-open-'+k} for k in ('request','gold','reference')}} for i in range(48)]})
    profile=write_once(tmp_path/'profile.json',{'dataset':dataset});orders=[]
    for track in ('natural_language','fixed_semantics'):
        pin=freeze_schedule(population_path=population['path'],population_sha256=population['sha256'],
            profile_path=profile['path'],profile_sha256=profile['sha256'],track=track,deployment='native',output=tmp_path/(track+'.json'))
        s=json.loads(Path(pin['path']).read_text());orders.append([c['question_id'] for c in s['cells'] if c['block']==0 and c['method_position']==0])
        assert len(set(c['question_id'] for c in s['cells']))==48
        if track=='natural_language':
            assert len(s['cells'])==96 and s['maximum_model_calls']==96
            assert set(Counter((c['method'],c['method_position']) for c in s['cells']).values())=={24}
            assert not any('fixed_semantics_input' in c for c in s['cells'])
        else:
            assert len(s['cells'])==144 and s['methods']==['xgap-native'] and s['maximum_model_calls']==0
    assert orders[0]==orders[1]


def test_native_json_wire_preserved_and_recorded_without_auth_values(tmp_path):
    requests=[];body=json.dumps({'statements':[{'statement':'RETURN $value AS value','parameters':{'value':'A&B=中文'}}]},ensure_ascii=False).encode()
    response=b'{"results":[],"errors":[]}'
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def do_POST(self):
            requests.append((self.path,self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200);self.send_header('Content-Length',str(len(response)));self.end_headers();self.wfile.write(response)
    source=ThreadingHTTPServer(('127.0.0.1',0),Handler);source.daemon_threads=True
    thread=threading.Thread(target=source.serve_forever,kwargs={'poll_interval':.01});thread.start()
    path='/db/neo4j/tx/commit';observer=CampaignSourceObserver({path:f'http://127.0.0.1:{source.server_port}'+path},tmp_path/'observer',budget=SourceObservationBudget())
    conn=http.client.HTTPConnection('127.0.0.1',observer.server.server_port,timeout=3)
    try:
        observer.set_phase('native-wire');conn.request('POST',path,body,{'Content-Type':'application/json','Authorization':'unused-test-auth'})
        reply=conn.getresponse();assert reply.status==200 and reply.read()==response
        seal=observer.seal_phase('native-wire');assert seal['requests']==1 and seal['failed_requests']==0
        assert 'native_statements' not in observer.records[0]
        row=json.loads((tmp_path/'observer/0000-result.json').read_text())
        assert requests==[(path,body)] and row['native_statements']==json.loads(body)['statements']
        assert row['request_body_sha256']==hashlib.sha256(body).hexdigest() and row['query_language']=='cypher'
        assert 'unused-test-auth' not in json.dumps(row)
        pin=write_once(tmp_path/'outcome.json',{'source_observations':seal});observer.release_phase('native-wire',pin)
    finally:
        conn.close();observer.close();source.shutdown();source.server_close();thread.join()


def test_native_label_rejects_rdf_only_profile_before_any_execution(tmp_path,monkeypatch):
    import xgap.experiments.fixed_semantic_worker as module
    dataset={'dataset_id':'controlled','version':'v1'}
    class Profile:
        @classmethod
        def load(cls,*a,**k):return cls()
        def materialize(self):return {'dataset':dataset},None,None,{}, {},{'rdf':{'engine':'fuseki'}},{}
    monkeypatch.setattr(module,'FrozenOneShotProfile',Profile)
    monkeypatch.setattr(module,'native_clients',lambda *_:pytest.fail('Invalid deployment reached database'))
    request=write_once(tmp_path/'request.json',{'schema_version':module.REQUEST_SCHEMA,'dataset':dataset,
        'question_id':'q','population':'tiny','exposure':'synthetic','program':{},'sparql':'SELECT * WHERE {}'})
    r=module.run_fixed(request_path=request['path'],request_sha256=request['sha256'],method='xgap-native',output=tmp_path/'run')
    assert not r['success'] and r['top_level_attempts']==0 and 'deployment engines' in r['error']


def test_native_retirement_discards_only_its_serving_data(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    from native_store_session import NativeStoreSession
    process=subprocess.Popen([sys.executable,'-c','pass'],start_new_session=True);process.wait(timeout=3)
    s=NativeStoreSession.__new__(NativeStoreSession);s.root=tmp_path/'session';s.root.mkdir()
    s.processes=SimpleNamespace(owned=[('owned',process)],logs=[]);s.ports=None;s.observer=None;s.discard_serving_copies=True
    for name in s.serving_copy_paths:
        p=s.root/name;p.mkdir(parents=True);(p/'data').write_bytes(b'copy')
    original=tmp_path/'original';original.write_bytes(b'frozen');log=s.root/'source.log';log.write_bytes(b'retained')
    r=s.close();assert r['owned_groups_drained'] and r['observer_stopped']
    assert r['discarded_reconstructable_serving_copies']==list(s.serving_copy_paths)
    assert original.read_bytes()==b'frozen' and log.read_bytes()==b'retained'


def test_native_controller_uses_no_rdf_summary_or_host(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    import run_rdf_campaign as module
    from xgap.experiments.campaign_budget import CampaignBudget
    class Session:
        def __init__(self,**kw):
            self.root=kw['root'];self.root.mkdir();self.owned=['native-owned-groups'];self.ready_pin={'kind':'native-ready'}
        def start(self):return self
        def close(self):return {'owned_groups_drained':True}
    monkeypatch.setattr(module,'NativeStoreSession',Session)
    monkeypatch.setattr(module,'CampaignMethodHosts',lambda *a,**kw:pytest.fail('Native deployment loaded RDF host'))
    q=write_once(tmp_path/'request.json',{'question_id':'q','question':'ordinary NL'})
    ctl=module.Controller(tmp_path,tmp_path,{'deployment':'native','source_budget':{}},
        {'path':'native-prepared','sha256':'pin'},None,CampaignBudget(tmp_path,maximum_cells=1))
    try:
        assert ctl.ready({'track':'natural_language','question_id':'q','request':q,'method':'xgap-performance','cell_id':'n'})['ready']
        assert ctl.hosts.owned_for('xgap-performance')==['native-owned-groups']
        with pytest.raises(ValueError,match='Unknown native'):ctl.hosts.owned_for('fedx')
    finally:ctl.close_session('fixture-complete')
