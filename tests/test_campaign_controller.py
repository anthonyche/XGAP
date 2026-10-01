"""Only package-monitor injection and actual controller handoff risks."""
import json
from pathlib import Path
import subprocess
import sys

from xgap.experiments.campaign_budget import CampaignBudget, GIB
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.owned_resources import OwnedResources, OwnedProcess
from xgap.experiments.process_guard import ProcessBudget, run_guarded_command, _stop_group


def test_package_admission_does_not_abort_last_admitted_cell(tmp_path):
    budget=CampaignBudget(tmp_path,maximum_cells=1,max_bytes=4)
    assert budget.readiness()['ready'];budget.admit()
    assert budget.readiness()['reason']=='chunk_cell_budget'
    assert budget.sample([]) is None
    (tmp_path/'over-budget').write_bytes(b'12345');budget.last_sample=0
    assert budget.sample([])=='campaign_disk_budget'


def test_package_monitor_reaches_owned_worker_guard(tmp_path):
    class Disk:
        def sample(self,_):return 'campaign_disk_budget'
    source=subprocess.Popen([sys.executable,'-c','import time; time.sleep(10)'],start_new_session=True)
    try:
        monitor=OwnedResources([OwnedProcess('controlled','source',source)],extra_monitor=Disk())
        r=run_guarded_command([sys.executable,'-c','import time; time.sleep(10)'],cwd=tmp_path,
            output=tmp_path/'guard',resource_monitor=monitor,budget=ProcessBudget(wall_seconds=5))
        assert not r['success'] and r['status']=='campaign_disk_budget' and r['cleanup']['complete']
        assert monitor.stop()['complete']
    finally:_stop_group(source,ProcessBudget())


def test_controller_keeps_healthy_session_and_replaces_failed_one(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    import run_rdf_campaign as module
    dataset={'dataset_id':'controlled','version':'fixture'};made=[]
    class Session:
        def __init__(self,**kwargs):
            self.root=kwargs['root'];self.root.mkdir(parents=True);self.observer=object()
            self.ready_pin={'path':'fixture-ready'};self.profile={'path':'fixture-profile','sha256':'fixture'};made.append(self)
        def start(self):return self
        def close(self):return {'owned_groups_drained':True}
    class Hosts:
        def __init__(self,*a,**k):self.initializations={};self.endpoints={}
        def start(self,method):self.endpoints[method]='http://controlled';return self.endpoints[method]
        def owned_for(self,method):return []
    calls=[]
    def runner(**kw):
        root=kw['output'];root.mkdir(parents=True)
        q=json.loads(Path(kw['request_path']).read_text());calls.append((q,kw['method']))
        pin=write_once(root/'receipt.json',{'method':kw['method'],'question_id':q['question_id'],'track':'fixed_semantics'})
        return {'receipt':pin,'can_continue_session':kw['method']!='fedup','timing':{'total_online_ms':2}}
    monkeypatch.setattr(module,'RdfTdbSession',Session);monkeypatch.setattr(module,'CampaignMethodHosts',Hosts)
    monkeypatch.setattr(module,'run_fixed_trial',runner);monkeypatch.setattr(module,'score_trial',lambda *a,**k:None)
    request=write_once(tmp_path/'question.json',{'question_id':'q','population':'tiny','exposure':'test','question':'ordinary NL'})
    gold=write_once(tmp_path/'gold.json',{'program':{'program_id':'opaque-fixture'},'reference_sparql':'SELECT ?s WHERE {?s ?p ?o}'})
    root=tmp_path/'campaign';root.mkdir();run=root/'run';run.mkdir()
    ctl=module.Controller(root,run,{'dataset':dataset,'source_budget':{}},{'path':'prepared','sha256':'pin'},
        {'path':'summary','sha256':'pin'},CampaignBudget(root,maximum_cells=4))
    base={'question_id':'q','request':request,'track':'fixed_semantics','fixed_semantics_input':gold,
        'reference_for_post_seal_scoring_only':{'path':'scorer-only','sha256':'pin'}}
    for i,method in enumerate(('xgap-rdf','fedup','fedx')):
        cell={**base,'method':method,'cell_id':str(i)}
        assert ctl.ready(cell)['ready'];ctl.execute(cell,root/('execution-'+str(i)))
    assert len(made)==2 and calls[0][0]==calls[1][0]==calls[2][0]
    assert calls[0][0]['sparql']=='SELECT ?s WHERE {?s ?p ?o}'
    assert not any('question' in q for q,_ in calls)
    assert ctl.request_for({**base,'track':'natural_language','fixed_semantics_input':{'path':'must-not-open'}})==request
    ctl.close_session('test-complete')
