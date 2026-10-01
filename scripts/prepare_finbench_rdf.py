#!/usr/bin/env python3
"""Explicit offline same-facts preparation; never invoked by online runtime."""
import argparse
import json
from xgap.experiments.finbench_rdf import materialize_finbench_rdf


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--partition-root",required=True)
    parser.add_argument("--output-root",required=True)
    args=parser.parse_args()
    print(json.dumps(materialize_finbench_rdf(args.partition_root,args.output_root),ensure_ascii=False))
