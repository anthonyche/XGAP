#!/usr/bin/env python3
import argparse
import json
from xgap.experiments.fixed_semantic_worker import run_fixed

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('request-path','request-sha256','method','output'):
        parser.add_argument('--'+name,required=True)
    for name in ('profile-path','profile-sha256','endpoint'):
        parser.add_argument('--'+name)
    parser.add_argument('--seconds',type=float,default=120)
    result=run_fixed(**vars(parser.parse_args()))
    print(json.dumps({'success':result['success'],'status':result['status']}))
    # A recorded method failure is still a normal worker terminal outcome.
