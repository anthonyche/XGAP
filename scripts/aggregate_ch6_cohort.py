#!/usr/bin/env python3
"""Reduce pinned trial records without running or changing any method."""
import argparse
import json
from pathlib import Path
from xgap.experiments.ch6_formal_protocol import load_pin, pin_file
from xgap.experiments.ch6_aggregate import reduce_cohort
from xgap.experiments.one_shot_records import write_once


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-path', required=True)
    p.add_argument('--input-sha256', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    pin = dict(path=a.input_path, sha256=a.input_sha256)
    result = reduce_cohort(load_pin(pin))
    root = Path(a.output)
    root.mkdir(parents=True, exist_ok=False)
    result['input'] = pin
    write_once(root / 'summary.json', result)
    print(json.dumps(dict(summary=pin_file(root / 'summary.json'), fully_observed=result['fully_observed'],
                          model_calls=0, backend_calls=0)))


if __name__ == '__main__':
    main()
