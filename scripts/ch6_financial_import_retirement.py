"""Explicit scheduler retirement for an abandoned, unsealed offline importer.

This never turns cleanup_incomplete into process-closure success. Terminal Slurm
records permit a fresh disjoint import; the failed store is never read or reused.
If assigned the old host, additionally reject a still-present old process identity.
"""
import argparse
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import time

from prepare_rdf_tdb import stream_pin
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once

SCHEMA = 'xgap-abandoned-import-allocation-retirement-v1'
TERMINAL = {'COMPLETED','FAILED','TIMEOUT','CANCELLED','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED'}


def read(pin):
    return json.loads(read_pinned(pin['path'], pin['sha256']))


def validate_spec(resume):
    spec = resume['import_retirement']
    if set(spec) != {'host','source_id','guard','process'}:
        raise ValueError('Unexpected importer retirement identity')
    if not spec['host'] or spec['source_id'] in read(resume['loaded'])['stores']:
        raise ValueError('Retirement applies only to an unsealed source')
    root = Path(resume['loaded']['path']).parent/spec['source_id']/'load-guard'
    if (spec['guard']['path'] != str(root/'receipt.json') or
            spec['process']['path'] != str(root/'process.json')):
        raise ValueError('Abandoned importer evidence is not owned by the prior load')
    guard, process = read(spec['guard']), read(spec['process'])
    expected = dict(pid=process.get('pid'), created=process.get('created'))
    if (guard.get('schema_version') != 'xgap-process-guard-v1' or guard.get('success') is not False
            or guard.get('status') != 'cleanup_incomplete' or guard.get('exit_code') is not None
            or guard.get('attempts') != 1 or guard.get('automatic_retries') != 0
            or type(expected['pid']) is not int or expected['pid'] < 1
            or type(expected['created']) not in (int,float) or not math.isfinite(expected['created'])
            or process.get('process_group') != expected['pid']
            or guard.get('observed_process_identities') != [expected]):
        raise ValueError('Only the exact single abandoned importer is admitted')
    cleanup = guard.get('cleanup', {})
    if (cleanup.get('complete') is not False or cleanup.get('live_pids') != [expected['pid']]
            or cleanup.get('pid') != expected['pid'] or 'SIGKILL' not in cleanup.get('signals', [])):
        raise ValueError('Prior importer termination evidence is incomplete')
    return spec, expected


def terminal_records(text, job, host):
    rows = [line.strip().split('|') for line in text.splitlines() if line.strip()]
    records = {}
    for row in rows:
        if len(row) != 5:
            raise ValueError('Invalid prior Slurm accounting record')
        ident, state, elapsed, code, node = row
        state = state.split()[0] if state.split() else ''
        if (ident in records or not (ident == job or ident.startswith(job+'.'))
                or state not in TERMINAL or not elapsed.isdigit() or not code
                or node != host):
            raise ValueError('Prior allocation or step not verifiably terminal')
        records[ident] = dict(state=state, elapsed_seconds=int(elapsed), exit_code=code, node=node)
    if not {job, job+'.batch', job+'.extern'} <= set(records) or records[job]['elapsed_seconds'] < 1:
        raise ValueError('Require allocation, batch and extern terminal accounting')
    return records


def capture(stage):
    stage = Path(stage); c = json.loads((stage/'handoff.json').read_text()); resume = c['resume']
    spec, identity = validate_spec(resume)
    root = stage/'previous-import-retirement'; root.mkdir(exist_ok=False)
    commands = dict(accounting=['sacct','-n','-P','-j',resume['job_id'],
        '--format=JobIDRaw,State%40,ElapsedRaw,ExitCode,NodeList'],
        active=['squeue','-h','-u',str(os.getuid()),'-o','%i'])
    evidence = {}
    for name, command in commands.items():
        with (root/(name+'.stdout')).open('xb') as out, (root/(name+'.stderr')).open('xb') as err:
            result = subprocess.run(command, stdout=out, stderr=err, timeout=60, check=False)
        evidence[name] = dict(command=command, exit_code=result.returncode,
            stdout=stream_pin(root/(name+'.stdout')), stderr=stream_pin(root/(name+'.stderr')))
        if result.returncode:
            raise ValueError('Cannot establish prior scheduler retirement: '+name)
    rows = terminal_records((root/'accounting.stdout').read_text(), resume['job_id'], spec['host'])
    active = (root/'active.stdout').read_text().split()
    if any(v == resume['job_id'] or v.startswith(resume['job_id']+'.') for v in active):
        raise ValueError('Old allocation is still active')
    receipt = dict(schema_version=SCHEMA, job_id=resume['job_id'], host=spec['host'], source_id=spec['source_id'],
        previous_loaded=resume['loaded'], guard=spec['guard'], process=spec['process'], identity=identity,
        evidence=evidence, terminal_records=rows, captured_unix=time.time(),
        scheduler_retired=True, os_process_exit_confirmed=False, old_guard_unchanged=True,
        failed_store_reusable=False,
        scope='Fresh disjoint offline import only; no successful store or process-closure certification')
    return write_once(stage/'previous-import-retirement.json', receipt)


def validate(pin, *, previous_loaded_pin, guard_pin, process_pin, source_id, expected_job_id, expected_host):
    doc = read(pin)
    if (doc.get('schema_version') != SCHEMA or doc.get('job_id') != expected_job_id
            or doc.get('host') != expected_host or doc.get('previous_loaded') != previous_loaded_pin
            or doc.get('guard') != guard_pin or doc.get('process') != process_pin
            or doc.get('source_id') != source_id or doc.get('scheduler_retired') is not True
            or doc.get('os_process_exit_confirmed') is not False or doc.get('failed_store_reusable') is not False):
        raise ValueError('Abandoned importer retirement binding differs')
    resume = dict(job_id=doc['job_id'], loaded=previous_loaded_pin,
        import_retirement=dict(host=doc['host'], source_id=source_id, guard=guard_pin, process=process_pin))
    _, identity = validate_spec(resume)
    if doc['identity'] != identity:
        raise ValueError('Abandoned importer process identity differs')
    evidence = doc['evidence']
    if any(evidence[name]['exit_code'] != 0 for name in ('accounting','active')):
        raise ValueError('Scheduler retirement commands failed')
    raw = read_pinned(evidence['accounting']['stdout']['path'], evidence['accounting']['stdout']['sha256']).decode()
    if terminal_records(raw, doc['job_id'], doc['host']) != doc['terminal_records']:
        raise ValueError('Scheduler retirement evidence differs')
    active = read_pinned(evidence['active']['stdout']['path'], evidence['active']['stdout']['sha256']).decode().split()
    if any(v == doc['job_id'] or v.startswith(doc['job_id']+'.') for v in active):
        raise ValueError('Old allocation is still active')
    local = dict(host=socket.gethostname(), checked=False, process_exit_confirmed=False)
    if local['host'].split('.')[0] == doc['host'].split('.')[0]:
        import psutil
        try:
            current = psutil.Process(identity['pid']).create_time()
        except psutil.NoSuchProcess:
            current = None
        if current == identity['created']:
            raise ValueError('Old importer is still present on this compute node; no load started')
        local.update(checked=True, process_exit_confirmed=True, current_created=current)
    return dict(receipt=pin, scope=doc['scope'], scheduler_retired=True,
        os_process_exit_confirmed=local['process_exit_confirmed'], local_check=local,
        original_guard_status='cleanup_incomplete', failed_store_reusable=False)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--stage',required=True)
    print(json.dumps(capture(parser.parse_args().stage)))
