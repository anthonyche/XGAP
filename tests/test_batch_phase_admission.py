"""Phase-aware study admission leaves request limits and attempted cells intact."""
from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ch6_external_session as external
import run_bounded_joint_batch as batch
from xgap.experiments.external_federation import DeadlineExceeded
from xgap.experiments.one_shot_records import write_once
from run_ch6_formal_campaign import usage
from run_ch6_small_study import stop_reason
from test_bounded_joint_batch import fixture


class Clock:
    now=10000.
    def monotonic(self):return self.now
    def time(self):return self.now+1000000
    def advance(self,seconds):self.now+=seconds


def runtime(tmp_path,monkeypatch,*,methods=None,source_seconds=0,external_seconds=0,
            method_seconds=0,external_raises=False,source_raises=False,closure_complete=True):
    clock=Clock();events=[];sessions=[];seen=[];startup_caps=[]
    monkeypatch.setattr(batch.time,'monotonic',clock.monotonic)
    monkeypatch.setattr(batch.time,'time',clock.time)
    monkeypatch.setattr(batch,'source_commit',lambda:'source-fixed')
    monkeypatch.setattr(batch,'validate',lambda manifest:None)
    def deadline(seconds):startup_caps.append(seconds);return nullcontext()
    monkeypatch.setattr(batch,'deadline',deadline)
    def closure():return dict(owned_groups_drained=closure_complete,owned_processes_terminal=closure_complete,observer_stopped=closure_complete)
    class Source:
        def __init__(self,root,**kwargs):
            self.root=root;root.mkdir();self.observer=SimpleNamespace(generation=0)
            self.owned=[];self.profile=dict(path='/unused',sha256='a'*64);self.closed=False;sessions.append(self)
        def start(self):
            events.append('source-start');clock.advance(source_seconds)
            if source_raises:raise DeadlineExceeded('simulated deadline during startup')
        def close(self):events.append('source-close');self.closed=True;return closure()
    class External:
        def __init__(self,root,**kwargs):self.root=root;root.mkdir();self.closed=False;sessions.append(self)
        def start(self):
            events.append('external-start');clock.advance(external_seconds)
            write_once(self.root/'ready.json',dict(no_model_calls=True))
            if external_raises:raise RuntimeError('simulated external startup failure')
        def close(self):events.append('external-close');self.closed=True;return closure()
    def trial(**kwargs):
        seen.append(kwargs);events.append('method');clock.advance(method_seconds)
        root=kwargs['output'];root.mkdir()
        method=kwargs.get('method',batch.EXTERNAL_METHOD)
        outcome=dict(method=method,request_sha256=manifest['cells'][0]['request']['sha256'],
            success=True,status='answered',can_continue_session=True,model_calls=1,input_tokens=5,output_tokens=2)
        return {**outcome,'receipt':write_once(root/'receipt.json',outcome)}
    def score(path,**kwargs):
        value=dict(answer_em=1.,receipt_sha256=kwargs['receipt_sha256'],reference_sha256=kwargs['reference_sha256'])
        write_once(kwargs['output'],value);return value
    monkeypatch.setattr(batch,'NativeStoreSession',Source);monkeypatch.setattr(batch,'RdfTdbSession',Source)
    monkeypatch.setattr(external,'ExternalSession',External);monkeypatch.setattr(external,'run_trial',trial)
    monkeypatch.setattr(batch,'run_nl_trial',trial);monkeypatch.setattr(batch,'score_trial',score)
    manifest=fixture(tmp_path);manifest['design'].update(method_wall_seconds=300,startup_seconds=1800,total_wall_seconds=30000)
    templates=manifest['cells']
    manifest['cells']=[dict(deepcopy(templates[i%len(templates)]),cell_id=str(i))
        for i in range(len(methods or ['internal']))]
    if methods:
        for cell,method in zip(manifest['cells'],methods):
            if method=='external':
                cell['method']=batch.EXTERNAL_METHOD
                for key in ('config','scope','oracle'):cell.pop(key)
    manifest['external_runtime']=dict(path='/external',sha256='c'*64)
    pin=write_once(tmp_path/'manifest.json',manifest)
    args=dict(manifest_path=pin['path'],manifest_sha256=pin['sha256'],output=tmp_path/'run')
    return SimpleNamespace(clock=clock,events=events,sessions=sessions,seen=seen,args=args,manifest=manifest,startup_caps=startup_caps)


@pytest.mark.parametrize('source_ready,method,external_ready,expected',[
    (False,'internal',False,2100),(True,'internal',False,300),
    (False,'external',False,3900),(True,'external',False,2100),(True,'external',True,300)])
