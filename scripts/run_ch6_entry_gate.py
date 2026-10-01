#!/usr/bin/env python3
"""Explicitly run the frozen eight-call entry gate; never start database services."""
import argparse
import getpass
import json
import os
from xgap.experiments.ch6_entry_gate import run, preflight

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('manifest-path','manifest-sha256','output'):p.add_argument('--'+key,required=True)
    args=vars(p.parse_args());preflight(args['manifest_path'],args['manifest_sha256'])
    credential=getpass.getpass('Fresh LLM API key (hidden; eight calls maximum): ').strip()
    if not credential:raise SystemExit('No credential supplied; no model calls made.')
    os.environ['XGAP_EXTERNAL_LLM_API_KEY']=credential
    try:
        result=run(**args)
        print(json.dumps({k:result[k] for k in ('attempted','counts','completed_all','usage','backend_calls','method_results_created')}))
    finally:
        os.environ.pop('XGAP_EXTERNAL_LLM_API_KEY',None)
