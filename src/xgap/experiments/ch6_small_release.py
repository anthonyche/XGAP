"""Release audit for the explicitly selected 48-case study, not the 800-case plan."""
from collections import Counter
from pathlib import Path
import re
import shutil

from xgap.experiments.ch6_formal_protocol import load_pin, METHODS
from xgap.experiments.ch6_small_sample import SCHEMA as SELECTION_SCHEMA, EXPOSURE
from xgap.experiments.ch6_pilot_release import TOKEN_POLICY

SCHEMA='xgap-ch6-small-real-release-v1'
BUDGET_KEYS=('total_wall_seconds','package_max_bytes','free_disk_reserve_bytes','model_calls_cap',
             'input_tokens_stop_threshold','output_tokens_stop_threshold')


def validate_membership(selection,units,manifests):
    """Require exactly the selected inputs once, including failures not yet known."""
    if selection.get('schema_version')!=SELECTION_SCHEMA or selection.get('unique_query_intent_cases')!=48:
        raise ValueError('A frozen 48-case selection is required')
    cohorts={(c['dataset'],c['deployment']):c for c in selection['cohorts']}
    if len(cohorts)!=6 or len(units)!=6 or len(manifests)!=6:
        raise ValueError('Six selected dataset/deployment units are required')
    expected_pairs={(d,p) for d in ('D1','D2','D3') for p in ('native','rdf')}
    seen=set();total=0;support=[]
    for unit,manifest in zip(units,manifests):
        key=(unit['dataset'],unit['deployment'])
        if key in seen or key not in cohorts:raise ValueError('Duplicate/unknown small-study unit')
        seen.add(key);cohort=cohorts[key]
        cases={c['case_id']:c for c in cohort['cases']}
        if len(cases)!=8 or len(cohort['case_ids'])!=8 or set(cases)!=set(cohort['case_ids']):
            raise ValueError('Exactly eight selected cases required per deployment')
        if Counter((c['workload'],c['stratum']) for c in cases.values())!=Counter(
                (w,f) for w in ('W1','W2','W3','W4') for f in ('uniform','active-anchor')):
            raise ValueError('W × sampling frame balance differs')
        if (manifest['deployment']!=key[1] or manifest['prepared']!=cohort['prepared']
                or manifest['design']!=cohort['design']
                or manifest.get('external_runtime')!=cohort.get('external_runtime')):
            raise ValueError('Original source deployment or budget changed')
        wanted={(cid,label) for cid in cases for label in METHODS if label!='TS' or key[1]=='rdf'}
        actual=set()
        for cell in manifest['cells']:
            cid=unit['cell_cases'][cell['cell_id']]
            label=next((k for k,v in METHODS.items() if v==cell['method']),None)
            pair=(cid,label)
            if pair not in wanted or pair in actual:raise ValueError('Unexpected or repeated selected method request')
            actual.add(pair)
            if 'controlled_state' in cell:raise ValueError('Main study must remain NL entry')
            for name in ('request','reference','oracle','scope'):
                if name in cell and cell[name]!=cases[cid][name]:raise ValueError('Selected input changed')
            total+=1
        if actual!=wanted:raise ValueError('Missing selected method request')
        support.extend(dict(dataset=key[0],deployment=key[1],case_id=cid,method=label,
                            status='unsupported_deployment' if label=='TS' and key[1]=='native' else 'supported')
                       for cid in cases for label in METHODS)
    if seen!=expected_pairs or total!=216:raise ValueError('Wrong small-study totals')
    return support


