"""Exercise recovery package preparation without model, backend or scheduler calls."""
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import types

import pytest

import build_ch6_small_chain_handoff as handoff


def pin(path):
    data=path.read_bytes()
    return dict(path=str(path),sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))


@pytest.fixture
def package(tmp_path,monkeypatch):
    server=tmp_path/'server';server.mkdir()
    parent=server/'parent';first=server/'first';parent.mkdir();first.mkdir()
    for key,value in dict(ROOT=str(server),PARENT_STAGE=str(parent),FIRST_STAGE=str(first),
                          PYTHON=str(server/'python')).items():monkeypatch.setattr(handoff,key,value)
    parent_release=parent/'release.json';parent_release.write_text('{}')
    first_contract=first/'continuation.json';first_contract.write_text('{}')
    parentpin=pin(parent_release);firstpin=pin(first_contract)
    (parent/'prepared.json').write_text(json.dumps(dict(release=parentpin)))
    (parent/'completion.json').write_text(json.dumps(dict(job_id='3890655')))
    (first/'prepared.json').write_text(json.dumps(dict(continuation=firstpin)))
    (first/'handoff.json').write_text(json.dumps(dict(parent_release=parentpin)))
    (first/'completion.json').write_text(json.dumps(dict(job_id='3891655',parent_job='3890655',
        study=dict(status='accounting_incomplete',contract=firstpin,elapsed_seconds=12230.97,
                   new_usage=dict(sealed_cells=135,unsealed_cells=0)))))
    for name,root in [('PARENT',parent),('FIRST',first)]:
        (root/'archive-index.json').write_text(json.dumps(dict(files=[pin(p) for p in root.iterdir()])))
        archive=tmp_path/(name+'.tar.gz');archive.write_bytes(b'fixture archival bytes '+name.encode())
        monkeypatch.setattr(handoff,name+'_ARCHIVE',str(archive))
        monkeypatch.setattr(handoff,name+'_ARCHIVE_SHA',pin(archive)['sha256'])
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
    result=handoff.build(repo=tmp_path,source_commit=source,parent_evidence=server,first_evidence=server,
                        work=tmp_path/'package',archive=tmp_path/'handoff.zip')
    return tmp_path/'package',result


def test_contract_preserves_both_attempts_and_fixed_39_complement(package):
    root,result=package;cfg=json.loads((root/'handoff.json').read_text())
    assert cfg['parent_jobs']==['3890655','3891655']
    assert len(cfg['evidence'])==2 and cfg['inherited_usage']['sealed_cells']==177
    assert cfg['expected_remaining']==39 and cfg['supported_requests']==216
    assert cfg['inherited_usage']['model_calls']==468
    assert cfg['inherited_usage']['input_tokens']==868493
    assert cfg['inherited_usage']['output_tokens']==103775
    assert cfg['total_allocated_seconds']==21600 and cfg['startup_cleanup_reserve_seconds']==900
    assert result['submitted_jobs']==result['backend_calls']==result['model_calls']==0
    assert 'clone' not in (root/'stage.py').read_text()
    batch=(root/'run.sbatch').read_text()
    assert '--cpus-per-task=8' in batch and '--mem=24G' in batch
    assert 'nodelist' not in batch and 'gres=' not in batch


def stage_runtime(package,tmp_path,monkeypatch,*,state='FAILED',elapsed=12300):
    root,result=package;source=json.loads((root/'handoff.json').read_text())['source_commit']
    calls=[];prompts=[]
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:tmp_path))
    def output(args,**kwargs):
        if args[0]=='sacct':return ('3891655|'+state+'|'+str(elapsed)+'|\n').encode()
        if args[:3]==['git','rev-parse','HEAD']:return (source+'\n').encode()
        return b''
    monkeypatch.setattr(handoff.subprocess,'check_output',output)
    monkeypatch.setattr(handoff.subprocess,'check_call',lambda *args,**kwargs:0)
    def run(args,**kwargs):
        calls.append(args);kwargs['stdout'].write(b'9000000\n')
        assert 'XGAP_EXTERNAL_LLM_API_KEY' not in kwargs['env']
        return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr(handoff.subprocess,'run',run)
    monkeypatch.setattr(handoff.os,'isatty',lambda _:True)
    import getpass
    keys=iter([' ','fixture-key-never-sent'])
    def get_key(prompt):prompts.append(prompt);return next(keys)
    monkeypatch.setattr(getpass,'getpass',get_key)
    monkeypatch.setenv('XGAP_EXTERNAL_LLM_API_KEY','not-inherited')
    return (root/'stage.py').read_text(),calls,prompts,Path(result['stage'])


