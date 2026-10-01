"""A late source drain cannot erase telemetry from an identity-validated worker."""
from types import SimpleNamespace

import pytest

from xgap.experiments import common_method_trial as common
from xgap.experiments import unified_contract as unified
from xgap.experiments.one_shot_records import write_once


@pytest.mark.parametrize('snapshot_failure',[False,True])
@pytest.mark.parametrize('child_case',['valid','answered','invalid_identity','unknown_tokens','missing'])
def test_worker_telemetry_survives_source_failure_only_after_identity_validation(tmp_path,monkeypatch,snapshot_failure,child_case):
    request=write_once(tmp_path/'request.json',dict(schema_version=common.NL_SCHEMA,
        question_id='q',question='fixture',population='toy',exposure='development'))
    dataset={'dataset_id':'toy','version':'v1'}
    profile=write_once(tmp_path/'profile.json',dict(dataset=dataset))
    missing={'path':str(tmp_path/'not-read.json'),'sha256':'a'*64}
    method=unified.METHODS[0];stopped=[]
    telemetry=dict(model_calls=1,input_tokens=None if child_case=='unknown_tokens' else 2649,output_tokens=427,
        probe_calls=3,backend_calls=8,final_plan_executions=1,top_level_attempts=1,
        planning_ms=1337.25,planning_cpu_ms=1276.75,execution_ms=70062.0,end_to_end_ms=74627.0,
        acquisition_ms=40.0,clarification_calls=2,scope_confirmation_calls=1,total_user_calls=3,
        physical_actions=4,physical_prepare_attempts=1,certificate_ms=11.25,certificate_checks=714,
        estimate_evaluations=49,expanded_states=461,root_gap=None,
        realized_trace_work_estimate=141823.6,realized_acquisition_cost_estimate=0.04,
        selected_execution_cost_estimate=141818.5,terminal_certificate={'status':'certified'},
        interpretation_diagnostics={'status':'interpreted'},cost_scope='declared worker cost units',
        error=None,error_type=None)
    class Monitor:
        def __init__(self,*a,**kw):pass
        def sample(self,members):return None
        def stop(self):stopped.append(True);return dict(complete=True,recovery_ms=0)
        def summary(self):return dict(status='within_observed_budget')
    observed=dict(requests=8,forwarded_requests=8,failed_requests=1,late_calls=0,
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
        if child_case!='missing':
            telemetry['result']=write_once(tmp_path/'run/worker/answer.json',dict(rows=[]))
            write_once(tmp_path/'run/worker/receipt.json',dict(schema_version='xgap-nl-method-worker-v1',
                method=method,request_sha256=request['sha256'],question_id='wrong' if child_case=='invalid_identity' else 'q',dataset=dataset,
                profile_sha256=profile['sha256'],scope_sha256=missing['sha256'],
                oracle_sha256=missing['sha256'],joint_config_sha256=missing['sha256'],
                track=unified.TRACK,status='answered' if child_case=='answered' else 'execution_failed',
                success=child_case=='answered',**telemetry))
        return dict(success=True,status='completed',cleanup=dict(complete=True))
    monkeypatch.setattr(common,'OwnedResources',Monitor)
    monkeypatch.setattr(common,'run_guarded_command',guarded)
    args={name+'_'+key:value for name in ('scope','oracle','joint_config') for key,value in missing.items()}
    result=common.run_nl_trial(request_path=request['path'],request_sha256=request['sha256'],
        profile_path=profile['path'],profile_sha256=profile['sha256'],method=method,
        output=tmp_path/'run',owned_services=[SimpleNamespace(role='source')],observer=Observer(),**args)
    assert not result['success'] and result['status']=='upstream_source_failure'
    assert not result['can_continue_session'] and stopped
    if child_case in ('invalid_identity','missing'):
        for key in telemetry:
            if key not in ('error','error_type'):
                assert result.get('method_cost_scope' if key=='cost_scope' else key) is None,key
    else:
        for key,value in telemetry.items():
            if key not in ('error','error_type'):
                assert result.get('method_cost_scope' if key=='cost_scope' else key)==value,key
        if snapshot_failure:
            assert result['error']=='Source accounting not settled'
            assert result['error_type']=='RuntimeError'
            # Never substitute worker end-to-end time for missing outer timing.
            assert result.get('decision_e2e_ms') is None
