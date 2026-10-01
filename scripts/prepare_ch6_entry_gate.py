#!/usr/bin/env python3
"""Freeze an eight-structure shared-entry acceptance gate, with zero external calls."""
import argparse
import json
from xgap.experiments.ch6_entry_gate import prepare

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('release-path','release-sha256','output'):p.add_argument('--'+key,required=True)
    p.add_argument('--pin-mirror',action='append',default=[])
    p.add_argument('--proof-mirror',action='append',default=[])
    args=vars(p.parse_args());args['pin_mirrors']=[v.split('=',1) for v in args.pop('pin_mirror')]
    args['proof_mirrors']=[v.split('=',1) for v in args.pop('proof_mirror')]
    print(json.dumps(prepare(**args)))