def test_stage_checks_archives_preserves_wall_cap_and_reprompts_empty_key(package,tmp_path,monkeypatch):
    code,calls,prompts,stage=stage_runtime(package,tmp_path,monkeypatch)
    exec(compile(code,'stage.py','exec'),{})
    assert len(calls)==1 and len(prompts)==2
    assert '--time=122' in calls[0]
    allocation=json.loads((stage/'prior-allocation.json').read_text())
    assert allocation['prior_allocations_seconds']==[1968,12300]
    assert allocation['slurm_allocation_seconds']==7320
    assert allocation['recovery_wall_seconds']==6420
    assert allocation['startup_cleanup_reserve_seconds']==900
    assert sum(allocation['prior_allocations_seconds'])+allocation['slurm_allocation_seconds']<=21600
    assert (stage/'credential.once').stat().st_mode & 0o777==0o600
    with pytest.raises(ValueError,match='never submit twice'):exec(compile(code,'stage.py','exec'),{})
    assert len(calls)==1


@pytest.mark.parametrize('state,elapsed,message',[
    ('RUNNING',12300,'not terminal'),('FAILED',21000,'No valid remaining'),
    ('FAILED',10,'No valid remaining')])
def test_stage_refuses_unresolved_or_overbudget_accounting_before_mutation(
        package,tmp_path,monkeypatch,state,elapsed,message):
    code,calls,prompts,stage=stage_runtime(package,tmp_path,monkeypatch,state=state,elapsed=elapsed)
    with pytest.raises(ValueError,match=message):exec(compile(code,'stage.py','exec'),{})
    assert not stage.exists() and not calls and not prompts


def test_stage_rejects_mutated_sealed_evidence_before_any_submission(package,tmp_path,monkeypatch):
    root,_=package;cfg=json.loads((root/'handoff.json').read_text())
    # Indexed public release tampering is detected, even when archive/completion are unchanged.
    Path(cfg['parent_release']['path']).write_text('{"tampered":true}')
    code,calls,prompts,stage=stage_runtime(package,tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='Historical sealed evidence changed'):exec(compile(code,'stage.py','exec'),{})
    assert not stage.exists() and not calls and not prompts


@pytest.mark.parametrize('wrong_count',[False,True])
def test_generated_prepare_verifies_complement_and_reconciled_usage(package,monkeypatch,wrong_count):
    root,result=package;stage=Path(result['stage']);stage.mkdir()
    cfg=json.loads((root/'handoff.json').read_text())
    (stage/'handoff.json').write_text(json.dumps(cfg))
    (stage/'prior-allocation.json').write_text(json.dumps(dict(prior_allocations_seconds=[1968,12300],recovery_wall_seconds=6420)))
    fake=types.ModuleType('run_ch6_small_chain_continuation');seen=[]
    def prepare(**kwargs):
        seen.append(kwargs);output=kwargs['output'];output.mkdir()
        p=output/'continuation.json'
        p.write_text(json.dumps(dict(remaining_cells=38 if wrong_count else 39,prior_usage=cfg['inherited_usage'],recovery_wall_seconds=6420)))
        return pin(p)
    fake.prepare=prepare;monkeypatch.setitem(sys.modules,'run_ch6_small_chain_continuation',fake)
    import xgap.experiments.ch6_small_release as release
    monkeypatch.setattr(release,'audit',lambda doc:dict(success=True))
    if wrong_count:
        with pytest.raises(ValueError,match='complement'):exec(compile((root/'prepare.py').read_text(),'prepare.py','exec'),{})
        assert not (stage/'prepared.json').exists()
    else:
        exec(compile((root/'prepare.py').read_text(),'prepare.py','exec'),{})
        assert (stage/'prepared.json').is_file()
    assert seen[0]['prior_allocations_seconds']==[1968,12300]
    assert seen[0]['recovery_wall_seconds']==6420


