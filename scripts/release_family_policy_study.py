#!/usr/bin/env python3
"""Publish the approved bounded study once, before any method observation."""
import argparse
import json
from pathlib import Path
import subprocess
from xgap.experiments.family_policy_study import release
from xgap.experiments.external_federation import deadline

REPO=Path(__file__).resolve().parents[1]
DATA=Path('/Users/anthonyche/xgap-data')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True)
    a=p.parse_args()
    if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):raise ValueError('Commit before study release')
    with deadline(300):
        pin=release(design_path=REPO/'experiments/protocols/family_policy_study_v1.json',
            archive=DATA/'int3-finbench-source-20260911/sf0.1.tar.gz',
            lock_path=REPO/'experiments/sources/m15_finbench_v010_sf0_1_sources.json',
            parent_release=DATA/'nl-strong-finbench-first-20260916-v1/release/release.json',output=a.output,
            excluded_selection=DATA/'finbench-one-shot-population-20260912-v1/selection.json',
            excluded_primary=DATA/'int3-finbench-20260911/finbench-primary-workload/public_instances.json')
    print(json.dumps(pin))