def test_actual_remaining_phase_costs(source_ready,method,external_ready,expected):
    context=batch.cell_admission_context(dict(method_wall_seconds=300,startup_seconds=1800),
        dict(method=batch.EXTERNAL_METHOD if method=='external' else 'xgap'),
        source_ready=source_ready,external_ready=external_ready)
    assert context['needed_total_seconds']==expected


def test_warm_internal_admits_full_method_with_301_seconds_left(tmp_path,monkeypatch):
    r=runtime(tmp_path,monkeypatch,methods=['internal','internal'],source_seconds=1800,method_seconds=0)
    contexts=[]
    def before(cell,context):contexts.append((cell['cell_id'],context));return None
    result=batch.run(**r.args,before_cell_phase=before,global_deadline_monotonic=r.clock.now+2101)
    assert result['status']=='returned' and result['counts']['sealed']==2
    second=next(c for cell,c in contexts if cell=='1')
    assert second['needed_total_seconds']==300 and second['global_remaining_seconds']==301
    assert all(call['budget'].wall_seconds==300 for call in r.seen)
    assert r.events.count('source-start')==1 and all(s.closed for s in r.sessions)


@pytest.mark.parametrize('remaining,starts',[(299,False),(3900,True)])
def test_cold_external_reserves_method_and_caps_each_startup(tmp_path,monkeypatch,remaining,starts):
    r=runtime(tmp_path,monkeypatch,methods=['external'],source_seconds=1800,external_seconds=1800)
    result=batch.run(**r.args,before_cell_phase=lambda *_:None,global_deadline_monotonic=r.clock.now+remaining)
    assert bool(r.seen)==starts
    if starts:
        assert result['counts']['sealed']==1 and r.seen[0]['budget'].wall_seconds==300
        assert r.startup_caps==[1800,1800]
    else:
        assert result['counts']['unattempted']==1 and not r.events
        assert result['admission_stop']['context']['needed_total_seconds']==3900


def test_actual_fast_cold_external_fits_without_full_worst_case_reservation(tmp_path,monkeypatch):
    r=runtime(tmp_path,monkeypatch,methods=['external'],source_seconds=328,external_seconds=6)
    result=batch.run(**r.args,before_cell_phase=lambda *_:None,global_deadline_monotonic=r.clock.now+1000)
    assert result['counts']['sealed']==1 and r.seen[0]['budget'].wall_seconds==300
    assert r.startup_caps==[700,372]
    assert all(cap<=1800 for cap in r.startup_caps) and all(s.closed for s in r.sessions)


def test_warm_external_reserves_just_external_startup(tmp_path,monkeypatch):
    r=runtime(tmp_path,monkeypatch,methods=['internal','external'],source_seconds=1800)
    contexts=[]
    result=batch.run(**r.args,before_cell_phase=lambda cell,c:contexts.append((cell['cell_id'],c)),
        global_deadline_monotonic=r.clock.now+3900)
    assert result['counts']['sealed']==2
    context=next(c for cell,c in contexts if cell=='1')
    assert context['source_startup_seconds']==0 and context['external_startup_seconds']==1800
    assert context['needed_total_seconds']==2100 and r.events.count('source-start')==1


def study_accounting(root,seen):
    """Use the real ledger scanner and stop gate, not an always-allow fixture."""
    limits=dict(model_calls_cap=1000,input_tokens_stop_threshold=10000,output_tokens_stop_threshold=10000)
    def before(cell,context):
        spent=usage(root);seen.append(dict(cell_id=cell['cell_id'],phase=context['phase'],usage=spent))
        return stop_reason(spent,limits,remaining_seconds=context['global_remaining_seconds'],
            needed_seconds=context['minimum_method_seconds'],next_call_cap=64 if cell['method']==batch.EXTERNAL_METHOD else 1)
    return before


def test_real_study_accounting_crosses_internal_three_ts_internal_without_false_unsealed(tmp_path,monkeypatch):
    r=runtime(tmp_path,monkeypatch,methods=['internal','internal','internal','external','internal'],
        source_seconds=328,external_seconds=6)
    study=tmp_path/'study';r.args['output']=study/'units/unit0';seen=[]
    result=batch.run(**r.args,before_cell_phase=study_accounting(study,seen),
        global_deadline_monotonic=r.clock.now+11000)
    assert result['status']=='returned' and result['counts']['sealed']==5
    assert result['new_cells']==5 and len(r.seen)==5
    assert usage(study)==dict(model_calls=5,input_tokens=25,output_tokens=10,
        unknown_model_usage=False,sealed_cells=5,unsealed_cells=0)
    assert not any(row['usage']['unsealed_cells'] for row in seen)
    assert all(call['budget'].wall_seconds==300 for call in r.seen)
    assert all(s.closed for s in r.sessions)


