#!/usr/bin/env python3
"""Freeze selected small-study plans offline; no engines, model calls or jobs."""
import argparse
import json
from xgap.experiments.ch6_parallel_freeze import freeze

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--release', required=True)
    p.add_argument('--release-sha256', required=True)
    p.add_argument('--evidence-root', required=True)
    p.add_argument('--original-prefix')
    p.add_argument('--artifact-root', help='Mirror root for original-prefix pins; defaults to evidence-root')
    p.add_argument('--output', required=True)
    a = p.parse_args()
    print(json.dumps(freeze(release_pin=dict(path=a.release, sha256=a.release_sha256),
        evidence_root=a.evidence_root, original_prefix=a.original_prefix,
        artifact_root=a.artifact_root, output=a.output)))
