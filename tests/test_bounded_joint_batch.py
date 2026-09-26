"""Current worker routing, compressed scoring, nonduplicating batch recovery."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import run_bounded_joint_batch as batch
from xgap.experiments.bounded_joint_contract import METHODS, TRACK, configuration, load_configuration
from xgap.experiments import common_method_trial as common
from xgap.experiments.common_row_score import score_trial
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.evidence_store import write_json_evidence
from xgap.experiments.nl_method_worker import run_nl
from xgap.experiments.one_shot_records import write_once

DATASET={'dataset_id':'toy','version':'v1'}
NORMALIZATION={'schema_version':'xgap-row-normalization-v1','fields':{'id':'text'}}


def fixture(root):
    request=write_once(root/'request.json',dict(schema_version='xgap-one-shot-evaluation-request-v1',
        question_id='q',question='A development question',population='toy',exposure='development'))
    reference=write_once(root/'reference.json',dict(schema_version='xgap-normalized-row-reference-v1',
        dataset=DATASET,question_id='q',ordered=True,normalization=NORMALIZATION,rows=[{'id':'1'},{'id':'2'}]))
    missing=dict(path=str(root/'private-never-opened.json'),sha256='a'*64)
    cells=[dict(cell_id=str(i),method=METHODS[i%2],request=request,reference=reference,
        scope=missing,oracle=missing,config=missing) for i in range(3)]
    design=dict(total_wall_seconds=3600,package_max_bytes=1024**3,free_disk_reserve_bytes=1,
        method_wall_seconds=5,method_rss_bytes=1024**3,source_rss_bytes=1024**3,startup_seconds=5,
        source_budget=asdict(SourceObservationBudget(capture_compression='gzip')))
    return dict(schema_version=batch.SCHEMA,deployment='native',prepared=missing,design=design,cells=cells)


def install_fake_runtime(monkeypatch, *, fail_cell=None, interrupt_cell=None, closure=True):
    seen=[];sessions=[]
    class Session:
        def __init__(self,root,**kwargs):
            self.root=root;root.mkdir();self.observer=SimpleNamespace(generation=0);self.owned=[]
            self.serving_root=kwargs.get('serving_root')
            self.profile=dict(path='/unused-profile',sha256='b'*64);self.closed=False;sessions.append(self)
        def start(self):pass
        def close(self):
            self.closed=True
            return dict(owned_groups_drained=closure,owned_processes_terminal=closure,observer_stopped=closure)
    def trial(**kwargs):
        assert not any('reference' in k for k in kwargs)
        path=kwargs['output'];cell=path.parent.name;seen.append(cell);path.mkdir()
        if cell==interrupt_cell:raise RuntimeError('simulated interruption after cell intent')
        success=cell!=fail_cell
        result=write_json_evidence(path/'answer.json.gz',dict(answer_format='json_rows',answer=[{'id':'1'},{'id':'2'}]))
        outcome=dict(schema_version='xgap-common-method-trial-v1',method=kwargs['method'],track=TRACK,
            dataset=DATASET,question_id='q',population='toy',exposure='development',
            request_sha256=kwargs['request_sha256'],success=success,status='returned' if success else 'budget_nonanswer',result=result)
        pin=write_once(path/'receipt.json',outcome)
        return {**outcome,'receipt':pin,'can_continue_session':success}
    monkeypatch.setattr(batch,'source_commit',lambda:'source-v1')
    monkeypatch.setattr(batch,'NativeStoreSession',Session)
    monkeypatch.setattr(batch,'run_nl_trial',trial)
    return seen,sessions


def launch(root,manifest,*,max_new_cells=10000,name='run'):
    pin=write_once(root/(name+'.json'),manifest)
    args=dict(manifest_path=pin['path'],manifest_sha256=pin['sha256'],output=root/'batch')
    return batch.run(**args,max_new_cells=max_new_cells),args


def test_declared_local_storage_is_shared_and_recorded(tmp_path,monkeypatch):
    seen,sessions=install_fake_runtime(monkeypatch)
    scratch=tmp_path/'scratch';scratch.mkdir()
    monkeypatch.setenv('SLURM_JOB_ID','fixture-job');monkeypatch.setenv('SLURM_TMPDIR',str(scratch))
    manifest=fixture(tmp_path);manifest['design']['source_storage']='node_local'
    result,_=launch(tmp_path,manifest)
    assert result['status']=='returned' and seen==['0','1','2'] and len(sessions)==1
    assert scratch in sessions[0].serving_root.parents
    record=json.loads((tmp_path/'batch/invocations/0001/source-workspace.json').read_text())
    assert record['common_to_all_methods'] and record['storage_accounted']
    assert Path(record['path'])==sessions[0].serving_root.parent
    manifest['design']['source_storage']='untracked_mount'
    with pytest.raises(ValueError,match='storage policy'):batch.validate(manifest)


def test_resume_skips_success_and_failed_cells_without_private_or_reference_worker_access(tmp_path,monkeypatch):
    seen,sessions=install_fake_runtime(monkeypatch,fail_cell='1')
    first,args=launch(tmp_path,fixture(tmp_path),max_new_cells=2)
    assert first['counts']==dict(sealed=2,execution_success=1,execution_failed=1,incomplete=0,unattempted=1)
    before=(tmp_path/'batch/cells/1/terminal.json').read_bytes()
    second=batch.run(**args)
    assert second['counts']['sealed']==3 and second['new_cells']==1
    assert batch.run(**args)['status']=='no_unattempted_cells'
    assert seen==['0','1','2'] and all(s.closed for s in sessions)
    assert (tmp_path/'batch/cells/1/terminal.json').read_bytes()==before


def test_interrupted_intent_is_counted_and_never_retried_after_verified_cleanup(tmp_path,monkeypatch):
    seen,_=install_fake_runtime(monkeypatch,interrupt_cell='0')
    first,args=launch(tmp_path,fixture(tmp_path))
    assert first['status']=='failed' and first['counts']['incomplete']==1 and first['all_owned_closed']
    resumed=batch.run(**args)
    assert resumed['counts']['sealed']==2 and resumed['counts']['incomplete']==1
    assert seen==['0','1','2']


def test_unknown_closure_or_different_source_refuses_resume(tmp_path,monkeypatch):
    seen,_=install_fake_runtime(monkeypatch)
    first,args=launch(tmp_path,fixture(tmp_path),max_new_cells=1)
    monkeypatch.setattr(batch,'source_commit',lambda:'source-v2')
    with pytest.raises(ValueError,match='change code'):batch.run(**args)
    monkeypatch.setattr(batch,'source_commit',lambda:'source-v1')
    Path(first['receipt']['path']).unlink()  # simulate hard termination before closure seal
    with pytest.raises(ValueError,match='verified closure'):batch.run(**args)
    assert seen==['0']


def test_study_budget_stops_before_source_start_and_is_not_a_failed_answer(tmp_path,monkeypatch):
    seen,sessions=install_fake_runtime(monkeypatch)
    manifest=fixture(tmp_path);manifest['design']['package_max_bytes']=1
    result,_=launch(tmp_path,manifest)
    assert result['status']=='budget_stopped' and result['budget_status']=='study_disk_budget'
    assert result['counts']['unattempted']==3 and result['counts']['execution_failed']==0
    assert seen==sessions==[]


@pytest.mark.parametrize('change',[lambda d:d['cells'].append(deepcopy(d['cells'][0])),
    lambda d:d['cells'][0].update(cell_id='../escape'),lambda d:d['cells'][0].update(method='fedx')])
def test_manifest_rejects_duplicate_unsafe_or_legacy_cells(tmp_path,change):
    manifest=fixture(tmp_path);change(manifest)
    with pytest.raises(ValueError):batch.validate(manifest)


def test_configuration_round_trip_and_reject_invalid_resource_budget(tmp_path):
    config=configuration(epsilon='1/2');pin=write_once(tmp_path/'config.json',config)
    raw,info,limits,costs=load_configuration(pin['path'],pin['sha256'])
    assert raw['epsilon']=='1/2' and limits.resources.remote_calls==32 and info.max_calls==9
    config['limits']['resources']['tokens']=-1;pin=write_once(tmp_path/'bad.json',config)
    with pytest.raises(ValueError):load_configuration(pin['path'],pin['sha256'])


def test_current_contract_cannot_silently_select_legacy_worker_or_ignore_missing_scope():
    args=dict(request_path='unused',request_sha256='a',profile_path='unused',profile_sha256='b',output='unused')
    with pytest.raises(ValueError,match='historical'):run_nl(**args,method='xgap-performance',scope_path='scope')
    with pytest.raises(ValueError,match='require pinned'):run_nl(**args,method=METHODS[0])


@pytest.mark.parametrize('corrupt,reverse',[(False,False),(False,True),(True,False)])
def test_compressed_scoring_preserves_order_and_rejects_corrupt_payload(tmp_path,corrupt,reverse):
    manifest=fixture(tmp_path);cell=manifest['cells'][0]
    rows=[{'id':'1'},{'id':'2'}];rows=rows[::-1] if reverse else rows
    answer=write_json_evidence(tmp_path/'answer.json.gz',dict(answer_format='json_rows',answer=rows))
    if corrupt:Path(answer['path']).write_bytes(b'broken')
    receipt=write_once(tmp_path/'receipt.json',dict(schema_version='xgap-common-method-trial-v1',
        method=cell['method'],track=TRACK,dataset=DATASET,question_id='q',population='toy',exposure='development',
        success=True,status='returned',result=answer))
    score=score_trial(receipt['path'],receipt_sha256=receipt['sha256'],reference_path=cell['reference']['path'],
        reference_sha256=cell['reference']['sha256'],output=tmp_path/'score.json')
    assert score['answer_em']==(0 if reverse or corrupt else 1)
    assert score['answer_row_multiset_f1']==(0 if corrupt else 1)
    assert bool(score['comparison_error'])==corrupt


@pytest.mark.parametrize('tamper',[False,True])
@pytest.mark.parametrize('proposal_failure',[False,True])
def test_common_trial_checks_current_identities_and_exports_metrics(tmp_path,monkeypatch,tamper,proposal_failure):
    manifest=fixture(tmp_path);cell=manifest['cells'][0];seen=[];stops=[]
    profile=write_once(tmp_path/'profile.json',dict(dataset=DATASET))
    class Resources:
        def __init__(self,*a,**kw):pass
        def summary(self):return {}
        def stop(self):stops.append(True);return dict(complete=True,recovery_ms=0)
    class Observer:
        def set_phase(self,phase):pass
        def snapshot(self,phase):return dict(failed_requests=0,requests=0)
    def guarded(command,**kwargs):
        seen.append(command)
        arg=lambda n:command[command.index('--'+n)+1]
        assert not any('reference' in x for x in command)
        root=Path(arg('output'));root.mkdir()
        receipt=dict(schema_version='xgap-nl-method-worker-v1',method=arg('method'),track=TRACK,
            request_sha256=arg('request-sha256'),profile_sha256=arg('profile-sha256'),dataset=DATASET,question_id='q',
            oracle_sha256=arg('oracle-sha256'),scope_sha256='bad' if tamper else arg('scope-sha256'),
            joint_config_sha256=arg('joint-config-sha256'),success=True,status='returned',planning_cpu_ms=7,
            certificate_ms=2,total_user_calls=2,final_plan_executions=1,model_calls=0)
        if proposal_failure:
            receipt.update(success=False,status='proposal_failed',model_calls=1,input_tokens=None,output_tokens=None,
                final_plan_executions=0,error='External endpoint returned HTTP 401: Unauthorized',
                proposal_failure_category='provider_error')
        write_once(root/'receipt.json',receipt)
        return dict(success=True,status='completed')
    monkeypatch.setattr(common,'OwnedResources',Resources);monkeypatch.setattr(common,'run_guarded_command',guarded)
    kwargs={}
    for key,arg in (('request','request'),('scope','scope'),('oracle','oracle'),('config','joint_config')):
        kwargs[arg+'_path']=cell[key]['path'];kwargs[arg+'_sha256']=cell[key]['sha256']
    outcome=common.run_nl_trial(**kwargs,profile_path=profile['path'],profile_sha256=profile['sha256'],
        method=cell['method'],output=tmp_path/'trial',observer=Observer(),owned_services=[SimpleNamespace(role='source')])
    assert outcome['success'] is (not tamper and not proposal_failure) and len(seen)==1
    if tamper:assert outcome['status']=='supervisor_failed' and stops and 'identity' in outcome['error']
    elif proposal_failure:
        assert outcome['status']=='proposal_failed' and outcome['proposal_failure_category']=='provider_error'
        assert 'HTTP 401' in outcome['error'] and outcome['final_plan_executions']==0
        assert outcome['model_calls']==1 and outcome['input_tokens'] is outcome['output_tokens'] is None
    else:assert outcome['planning_cpu_ms']==7 and outcome['certificate_ms']==2 and outcome['final_plan_executions']==1


def test_batch_logs_proposal_diagnostics_without_repeating_attempt(tmp_path,monkeypatch,capsys):
    seen,sessions=install_fake_runtime(monkeypatch,fail_cell='0')
    original=batch.run_nl_trial
    def trial(**kwargs):
        outcome=original(**kwargs)
        if not outcome['success']:
            outcome.update(status='proposal_failed',proposal_failure_category='provider_error',
                error='External endpoint returned HTTP 401: Unauthorized')
        return outcome
    monkeypatch.setattr(batch,'run_nl_trial',trial)
    first,args=launch(tmp_path,fixture(tmp_path),max_new_cells=1)
    line=json.loads(capsys.readouterr().out.strip())
    assert line['proposal_failure_category']=='provider_error' and 'HTTP 401' in line['error']
    assert line['status']=='proposal_failed' and first['counts']['execution_failed']==1
    batch.run(**args)
    assert seen==['0','1','2'] and all(s.closed for s in sessions)
