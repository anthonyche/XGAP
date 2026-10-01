#!/usr/bin/env python3
"""Convert frozen financial canonical data to 16 Neo4j and 16 RDF load files."""
import argparse
import json

from xgap.experiments.ch6_financial_materialize import materialize
from xgap.experiments.ch6_financial_scale import GIB


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--canonical-root', required=True)
    parser.add_argument('--canonical-manifest-sha256')
    parser.add_argument('--output', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--max-output-bytes', type=int, default=64*GIB)
    parser.add_argument('--reserve-bytes', type=int, default=6*GIB)
    args = vars(parser.parse_args(argv))
    result = materialize(**args, progress=lambda event: print(json.dumps(event), flush=True))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
