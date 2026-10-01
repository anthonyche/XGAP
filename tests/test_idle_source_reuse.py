"""Pre-execution rejection may retain only demonstrably untouched live sources."""
from types import SimpleNamespace
import pytest

from xgap.experiments import common_method_trial as common
from xgap.experiments import unified_contract as unified
from xgap.experiments.one_shot_records import write_once


def evidence():
    result=dict(method=unified.METHODS[0],status='proposal_failed',success=False)
    child=dict(status='proposal_failed',backend_calls=0,final_plan_executions=0)
    guard=dict(success=True,status='completed',cleanup=dict(complete=True))
    observed=dict(requests=0,forwarded_requests=0,failed_requests=0,late_calls=0,
                  persistence_failures=0,failure_categories={},phase_seal={'path':'sealed'})
    return result,child,guard,observed


@pytest.mark.parametrize('change',[
    lambda r,c,g,o:r.update(method='aruqula-fedx'),
    lambda r,c,g,o:r.update(status='execution_failed'),
    lambda r,c,g,o:c.update(backend_calls=1),
    lambda r,c,g,o:c.update(final_plan_executions=1),
    lambda r,c,g,o:g.update(success=False),
    lambda r,c,g,o:g['cleanup'].update(complete=False),
    lambda r,c,g,o:o.update(requests=1),
    lambda r,c,g,o:o.update(late_calls=1),
    lambda r,c,g,o:o.update(persistence_failures=1),
    lambda r,c,g,o:o.pop('phase_seal'),
])
def test_uncertain_or_used_sources_are_never_reused(change):
    args=evidence();assert common._idle_source_reusable(*args,sealed=True)
    change(*args);assert not common._idle_source_reusable(*args,sealed=True)


@pytest.mark.parametrize('source_calls,release_error,retain',[(0,False,True),(1,False,False),(0,True,False)])
def test_trial_retains_only_released_empty_phase(tmp_path,monkeypatch,source_calls,release_error,retain):
    request=write_once(tmp_path/'request.json',dict(schema_version=common.NL_SCHEMA,
        question_id='q',question='fixture',population='toy',exposure='development'))
    dataset={'dataset_id':'toy','version':'v1'}
    profile=write_once(tmp_path/'profile.json',dict(dataset=dataset))
    missing={'path':str(tmp_path/'not-read.json'),'sha256':'a'*64}
    method=unified.METHODS[0];stopped=[];released=[]
    class Monitor:
        def __init__(self,*a,**kw):pass
        def sample(self,members):return None
        def stop(self):stopped.append(True);return dict(complete=True,recovery_ms=0)
        def summary(self):return dict(status='within_observed_budget')
    class Observer:
        def set_phase(self,phase):self.phase=phase
        def snapshot(self,phase):
            assert phase==self.phase
            return dict(evidence()[3],requests=source_calls)
        def seal_phase(self,phase):return self.snapshot(phase)
        def release_phase(self,phase,pin):
            if release_error:raise OSError('simulated persistence failure')
            released.append(pin)
    def guarded(command,**kwargs):
        (tmp_path/'run/worker').mkdir()
        write_once(tmp_path/'run/worker/receipt.json',dict(schema_version='xgap-nl-method-worker-v1',
            method=method,request_sha256=request['sha256'],question_id='q',dataset=dataset,
            profile_sha256=profile['sha256'],scope_sha256=missing['sha256'],
            oracle_sha256=missing['sha256'],joint_config_sha256=missing['sha256'],
            track=unified.TRACK,status='proposal_failed',success=False,backend_calls=0,
            final_plan_executions=0,model_calls=1,input_tokens=10,output_tokens=2))
        return evidence()[2]
    monkeypatch.setattr(common,'OwnedResources',Monitor)
    monkeypatch.setattr(common,'run_guarded_command',guarded)
    args={name+'_'+key:value for name in ('scope','oracle','joint_config') for key,value in missing.items()}
    result=common.run_nl_trial(request_path=request['path'],request_sha256=request['sha256'],
        profile_path=profile['path'],profile_sha256=profile['sha256'],method=method,
        output=tmp_path/'run',owned_services=[SimpleNamespace(role='source')],observer=Observer(),**args)
    assert not result['success'] and result['status']=='proposal_failed'
    assert result['can_continue_session']==retain
    assert bool(stopped)==(not retain)
    assert result['model_calls']==1 and result['input_tokens']==10
    if retain:
        assert released and result['quiescence']['complete']
        assert result['quiescence']['new_serving_session_required'] is False
