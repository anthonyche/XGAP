"""Owned disk-backed RDF serving session for consecutive campaign cells."""
import json
from pathlib import Path
import shutil
import time
import subprocess
import psutil

from prepare_rdf_tdb import stream_pin
from run_external_federation_tiny import Processes, ready
from xgap.experiments.campaign_source_observer import CampaignSourceObserver, SourceObservationBudget
from xgap.experiments.m15_native_services import LoopbackPortReservations, _fuseki_server_configuration
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.owned_resources import OwnedProcess
from xgap.experiments.process_guard import _group_sample, _stop_group, ProcessBudget


class RdfTdbSession:
    serving_copy_paths=('graph-tdb2','control-tdb2','fedup-host/serving-summary')
    def __init__(self,*,root,prepared_path,prepared_sha256,budget:SourceObservationBudget,prepared_input_sha256=None,discard_serving_copies=False):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=False)
        self.prepared=json.loads(read_pinned(prepared_path,prepared_sha256))
        if not self.prepared.get('success'):raise ValueError('Successful frozen store preparation required')
        self.prepared_pin={'path':str(Path(prepared_path).resolve()),'sha256':prepared_sha256}
        self.input_pin=self.prepared.get('input_seal') or {
            'path':str(Path(prepared_path).parent/'input-seal.json'),'sha256':prepared_input_sha256}
        if not self.input_pin['sha256']:raise ValueError('Pinned preparation input is required')
        self.budget=budget;self.processes=Processes(self.root);self.ports=None;self.observer=None;self.owned=[]
        self.profile=None;self.ready_pin=None
        self.discard_serving_copies=discard_serving_copies

    def start(self):
        at=time.perf_counter()
        try:
            parent=self.prepared['profile'];base=Path(parent['path'])
            doc=json.loads(read_pinned(base,parent['sha256']))
            build=json.loads(read_pinned(self.input_pin['path'],self.input_pin['sha256']))
            if build['profile']!=parent:raise ValueError('Preparation engine/input identity mismatch')
            engine=build['fuseki_jar'];java=build['java']
            if stream_pin(engine['path'])!=engine or stream_pin(java['path'])!=java:raise ValueError('Prepared engine changed')
            for name,store in self.prepared['stores'].items():
                seal=json.loads(read_pinned(store['seal']['path'],store['seal']['sha256']))
                if seal['source']['sha256']!=doc['offline']['rdf_loads'][name]['sha256']:raise ValueError('Store source mismatch')
                actual=[stream_pin(p) for p in sorted(Path(store['path']).rglob('*')) if p.is_file()]
                if actual!=seal['files']:raise ValueError('Frozen store changed: '+name)
                if shutil.disk_usage(self.root).free<store['bytes']+6*1024**3:raise ValueError('Insufficient serving-copy reserve')
                shutil.copytree(store['path'],self.root/(name+'-tdb2'))
            self.ports=LoopbackPortReservations.acquire(2)
            routes={}
            for i,name in enumerate(('graph','control')):
                port=self.ports.ports[i];state=self.root/('fuseki-'+name);state.mkdir()
                (state/'config.ttl').write_text(_fuseki_server_configuration(query_timeout_seconds=self.budget.timeout_seconds))
                self.ports.release(i)
                process=self.processes.start('source-'+name,[java['path'],'-Xms128m','-Xmx768m','-jar',engine['path'],
                    '--localhost','--port',str(port),'--tdb2','--loc',str(self.root/(name+'-tdb2')),'/'+name],
                    cwd=Path(engine['path']).parent,env={'FUSEKI_BASE':str(state)})
                self.owned.append(OwnedProcess(name,'source',process));ready(process,port)
                routes['/'+name+'/sparql']=f'http://127.0.0.1:{port}/{name}/sparql'
            self.observer=CampaignSourceObserver(routes,self.root/'source-observations',budget=self.budget)
            for spec in doc['backends'].values():
                spec['client'].update(url=self.observer.base_url,timeout_seconds=self.budget.timeout_seconds)
            for key in ('estimator','catalog'):doc[key]['path']=str((base.parent/doc[key]['path']).resolve())
            doc['offline']['serving_endpoint_parent']=parent
            doc['offline']['prepared_stores']=self.prepared_pin
            self.profile=write_once(self.root/'profile.json',doc)
            FrozenOneShotProfile.load(self.profile['path'],expected_sha256=self.profile['sha256'])
            self.ready_pin=write_once(self.root/'ready.json',{'prepared':self.prepared_pin,'preparation_input':self.input_pin,'profile':self.profile,
                'source_urls':routes,'observation_url':self.observer.base_url,'read_only_cli':True,
                'query_timeout_seconds':self.budget.timeout_seconds,'offline_fresh_session_ms':(time.perf_counter()-at)*1000,
                'scope':'store/engine verification, serving copies, startup, observer and profile reads; no warmup query',
                'source_groups':[{'name':s.name,'pid':s.process.pid} for s in self.owned]})
            return self
        except BaseException:
            self.close();raise

    def close(self):
        rows=[]
        # Unlike the legacy tiny Processes.close, inspect/drain the group before
        # sending a signal; materialized-return cleanup may already have stopped it.
        for name,process in reversed(self.processes.owned):
            try:
                cleanup=_stop_group(process,ProcessBudget())
                if cleanup['complete'] and process.poll() is None:
                    try:process.wait(timeout=2)
                    except subprocess.TimeoutExpired:pass
                try:state=psutil.Process(process.pid).status() if process.poll() is None else 'reaped'
                except psutil.NoSuchProcess:state='absent'
                rows.append({'name':name,'pid':process.pid,'returncode':process.poll(),'leader_state':state,
                    'terminal':process.poll() is not None or state in ('absent',psutil.STATUS_ZOMBIE),'cleanup':cleanup})
            except Exception as error:
                rows.append({'name':name,'pid':process.pid,'returncode':process.poll(),'terminal':False,
                    'cleanup':{'complete':False,'error_type':type(error).__name__,'error':str(error)}})
        drained=all(row['cleanup']['complete'] for row in rows)
        if self.observer and drained:self.observer.close()
        for log in self.processes.logs:log.close()
        if self.ports:self.ports.close()
        result={'processes':rows,'owned_processes_terminal':all(r['terminal'] for r in rows),
            'observer_stopped':self.observer is None or (not self.observer.thread.is_alive() and not self.observer.inflight)}
        result['owned_groups_drained']=drained and not any(_group_sample(row['pid']) for row in rows)
        if self.discard_serving_copies and result['owned_groups_drained'] and result['observer_stopped']:
            removed=[]
            for relative in self.serving_copy_paths:
                path=self.root/relative
                if path.exists():
                    if path.is_symlink():raise ValueError('Refuse to discard redirected serving copy')
                    shutil.rmtree(path);removed.append(relative)
            result['discarded_reconstructable_serving_copies']=removed
            result['frozen_inputs_and_all_query_artifacts_retained']=True
        # The caller may close after start already performed failure cleanup.
        if not (self.root/'closed.json').exists():write_once(self.root/'closed.json',result)
        return result