def test_prepare_audits_frozen_inputs_before_continuation_or_key(package,monkeypatch):
    root,result=package;stage=Path(result['stage']);stage.mkdir()
    (stage/'handoff.json').write_bytes((root/'handoff.json').read_bytes())
    (stage/'prior-allocation.json').write_text(json.dumps(dict(prior_allocations_seconds=[1968,12300],recovery_wall_seconds=6420)))
    fake=types.ModuleType('run_ch6_small_chain_continuation');seen=[]
    fake.prepare=lambda **kwargs:seen.append(kwargs)
    monkeypatch.setitem(sys.modules,'run_ch6_small_chain_continuation',fake)
    import xgap.experiments.ch6_small_release as release
    monkeypatch.setattr(release,'audit',lambda doc:dict(success=False,failed_checks=['source changed']))
    with pytest.raises(ValueError,match='Frozen input audit failed'):
        exec(compile((root/'prepare.py').read_text(),'prepare.py','exec'),{})
    assert not seen and not (stage/'prepared.json').exists()


@pytest.mark.parametrize('status,expected_exit',[
    ('all_unattempted_requests_processed',0),('accounting_incomplete',2)])
def test_generated_driver_retains_timing_closure_and_removes_secret(
        package,tmp_path,monkeypatch,status,expected_exit):
    root,result=package;stage=Path(result['stage']);stage.mkdir()
    (stage/'credential.once').write_text('fixture-only-never-sent');(stage/'credential.once').chmod(0o600)
    (stage/'prepared.json').write_text(json.dumps(dict(continuation=dict(path='/frozen/contract',sha256='a'*64))))
    fake=types.ModuleType('run_ch6_small_chain_continuation');calls=[]
    def execute(ref):
        calls.append(ref);p=stage/'continuation/results/session';p.mkdir(parents=True)
        (p/'timing.json').write_text('{"elapsed":1}')
        (p/'session-finalization.json').write_text('{"closed":true}')
        return dict(status=status,new_usage=dict(sealed_cells=39),cumulative_usage=dict(sealed_cells=216))
    fake.execute=execute;monkeypatch.setitem(sys.modules,'run_ch6_small_chain_continuation',fake)
    import xgap.experiments.llm_auth_preflight as auth
    monkeypatch.setattr(auth,'check_authentication',lambda **kwargs:dict(success=True,fixture=True))
    failure=types.ModuleType('ch6_failure_archive');failure.collect_failure_evidence=lambda *args:dict(fixture=True)
    monkeypatch.setitem(sys.modules,'ch6_failure_archive',failure)
    monkeypatch.setenv('SLURM_JOB_ID','fixture-job');monkeypatch.setenv('SLURM_CPUS_PER_TASK','8')
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:tmp_path))
    with pytest.raises(SystemExit) as stopped:exec(compile((root/'driver.py').read_text(),'driver.py','exec'),{})
    assert stopped.value.code==expected_exit and len(calls)==1
    assert not (stage/'credential.once').exists()
    archive=tmp_path/'xgap-small48-final39-fixture-job.tar.gz'
    with tarfile.open(archive) as tar:
        names=tar.getnames()
        assert any(name.endswith('/timing.json') for name in names)
        assert any(name.endswith('/session-finalization.json') for name in names)
        assert not any(name.endswith('/credential.once') for name in names)
    completion=json.loads((stage/'completion.json').read_text())
    assert completion['success']==(expected_exit==0)
