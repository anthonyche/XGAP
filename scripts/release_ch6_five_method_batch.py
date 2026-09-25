#!/usr/bin/env python3
"""Build an immutable same-case five-method batch from already pinned inputs.

No gold is used to choose cases/configurations. This publisher does not turn a
development case bundle into a held-out evaluation. Each factor level needs its
own independently admitted public inputs; it cannot be simulated by duplicating
a candidate or merely changing a figure label.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import random

from run_bounded_joint_batch import FORMAL_SCHEMA,validate,source_commit
from xgap.experiments.ch6_formal_protocol import load_pin,METHODS
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.unified_contract import load_configuration,validate_method
from xgap.experiments.batch_cell_identity import validate_cell_id


def configuration_for(base,method):
    doc=deepcopy(base);settings=doc['settings']
    settings.update(decision_order='joint',information_mode='no_probe' if method=='NP' else 'all',
                    action_objective='myopic' if method=='GR' else 'continuation')
    if method in ('SH','GR'):settings['limits']['depth']=1
    return doc


def publish(*,spec_path,spec_sha256,output):
    spec=load_pin(dict(path=spec_path,sha256=spec_sha256))
    if spec.get('schema_version')!='xgap-ch6-batch-input-v1':raise ValueError('Explicit batch input required')
    selected_methods=spec.get('methods',list(METHODS))
    if (not isinstance(selected_methods,list) or not selected_methods or len(selected_methods)!=len(set(selected_methods))
            or any(method not in METHODS for method in selected_methods)):
        raise ValueError('A nonempty unique subset of the five declared methods is required')
    identities=[validate_cell_id(case['case_id']+'-'+method)
                for case in spec['cases'] for method in selected_methods]
    if len(identities)!=len(set(identities)):raise ValueError('Duplicate cell IDs')
    commit=source_commit();root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    prepared=load_pin(spec['prepared']);load_pin(prepared['profile'])
    if not prepared.get('success'):raise ValueError('Frozen stores not ready')
    if spec['deployment']=='rdf':load_pin(spec['external_runtime'])
    base=load_pin(spec['base_configuration']);rng=random.Random(spec['order_seed'])
    cells=[];bindings=[];config_cache={}
    def configs_for(base):
        key=json.dumps(base,sort_keys=True,separators=(',',':'))
        if key not in config_cache:
            ordinal=len(config_cache);configs={}
            for label in tuple(METHODS)[:-1]:
                name=label+'-config.json' if ordinal==0 else f'{label}-config-{ordinal}.json'
                pin=write_once(root/name,configuration_for(base,label));configs[label]=pin
                _,_,settings,_=load_configuration(pin['path'],pin['sha256']);validate_method(METHODS[label],settings)
            config_cache[key]=configs
        return config_cache[key]
    for case in spec['cases']:
        # Validate public/reference association only, no scoring or answer-based filtering.
        request=load_pin(case['request']);reference=load_pin(case['reference'])
        if request['question_id']!=reference['question_id']:raise ValueError('Case reference mismatch')
        configs=configs_for(load_pin(case['base_configuration']) if 'base_configuration' in case else base)
        labels=[label for label in METHODS if label in selected_methods];rng.shuffle(labels)
        for label in labels:
            if label=='TS' and (spec['deployment']=='native' or spec['input_track']=='controlled'):
                bindings.append(dict(case_id=case['case_id'],method=label,
                    status='unsupported_deployment' if spec['deployment']=='native' else 'fixed_nl_reference_required',
                    cell_id=None,reason='Original TS does not accept native federation or XGAP controlled state.'))
                continue
            cid=case['case_id']+'-'+label
            cell=dict(cell_id=cid,method=METHODS[label],request=case['request'],reference=case['reference'])
            if label!='TS':
                cell.update(scope=case['scope'],oracle=case['oracle'],config=configs[label])
                if spec['input_track']=='controlled':cell['controlled_state']=case['controlled_state']
            cells.append(cell);bindings.append(dict(case_id=case['case_id'],method=label,status='scheduled',cell_id=cid))
    manifest=dict(schema_version=FORMAL_SCHEMA,deployment=spec['deployment'],prepared=spec['prepared'],
        design=spec['design'],external_runtime=spec.get('external_runtime'),cells=cells)
    validate(manifest);pin=write_once(root/'manifest.json',manifest)
    release=dict(schema_version='xgap-ch6-five-method-batch-release-v1',source_commit=commit,
        input=dict(path=spec_path,sha256=spec_sha256),manifest=pin,bindings=bindings,
        methods=selected_methods,
        exposure=spec['exposure'],input_track=spec['input_track'],order_seed=spec['order_seed'],
        method_results_read=0,formal_campaign_ready=False)
    write_once(root/'release.json',release);print(json.dumps(pin))
    return release


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('spec-path','spec-sha256','output'):p.add_argument('--'+n,required=True)
    publish(**vars(p.parse_args()))
