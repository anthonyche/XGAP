"""Exercise generated handoff code without SSH, a scheduler or model calls."""
import json
from pathlib import Path
import sys
import types

import pytest

import build_ch6_small_continuation_handoff as handoff


@pytest.fixture
def package(tmp_path, monkeypatch):
    evidence=tmp_path/'evidence'
    parent=evidence/Path(handoff.PARENT_STAGE).relative_to(handoff.ROOT)
    parent.mkdir(parents=True)
    usage=dict(model_calls=65,input_tokens=140424,output_tokens=21064,
               unknown_model_usage=False,sealed_cells=42,unsealed_cells=0)
    (parent/'prepared.json').write_text(json.dumps(dict(release=dict(path='/parent/release.json',sha256='a'*64))))
    (parent/'completion.json').write_text(json.dumps(dict(job_id='3890655',
        study=dict(status='study_harness_failure',usage=usage))))
    (parent/'archive-index.json').write_text(json.dumps(dict(files=[])))
    source='b'*40
    def git(args,**kwargs):
        command=args[1:]
        if command[0]=='rev-parse':return (source+'\n').encode()
        if command[:2]==['bundle','create']:
            Path(command[2]).write_bytes(('# v2 git bundle\n'+source+' '+command[3]+'\n\n').encode())
        if command[:2]==['bundle','list-heads']:
            return Path(command[2]).read_bytes().split(b'\n')[1]+b'\n'
        return b''
    monkeypatch.setattr(handoff.subprocess,'check_output',git)
    result=handoff.build(repo=tmp_path,source_commit=source,parent_evidence=evidence,
        work=tmp_path/'package',archive=tmp_path/'handoff.zip')
    return tmp_path/'package',result


def test_generated_preparation_and_transfer_contract_keep_original_budget_and_inputs(package):
    root,result=package
    cfg=json.loads((root/'handoff.json').read_text())
    assert cfg['inherited_usage']['sealed_cells']==42 and cfg['expected_remaining']==174
    assert cfg['recovery_wall_seconds']+cfg['prior_allocation_seconds']==21600
    assert 'scripts/run_ch6_small_continuation.py' in cfg['allowed_harness_changes']
    assert result['submitted_jobs']==result['backend_calls']==result['model_calls']==0
    assert 'audit(load_pin' in (root/'prepare.py').read_text()
    assert 'Parent sealed evidence changed' in (root/'stage.py').read_text()
    assert 'git(\'init\'' in (root/'stage.py').read_text()
    assert 'clone' not in (root/'stage.py').read_text()


@pytest.mark.parametrize('status,expected_exit',[
    ('all_unattempted_requests_processed',0),('accounting_incomplete',2)])
def test_generated_driver_recognizes_real_continuation_status_without_remote_calls(
        package,tmp_path,monkeypatch,status,expected_exit):
    package_root,result=package
    server=tmp_path/'server';stage=server/Path(result['stage']).relative_to(handoff.ROOT)
    stage.mkdir(parents=True)
    (stage/'credential.once').write_text('fixture-only-never-sent')
    (stage/'credential.once').chmod(0o600)
    (stage/'prepared.json').write_text(json.dumps(dict(continuation=dict(path='/frozen/contract',sha256='a'*64))))
    driver=(package_root/'driver.py').read_text().replace(handoff.ROOT,str(server))
    fake=types.ModuleType('run_ch6_small_continuation')
    calls=[]
    def execute(pin):
        calls.append(pin)
        return dict(status=status,new_usage=dict(sealed_cells=174),cumulative_usage=dict(sealed_cells=216))
    fake.execute=execute
    monkeypatch.setitem(sys.modules,'run_ch6_small_continuation',fake)
    import xgap.experiments.llm_auth_preflight as auth
    monkeypatch.setattr(auth,'check_authentication',lambda **kwargs:dict(success=True,fixture=True))
    failure=types.ModuleType('ch6_failure_archive')
    failure.collect_failure_evidence=lambda *args:dict(fixture=True)
    monkeypatch.setitem(sys.modules,'ch6_failure_archive',failure)
    monkeypatch.setenv('SLURM_JOB_ID','fixture-job')
    monkeypatch.setenv('SLURM_CPUS_PER_TASK','8')
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:tmp_path))
    with pytest.raises(SystemExit) as stopped:exec(compile(driver,'driver.py','exec'),{})
    assert stopped.value.code==expected_exit and len(calls)==1
    receipt=json.loads((stage/'completion.json').read_text())
    assert receipt['success']==(expected_exit==0) and receipt['study']['status']==status
    assert not (stage/'credential.once').exists()
    assert (tmp_path/'xgap-small48-continue-fixture-job.tar.gz').is_file()
