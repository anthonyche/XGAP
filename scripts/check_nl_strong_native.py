#!/usr/bin/env python3
"""One live model request through conditional strong planning on eight-node stores."""
import argparse
from check_compact_roles_native import main
from xgap.experiments.external_federation import deadline

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True); p.add_argument('--read-key', action='store_true')
    p.add_argument('--case-id', choices=['ROLE-ID-01'])
    with deadline(600):
        raise SystemExit(main(**vars(p.parse_args()), contract='contribution', strong=True))
