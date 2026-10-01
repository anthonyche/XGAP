#!/usr/bin/env python3
"""Publish a new live E7 price sweep; no models, services, or job submission."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from xgap.agent.live_probe import policy_from_dict
from xgap.experiments.ch6_figure_recipes import build_live_e7, live_e7_configuration
from xgap.experiments.ch6_figure_bindings import audit_bindings
from xgap.experiments.ch6_formal_protocol import load_pin, METHODS
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.unified_contract import load_configuration, validate_method
from xgap.experiments.batch_cell_identity import validate_cell_id


def prepare(spec_path, spec_sha256, output, *, original_root=None, mirror_root=None):
    spec_pin = dict(path=spec_path, sha256=spec_sha256); spec = load_pin(spec_pin)
    if bool(original_root) != bool(mirror_root): raise ValueError('Both mirror roots required')
    def read(pin):
        p = Path(pin['path'])
        if original_root and p.is_relative_to(Path(original_root)):
            p = Path(mirror_root) / p.relative_to(Path(original_root))
        return json.loads(read_pinned(p, pin['sha256']))
    recipes = build_live_e7(spec, load=read)
    policy = policy_from_dict(read(spec['live_probe_policy']))
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=False)
    units = []; configs = {}
    for group in recipes['unit_requests']:
        parent = read(group['parent']); original = read(parent['manifest']); manifest = deepcopy(original)
        folder = root / group['unit_id']; folder.mkdir()
        manifest['cells'] = []
        for cell in original['cells']:
            label = next(k for k,v in METHODS.items() if v == cell['method'])
            if label not in group['methods'] or parent['cell_cases'][cell['cell_id']] not in recipes['case_ids']: continue
            new = deepcopy(cell); cid = validate_cell_id(cell['cell_id'])
            if label != 'TS':
                raw = live_e7_configuration(read(cell['config']), policy, label, group['price'])
                pin = write_once(folder / (cid+'-config.json'), raw)
                _,_,settings,_ = load_configuration(pin['path'],pin['sha256'])
                validate_method(cell['method'], settings)
                new['config'] = pin; configs[(group['unit_id'],cid)] = pin
            manifest['cells'].append(new)
        unit = dict(unit_id=group['unit_id'], manifest=write_once(folder/'manifest.json',manifest),
            parent_manifest=parent['manifest'], cell_cases={c['cell_id']:parent['cell_cases'][c['cell_id']] for c in manifest['cells']})
        units.append(unit)
    bindings = []
    for recipe in recipes['recipes']:
        row = deepcopy(recipe); row['cells'] = row.pop('future_cells')
        if row['status'] == 'planned': row['status'] = 'scheduled'
        if row['method'] != 'TS':
            row['cost_references'] = [dict(**ref,
                configuration=configs[('E7-live-price-1',ref['cell_id'])],
                base_cell=dict(unit_id='E7-live-price-1',cell_id=ref['cell_id'])) for ref in row['cells']]
        bindings.append(row)
    publication = dict(schema_version='xgap-ch6-live-e7-publication-v1',input=spec_pin,
        units=units, figure_bindings=bindings, recipes=write_once(root/'recipes.json',recipes),
        figure_scope=['E7'], model_calls=0, backend_calls=0, submitted_jobs=0,
        method_measurements_created=0, formal_campaign_ready=False, launch_ready=False,
        remaining=recipes['remaining'])
    checks = audit_bindings(publication, figures=('E7',))
    publication['audit'] = write_once(root/'binding-audit.json',dict(success=all(c['passed'] for c in checks),checks=checks))
    if not all(c['passed'] for c in checks):
        raise ValueError('Live E7 binding failure: '+str([c for c in checks if not c['passed']][:5]))
    return write_once(root/'publication.json',publication)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('spec-path','spec-sha256','output'): p.add_argument('--'+name,required=True)
    p.add_argument('--original-root');p.add_argument('--mirror-root')
    print(json.dumps(prepare(**vars(p.parse_args()))))
