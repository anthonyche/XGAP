"""Fail-closed formal release admission. Design tables alone are not runnable."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

from xgap.experiments.ch6_formal_protocol import load_pin,METHODS,FIGURES


def audit_release(release,*,free_bytes=None):
    checks=[]
    def check(name,predicate,detail=''):
        checks.append(dict(check=name,passed=bool(predicate),detail=detail))
    check('schema',release.get('schema_version')=='xgap-ch6-formal-release-v1')
    check('five_methods',release.get('methods')==list(METHODS))
    check('all_21_figures',release.get('figures')==[f.id for f in FIGURES])
    check('no_automatic_retries',release.get('automatic_retries')==0)
    check('frozen_before_results',release.get('method_results_read_at_release')==0)
    try:
        budget=release['budget']
        for k in ('total_wall_seconds','package_max_bytes','free_disk_reserve_bytes','model_calls_cap',
                  'input_tokens_cap','output_tokens_cap','repetitions'):
            check('positive_budget_'+k,type(budget.get(k)) is int and budget[k]>0)
        output=Path(release['output_root'])
        probe=output
        while not probe.exists():probe=probe.parent
        free=shutil.disk_usage(probe).free if free_bytes is None else free_bytes
        check('disk_capacity',free>=budget['package_max_bytes']+budget['free_disk_reserve_bytes'])
        case_ids=set();counts=Counter();template_splits={};input_keys={}
        for bundle_pin in release['case_bundles']:
            bundle=load_pin(bundle_pin)
            check('bundle_schema',bundle.get('schema_version')=='xgap-ch6-heldout-cases-v1',bundle_pin['path'])
            check('bundle_test_only',bundle.get('split')=='test' and bundle.get('method_outputs_used_for_selection') is False)
            for partition,ids in bundle['template_splits'].items():
                template_splits.setdefault(partition,set()).update(ids)
            for case in bundle['cases']:
                cid=case['case_id'];check('unique_case_'+cid,cid not in case_ids);case_ids.add(cid)
                counts[(bundle['dataset'],case['workload'])]+=1
                check('template_in_test_'+cid,case['template_family'] in bundle['template_splits']['test'])
                for key in ('request','scope','oracle','reference','controlled_state'):
                    load_pin(case[key])
                request=load_pin(case['request']);oracle=load_pin(case['oracle']);ref=load_pin(case['reference'])
                encoded=json.dumps(request['question'],sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
                check('private_question_'+cid,oracle['question_sha256']==hashlib.sha256(encoded.encode()).hexdigest())
                check('reference_question_'+cid,ref['question_id']==request['question_id'])
                check('independent_reference_'+cid,case.get('reference_engine') in
                      ('independent_relational','independent_gold_sparql','independent_gold_cypher'))
                input_keys[cid]=dict(request=case['request']['sha256'],reference=case['reference']['sha256'])
        check('nonempty_test',bool(case_ids))
        check('disjoint_templates',not template_splits.get('test',set()) &
              (template_splits.get('development',set())|template_splits.get('pilot',set())))
        for d in ('D1','D2','D3'):
            for w in ('W1','W2','W3','W4'):
                check('sample_'+d+'_'+w,counts[(d,w)]==release['sample_counts'][d][w])
        figures=set();methods=set();units=set()
        from run_bounded_joint_batch import validate,FORMAL_SCHEMA
        for unit in release['units']:
            check('unique_unit_'+unit['unit_id'],unit['unit_id'] not in units);units.add(unit['unit_id'])
            manifest=load_pin(unit['manifest']);validate(manifest)
            check('formal_dispatch_'+unit['unit_id'],manifest['schema_version']==FORMAL_SCHEMA)
            preparation=load_pin(manifest['prepared']);check('stores_'+unit['unit_id'],preparation.get('success'))
            for cell in manifest['cells']:
                methods.add(cell['method'])
                public=load_pin(cell['request']);ref=load_pin(cell['reference'])
                check('cell_reference_'+cell['cell_id'],public['question_id']==ref['question_id'])
            figures.update(unit['figures'])
        for support in release['support_exceptions']:
            check('honest_exception',support['status'] in ('unsupported_deployment','unsupported_interface','unscorable_metric')
                  and bool(support['reason']) and support.get('value') is None)
            figures.update(support['figures'])
        check('figure_execution_coverage',figures=={f.id for f in FIGURES})
        check('method_execution_coverage',methods==set(METHODS.values()))
        for name in ('five_method_gate','factor_gate','scoring_gate'):
            evidence=load_pin(release['gates'][name])
            check(name,evidence.get('success') is True)
        for pin in release['artifact_pins']:load_pin(pin)
    except (KeyError,ValueError,TypeError,OSError) as error:
        check('complete_pinned_release',False,type(error).__name__+': '+str(error))
    return dict(schema_version='xgap-ch6-release-audit-v1',success=all(c['passed'] for c in checks),checks=checks,
                model_calls=0,backend_calls=0,failed_checks=[c for c in checks if not c['passed']])
