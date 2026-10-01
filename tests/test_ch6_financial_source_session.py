"""Configuration/routing/lifecycle tests; no database load or scale experiment."""
import json
from pathlib import Path
from types import SimpleNamespace
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request

import pytest
import ch6_financial_source_session as sources
from xgap.experiments.campaign_source_observer import CampaignSourceObserver, SourceObservationBudget


def runtime(tmp_path):
    return dict(neo4j_root=str(tmp_path/'neo'), java={'path':str(tmp_path/'java')},
                fuseki_jar={'path':str(tmp_path/'fuseki.jar')})


def test_32_sources_have_distinct_observer_routes_and_48_ports(tmp_path):
    config=runtime(tmp_path); specs=[]; cursor=18000
    for i in range(32):
        name=('neo4j-' if i<16 else 'rdf-')+f'{i:02d}'
        source=dict(source_id=name,engine='neo4j' if i<16 else 'rdf')
        count=2 if i<16 else 1
        spec=sources.source_commands(source,config,tmp_path/('s'+str(i)),tmp_path/('db'+str(i)),
                                     list(range(cursor,cursor+count)),tmp_path/'overlay',840,client_seconds=860)
        cursor+=count;specs.append(spec)
        assert spec['client']['timeout_seconds']==860
        if i<16:
            conf=(tmp_path/('s'+str(i))/'conf/neo4j.conf').read_text()
            assert 'server.memory.heap.max_size=1g' in conf
            assert 'server.memory.pagecache.size=1g' in conf
            assert 'server.jvm.additional=-XX:ActiveProcessorCount=2' in conf
            assert 'db.transaction.timeout=840s' in conf
            assert '/'+name+'/db/neo4j/tx/commit'==spec['route']
            assert spec['upstream'].endswith('/db/neo4j/tx/commit')
        else:
            assert '-Xmx1g' in spec['command'] and '-Dxgap.rangeOverlay=lazy-v2' in spec['command']
            assert '--timeout=840000' in spec['command']
            assert ['XgapStorageMode','direct']==spec['command'][spec['command'].index('XgapStorageMode'):][:2]
    assert cursor==18048 and len({s['route'] for s in specs})==32
    assert len({s['upstream'] for s in specs})==32


def test_bulk_loader_is_offline_bounded_and_database_precedes_variadic_inputs(tmp_path):
    assert any('REQUIRE n.id IS UNIQUE' in statement for statement in sources.INDEXES)
    assert any('REQUIRE n.xgap_id IS UNIQUE' in statement for statement in sources.INDEXES)
    s=dict(source_id='neo4j-00',engine='neo4j',native_bulk_files={
        'nodes-Account.csv.gz':{'path':'/frozen/nodes.csv.gz'},
        'relationships.csv.gz':{'path':'/frozen/edges.csv.gz'}})
    command=sources.import_command(s,runtime(tmp_path),tmp_path/'store',tmp_path/'report')
    assert command[1:5]==['database','import','full','neo4j']
    assert '--threads=4' in command and '--max-off-heap-memory=4G' in command
    assert '--skip-bad-relationships=false' in command and '--skip-duplicate-nodes=false' in command
    assert not any('overwrite' in value for value in command)
    rdf=dict(source_id='rdf-16',engine='rdf',rdf_load={'path':'/frozen/data.nt.gz'})
    command=sources.import_command(rdf,runtime(tmp_path),tmp_path/'rdf-store',tmp_path/'report')
    assert '-Xmx4g' in command and '-XX:ActiveProcessorCount=4' in command
    assert command[-4:]==['tdb2.tdbloader','--loc',str(tmp_path/'rdf-store'),'/frozen/data.nt.gz']


def test_native_prefix_routes_actual_http_to_independent_sources(tmp_path):
    calls=[];servers=[];threads=[]
    def handler(label):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                body=self.rfile.read(int(self.headers['Content-Length']))
                calls.append((label,self.path,body))
                data=json.dumps({'source':label}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        return Handler
    for label in ('neo4j-00','neo4j-01'):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(label));thread=threading.Thread(target=server.serve_forever)
        thread.start();servers.append(server);threads.append(thread)
    routes={'/'+label+'/db/neo4j/tx/commit':f'http://127.0.0.1:{server.server_port}/db/neo4j/tx/commit'
            for label,server in zip(('neo4j-00','neo4j-01'),servers)}
    observer=CampaignSourceObserver(routes,tmp_path/'observations',budget=SourceObservationBudget(timeout_seconds=2))
    try:
        for label in ('neo4j-00','neo4j-01'):
            req=urllib.request.Request(observer.base_url+'/'+label+'/db/neo4j/tx/commit',data=b'{"statements":[]}',headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=3) as response:
                assert json.load(response)['source']==label
        assert [(label,path) for label,path,_ in calls]==[
            ('neo4j-00','/db/neo4j/tx/commit'),('neo4j-01','/db/neo4j/tx/commit')]
        assert observer.settle()
    finally:
        observer.close()
        for server in servers:server.shutdown();server.server_close()
        for thread in threads:thread.join(timeout=3)


def test_integrity_reads_actual_counts_and_rejects_wrong_store(tmp_path):
    class Client:
        def __init__(self,counts):self.counts=iter(counts);self.calls=[]
        def execute(self,artifact):
            self.calls.append(artifact)
            n=next(self.counts)
            return SimpleNamespace(success=True,rows=[{'count':n}],to_dict=lambda:dict(success=True,rows=[{'count':n}]))
    good=Client([100,1000]);s=dict(engine='neo4j',source_id='neo4j-00',materialized_nodes=100,logical_edges=1000)
    assert sources.integrity(good,s,tmp_path)==dict(nodes=100,relationships=1000)
    assert len(good.calls)==2 and all('count(' in c.text for c in good.calls)
    other=tmp_path/'bad';other.mkdir()
    with pytest.raises(ValueError,match='count mismatch'):
        sources.integrity(Client([99]),s,other)
    rdf=tmp_path/'rdf';rdf.mkdir();s.update(engine='rdf',source_id='rdf-16',rdf_triples=8400)
    assert sources.integrity(Client(['8400','100','1000']),s,rdf)==dict(triples=8400,nodes=100,edges=1000)


