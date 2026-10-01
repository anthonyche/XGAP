#!/usr/bin/env python3
"""Recover publication from completed diagnostic evidence, without executing it.

The original failure, manifests, cases and source snapshots remain immutable.
The figure recipes select inputs/configurations before any method results exist.
This produces manifests and bindings, never campaign launch authorization.
"""
import argparse
import json
from copy import deepcopy
from pathlib import Path

from ch6_external_session import verify_config
from freeze_ch6_mixed_support import freeze
from prepare_ch6_execution_units import prepare
from xgap.experiments.ch6_backend_eligibility import eligible
from xgap.experiments.ch6_figure_bindings import audit_bindings
from xgap.experiments.ch6_figure_recipes import build
from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.one_shot_records import write_once


def completed_cohorts(contract, previous):
    """A publication failure is recoverable only after every frozen case closes."""
    items=contract['cohorts']
    if (previous.get('source_commit')!=contract['source_commit']
            or previous.get('error')!='Invalid cell ID' or previous.get('success') is not False
            or previous.get('model_calls')!=0 or previous.get('automatic_retries')!=0
            or previous.get('formal_campaign_started') is not False
            or set(previous['cohorts'])!={x['cohort_id'] for x in items}):
        raise ValueError('Expected the completed diagnostic run with a publication-only failure')
    result={};seen=set()
    for item in items:
        cid=item['cohort_id'];prior=previous['cohorts'][cid]
        census=load_pin(prior['census']);gate=load_pin(prior['eligibility']);bundle=load_pin(item['bundle'])
        order=[c['case_id'] for c in bundle['cases']]
        if (not prior.get('complete') or prior.get('remaining') or prior.get('stop_reason')
                or not census.get('census_complete') or census.get('remaining') or census.get('stop_reason')
                or census.get('error') or census['case_order']!=order or order!=item['case_order']
                or prior['counts']!=census['counts'] or gate['counts']!=census['counts']
                or census.get('model_calls')!=0 or census.get('automatic_retries')!=0
                or gate['source_commit']!=contract['source_commit']
                or gate['evidence']!=[s['receipt'] for s in census['segments']]
                or seen.intersection(order)):
            raise ValueError('Incomplete, changed or repeated diagnostic cohort: '+cid)
        if not eligible(gate,bundle_pin=item['bundle'],prepared_pin=item['prepared']):
            raise ValueError('Backend eligibility missing: '+cid)
        seen.update(order);result[cid]={**item,'eligibility':prior['eligibility']}
    if len(seen)!=contract['maximum_final_plan_executions']:
        raise ValueError('Frozen diagnostic coverage differs')
    return result


def bind_recipes(recipes,units,*,sensitivity_pin,interface_pin):
    """Resolve every symbolic reference to an actual immutable manifest cell."""
    lookup={};names=set()
    for unit in units:
        if unit['unit_id'] in names:raise ValueError('Duplicate execution unit')
        names.add(unit['unit_id'])
        for cell in load_pin(unit['manifest'])['cells']:
            key=(unit['unit_id'],cell['cell_id'])
            if key in lookup:raise ValueError('Duplicate manifest cell')
            lookup[key]=cell
    sensitivity=load_pin(sensitivity_pin);bindings=[];used=set()
    for recipe in recipes['recipes']:
        row=deepcopy(recipe);refs=row.pop('future_cells');row['cells']=refs
        if any((r['unit_id'],r['cell_id']) not in lookup for r in refs):
            raise ValueError('Figure reference has no published cell')
        used.update((r['unit_id'],r['cell_id']) for r in refs)
        if row['figure']=='F6':
            records=[r for r in sensitivity['rows'] if r['method']==row['method'] and r['eta']==row['x_value']]
            if len(records)!=1:raise ValueError('Missing or repeated F6 record')
            record=records[0]
            row.update(status='offline_measured' if record['status']=='measured' else record['status'],
                value=record['value'],evidence_pin=sensitivity_pin)
            if record.get('reason'):row['reason']=record['reason']
        elif row['status']=='unscorable_metric':row['evidence_pin']=interface_pin
        elif row['status']=='planned':row['status']='scheduled'
        if row['figure'] in ('E7','E8') and row['method']!='TS':
            row['cost_references']=[]
            for ref in refs:
                repeat=ref['unit_id'].rsplit('-r',1)[1]
                default=lookup[('D1-mechanism-default-r'+repeat,ref['cell_id'])]
                row['cost_references'].append({**ref,'configuration':default['config']})
        bindings.append(row)
    if used!=set(lookup):raise ValueError('Published cells must exactly cover the frozen recipes')
    return bindings



def dataset_handoffs(units):
    result={}
    for dataset in ('D1','D3'):
        selected=[u for u in units if u['unit_id'].rsplit('-r',1)[0] in
                  (dataset+'-native-final',dataset+'-rdf-final')]
        result[dataset]=dict(units=selected,method_requests=sum(len(load_pin(u['manifest'])['cells']) for u in selected),
            repetitions=3,first_repetition=[u['unit_id'] for u in selected if u['repetition']==0])
    return result


