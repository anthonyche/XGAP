"""Observer budget censoring advances only after accounting and service closure."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ch6_external_session as external
import run_bounded_joint_batch as batch
from test_bounded_joint_batch import fixture,install_fake_runtime,launch
from xgap.experiments.ch6_formal_metrics import extract_metrics
from xgap.experiments.ch6_formal_protocol import METHODS
from xgap.experiments.common_row_score import score_trial
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.process_guard import ProcessBudget


def observations():
    values={name:dict(phase_seal=dict(path='/sealed/'+name,sha256='a'*64),
        persistence_failures=0,late_calls=0,failure_categories={},requests=count,forwarded_requests=count,
        failed_requests=0,request_body_bytes=1,request_target_bytes=1,response_body_bytes=1)
        for name,count in (('source',276),('model',28),('lookup',13),('federation',12))}
    values['source'].update(forwarded_requests=256,failed_requests=20,failure_categories={'harness_call_budget':20})
    values['federation'].update(failed_requests=3,failure_categories={'upstream_http_failure':3})
    return values


def censored_outcome():
    observed=observations()
    return dict(status='harness_budget_censored',success=False,observations=observed,
        source_observations=observed['source'],harness_failures={'source':{'harness_call_budget':20}},
        model_usage_complete=True,model_calls=28,input_tokens=1200,output_tokens=400,
        guard_status='completed',quiescence=dict(complete=True),
        failure_scope='study_budget_censoring_not_method_incorrectness')


@pytest.mark.parametrize('category',sorted(external.HARNESS_BUDGET_CATEGORIES))
def test_only_explicit_observer_budgets_with_complete_accounting_are_censoring(category):
    outcome=censored_outcome()
    outcome['observations']['source']['failure_categories']={category:20}
    assert external.verified_budget_censoring(outcome)


@pytest.mark.parametrize('change',[
    lambda r:r['observations'].pop('lookup'),
    lambda r:r['observations']['source'].pop('phase_seal'),
    lambda r:r['observations']['source'].update(persistence_failures=1),
    lambda r:r['observations']['source'].update(late_calls=1),
    lambda r:r.update(model_usage_complete=False),
    lambda r:r.update(guard_status='monitor_failed'),
    lambda r:r.update(error_type='ValueError'),
    lambda r:r.update(observation_error_type='OSError'),
    lambda r:r['quiescence'].update(complete=False),
    *[lambda r,c=c:r['observations']['federation']['failure_categories'].update({c:1})
      for c in ('harness_route','harness_late_source_call','harness_transport','harness_persistence',
                'harness_unknown_budget','source_transport','source_timeout','unclassified_source_failure')],
])
def test_integrity_or_usage_uncertainty_never_authorizes_continuation(change):
    outcome=censored_outcome();change(outcome)
    assert not external.verified_budget_censoring(outcome)


@pytest.mark.parametrize('integrity_error',[False,True])
@pytest.mark.parametrize('guard_status',['completed','study_wall_budget'])
def test_external_trial_seals_distinct_budget_status_and_null_formal_quality(tmp_path,monkeypatch,integrity_error,guard_status):
    manifest=fixture(tmp_path);cell=manifest['cells'][0];observed=observations();stops=[]
    if integrity_error:observed['federation']['failure_categories']['harness_route']=1
    class Observer:
        def __init__(self,name):self.name=name;self.base_url='http://unused.invalid'
        def set_phase(self,phase):self.phase=phase
        def seal_phase(self,phase):
            assert phase==self.phase
            return deepcopy(observed[self.name])
        def release_phase(self,phase,pin):pass
    class Resources:
        def __init__(self,*args,**kwargs):pass
        def stop(self):stops.append(True);return dict(complete=True)
        def summary(self):return {}
    def guarded(command,**kwargs):
        arg=lambda n:command[command.index('--'+n)+1]
        worker=Path(arg('output'));worker.mkdir()
        write_once(worker/'receipt.json',dict(schema_version='xgap-ch7-aruqula-worker-v1',
            request_sha256=arg('request-sha256'),method=external.METHOD,question_id='q',
            success=False,status='author_failed',final_query_submissions=1))
        return dict(success=guard_status=='completed',status=guard_status)
    profile=write_once(tmp_path/'profile.json',dict(dataset={'dataset_id':'toy','version':'v1'}))
    source=SimpleNamespace(profile=profile,observer=Observer('source'),owned=[])
    session=SimpleNamespace(source_session=source,owned=[],
        observers={name:Observer(name) for name in ('model','lookup','federation')},
        config=dict(python_command='/unused',author_source=dict(path='/unused'),model_id='fixture',query_seconds=1))
    monkeypatch.setattr(external,'OwnedResources',Resources)
    monkeypatch.setattr(external,'run_guarded_command',guarded)
    monkeypatch.setattr(external,'observed_model_usage',lambda _:dict(model_network_calls=28,
        input_tokens=1200,output_tokens=400,usage_complete=True))
    monkeypatch.setenv('XGAP_EXTERNAL_LLM_API_KEY','nonsecret-fixture')
    outcome=external.run_trial(request=cell['request'],output=tmp_path/'trial',session=session,
        budget=ProcessBudget(),source_rss_bytes=1024**3)
    assert outcome['status']==('harness_budget_censored' if not integrity_error and guard_status=='completed'
                              else 'harness_observation_failure')
    assert stops and not outcome['success'] and not outcome['can_continue_session']
    assert outcome['observations']==observed and outcome['model_calls']==28
    score_trial(outcome['receipt']['path'],receipt_sha256=outcome['receipt']['sha256'],
        reference_path=cell['reference']['path'],reference_sha256=cell['reference']['sha256'],output=tmp_path/'score.json')
    from xgap.experiments.evidence_store import file_pin
    metrics=extract_metrics(outcome_pin=outcome['receipt'],score_pin=file_pin(tmp_path/'score.json'),
        timing_pin=file_pin(tmp_path/'trial/timing.json'))
    assert metrics['study_censored'] and metrics['answer_em'] is metrics['answer_f1'] is metrics['answer_coverage'] is None
    assert metrics['backend_calls']==276 and metrics['backend_forwarded_calls']==256 and metrics['backend_failed_calls']==20


def setup_batch(tmp_path,monkeypatch,*,source_closed=True,external_closed=True,outcome=None):
    manifest=fixture(tmp_path)
    for cell in manifest['cells']:cell['method']=METHODS['XGAP']
    first=manifest['cells'][0]
    manifest['cells'][0]={k:v for k,v in first.items() if k in ('cell_id','request','reference')}
    manifest['cells'][0]['method']=external.METHOD
    manifest.update(schema_version=batch.FORMAL_SCHEMA,deployment='rdf',
        external_runtime=write_once(tmp_path/'external.json',{}))
    seen,sessions=install_fake_runtime(monkeypatch,fail_cell='0',closure=source_closed,
        outcomes={'0':outcome or censored_outcome()})
    monkeypatch.setattr(batch,'RdfTdbSession',batch.NativeStoreSession)
    closed=[]
    class External:
        def __init__(self,**kwargs):pass
        def start(self):pass
        def close(self):
            closed.append(True)
            return dict(owned_groups_drained=external_closed,owned_processes_terminal=external_closed,
                        observer_stopped=external_closed)
    original=batch.run_nl_trial
    def trial(**kwargs):
        if kwargs['output'].parent.name!='0':assert closed and sessions[0].closed
        return original(**kwargs)
    monkeypatch.setattr(batch,'run_nl_trial',trial)
    monkeypatch.setattr(external,'ExternalSession',External)
    monkeypatch.setattr(external,'run_trial',lambda **kw:trial(output=kw['output'],method=external.METHOD,
        request_sha256=kw['request']['sha256']))
    return manifest,seen,sessions


def test_budget_censored_cell_stays_sealed_and_next_unattempted_cell_gets_fresh_session(tmp_path,monkeypatch,capsys):
    manifest,seen,sessions=setup_batch(tmp_path,monkeypatch)
    first,args=launch(tmp_path,manifest,max_new_cells=2)
    assert first['status']=='returned' and first['all_owned_closed']
    assert first['counts']==dict(sealed=2,execution_success=1,execution_failed=1,study_censored=1,incomplete=0,unattempted=1)
    assert seen==['0','1'] and len(sessions)==2
    summary=json.loads(capsys.readouterr().out.splitlines()[0])
    assert summary['status']=='harness_budget_censored' and summary['answer_em'] is None
    assert json.loads((tmp_path/'batch/cells/0/terminal.json').read_text())['answer_em'] is None
    sealed={p:p.read_bytes() for p in (tmp_path/'batch/cells/0').rglob('*') if p.is_file()}
    second=batch.run(**args)
    assert second['new_cells']==1 and second['counts']['study_censored']==1 and seen==['0','1','2']
    assert all(p.read_bytes()==data for p,data in sealed.items())
    assert all(s.closed for s in sessions) and second['automatic_retries']==0


@pytest.mark.parametrize('source_closed,external_closed',[(False,True),(True,False)])
def test_unverified_service_shutdown_blocks_later_cells_and_resume(tmp_path,monkeypatch,source_closed,external_closed):
    manifest,seen,_=setup_batch(tmp_path,monkeypatch,source_closed=source_closed,external_closed=external_closed)
    result,args=launch(tmp_path,manifest)
    assert result['status']=='failed' and not result['all_owned_closed'] and seen==['0']
    assert result['counts']['unattempted']==2
    with pytest.raises(ValueError,match='verified closure'):batch.run(**args)


@pytest.mark.parametrize('status,usage_complete',[
    ('harness_observation_failure',True),('harness_budget_censored',False)])
def test_integrity_failure_or_unverified_budget_status_stops_even_after_closed_services(tmp_path,monkeypatch,status,usage_complete):
    outcome=censored_outcome();outcome.update(status=status,model_usage_complete=usage_complete)
    manifest,seen,_=setup_batch(tmp_path,monkeypatch,outcome=outcome)
    result,args=launch(tmp_path,manifest)
    assert result['status']=='budget_stopped' and result['budget_status']=='study_harness_failure'
    assert result['all_owned_closed'] and result['counts']['unattempted']==2 and seen==['0']
    with pytest.raises(ValueError,match='unresolved harness failure'):batch.run(**args)
