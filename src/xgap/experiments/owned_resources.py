"""Sample and retire only caller-owned live services around a method trial."""
from dataclasses import dataclass
from pathlib import Path
import time

import psutil

from xgap.experiments.linux_source_work import LinuxSourceWork
from xgap.experiments.process_guard import ProcessBudget, _group_sample, _stop_group


@dataclass(frozen=True)
class OwnedProcess:
    name: str
    role: str  # source or method_host
    process: object  # The Popen handle returned when the serving controller spawned it.


class OwnedResources:
    def __init__(self, services, *, method_rss_bytes=2*1024**3, source_rss_bytes=2*1024**3, extra_monitor=None):
        self.extra_monitor=extra_monitor
        self.services=tuple(services);self.limits={'method':method_rss_bytes,'source':source_rss_bytes}
        if not self.services or any(not isinstance(s,OwnedProcess) or s.role not in ('source','method_host') for s in self.services):
            raise ValueError('Live trials require explicit caller-owned method/source processes')
        if len({s.process.pid for s in self.services})!=len(self.services):raise ValueError('Duplicate owned process group')
        self.identities={};self.cpu_base={};self.cpu_last={};self.seen={};self.peak={'method':0,'source':0}
        self.source_work=LinuxSourceWork()
        self.samples=0;self.status=None;self.started=time.perf_counter();self.rss_components={};self.components_at=0.
        for s in self.services:
            if s.process.poll() is not None:raise ValueError('Owned service is already terminal')
            self.identities[s.process.pid]=psutil.Process(s.process.pid).create_time()
            for p in _group_sample(s.process.pid):
                cpu=psutil.Process(p['pid']).cpu_times();key=(p['pid'],p['created'],s.role)
                self.cpu_base[key]=cpu.user+cpu.system
                if s.role=='source':self.source_work.observe(p['pid'],p['created'],'source')

    def sample(self, worker_members):
        groups=[('method',p) for p in worker_members]
        for s in self.services:
            if s.process.poll() is not None:
                self.status='owned_service_exited';return self.status
            if psutil.Process(s.process.pid).create_time()!=self.identities[s.process.pid]:
                raise ValueError('Owned service PID identity changed')
            groups.extend((s.role,p) for p in _group_sample(s.process.pid))
        totals={'method':0,'source':0}
        for role,p in groups:
            totals['method' if role=='method_host' else role]+=p['rss']
            key=(p['pid'],p['created'],role);self.seen[key]=p['rss']
            try:
                cpu=psutil.Process(p['pid']).cpu_times();self.cpu_last[key]=cpu.user+cpu.system
            except psutil.NoSuchProcess:pass
        for role in totals:
            self.peak[role]=max(self.peak[role],totals[role])
            if totals[role]>self.limits[role]:self.status=role+'_rss_limit_observed'
        # Linux diagnostics distinguish anonymous memory from resident mapped
        # file pages. Both still count towards the declared total RSS guard.
        # Read only caller-owned identities; missing fields stay unknown.
        if time.monotonic()-self.components_at>=1 or self.status:
            self.components_at=time.monotonic()
            for role,p in groups:
                try:
                    if psutil.Process(p['pid']).create_time()!=p['created']:continue
                    if role=='source':
                        self.source_work.observe(p['pid'],p['created'],'source')
                    fields={}
                    for line in Path('/proc/'+str(p['pid'])+'/status').read_text().splitlines():
                        name,_,value=line.partition(':')
                        if name in ('RssAnon','RssFile','RssShmem'):fields[name]=int(value.split()[0])*1024
                    if fields:self.rss_components[str(p['pid'])]=dict(role=role,created=p['created'],bytes=fields,
                        observed_after_ms=(time.perf_counter()-self.started)*1000)
                except (OSError,ValueError,psutil.Error):pass
        if self.extra_monitor is not None:
            self.status=self.status or self.extra_monitor.sample(worker_members)
        self.samples+=1;return self.status

    def summary(self):
        cpu={'method':0.0,'source':0.0}
        for (pid,created,role),value in self.cpu_last.items():
            cpu['method' if role=='method_host' else role]+=max(0,value-self.cpu_base.get((pid,created,role),0))
        return {'status':self.status or 'within_observed_budget','samples':self.samples,
            'sampled_peak_rss_bytes':self.peak,'limits':self.limits,'sampled_cpu_seconds':cpu,
            'last_linux_rss_components':self.rss_components,
            'linux_source_work':self.source_work.summary(),
            'owned_groups':[{'name':s.name,'role':s.role,'pid':s.process.pid,'created':self.identities[s.process.pid]} for s in self.services],
            'scope':'method worker plus hosted method; source groups separately, remote LLM excluded',
            'limitations':'sampled group RSS may double-count shared pages; short-lived CPU/peaks may be missed; not an OS cap'}

    def stop(self):
        started=time.perf_counter();records=[]
        for s in reversed(self.services):
            try:
                # The guard checks the recorded identity around signal/reap and
                # handles a leader disappearing before its Popen status updates.
                records.append({'name':s.name,**_stop_group(s.process,ProcessBudget(),
                    expected_created=self.identities[s.process.pid])})
            except Exception as e:records.append({'name':s.name,'complete':False,'error':type(e).__name__+': '+str(e)})
        return {'complete':all(r['complete'] for r in records),'groups':records,
            'recovery_ms':(time.perf_counter()-started)*1000,'new_serving_session_required':True}
