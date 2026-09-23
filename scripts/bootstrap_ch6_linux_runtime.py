#!/usr/bin/env python3
"""Build the pinned Linux TS dependencies on a CPU allocation, without LLM calls.

Only installation/portability work is performed. Author source and JAR entries
remain unchanged. A separate publisher admits services on the tiny frozen data.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import sys
import tarfile
import time
from urllib.request import urlopen

JAVA_URL = ('https://github.com/adoptium/temurin21-binaries/releases/download/'
            'jdk-21.0.8%2B9/OpenJDK21U-jdk_x64_linux_hotspot_21.0.8_9.tar.gz')
JAVA_SHA = 'f2dc5418092c43003db8f9005c4a286e1c0104fea96ccdd49e8ebd037cac9219'
GIB = 1024**3


def pin(path):
    path = Path(path).resolve(); digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''): digest.update(chunk)
    return dict(path=str(path), sha256=digest.hexdigest(), bytes=path.stat().st_size)


def unpack(archive, output, *, allow_links=False, max_bytes=GIB):
    """Reject traversal, duplicate names, device entries and link parents first."""
    output = Path(output).resolve()
    with tarfile.open(archive) as package:
        members = package.getmembers(); seen = set(); links = set()
        if sum(m.size for m in members) > max_bytes or len(members) > 20000:
            raise ValueError('Archive extraction budget exceeded')
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or str(path) in seen:
                raise ValueError('Unsafe or duplicate archive path')
            seen.add(str(path))
            if member.issym():
                if not allow_links: raise ValueError('Links excluded from transfer')
                target = (output/path.parent/member.linkname).resolve()
                if not target.is_relative_to(output): raise ValueError('Escaping link')
                links.add(path)
            elif not (member.isfile() or member.isdir()):
                raise ValueError('Unsupported archive entry')
        if any(p in links for m in members for p in PurePosixPath(m.name).parents):
            raise ValueError('Archive writes through a link')
        output.mkdir(parents=True, exist_ok=False)
        # Every member was checked, including link targets; links are created last.
        for member in sorted(members, key=lambda m: m.issym()):
            package.extract(member, output)


def bootstrap(archive, archive_sha256, output):
    if (platform.system() != 'Linux' or platform.machine() != 'x86_64'
            or not os.environ.get('SLURM_JOB_ID')):
        raise ValueError('Linux x86_64 CPU scheduler allocation required')
    if os.environ.get('SLURM_JOB_GPUS') or os.environ.get('SLURM_GPUS_ON_NODE') not in (None, '', '0'):
        raise ValueError('GPU allocation is outside this task')
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=False)
    result = dict(schema_version='xgap-ch6-linux-bootstrap-v1', success=False,
                  job_id=os.environ['SLURM_JOB_ID'], host=platform.node(),
                  model_calls=0, backend_calls=0, gpu_requested=False,
                  formal_campaign_ready=False, commands=[])
    env = dict(os.environ); env.pop('XGAP_EXTERNAL_LLM_API_KEY', None)
    env.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', PIP_NO_CACHE_DIR='1')
    start = time.monotonic()

    def run(name, args, cwd=None, seconds=1200):
        log = root/(name+'.log'); at = time.monotonic()
        with log.open('xb') as stream:
            value = subprocess.run([str(a) for a in args], cwd=cwd, env=env,
                                   stdout=stream, stderr=subprocess.STDOUT, timeout=seconds)
        result['commands'].append(dict(name=name, returncode=value.returncode,
                                       elapsed_seconds=time.monotonic()-at, log=pin(log)))
        if value.returncode: raise RuntimeError('Dependency stage failed: '+name)

    try:
        if shutil.disk_usage(root).free < 8*GIB: raise ValueError('Storage reserve unavailable')
        transfer = pin(archive)
        if transfer['sha256'] != archive_sha256: raise ValueError('Transfer checksum mismatch')
        unpack(archive, root/'inputs', max_bytes=512*1024**2)
        inputs = root/'inputs'; manifest = json.loads((inputs/'manifest.json').read_text())
        if manifest['schema_version'] != 'xgap-ch6-linux-transfer-v1': raise ValueError('Unknown package')
        for relative, expected in manifest['files'].items():
            path = (inputs/relative).resolve()
            if not path.is_relative_to(inputs): raise ValueError('Escaping manifest reference')
            actual = pin(path)
            if any(actual[k] != expected[k] for k in ('sha256', 'bytes')):
                raise ValueError('Transfer member mismatch: '+relative)
        result.update(transfer=transfer, verified_files=len(manifest['files']))
        download = root/'temurin21-linux.tar.gz'
        with urlopen(JAVA_URL, timeout=60) as response, download.open('xb') as stream:
            size = 0
            while chunk := response.read(1024**2):
                size += len(chunk)
                if size > 300*1024**2: raise ValueError('Java download budget exceeded')
                stream.write(chunk)
        if pin(download)['sha256'] != JAVA_SHA: raise ValueError('Official Java checksum mismatch')
        unpack(download, root/'java', allow_links=True)
        java = root/'java/jdk-21.0.8+9/bin/java'
        run('java-version', [java, '-version'], seconds=30)
        for name, commit in manifest['repositories'].items():
            target = root/name
            run('clone-'+name, ['git', 'clone', inputs/(name+'.bundle'), target], seconds=300)
            run('checkout-'+name, ['git', 'checkout', '--detach', commit], cwd=target, seconds=30)
            if subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=target, text=True).strip() != commit:
                raise ValueError('Author commit mismatch')
        run('redis-build', ['make', '-j4', 'MALLOC=libc'], cwd=root/'redis', seconds=900)
        run('redis-version', [root/'redis/src/redis-server', '--version'], seconds=30)
        shutil.copyfile(inputs/'lookup.jar', root/'lookup/lookup.jar')
        target = root/'lookup/lookup/target'; target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(inputs/'lookup.jar', target/'lookup-1.0.jar')
        classpath = root/'lookup-classpath.txt'
        classpath.write_text(':'.join(str(inputs/name) for name in manifest['classpath'])+'\n')
        run('python-venv', [sys.executable, '-m', 'venv', root/'author-venv'])
        python = root/'author-venv/bin/python'
        # Preserve the admitted Mac dependency versions where portable; appnope
        # is an IPython macOS extra, never imported by the Linux author method.
        constraints = root/'linux-constraints.txt'
        constraints.write_text('\n'.join(line for line in (inputs/'mac-reference-packages.txt').read_text().splitlines()
                                         if not line.lower().startswith(('appnope==', 'pyobjc'))) + '\n')
        run('author-dependencies', [python, '-m', 'pip', 'install', '--disable-pip-version-check',
            '--no-cache-dir', '-r', inputs/'author-requirements.txt', '-c', constraints, 'psutil'], seconds=1500)
        run('pip-check', [python, '-m', 'pip', 'check'], seconds=30)
        run('python-imports', [python, '-c', 'import chainlite,litellm,rdflib,redis,yaml,psutil'], seconds=60)
        packages = subprocess.check_output([str(python), '-m', 'pip', 'freeze'], text=True, env=env)
        (root/'linux-installed-packages.txt').write_text(packages)
        result.update(success=True, java=pin(java), python_command=str(python), python=pin(python),
            python_environment=pin(root/'author-venv/pyvenv.cfg'), redis=pin(root/'redis/src/redis-server'),
            classpath=pin(classpath), packages=pin(root/'linux-installed-packages.txt'),
            author_source=dict(path=str(root/'aruqula'), commit=manifest['repositories']['aruqula']),
            lookup_source=dict(path=str(root/'lookup'), commit=manifest['repositories']['lookup']),
            algorithm_changes=0, services_admitted=False)
    except Exception as error:
        result.update(error_type=type(error).__name__, error=str(error))
    finally:
        result['elapsed_seconds'] = time.monotonic()-start
        (root/'receipt.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(success=result['success'], receipt=str(root/'receipt.json'), error=result.get('error'))))
    return 0 if result['success'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'archive-sha256', 'output'): parser.add_argument('--'+name, required=True)
    raise SystemExit(bootstrap(**vars(parser.parse_args())))
