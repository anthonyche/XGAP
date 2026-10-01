#!/usr/bin/env python3
"""One read-only Cypher expression fixture for necessary primitive screening.

This is a compiler component check, not a federated query or a dataset result.
The six inline rows do not write to the frozen graph stores.
"""
import argparse
import json
from pathlib import Path
import subprocess
import threading

from check_compact_roles_native import PREPARED, PREPARED_SHA
from native_store_session import NativeStoreSession
from prepare_rdf_tdb import REPO
from xgap.compilers.necessary_row_filters import add_necessary_row_filters
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.external_federation import deadline
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, native_clients
from xgap.experiments.one_shot_records import CapturingClient, write_once
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.row_operations import filter_rows


def main(output):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False);session=None
    receipt={'schema_version':'xgap-necessary-filter-cypher-component-v1','success':False,
        'paper_result':False,'model_calls':0,'fit_calls':0,'data_loads':0,'automatic_retries':0,
        'scope':'one read-only six-row primitive fixture; not a federated dataset result','closures':[]}
    conditions=[{'op':'eq','field':'s','value':'keep'},{'op':'eq','field':'b','value':True}]
    fixture=QueryArtifact('necessary-filter-inline-primitive-fixture','cypher',
        "UNWIND [{id:'a',s:'keep',b:true},{id:'b',s:'drop',b:true},"
        "{id:'c',s:'keep',b:false},{id:'d',s:1,b:1},"
        "{id:'e',s:date('2020-01-01'),b:true},{id:'f',s:null,b:null}] AS row\n"
        "RETURN row.id AS entity, row.s AS s, row.b AS b",kind='compiled',
        parameters={'compiler':'semantic_node_match_v1','output_columns':['entity','s','b'],
            'component_fixture':True,'production_match_query':False})
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):raise ValueError('Commit first')
        receipt['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
        artifact=add_necessary_row_filters(fixture,conditions)
        receipt['intent']=write_once(root/'intent.json',{'artifact':artifact.to_dict(),
            'expected_native_entities':['a','d','e','f'],'expected_final_rows':[{'entity':'a','s':'keep','b':True}],
            'maximum_source_calls':1,'reuses_frozen_graphs_without_writes':True})
        session=NativeStoreSession(root=root/'session',prepared_path=PREPARED,prepared_sha256=PREPARED_SHA,
            discard_serving_copies=True,budget=SourceObservationBudget(max_calls=1,request_bytes=65536,
                phase_request_bytes=65536,response_bytes=65536,phase_response_bytes=65536,timeout_seconds=20))
        with deadline(120):session.start()
        specs=FrozenOneShotProfile.load(session.profile['path'],expected_sha256=session.profile['sha256']).materialize()[5]
        records=[];clients=native_clients(specs)
        client=CapturingClient(clients['neo4j'],root,records,threading.Lock(),retain_payloads=False)
        session.observer.set_phase('primitive-types')
        with deadline(30):result=client.execute(artifact)
        result_pin=write_once(root/'result.json',result.to_dict());observed=session.observer.seal_phase('primitive-types')
        outcome=write_once(root/'outcome.json',{'result':result_pin,'source_observations':observed,'ledger':records})
        session.observer.release_phase('primitive-types',outcome)
        kept=sorted(r['entity'] for r in result.rows)
        final=list(filter_rows(result.rows,{'op':'and','args':conditions})) if result.success else []
        receipt.update(result=result_pin,outcome=outcome,source_calls=observed['requests'],native_entities=kept,final_rows=final,
            success=result.success and kept==['a','d','e','f'] and final==[{'entity':'a','s':'keep','b':True}] and observed['requests']==1)
    except Exception as error:receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        if session:receipt['closures'].append(session.close())
        receipt['success'] &= all(all(c[k] for k in ('owned_groups_drained','owned_processes_terminal','observer_stopped')) for c in receipt['closures'])
        pin=write_once(root/'receipt.json',receipt)
    print(json.dumps({'success':receipt['success'],'receipt':pin,'source_calls':receipt.get('source_calls'),'error':receipt.get('error')}),flush=True)
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    with deadline(240):raise SystemExit(main(**vars(parser.parse_args())))
