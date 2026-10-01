"""Real local process/termination checks only; no models, databases or baselines."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
psutil=pytest.importorskip('psutil')

from xgap.experiments.process_guard import ProcessBudget,run_guarded_command
from xgap.experiments.guarded_one_shot import run_guarded_record
from xgap.experiments.one_shot_records import evaluate_record


def run(tmp_path,code,**limits):
    budget=replace(ProcessBudget(wall_seconds=3,sample_seconds=.01,terminate_grace_seconds=.04),**limits)
    return run_guarded_command([sys.executable,'-c',code],cwd=tmp_path,output=tmp_path/'guard',budget=budget)


def test_success_and_nonzero_exit_are_distinct_from_answer_correctness(tmp_path):
    result=run(tmp_path,"print('finished')")
    assert result['success'] and result['status']=='completed' and result['exit_code']==0
    assert result['decision_wall_ms']>0 and result['cleanup']['complete']
    assert result['sample_count']>0 and result['automatic_retries']==0
    other=tmp_path/'other';other.mkdir()
    failed=run(other,"import sys;print('failed');sys.exit(7)")
    assert not failed['success'] and failed['status']=='completed' and failed['exit_code']==7
    assert failed['requires_external_quiescence_barrier']


def test_deadline_kills_ignoring_descendants_but_leaves_unrelated_service(tmp_path):
    unrelated=subprocess.Popen([sys.executable,'-c','import time;time.sleep(15)'],start_new_session=True)
    try:
        child="import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(15)"
        code=("import subprocess,sys,time,signal;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
              f"p=subprocess.Popen([sys.executable,'-c',{child!r}]);print(p.pid,flush=True);time.sleep(15)")
        result=run(tmp_path,code,wall_seconds=.4)
        assert result['status']=='deadline_exceeded' and not result['success']
        assert result['cleanup']['complete'] and 'SIGKILL' in result['cleanup']['signals']
        assert result['requires_external_quiescence_barrier'] and result['decision_wall_ms']>=400
        assert result['total_wall_ms']<5000 and unrelated.poll() is None
        pid=int((tmp_path/'guard/stdout.log').read_text().strip())
        assert not psutil.pid_exists(pid) or psutil.Process(pid).status()==psutil.STATUS_ZOMBIE
    finally:
        unrelated.terminate();unrelated.wait(timeout=2)


def test_sampled_rss_and_log_limits_preserve_failure_output(tmp_path):
    code="import time;x=bytearray(80*1024*1024)\nfor i in range(0,len(x),4096):x[i]=1\ntime.sleep(15)"
    result=run(tmp_path,code,max_group_rss_bytes=32*1024*1024)
    assert result['status']=='rss_limit_observed' and result['sampled_peak_group_rss_bytes']>32*1024*1024
    assert result['cleanup']['complete']
    other=tmp_path/'logs';other.mkdir()
    result=run(other,"import time;print('x'*4096,flush=True);time.sleep(15)",max_log_bytes=1024)
    assert result['status']=='log_limit_observed' and not result['success']
    assert (other/'guard/stdout.log').stat().st_size>1024
    assert result['cleanup']['complete']


def test_leader_exit_with_live_child_and_monitor_failure_cannot_leak_success(tmp_path,monkeypatch):
    code="import subprocess,sys;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(15)']);print(p.pid,flush=True)"
    result=run(tmp_path,code)
    assert result['status']=='descendants_remaining' and not result['success'] and result['cleanup']['complete']
    other=tmp_path/'monitor';other.mkdir()
    from xgap.experiments import process_guard
    def broken(_):raise RuntimeError('injected monitor failure')
    monkeypatch.setattr(process_guard,'_group_sample',broken)
    result=run(other,"import time;time.sleep(15)")
    assert result['status']=='cleanup_incomplete' and not result['success']
    assert result['error']['message']=='injected monitor failure'
    pid=json.loads((other/'guard/process.json').read_text())['pid']
    assert not psutil.pid_exists(pid) or psutil.Process(pid).status()==psutil.STATUS_ZOMBIE


def test_interrupted_request_keeps_identity_and_scores_zero_against_empty_gold(tmp_path,monkeypatch):
    monkeypatch.delenv('XGAP_EXTERNAL_LLM_API_KEY',raising=False)
    def save(name,obj):
        p=tmp_path/name;p.write_text(json.dumps(obj));return str(p),hashlib.sha256(p.read_bytes()).hexdigest()
    dataset={'dataset_id':'guard-toy','version':'1'}
    # A deliberately incomplete worker profile cannot make a model/backend call.
    profile,ph=save('profile.json',{'dataset':dataset})
    request,rh=save('request.json',{'schema_version':'xgap-one-shot-evaluation-request-v1',
        'question_id':'guard-1','question':'Any rows?','population':'tiny','exposure':'development'})
    budget,bh=save('budget.json',{'schema_version':'xgap-request-budget-v1',
        'process_budget':{'wall_seconds':.0001,'terminate_grace_seconds':.02}})
    result=run_guarded_record(profile_path=profile,profile_sha256=ph,request_path=request,request_sha256=rh,
        mode='performance',operation='execute',output=tmp_path/'run',budget_path=budget,budget_sha256=bh)
    assert not result['success'] and result['status']=='guard_deadline_exceeded'
    assert result['dataset']==dataset and result['question_id']=='guard-1'
    assert result['model_network_calls'] is None and result['supervised_end_to_end_ms']>0
    reference,refh=save('reference.json',{'schema_version':'xgap-normalized-row-reference-v1',
        'question_id':'guard-1','dataset':dataset,'ordered':True,'rows':[]})
    receipt=tmp_path/'run/receipt.json'
    score=evaluate_record(receipt,receipt_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
        reference_path=reference,reference_sha256=refh,output=tmp_path/'score.json')
    assert score['answer_em']==score['answer_row_multiset_f1']==0 and not score['execution_success']
