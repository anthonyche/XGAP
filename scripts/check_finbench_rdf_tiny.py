#!/usr/bin/env python3
"""Three new FinBench representation checks on one owned Fuseki (not federation).

Development-only: the fixture has eight entities and sixteen relationships. It
does not load SF0.1, call an LLM, run baselines or measure planner effectiveness.
"""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import sys
import time

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'tests'))
from test_finbench_rdf import tiny_partition, parameters, expected_rows
from xgap.experiments.finbench_rdf import FAMILIES, materialize_finbench_rdf, fixed_semantics_query, _pin
from xgap.experiments.external_federation import deadline, query_once
from xgap.experiments.m15_native_services import LoopbackPortReservations
from xgap.experiments.one_shot_records import write_once
from run_external_federation_tiny import Processes, ready


def normalize(rows):
    """Keep ordering and duplicates; normalize only declared numeric columns."""
    return [{key:(format(Decimal(str(value)).quantize(Decimal('.001')),'f') if key=='total_amount'
        else int(value) if key=='account_distance' else value) for key,value in row.items()} for row in rows]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root',required=True,type=Path)
    parser.add_argument('--java',default='/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home/bin/java')
    parser.add_argument('--fuseki-root',type=Path,default=Path('/Users/anthonyche/xgap-data/d202-local-native-20260910-diagnostic2/runtime/apache-jena-fuseki-5.6.0'))
    args=parser.parse_args();root=args.output_root.resolve();root.mkdir(parents=True,exist_ok=False)
    receipt={'schema_version':'xgap-finbench-rdf-tiny-native-v1','success':False,'model_calls':0,'baseline_calls':0,
        'paper_result':False,'federated_execution':False,'query_limit':3,'runs':[]}
    processes=Processes(root);ports=LoopbackPortReservations.acquire(1)
    try:
        with deadline(90):
            started=time.perf_counter();partition=tiny_partition(root/'fixture')
            materialization=materialize_finbench_rdf(partition,root/'rdf')
            receipt['offline_prepare_ms']=(time.perf_counter()-started)*1000
            receipt['facts']={k:materialization[k] for k in ['entity_count','relationship_count','source_partition_sha256']}
            combined=root/'combined.ttl';combined.write_bytes((root/'rdf/graph.ttl').read_bytes()+(root/'rdf/control.ttl').read_bytes())
            cases=[{'id':family,'parameters':p,'query':fixed_semantics_query(family,p)} for family,p in zip(FAMILIES,parameters())]
            write_once(root/'cases.json',cases)
            write_once(root/'input_seal.json',{'files':[_pin(p) for p in [combined,root/'rdf/manifest.json',REPO/'src/xgap/experiments/finbench_rdf.py',Path(__file__),REPO/'tests/test_finbench_rdf.py']], 'maximum_query_attempts':3,'no_retries':True})
            base=root/'fuseki';base.mkdir();port=ports.ports[0];ports.release(0)
            started=time.perf_counter()
            process=processes.start('source',[str(args.fuseki_root/'fuseki-server'),'--localhost','--port',str(port),'--file',str(combined),'/ds'],
                env={'JAVA':args.java,'FUSEKI_HOME':str(args.fuseki_root),'FUSEKI_BASE':str(base),'JVM_ARGS':'-Xms128m -Xmx512m'},cwd=args.fuseki_root)
            ready(process,port);receipt['offline_startup_load_ms']=(time.perf_counter()-started)*1000
            for i,case in enumerate(cases):
                raw=query_once(f'http://127.0.0.1:{port}/ds/sparql',case['query'],seconds=8,output=root/(case['id']+'-raw.json'))
                result={'id':case['id'],'http_status':raw.get('http_status'),'client_wall_ms':raw['client_wall_ms'],'answer_exact':False}
                if raw['status']=='returned' and raw['http_status']==200:
                    rows=json.loads(raw['body_utf8'])['results']['bindings']
                    if any(t['type'] not in ('literal','typed-literal') for r in rows for t in r.values()):
                        raise ValueError('Unexpected RDF result term')
                    actual=normalize([{k:t['value'] for k,t in r.items()} for r in rows])
                    # Read independent gold only after raw response was sealed.
                    expected=normalize(expected_rows()[i])
                    result.update(answer_exact=actual==expected,actual=actual,expected=expected)
                write_once(root/(case['id']+'-evaluation.json'),result);receipt['runs'].append(result)
                if raw['status']!='returned' or raw['http_status']!=200:break
            receipt['success']=len(receipt['runs'])==3 and all(r['answer_exact'] for r in receipt['runs'])
    except Exception as error:
        receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        receipt['owned_processes']=processes.close();ports.close()
        receipt['owned_processes_terminal']=all(p['returncode'] is not None for p in receipt['owned_processes'])
        receipt['query_attempts']=len(receipt['runs'])
        receipt['success'] &= receipt['owned_processes_terminal']
        write_once(root/'receipt.json',receipt)
    print(json.dumps(receipt));return 0 if receipt['success'] else 1


if __name__=='__main__':
    raise SystemExit(main())
