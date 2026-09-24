#!/usr/bin/env python3
"""Freeze repetitions/configurations for an admitted cohort; never execute it.

Per-case relaxation names come from its public finite family. Hard scope slots
remain mandatory. Private intent and reference answer values cannot choose knobs.
"""
import argparse
from copy import deepcopy
from pathlib import Path

from release_ch6_five_method_batch import publish
from ch6_source_runtime import validate_admission
from xgap.agent.intent_strong import FamilyInformationPolicy
from xgap.agent.unified_family import UnifiedSettings
from xgap.agent.unified_lookahead import Limits
from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.controlled_state import read_state
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.unified_contract import configuration
from xgap.planning.joint_cost import JointCostProfile


def case_configuration(case,*,depth=2,horizon=12,epsilon='1/3',clarification_price=1,probe_price=1):
    if probe_price not in (.1,.5,1,2,5) or clarification_price not in (.1,.5,1,2,5):
        raise ValueError('Use a declared price-grid value')
    request=load_pin(case['request'])
    family,_,_=read_state(load_pin(case['controlled_state']),request['question'])
    settings=UnifiedSettings(epsilon=epsilon,relaxable=tuple(s.name for s in family.slots if not s.hard),
        limits=Limits(depth=depth,horizon=horizon,max_outcomes=1024,max_terminals=1024,optional_ms=1000),
        max_plans=4096,max_plan_bytes=64*1024**2)
    costs=JointCostProfile(clarification_call=clarification_price,disclosed_field=.25*clarification_price)
    # No unregistered/artificial probe is added to manufacture an NP separation.
    # The price axis is explicitly inactive until a real frozen target is registered.
    return configuration(settings=settings,information=FamilyInformationPolicy(),costs=costs)


def prepare(spec_path,spec_sha256,output):
    spec=load_pin(dict(path=spec_path,sha256=spec_sha256))
    if (spec.get('schema_version')!='xgap-ch6-unit-preparation-v1' or spec.get('method_results_read')!=0
            or spec['input_track'] not in ('nl','controlled') or type(spec['repetitions']) is not int
            or not 1<=spec['repetitions']<=10):raise ValueError('Explicit pre-result unit preparation required')
    bundle=load_pin(spec['bundle']);stores=load_pin(spec['prepared']);gate=load_pin(spec['backend_admission'])
    if (not stores.get('success') or not gate.get('success') or not gate.get('backend_roundtrip')
            or gate.get('admission_scope','complete_bundle')!='complete_bundle'
            or gate.get('full_bundle_admitted',True) is not True
            or gate['profile']['sha256']!=bundle['profile']['sha256']
            or stores['profile']['sha256']!=bundle['profile']['sha256']):
        raise ValueError('Cohort requires the actual admitted source deployment')
    runtime=validate_admission(spec['design'],bundle['deployment'],spec['prepared'],bundle_pin=spec['bundle'])
    if runtime is not None:
        if runtime['admission']['sha256']!=spec['backend_admission']['sha256']:
            raise ValueError('Cohort and shared-runtime admission must be identical')
    elif gate.get('source_runtime') or gate.get('rdf_file_mode','default')!='default' or gate.get('experimental_lazy_range'):
        raise ValueError('Nondefault admission cannot silently release the default source runtime')
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    wanted=spec.get('case_ids');cases=bundle['cases']
    if wanted is not None:
        if len(wanted)!=len(set(wanted)) or set(wanted)-{c['case_id'] for c in cases}:raise ValueError('Unknown or duplicate selected case')
        cases=[c for c in cases if c['case_id'] in wanted]
    if not cases:raise ValueError('Nonempty prespecified cohort required')
    cases=deepcopy(cases);cache={}
    import json
    for case in cases:
        config=case_configuration(case,**spec.get('parameters',{}));key=json.dumps(config,sort_keys=True)
        if key not in cache:cache[key]=write_once(root/f'base-{len(cache):03d}.json',config)
        case['base_configuration']=cache[key]
    units=[]
    for repetition in range(spec['repetitions']):
        inputs=dict(schema_version='xgap-ch6-batch-input-v1',prepared=spec['prepared'],
            external_runtime=spec.get('external_runtime'),deployment=bundle['deployment'],
            input_track=spec['input_track'],exposure='test',order_seed=spec['order_seed']+repetition,
            base_configuration=cases[0]['base_configuration'],design=spec['design'],cases=cases)
        if 'methods' in spec:inputs['methods']=spec['methods']
        ip=write_once(root/f'input-{repetition:02d}.json',inputs)
        result=publish(spec_path=ip['path'],spec_sha256=ip['sha256'],output=root/f'repeat-{repetition:02d}')
        units.append(dict(unit_id=spec['unit_prefix']+f'-r{repetition}',manifest=result['manifest'],
            repetition=repetition,dataset=bundle['dataset'],input_track=spec['input_track'],
            figures=spec['figures'],bindings=result['bindings'],
            cell_cases={b['cell_id']:b['case_id'] for b in result['bindings'] if b['cell_id']}))
    receipt=dict(schema_version='xgap-ch6-prepared-units-v1',success=True,units=units,
        input=dict(path=spec_path,sha256=spec_sha256),unique_cases=len(cases),repetitions=spec['repetitions'],
        cases=[c['case_id'] for c in cases],model_calls=0,backend_calls=0,method_results_read=0,
        probe_axis_active=False,formal_campaign_ready=False,
        configuration_scope='Same parameter values; per-family non-hard relaxation names; no answer-based choice')
    return write_once(root/'receipt.json',receipt)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('spec-path','spec-sha256','output'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    import json
    print(json.dumps(prepare(**vars(args))))
