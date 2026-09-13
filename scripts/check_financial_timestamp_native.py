#!/usr/bin/env python3
"""One SELECT over finite VALUES at a private Fuseki; no dataset/model/baseline."""
import argparse
import json
from pathlib import Path
import subprocess

from prepare_rdf_tdb import REPO, stream_pin
from run_external_federation_tiny import Processes, ready
from test_financial_timestamp_v2 import cases
from xgap.compilers.global_semantic_sparql import condition, literal
from xgap.experiments.external_federation import deadline, query_once
from xgap.experiments.m15_native_services import LoopbackPortReservations
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.process_guard import _stop_group, ProcessBudget


def main(output):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    java=Path('/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home/bin/java')
    jar=Path('/Users/anthonyche/xgap-data/d202-local-native-20260910-diagnostic2/runtime/apache-jena-fuseki-5.6.0/fuseki-server.jar')
    processes=Processes(root);ports=LoopbackPortReservations.acquire(1)
    receipt={'schema_version':'xgap-financial-timestamp-native-gate-v2','success':False,
        'model_calls':0,'data_loads':0,'baseline_calls':0,'fit_calls':0,'maximum_queries':1,
        'automatic_retries':0,'paper_result':False}
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):raise ValueError('Commit before live gate')
        receipt['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
        arms=[];expected={}
        for i,(left,right,op,value) in enumerate(cases()):
            values=['UNDEF' if v is None else literal(v) for v in (left,right)]
            c={'op':op,'field':'a','right_field':'b','value_type':'timestamp_ms'}
            arms.append('{ VALUES (?a ?b) { ('+' '.join(values)+') } BIND('+str(i)+' AS ?id) '
                'BIND('+condition(c,{'a':'?a','b':'?b'})+' AS ?passed) }')
            expected[str(i)]=value
        query='SELECT ?id ?passed WHERE { '+' UNION '.join(arms)+' } ORDER BY ?id'
        assert len(query.encode())<65536
        receipt['input']=write_once(root/'input.json',{'java':stream_pin(java),'fuseki':stream_pin(jar),
            'cases':cases(),'query':query,'expected':expected,'query_timeout_seconds':15,'heap_mib':512})
        with deadline(45):
            port=ports.ports[0];ports.release(0)
            process=processes.start('fuseki',[str(java),'-Xms128m','-Xmx512m','-jar',str(jar),
                '--localhost','--port',str(port),'--mem','/ds'],cwd=jar.parent,env={'FUSEKI_BASE':str(root/'state')})
            ready(process,port)
            record=query_once(f'http://127.0.0.1:{port}/ds/sparql',query,seconds=15,output=root/'query.json')
            if record.get('http_status')!=200:raise ValueError('Native time predicate query failed')
            rows=json.loads(record['body_utf8'])['results']['bindings']
            actual={r['id']['value']:r['passed']['value']=='true' for r in rows}
            receipt.update(success=len(rows)==len(expected) and actual==expected,
                actual=actual,case_count=len(expected),query_calls=1,response_bytes=record['response_body_bytes'])
    except Exception as error:receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        closure=[]
        for name,process in reversed(processes.owned):
            result=_stop_group(process,ProcessBudget())
            if result['complete'] and process.poll() is None:process.wait(timeout=2)
            closure.append({'name':name,'pid':process.pid,'returncode':process.poll(),**result})
        for log in processes.logs:log.close()
        ports.close();receipt['closure']=closure
        receipt['success'] &= all(c['complete'] and c['returncode'] is not None for c in closure)
        pin=write_once(root/'receipt.json',receipt)
    print(json.dumps({'success':receipt['success'],'receipt':pin,'error':receipt.get('error')}))
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    raise SystemExit(main(**vars(parser.parse_args())))
