#!/usr/bin/env python3
"""Freeze a separate small controlled probe scenario; perform no remote calls."""
import argparse
import json

from xgap.experiments.ch6_probe_pilot import publish


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('input-path', 'input-sha256', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    print(json.dumps(publish(dict(path=args.input_path, sha256=args.input_sha256), args.output)))
