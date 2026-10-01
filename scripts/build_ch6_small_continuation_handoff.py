"""Build a self-contained CPU handoff for the unattempted small48 complement.

No scheduler or model calls are made by this builder. Parent observations remain
immutable; recovery wall accounting is explicit and retains spent model usage.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid
import zipfile

ROOT = '/home/hxc859/xgap-ch6-artifacts'
PARENT_STAGE = ROOT + '/small48-fixed-f40dfa9-independent-v1'
PARENT_ARCHIVE = '/home/hxc859/xgap-small48-fixed-3890655.tar.gz'
PARENT_ARCHIVE_SHA = 'dfd92ed079c0b7793a25855c39f7b31ff5d9e84f1219a02487647ea13e8c4aab'
PYTHON = ROOT + '/linux-runtime-v3/author-venv/bin/python'
HARNESS = ['scripts/run_ch6_small_continuation.py', 'scripts/ch6_external_session.py', 'src/xgap/experiments/process_guard.py',
           'src/xgap/experiments/owned_resources.py']


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build(*, repo, source_commit, parent_evidence, work, archive):
    repo, parent_evidence, work, archive = map(Path, (repo, parent_evidence, work, archive))
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=repo, env=env).decode().strip()
    if git('rev-parse', source_commit) != source_commit or len(source_commit) != 40:
        raise ValueError('Exact source commit required')
    parent_stage = parent_evidence / Path(PARENT_STAGE).relative_to(ROOT)
    prepared = json.loads((parent_stage / 'prepared.json').read_text())
    completion = json.loads((parent_stage / 'completion.json').read_text())
    usage = completion['study']['usage']
    if (completion['job_id'] != '3890655' or completion['study']['status'] != 'study_harness_failure'
            or usage != dict(model_calls=65, input_tokens=140424, output_tokens=21064,
                             unknown_model_usage=False, sealed_cells=42, unsealed_cells=0)):
        raise ValueError('Parent terminal identity or accounting differs')
    short = source_commit[:7]
    stage = ROOT + '/small48-continue-' + short + '-v1'
    checkout = ROOT + '/XGAP-small48-continue-' + short
    contract = dict(source_commit=source_commit, parent_release=prepared['release'],
                    parent_completion_sha256=digest((parent_stage / 'completion.json').read_bytes()),
                    parent_archive_index_sha256=digest((parent_stage / 'archive-index.json').read_bytes()),
                    parent_archive_sha256=PARENT_ARCHIVE_SHA, parent_job='3890655',
                    stage=stage, checkout=checkout, inherited_usage=usage,
                    recovery_wall_seconds=19632, prior_allocation_seconds=1968,
                    expected_remaining=174, unique_cases=48, supported_requests=216,
                    automatic_retries=0, allowed_harness_changes=HARNESS,
                    wall_policy='active recovery allocation excludes idle handoff; cumulative allocated seconds <= 21600',
                    backend_calls=0, model_calls=0, submitted_jobs=0)
    work.mkdir(parents=True, exist_ok=False)
    (work / 'handoff.json').write_text(json.dumps(contract, indent=2) + '\n')
    ref = 'refs/xgap-handoff/' + uuid.uuid4().hex
    git('update-ref', ref, source_commit, '')
    try:
        git('bundle', 'create', str(work / 'source.bundle'), ref)
    finally:
        git('update-ref', '-d', ref, source_commit)
    with (work / 'source.bundle').open('rb') as stream:
        header = []
        while True:
            line = stream.readline()
            if line == b'\n': break
            if not line or len(header) > 100: raise ValueError('Invalid bundle header')
            header.append(line)
    if any(line.startswith(b'-') for line in header):
        raise ValueError('Continuation bundle must be independent')
    if git('bundle', 'list-heads', str(work / 'source.bundle')) != source_commit + ' ' + ref:
        raise ValueError('Bundle source differs')
    (work / 'prepare.py').write_text('''from pathlib import Path
import json
from run_ch6_small_continuation import prepare
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.ch6_small_release import audit
from xgap.experiments.ch6_formal_protocol import load_pin
J=Path(__STAGE__)
c=json.loads((J/'handoff.json').read_text())
checked=audit(load_pin(c['parent_release']))
if not checked['success']:raise ValueError('Parent release audit failed: '+str(checked.get('failed_checks')))
pin=prepare(parent_release=c['parent_release'],output=J/'continuation',
 source_commit=c['source_commit'],recovery_wall_seconds=c['recovery_wall_seconds'],
 prior_allocation_seconds=c['prior_allocation_seconds'],allowed_harness_changes=c['allowed_harness_changes'])
d=json.loads(Path(pin['path']).read_text())
if d['remaining_cells']!=c['expected_remaining'] or d['prior_usage']!=c['inherited_usage']:
 raise ValueError('Continuation complement or inherited usage differs')
write_once(J/'prepared.json',dict(continuation=pin))
print(json.dumps(dict(prepared=True,continuation=pin,model_calls=0,backend_calls=0)),flush=True)
'''.replace('__STAGE__', repr(stage)))
    driver = '''from pathlib import Path
import json,os,socket,tarfile,traceback
from run_ch6_small_continuation import execute
from xgap.experiments.llm_auth_preflight import check_authentication
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.evidence_store import file_pin
J=Path(__STAGE__);R=Path(__ROOT__)
result=dict(success=False,purpose='small_real_continuation',source_commit=__SOURCE__,
 parent_job='3890655',job_id=os.environ.get('SLURM_JOB_ID'),node=socket.gethostname(),
 formal_campaign_ready=False)
secret=J/'credential.once'
try:
 if not os.environ.get('SLURM_JOB_ID'):raise ValueError('CPU allocation required')
 if secret.is_symlink() or secret.stat().st_mode & 0o077:raise ValueError('Credential permissions differ')
 key=secret.read_text().strip();secret.unlink()
 if not key:raise ValueError('Empty credential')
 os.environ['XGAP_EXTERNAL_LLM_API_KEY']=key;del key
 write_once(J/'host.json',dict(node=socket.gethostname(),job_id=os.environ['SLURM_JOB_ID'],
  allocated_cpus=os.environ.get('SLURM_CPUS_PER_TASK'),gpu_requested=False))
 auth=check_authentication(base_url='http://112.95.75.67:9018/v1',model='qwen3.8-27b',
  api_key=os.environ['XGAP_EXTERNAL_LLM_API_KEY'])
 result['startup_authentication']=write_once(J/'authentication-preflight.json',auth)
 if not auth['success']:raise ValueError('Authentication failed before source loading')
 pin=json.loads((J/'prepared.json').read_text())['continuation']
 outcome=execute(pin)
 result.update(study=outcome,success=outcome['status']=='all_unattempted_requests_processed')
except (Exception,KeyboardInterrupt) as exc:
 result.update(error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc())
finally:
 os.environ.pop('XGAP_EXTERNAL_LLM_API_KEY',None)
 if secret.exists():secret.unlink()
try:
 from ch6_failure_archive import collect_failure_evidence
 result['failure_evidence']=collect_failure_evidence(J/'continuation/results',J/'failure-evidence')
except Exception as exc:result['failure_evidence_collection_error']=type(exc).__name__
write_once(J/'completion.json',result)
allowed={'terminal.json','score.json','query-loss.json','receipt.json','intent.json','identity.json',
 'ready.json','closed.json','core.json.gz','interpretation.json','plan.json','answer.json',
 'profile.json','entry-profile.json','entry-profile-receipt.json'}
files=[];omitted=0;omitted_bytes=0
for p in sorted(J.rglob('*')):
 if p.is_symlink() or not p.is_file():continue
 include=(p.name in allowed or p.name.endswith(('-summary.json','-index.json')) or
  ('results' not in p.relative_to(J).parts and p.suffix in ('.json','.csv','.py','.sbatch','.sh')))
 if include and p.stat().st_size<=4*1024**2:files.append(p)
 else:omitted+=1;omitted_bytes+=p.stat().st_size
if sum(p.stat().st_size for p in files)>512*1024**2:raise ValueError('Summary archive limit; raw evidence retained')
pin=write_once(J/'archive-index.json',dict(files=[file_pin(p) for p in files],
 omitted_files=omitted,omitted_bytes=omitted_bytes,all_raw_evidence_retained_on_server=True))
files.append(Path(pin['path']))
archive=Path.home()/('xgap-small48-continue-'+os.environ.get('SLURM_JOB_ID','nojob')+'.tar.gz')
with archive.open('xb') as stream,tarfile.open(fileobj=stream,mode='w:gz') as tar:
 for p in files:tar.add(p,arcname=str(p.relative_to(R)),recursive=False)
print(json.dumps(dict(success=result['success'],purpose=result['purpose'],
 status=result.get('study',{}).get('status'),new_usage=result.get('study',{}).get('new_usage'),
 cumulative_usage=result.get('study',{}).get('cumulative_usage'),error=result.get('error'),
 archive=file_pin(archive),formal_campaign_ready=False)),flush=True)
raise SystemExit(0 if result['success'] else 2)
'''
    for key, value in [('STAGE', stage), ('ROOT', ROOT), ('SOURCE', source_commit)]:
        driver = driver.replace('__' + key + '__', repr(value))
    (work / 'driver.py').write_text(driver)
    (work / 'run.sbatch').write_text(f'''#!/bin/bash
#SBATCH --job-name=xgap-small48-cont
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --time=05:45:00
#SBATCH --no-requeue
set -euo pipefail
umask 077
trap 'rm -f {stage}/credential.once' EXIT
module load Miniconda3/23.10.0-1
cd {checkout}
export PYTHONPATH=src:scripts
export PYTHONDONTWRITEBYTECODE=1
{PYTHON} {stage}/driver.py
''')
    (work / 'README.md').write_text(
        '# small48 continuation after 3890655\n\n'
        'Retain all 42 sealed requests; execute only the 174 unattempted requests.\n'
        'The original 48 questions, algorithm configuration and per-request limits remain fixed.\n'
        'The prior failed/censored requests are not retried or overwritten.\n'
        'Only harness cleanup/diagnostics and explicit continuation change.\n'
        'Inherit 65 model calls, 140424 input tokens and 21064 output tokens.\n'
        'Recovery time is capped at 19632 seconds, plus prior 1968 allocated seconds <= 6 hours.\n'
        'This explicitly excludes offline handoff delay; it is not the old absolute-deadline policy.\n'
        '8 CPUs / 24 GiB / no GPU / no pinned node. Authentication is recorded separately.\n')
    pins = {p.name: digest(p.read_bytes()) for p in work.iterdir()}
    stage_code = '''from pathlib import Path
import getpass,hashlib,json,os,subprocess,zipfile
J=Path(__STAGE__);CHECKOUT=Path(__CHECKOUT__);SOURCE=__SOURCE__;pins=__PINS__;ref=__REF__
if any(p.exists() or p.is_symlink() for p in (J,CHECKOUT)):
 raise ValueError('Continuation attempt exists; inspect it, never submit twice')
parent=Path(__PARENT_STAGE__)
if hashlib.sha256((parent/'completion.json').read_bytes()).hexdigest()!=__COMPLETION_SHA__:
 raise ValueError('Parent completion changed')
if hashlib.sha256(Path(__PARENT_ARCHIVE__).read_bytes()).hexdigest()!=__PARENT_ARCHIVE_SHA__:
 raise ValueError('Parent evidence archive differs')
index_data=(parent/'archive-index.json').read_bytes()
if hashlib.sha256(index_data).hexdigest()!=__PARENT_INDEX_SHA__:
 raise ValueError('Parent archive index changed')
for item in json.loads(index_data)['files']:
 file=Path(item['path'])
 if not str(file).startswith(__ROOT_PREFIX__) or file.is_symlink():
  raise ValueError('Parent evidence path is redirected')
 payload=file.read_bytes()
 if len(payload)!=item['bytes'] or hashlib.sha256(payload).hexdigest()!=item['sha256']:
  raise ValueError('Parent sealed evidence changed: '+str(file))
with zipfile.ZipFile(str(Path.home()/__ARCHIVE_NAME__)) as z:
 if len(z.namelist())!=len(pins)+1 or set(z.namelist())!=set(pins)|{'stage.py'}:
  raise ValueError('Unexpected handoff members')
 data={name:z.read(name) for name in pins}
for name,content in data.items():
 if hashlib.sha256(content).hexdigest()!=pins[name]:raise ValueError('Handoff member changed: '+name)
os.umask(0o077);J.mkdir(mode=0o700);CHECKOUT.mkdir(mode=0o700)
for name,content in data.items():(J/name).write_bytes(content)
env={k:v for k,v in os.environ.items() if not k.startswith('GIT_') and k!='XGAP_EXTERNAL_LLM_API_KEY'}
env.update(PYTHONPATH=str(CHECKOUT/'src')+':'+str(CHECKOUT/'scripts'),PYTHONDONTWRITEBYTECODE='1')
def git(*args):return subprocess.check_output(['git']+list(args),cwd=str(CHECKOUT),env=env)
git('init','--quiet');git('bundle','verify',str(J/'source.bundle'))
git('fetch',str(J/'source.bundle'),ref);git('checkout','--detach',SOURCE)
if (CHECKOUT/'.git/objects/info/alternates').exists():raise ValueError('Unexpected alternate objects')
git('fsck','--connectivity-only','--no-dangling')
if git('rev-parse','HEAD').decode().strip()!=SOURCE or git('status','--porcelain'):
 raise ValueError('Source checkout differs')
subprocess.check_call(['bash','-n',str(J/'run.sbatch')],env=env)
subprocess.check_call([__PYTHON__,str(J/'prepare.py')],cwd=str(CHECKOUT),env=env)
if not os.isatty(0):raise ValueError('Interactive hidden credential input required')
key=getpass.getpass('LLM API key (hidden input): ').strip()
if not key:raise ValueError('Empty key; no submission')
with (J/'credential.once').open('x') as f:f.write(key)
os.chmod(J/'credential.once',0o600);del key
with (J/'submission-stdout.txt').open('xb') as out,(J/'submission-stderr.txt').open('xb') as err:
 run=subprocess.run(['sbatch','--parsable','--output='+str(J/'small48-continue-%j.out'),str(J/'run.sbatch')],
  stdout=out,stderr=err,env=env)
(J/'submission-exit-code.txt').write_text(str(run.returncode)+'\\n')
if run.returncode:
 (J/'credential.once').unlink();print((J/'submission-stderr.txt').read_text());raise SystemExit(run.returncode)
print('SUBMISSION '+(J/'submission-stdout.txt').read_text().strip(),flush=True)
'''
    replacements = dict(STAGE=stage, CHECKOUT=checkout, SOURCE=source_commit, PINS=pins, REF=ref,
                        PARENT_STAGE=PARENT_STAGE, COMPLETION_SHA=contract['parent_completion_sha256'],
                        PARENT_INDEX_SHA=contract['parent_archive_index_sha256'], ROOT_PREFIX=ROOT+'/',
                        PARENT_ARCHIVE=PARENT_ARCHIVE, PARENT_ARCHIVE_SHA=PARENT_ARCHIVE_SHA,
                        ARCHIVE_NAME=archive.name, PYTHON=PYTHON)
    for key, value in replacements.items():
        stage_code = stage_code.replace('__' + key + '__', repr(value))
    (work / 'stage.py').write_text(stage_code)
    for name in ('stage.py', 'prepare.py', 'driver.py'):
        compile((work / name).read_text(), name, 'exec')
    subprocess.check_call(['bash', '-n', str(work / 'run.sbatch')])
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(work.iterdir()): z.write(p, p.name)
    result = dict(path=str(archive), sha256=digest(archive.read_bytes()), bytes=archive.stat().st_size,
                  source_commit=source_commit, parent_job='3890655', remaining=174,
                  model_calls=0, backend_calls=0, submitted_jobs=0, stage=stage, checkout=checkout)
    (work.parent / (work.name + '-verification.json')).write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('repo', 'source-commit', 'parent-evidence', 'work', 'archive'):
        parser.add_argument('--' + arg, required=True)
    print(json.dumps(build(**vars(parser.parse_args())), indent=2))
