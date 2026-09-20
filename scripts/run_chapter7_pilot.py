#!/usr/bin/env python3
"""Run a bounded pilot invocation; optional credential stays in process memory."""
import argparse
import getpass
import json
import os
from run_bounded_joint_batch import run

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('manifest-path','manifest-sha256','output'):p.add_argument('--'+name,required=True)
    p.add_argument('--max-new-cells',type=int,default=10000);p.add_argument('--read-key',action='store_true')
    args=vars(p.parse_args());read_key=args.pop('read_key');prior=os.environ.get('XGAP_EXTERNAL_LLM_API_KEY')
    try:
        if read_key:os.environ['XGAP_EXTERNAL_LLM_API_KEY']=getpass.getpass('Qwen credential (not recorded): ')
        result=run(**args);print(json.dumps(result))
    finally:
        if prior is None:os.environ.pop('XGAP_EXTERNAL_LLM_API_KEY',None)
        else:os.environ['XGAP_EXTERNAL_LLM_API_KEY']=prior
    raise SystemExit(1 if result['status']=='failed' else 0)
