#!/usr/bin/env python3
"""Offline streaming same-facts materialization. Does not launch experiments."""
import argparse
import json
from xgap.experiments.ch6_materialize import materialize

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--index-receipt',required=True);p.add_argument('--output',required=True)
    p.add_argument('--scale',choices=['.25','1','4'],default='1')
    p.add_argument('--source-count',type=int,choices=[2,4,8],default=2)
    result=materialize(**vars(p.parse_args()))
    print(json.dumps({k:v for k,v in result.items() if k in ('success','counts','error','offline_seconds','logical_facts_sha256')}))
    raise SystemExit(0 if result['success'] else 1)
