#!/usr/bin/env python3
"""Audit F6 selections using frozen same-Q measurements; no external calls."""
import argparse
import json
from xgap.experiments.ch6_cost_pool import load
from xgap.experiments.ch6_cost_selection import study
from xgap.experiments.ch6_fact_index import write

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('pool-path','pool-sha256','costs-path','costs-sha256','output'):
        p.add_argument('--'+n,required=True)
    a=p.parse_args()
    pool_pin=dict(path=a.pool_path,sha256=a.pool_sha256);costs_pin=dict(path=a.costs_path,sha256=a.costs_sha256)
    result=study(load(pool_pin),load(costs_pin));result.update(pool=pool_pin,measurements=costs_pin)
    write(a.output,result);print(json.dumps(dict(success=result['success'],rows=len(result['rows']),model_calls=0,backend_calls=0)))
