#!/usr/bin/env python3
"""Offline full-core disk index, no LLM or graph queries."""
import argparse
import json
from xgap.experiments.ch6_fact_index import build

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',required=True,choices=['D1','D2','D3'])
    p.add_argument('--source',required=True);p.add_argument('--output',required=True)
    result=build(**vars(p.parse_args()))
    print(json.dumps({k:v for k,v in result.items() if k not in ('provenance','core')}))
    raise SystemExit(0 if result['success'] else 1)
