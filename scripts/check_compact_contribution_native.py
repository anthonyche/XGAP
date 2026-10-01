#!/usr/bin/env python3
"""One contribution-v2 NL request on the existing frozen eight-node tiny stores."""
import argparse
from check_compact_roles_native import main
from xgap.experiments.external_federation import deadline

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--read-key',action='store_true')
    with deadline(600):raise SystemExit(main(**vars(parser.parse_args()),contract='contribution'))
