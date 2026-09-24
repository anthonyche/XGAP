"""Owned disk-backed RDF serving session for consecutive campaign cells."""
import json
import os
from pathlib import Path
import shutil
import time
import subprocess
import hashlib
import zipfile
import psutil

from prepare_rdf_tdb import stream_pin
from run_external_federation_tiny import Processes, ready
from xgap.experiments.campaign_source_observer import CampaignSourceObserver, SourceObservationBudget
from xgap.experiments.m15_native_services import LoopbackPortReservations, _fuseki_server_configuration
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.owned_resources import OwnedProcess
from xgap.experiments.process_guard import _group_sample, _stop_group, ProcessBudget
from xgap.experiments.verified_store_copy import copy_sealed_store


class RdfTdbSession:
    serving_copy_paths=('graph-tdb2','control-tdb2','fedup-host/serving-summary')
    def __init__(self,*,root,prepared_path,prepared_sha256,budget:SourceObservationBudget,prepared_input_sha256=None,discard_serving_copies=False,serving_root=None,file_mode='default',experimental_lazy_range=False):
        if file_mode not in ('default','direct'):raise ValueError('Unknown TDB2 serving file mode')
        if experimental_lazy_range and file_mode!='direct':raise ValueError('Experimental lazy ranges require admitted Direct bootstrap')
        self.experimental_lazy_range=experimental_lazy_range
        self.file_mode=file_mode
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
        self.store_root=self.root
        if serving_root is not None:
            candidate=Path(serving_root).resolve()
            if candidate==self.root or self.root in candidate.parents or candidate in self.root.parents:
                raise ValueError('Separate serving workspace must be disjoint from durable evidence')
            candidate.mkdir(parents=True,exist_ok=False);self.store_root=candidate
        write_once(self.root/'storage-placement.json',dict(evidence_root=str(self.root),serving_root=str(self.store_root),
            separate=self.store_root!=self.root,shared_method_contract=True,query_warmup_calls=0))

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
                if shutil.disk_usage(self.store_root).free<store['bytes']+6*1024**3:raise ValueError('Insufficient serving-copy reserve')
                copied=copy_sealed_store(store['path'],self.store_root/(name+'-tdb2'),seal['files'])
                write_once(self.root/('copy-'+name+'.json'),copied)
            # Configure the DBOE factory before any source dataset opens. TDB's CLI
            # context alone does not control Jena 5.6 B+tree block access.
            bootstrap=None
            if self.file_mode=='direct':
                source=Path(__file__).parent/'java/XgapStorageMode.java'
                overlays=[];overlay_originals={}
                if self.experimental_lazy_range:
                    expected={'BPTreeRangeIterator':'cd48a47afe150e1b4cd2a8645e8c6ad6b6d1d758d7bf1708bdae6d17c80f696d',
                        'BPTreeRangeIteratorMapper':'8dfbaeb5bec7a7c9312f87467a50b15634c0000bb98ddb88f4b96704ea7538c2'}
                    with zipfile.ZipFile(engine['path']) as jar:
                        for name,digest in expected.items():
                            actual=hashlib.sha256(jar.read('org/apache/jena/dboe/trans/bplustree/'+name+'.class')).hexdigest()
                            if actual!=digest:raise ValueError('Experimental range overlay requires exact pinned upstream classes')
                            overlay_originals[name]=actual;overlays.append(source.parent/'jena_lazy_range'/(name+'.java'))
                classes=self.root/'storage-bootstrap';classes.mkdir()
                javac=Path(java['path']).with_name('javac')
                with (classes/'compile.stdout').open('xb') as out,(classes/'compile.stderr').open('xb') as err:
                    subprocess.run([str(javac),'-J-Xmx128m','-proc:none','--release','21',
                        '-cp',engine['path'],'-d',str(classes),str(source),*[str(p) for p in overlays]],
                        stdout=out,stderr=err,check=True,timeout=45)
                bootstrap=write_once(classes/'receipt.json',dict(source=stream_pin(source),
                    javac=stream_pin(javac),compiled=stream_pin(classes/'XgapStorageMode.class'),
                    engine=engine,requested_mode='direct',
                    range_overlay=dict(revision='lazy-v2-both-paths',original_classes=overlay_originals,
                        sources=[stream_pin(p) for p in overlays],
                        compiled=[stream_pin(p) for p in sorted(classes.rglob('BPTreeRangeIterator*.class'))],
                        scope='experimental read-only backend admission; shared by all sources/methods in this session; not upstream Jena') if overlays else None,
                    contract='SystemIndex and SystemTDB asserted before Fuseki dataset startup'))
            names=sorted(self.prepared['stores'])
            if set(names)!=set(doc['offline']['rdf_loads']) or not 1<=len(names)<=8:
                raise ValueError('Prepared and frozen source sets differ')
            self.ports=LoopbackPortReservations.acquire(len(names))
            # Keep aggregate Java heap fixed as source count changes (S2).
            heap_mib=1536//len(names)
            routes={}
            for i,name in enumerate(names):
                port=self.ports.ports[i];state=self.root/('fuseki-'+name);state.mkdir()
                (state/'config.ttl').write_text(_fuseki_server_configuration(query_timeout_seconds=self.budget.timeout_seconds))
                self.ports.release(i)
                file_args=['--set=tdb2:fileMode=direct'] if self.file_mode=='direct' else []
                entry=(['-cp',str(classes)+os.pathsep+engine['path'],'XgapStorageMode','direct']
                    if bootstrap else ['-jar',engine['path']])
                overlay_args=['-Dxgap.rangeOverlay=lazy-v2'] if self.experimental_lazy_range else []
                process=self.processes.start('source-'+name,[java['path'],'-Xms64m',f'-Xmx{heap_mib}m',*overlay_args,*entry,
                    '--localhost','--port',str(port),'--tdb2','--loc',str(self.store_root/(name+'-tdb2')),*file_args,'/'+name],
                    cwd=Path(engine['path']).parent,env={'FUSEKI_BASE':str(state)})
                self.owned.append(OwnedProcess(name,'source',process));ready(process,port)
                routes['/'+name+'/sparql']=f'http://127.0.0.1:{port}/{name}/sparql'
            self.observer=CampaignSourceObserver(routes,self.root/'source-observations',budget=self.budget)
            for spec in doc['backends'].values():
                if spec['client']['database'] not in names:
                    raise ValueError('Backend dataset is absent from frozen stores')
                spec['client'].update(url=self.observer.base_url,timeout_seconds=self.budget.timeout_seconds)
            for key in ('estimator','catalog'):doc[key]['path']=str((base.parent/doc[key]['path']).resolve())
            doc['offline']['serving_endpoint_parent']=parent
            doc['offline']['prepared_stores']=self.prepared_pin
            doc['offline']['tdb2_serving_file_mode']=self.file_mode
            doc['offline']['experimental_lazy_range']=self.experimental_lazy_range
            if bootstrap:doc['offline']['tdb2_storage_bootstrap']=bootstrap
            self.profile=write_once(self.root/'profile.json',doc)
            FrozenOneShotProfile.load(self.profile['path'],expected_sha256=self.profile['sha256'])
            self.ready_pin=write_once(self.root/'ready.json',{'prepared':self.prepared_pin,'preparation_input':self.input_pin,'profile':self.profile,
                'source_urls':routes,'observation_url':self.observer.base_url,'read_only_cli':True,
                'query_timeout_seconds':self.budget.timeout_seconds,'offline_fresh_session_ms':(time.perf_counter()-at)*1000,
                'aggregate_heap_mib':heap_mib*len(names),'per_source_heap_mib':heap_mib,
                'tdb2_file_mode':self.file_mode,'storage_bootstrap':bootstrap,
                'experimental_lazy_range':self.experimental_lazy_range,
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
                if process.poll() is None:
                    # A Linux JVM leader can be Z while its final native threads
                    # are still exiting. The 0.5-second guard reap can time out;
                    # finish a bounded wait on our own child before certification.
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:pass
                cleanup['post_stop_reap_returncode']=process.returncode
                cleanup['complete']=not _group_sample(process.pid) and process.returncode is not None
                try:state=psutil.Process(process.pid).status() if process.poll() is None else 'reaped'
                except psutil.NoSuchProcess:state='absent'
                rows.append({'name':name,'pid':process.pid,'returncode':process.poll(),'leader_state':state,
                    'terminal':process.poll() is not None or state in ('absent',psutil.STATUS_ZOMBIE),'cleanup':cleanup})
            except Exception as error:
                rows.append({'name':name,'pid':process.pid,'returncode':process.poll(),'terminal':False,
                    'cleanup':{'complete':False,'error_type':type(error).__name__,'error':str(error)}})
        drained=all(row['cleanup']['complete'] for row in rows)
        # Stop accepting requests even when a source failed to terminate. An
        # unclosed non-daemon observer would keep a failed Slurm job alive forever.
        # This does not upgrade the separate source-quiescence certificate.
        if self.observer:self.observer.close()
        for log in self.processes.logs:log.close()
        if self.ports:self.ports.close()
        result={'processes':rows,'owned_processes_terminal':all(r['terminal'] for r in rows),
            'observer_stopped':self.observer is None or (not self.observer.thread.is_alive() and not self.observer.inflight)}
        result['owned_groups_drained']=drained and not any(_group_sample(row['pid']) for row in rows)
        if self.discard_serving_copies and result['owned_groups_drained'] and result['observer_stopped']:
            removed=[];retained=[]
            for relative in dict.fromkeys((*self.serving_copy_paths,*(n+'-tdb2' for n in self.prepared['stores']))):
                path=getattr(self,'store_root',self.root)/relative
                if path.exists():
                    try:
                        if path.is_symlink():raise ValueError('Refuse to discard redirected serving copy')
                        shutil.rmtree(path);removed.append(relative)
                    except (OSError,ValueError) as error:
                        # NFS may retain delayed-unlink files after the owned
                        # JVM has exited. Storage reclamation is separate from
                        # source quiescence; always seal the latter and retain
                        # this bounded failure without a destructive retry loop.
                        retained.append(dict(path=relative,error_type=type(error).__name__,error=str(error)))
            result['discarded_reconstructable_serving_copies']=removed
            result['serving_copy_reclamation_complete']=not retained
            result['retained_serving_copy_errors']=retained
            result['frozen_inputs_and_all_query_artifacts_retained']=True
        # The caller may close after start already performed failure cleanup.
        if not (self.root/'closed.json').exists():write_once(self.root/'closed.json',result)
        return result