def test_session_retirement_requires_every_owned_group_and_observer(tmp_path,monkeypatch):
    session=object.__new__(sources.FinancialSourceSession)
    process=SimpleNamespace(pid=123,poll=lambda:143)
    session.processes=SimpleNamespace(owned=[('neo4j-00',process)],logs=[])
    session.root=tmp_path;session.ports=SimpleNamespace(close=lambda:None)
    session.observer=SimpleNamespace(close=lambda:None,thread=SimpleNamespace(is_alive=lambda:False),inflight=0)
    monkeypatch.setattr(sources,'_stop_group',lambda *args,**kwargs:dict(complete=False,live_pids=[123]))
    result=session.close()
    assert not result['owned_groups_drained'] and result['observer_stopped']
    assert result['serving_copies_retained'] and (tmp_path/'closed.json').exists()


def test_initial_readiness_does_not_hide_an_earlier_service_exit():
    owned=[SimpleNamespace(name='source-'+str(i),process=SimpleNamespace(poll=lambda:None)) for i in range(32)]
    sources.require_live_sources(owned)
    owned[0].process.poll=lambda:1
    with pytest.raises(RuntimeError,match='source-0'):
        sources.require_live_sources(owned)


def test_complete_loads_require_terminal_retirement_for_every_sealed_source(monkeypatch):
    closures={str(i):dict(loaded_and_sealed=True,owned_process_terminal=True,cleanup=dict(complete=True)) for i in range(32)}
    receipt=dict(stores={k:{} for k in closures},source_attempts={k:k for k in closures})
    monkeypatch.setattr(sources,'load_pin',lambda p:closures[p])
    assert sources.completed_loads(receipt)
    closures['0']['cleanup']['complete']=False
    assert not sources.completed_loads(receipt)
    closures['0']['cleanup']['complete']=True
    closures['1']['owned_process_terminal']=False
    assert not sources.completed_loads(receipt)


def grouped_materialization(tmp_path, count):
    """Pinned input bytes for configuration/lifecycle tests, not source data."""
    root=tmp_path/'grouped-inputs';root.mkdir()
    layout=sources.grouped_layout(count,nodes_per_bank=9);records=[]
    for group in layout['sources']:
        source={k:group[k] for k in ('source_id','engine','atoms','logical_edges')}
        source.update(materialized_nodes=group['accounts'],owned_accounts=group['accounts'])
        directory=root/source['source_id'];directory.mkdir()
        if source['engine']=='neo4j':
            source['native_bulk_files']={}
            for name in ('nodes-Account.csv.gz','relationships.csv.gz'):
                file=directory/name;file.write_bytes((source['source_id']+name).encode())
                source['native_bulk_files'][name]=sources.stream_pin(file)
            source['rdf_triples']=0
        else:
            file=directory/'data.nt.gz';file.write_bytes(source['source_id'].encode())
            source['rdf_load']=sources.stream_pin(file)
            source['rdf_triples']=4*source['materialized_nodes']+8*source['logical_edges']
        records.append(source)
    doc=dict(schema_version='xgap-financial-mixed-loads-v1',success=True,source_count=count,
        grouping_profile=sources.GROUPING_PROFILE,layout=layout,logical_nodes=288,
        logical_edges=2880,logical_facts_sha256='same-canonical-graph',sources=records)
    return doc,sources.write_once(root/'receipt.json',doc)


