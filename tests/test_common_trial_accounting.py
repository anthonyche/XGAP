"""A late source drain cannot erase model usage from a validated worker."""
from types import SimpleNamespace

import pytest

from xgap.experiments import common_method_trial as common
from xgap.experiments import unified_contract as unified
from xgap.experiments.one_shot_records import write_once


@pytest.mark.parametrize('snapshot_failure',[False,True])
@pytest.mark.parametrize('child_case',['valid','invalid_identity','unknown_tokens'])
def test_worker_usage_survives_source_failure_only_after_identity_validation(tmp_path,monkeypatch,snapshot_failure,child_case):
    request=write_once(tmp_path/'request.json',dict(schema_version=common.NL_SCHEMA,
        question_id='q',question='fixture',population='toy',exposure='development'))
    dataset={'dataset_id':'toy','version':'v1'}
    profile=write_once(tmp_path/'profile.json',dict(dataset=dataset))
    missing={'path':str(tmp_path/'not-read.json'),'sha256':'a'*64}
    method=unified.METHODS[0];stopped=[]
    class Monitor:
        def __init__(self,*a,**kw):pass
        def sample(self,members):return None
        def stop(self):stopped.append(True);return dict(complete=True,recovery_ms=0)
        def summary(self):return dict(status='within_observed_budget')
    observed=dict(requests=4,forwarded_requests=4,failed_requests=1,late_calls=0,
        persistence_failures=0,failure_categories={'source_transport':1},phase_seal={'path':'sealed'})
    class Observer:
        count=0
        def set_phase(self,phase):self.phase=phase
        def snapshot(self,phase):
            self.count+=1
            if snapshot_failure and self.count==1:raise RuntimeError('Source accounting not settled')
            return dict(observed)
        def seal_phase(self,phase):return dict(observed)
        def release_phase(self,phase,pin):pass
    def guarded(command,**kwargs):
        (tmp_path/'run/worker').mkdir()
        write_once(tmp_path/'run/worker/receipt.json',dict(schema_version='xgap-nl-method-worker-v1',
            method=method,request_sha256=request['sha256'],question_id='wrong' if child_case=='invalid_identity' else 'q',dataset=dataset,
            profile_sha256=profile['sha256'],scope_sha256=missing['sha256'],
            oracle_sha256=missing['sha256'],joint_config_sha256=missing['sha256'],
            track=unified.TRACK,status='execution_failed',success=False,backend_calls=4,
            final_plan_executions=1,model_calls=1,input_tokens=None if child_case=='unknown_tokens' else 2649,output_tokens=427))
        return dict(success=True,status='completed',cleanup=dict(complete=True))
    monkeypatch.setattr(common,'OwnedResources',Monitor)
    monkeypatch.setattr(common,'run_guarded_command',guarded)
    args={name+'_'+key:value for name in ('scope','oracle','joint_config') for key,value in missing.items()}
    result=common.run_nl_trial(request_path=request['path'],request_sha256=request['sha256'],
        profile_path=profile['path'],profile_sha256=profile['sha256'],method=method,
        output=tmp_path/'run',owned_services=[SimpleNamespace(role='source')],observer=Observer(),**args)
    assert not result['success'] and result['status']=='upstream_source_failure'
    assert not result['can_continue_session'] and stopped
    if child_case=='invalid_identity':
        assert result['model_calls'] is None and result.get('input_tokens') is None
    else:
        assert result['model_calls']==1 and result['output_tokens']==427
        assert result['input_tokens']==(None if child_case=='unknown_tokens' else 2649)
        if snapshot_failure:assert result['error']=='Source accounting not settled'
