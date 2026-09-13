#!/usr/bin/env python3
import argparse
import json
from xgap.experiments.nl_method_worker import run_nl

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('request-path','request-sha256','profile-path','profile-sha256','method','output'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--endpoint');parser.add_argument('--seconds',type=float,default=180)
    result=run_nl(**vars(parser.parse_args()))
    print(json.dumps({'success':result['success'],'status':result['status']}))
