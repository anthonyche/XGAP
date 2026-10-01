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
    assert result['decision_status']=='completed'
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
    assert result['decision_status']=='monitor_failed'
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


def test_cleanup_failure_preserves_original_deadline_decision(tmp_path,monkeypatch):
    from xgap.experiments import process_guard
    original=process_guard._stop_group
    def incomplete(process,budget):
        closed=original(process,budget)
        assert closed['complete']
        return dict(closed,complete=False)  # Simulate a missing closure proof, not a leaked process.
    monkeypatch.setattr(process_guard,'_stop_group',incomplete)
    result=run(tmp_path,"import time;time.sleep(15)",wall_seconds=.15)
    assert result['status']=='cleanup_incomplete' and result['decision_status']=='deadline_exceeded'
    assert not result['success'] and result['requires_external_quiescence_barrier']
    assert result['decision_wall_ms']>=150
    assert json.loads((tmp_path/'guard/receipt.json').read_text())['decision_status']=='deadline_exceeded'


def _fake_proc(root,pid,*,ticks=19,state='R',minor=5,major=1,read_bytes=100):
    path=root/str(pid);path.mkdir(exist_ok=True)
    fields=['0']*50;fields[0]=state;fields[7]=str(minor);fields[9]=str(major);fields[19]=str(ticks)
    (path/'stat').write_text(str(pid)+' (name with ) spaces) '+' '.join(fields))
    (path/'io').write_text('read_bytes: '+str(read_bytes)+'\nsyscr: 9\n')
    return path


def test_linux_snapshots_record_fault_io_and_state_without_inventing_missing_counters(tmp_path):
    from xgap.experiments.process_guard import _LinuxGuardDiagnostics
    pid=os.getpid();member=dict(pid=pid,created=psutil.Process(pid).create_time())
    _fake_proc(tmp_path,pid)
    diagnostics=_LinuxGuardDiagnostics(proc_root=tmp_path)
    diagnostics.sample([member],0.)
    _fake_proc(tmp_path,pid,state='D',minor=15,major=3,read_bytes=400)
    diagnostics.sample([member],1.)
    row=diagnostics.summary()['processes'][0]
    assert row['samples']==2 and row['first']['state']=='R' and row['last']['state']=='D'
    assert row['observed_delta']['minor_faults']==10 and row['observed_delta']['major_faults']==2
    assert row['observed_delta']['read_bytes']==300 and row['observed_delta']['syscr']==0
    assert row['observed_delta']['write_bytes'] is None
    assert row['last']['observed_after_ms']==1000


def test_linux_snapshots_cannot_charge_reused_pid_or_stat_identity(tmp_path):
    from xgap.experiments.process_guard import _LinuxGuardDiagnostics
    pid=os.getpid();member=dict(pid=pid,created=psutil.Process(pid).create_time())
    _fake_proc(tmp_path,pid)
    diagnostics=_LinuxGuardDiagnostics(proc_root=tmp_path)
    diagnostics.sample([member],0.)
    _fake_proc(tmp_path,pid,ticks=20,read_bytes=5000)
    diagnostics.sample([member],1.)
    diagnostics.sample([dict(member,created=member['created']-1)],2.)
    rows=diagnostics.summary()['processes']
    assert all(all(value is None for value in row['observed_delta'].values()) for row in rows)
    assert next(row for row in rows if row['created']==member['created'])['identity_changed']
    assert next(row for row in rows if row['created']!=member['created'])['samples']==0


def test_linux_diagnostics_sampling_and_storage_are_bounded_and_missing_is_unknown(monkeypatch):
    from xgap.experiments.process_guard import _LinuxGuardDiagnostics
    diagnostics=_LinuxGuardDiagnostics();diagnostics.max_identities=2
    calls=[]
    def missing(member):
        calls.append(member['pid']);raise PermissionError('inaccessible diagnostic')
    monkeypatch.setattr(diagnostics,'_read',missing)
    members=[dict(pid=n,created=1.) for n in (1,2,3)]
    diagnostics.sample(members,0.)
    diagnostics.sample(members,.5)
    assert calls==[1,2]
    diagnostics.sample(members,.6,force=True)
    result=diagnostics.summary()
    assert result['truncated'] and len(result['processes'])==2 and calls==[1,2,1,2]
    assert all(row['unavailable_samples']==2 and row['samples']==0 for row in result['processes'])
    assert all(all(value is None for value in row['observed_delta'].values()) for row in result['processes'])


def test_optional_linux_diagnostic_failure_does_not_change_command_result(tmp_path,monkeypatch):
    from xgap.experiments.process_guard import _LinuxGuardDiagnostics
    def fail(self,member):raise OSError('unavailable proc filesystem')
    monkeypatch.setattr(_LinuxGuardDiagnostics,'_read',fail)
    result=run(tmp_path,"import time;time.sleep(.1);print('done')")
    assert result['success'] and result['decision_status']=='completed' and result['cleanup']['complete']
    rows=result['linux_process_diagnostics']['processes']
    assert rows and all(row['samples']==0 for row in rows)
