#!/usr/bin/env python3
"""Publish an independent bounded cohort; do not execute any evaluated method."""
import argparse
import json
from xgap.experiments.ch6_heldout import publish

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('index-receipt','profile-path','profile-sha256','output'):p.add_argument('--'+n,required=True)
    p.add_argument('--split',required=True,choices=['development','pilot','test'])
    p.add_argument('--anchors-per-template',required=True,type=int)
    p.add_argument('--seed',type=int,default=20260923)
    p.add_argument('--deployment-selection',choices=['balanced','all'],default='balanced')
    result=publish(**vars(p.parse_args()));print(json.dumps(result));raise SystemExit(0 if result['success'] else 2)
