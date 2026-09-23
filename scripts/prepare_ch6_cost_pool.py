#!/usr/bin/env python3
import argparse
import json
from xgap.experiments.ch6_cost_pool import load,prepare
from xgap.experiments.ch6_fact_index import pin

if __name__=='__main__':
    p=argparse.ArgumentParser(description='Freeze complete-Q offline cost pool and schedule; no plan execution.')
    for n in ('query-path','query-sha256','profile-path','profile-sha256','reference-path','reference-sha256','output'):p.add_argument('--'+n,required=True)
    p.add_argument('--max-plans',type=int,default=4);p.add_argument('--repetitions',type=int,default=3)
    a=vars(p.parse_args());q=load(dict(path=a.pop('query_path'),sha256=a.pop('query_sha256')))
    reference=dict(path=a.pop('reference_path'),sha256=a.pop('reference_sha256'));load(reference)
    print(json.dumps(prepare(query=q,reference=reference,**a)))
