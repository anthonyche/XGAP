#!/usr/bin/env python3
"""Generate the D4 SQLite source index only; no model or database service calls."""
import argparse
import json
from xgap.experiments.ch6_synthetic import generate

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    p.add_argument('--nodes', type=int, default=4096)
    p.add_argument('--degree', type=int, default=8)
    p.add_argument('--seed', type=int, default=20260926)
    print(json.dumps(generate(**vars(p.parse_args()))))
