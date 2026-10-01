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
from xgap.experiments.linux_source_work import read_counters


class _LinuxGuardDiagnostics:
    """Best-effort first/last snapshots; never an admission or cleanup decision."""
    interval_seconds = 1.0
    max_identities = 256
    counter_keys = ('minor_faults','major_faults','read_bytes','write_bytes','rchar','wchar','syscr','syscw')

    def __init__(self, *, proc_root=Path('/proc')):
        self.proc_root=proc_root;self.records={};self.last_at=None;self.truncated=False

    def _read(self, member):
        import psutil
        pid=member['pid'];created=member['created']
        if psutil.Process(pid).create_time()!=created:return None
        sample=read_counters(pid,proc_root=self.proc_root)
        if sample is None:return None
        stat=(self.proc_root/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
        if int(stat[19])!=sample['start_ticks'] or psutil.Process(pid).create_time()!=created:return None
        return dict(sample,state=stat[0])

    def sample(self, members, elapsed, *, force=False):
        if not force and self.last_at is not None and elapsed-self.last_at<self.interval_seconds:return
        self.last_at=elapsed
        for member in members:
            key=(member['pid'],member['created'])
            if key not in self.records:
                if len(self.records)>=self.max_identities:
                    self.truncated=True;continue
                self.records[key]=dict(first=None,last=None,samples=0,unavailable_samples=0,
                    identity_changed=False,last_error_type=None)
            record=self.records[key]
            try:sample=self._read(member)
            except Exception as error:
                # Optional /proc reads must not fail a successfully guarded job.
                sample=None;record['last_error_type']=type(error).__name__
            if sample is None:
                record['unavailable_samples']+=1;continue
            sample=dict(sample,observed_after_ms=elapsed*1000)
            if record['first'] is None:record['first']=sample
            if sample['start_ticks']!=record['first']['start_ticks']:
                record['identity_changed']=True;continue
            record['last']=sample;record['samples']+=1

    def summary(self):
        rows=[]
        for (pid,created),record in sorted(self.records.items()):
            delta={key:None for key in self.counter_keys}
            if record['samples']>=2 and not record['identity_changed']:
                first=record['first']['counters'];last=record['last']['counters']
                for key in delta:
                    if key in first and key in last and last[key]>=first[key]:delta[key]=last[key]-first[key]
            rows.append(dict(record,pid=pid,created=created,observed_delta=delta))
        return dict(processes=rows,sample_interval_seconds=self.interval_seconds,
            max_identities=self.max_identities,truncated=self.truncated,
            scope='owned guarded process identities; first/last Linux snapshots; no global counters',
            limitations='Missing counters remain unknown. Short-lived work and final tails may be missed. '
                'Process state is an instant observation, not I/O wait duration. Faults are not scan rows; '
                'read_bytes is process storage I/O, not HTTP bytes. Diagnostics do not establish cleanup.')


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


def _stop_group(process, budget, *, expected_created=None):
    """Only the fresh session created below; handle descendants after leader exit."""
    import psutil
    def verify_identity():
        if expected_created is None:
            return
        try:
            actual=psutil.Process(process.pid).create_time()
        except psutil.NoSuchProcess:
            return  # The owned handle must still be reaped below.
        if actual!=expected_created:
            raise ValueError('Refuse to stop a changed process identity')
    signals=[]; started=time.monotonic();resolved_permission_races=0
    for sig,seconds in [(signal.SIGTERM,budget.terminate_grace_seconds),(signal.SIGKILL,2.0)]:
        verify_identity()
        if not _group_sample(process.pid):
            break
        try:
            os.killpg(process.pid,sig);signals.append(signal.Signals(sig).name)
        except ProcessLookupError:
            break
        except PermissionError:
            # Darwin can reject killpg when the last live member exits between
            # the scan and signal. A live/inaccessible group is never ignored.
            if _group_sample(process.pid):raise
            resolved_permission_races+=1;break
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            process.poll()
            if not _group_sample(process.pid):
                break
            time.sleep(min(.02,max(0,end-time.monotonic())))
    # Linux JVM leaders can already be zombies while final native threads exit;
    # Darwin can also stop listing an exiting leader before waitpid exposes it.
    # Reap only our own child, with a bounded cleanup allowance separate from
    # query execution budgets. Empty/non-running samples alone are insufficient.
    reap_wait_seconds=3.0
    if process.poll() is None:
        try:
            process.wait(timeout=reap_wait_seconds)
        except subprocess.TimeoutExpired:
            pass
    verify_identity()
    live=_group_sample(process.pid)
    # The final group scan may itself take time; refresh waitpid after that scan
    # rather than seal an earlier cached None even though our child has exited.
    returncode=process.poll()
    return {'signals':signals,'live_pids':[p['pid'] for p in live],'resolved_permission_races':resolved_permission_races,
        'pid':process.pid,'expected_created':expected_created,'post_stop_reap_returncode':returncode,
        'leader_reap_wait_seconds':reap_wait_seconds,
        'elapsed_ms':(time.monotonic()-started)*1000,'complete':not live and returncode is not None}


def run_guarded_command(command, *, cwd, output, budget=ProcessBudget(), environment=None, resource_monitor=None):
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
    samples=0;peak=0;peak_processes=0;seen={};cleanup=None;members=[]
    linux_diagnostics=_LinuxGuardDiagnostics()
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
                resource_status=resource_monitor.sample(members) if resource_monitor is not None else None
                elapsed=time.monotonic()-started
                log_bytes=sum((root/name).stat().st_size for name in ('stdout.log','stderr.log'))
                if resource_status:status=resource_status
                elif elapsed>=budget.wall_seconds:status='deadline_exceeded'
                elif rss>budget.max_group_rss_bytes:status='rss_limit_observed'
                elif log_bytes>budget.max_log_bytes:status='log_limit_observed'
                elif len(members)>budget.max_group_processes:status='process_limit_observed'
                elif code is not None:
                    status='descendants_remaining' if members else 'completed'
                linux_diagnostics.sample(members,elapsed,force=status!='running')
                if status!='running':break
                time.sleep(min(budget.sample_seconds,max(0,budget.wall_seconds-elapsed)))
    except Exception as exc:
        status='monitor_failed' if process is not None else 'spawn_failed'
        error={'type':type(exc).__name__,'message':str(exc)}
    finally:
        decision_ms=(time.monotonic()-started)*1000
        decision_status=status
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
            linux_diagnostics.sample(members,time.monotonic()-started,force=True)
        receipt={'schema_version':'xgap-process-guard-v1','status':status,
            'decision_status':decision_status,'linux_process_diagnostics':linux_diagnostics.summary(),
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
