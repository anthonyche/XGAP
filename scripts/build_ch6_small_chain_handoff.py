"""Build an independent CPU handoff for the final unattempted small48 requests.

Preserve previous attempts and reconcile known worker usage append-only.
The builder performs no model, backend, scheduler, or credential operations.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import uuid
import zipfile

ROOT='/home/hxc859/xgap-ch6-artifacts'
PARENT_STAGE=ROOT+'/small48-fixed-f40dfa9-independent-v1'
FIRST_STAGE=ROOT+'/small48-continue-2a8e16e-v1'
PARENT_ARCHIVE='/home/hxc859/xgap-small48-fixed-3890655.tar.gz'
PARENT_ARCHIVE_SHA='dfd92ed079c0b7793a25855c39f7b31ff5d9e84f1219a02487647ea13e8c4aab'
FIRST_ARCHIVE='/home/hxc859/xgap-small48-continue-3891655.tar.gz'
FIRST_ARCHIVE_SHA='a5b5e6430f511e966146c583ae215bfabf6c4350fac10869109dce0a38748ce2'
PYTHON=ROOT+'/linux-runtime-v3/author-venv/bin/python'


def digest(data):return hashlib.sha256(data).hexdigest()


def build(*,repo,source_commit,parent_evidence,first_evidence,work,archive,completed_handoffs=(),
          batch_total_wall_seconds=21600):
    if type(batch_total_wall_seconds) is not int or batch_total_wall_seconds not in (21600,28800):
        raise ValueError('Only the original 6-hour or explicit 8-hour administrative allocation is supported')
    if not isinstance(completed_handoffs,(list,tuple)) or len(completed_handoffs)>216:
        raise ValueError('A bounded ordered continuation history is required')
    repo,parent_evidence,first_evidence,work,archive=map(Path,(repo,parent_evidence,first_evidence,work,archive))
    env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
    def git(*args):return subprocess.check_output(['git',*args],cwd=repo,env=env).decode().strip()
    if len(source_commit)!=40 or git('rev-parse',source_commit)!=source_commit:
        raise ValueError('Exact source commit required')
    parent=parent_evidence/Path(PARENT_STAGE).relative_to(ROOT)
    first=first_evidence/Path(FIRST_STAGE).relative_to(ROOT)
    original=json.loads((parent/'prepared.json').read_text())
    completion=json.loads((first/'completion.json').read_text())
    prepared=json.loads((first/'prepared.json').read_text())
    prior=json.loads((first/'handoff.json').read_text())
    if (completion.get('job_id')!='3891655' or completion.get('parent_job')!='3890655'
            or completion['study'].get('status')!='accounting_incomplete'
            or completion['study']['new_usage'].get('sealed_cells')!=135
            or completion['study']['new_usage'].get('unsealed_cells')!=0
            or prepared['continuation']!=completion['study']['contract']
            or prior['parent_release']!=original['release']):
        raise ValueError('Frozen two-attempt chain identity differs')
    stages=[]
    for root,server,path,sha in [(parent,PARENT_STAGE,PARENT_ARCHIVE,PARENT_ARCHIVE_SHA),
                               (first,FIRST_STAGE,FIRST_ARCHIVE,FIRST_ARCHIVE_SHA)]:
        stages.append(dict(stage=server,archive=path,archive_sha256=sha,
            completion_sha256=digest((root/'completion.json').read_bytes()),
            archive_index_sha256=digest((root/'archive-index.json').read_bytes())))
    # Each completed continuation contributes immutable outcomes and an allocation
    # prefix. Only the newest allocation still needs historical scheduler lookup.
    completed_contracts=[];parent_jobs=['3890655','3891655']
    inherited=dict(model_calls=468,input_tokens=868493,output_tokens=103775,
                   sealed_cells=177,unsealed_cells=0,unknown_model_usage=False)
    allocations=[1968];minimum_elapsed=math.ceil(completion['study']['elapsed_seconds'])
    for record in completed_handoffs:
        local=Path(record['local_stage']);raw_archive=Path(record['local_archive'])
        done=json.loads((local/'completion.json').read_text())
        ready=json.loads((local/'prepared.json').read_text())
        old=json.loads((local/'handoff.json').read_text())
        study=done.get('study') or {};pin=study.get('contract') or {}
        server=str(Path(pin.get('path','')).parent.parent)
        config=json.loads((local/'continuation/continuation.json').read_text())
        job=done.get('job_id');prior_allocations=config.get('prior_allocations_seconds')
        if (not isinstance(job,str) or not job.isdigit() or job in parent_jobs or done.get('error') or study.get('error') or
                done.get('parent_jobs')!=parent_jobs or old.get('parent_jobs')!=parent_jobs or
                ready.get('continuation')!=pin or study.get('parent_usage')!=inherited or
                config.get('prior_usage')!=inherited or config.get('completed_chain_contracts',[])!=completed_contracts or
                config.get('parent_release')!=original['release'] or config.get('first_contract')!=prepared['continuation'] or
                config.get('original_budget',{}).get('total_wall_seconds')!=21600 or
                not isinstance(prior_allocations,list) or prior_allocations[:-1]!=allocations or
                any(type(value) is not int or value<=0 for value in prior_allocations) or
                prior_allocations[-1]<minimum_elapsed or sum(prior_allocations)>=batch_total_wall_seconds or
                digest((local/'continuation/continuation.json').read_bytes())!=pin.get('sha256') or
                study.get('new_usage',{}).get('unknown_model_usage') is not False or
                study.get('new_usage',{}).get('unsealed_cells')!=0):
            raise ValueError('Completed continuation identity, accounting or allocation prefix differs')
        expected=dict(inherited)
        for key in ('model_calls','input_tokens','output_tokens','sealed_cells'):
            value=study['new_usage'].get(key)
            if type(value) is not int or value<0:raise ValueError('Incomplete continuation usage')
            expected[key]+=value
        elapsed=study.get('elapsed_seconds')
        if (expected!=study.get('cumulative_usage') or expected['sealed_cells']>=216 or
                type(elapsed) not in (int,float) or not math.isfinite(elapsed) or elapsed<=0):
            raise ValueError('Completed continuation does not leave a known strict suffix')
        index=json.loads((local/'archive-index.json').read_text())
        for item in index['files']:
            relative=Path(item['path']).relative_to(server)
            target=local/relative
            if '..' in relative.parts or target.is_symlink() or target.stat().st_size!=item['bytes'] or digest(target.read_bytes())!=item['sha256']:
                raise ValueError('Local continuation evidence differs')
        stages.append(dict(stage=server,archive=record['server_archive'],archive_sha256=digest(raw_archive.read_bytes()),
            completion_sha256=digest((local/'completion.json').read_bytes()),
            archive_index_sha256=digest((local/'archive-index.json').read_bytes())))
        completed_contracts.append(pin);parent_jobs.append(job);inherited=expected
        allocations=prior_allocations;minimum_elapsed=math.ceil(elapsed)
    remaining=216-inherited['sealed_cells'];tag='final39' if not completed_contracts else 'tail'+str(remaining)
    short=source_commit[:7];stage=ROOT+'/small48-'+tag+'-'+short+'-v1';checkout=ROOT+'/XGAP-small48-'+tag+'-'+short
    contract=dict(source_commit=source_commit,parent_release=original['release'],first_contract=prepared['continuation'],
        evidence=stages,stage=stage,checkout=checkout,parent_jobs=parent_jobs,expected_remaining=remaining,
        completed_chain_contracts=completed_contracts,inherited_usage=inherited,run_tag=tag,
        fixed_prior_allocation_seconds=sum(allocations),fixed_prior_allocations_seconds=allocations,
        predecessor_job_id=parent_jobs[-1],total_allocated_seconds=batch_total_wall_seconds,
        original_total_allocated_seconds=21600,startup_cleanup_reserve_seconds=900,
        min_first_allocation_seconds=minimum_elapsed,
        automatic_retries=0,unique_cases=48,supported_requests=216,model_calls=0,backend_calls=0,submitted_jobs=0)
    work.mkdir(parents=True,exist_ok=False)
    (work/'handoff.json').write_text(json.dumps(contract,indent=2)+'\n')
    ref='refs/xgap-handoff/'+uuid.uuid4().hex
    git('update-ref',ref,source_commit,'')
    try:git('bundle','create',str(work/'source.bundle'),ref)
    finally:git('update-ref','-d',ref,source_commit)
    with (work/'source.bundle').open('rb') as f:
        header=[]
        while True:
            line=f.readline()
            if line==b'\n':break
            if not line or len(header)>100:raise ValueError('Invalid independent bundle')
            header.append(line)
    if any(x.startswith(b'-') for x in header):raise ValueError('Bundle has prerequisites')
    if git('bundle','list-heads',str(work/'source.bundle'))!=source_commit+' '+ref:
        raise ValueError('Bundle identity differs')
    prepare_code='''from pathlib import Path
import json
from run_ch6_small_chain_continuation import prepare
from xgap.experiments.ch6_small_release import audit
from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.one_shot_records import write_once
J=Path(__STAGE__)
c=json.loads((J/'handoff.json').read_text());a=json.loads((J/'prior-allocation.json').read_text())
checked=audit(load_pin(c['parent_release']))
if not checked['success']:raise ValueError('Frozen input audit failed: '+str(checked.get('failed_checks')))
pin=prepare(parent_release=c['parent_release'],first_contract=c['first_contract'],output=J/'continuation',
 source_commit=c['source_commit'],prior_allocations_seconds=a['prior_allocations_seconds'],
 recovery_wall_seconds=a['recovery_wall_seconds'],completed_chain_contracts=c['completed_chain_contracts'],
 batch_total_wall_seconds=c['total_allocated_seconds'])
d=json.loads(Path(pin['path']).read_text())
if d['remaining_cells']!=c['expected_remaining'] or d['prior_usage']!=c['inherited_usage']:
 raise ValueError('Prepared complement or inherited accounting differs')
if d['recovery_wall_seconds']!=a['recovery_wall_seconds']:
 raise ValueError('Prepared wall allowance differs')
write_once(J/'prepared.json',dict(continuation=pin,prior_allocation=a))
print(json.dumps(dict(prepared=True,continuation=pin,model_calls=0,backend_calls=0)),flush=True)
'''
    driver='''from pathlib import Path
import json,os,socket,tarfile,traceback
from run_ch6_small_chain_continuation import execute
from xgap.experiments.llm_auth_preflight import check_authentication
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.evidence_store import file_pin
J=Path(__STAGE__);R=Path(__ROOT__)
c=json.loads((J/'handoff.json').read_text())
result=dict(success=False,purpose='small_real_chain_continuation',source_commit=__SOURCE__,
 parent_jobs=c['parent_jobs'],job_id=os.environ.get('SLURM_JOB_ID'),node=socket.gethostname(),formal_campaign_ready=False)
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
 'profile.json','entry-profile.json','entry-profile-receipt.json','timing.json','session-finalization.json'}
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
archive=Path.home()/('xgap-small48-'+c['run_tag']+'-'+os.environ.get('SLURM_JOB_ID','nojob')+'.tar.gz')
with archive.open('xb') as stream,tarfile.open(fileobj=stream,mode='w:gz') as tar:
 for p in files:tar.add(p,arcname=str(p.relative_to(R)),recursive=False)
print(json.dumps(dict(success=result['success'],purpose=result['purpose'],
 status=result.get('study',{}).get('status'),new_usage=result.get('study',{}).get('new_usage'),
 cumulative_usage=result.get('study',{}).get('cumulative_usage'),error=result.get('error'),
 archive=file_pin(archive),formal_campaign_ready=False)),flush=True)
raise SystemExit(0 if result['success'] else 2)
'''
    for key,value in [('STAGE',stage),('ROOT',ROOT),('SOURCE',source_commit)]:
        prepare_code=prepare_code.replace('__'+key+'__',repr(value));driver=driver.replace('__'+key+'__',repr(value))
    (work/'prepare.py').write_text(prepare_code);(work/'driver.py').write_text(driver)
    (work/'run.sbatch').write_text(f'''#!/bin/bash
#SBATCH --job-name=xgap-small48-final
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
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
    (work/'README.md').write_text('# Final small48 continuation\n\n'
        f'Preserve {inherited["sealed_cells"]} sealed requests; run only the {remaining} unattempted D2 RDF requests.\n'
        'Original 48 questions, method configuration, and per-request limits remain unchanged.\n'
        'Known child accounting is reconciled in a new record; original null parent fields remain intact.\n'
        'All prior archives and their indexed files are checked before preparation.\n'
        f'Slurm accounting must confirm {parent_jobs[-1]} terminal; its elapsed allocation and prior {sum(allocations)} s\n'
        f'are subtracted from {batch_total_wall_seconds} s, rounded down to complete Slurm minutes. Reserve 900 s inside\n'
        'the new allocation for startup/cleanup. No pinned node or GPU; 8 CPU / 24 GiB.\n'
        'No attempted request is retried. Empty hidden credentials reprompt before submission.\n')
    if batch_total_wall_seconds!=21600:
        with (work/'README.md').open('a') as readme:
            readme.write('Administrative batch allocation is explicitly extended from 6 to 8 hours; all prior time counts.\n'
                         'Original per-request method/source/LLM budgets, inputs and outcomes are unchanged.\n')
    pins={p.name:digest(p.read_bytes()) for p in work.iterdir()}
    stage_code='''from pathlib import Path
import getpass,hashlib,json,os,subprocess,zipfile
J=Path(__STAGE__);CHECKOUT=Path(__CHECKOUT__);SOURCE=__SOURCE__;pins=__PINS__;ref=__REF__;ROOT=Path(__ROOT__)
if any(p.exists() or p.is_symlink() for p in (J,CHECKOUT)):
 raise ValueError('Continuation attempt exists; inspect it, never submit twice')
def checksum(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(1024**2),b''):h.update(block)
 return h.hexdigest()
with zipfile.ZipFile(str(Path.home()/__ARCHIVE_NAME__)) as z:
 if len(z.namelist())!=len(pins)+1 or set(z.namelist())!=set(pins)|{'stage.py'}:
  raise ValueError('Unexpected handoff members')
 data={name:z.read(name) for name in pins}
for name,content in data.items():
 if hashlib.sha256(content).hexdigest()!=pins[name]:raise ValueError('Handoff member changed: '+name)
c=json.loads(data['handoff.json'])
for record in c['evidence']:
 parent=Path(record['stage'])
 if checksum(record['archive'])!=record['archive_sha256']:raise ValueError('Historical archive changed')
 if checksum(parent/'completion.json')!=record['completion_sha256']:raise ValueError('Historical completion changed')
 index=(parent/'archive-index.json').read_bytes()
 if hashlib.sha256(index).hexdigest()!=record['archive_index_sha256']:raise ValueError('Historical index changed')
 for item in json.loads(index)['files']:
  file=Path(item['path'])
  if not file.is_absolute() or file.resolve()!=file or ROOT not in file.parents:
   raise ValueError('Historical evidence path is redirected')
  if file.stat().st_size!=item['bytes'] or checksum(file)!=item['sha256']:
   raise ValueError('Historical sealed evidence changed: '+str(file))
for pin in [c['parent_release'],c['first_contract']]+c['completed_chain_contracts']:
 if checksum(pin['path'])!=pin['sha256']:raise ValueError('Parent release or first continuation changed')
env={k:v for k,v in os.environ.items() if not k.startswith('GIT_') and k!='XGAP_EXTERNAL_LLM_API_KEY'}
job=c['predecessor_job_id']
accounting=subprocess.check_output(['sacct','-X','-j',job,'--format=JobIDRaw,State,ElapsedRaw','-n','-P'],env=env).decode()
rows=[line.strip().split('|') for line in accounting.splitlines() if line.strip()]
if len(rows)!=1 or len(rows[0]) not in (3,4) or rows[0][0]!=job:raise ValueError('Ambiguous previous job accounting')
state=rows[0][1].split()[0]
if state not in ('COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED'):
 raise ValueError('Previous allocation is not terminal; do not submit')
elapsed=int(rows[0][2]);remaining=c['total_allocated_seconds']-c['fixed_prior_allocation_seconds']-elapsed
slurm_minutes=remaining//60;slurm_seconds=slurm_minutes*60;reserve=c['startup_cleanup_reserve_seconds']
if elapsed<c['min_first_allocation_seconds'] or slurm_seconds<=reserve:raise ValueError('No valid remaining allocation allowance')
allocation=dict(job_id=job,state=state,prior_allocations_seconds=c['fixed_prior_allocations_seconds']+[elapsed],
 remaining_seconds=remaining,slurm_allocation_seconds=slurm_seconds,startup_cleanup_reserve_seconds=reserve,
 recovery_wall_seconds=slurm_seconds-reserve,raw_accounting=accounting)
os.umask(0o077);J.mkdir(mode=0o700);CHECKOUT.mkdir(mode=0o700)
for name,content in data.items():(J/name).write_bytes(content)
(J/'prior-allocation.json').write_text(json.dumps(allocation,indent=2)+'\\n')
env.update(PYTHONPATH=str(CHECKOUT/'src')+':'+str(CHECKOUT/'scripts'),PYTHONDONTWRITEBYTECODE='1')
def git(*args):return subprocess.check_output(['git']+list(args),cwd=str(CHECKOUT),env=env)
git('init','--quiet');git('bundle','verify',str(J/'source.bundle'))
git('fetch',str(J/'source.bundle'),ref);git('checkout','--detach',SOURCE)
if (CHECKOUT/'.git/objects/info/alternates').exists():raise ValueError('Unexpected alternate objects')
git('fsck','--connectivity-only','--no-dangling')
if git('rev-parse','HEAD').decode().strip()!=SOURCE or git('status','--porcelain'):raise ValueError('Source checkout differs')
subprocess.check_call(['bash','-n',str(J/'run.sbatch')],env=env)
subprocess.check_call([__PYTHON__,str(J/'prepare.py')],cwd=str(CHECKOUT),env=env)
if not os.isatty(0):raise ValueError('Interactive hidden credential input required')
key=''
while not key:
 key=getpass.getpass('LLM API key (hidden input): ').strip()
 if not key:print('Empty input; please enter the key again. Nothing submitted.',flush=True)
with (J/'credential.once').open('x') as f:f.write(key)
os.chmod(J/'credential.once',0o600);del key
wall=str(slurm_minutes)
with (J/'submission-stdout.txt').open('xb') as out,(J/'submission-stderr.txt').open('xb') as err:
 run=subprocess.run(['sbatch','--parsable','--time='+wall,'--output='+str(J/('small48-'+c['run_tag']+'-%j.out')),str(J/'run.sbatch')],
  stdout=out,stderr=err,env=env)
(J/'submission-exit-code.txt').write_text(str(run.returncode)+'\\n')
if run.returncode:
 (J/'credential.once').unlink();print((J/'submission-stderr.txt').read_text());raise SystemExit(run.returncode)
print('SUBMISSION '+(J/'submission-stdout.txt').read_text().strip(),flush=True)
'''
    for key,value in dict(STAGE=stage,CHECKOUT=checkout,SOURCE=source_commit,PINS=pins,REF=ref,ROOT=ROOT,
                          ARCHIVE_NAME=archive.name,PYTHON=PYTHON).items():
        stage_code=stage_code.replace('__'+key+'__',repr(value))
    (work/'stage.py').write_text(stage_code)
    for name in ('stage.py','prepare.py','driver.py'):compile((work/name).read_text(),name,'exec')
    subprocess.check_call(['bash','-n',str(work/'run.sbatch')])
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(work.iterdir()):z.write(p,p.name)
    result=dict(path=str(archive),sha256=digest(archive.read_bytes()),bytes=archive.stat().st_size,
        source_commit=source_commit,parent_jobs=parent_jobs,remaining=remaining,model_calls=0,
        backend_calls=0,submitted_jobs=0,stage=stage,checkout=checkout,
        original_total_wall_seconds=21600,batch_total_wall_seconds=batch_total_wall_seconds)
    (work.parent/(work.name+'-verification.json')).write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ('repo','source-commit','parent-evidence','first-evidence','work','archive'):
        parser.add_argument('--'+arg,required=True)
    parser.add_argument('--completed-handoff',dest='completed_handoffs',type=json.loads,action='append',default=[])
    parser.add_argument('--batch-total-wall-seconds',type=int,default=21600)
    print(json.dumps(build(**vars(parser.parse_args())),indent=2))
