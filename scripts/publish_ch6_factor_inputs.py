#!/usr/bin/env python3
import argparse
import json
from xgap.experiments.ch6_factor_inputs import publish

if __name__=='__main__':
    p=argparse.ArgumentParser(description='Freeze real controlled N/u inputs; no evaluated method calls.')
    for n in ('index-receipt','profile-path','profile-sha256','output'):p.add_argument('--'+n,required=True)
    p.add_argument('--seed',type=int,default=20260923)
    result=publish(**vars(p.parse_args()));print(json.dumps(result));raise SystemExit(0 if result['success'] else 2)