def test_real_unsealed_prior_cell_still_stops_before_any_setup(tmp_path,monkeypatch):
    r=runtime(tmp_path,monkeypatch,methods=['external'])
    study=tmp_path/'study';r.args['output']=study/'units/unit0';seen=[]
    old=study/'units/other/cells/old-attempt';old.mkdir(parents=True)
    write_once(old/'intent.json',dict(attempts=1))
    result=batch.run(**r.args,before_cell_phase=study_accounting(study,seen),
        global_deadline_monotonic=r.clock.now+11000)
    assert result['budget_status']=='unsealed_cell_requires_accounting'
    assert result['counts']['unattempted']==1 and result['new_cells']==0
    assert usage(study)['unsealed_cells']==1 and not r.events and not r.seen


@pytest.mark.parametrize('stop_phase',['before_cell','after_source_startup'])
def test_callback_stop_never_journals_or_runs_method_and_closes_setup(tmp_path,monkeypatch,stop_phase):
    r=runtime(tmp_path,monkeypatch,methods=['external'])
    def before(cell,c):return 'test_stop' if c['phase']==stop_phase else None
    result=batch.run(**r.args,before_cell_phase=before)
    assert result['budget_status']=='test_stop' and result['counts']['unattempted']==1
    assert result['new_cells']==0 and not r.seen and all(s.closed for s in r.sessions)
    assert not (Path(r.args['output'])/'cells/0').exists()


def test_rechecks_full_method_grant_after_external_setup(tmp_path,monkeypatch):
    # Extra setup overhead must never silently shrink the method's 300 seconds.
    r=runtime(tmp_path,monkeypatch,methods=['external'],source_seconds=1800,external_seconds=1801)
    result=batch.run(**r.args,before_cell_phase=lambda *_:None,global_deadline_monotonic=r.clock.now+3900)
    assert result['budget_status']=='study_global_insufficient_time_for_cell'
    assert result['admission_stop']['context']['global_remaining_seconds']==299
    assert result['counts']['unattempted']==1 and result['new_cells']==0 and not r.seen
    assert result['unstarted_setup'] and all(s.closed for s in r.sessions)
    record=json.loads(Path(result['unstarted_setup']['path']).read_text())
    assert record['method_attempts']==record['model_calls']==record['answer_query_executions']==0
    assert record['setup_attempts']==1 and record['all_owned_closed']
    assert Path(record['retained_path'],'external-services/ready.json').exists()


def test_external_setup_exception_retained_without_attempt(tmp_path,monkeypatch):
    r=runtime(tmp_path,monkeypatch,methods=['external'],external_raises=True)
    result=batch.run(**r.args,before_cell_phase=lambda *_:None)
    assert result['status']=='failed' and result['error']['type']=='RuntimeError'
    assert result['counts']['unattempted']==1 and result['unstarted_setup']
    assert not r.seen and all(s.closed for s in r.sessions)


def test_unverified_setup_shutdown_cannot_release_cell_for_new_attempt(tmp_path,monkeypatch):
    r=runtime(tmp_path,monkeypatch,methods=['external'],closure_complete=False,external_raises=True)
    result=batch.run(**r.args,before_cell_phase=lambda *_:None)
    assert result['status']=='failed' and result['all_owned_closed'] is False
    assert result['counts']['incomplete']==1 and result['unstarted_setup'] is None
    assert not r.seen and (Path(r.args['output'])/'cells/0/external-services').is_dir()
    with pytest.raises(ValueError,match='verified closure'):
        batch.run(**r.args,before_cell_phase=lambda *_:None)


def test_external_setup_still_refreshes_storage_without_repeating_cell_accounting(tmp_path,monkeypatch):
    r=runtime(tmp_path,monkeypatch,methods=['external'],external_seconds=2)
    study=tmp_path/'study';r.args['output']=study/'units/unit0';seen=[]
    original=batch.BatchBudget.sample
    def sample(self,members):
        # Model public-metadata setup consuming the declared artifact allowance.
        if (self.root/'cells/0/external-services/ready.json').exists():self.design['package_max_bytes']=1
        return original(self,members)
    monkeypatch.setattr(batch.BatchBudget,'sample',sample)
    result=batch.run(**r.args,before_cell_phase=study_accounting(study,seen),
        global_deadline_monotonic=r.clock.now+11000)
    assert result['budget_status']=='study_disk_budget' and result['new_cells']==0
    assert result['admission_stop']['context']['phase']=='after_external_startup'
    assert result['counts']['unattempted']==1 and not r.seen and all(s.closed for s in r.sessions)
    assert result['unstarted_setup'] and usage(study)['unsealed_cells']==0
    assert {row['phase'] for row in seen}=={'before_cell','after_source_startup'}


