#!/usr/bin/env python3
"""One-time, guarded TDB2 loading from an already frozen RDF profile. No queries."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.process_guard import ProcessBudget, run_guarded_command

GIB=1024**3
REPO=Path(__file__).resolve().parents[1]


def stream_pin(path):
    p=Path(path).resolve();digest=hashlib.sha256();size=0
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1024**2),b''):digest.update(chunk);size+=len(chunk)
    return {'path':str(p),'sha256':digest.hexdigest(),'bytes':size}


class DiskBoundary:
    """Sample a private output tree and shared free space; never delete user data."""
    def __init__(self,root,max_store_bytes=10*GIB):
        self.root=root;self.maximum=max_store_bytes;self.at=0;self.peak=0;self.minimum_free=None;self.status=None
    def sample(self,_):
        if time.monotonic()-self.at<1:return self.status
        self.at=time.monotonic();free=shutil.disk_usage(self.root).free
        self.minimum_free=free if self.minimum_free is None else min(free,self.minimum_free)
        size=sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file());self.peak=max(size,self.peak)
        if free<6*GIB:self.status='offline_free_disk_reserve_reached'
        if size>self.maximum:self.status='offline_store_disk_budget_reached'
        return self.status


def prepare(*,profile,profile_sha256,output,java,fuseki_jar,max_store_bytes=10*GIB,load_seconds=900,heap_mib=2048):
    started=time.perf_counter();root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    receipt={'schema_version':'xgap-frozen-rdf-tdb2-v1','success':False,'stores':{},'loads':[],
        'model_calls':0,'query_calls':0,'catalog_builds':0,'estimator_fit_calls':0,'automatic_retries':0,
        'phase':'offline_preprocessing','formal_campaign_ready':False}
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):raise ValueError('Commit loader before native execution')
        receipt['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
        doc=json.loads(read_pinned(profile,profile_sha256));loads=doc['offline']['rdf_loads']
        import re
        if (not 1<=len(loads)<=8 or any(not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}',n) for n in loads)):
            raise ValueError('One to eight named frozen RDF stores required')
        if type(max_store_bytes) is not int or not 256*1024**2<=max_store_bytes<=256*GIB:
            raise ValueError('Explicit store output bound must be 256MiB..256GiB')
        if type(load_seconds) is not int or not 60<=load_seconds<=3600 or type(heap_mib) is not int or not 512<=heap_mib<=8192:
            raise ValueError('Explicit offline process bounds invalid')
        source_pins={}
        for name,load in sorted(loads.items()):
            pin=stream_pin(load['path'])
            if pin['sha256']!=load['sha256'] or pin['bytes']!=load.get('size_bytes',pin['bytes']):
                raise ValueError('Frozen RDF input changed: '+name)
            source_pins[name]=pin
        if shutil.disk_usage(root).free<max_store_bytes+6*GIB:raise ValueError('Reserve declared output plus 6GiB free before starting')
        jar=stream_pin(fuseki_jar);java_pin=stream_pin(java)
        budget=ProcessBudget(wall_seconds=load_seconds,max_group_rss_bytes=(heap_mib+2048)*1024**2,max_log_bytes=4*1024**2,sample_seconds=.1)
        receipt.update(dataset=doc['dataset'],profile={'path':str(Path(profile).resolve()),'sha256':profile_sha256})
        receipt['input_seal']=write_once(root/'input-seal.json',{'profile':receipt['profile'],'sources':source_pins,
            'fuseki_jar':jar,'java':java_pin,'process_budget_per_source':asdict(budget),
            'maximum_loader_invocations':len(loads),'maximum_heap_bytes':heap_mib*1024**2,'maximum_output_bytes':max_store_bytes,
            'minimum_free_disk_bytes':6*GIB,'catalog_and_estimator_reused':True,
            'loader':'tdb2.tdbloader default phased; same jar as serving Fuseki',
            'store_usage':'frozen offline artifacts; serve a copy, never mutate these files'})
        disk=DiskBoundary(root,max_store_bytes)
        for name in sorted(loads):
            store=root/(name+'-tdb2')
            args=[str(java),'-Xms128m',f'-Xmx{heap_mib}m','-cp',jar['path'],'tdb2.tdbloader','--loc',str(store),source_pins[name]['path']]
            guarded=run_guarded_command(args,cwd=REPO,output=root/('load-'+name),budget=budget,resource_monitor=disk)
            receipt['loads'].append({'source':name,'guard':guarded})
            if not guarded['success']:raise RuntimeError('Offline loading failed; partial artifacts retained: '+name)
            files=[stream_pin(p) for p in sorted(store.rglob('*')) if p.is_file()]
            seal=write_once(root/(name+'-store-seal.json'),{'source':source_pins[name],'store':str(store),'files':files})
            receipt['stores'][name]={'path':str(store),'seal':seal,'bytes':sum(p['bytes'] for p in files),'files':len(files)}
        receipt['sources_unchanged']=all(stream_pin(pin['path'])==pin for pin in source_pins.values())
        receipt.update(success=receipt['sources_unchanged'],sampled_output_peak_bytes=disk.peak,
            minimum_sampled_free_disk_bytes=disk.minimum_free)
    except Exception as error:receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        receipt['offline_elapsed_ms_before_receipt']=(time.perf_counter()-started)*1000
        receipt['cost_scope']='offline source pinning, engine loading/indexing, guard cleanup, output sealing; excludes final receipt write'
        pin=write_once(root/'receipt.json',receipt)
    print(json.dumps({'success':receipt['success'],'receipt':pin,'stores':receipt['stores'],
        'error':receipt.get('error'),'offline_ms':receipt['offline_elapsed_ms_before_receipt']}))
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('profile','profile-sha256','output','java','fuseki-jar'):p.add_argument('--'+name,required=True)
    p.add_argument('--max-store-bytes',type=int,default=10*GIB)
    p.add_argument('--load-seconds',type=int,default=900)
    p.add_argument('--heap-mib',type=int,default=2048)
    raise SystemExit(prepare(**vars(p.parse_args())))
