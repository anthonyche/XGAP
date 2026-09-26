#!/usr/bin/env python3
"""Freeze unchanged 48 cases with revised public roles and proved source contracts."""
import argparse,json
from xgap.experiments.ch6_small_migration import prepare

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('selection-path','selection-sha256','output'):p.add_argument('--'+n,required=True)
    p.add_argument('--pin-mirror',action='append',default=[])
    p.add_argument('--proof-mirror',action='append',default=[])
    a=vars(p.parse_args())
    a['selection_pin']=dict(path=a.pop('selection_path'),sha256=a.pop('selection_sha256'))
    a['pin_mirrors']=[v.split('=',1) for v in a.pop('pin_mirror')]
    a['proof_mirrors']=[v.split('=',1) for v in a.pop('proof_mirror')]
    print(json.dumps(prepare(**a)))