def test_global_deadline_during_source_startup_is_budget_stop_and_closes(tmp_path,monkeypatch):
    r=runtime(tmp_path,monkeypatch,source_seconds=2200,source_raises=True)
    result=batch.run(**r.args,global_deadline_monotonic=r.clock.now+2100)
    assert result['status']=='budget_stopped' and result['budget_status']=='study_global_wall_budget'
    assert result['error'] is None and result['counts']['unattempted']==1
    assert not r.seen and all(s.closed for s in r.sessions)


def test_capped_startup_timeout_is_study_censoring_not_original_startup_timeout(tmp_path,monkeypatch):
    r=runtime(tmp_path,monkeypatch,source_seconds=700,source_raises=True)
    result=batch.run(**r.args,before_cell_phase=lambda *_:None,global_deadline_monotonic=r.clock.now+1000)
    assert result['status']=='budget_stopped' and result['budget_status']=='study_startup_wall_budget'
    assert result['stopped_startup_limit']==dict(seconds=700,capped_by_study=True,reserved_method_seconds=300)
    assert result['error'] is None and result['counts']['unattempted']==1 and not r.seen
    assert r.startup_caps==[700] and all(s.closed for s in r.sessions)


def test_original_startup_cap_timeout_remains_technical_failure(tmp_path,monkeypatch):
    r=runtime(tmp_path,monkeypatch,source_seconds=1800,source_raises=True)
    result=batch.run(**r.args,before_cell_phase=lambda *_:None,global_deadline_monotonic=r.clock.now+10000)
    assert result['status']=='failed' and result['error']['type']=='DeadlineExceeded'
    assert result['budget_status'] is None and result['counts']['unattempted']==1 and not r.seen


def test_slow_accounting_callback_cannot_spend_stale_full_method_grant(tmp_path,monkeypatch):
    r=runtime(tmp_path,monkeypatch)
    def before(cell,context):r.clock.advance(701)
    result=batch.run(**r.args,before_cell_phase=before,global_deadline_monotonic=r.clock.now+1000)
    assert result['budget_status']=='study_global_insufficient_time_for_cell'
    assert result['admission_stop']['context']['global_remaining_seconds']==299
    assert result['new_cells']==0 and not r.seen and not r.events


def test_storage_scan_before_journaling_rechecks_global_full_method(tmp_path,monkeypatch):
    r=runtime(tmp_path,monkeypatch)
    original=batch.BatchBudget.sample;calls=[]
    def sample(self,members):
        calls.append(True)
        # The final pre-journal scan follows the post-source admission check.
        if len(calls)==4:r.clock.advance(701)
        return original(self,members)
    monkeypatch.setattr(batch.BatchBudget,'sample',sample)
    result=batch.run(**r.args,before_cell_phase=lambda *_:None,global_deadline_monotonic=r.clock.now+1000)
    assert result['budget_status']=='study_global_insufficient_time_for_cell'
    assert result['admission_stop']['context']['phase']=='before_request_journal'
    assert result['counts']['unattempted']==1 and not r.seen and all(s.closed for s in r.sessions)


def test_running_worker_monitor_enforces_global_deadline(tmp_path,monkeypatch):
    r=runtime(tmp_path,monkeypatch)
    monitor=batch.BatchBudget(Path(r.args['output']),r.manifest['design'],r.clock.time(),
        global_deadline_monotonic=r.clock.now+1)
    Path(r.args['output']).mkdir()
    assert monitor.sample([]) is None
    r.clock.advance(1)
    assert monitor.sample([])=='study_global_wall_budget'


def test_legacy_callback_stays_one_argument_and_new_api_rejects_both(tmp_path,monkeypatch):
    r=runtime(tmp_path,monkeypatch);calls=[]
    with pytest.raises(ValueError,match='not both'):
        batch.run(**r.args,before_cell=lambda cell:None,before_cell_phase=lambda cell,c:None)
    result=batch.run(**r.args,before_cell=lambda cell:calls.append(cell['cell_id']))
    assert result['counts']['sealed']==1 and calls==['0']
    assert 'admission_stop' not in result