def recover(spec_path,spec_sha256,output):
    spec=load_pin(dict(path=spec_path,sha256=spec_sha256))
    if spec.get('schema_version')!='xgap-ch6-publication-recovery-v1' or spec.get('execute') is not False:
        raise ValueError('Explicit metadata-only recovery required')
    contract=load_pin(spec['contract']);previous=load_pin(spec['previous_receipt'])
    cohorts=completed_cohorts(contract,previous)
    recipes=load_pin(spec['recipes'])
    if (recipes.get('input',{}).get('sha256')!=spec['recipe_input']['sha256']
            or build(load_pin(spec['recipe_input']),load=load_pin)!={k:v for k,v in recipes.items() if k!='input'}):
        raise ValueError('Frozen figure recipes differ')
    prior_d2=load_pin(contract['d2_releaseprep'])
    if (not prior_d2['success'] or any(prior_d2[k] for k in ('backend_calls','model_calls','submitted_jobs'))):
        raise ValueError('Retained D2 publication differs')
    sensitivity=load_pin(spec['f6_sensitivity'])
    if not sensitivity.get('success') or sensitivity['cost_audit']['sha256']!=contract['f6_audit']['sha256']:
        raise ValueError('F6 audit identity differs')
    root=Path(output).resolve()
    if root.exists():raise ValueError('Existing recovery output; never overwrite or repeat')
    # Read-only verification of binaries, author checkouts and metadata. No service starts.
    external_base=load_pin(contract['external_runtime_template']);external={}
    for cid,item in cohorts.items():
        if item['deployment']=='rdf':
            profile=load_pin(load_pin(item['prepared'])['profile'])
            cfg={**external_base,'metadata':profile['offline']['shared_public_metadata']}
            verify_config(cfg,profile);external[cid]=cfg
    root.mkdir(parents=True,exist_ok=False)
    units=[];preparations=[];entries=[]
    for cid,item in cohorts.items():
        entries.append(dict(bundle=item['bundle'],prepared=item['prepared'],backend_admission=item['eligibility'],
            ts_nl_reference=item['kind']=='deployment_factors'))
    for dep,item in contract['retained_d2'].items():
        entries.append(dict(bundle=item['bundle'],prepared=item['prepared'],backend_admission=item['eligibility']))
    for group in recipes['unit_requests']:
        cid=group['cohort_id'];target=root/group['unit_prefix']
        if cid.startswith('D2-'):
            if not group['existing_preparation']:raise ValueError('D2 recovery may only reuse frozen units')
            dep=cid.split('-',1)[1];rp=prior_d2['units'][dep]['receipt'];retained=load_pin(rp)
            if retained['cases']!=group['case_ids'] or retained['repetitions']!=group['repetitions']:
                raise ValueError('Retained D2 unit selection differs')
            for unit in retained['units']:
                if unit['unit_id']!=group['unit_prefix']+'-r'+str(unit['repetition']):
                    raise ValueError('Retained D2 unit identity differs')
                units.append(unit)
            preparations.append(dict(unit_prefix=group['unit_prefix'],receipt=rp,reused=True));continue
        item=cohorts[cid]
        if group['bundle']!=item['bundle']:raise ValueError('Recipe cohort pin differs')
        gate=load_pin(item['eligibility']);stores=load_pin(item['prepared']);target.mkdir()
        design=dict(total_wall_seconds=86400,package_max_bytes=sum(x['bytes'] for x in stores['stores'].values())+16*1024**3,
            free_disk_reserve_bytes=6*1024**3,method_wall_seconds=300,method_rss_bytes=3*1024**3,
            source_rss_bytes=4*1024**3,source_budget=gate['source_budget'],startup_seconds=300,source_storage='node_local')
        ext=write_once(target/'external-runtime.json',external[cid]) if cid in external else None
        unit_spec=dict(schema_version='xgap-ch6-unit-preparation-v1',method_results_read=0,
            bundle=item['bundle'],prepared=item['prepared'],backend_admission=item['eligibility'],external_runtime=ext,
            order_seed=20260923,design=design,
            **{k:group[k] for k in ('unit_prefix','case_ids','methods','input_track','parameters','repetitions','figures','ts_nl_reference')})
        ip=write_once(target/'spec.json',unit_spec);rp=prepare(ip['path'],ip['sha256'],target/'units')
        units.extend(load_pin(rp)['units']);preparations.append(dict(unit_prefix=group['unit_prefix'],receipt=rp,reused=False))
    sp=write_once(root/'support-input.json',dict(schema_version='xgap-ch6-support-input-v1',method_outputs_used=False,
        external_interface_gate=contract['external_interface_gate'],bundles=entries))
    freeze(sp['path'],sp['sha256'],str(root/'support.json'))
    from xgap.experiments.ch6_fact_index import pin
    bindings=bind_recipes(recipes,units,sensitivity_pin=spec['f6_sensitivity'],interface_pin=contract['external_interface_gate'])
    planned=dict(units=units,figure_bindings=bindings)
    checks=audit_bindings(planned)
    audit=write_once(root/'figure-binding-audit.json',dict(success=all(c['passed'] for c in checks),checks=checks))
    if not all(c['passed'] for c in checks):
        raise ValueError('Figure binding audit failed: '+str([c for c in checks if not c['passed']][:8]))
    by_dataset=dataset_handoffs(units)
    result=dict(schema_version='xgap-ch6-publication-recovery-receipt-v1',success=True,
        input=dict(path=spec_path,sha256=spec_sha256),previous_receipt=spec['previous_receipt'],
        preparations=preparations,**planned,support=pin(root/'support.json'),figure_binding_audit=audit,
        first_dataset_handoffs=by_dataset,model_calls=0,backend_calls=0,submitted_jobs=0,
        formal_campaign_ready=False,formal_campaign_started=False,
        remaining=['Freeze API/input-output-token/wall/storage reservations and audit release',
                   'Start the authorized bounded first dataset; full campaign remains unstarted'])
    return write_once(root/'receipt.json',result)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('spec-path','spec-sha256','output'):p.add_argument('--'+name,required=True)
    print(json.dumps(recover(**vars(p.parse_args()))))
