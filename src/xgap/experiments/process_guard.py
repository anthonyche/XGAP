"""One attempt in an owned POSIX process group, with an external watchdog.

The guard does not retry, select answers or kill shared database/model services.
RSS is a sampled sum (shared pages may be counted twice), not an OS memory cap.
Hosted engines/remote LLMs are outside this process-group measurement boundary.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time

from xgap.experiments.one_shot_records import write_once


@dataclass(frozen=True)
class ProcessBudget:
    wall_seconds: float = 180.0
    max_group_rss_bytes: int = 2*1024**3
    max_log_bytes: int = 1024**2
    max_group_processes: int = 64
    sample_seconds: float = 0.05
    terminate_grace_seconds: float = 0.5

    def __post_init__(self):
        for key,minimum,maximum in [('wall_seconds',0,3600),('sample_seconds',0,1),
                                    ('terminate_grace_seconds',0,5)]:
            value=getattr(self,key)
            if type(value) not in (int,float) or not math.isfinite(value) or not minimum<value<=maximum:
                raise ValueError('Invalid process budget: '+key)
        for key,maximum in [('max_group_rss_bytes',256*1024**3),('max_log_bytes',1024**3),('max_group_processes',256)]:
            value=getattr(self,key)
            if type(value) is not int or not 0<value<=maximum:
                raise ValueError('Invalid process budget: '+key)


def _group_sample(pgid):
    import psutil
    members=[]
    for pid in psutil.pids():
        try:
            if os.getpgid(pid)!=pgid:
                continue
        except ProcessLookupError:
            continue
        except PermissionError:
            continue  # Another user's process cannot be a member of our group.
        try:
            process=psutil.Process(pid)
            if process.status()==psutil.STATUS_ZOMBIE:
                continue
            members.append({'pid':pid,'created':process.create_time(),'rss':process.memory_info().rss})
        except psutil.NoSuchProcess:
            continue
    return members


def _stop_group(process, budget):
    """Only the fresh session created below; handle descendants after leader exit."""
    signals=[]; started=time.monotonic()
    for sig,seconds in [(signal.SIGTERM,budget.terminate_grace_seconds),(signal.SIGKILL,2.0)]:
        if not _group_sample(process.pid):
            break
        try:
            os.killpg(process.pid,sig);signals.append(signal.Signals(sig).name)
        except ProcessLookupError:
            break
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            process.poll()
            if not _group_sample(process.pid):
                break
            time.sleep(min(.02,max(0,end-time.monotonic())))
    process.poll()
    live=_group_sample(process.pid)
    return {'signals':signals,'live_pids':[p['pid'] for p in live],
        'elapsed_ms':(time.monotonic()-started)*1000,'complete':not live}


def run_guarded_command(command, *, cwd, output, budget=ProcessBudget(), environment=None):
    """Run once. A zero exit code alone is not proof of answer correctness."""
    import psutil  # Required experiment extra; never silently skip monitoring.
    if os.name!='posix' or not isinstance(budget,ProcessBudget):
        raise ValueError('An explicit POSIX process budget is required')
    if not isinstance(command,(tuple,list)) or not command or any(not isinstance(a,str) or not a or '\0' in a for a in command):
        raise ValueError('Command must be an argument vector, not shell text')
    root=Path(output);root.mkdir(parents=True,exist_ok=False)
    intent={'schema_version':'xgap-process-guard-intent-v1','budget':asdict(budget),
        'command_sha256':hashlib.sha256(json.dumps(list(command),ensure_ascii=False).encode()).hexdigest(),
        'cwd':str(Path(cwd).resolve()),'attempts':1,'environment_values_recorded':False,
        'psutil_version':psutil.__version__,'scope':'owned method-worker process group; hosted engines/remote LLM excluded'}
    write_once(root/'intent.json',intent)
    started=time.monotonic();process=None;status='spawn_failed';error=None
    samples=0;peak=0;peak_processes=0;seen={};cleanup=None
    try:
        with (root/'stdout.log').open('xb') as stdout, (root/'stderr.log').open('xb') as stderr:
            process=subprocess.Popen(command,cwd=cwd,env={**os.environ,**(environment or {})},
                stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True)
            try:created=psutil.Process(process.pid).create_time()
            except psutil.NoSuchProcess:created=None  # A fast command may already have exited.
            write_once(root/'process.json',{'pid':process.pid,'process_group':process.pid,'created':created})
            status='running'
            while True:
                code=process.poll()
                members=_group_sample(process.pid);samples+=1
                for p in members:seen[p['pid']]=p['created']
                rss=sum(p['rss'] for p in members);peak=max(peak,rss);peak_processes=max(peak_processes,len(members))
                elapsed=time.monotonic()-started
                log_bytes=sum((root/name).stat().st_size for name in ('stdout.log','stderr.log'))
                if elapsed>=budget.wall_seconds:status='deadline_exceeded'
                elif rss>budget.max_group_rss_bytes:status='rss_limit_observed'
                elif log_bytes>budget.max_log_bytes:status='log_limit_observed'
                elif len(members)>budget.max_group_processes:status='process_limit_observed'
                elif code is not None:
                    status='descendants_remaining' if members else 'completed'
                if status!='running':break
                time.sleep(min(budget.sample_seconds,max(0,budget.wall_seconds-elapsed)))
    except Exception as exc:
        status='monitor_failed' if process is not None else 'spawn_failed'
        error={'type':type(exc).__name__,'message':str(exc)}
    finally:
        decision_ms=(time.monotonic()-started)*1000
        if process is not None:
            try:
                cleanup=_stop_group(process,budget)
            except Exception as exc:
                # Monitoring failure must not abandon a process we just spawned.
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:pass
                cleanup={'complete':False,'live_pids':None,'elapsed_ms':(time.monotonic()-started)*1000-decision_ms,
                    'signals':['SIGKILL'],'error':type(exc).__name__+': '+str(exc)}
            if not cleanup['complete']:status='cleanup_incomplete'
        receipt={'schema_version':'xgap-process-guard-v1','status':status,
            'success':status=='completed' and process.returncode==0 if process else False,
            'exit_code':process.returncode if process else None,'error':error,
            'decision_wall_ms':decision_ms,'cleanup':cleanup,'total_wall_ms':(time.monotonic()-started)*1000,
            'budget':asdict(budget),'sample_count':samples,'sampled_peak_group_rss_bytes':peak if samples else None,
            'peak_group_process_count':peak_processes if samples else None,
            'observed_process_identities':[{'pid':pid,'created':created} for pid,created in sorted(seen.items())],
            'attempts':1,'automatic_retries':0,'measurement_scope':intent['scope'],
            'rss_semantics':'sampled sum, not exact peak/unique physical RAM or OS-enforced cap',
            'time_semantics':'parent-observed completion includes worker startup/file reads/capture; cleanup separately shown',
            'external_work_quiescence':'not established by worker termination',
            'requires_external_quiescence_barrier':status!='completed' or process.returncode!=0 if process else False,
            'paper_result':False}
        write_once(root/'receipt.json',receipt)
    return receipt
