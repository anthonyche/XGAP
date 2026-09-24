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
    p.add_argument('--audit-path');p.add_argument('--audit-sha256')
    a=p.parse_args()
    pool_pin=dict(path=a.pool_path,sha256=a.pool_sha256);costs_pin=dict(path=a.costs_path,sha256=a.costs_sha256)
    result=study(load(pool_pin),load(costs_pin));result.update(pool=pool_pin,measurements=costs_pin)
    if bool(a.audit_path)!=bool(a.audit_sha256):raise ValueError('Audit path and digest required together')
    if a.audit_path:
        audit_pin=dict(path=a.audit_path,sha256=a.audit_sha256);audit=load(audit_pin)
        if (audit.get('schema_version')!='xgap-ch6-cost-measurement-audit-v1' or audit.get('success') is not True
                or audit['pool']['sha256']!=pool_pin['sha256'] or audit['frozen_costs']['sha256']!=costs_pin['sha256']):
            raise ValueError('Cost audit does not cover these measurements')
        result['cost_audit']=audit_pin
    write(a.output,result);print(json.dumps(dict(success=result['success'],rows=len(result['rows']),model_calls=0,backend_calls=0)))
