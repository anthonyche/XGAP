#!/usr/bin/env python3
"""Bind a frozen cohort to offline endpoint-degree estimates without resampling.

Only the estimator, profile label and added endpoint-degree provenance may change.
All case bytes/pins and semantic/source declarations must remain identical.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from xgap.experiments.ch6_cost_pool import load
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once


def validate_revision(old, new):
    left, right = deepcopy(old), deepcopy(new)
    for key in ('estimator', 'profile_id'):
        left.pop(key, None)
        right.pop(key, None)
    revision = right.get('offline', {}).pop('endpoint_degree_revision', None)
    if not revision or 'endpoint_degree_revision' in left.get('offline', {}) or left != right:
        raise ValueError('Only a new offline endpoint-degree estimator revision is allowed')
    return revision


def rebind(bundle_pin, prepared_pin, output):
    bundle, prepared = load(bundle_pin), load(prepared_pin)
    if bundle.get('schema_version') != 'xgap-ch6-heldout-cases-v1' or not prepared.get('success'):
        raise ValueError('Frozen held-out cohort and successful prepared stores required')
    old, new = load(bundle['profile']), load(prepared['profile'])
    revision = validate_revision(old, new)
    seal = load(prepared['input_seal'])
    if seal['profile'] != prepared['profile']:
        raise ValueError('Prepared profile differs from engine input seal')
    # Verify every linked input before publishing; values never select or edit cases.
    for case in bundle['cases']:
        for key in ('request', 'reference', 'oracle', 'controlled_state'):
            ref = case[key]
            read_pinned(ref['path'], ref['sha256'])
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    rebound = deepcopy(bundle)
    rebound['profile'] = prepared['profile']
    result = write_once(root/'bundle.json', rebound)
    write_once(root/'receipt.json', dict(schema_version='xgap-ch6-profile-rebinding-v1',
        success=True, original_bundle=bundle_pin, prepared=prepared_pin, bundle=result,
        old_profile=bundle['profile'], profile=prepared['profile'], endpoint_degree_revision=revision,
        cases=len(bundle['cases']), cases_unchanged=True, model_calls=0, backend_calls=0,
        method_results_read=0, selection='No resampling; all input and reference pins retained'))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('bundle-path', 'bundle-sha256', 'prepared-path', 'prepared-sha256', 'output'):
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    print(json.dumps(rebind(dict(path=args.bundle_path, sha256=args.bundle_sha256),
        dict(path=args.prepared_path, sha256=args.prepared_sha256), args.output)))
