"""A published dataset's first NL repetition, explicitly a development pilot.

Preserve immutable cases/manifests. A pilot does not satisfy the full research
sample, provenance or holdout contract. No backend/model calls in this module.
"""
from collections import Counter
from pathlib import Path
import re
import shutil

from xgap.experiments.ch6_formal_protocol import load_pin, METHODS
from xgap.experiments.ch6_support import validate_support
from xgap.experiments.ch6_backend_eligibility import eligible

SCHEMA='xgap-ch6-dataset-pilot-release-v1'
TOKEN_POLICY=dict(kind='observed_thresholds',check='before_each_method_request',
    overshoot='One method request may cross a threshold; no exact tokenizer bound is claimed')


def make_release(publication,dataset,source_commit,output_root,budget):
    prior=load_pin(publication)
    handoff=prior['first_dataset_handoffs'][dataset]
    selected=[next(u for u in handoff['units'] if u['unit_id']==name)
              for name in handoff['first_repetition']]
    spec=load_pin(prior['input']);contract=load_pin(spec['contract'])
    cohorts=[c for c in contract['cohorts'] if c['cohort_id'] in (dataset+'-native',dataset+'-rdf')]
    return dict(schema_version=SCHEMA,purpose='development_pilot',heldout_claim=False,
        original_workload_satisfied=False,dataset=dataset,publication=publication,
        source_commit=source_commit,output_root=str(output_root),units=selected,
        case_bundles=[c['bundle'] for c in cohorts],support_contract=prior['support'],
        external_interface_gate=contract['external_interface_gate'],methods=list(METHODS),
        repetitions=1,automatic_retries=0,method_results_read_at_release=0,
        max_cells_per_source_session=32,budget=budget,token_policy=TOKEN_POLICY,
        fixed_manifest_order=True)


def audit_pilot(release,*,free_bytes=None):
    from run_bounded_joint_batch import validate
    checks=[]
    def check(k,v):checks.append(dict(check=k,passed=bool(v)))
    try:
        check('schema',release['schema_version']==SCHEMA)
        check('source_revision',isinstance(release.get('source_commit'),str) and
              re.fullmatch(r'[a-f0-9]{40}',release['source_commit']) is not None)
        check('absolute_output_root',Path(release['output_root']).is_absolute())
        check('honest_pilot_scope',release['purpose']=='development_pilot' and
              release['heldout_claim'] is False and release['original_workload_satisfied'] is False)
        check('one_repetition',release['repetitions']==1)
        check('no_result_selection_or_retry',release['automatic_retries']==0 and release['method_results_read_at_release']==0)
        check('five_methods',release['methods']==list(METHODS))
        check('observed_tokens_not_estimated_bound',release['token_policy']==TOKEN_POLICY)
        check('bounded_sessions',type(release['max_cells_per_source_session']) is int and
              1<=release['max_cells_per_source_session']<=32)
        budget=release['budget']
        for key in ('total_wall_seconds','package_max_bytes','free_disk_reserve_bytes','model_calls_cap',
                    'input_tokens_stop_threshold','output_tokens_stop_threshold'):
            check('budget_'+key,type(budget.get(key)) is int and budget[key]>0)
        root=Path(release['output_root']);probe=root
        while not probe.exists():probe=probe.parent
        free=shutil.disk_usage(probe).free if free_bytes is None else free_bytes
        check('disk_capacity',free>=budget['package_max_bytes']+budget['free_disk_reserve_bytes'])
        prior=load_pin(release['publication']);handoff=prior['first_dataset_handoffs'][release['dataset']]
        check('successful_publication',prior['success'] is True and all(prior[k]==0 for k in ('model_calls','backend_calls','submitted_jobs')))
        expected=[next(u for u in handoff['units'] if u['unit_id']==name) for name in handoff['first_repetition']]
        check('both_deployments_first_repetition',release['units']==expected and len(expected)==2 and
              all(u['repetition']==0 and u['input_track']=='nl' for u in expected))
        spec=load_pin(prior['input']);contract=load_pin(spec['contract']);old=load_pin(spec['previous_receipt'])
        cohorts=[c for c in contract['cohorts'] if c['cohort_id'] in (release['dataset']+'-native',release['dataset']+'-rdf')]
        check('full_frozen_bundles',len(cohorts)==2 and release['case_bundles']==[c['bundle'] for c in cohorts])
        check('unchanged_support',release['support_contract']==prior['support'])
        check('interface_gate',release['external_interface_gate']==contract['external_interface_gate'] and
              load_pin(release['external_interface_gate'])['success'] is True)
        support=validate_support(load_pin(release['support_contract']));supported={c['case_id']:c for c in support['cases']}
        wanted=set();actual=set();cases=set();calls=0;counts=Counter()
        for cohort in cohorts:
            bundle=load_pin(cohort['bundle']);gate=load_pin(old['cohorts'][cohort['cohort_id']]['eligibility'])
            check('eligible_'+cohort['cohort_id'],eligible(gate,bundle_pin=cohort['bundle'],prepared_pin=cohort['prepared']))
            for case in bundle['cases']:
                cid=case['case_id'];check('unique_case_'+cid,cid not in cases);cases.add(cid)
                for method,assessment in supported[cid]['methods'].items():
                    if assessment['status']=='supported':wanted.add((cid,METHODS[method]))
            unit=next(u for u in release['units'] if load_pin(u['manifest'])['deployment']==cohort['deployment'])
            manifest=load_pin(unit['manifest']);validate(manifest)
            check('same_store_'+unit['unit_id'],manifest['prepared']==cohort['prepared'])
            check('unit_space_'+unit['unit_id'],manifest['design']['package_max_bytes']<=budget['package_max_bytes'])
            by_id={c['case_id']:c for c in bundle['cases']}
            for cell in manifest['cells']:
                cid=unit['cell_cases'][cell['cell_id']];key=(cid,cell['method'])
                check('unique_request_'+cell['cell_id'],key not in actual);actual.add(key);counts[cell['method']]+=1
                check('nl_only_'+cell['cell_id'],'controlled_state' not in cell)
                for field in ('request','reference','oracle','scope'):
                    if field in cell:
                        check('same_'+field+'_'+cell['cell_id'],cell[field]==by_id[cid][field]);load_pin(cell[field])
                if cell['method']=='aruqula-fedx':
                    runtime=load_pin(manifest['external_runtime']);calls+=runtime['model_budget']['max_calls']
                else:
                    load_pin(cell['config']);calls+=1
        check('all_supported_requests_exactly_once',actual==wanted)
        check('model_call_reservation',calls<=budget['model_calls_cap'])
        check('fixed_manifest_order',release['fixed_manifest_order'] is True)
    except (KeyError,ValueError,TypeError,OSError,StopIteration) as error:
        checks.append(dict(check='complete_pinned_pilot',passed=False,detail=type(error).__name__+': '+str(error)))
    return dict(schema_version='xgap-ch6-dataset-pilot-audit-v1',success=all(c['passed'] for c in checks),
        checks=checks,failed_checks=[c for c in checks if not c['passed']],model_calls=0,backend_calls=0,
        formal_campaign_ready=False)
