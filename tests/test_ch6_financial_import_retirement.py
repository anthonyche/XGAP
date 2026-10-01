from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ch6_financial_import_retirement as retirement
from prepare_rdf_tdb import stream_pin
from xgap.experiments.one_shot_records import write_once


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    old=tmp_path/'old'; root=old/'loaded/rdf-16/load-guard';root.mkdir(parents=True)
    process=write_once(root/'process.json',dict(pid=176003,process_group=176003,created=123.0))
    guard=write_once(root/'receipt.json',dict(schema_version='xgap-process-guard-v1',success=False,
        status='cleanup_incomplete',exit_code=None,attempts=1,automatic_retries=0,
        observed_process_identities=[dict(pid=176003,created=123.0)],
        cleanup=dict(complete=False,live_pids=[176003],pid=176003,signals=['SIGTERM','SIGKILL'])))
    loaded=write_once(old/'loaded/receipt.json',dict(stores={'neo4j-00':{}}))
    resume=dict(job_id='3913895',loaded=loaded,import_retirement=dict(host='compt321',source_id='rdf-16',guard=guard,process=process))
    stage=tmp_path/'new';stage.mkdir();write_once(stage/'handoff.json',dict(resume=resume))
    raw='\n'.join(f'{j}|{s}|2780|{e}|compt321' for j,s,e in [
        ('3913895','FAILED','2:0'),('3913895.batch','FAILED','2:0'),('3913895.extern','COMPLETED','0:0')])+'\n'
    def run(command,stdout,stderr,**kw):
        stdout.write(raw.encode() if command[0]=='sacct' else b'99999\n')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(retirement.subprocess,'run',run)
    monkeypatch.setattr(retirement.socket,'gethostname',lambda:'different-node')
    return stage,resume,raw


def validate(pin,resume):
    spec=resume['import_retirement']
    return retirement.validate(pin,previous_loaded_pin=resume['loaded'],guard_pin=spec['guard'],
        process_pin=spec['process'],source_id=spec['source_id'],expected_job_id=resume['job_id'],expected_host=spec['host'])


def test_retirement_preserves_failure_and_does_not_claim_os_exit(fixture):
    stage,resume,_=fixture
    before=Path(resume['import_retirement']['guard']['path']).read_bytes()
    pin=retirement.capture(stage);doc=retirement.read(pin);out=validate(pin,resume)
    assert doc['scheduler_retired'] and out['os_process_exit_confirmed'] is False
    assert out['original_guard_status']=='cleanup_incomplete' and out['failed_store_reusable'] is False
    assert before==Path(resume['import_retirement']['guard']['path']).read_bytes()
    with pytest.raises(FileExistsError):retirement.capture(stage)


@pytest.mark.parametrize('mutation', ['running','missing_extern','wrong_host','duplicate','empty'])
def test_bad_scheduler_closure_rejected(fixture,mutation):
    _,_,raw=fixture
    if mutation=='running':raw=raw.replace('FAILED','RUNNING',1)
    elif mutation=='missing_extern':raw='\n'.join(raw.splitlines()[:2])
    elif mutation=='wrong_host':raw=raw.replace('compt321','compt300')
    elif mutation=='duplicate':raw+=raw.splitlines()[0]+'\n'
    else:raw=''
    with pytest.raises(ValueError):retirement.terminal_records(raw,'3913895','compt321')


def test_live_same_host_process_blocks_new_load(fixture,monkeypatch):
    import psutil
    stage,resume,_=fixture;pin=retirement.capture(stage)
    monkeypatch.setattr(retirement.socket,'gethostname',lambda:'compt321.local')
    monkeypatch.setattr(psutil,'Process',lambda pid:SimpleNamespace(create_time=lambda:123.0))
    with pytest.raises(ValueError,match='still present'):validate(pin,resume)
    monkeypatch.setattr(psutil,'Process',lambda pid:SimpleNamespace(create_time=lambda:999.0))
    assert validate(pin,resume)['os_process_exit_confirmed'] is True


def test_unrelated_allocation_and_reused_store_rejected(fixture):
    stage,resume,_=fixture;pin=retirement.capture(stage)
    changed=deepcopy(resume);changed['job_id']='1111111'
    with pytest.raises(ValueError,match='binding'):validate(pin,changed)
    loaded=Path(resume['loaded']['path']);loaded.write_text(json.dumps(dict(stores={'rdf-16':{}})))
    resume['loaded']=stream_pin(loaded)
    with pytest.raises(ValueError,match='unsealed'):retirement.validate_spec(resume)


def test_active_allocation_blocks_capture(fixture,monkeypatch):
    stage,resume,raw=fixture
    def run(command,stdout,stderr,**kw):
        stdout.write(raw.encode() if command[0]=='sacct' else b'3913895\n')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(retirement.subprocess,'run',run)
    with pytest.raises(ValueError,match='still active'):retirement.capture(stage)
    assert not (stage/'previous-import-retirement.json').exists()
