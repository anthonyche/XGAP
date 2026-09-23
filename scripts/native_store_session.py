"""Owned native serving copies; no loading, catalog build, fit or warmup query."""
import json
from pathlib import Path
import shutil
import time

from prepare_native_stores import discovery_ready
from prepare_rdf_tdb import stream_pin
from rdf_tdb_session import RdfTdbSession
from run_external_federation_tiny import ready
from xgap.experiments.campaign_source_observer import CampaignSourceObserver
from xgap.experiments.m15_native_services import LoopbackPortReservations, _neo4j_configuration, _fuseki_server_configuration
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.owned_resources import OwnedProcess


def resolve_profile_inputs(doc,origin):
    """Relocate references, never prompt contents or their frozen checksums."""
    for key in ('estimator','catalog'):
        doc[key]['path']=str((Path(origin)/doc[key]['path']).resolve())
    for mode in doc['modes'].values():
        prompt=mode['provider']['prompt']
        prompt['path']=str((Path(origin)/prompt['path']).resolve())
        read_pinned(prompt['path'],prompt['sha256'])


class NativeStoreSession(RdfTdbSession):
    serving_copy_paths=('neo4j/data','neo4j/transactions','control-tdb2')

    def start(self):
        at=time.perf_counter()
        try:
            if self.prepared.get('schema_version')!='xgap-frozen-native-stores-v1':
                raise ValueError('Native session requires native prepared stores')
            parent=self.prepared['profile'];base=Path(parent['path'])
            doc=json.loads(read_pinned(base,parent['sha256']))
            resolve_profile_inputs(doc,base.parent)
            build=json.loads(read_pinned(self.input_pin['path'],self.input_pin['sha256']))
            if build['profile']!=parent or set(self.prepared['stores'])!={'neo4j','control'}:
                raise ValueError('Native preparation/profile identity mismatch')
            if {s['client']['engine'] for s in doc['backends'].values()}!={'neo4j','fuseki'}:
                raise ValueError('Native session requires both declared engine types')
            for pin in build['neo4j_engine_files']+[build['java'],build['fuseki_jar']]:
                if stream_pin(pin['path'])!=pin:raise ValueError('Native prepared engine changed')
            for name,source in (('neo4j','load_neo4j_batches.jsonl'),('control','control.ttl')):
                store=self.prepared['stores'][name]
                seal=json.loads(read_pinned(store['seal']['path'],store['seal']['sha256']))
                loads=doc['offline'].get('native_load_files',doc['offline'].get('load_files',{}))
                if seal['source']['sha256']!=loads[source]['sha256']:
                    raise ValueError('Native store source mismatch')
                parts=['data','transactions'] if name=='neo4j' else ['.']
                if name=='neo4j' and (seal['parts']!=parts or store['parts']!=parts):
                    raise ValueError('Unexpected native store parts')
                actual=[stream_pin(p) for part in parts for p in sorted((Path(store['path'])/part).rglob('*')) if p.is_file()]
                if actual!=seal['files']:raise ValueError('Frozen native store changed: '+name)
                if shutil.disk_usage(self.root).free<store['bytes']+6*1024**3:
                    raise ValueError('Insufficient native serving-copy reserve')
                if name=='neo4j':
                    for part in parts:shutil.copytree(Path(store['path'])/part,self.root/'neo4j'/part)
                else:shutil.copytree(store['path'],self.root/'control-tdb2')
            neo=Path(build['neo4j_root']);conf=self.root/'neo4j-conf';conf.mkdir()
            for part in ('logs','run','import','plugins'):(self.root/'neo4j'/part).mkdir()
            self.ports=LoopbackPortReservations.acquire(3);np,bp,fp=self.ports.ports
            memory={'heap_initial_size':'256m','heap_max_size':'768m','pagecache_size':'128m'}
            (conf/'neo4j.conf').write_text(_neo4j_configuration(neo4j_root=neo,state_root=self.root,
                http_port=np,bolt_port=bp,resource_profile=memory,query_timeout_seconds=self.budget.timeout_seconds))
            self.ports.release(0);self.ports.release(1)
            process=self.processes.start('source-neo4j',[str(neo/'bin/neo4j'),'console'],cwd=neo,
                env={'JAVACMD':build['java']['path'],'NEO4J_CONF':str(conf),'NEO4J_HOME':str(neo)})
            self.owned.append(OwnedProcess('neo4j','source',process))
            health=discovery_ready(process,f'http://127.0.0.1:{np}/')
            rdf=self.root/'fuseki-control';rdf.mkdir()
            (rdf/'config.ttl').write_text(_fuseki_server_configuration(query_timeout_seconds=self.budget.timeout_seconds))
            fuseki=[s for s in doc['backends'].values() if s['client']['engine']=='fuseki']
            native=[s for s in doc['backends'].values() if s['client']['engine']=='neo4j']
            if len(native)!=1 or len(fuseki)!=1 or native[0]['client']['database']!='neo4j':
                raise ValueError('One Neo4j database and one control endpoint required')
            dataset=fuseki[0]['client']['database'];self.ports.release(2)
            process=self.processes.start('source-control',[build['java']['path'],'-Xms128m','-Xmx768m',
                '-jar',build['fuseki_jar']['path'],'--localhost','--port',str(fp),'--tdb2',
                '--loc',str(self.root/'control-tdb2'),'/'+dataset],cwd=Path(build['fuseki_jar']['path']).parent,
                env={'FUSEKI_BASE':str(rdf)})
            self.owned.append(OwnedProcess('control','source',process));ready(process,fp)
            routes={'/db/neo4j/tx/commit':f'http://127.0.0.1:{np}/db/neo4j/tx/commit',
                    '/'+dataset+'/sparql':f'http://127.0.0.1:{fp}/{dataset}/sparql'}
            self.observer=CampaignSourceObserver(routes,self.root/'source-observations',budget=self.budget)
            for spec in doc['backends'].values():
                spec['client'].update(url=self.observer.base_url,timeout_seconds=self.budget.timeout_seconds)
            doc['offline'].update(serving_endpoint_parent=parent,prepared_stores=self.prepared_pin)
            self.profile=write_once(self.root/'profile.json',doc)
            FrozenOneShotProfile.load(self.profile['path'],expected_sha256=self.profile['sha256'])
            self.ready_pin=write_once(self.root/'ready.json',{'prepared':self.prepared_pin,'profile':self.profile,
                'source_urls':routes,'observation_url':self.observer.base_url,'deployment':'native',
                'query_timeout_seconds':self.budget.timeout_seconds,'neo4j_memory':memory,'fuseki_heap':'768m',
                'source_query_contract':'compiled read-only queries on private serving copies; no runtime loader',
                'discovery':health,'warmup_queries':0,'offline_fresh_session_ms':(time.perf_counter()-at)*1000,
                'source_groups':[{'name':s.name,'pid':s.process.pid} for s in self.owned]})
            return self
        except BaseException:
            self.close();raise


class NativeSources:
    """The common controller's resource interface, with no external method host."""
    def __init__(self,session):
        self.session=session;self.initializations={};self.endpoints={}

    def start(self,method):
        raise ValueError('External RDF baselines cannot run on the native deployment')

    def owned_for(self,method):
        from xgap.agent.nl_strong_question import NL_STRONG_METHODS, NL_USER_METHODS, NL_FAMILY_METHODS
        from xgap.experiments.bounded_joint_contract import METHODS as JOINT_METHODS
        if method not in ('xgap-native','xgap-precision','xgap-performance',*NL_STRONG_METHODS,
                          *NL_USER_METHODS,*NL_FAMILY_METHODS,*JOINT_METHODS):
            raise ValueError('Unknown native method')
        return self.session.owned
