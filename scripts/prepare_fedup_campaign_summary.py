#!/usr/bin/env python3
"""Original author summary, built once offline on stable logical source names."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time

from prepare_rdf_tdb import stream_pin, DiskBoundary, GIB
from check_common_rdf_trial import JAVA, JARS, PINS
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.process_guard import ProcessBudget, run_guarded_command

REPO=Path(__file__).resolve().parents[1]
LOGICAL_BASE='http://xgap-source.invalid'


def prepare(*,profile,profile_sha256,output):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False);started=time.perf_counter()
    receipt={'schema_version':'xgap-frozen-author-summary-v1','success':False,'stages':[],
        'model_calls':0,'evaluation_queries':0,'automatic_retries':0,'baseline_algorithm_changes':0,
        'hash_modulo':1,'logical_source_base':LOGICAL_BASE,'phase':'offline_preprocessing'}
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):raise ValueError('Commit before author execution')
        receipt['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
        doc=json.loads(read_pinned(profile,profile_sha256));loads=doc['offline']['rdf_loads'];sources={}
        if set(loads)!={'graph','control'}:raise ValueError('Expected graph/control RDF sources')
        for name,load in loads.items():
            pin=stream_pin(load['path'])
            if pin['sha256']!=load['sha256']:raise ValueError('Frozen source changed: '+name)
            sources[name]=pin
        jars={name:stream_pin(JARS[name]) for name in ('fedup','summary','fedx')}
        if any(jars[n]['sha256']!=PINS[n] for n in jars):raise ValueError('Pinned author artifact changed')
        if shutil.disk_usage(root).free<16*GIB:raise ValueError('Insufficient preparation reserve')
        receipt.update(dataset=doc['dataset'],profile={'path':str(Path(profile).resolve()),'sha256':profile_sha256})
        receipt['input_seal']=write_once(root/'input-seal.json',{'profile':receipt['profile'],'sources':sources,
            'jars':jars,'java':stream_pin(JAVA),'logical_sources':{n:LOGICAL_BASE+'/'+n+'/sparql' for n in sources},
            'source_queries':0,'offline_named_graph_loads':2,'maximum_summary_calls':1,
            'loader_heap_bytes':2*GIB,'loader_sampled_rss_bytes':3*GIB,
            'summary_heap_bytes':4*GIB,'summary_sampled_rss_bytes':6*GIB,'per_stage_seconds':900})
        disk=DiskBoundary(root);tdb=root/'summary-input';summary=root/'frozen-summary';summary.mkdir()
        stages=[('load-'+name,[JAVA,'-Xms128m','-Xmx2g','-cp',jars['fedup']['path'],'tdb2.tdbloader',
            '--loc',str(tdb),'--graph',LOGICAL_BASE+'/'+name+'/sparql',sources[name]['path']],3*GIB)
            for name in ('graph','control')]
        stages.append(('summarize',[JAVA,'-Xms128m','-Xmx4g','-jar',jars['summary']['path'],
            '--input',str(tdb),'--output',str(summary),'--hash','1'],6*GIB))
        for name,command,rss in stages:
            guard=run_guarded_command(command,cwd=REPO,output=root/name,resource_monitor=disk,
                budget=ProcessBudget(wall_seconds=900,max_group_rss_bytes=rss,max_log_bytes=4*1024**2,sample_seconds=.1))
            receipt['stages'].append({'name':name,'guard':guard})
            if not guard['success']:raise RuntimeError('Author preparation failed without retry: '+name)
        files=[stream_pin(p) for p in sorted(summary.rglob('*')) if p.is_file()]
        receipt['summary_seal']=write_once(root/'summary-seal.json',{'input':receipt['input_seal'],
            'path':str(summary),'files':files,'hash_modulo':1,'logical_source_base':LOGICAL_BASE})
        receipt['sources_unchanged']=all(stream_pin(p['path'])==p for p in sources.values())
        receipt['success']=receipt['sources_unchanged'];receipt['summary_bytes']=sum(p['bytes'] for p in files)
    except Exception as error:receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        receipt['offline_elapsed_ms_before_receipt']=(time.perf_counter()-started)*1000
        receipt['cost_scope']='offline input/engine verification, named graph loads, original summarizer, cleanup and sealing; final receipt write excluded'
        pin=write_once(root/'receipt.json',receipt)
    print(json.dumps({'success':receipt['success'],'receipt':pin,'offline_ms':receipt['offline_elapsed_ms_before_receipt'],
        'summary_bytes':receipt.get('summary_bytes'),'error':receipt.get('error')}))
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('profile','profile-sha256','output'):p.add_argument('--'+name,required=True)
    raise SystemExit(prepare(**vars(p.parse_args())))
