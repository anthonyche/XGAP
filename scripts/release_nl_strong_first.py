#!/usr/bin/env python3
"""Freeze the first twelve NL-only SF0.1 cases, without calling any service."""
import argparse
import json
import subprocess
from pathlib import Path
from xgap.experiments.nl_strong_release import release

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent', required=True); p.add_argument('--parent-sha256', required=True)
    p.add_argument('--output', required=True); a = p.parse_args()
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=Path(__file__).resolve().parents[1], text=True):
        raise ValueError('Commit before freezing the first pass')
    print(json.dumps(release({'path': a.parent, 'sha256': a.parent_sha256}, a.output)))
