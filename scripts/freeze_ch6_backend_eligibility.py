#!/usr/bin/env python3
"""Freeze complete diagnostic coverage without requiring every query to finish."""
import argparse
import json
from pathlib import Path
from xgap.experiments.ch6_backend_eligibility import assess
from xgap.experiments.one_shot_records import write_once

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('spec-path','spec-sha256','output'):p.add_argument('--'+name,required=True)
    a = p.parse_args()
    doc = assess(dict(path=a.spec_path,sha256=a.spec_sha256))
    print(json.dumps(write_once(Path(a.output),doc)))
