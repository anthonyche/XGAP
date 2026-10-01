#!/usr/bin/env python3
"""Extract actual small-study means/counts/resource totals; never simulate or scale."""
import argparse
import json
from xgap.experiments.ch6_small_summary import summarize


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence-root', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--release-path')
    p.add_argument('--release-sha256')
    p.add_argument('--original-prefix', help='Read-only original-to-extracted archive prefix mapping')
    a = vars(p.parse_args())
    path, digest = a.pop('release_path'), a.pop('release_sha256')
    if bool(path) != bool(digest): p.error('Release path and SHA-256 must be supplied together')
    if path: a['release_pin'] = dict(path=path, sha256=digest)
    print(json.dumps(summarize(**a)))
