"""Recover the pre-submission small48 transfer using a self-contained Git bundle.

This changes packaging only: the experimental source remains exactly f40dfa9.
The original failed staging directory and checkout are never modified.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import uuid
import zipfile


SOURCE = 'f40dfa9024f1473a90e6f340fb787f90ca204c46'
ORIGINAL_SHA = '4ce87128feb6437494200445e67bc33edcd4501870fc10925309478adf0e4999'
SERVER_ROOT = '/home/hxc859/xgap-ch6-artifacts'
OLD_J = SERVER_ROOT + '/small48-fixed-f40dfa9-v1'
OLD_OUT = SERVER_ROOT + '/small48-fixed-results-f40dfa9-v1'
OLD_CHECKOUT = SERVER_ROOT + '/XGAP-small48-fixed-f40dfa9'
NEW_J = SERVER_ROOT + '/small48-fixed-f40dfa9-independent-v1'
NEW_OUT = SERVER_ROOT + '/small48-fixed-results-f40dfa9-independent-v1'
NEW_CHECKOUT = SERVER_ROOT + '/XGAP-small48-fixed-f40dfa9-independent'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git_environment():
    # No inherited object directories or global clone references may affect this proof.
    return {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}


def independent_bundle(repo, destination):
    ref = 'refs/xgap-handoff/' + uuid.uuid4().hex
    env = git_environment()
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=str(repo), env=env)
    git('update-ref', ref, SOURCE, '')
    try:
        git('bundle', 'create', str(destination), ref)
    finally:
        git('update-ref', '-d', ref, SOURCE)
    with destination.open('rb') as stream:
        header = []
        while True:
            line = stream.readline()
            if line == b'\n':
                break
            if not line or len(header) > 100:
                raise ValueError('Invalid bundle header')
            header.append(line.decode('ascii').rstrip('\n'))
    if any(line.startswith('-') for line in header):
        raise ValueError('Independent bundle must not require any prerequisite commit')
    if git('bundle', 'list-heads', str(destination)).decode().strip() != SOURCE + ' ' + ref:
        raise ValueError('Unexpected source ref')
    return ref


def build(repo, original, output_zip, work):
    raw = original.read_bytes()
    if sha(raw) != ORIGINAL_SHA:
        raise ValueError('Original frozen package differs')
    work.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(original) as z:
        old = {n: z.read(n) for n in z.namelist() if n != 'stage.py'}
    old_pins = {n: sha(b) for n, b in old.items()}
    for name, content in old.items():
        if name == 'delta.bundle':
            continue
        for a, b in ((OLD_CHECKOUT, NEW_CHECKOUT), (OLD_J, NEW_J), (OLD_OUT, NEW_OUT)):
            content = content.replace(a.encode(), b.encode())
        (work / name).write_bytes(content)
    # Absolute deployment paths change, while selected cases, priors and budgets do not.
    spec_path = work / 'spec.json'
    spec = json.loads(spec_path.read_text())
    for field in ('selection', 'live_probe_policy'):
        file = work / Path(spec[field]['path']).name
        spec[field].update(sha256=sha(file.read_bytes()), bytes=file.stat().st_size)
    spec_path.write_text(json.dumps(spec, indent=2) + '\n')
    for name in ('selection.json', 'live-probe-policy.json', 'scalability-spec.json'):
        if (work / name).read_bytes() != old[name]:
            raise ValueError('Frozen experimental input unexpectedly changed: ' + name)
    if spec['budget'] != json.loads(old['spec.json'])['budget']:
        raise ValueError('Budget changed')
    ref = independent_bundle(repo, work / 'source.bundle')
    (work / 'README.md').write_text(
        '# small48 independent-source recovery\n\n'
        'Experimental source: ' + SOURCE + '\n'
        'Original 48 cases / 216 supported requests; inputs, sources and budgets unchanged.\n'
        'This replaces only the failed pre-submission Git transfer. No old path is changed.\n'
        'The stage verifies old staging has not reached preparation or submission.\n'
        'The complete bundle needs no existing checkout, alternates or network Git access.\n'
        'A fresh checkout is verified before publication, hidden API input and one submission.\n')
    manifest = dict(source_commit=SOURCE, original_package_sha256=ORIGINAL_SHA,
                    old_stage=OLD_J, old_checkout=OLD_CHECKOUT, old_output=OLD_OUT,
                    new_stage=NEW_J, new_checkout=NEW_CHECKOUT, new_output=NEW_OUT,
                    old_pins=old_pins, bundle_ref=ref,
                    unique_cases=48, supported_requests=216, budget=spec['budget'],
                    backend_calls=0, model_calls=0, submitted_jobs=0)
    (work / 'recovery-contract.json').write_text(json.dumps(manifest, indent=2) + '\n')
    pins = {p.name: sha(p.read_bytes()) for p in work.iterdir()}
    stage = '''from pathlib import Path
import getpass,hashlib,json,os,subprocess,zipfile
SOURCE=__SOURCE__;J=Path(__NEW_J__);OUT=Path(__NEW_OUT__);CHECKOUT=Path(__NEW_CHECKOUT__)
old_j=Path(__OLD_J__);old_out=Path(__OLD_OUT__);old_checkout=Path(__OLD_CHECKOUT__)
pins=__PINS__;old_pins=__OLD_PINS__;bundle_ref=__REF__
if any(p.exists() or p.is_symlink() for p in (J,OUT,CHECKOUT)):
 raise ValueError('Recovery attempt already exists; inspect it, never submit twice')
if old_j.is_symlink() or not old_j.is_dir() or old_checkout.is_symlink() or not (old_checkout/'.git').is_dir():
 raise ValueError('Original failed attempt is missing or redirected')
if old_out.exists() or old_out.is_symlink() or {p.name for p in old_j.iterdir()}!=set(old_pins):
 raise ValueError('Original attempt progressed beyond failed transfer; inspect before recovery')
for n,h in old_pins.items():
 p=old_j/n
 if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=h:
  raise ValueError('Original staging changed: '+n)
if {p.name for p in old_checkout.iterdir()}!={'.git'}:
 raise ValueError('Original checkout progressed beyond failed fetch')
with zipfile.ZipFile(str(Path.home()/__ARCHIVE_NAME__)) as z:
 if len(z.namelist())!=len(pins)+1 or set(z.namelist())!=set(pins)|{'stage.py'}:
  raise ValueError('Recovery package members differ')
 data={n:z.read(n) for n in pins}
for n,h in pins.items():
 if hashlib.sha256(data[n]).hexdigest()!=h:raise ValueError('Recovery package member differs: '+n)
os.umask(0o077);J.mkdir(mode=0o700)
for n,b in data.items():(J/n).write_bytes(b)
env={k:v for k,v in os.environ.items() if not k.startswith('GIT_') and k!='XGAP_EXTERNAL_LLM_API_KEY'}
def git(*args):
 return subprocess.check_output(['git']+list(args),cwd=str(CHECKOUT),env=env)
CHECKOUT.mkdir(mode=0o700)
git('init','--quiet')
git('bundle','verify',str(J/'source.bundle'))
git('fetch',str(J/'source.bundle'),bundle_ref)
git('checkout','--detach',SOURCE)
if (CHECKOUT/'.git/objects/info/alternates').exists():raise ValueError('Unexpected object dependency')
git('fsck','--connectivity-only','--no-dangling')
if git('rev-parse','HEAD').decode().strip()!=SOURCE or git('status','--porcelain'):
 raise ValueError('Independent checkout identity or contents differ')
(J/'independent-source-receipt.json').write_text(json.dumps(dict(
 source_commit=SOURCE,old_attempt_retained=True,old_attempt_preparation_started=False,
 old_attempt_submission_started=False,independent_objects=True,connectivity_verified=True,
 backend_calls=0,model_calls=0,submitted_jobs=0),indent=2)+'\\n')
for n in ('prepare.sh','run.sbatch'):subprocess.check_call(['bash','-n',str(J/n)],env=env)
subprocess.check_call(['bash',str(J/'prepare.sh')],env=env)
if not os.isatty(0):raise ValueError('Interactive hidden credential input required')
key=getpass.getpass('LLM API key (hidden input): ').strip()
if not key:raise ValueError('Empty key; no submission')
with (J/'credential.once').open('x') as f:f.write(key)
os.chmod(J/'credential.once',0o600);del key
with (J/'submission-stdout.txt').open('xb') as out,(J/'submission-stderr.txt').open('xb') as err:
 done=subprocess.run(['sbatch','--parsable','--output='+str(J/'small48-%j.out'),str(J/'run.sbatch')],stdout=out,stderr=err,env=env)
(J/'submission-exit-code.txt').write_text(str(done.returncode)+'\\n')
if done.returncode:
 (J/'credential.once').unlink();print((J/'submission-stderr.txt').read_text());raise SystemExit(done.returncode)
print('SUBMISSION '+(J/'submission-stdout.txt').read_text().strip(),flush=True)
'''
    replacements = {'SOURCE': SOURCE, 'NEW_J': NEW_J, 'NEW_OUT': NEW_OUT,
                    'NEW_CHECKOUT': NEW_CHECKOUT, 'OLD_J': OLD_J, 'OLD_OUT': OLD_OUT,
                    'OLD_CHECKOUT': OLD_CHECKOUT, 'PINS': pins, 'OLD_PINS': old_pins,
                    'REF': ref, 'ARCHIVE_NAME': output_zip.name}
    for key, value in replacements.items():
        stage = stage.replace('__' + key + '__', repr(value))
    (work / 'stage.py').write_text(stage)
    for p in work.glob('*.py'):
        compile(p.read_text(), str(p), 'exec')
    for n in ('prepare.sh', 'run.sbatch'):
        subprocess.check_call(['bash', '-n', str(work / n)])
    with zipfile.ZipFile(output_zip, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(work.iterdir()):
            z.write(p, p.name)
    receipt = dict(archive=str(output_zip),sha256=sha(output_zip.read_bytes()),
                   bytes=output_zip.stat().st_size,**manifest)
    (work.parent / (work.name + '-receipt.json')).write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:receipt[k] for k in ('archive','sha256','bytes','source_commit')}))
    return receipt


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,required=True)
    p.add_argument('--original',type=Path,required=True)
    p.add_argument('--output-zip',type=Path,required=True)
    p.add_argument('--work',type=Path,required=True)
    a=p.parse_args();build(a.repo.resolve(),a.original.resolve(),a.output_zip.resolve(),a.work.resolve())
