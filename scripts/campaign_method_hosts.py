"""Original method hosts sharing a verified source session; no query optimization."""
import json
from pathlib import Path
import shutil
import time

from check_common_rdf_trial import JAVA, JARS, PINS
from prepare_rdf_tdb import stream_pin
from run_external_federation_tiny import ready
from xgap.experiments.external_federation import deadline
from xgap.experiments.m15_native_services import LoopbackPortReservations
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.owned_resources import OwnedProcess


class CampaignMethodHosts:
    def __init__(self,session,*,summary_path,summary_sha256):
        self.session=session;self.hosts={};self.endpoints={};self.initializations={}
        self.summary_pin={'path':str(Path(summary_path).resolve()),'sha256':summary_sha256}

    def start(self,method):
        if method in self.hosts:
            if self.hosts[method].process.poll() is not None:raise RuntimeError('Terminal method host requires a new session')
            return self.endpoints[method]
        if method not in ('fedx','fedup'):raise ValueError('No hosted endpoint for this method')
        started=time.perf_counter();session=self.session;observer=session.observer
        root=session.root/(method+'-host');root.mkdir(exist_ok=False)
        phase=method+':initialization';observer.set_phase(phase);ports=LoopbackPortReservations.acquire(1)
        try:
            with deadline(120):
                jar=stream_pin(JARS[method])
                if jar['sha256']!=PINS[method]:raise ValueError('Pinned author artifact changed')
                port=ports.ports[0];endpoints=[observer.base_url+'/'+n+'/sparql' for n in ('graph','control')]
                if method=='fedx':
                    command=[JAVA,'-Xms128m','-Xmx512m','-jar',jar['path'],str(port),'120',*endpoints]
                    endpoint=f'http://127.0.0.1:{port}/sparql'
                else:
                    summary=json.loads(read_pinned(self.summary_pin['path'],self.summary_pin['sha256']))
                    if not summary['success'] or summary['dataset']!=session.prepared['dataset']:
                        raise ValueError('Prepared summary dataset mismatch')
                    source_seal=json.loads(read_pinned(summary['input_seal']['path'],summary['input_seal']['sha256']))
                    source_doc=json.loads(read_pinned(session.prepared['profile']['path'],session.prepared['profile']['sha256']))
                    if {k:v['sha256'] for k,v in source_seal['sources'].items()}!={
                            k:v['sha256'] for k,v in source_doc['offline']['rdf_loads'].items()}:
                        raise ValueError('Summary source facts differ from served sources')
                    seal=json.loads(read_pinned(summary['summary_seal']['path'],summary['summary_seal']['sha256']))
                    if [stream_pin(p) for p in sorted(Path(seal['path']).rglob('*')) if p.is_file()]!=seal['files']:
                        raise ValueError('Frozen summary files changed')
                    serving=root/'serving-summary';shutil.copytree(seal['path'],serving)
                    base=summary['logical_source_base']
                    if base!='http://xgap-source.invalid':raise ValueError('Unexpected logical source contract')
                    modifier='(e) -> e.replace('+json.dumps(base)+', '+json.dumps(observer.base_url)+')'
                    command=[JAVA,'-Xms128m','-Xmx512m','-jar',jar['path'],'--port',str(port),
                        '--summaries',str(serving),'--engine','FedX','--modify',modifier]
                    endpoint=f'http://127.0.0.1:{port}/serving-summary/sparql'
                ports.release(0);host=session.processes.start(method,command);ready(host,port)
                self.hosts[method]=OwnedProcess(method,'method_host',host);self.endpoints[method]=endpoint
                observed=observer.seal_phase(phase)
                if observed['failed_requests']:raise ValueError('Source failure during method initialization')
                outcome=write_once(root/'initialization.json',{'method':method,'endpoint':endpoint,'author_jar':jar,
                    'summary':self.summary_pin if method=='fedup' else None,'source_observations':observed,
                    'initialization_ms_before_seal':(time.perf_counter()-started)*1000,'model_calls':0,'final_method_queries':0})
                observer.release_phase(phase,outcome);self.initializations[method]=outcome
                return endpoint
        except BaseException:
            # Includes other idle owned hosts: none may outlive failed sources.
            session.close();raise
        finally:ports.close()

    def owned_for(self,method):
        return [*self.session.owned,*([self.hosts[method]] if method in self.hosts else [])]
