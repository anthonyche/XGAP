#!/usr/bin/env python3
"""Refresh frozen controlled factor manifests with v3 actual-family probes, offline.

Reads publication/configuration metadata only. Original controlled inputs,
source/admission pins, budgets, cells and parameter points remain unchanged.
The output is preparation, never method evidence or permission to dispatch.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

from xgap.agent.live_probe import policy_from_dict
from xgap.experiments.ch6_formal_protocol import METHODS, pin_file
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.unified_contract import load_configuration, validate_method

COHORTS = ('D1-N-u-final', 'D1-sources-base-two-final', 'D1-sources-sources-four-final',
    'D1-sources-sources-eight-final', 'D1-graph_scale-scale-quarter-final',
    'D1-graph_scale-base-two-final', 'D1-graph_scale-scale-four-final')


def refresh_config(raw, policy, method, price=1):
    if raw['provider'] != 'frozen_compact_model':
        raise ValueError('Controlled factors require the original frozen_compact_model provider')
    out = deepcopy(raw); settings = out['settings']
    if settings['information_targets'] or settings['candidate_weights'] is not None or settings.get('live_probe_policy'):
        raise ValueError('Do not replace an existing registry/prior/policy silently')
    settings['limits']['aggregation'] = 'expectation'
    settings['live_probe_policy'] = asdict(policy)
    settings['live_probe_policy']['action_cost'] *= price
    out['schema_version'] = 'xgap-unified-run-config-v3'
    if settings['information_mode'] != ('no_probe' if method == METHODS['NP'] else 'all'):
        raise ValueError('Method/probe policy mismatch')
    return out


def prepare(publication_root, policy_path, policy_sha256, output,
            original_publication_root=None, artifact_target_root=None):
    publication = Path(publication_root).resolve(); root = Path(output).resolve()
    policy = policy_from_dict(json.loads(read_pinned(policy_path, policy_sha256)))
    if policy is None: raise ValueError('An explicit live policy is required')
    original = Path(original_publication_root) if original_publication_root else None
    target = Path(artifact_target_root) if artifact_target_root else root
    def load(pin):
        p = Path(pin['path'])
        if original is not None and p.is_relative_to(original): p = publication / p.relative_to(original)
        return json.loads(read_pinned(p, pin['sha256']))
    def parent_pin(path):
        pin = pin_file(path)
        if original is not None:
            pin['path'] = str(original / Path(path).relative_to(publication))
        return pin
    root.mkdir(parents=True, exist_ok=False)
    def write(relative, obj):
        p = root / relative; p.parent.mkdir(parents=True, exist_ok=True)
        pin = write_once(p, obj); pin['path'] = str(target / relative)
        return pin
    frozen_policy = write('live-probe-policy.json', asdict(policy))
    units = []; ts_references = []; source_specs = []
    for name in COHORTS:
        source_spec = parent_pin(publication / name / 'spec.json'); spec = load(source_spec)
        if spec['input_track'] != 'controlled' or spec.get('method_results_read') != 0:
            raise ValueError('Only pre-result controlled factor publications can be refreshed')
        receipt_pin = parent_pin(publication / name / 'units/receipt.json'); receipt = load(receipt_pin)
        old_unit = next(u for u in receipt['units'] if u['repetition'] == 0)
        parent = old_unit['manifest']; old = load(parent); new = deepcopy(old); cache = {}
        expected = {(cid, METHODS[m]) for cid in spec['case_ids'] for m in ('XGAP','NP','SH','GR')}
        if (len(old['cells']) != len(expected)
                or {(old_unit['cell_cases'][c['cell_id']], c['method']) for c in old['cells']} != expected):
            raise ValueError('Frozen factor membership is incomplete or differs from its source spec')
        for cell in new['cells']:
            if 'controlled_state' not in cell: raise ValueError('Controlled state is mandatory')
            key = cell['config']['sha256']
            if key not in cache:
                config = refresh_config(load(cell['config']), policy, cell['method'], spec['parameters']['probe_price'])
                local = root / name / f'config-{len(cache):03d}.json'
                cache[key] = write(str(local.relative_to(root)), config)
                _, _, settings, _ = load_configuration(local, cache[key]['sha256'])
                validate_method(cell['method'], settings)
            cell['config'] = cache[key]
        # All runtime inputs and fixed hyperparameters survive byte-for-byte;
        # only config pins change. Old manifest and query/private inputs untouched.
        for before, after in zip(old['cells'], new['cells']):
            assert {k:v for k,v in before.items() if k != 'config'} == {k:v for k,v in after.items() if k != 'config'}
        manifest = write(name + '/manifest.json', new)
        unit = {**old_unit, 'unit_id': name + '-live-r0', 'manifest': manifest,
            'parent_manifest': parent, 'source_spec': source_spec, 'source_receipt': receipt_pin}
        units.append(unit); source_specs.append(source_spec)
        ts_name = 'D1-rdf-final' if name == 'D1-N-u-final' else name.removesuffix('-final') + '-TS-nl-reference'
        ts_receipt_pin = parent_pin(publication / ts_name / 'units/receipt.json')
        ts_unit = next(u for u in load(ts_receipt_pin)['units'] if u['repetition'] == 0)
        ts_manifest = load(ts_unit['manifest'])
        ts_cells = [c['cell_id'] for c in ts_manifest['cells'] if c['method'] == METHODS['TS']
                    and (name != 'D1-N-u-final' or ts_unit['cell_cases'][c['cell_id']].endswith('-W3'))]
        if not ts_cells: raise ValueError('The fifth-method NL reference cannot be omitted')
        ts_references.append(dict(cohort=name, method='TS', manifest=ts_unit['manifest'], cells=ts_cells,
            status='fixed_nl_reference', source_receipt=ts_receipt_pin,
            reason='Original TS NL on the actual source/scale snapshot; N/u uses frozen D1 RDF W3 reference.'))
    doc = dict(schema_version='xgap-ch6-live-factor-refresh-v1', units=units, source_specs=source_specs,
        ts_references=ts_references, live_probe_policy=frozen_policy, methods=list(METHODS),
        repetitions=1, input_track='controlled', provider='frozen_compact_model',
        aggregation='expectation', target_binding='runtime actual public family and compiler seed fragments',
        probe_execution_not_forced=True, actual_probe_counts_pending=True,
        model_calls=0, backend_calls=0, submitted_jobs=0, method_measurements_created=0,
        formal_campaign_ready=False, launch_ready=False,
        remaining=['Server-side validation of inherited source/input pins and cumulative launch budgets',
            'Depth/horizon/epsilon/clarification axes retain reusable inputs but need the same v3 refresh',
            'E7 probe-price axis needs new live-policy price bindings; old recipes collapse price to 1',
            '21-figure binding audit must recognize live_probe_policy before publishing refreshed curves'])
    pin = write('factor-refresh.json', doc)
    return dict(receipt=pin, local_receipt=str(root/'factor-refresh.json'), units=len(units),
        controlled_method_requests=sum(len(load_manifest['cells']) for load_manifest in
            (json.loads((root / name / 'manifest.json').read_text()) for name in COHORTS)),
        ts_reference_cells=sum(len(x['cells']) for x in ts_references),
        model_calls=0, backend_calls=0, submitted_jobs=0, launch_ready=False)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('publication-root','policy-path','policy-sha256','output'): p.add_argument('--'+k, required=True)
    p.add_argument('--original-publication-root'); p.add_argument('--artifact-target-root')
    print(json.dumps(prepare(**vars(p.parse_args()))))
