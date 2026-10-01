#!/usr/bin/env python3
"""Freeze 48 outcome-independent authored cases; no model or source calls."""
import argparse
import json

from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.ch6_small_sample import prepare

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-path', required=True)
    parser.add_argument('--input-sha256', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(load_pin(dict(path=args.input_path, sha256=args.input_sha256)), args.output)))