def audit(release,*,free_bytes=None):
    from run_bounded_joint_batch import validate
    from xgap.experiments.ch6_backend_eligibility import eligible,check_design
    from xgap.experiments.unified_contract import load_configuration,validate_method
    checks=[]
    def check(name,value):checks.append(dict(check=name,passed=bool(value)))
    try:
        check('schema',release['schema_version']==SCHEMA)
        check('explicit_small_scope',release['purpose']=='small_real_evaluation' and
              release['exposure']==EXPOSURE and release['heldout_claim'] is False and
              release['full_800_claim'] is False and release['repetitions']==1)
        check('revision',re.fullmatch(r'[a-f0-9]{40}',release['source_commit']) is not None)
        check('no_retries',release['automatic_retries']==0)
        check('five_methods',release['methods']==list(METHODS))
        check('frozen_execution_order',release['execution_dataset_order']==['D1','D3','D2'])
        check('observed_tokens',release['token_policy']==TOKEN_POLICY)
        check('session_bound',type(release['max_cells_per_source_session']) is int and
              1<=release['max_cells_per_source_session']<=32)
        for key in BUDGET_KEYS:
            check('budget_'+key,type(release['budget'].get(key)) is int and release['budget'][key]>0)
        root=Path(release['output_root']);check('absolute_output',root.is_absolute())
        while not root.exists():root=root.parent
        capacity=shutil.disk_usage(root).free if free_bytes is None else free_bytes
        check('disk_capacity',capacity>=release['budget']['package_max_bytes']+release['budget']['free_disk_reserve_bytes'])
        selection=load_pin(release['selection']);manifests=[load_pin(u['manifest']) for u in release['units']]
        support=validate_membership(selection,release['units'],manifests)
        check('exact_216_requests',len([s for s in support if s['status']=='supported'])==216)
        reservations=0;policy=load_pin(release['live_probe_policy'])
        for cohort,unit,manifest in zip(selection['cohorts'],release['units'],manifests):
            if (cohort['dataset'],cohort['deployment'])!=(unit['dataset'],unit['deployment']):
                raise ValueError('Frozen unit order differs')
            gate=load_pin(cohort['backend_admission'])
            parent=load_pin(cohort['bundle']);parent_cases={c['case_id']:c for c in parent['cases']}
            def same_pin(a,b):return all(a.get(k)==b.get(k) for k in ('path','sha256'))
            if not same_pin(parent['profile'],cohort['profile']) or not same_pin(load_pin(cohort['prepared'])['profile'],cohort['profile']):
                raise ValueError('Selected cohort profile differs from its prepared parent')
            for case in cohort['cases']:
                original=parent_cases.get(case['case_id'])
                if original is None or any(case[k]!=original[k] for k in
                        ('request','reference','oracle','scope','controlled_state')):
                    raise ValueError('Selected inputs differ from the admitted parent bundle')
            check('parent_source_eligibility_'+unit['unit_id'],eligible(gate,bundle_pin=cohort['bundle'],prepared_pin=cohort['prepared']))
            check_design(gate,manifest['design']);validate(manifest)
            check('bounded_unit_storage_'+unit['unit_id'],manifest['design']['package_max_bytes']<=release['budget']['package_max_bytes'])
            configs={}
            for cell in manifest['cells']:
                for name in ('request','reference','oracle','scope'):
                    if name in cell:load_pin(cell[name])
                if cell['method']=='aruqula-fedx':
                    reservations+=load_pin(manifest['external_runtime'])['model_budget']['max_calls'];continue
                raw,_,settings,_=load_configuration(cell['config']['path'],cell['config']['sha256'])
                validate_method(cell['method'],settings)
                if raw['provider']!='frozen_compact_model_equivalence_v1':
                    raise ValueError('Small study requires the frozen equivalent-public-input frontend adapter')
                if settings.live_probe_policy is None or settings.candidate_weights is not None or settings.information_targets:
                    raise ValueError('Bind live probe and candidate priors after actual NL interpretation')
                from dataclasses import asdict
                if asdict(settings.live_probe_policy)!=policy:
                    # JSON encodes tuple probabilities as a list.
                    import json
                    if json.loads(json.dumps(asdict(settings.live_probe_policy)))!=policy:
                        raise ValueError('Cell probe policy differs from the frozen release policy')
                if settings.limits.aggregation!='expectation':raise ValueError('Paid information study requires explicit expected-cost objective')
                configs[(unit['cell_cases'][cell['cell_id']],cell['method'])]=raw;reservations+=1
            for cid in cohort['case_ids']:
                x=configs[(cid,METHODS['XGAP'])];n=configs[(cid,METHODS['NP'])]
                from copy import deepcopy
                normalized=deepcopy(n);normalized['settings']['information_mode']='all'
                if normalized!=x:raise ValueError('XGAP/NP differ beyond probe availability')
        check('model_call_reservation',reservations<=release['budget']['model_calls_cap'])
    except (KeyError,ValueError,TypeError,OSError,StopIteration) as exc:
        checks.append(dict(check='pinned_small_release',passed=False,detail=f'{type(exc).__name__}: {exc}'))
    return dict(schema_version='xgap-ch6-small-release-audit-v1',success=all(c['passed'] for c in checks),
                checks=checks,failed_checks=[c for c in checks if not c['passed']],model_calls=0,backend_calls=0)
