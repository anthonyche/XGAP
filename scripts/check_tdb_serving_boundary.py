#!/usr/bin/env python3
"""One new TDB2/HTTP boundary on the already accepted 211+36-triple fixture."""
import argparse
import json
from pathlib import Path
import subprocess

from prepare_rdf_tdb import stream_pin
from rdf_tdb_session import RdfTdbSession
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.external_federation import query_once
from xgap.experiments.one_shot_records import write_once

REPO=Path(__file__).resolve().parents[1]
PREP=Path('/Users/anthonyche/xgap-data/rdf-tdb-tiny-20260913-v1/receipt.json')
PREP_SHA='cf4190cb71ec7ad635c34ab9a852b3f6bfe14d649b2048c9f897905564e2577d'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--prepared-input-sha256',required=True);args=p.parse_args()
    root=args.output.resolve();root.mkdir(parents=True,exist_ok=False)
    if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):raise ValueError('Commit before native boundary')
    receipt={'success':False,'model_calls':0,'baseline_queries':0,'source_queries':0,'automatic_retries':0,
        'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        'scope':'new disk storage to read-only HTTP only; no repeated interpretation/planning gate','paper_result':False}
    session=RdfTdbSession(root=root/'session',prepared_path=PREP,prepared_sha256=PREP_SHA,
        budget=SourceObservationBudget(),prepared_input_sha256=args.prepared_input_sha256)
    try:
        session.start();observer=session.observer;receipt['counts']={}
        for name,expected in (('graph',211),('control',36)):
            observer.set_phase(name+':storage-read')
            query='SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }'
            result=query_once(observer.base_url+'/'+name+'/sparql',query,output=root/(name+'-query.json'),seconds=10)
            receipt['source_queries']+=1
            if result['status']!='returned' or result.get('http_status')!=200:raise ValueError('TDB2 HTTP query failed')
            answer=json.loads(result['body_utf8'])
            count=int(answer['results']['bindings'][0]['n']['value'])
            receipt['counts'][name]=count
            if count!=expected:raise ValueError('Independent triple count mismatch')
            phase=observer.seal_phase(observer.phase)
            outcome=write_once(root/(name+'-outcome.json'),{'source_observations':phase,'count':count})
            observer.release_phase(observer.phase,outcome)
        receipt['success']=True;receipt['ready']=session.ready_pin
    except Exception as error:receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        receipt['closure']=session.close()
        receipt['success'] &= receipt['closure']['owned_processes_terminal'] and receipt['closure']['observer_stopped']
        pin=write_once(root/'receipt.json',receipt)
    print(json.dumps({'receipt':pin,**receipt}));return 0 if receipt['success'] else 1


if __name__=='__main__':raise SystemExit(main())