@pytest.mark.parametrize('count',[2,4,8,16,32])
def test_grouped_materialization_validates_actual_engine_and_all_atoms(tmp_path,count):
    doc,pin=grouped_materialization(tmp_path,count)
    assert sources.materialized_sources(pin)==doc
    rdf=doc['sources'][count//2]
    assert rdf['source_id']==('rdf-16' if count==32 else 'rdf-00')
    command=sources.import_command(rdf,runtime(tmp_path),tmp_path/'store',tmp_path/'report')
    assert 'tdb2.tdbloader' in command and '-Xmx4g' in command
    assert sorted(b for s in doc['sources'] for b in s['atoms'])==list(range(32))


@pytest.mark.parametrize('change', ['count','engine','atoms','duplicate','layout','edge_count','node_count','triple_count','profile','files'])
def test_grouped_materialization_rejects_inconsistent_or_changed_inputs(tmp_path,change):
    doc,pin=grouped_materialization(tmp_path,4)
    if change=='count':doc['source_count']=8
    elif change=='engine':doc['sources'][2]['engine']='neo4j'
    elif change=='atoms':doc['sources'][2]['atoms']=[0]
    elif change=='duplicate':doc['sources'][3]['source_id']=doc['sources'][2]['source_id']
    elif change=='layout':doc['layout']['sources'][0]['accounts']+=1
    elif change=='edge_count':doc['sources'][0]['logical_edges']+=1
    elif change=='node_count':doc['sources'][0]['materialized_nodes']=1
    elif change=='triple_count':doc['sources'][2]['rdf_triples']+=1
    elif change=='profile':doc.pop('grouping_profile')
    else:Path(doc['sources'][2]['rdf_load']['path']).write_bytes(b'changed')
    pin=sources.write_once(tmp_path/'changed-material.json',doc)
    with pytest.raises(ValueError):sources.materialized_sources(pin)


@pytest.mark.parametrize('count',[2,4,8,16,32])
def test_fixed_serving_memory_keeps_aggregate_caps_constant(tmp_path,count):
    memory=sources.serving_memory(count,sources.FIXED_MEMORY_PROFILE)
    gib=32//count
    assert memory['aggregate_configured_heap_gib']==32
    assert memory['aggregate_neo4j_pagecache_gib']==16
    assert memory['rdf_heap_initial']==memory['neo4j']['heap_initial_size']=='256m'
    assert memory['rdf_heap_max']==memory['neo4j']['heap_max_size']==f'{gib}g'
    assert memory['neo4j']['pagecache_size']==f'{gib}g'
    for engine,ports in (('neo4j',[18000,18001]),('rdf',[18002])):
        source=dict(source_id=engine+'-00',engine=engine)
        config=sources.source_commands(source,runtime(tmp_path),tmp_path/engine,
            tmp_path/(engine+'-store'),ports,tmp_path/'overlay',600,client_seconds=610,memory=memory)
        if engine=='neo4j':
            conf=(tmp_path/engine/'conf/neo4j.conf').read_text()
            assert f'server.memory.heap.max_size={gib}g' in conf
            assert f'server.memory.pagecache.size={gib}g' in conf
        else:
            assert '-Xms256m' in config['command'] and f'-Xmx{gib}g' in config['command']
    # New serving caps do not enlarge offline importer resources.
    assert sources.serving_memory(32)['neo4j']==sources.MEMORY
    assert sources.serving_memory(32)['rdf_heap_initial']=='128m'


def test_memory_profiles_and_source_ports_reject_unfrozen_values(tmp_path):
    for count in (1,3,64,True):
        with pytest.raises(ValueError):sources.serving_memory(count,sources.FIXED_MEMORY_PROFILE)
    with pytest.raises(ValueError):sources.serving_memory(2,'arbitrary')
    with pytest.raises(ValueError,match='ports'):
        sources.source_commands(dict(source_id='neo4j-00',engine='neo4j'),runtime(tmp_path),
            tmp_path/'invalid',tmp_path/'store',[18000],tmp_path/'overlay',600,client_seconds=610)
    assert not (tmp_path/'invalid').exists()


def test_live_source_check_uses_exact_group_ids_and_catches_missing_or_exited():
    ids=['neo4j-00','rdf-00']
    owned=[SimpleNamespace(name=name,process=SimpleNamespace(poll=lambda:None)) for name in ids]
    sources.require_live_sources(owned,ids)
    with pytest.raises(RuntimeError,match='declared'):sources.require_live_sources(owned[:1],ids)
    with pytest.raises(RuntimeError,match='declared'):sources.require_live_sources(owned,['neo4j-00','rdf-01'])
    owned[1].process.poll=lambda:143
    with pytest.raises(RuntimeError,match='rdf-00'):sources.require_live_sources(owned,ids)


@pytest.fixture
def resumable_load(tmp_path, monkeypatch):
    """Real pins and store bytes; the interrupted eleventh import is preserved."""
    base=tmp_path/'old';base.mkdir();root=base/'loaded';root.mkdir();(root/'stores').mkdir()
    inputs=base/'materialized';inputs.mkdir();rows=[]
    for i in range(32):
        name=('neo4j-' if i<16 else 'rdf-')+f'{i:02d}'
        source=dict(source_id=name,engine='neo4j' if i<16 else 'rdf',atoms=[i],
                    materialized_nodes=20+i,logical_edges=100,rdf_triples=700 if i>=16 else 0)
        folder=inputs/name;folder.mkdir()
        names=['nodes-Account.csv.gz','relationships.csv.gz'] if i<16 else ['load.nt.gz']
        pins={}
        for filename in names:
            path=folder/filename;path.write_bytes((name+filename).encode());pins[filename]=sources.stream_pin(path)
        if i<16:source['native_bulk_files']=pins
        else:source['rdf_load']=pins['load.nt.gz']
        rows.append(source)
    material=dict(schema_version='xgap-financial-mixed-loads-v1',success=True,source_count=32,
        sources=rows,logical_edges=3200,logical_facts_sha256='canonical-facts')
    material_pin=sources.write_once(inputs/'receipt.json',material)
    engines=runtime(tmp_path);engine_pin=sources.write_once(base/'input-seal.json',engines)
    monkeypatch.setattr(sources,'runtime_from_seal',lambda pin:engines)
    prior=dict(schema_version=sources.SCHEMA,success=False,materialization=material_pin,
        runtime_input_seal=engine_pin,runtime=engines,sources=rows,index_statements=list(sources.INDEXES),
        logical_facts_sha256=material['logical_facts_sha256'],storage_root=str(root/'stores'),
        stores={},source_attempts={})
    for source in rows[:11]:
        name=source['source_id'];evidence=root/name;evidence.mkdir()
        store=root/'stores'/name;(store/'data').mkdir(parents=True);(store/'transactions').mkdir()
        (store/'data/index').write_bytes((name+'-data').encode())
        (store/'transactions/log').write_bytes((name+'-tx').encode())
        sealed=name!='neo4j-10'
        if sealed:
            files=[sources.stream_pin(store/'data/index'),sources.stream_pin(store/'transactions/log')]
            seal=sources.write_once(evidence/'store-seal.json',dict(store=str(store),parts=['data','transactions'],
                files=files,source=source,observed=dict(nodes=source['materialized_nodes'],relationships=100)))
            prior['stores'][name]=dict(path=str(store),parts=['data','transactions'],
                files=len(files),bytes=sum(p['bytes'] for p in files),seal=seal)
        closure=dict(loaded_and_sealed=sealed,owned_process_terminal=True,
            cleanup=dict(complete=True,live_pids=[]) if sealed else dict(complete=True,service_not_started=True))
        prior['source_attempts'][name]=sources.write_once(evidence/'attempt-closure.json',closure)
        guard=evidence/'load-guard';guard.mkdir()
        sources.write_once(guard/'receipt.json',dict(schema_version='xgap-process-guard-v1',
            success=sealed,status='completed' if sealed else 'monitor_failed',exit_code=0 if sealed else 143,
            cleanup=dict(complete=True,live_pids=[],post_stop_reap_returncode=0 if sealed else 143)))
    prior['durable_store_bytes']=sum(s['bytes'] for s in prior['stores'].values())
    pin=sources.write_once(root/'receipt.json',prior)
    return SimpleNamespace(root=root,prior=prior,pin=pin,material=material,material_pin=material_pin,
        runtime=engines,runtime_pin=engine_pin,output=tmp_path/'new-loaded')


def repin_json(pin, transform):
    path=Path(pin['path']);doc=json.loads(path.read_text());transform(doc)
    path.write_text(json.dumps(doc));return sources.stream_pin(path)


def check_resume(fixture):
    return sources.verified_resume(fixture.pin,fixture.material_pin,fixture.runtime_pin,
        fixture.material,fixture.runtime,fixture.output)


def test_resume_verifies_actual_sealed_bytes_and_old_retirement(resumable_load):
    f=resumable_load;before={p:p.read_bytes() for p in f.root.rglob('*') if p.is_file()}
    prior,provenance=check_resume(f)
    assert list(prior['stores'])==[f'neo4j-{i:02d}' for i in range(10)]
    assert provenance['incomplete_source_ids']==['neo4j-10']
    assert len(provenance['loader_guards'])==11
    assert all(p.read_bytes()==content for p,content in before.items())
    # Same byte count, different contents: metadata/size-only checking misses it.
    member=f.root/'stores/neo4j-00/data/index';member.write_bytes(b'x'*member.stat().st_size)
    with pytest.raises(ValueError,match='content changed'):check_resume(f)


@pytest.mark.parametrize('change,match',[
    ('inventory','inventory'),('symlink','links'),('seal_count','source/count/identity'),
    ('seal_source','source/count/identity'),('runtime','source/runtime/materialization'),
    ('materialization','source/runtime/materialization'),('attempt_identity','attempt identity'),
    ('store_identity','seal identity'),('attempt_cleanup','attempt cleanup'),
    ('guard_cleanup','guard cleanup'),('guard_live','guard cleanup'),
    ('guard_exit','guard cleanup'),('incomplete_guard','guard cleanup'),
    ('incomplete_closure','attempt cleanup'),('leftover','unclosed'),('orphan_seal','unrecorded seal'),
])
def test_resume_rejects_changed_identity_inventory_or_incomplete_cleanup(resumable_load,change,match):
    f=resumable_load;prior=f.prior;name='neo4j-00'
    if change=='inventory':(f.root/'stores'/name/'data/extra').write_bytes(b'new')
    elif change=='symlink':(f.root/'stores'/name/'data/link').symlink_to('index')
    elif change in ('seal_count','seal_source'):
        def corrupt(seal):
            if change=='seal_count':seal['observed']['nodes']+=1
            else:seal['source']['source_id']='neo4j-01'
        prior['stores'][name]['seal']=repin_json(prior['stores'][name]['seal'],corrupt)
    elif change=='runtime':prior['runtime']={**prior['runtime'],'neo4j_root':'/different-engine'}
    elif change=='materialization':prior['materialization']={**prior['materialization'],'sha256':'0'*64}
    elif change=='attempt_identity':prior['source_attempts'][name]=prior['source_attempts']['neo4j-01']
    elif change=='store_identity':prior['stores'][name]['path']=prior['stores']['neo4j-01']['path']
    elif change in ('attempt_cleanup','incomplete_closure'):
        name='neo4j-10' if change=='incomplete_closure' else name
        prior['source_attempts'][name]=repin_json(prior['source_attempts'][name],lambda d:d['cleanup'].update(complete=False))
    elif change in ('guard_cleanup','guard_live','guard_exit','incomplete_guard'):
        name='neo4j-10' if change=='incomplete_guard' else name
        updates=({'live_pids':[123]} if change=='guard_live' else
                 {'post_stop_reap_returncode':None} if change=='guard_exit' else {'complete':False})
        repin_json({'path':str(f.root/name/'load-guard/receipt.json')},lambda d:d['cleanup'].update(**updates))
    elif change=='leftover':(f.root/'stores/neo4j-11').mkdir()
    elif change=='orphan_seal':sources.write_once(f.root/'neo4j-10/store-seal.json',{})
    f.pin=repin_json(f.pin,lambda d:d.update(prior))
    with pytest.raises(ValueError,match=match):check_resume(f)


def mock_load_services(monkeypatch, *, fail_source=None):
    imported=[];started=[];samples=[]
    def overlay(runtime,root):root.mkdir();return root
    monkeypatch.setattr(sources,'compile_overlay',overlay)
    monkeypatch.setattr(sources.shutil,'disk_usage',lambda path:SimpleNamespace(free=20*sources.GIB))
    monkeypatch.setattr(sources.LoopbackPortReservations,'acquire',lambda count:SimpleNamespace(
        ports=list(range(18000,18000+count)),release=lambda i:None,close=lambda:None))
    def config(source,runtime,state,store,ports,overlay,backend_seconds,*,client_seconds):
        state.mkdir();(state/'conf').mkdir();(state/'conf/neo4j.conf').write_text('server.memory.heap.max_size=1g\n')
        return dict(command=[source['source_id']],cwd=str(state),env={},client={'url':'http://localhost'})
    monkeypatch.setattr(sources,'source_commands',config)
    monkeypatch.setattr(sources,'import_command',lambda source,runtime,store,report:[source['source_id'],str(store)])
    def guarded(command,*,output,resource_monitor,**kwargs):
        name,directory=command;imported.append(name);store=Path(directory)
        if name.startswith('neo4j-'):
            (store/'data').mkdir();(store/'transactions').mkdir();(store/'data/index').write_bytes(b'new')
        else:(store/'index').write_bytes(b'new-rdf')
        disks = getattr(resource_monitor, 'disks', (resource_monitor,))
        samples.append((resource_monitor, sum(d._tree_bytes() for d in disks)))
        output.mkdir();success=name!=fail_source
        result=dict(schema_version='xgap-process-guard-v1',success=success,
            status='completed' if success else 'monitor_failed',exit_code=0 if success else 143,
            cleanup=dict(complete=True,live_pids=[],post_stop_reap_returncode=0 if success else 143))
        sources.write_once(output/'receipt.json',result)
        return result
    monkeypatch.setattr(sources,'run_guarded_command',guarded)
    def start(name,*args,**kwargs):
        started.append(name);return SimpleNamespace(pid=123,poll=lambda:0)
    monkeypatch.setattr(sources,'Processes',lambda evidence:SimpleNamespace(logs=[],start=start))
    monkeypatch.setattr(sources,'discovery_ready',lambda *args,**kwargs:None)
    monkeypatch.setattr(sources,'fuseki_ready',lambda *args,**kwargs:None)
    monkeypatch.setattr(sources,'_group_sample',lambda pid:[])
    result=SimpleNamespace(success=True,to_dict=lambda:dict(success=True))
    monkeypatch.setattr(sources,'native_clients',lambda specs:{name:SimpleNamespace(execute=lambda query:result) for name in specs})
    monkeypatch.setattr(sources,'integrity',lambda client,source,evidence:
        dict(nodes=source['materialized_nodes'],relationships=source['logical_edges']) if source['engine']=='neo4j' else
        dict(triples=source['rdf_triples'],nodes=source['materialized_nodes'],edges=source['logical_edges']))
    monkeypatch.setattr(sources,'graceful_stop',lambda process:dict(complete=True,exit_code=0,live_pids=[]))
    return imported,started,samples


def test_grouped_loader_seals_two_real_source_identities_and_resumes_without_reimport(tmp_path,monkeypatch):
    material,material_pin=grouped_materialization(tmp_path,2)
    engines=runtime(tmp_path);engine_pin=sources.write_once(tmp_path/'engines.json',engines)
    monkeypatch.setattr(sources,'runtime_from_seal',lambda pin:engines)
    imported,started,_=mock_load_services(monkeypatch)
    prepared_pin=sources.load_stores(material_pin,engine_pin,tmp_path/'first',max_store_bytes=1024**2)
    prepared=sources.load_pin(prepared_pin)
    assert prepared['success'],prepared
    assert imported==started==['neo4j-00','rdf-00']
    assert prepared['source_count']==2 and prepared['layout']==material['layout']
    assert prepared['grouping_profile']==sources.GROUPING_PROFILE
    assert sources.completed_loads(prepared)
    before={p:p.read_bytes() for p in (tmp_path/'first').rglob('*') if p.is_file()}
    resumed=sources.load_pin(sources.load_stores(material_pin,engine_pin,tmp_path/'resumed',
        resume_pin=prepared_pin,max_store_bytes=1024**2))
    assert resumed['success'] and resumed['reused_source_ids']==['neo4j-00','rdf-00']
    assert resumed['loaded_source_ids']==[] and imported==['neo4j-00','rdf-00']
    assert all(p.read_bytes()==content for p,content in before.items())
    prepared['source_attempts'].pop('rdf-00')
    assert not sources.completed_loads(prepared)


@pytest.mark.parametrize('count',[2,4,8,16,32])
def test_grouped_session_starts_exact_endpoints_with_actual_ports_and_fixed_total_memory(tmp_path,monkeypatch,count):
    material,_=grouped_materialization(tmp_path,count)
    engines=runtime(tmp_path);engine_pin=sources.write_once(tmp_path/'engines.json',engines)
    stores={}
    for source in material['sources']:
        sid=source['source_id'];path=tmp_path/('durable-'+sid);path.mkdir()
        seal=sources.write_once(tmp_path/('seal-'+sid+'.json'),dict(store=str(path),parts=['.'],files=[]))
        stores[sid]=dict(path=str(path),parts=['.'],bytes=0,seal=seal)
    prepared={**material,'schema_version':sources.SCHEMA,'stores':stores,
        'runtime':engines,'runtime_input_seal':engine_pin}
    prepared_pin=sources.write_once(tmp_path/'prepared.json',prepared)
    session=sources.FinancialSourceSession(prepared_pin,tmp_path/'session',
        budget=SourceObservationBudget(timeout_seconds=605),backend_seconds=600,client_seconds=610,
        serving_memory_profile=sources.FIXED_MEMORY_PROFILE)
    assert session.source_count==count and session.port_count==3*count//2
    monkeypatch.setattr(sources,'runtime_from_seal',lambda pin:engines)
    monkeypatch.setattr(sources,'copy_sealed_store',lambda *args,**kwargs:{'verified':True})
    monkeypatch.setattr(sources,'compile_overlay',lambda runtime,root:root)
    calls=[];released=[]
    def ports(n):
        calls.append(n)
        return SimpleNamespace(ports=list(range(18000,18000+n)),release=released.append,close=lambda:None)
    monkeypatch.setattr(sources.LoopbackPortReservations,'acquire',ports)
    def start(name,command,**kwargs):
        process=SimpleNamespace(pid=10000+len(session.processes.owned),poll=lambda:None)
        session.processes.owned.append((name,process));return process
    session.processes=SimpleNamespace(owned=[],logs=[],start=start)
    monkeypatch.setattr(sources,'discovery_ready',lambda *args,**kwargs:None)
    monkeypatch.setattr(sources,'fuseki_ready',lambda *args,**kwargs:None)
    def observer(routes,*args,**kwargs):
        assert len(routes)==count and len(set(routes.values()))==count
        return SimpleNamespace(base_url='http://127.0.0.1:19999',close=lambda:None,
            thread=SimpleNamespace(is_alive=lambda:False),inflight=0)
    monkeypatch.setattr(sources,'CampaignSourceObserver',observer)
    monkeypatch.setattr(sources,'_stop_group',lambda *args,**kwargs:dict(complete=True))
    session.start()
    ready=sources.load_pin(session.ready_pin)
    assert ready['logical_sources']==ready['jvm_processes']==count
    assert ready['reserved_ports']==3*count//2 and calls==[3*count//2]
    assert released==list(range(3*count//2))
    assert ready['aggregate_configured_heap_gib']==32 and ready['aggregate_neo4j_pagecache_gib']==16
    assert ready['fuseki_heap_per_source']==f'{32//count}g'
    assert set(session.client_specs)==set(stores)
    for name,spec in session.client_specs.items():
        if spec['engine']=='neo4j':assert spec['url']=='http://127.0.0.1:19999/'+name
        else:assert spec['database']==name and spec['url']=='http://127.0.0.1:19999'
    session.close()


def test_old_atomic_prepared_receipt_still_accepts_legacy_defaults(resumable_load,tmp_path):
    f=resumable_load
    prepared={**f.prior,'success':True,'stores':{s['source_id']:{} for s in f.material['sources']}}
    assert 'source_count' not in prepared and 'logical_edges' not in prepared
    pin=sources.write_once(tmp_path/'old-prepared.json',prepared)
    session=sources.FinancialSourceSession(pin,tmp_path/'legacy-session',budget=SourceObservationBudget(timeout_seconds=850))
    assert session.source_count==32 and session.port_count==48
    assert session.memory['neo4j']==sources.MEMORY and session.memory['rdf_heap_initial']=='128m'


def test_resume_loads_only_unsealed_complement_into_new_paths(resumable_load,monkeypatch):
    f=resumable_load;before={p:p.read_bytes() for p in f.root.rglob('*') if p.is_file()}
    imported,started,samples=mock_load_services(monkeypatch)
    # Borrowed files already consume shared disk; reserve only the remaining
    # active capacity while continuing to count them toward the active bound.
    monkeypatch.setattr(sources.shutil,'disk_usage',lambda path:SimpleNamespace(
        free=8*sources.GIB+1024**2-f.prior['durable_store_bytes']))
    pin=sources.load_stores(f.material_pin,f.runtime_pin,f.output,resume_pin=f.pin,max_store_bytes=1024**2)
    receipt=sources.load_pin(pin)
    assert receipt['success'],receipt
    complement=[s['source_id'] for s in f.material['sources'][10:]]
    assert imported==started==receipt['loaded_source_ids']==complement
    assert receipt['reused_source_ids']==[f'neo4j-{i:02d}' for i in range(10)]
    assert receipt['resume_pin']==f.pin and receipt['reused_store_bytes']==f.prior['durable_store_bytes']
    for name in receipt['reused_source_ids']:
        assert receipt['stores'][name]==f.prior['stores'][name]
        assert receipt['source_attempts'][name]==f.prior['source_attempts'][name]
    assert receipt['stores']['neo4j-10']['path']==str(f.output/'stores/neo4j-10')
    assert all(p.read_bytes()==content for p,content in before.items())
    monitor=samples[-1][0]
    assert monitor._tree_bytes()==f.prior['durable_store_bytes']+sum(p.stat().st_size for p in f.output.rglob('*') if p.is_file())
    monitor.maximum=monitor._tree_bytes()-1
    assert monitor.sample(None,force=True)=='offline_store_disk_budget_reached'
    assert sources.completed_loads(receipt)


@pytest.mark.parametrize('fail_source',['neo4j-10','neo4j-11'])
def test_resume_failure_keeps_borrowed_stores_and_attempt_pins(resumable_load,monkeypatch,fail_source):
    f=resumable_load;imported,started,_=mock_load_services(monkeypatch,fail_source=fail_source)
    pin=sources.load_stores(f.material_pin,f.runtime_pin,f.output,resume_pin=f.pin,max_store_bytes=1024**2)
    receipt=sources.load_pin(pin)
    assert not receipt['success'] and imported[-1]==fail_source
    assert started==receipt['loaded_source_ids']==([] if fail_source=='neo4j-10' else ['neo4j-10'])
    assert all(receipt['stores'][name]==store for name,store in f.prior['stores'].items())
    assert receipt['resume_provenance']['incomplete_source_ids']==['neo4j-10']
    assert all(receipt['source_attempts'][name]==f.prior['source_attempts'][name] for name in f.prior['stores'])
    # A further explicit continuation can validate the inherited original pins.
    verified,provenance=sources.verified_resume(pin,f.material_pin,f.runtime_pin,f.material,f.runtime,f.output.parent/'third')
    assert verified['stores']==receipt['stores'] and provenance['incomplete_source_ids']==[fail_source]


def test_resume_counts_borrowed_bytes_against_the_disk_bound(resumable_load,monkeypatch):
    f=resumable_load;imported,_,_=mock_load_services(monkeypatch)
    receipt=sources.load_pin(sources.load_stores(f.material_pin,f.runtime_pin,f.output,
        resume_pin=f.pin,max_store_bytes=f.prior['durable_store_bytes']))
    assert not receipt['success'] and 'exhaust durable' in receipt['error'] and imported==[]
    assert receipt['stores']==f.prior['stores']


def test_resume_refuses_nested_output_before_mutating_old_artifacts(resumable_load):
    f=resumable_load;output=f.root/'nested'
    with pytest.raises(ValueError,match='disjoint'):
        sources.load_stores(f.material_pin,f.runtime_pin,output,resume_pin=f.pin)
    assert not output.exists()


def test_resume_requires_the_original_receipt_sha(resumable_load):
    f=resumable_load;Path(f.pin['path']).write_text('{}')
    with pytest.raises(ValueError,match='SHA|sha|hash'):
        sources.load_stores(f.material_pin,f.runtime_pin,f.output,resume_pin=f.pin)
    assert not f.output.exists()


def mock_separate_local_disk(monkeypatch, local_parent):
    def identity(path):
        path = Path(path).resolve()
        local = path == local_parent.resolve()
        return dict(path=str(path), device=2 if local else 1, filesystem='xfs' if local else 'nfs4',
                    mount_id='2' if local else '1', mount_point=str(path), mount_source='local' if local else 'shared')
    monkeypatch.setattr(sources, 'filesystem_identity', identity)


@pytest.mark.parametrize('fault', ['same_device', 'network_fs', 'memory_fs', 'no_space', 'existing', 'redirected'])
def test_rdf_workspace_requires_explicit_separate_new_local_disk(tmp_path, monkeypatch, fault):
    durable = tmp_path/'durable'; durable.mkdir(); local_parent = tmp_path/'node'; local_parent.mkdir()
    work = local_parent/'work'
    def identity(path):
        local = Path(path) == local_parent
        return dict(device=1 if fault == 'same_device' or not local else 2,
                    filesystem=('nfs4' if fault == 'network_fs' else 'tmpfs' if fault == 'memory_fs' else 'xfs'))
    monkeypatch.setattr(sources, 'filesystem_identity', identity)
    monkeypatch.setattr(sources.shutil, 'disk_usage', lambda path: SimpleNamespace(
        free=8*sources.GIB if fault == 'no_space' else 100*sources.GIB))
    if fault == 'existing': work.mkdir()
    if fault == 'redirected': work.symlink_to(durable, target_is_directory=True)
    with pytest.raises(ValueError):
        sources.prepare_rdf_work_root(work, durable, 64*sources.GIB, 8*sources.GIB)
    assert work.exists() is (fault in {'existing', 'redirected'})


def test_rdf_input_and_closed_store_roundtrip_preserve_exact_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(sources.shutil, 'disk_usage', lambda path: SimpleNamespace(free=100*sources.GIB))
    original = tmp_path/'load.nt.gz'; original.write_bytes(b'compressed RDF bytes')
    frozen = dict(source_id='rdf-16', engine='rdf', rdf_load=sources.stream_pin(original))
    work = tmp_path/'local'; staged = sources.stage_rdf_input(frozen, work, 64*sources.GIB, 8*sources.GIB)
    assert frozen['rdf_load']['path'] == str(original)
    assert staged['rdf_load']['path'] == str(work/'load.nt.gz')
    assert (work/'load.nt.gz').read_bytes() == original.read_bytes()
    (work/'store/index').write_bytes(b'closed index')
    durable = tmp_path/'durable'; durable.mkdir()
    pins, record = sources.copy_local_rdf_store(work/'store', durable, 64*sources.GIB, 8*sources.GIB)
    assert record['durable_readback_verified'] and record['content_verified']
    assert pins == [sources.stream_pin(durable/'index')]
    assert (durable/'index').read_bytes() == (work/'store/index').read_bytes()


def test_filesystem_identity_uses_longest_escaped_linux_mount(tmp_path, monkeypatch):
    parent = tmp_path/'local disk'; parent.mkdir(); nested = parent/'work'; nested.mkdir()
    escaped = str(parent).replace(' ', r'\040')
    mounts = '1 0 1:1 / / rw - nfs4 remote:/home rw\n'
    mounts += f'2 1 8:1 / {escaped} rw - xfs /dev/sda2 rw\n'
    original_read = Path.read_text
    monkeypatch.setattr(Path, 'read_text', lambda self, *args, **kwargs:
        mounts if str(self) == '/proc/self/mountinfo' else original_read(self, *args, **kwargs))
    record = sources.filesystem_identity(nested)
    assert record['filesystem'] == 'xfs' and record['mount_point'] == str(parent)
    assert record['path'] == str(nested) and record['device'] == nested.stat().st_dev


def test_rdf_staging_rejects_changed_input_without_touching_original(tmp_path, monkeypatch):
    monkeypatch.setattr(sources.shutil, 'disk_usage', lambda path: SimpleNamespace(free=100*sources.GIB))
    original = tmp_path/'load.nt.gz'; original.write_bytes(b'good')
    frozen = dict(rdf_load=sources.stream_pin(original)); original.write_bytes(b'evil')
    with pytest.raises(ValueError, match='changed during staging'):
        sources.stage_rdf_input(frozen, tmp_path/'work', 64*sources.GIB, 8*sources.GIB)
    assert original.read_bytes() == b'evil'


def test_closed_rdf_copy_rejects_corrupt_durable_readback(tmp_path, monkeypatch):
    monkeypatch.setattr(sources.shutil, 'disk_usage', lambda path: SimpleNamespace(free=100*sources.GIB))
    working = tmp_path/'local'; working.mkdir(); (working/'index').write_bytes(b'good')
    durable = tmp_path/'durable'; durable.mkdir(); copy = sources.copy_sealed_store
    def corrupt(source, target, files):
        record = copy(source, target, files); (target/'index').write_bytes(b'evil'); return record
    monkeypatch.setattr(sources, 'copy_sealed_store', corrupt)
    with pytest.raises(ValueError, match='readback differs'):
        sources.copy_local_rdf_store(working, durable, 64*sources.GIB, 8*sources.GIB)
    assert (working/'index').read_bytes() == b'good'


def test_node_local_rdf_load_uses_staged_input_then_seals_durable_and_reclaims(resumable_load, monkeypatch):
    f = resumable_load
    imported, started, _ = mock_load_services(monkeypatch)
    local_parent = f.output.parent/'node-local'; local_parent.mkdir()
    mock_separate_local_disk(monkeypatch, local_parent)
    seen = []; ordinary_import = sources.import_command
    def command(source, runtime, store, report):
        if source['engine'] == 'rdf':
            assert Path(store).parent.parent == local_parent/'workspace'
            assert Path(source['rdf_load']['path']).parent == Path(store).parent
            seen.append(source['source_id'])
        return ordinary_import(source, runtime, store, report)
    monkeypatch.setattr(sources, 'import_command', command)
    receipt = sources.load_pin(sources.load_stores(f.material_pin, f.runtime_pin, f.output,
        resume_pin=f.pin, max_store_bytes=1024**2, rdf_work_root=local_parent/'workspace', rdf_work_bytes=sources.GIB))
    assert receipt['success'], receipt
    assert imported == started and seen == [f'rdf-{i:02d}' for i in range(16, 32)]
    assert list((local_parent/'workspace').iterdir()) == []
    assert len(receipt['rdf_workspaces']) == 16
    for name in seen:
        closure = sources.load_pin(receipt['rdf_workspaces'][name])
        assert closure['durable_copy_verified'] and closure['reclaimed']
        assert closure['sampled_peak_bytes'] >= len(b'new-rdf')
        seal = sources.load_pin(receipt['stores'][name]['seal'])
        assert seal['store'] == str(f.output/'stores'/name)
        assert seal['source'] == next(s for s in f.material['sources'] if s['source_id'] == name)
        assert all(p['path'].startswith(seal['store'] + '/') for p in seal['files'])
    # The usual continuation verifier still admits only durable source seals.
    prior, _ = sources.verified_resume(sources.stream_pin(f.output/'receipt.json'), f.material_pin, f.runtime_pin,
        f.material, f.runtime, f.output.parent/'third')
    assert len(prior['stores']) == 32


def test_failed_local_rdf_import_keeps_partial_work_and_never_starts_it(resumable_load, monkeypatch):
    f = resumable_load; imported, started, _ = mock_load_services(monkeypatch, fail_source='rdf-16')
    local_parent = f.output.parent/'node-local'; local_parent.mkdir()
    mock_separate_local_disk(monkeypatch, local_parent)
    receipt = sources.load_pin(sources.load_stores(f.material_pin, f.runtime_pin, f.output,
        resume_pin=f.pin, max_store_bytes=1024**2, rdf_work_root=local_parent/'workspace', rdf_work_bytes=sources.GIB))
    assert not receipt['success'] and imported[-1] == 'rdf-16' and 'rdf-16' not in started
    assert len(receipt['stores']) == 16
    closure = sources.load_pin(receipt['rdf_workspaces']['rdf-16'])
    assert not closure['reclaimed'] and not closure['durable_copy_verified']
    assert (local_parent/'workspace/rdf-16/store/index').read_bytes() == b'new-rdf'
    assert not (f.output/'rdf-16/store-seal.json').exists()


def test_failed_local_reclamation_stops_before_reusing_its_capacity(resumable_load, monkeypatch):
    f = resumable_load; imported, started, _ = mock_load_services(monkeypatch)
    local_parent = f.output.parent/'node-local'; local_parent.mkdir()
    mock_separate_local_disk(monkeypatch, local_parent)
    def fail_reclaim(path):
        raise OSError('Owned scratch could not be reclaimed')
    monkeypatch.setattr(sources.shutil, 'rmtree', fail_reclaim)
    receipt = sources.load_pin(sources.load_stores(f.material_pin, f.runtime_pin, f.output,
        resume_pin=f.pin, max_store_bytes=1024**2, rdf_work_root=local_parent/'workspace', rdf_work_bytes=sources.GIB))
    assert not receipt['success'] and imported[-1] == started[-1] == 'rdf-16'
    assert 'stop before another load' in receipt['error'] and len(receipt['stores']) == 17
    closure = sources.load_pin(receipt['rdf_workspaces']['rdf-16'])
    assert closure['durable_copy_verified'] and not closure['reclaimed']
    assert 'could not be reclaimed' in closure['reclamation_error']
    assert (f.output/'stores/rdf-16/index').read_bytes() == b'new-rdf'


def test_scheduler_retirement_only_admits_unsealed_failed_import(resumable_load,monkeypatch,tmp_path):
    import ch6_financial_import_retirement as retirement
    f=resumable_load;name='neo4j-10';r=f.root/name/'load-guard'
    gp=repin_json({'path':str(r/'receipt.json')},lambda d:d.update(status='cleanup_incomplete',
        success=False,exit_code=None,attempts=1,automatic_retries=0,
        observed_process_identities=[dict(pid=12345,created=100.0)],
        cleanup=dict(complete=False,pid=12345,live_pids=[12345],signals=['SIGTERM','SIGKILL'])))
    pp=sources.write_once(r/'process.json',dict(pid=12345,created=100.0,process_group=12345))
    before=(r/'receipt.json').read_bytes()
    stage=tmp_path/'stage';stage.mkdir()
    sources.write_once(stage/'handoff.json',dict(resume=dict(job_id='123',loaded=f.pin,
        import_retirement=dict(host='old-node',source_id=name,guard=gp,process=pp))))
    def run(command,stdout,stderr,**kw):
        stdout.write(b'123|FAILED|20|2:0|old-node\n123.batch|FAILED|20|2:0|old-node\n123.extern|COMPLETED|20|0:0|old-node\n'
            if command[0]=='sacct' else b'')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(retirement.subprocess,'run',run)
    monkeypatch.setattr(retirement.socket,'gethostname',lambda:'new-node')
    proof=retirement.capture(stage)
    with pytest.raises(ValueError,match='guard cleanup'):check_resume(f)
    old,provenance=sources.verified_resume(f.pin,f.material_pin,f.runtime_pin,
        f.material,f.runtime,f.output,retirement_pin=proof,retirement_identity=dict(job_id='123',host='old-node'))
    assert name not in old['stores'] and provenance['abandoned_imports'][name]['failed_store_reusable'] is False
    assert provenance['abandoned_imports'][name]['os_process_exit_confirmed'] is False
    assert (r/'receipt.json').read_bytes()==before
    repin_json({'path':str(f.root/'neo4j-00/load-guard/receipt.json')},lambda d:d.update(exit_code=None))
    with pytest.raises(ValueError,match='guard cleanup'):
        sources.verified_resume(f.pin,f.material_pin,f.runtime_pin,f.material,f.runtime,f.output,
            retirement_pin=proof,retirement_identity=dict(job_id='123',host='old-node'))
