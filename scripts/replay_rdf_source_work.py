"""One captured SELECT replay, with pinned Jena index and Linux I/O diagnostics.

Offline diagnosis only. Never feeds measured candidates into the online planner.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from xgap.experiments.ch6_fact_index import pin
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.process_guard import ProcessBudget, run_guarded_command
from xgap.experiments.verified_store_copy import copy_sealed_store


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('prepared','captured','query-sha256','java','jar','output','work'):
        p.add_argument('--'+name,required=True)
    p.add_argument('--file-mode',choices=('mapped','direct'),default='mapped')
    a=p.parse_args();o=Path(a.output).resolve();o.mkdir(parents=True,exist_ok=False)
    capture=Path(a.captured);q=json.loads(capture.read_text())['query']
    if hashlib.sha256(q.encode()).hexdigest()!=a.query_sha256:
        raise ValueError('Captured query digest changed')
    prepared=Path(a.prepared);s=json.loads(prepared.read_text())['stores']['graph']
    seal=json.loads(Path(s['seal']['path']).read_text());work=Path(a.work).resolve()
    if shutil.disk_usage(work.parent).free<s['bytes']+6*1024**3:
        raise ValueError('Insufficient diagnostic-copy space')
    source=Path(__file__).parent/'java/XgapTdbReplay.java'
    budget=ProcessBudget(wall_seconds=60,max_group_rss_bytes=4*1024**3,max_log_bytes=4*1024**2)
    write_once(o/'intent.json',dict(schema_version='xgap-rdf-source-work-replay-v1',
        purpose='offline failed-request diagnosis; no workload selection or paper latency',
        prepared=pin(prepared),captured=pin(capture),query_sha256=a.query_sha256,
        java_source=pin(source),jar=pin(Path(a.jar)),query_count=1,
        attempts=1,wall_seconds=60,max_rss_bytes=4*1024**3,java_heap='768m',
        os_cache='uncontrolled; verified copy is not a cold-cache guarantee',
        file_mode=a.file_mode,clock_ticks_per_second=os.sysconf('SC_CLK_TCK'),
        page_size_bytes=os.sysconf('SC_PAGE_SIZE'),model_calls=0,full_workload_run=False))
    classes=o/'classes';classes.mkdir();javac=Path(a.java).with_name('javac')
    subprocess.run([str(javac),'-proc:none','--release','21','-cp',a.jar,'-d',str(classes),str(source)],check=True)
    write_once(o/'copy.json',copy_sealed_store(s['path'],work,seal['files']))
    query=o/'query.rq';query.write_text(q)
    outcome=run_guarded_command([a.java,'-Xmx768m','-cp',str(classes)+os.pathsep+a.jar,
        'XgapTdbReplay',str(work),str(query),str(o/'metrics.json'),str(o/'rows.json'),a.file_mode],
        cwd=o,output=o/'guard',budget=budget)
    write_once(o/'receipt.json',dict(guard=outcome,query=pin(query),model_calls=0,
        diagnostic_only=True,source_unchanged=True,
        metric_scope='index tuple yields are not physical records/pages scanned; I/O bytes are not HTTP bytes'))
    if outcome['cleanup']['complete']:
        shutil.rmtree(work)
    print(json.dumps(dict(status=outcome['status'],success=outcome['success'],output=str(o))))

if __name__=='__main__':main()
