#!/usr/bin/env python3
"""Prepare canonical 32-bank financial scale data; default is a no-write dry run."""
import argparse
import json

from xgap.experiments.ch6_financial_scale import generate, GIB, NODES_PER_BANK, SEED


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='New directory; never overwritten')
    parser.add_argument('--execute', action='store_true', help='Explicitly generate source CSV chunks')
    parser.add_argument('--nodes-per-bank', type=int, default=NODES_PER_BANK)
    parser.add_argument('--seed', type=int, default=SEED)
    parser.add_argument('--chunk-rows', type=int, default=100000)
    parser.add_argument('--max-output-bytes', type=int, default=64*GIB)
    parser.add_argument('--reserve-bytes', type=int, default=6*GIB)
    result = generate(**vars(parser.parse_args(argv)))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
