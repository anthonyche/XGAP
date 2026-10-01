#!/usr/bin/env python3
"""Create or execute a pinned D4 CPU preprocessing recipe; default is zero execution."""
import argparse
import json
from xgap.experiments.ch6_d4_recipe import prepare, execute

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    make=sub.add_parser('prepare')
    for name in ('output','source-commit','remote-output'):make.add_argument('--'+name,required=True)
    run=sub.add_parser('run')
    for name in ('recipe-path','recipe-sha256'):run.add_argument('--'+name,required=True)
    run.add_argument('--execute',action='store_true')
    args=vars(p.parse_args());mode=args.pop('command')
    if mode=='prepare':result=prepare(**args)
    else:args['run']=args.pop('execute');result=execute(**args)
    print(json.dumps(result))
    raise SystemExit(0 if result.get('success',True) else 2)
