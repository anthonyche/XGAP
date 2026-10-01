#!/usr/bin/env python3
"""Check all pins/budgets/splits before releasing a full campaign; no queries."""
import argparse
import json
from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.ch6_release_audit import audit_release
from xgap.experiments.one_shot_records import write_once

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('release-path','release-sha256','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();pin=dict(path=a.release_path,sha256=a.release_sha256)
    result=audit_release(load_pin(pin));result['release']=pin
    write_once(a.output,result);print(json.dumps(dict(success=result['success'],failed=result['failed_checks'])))
    raise SystemExit(0 if result['success'] else 1)
