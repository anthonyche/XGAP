#!/usr/bin/env python3
"""Publish the selected 48 NL cases with a frozen actual-family probe policy."""
import argparse
from dataclasses import replace
import json
from pathlib import Path

from prepare_ch6_execution_units import case_configuration
from release_ch6_five_method_batch import publish
from run_bounded_joint_batch import source_commit
from xgap.agent.live_probe import policy_from_dict
from xgap.experiments.ch6_formal_protocol import load_pin,METHODS
from xgap.experiments.ch6_pilot_release import TOKEN_POLICY
from xgap.experiments.ch6_small_sample import EXPOSURE
from xgap.experiments.ch6_small_release import SCHEMA,audit
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.unified_contract import load_configuration,configuration


def prepare(spec_path,spec_sha256,output):
    spec=load_pin(dict(path=spec_path,sha256=spec_sha256))
    if spec.get('schema_version')!='xgap-ch6-small-release-input-v1':raise ValueError('Explicit small-study inputs required')
    selection=load_pin(spec['selection']);policy=policy_from_dict(load_pin(spec['live_probe_policy']))
    migration=selection.get('entry_migration')
    if migration:
        from xgap.experiments.ch6_small_migration import verify_migration,verify_selection,PROVIDER
        verified=verify_migration(migration);verify_selection(selection,verified)
    if policy is None:raise ValueError('A real live probe policy must be pinned')
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    units=[]
    for cohort in selection['cohorts']:
        name=cohort['dataset']+'-'+cohort['deployment'];folder=root/name;folder.mkdir();cases=[]
        inherited_requests=({c['case_id']:c['original_request'] for row in verified['cohorts']
            if (row['dataset'],row['deployment'])==(cohort['dataset'],cohort['deployment'])
            for c in row['cases']} if migration else {})
        for i,case in enumerate(cohort['cases']):
            # Only public slot/configuration inheritance uses the original wording
            # bound to the unchanged controlled state. All methods get new NL below.
            config_case={**case,'request':inherited_requests[case['case_id']]} if migration else case
            original=case_configuration(config_case,**cohort.get('parameters',{}))
            base_pin=write_once(folder/f'base-inherited-{i:02d}.json',original)
            _,information,settings,costs=load_configuration(base_pin['path'],base_pin['sha256'])
            settings=replace(settings,limits=replace(settings.limits,aggregation='expectation'),
                information_targets=(),candidate_weights=None,live_probe_policy=policy)
            base=configuration(settings=settings,information=information,costs=costs,
                               provider=PROVIDER if migration else 'frozen_compact_model_equivalence_v1')
            config=write_once(folder/f'base-live-{i:02d}.json',base)
            cases.append({**case,'base_configuration':config})
        inputs=dict(schema_version='xgap-ch6-batch-input-v1',prepared=cohort['prepared'],
            external_runtime=cohort.get('external_runtime'),deployment=cohort['deployment'],
            input_track='nl',exposure=EXPOSURE,order_seed=20260926,
            base_configuration=cases[0]['base_configuration'],design=cohort['design'],cases=cases,methods=list(METHODS))
        if migration:inputs.update(entry_migration=migration,entry_profile=cohort['entry_profile'])
        inp=write_once(folder/'input.json',inputs)
        result=publish(spec_path=inp['path'],spec_sha256=inp['sha256'],output=folder/'unit')
        units.append(dict(unit_id=name+'-small-r0',dataset=cohort['dataset'],deployment=cohort['deployment'],
            repetition=0,input_track='nl',manifest=result['manifest'],bindings=result['bindings'],
            cell_cases={b['cell_id']:b['case_id'] for b in result['bindings'] if b['cell_id']}))
    release=dict(schema_version=SCHEMA,purpose='small_real_evaluation',exposure=EXPOSURE,
        heldout_claim=False,full_800_claim=False,selection=spec['selection'],preparation_spec=dict(path=spec_path,sha256=spec_sha256),
        live_probe_policy=spec['live_probe_policy'],source_commit=source_commit(),output_root=spec['output_root'],
        units=units,execution_dataset_order=['D1','D3','D2'],repetitions=1,automatic_retries=0,max_cells_per_source_session=32,
        budget=spec['budget'],token_policy=TOKEN_POLICY,methods=list(METHODS))
    pin=write_once(root/'release.json',release)
    result=audit(release);write_once(root/'audit.json',result)
    return dict(release=pin,audit_passed=result['success'],failed_checks=result['failed_checks'],
                model_calls=0,backend_calls=0,submitted_jobs=0)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('spec-path','spec-sha256','output'):p.add_argument('--'+n,required=True)
    result=prepare(**vars(p.parse_args()));print(json.dumps(result));raise SystemExit(0 if result['audit_passed'] else 2)
