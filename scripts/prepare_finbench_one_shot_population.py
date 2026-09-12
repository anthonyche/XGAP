#!/usr/bin/env python3
"""One bounded offline evaluation-population preparation, no method execution."""
import argparse
import json

from xgap.experiments.external_federation import deadline
from xgap.experiments.finbench_one_shot_population import build_population

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',required=True)
    parser.add_argument('--lock-path',default='experiments/artifacts/m15_finbench_v010_sf0_1_sources.json')
    parser.add_argument('--excluded-public',required=True)
    parser.add_argument('--output-root',required=True)
    args=parser.parse_args()
    with deadline(120):
        pin=build_population(archive=args.archive,lock_path=args.lock_path,excluded_public=args.excluded_public,output=args.output_root)
    print(json.dumps(pin))
