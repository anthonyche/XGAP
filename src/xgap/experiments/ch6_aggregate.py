"""Offline cohort reduction over sealed trials and predeclared support.

No model/backend calls, outcome-dependent support, or inferred observations.
This reduces a cohort; figure bindings and frozen release admission are separate.
"""
from xgap.experiments.ch6_formal_protocol import METHODS, load_pin
from xgap.experiments.ch6_formal_metrics import extract_metrics, clustered_summary
from xgap.experiments.ch6_support import validate_support, summarize_supported, paired_xgap_subset

METRICS = ('e2e_ms', 'request_ms', 'planning_ms', 'answer_em', 'answer_f1',
           'interpretation_loss', 'backend_calls', 'clarification_calls',
           'trace_cost', 'coordinator_rss_bytes')
COMPLETED_METRICS = {'e2e_ms', 'request_ms'}


def reduce_cohort(spec):
    if spec.get('schema_version') != 'xgap-ch6-cohort-input-v1':
        raise ValueError('Unknown cohort input')
    support = validate_support(load_pin(spec['support']))
    cases = {c['case_id']: c for c in support['cases']}
    metadata = spec['case_metadata']
    if set(metadata) != set(cases):
        raise ValueError('Metadata must cover the complete frozen cohort')
    strata = {v['stratum'] for v in metadata.values()}
    if len(strata) != 1 or not all(v.get('family_id') and v.get('question_id') for v in metadata.values()):
        raise ValueError('One sampling stratum and explicit template/question identities required')
    repetitions = spec['repetitions']
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError('Positive frozen repetition count required')
    observations = []
    for trial in spec['trials']:
        cid = trial['case_id']
        if cid not in cases or type(trial['repeat']) is not int or not 0 <= trial['repeat'] < repetitions:
            raise ValueError('Unknown case or repetition')
        terminal = load_pin(trial['terminal'])
        metrics = extract_metrics(outcome_pin=terminal['outcome'], score_pin=terminal['score'],
            timing_pin=trial['timing'], loss_pin=terminal.get('query_loss'), weights=spec['trace_cost_weights'])
        method = next((k for k, v in METHODS.items() if v == metrics['method_id']), None)
        if method is None or metrics['question_id'] != metadata[cid]['question_id']:
            raise ValueError('Sealed question/method differs from the cohort')
        if metrics['dataset'] != spec['dataset']:
            raise ValueError('Dataset differs from the declared cohort')
        # Actual trial deployment/snapshot identity is pinned by its manifest.
        manifest = load_pin(trial['manifest'])
        cell = next((c for c in manifest['cells'] if c['cell_id'] == terminal['cell_id']), None)
        outcome = load_pin(terminal['outcome'])
        if cell is None or cell['method'] != metrics['method_id']:
            raise ValueError('Terminal is not a cell of the pinned manifest')
        if outcome['request_sha256'] != cell['request']['sha256']:
            raise ValueError('Outcome request differs from the frozen manifest')
        if manifest['deployment'] != cases[cid]['deployment']:
            raise ValueError('Actual deployment differs from the support contract')
        prepared = load_pin(manifest['prepared'])
        if prepared.get('success') is not True or prepared['dataset'] != metrics['dataset']:
            raise ValueError('Trial does not use the admitted dataset identity')
        if prepared['dataset']['version'] != cases[cid]['source_snapshot_sha256']:
            raise ValueError('Prepared sources differ from the frozen snapshot')
        observations.append(dict(metrics, case_id=cid, repeat=trial['repeat'], method=method,
            family_id=metadata[cid]['family_id'], deployment=manifest['deployment'],
            source_snapshot_sha256=prepared['dataset']['version']))
    summaries = {}
    for method in METHODS:
        s = summarize_supported(support, observations, method)
        seen = {(r['case_id'], r['repeat']) for r in s['rows']}
        missing = [(cid, rep) for cid, c in cases.items()
                   if c['methods'][method]['status'] == 'supported'
                   for rep in range(repetitions) if (cid, rep) not in seen]
        scope = {r['timing_scope'] for r in s['rows']}
        if len(scope) > 1:
            raise ValueError('A cohort cannot mix NL and controlled timing for a method')
        metrics = {}
        for metric in METRICS:
            filtered = [dict(r, **{metric: None if r['study_censored'] or
                (metric in COMPLETED_METRICS and not r['execution_success']) else r.get(metric)}) for r in s['rows']]
            metrics[metric] = clustered_summary(filtered, metric,
                bootstrap=spec.get('bootstrap', 2000), seed=spec.get('bootstrap_seed', 20260923))
            metrics[metric]['scored_requests'] = sum(r[metric] is not None for r in filtered)
        metrics['max_interpretation_loss'] = clustered_summary(
            [dict(r, interpretation_loss=None if r['study_censored'] else r['interpretation_loss']) for r in s['rows']],
            'interpretation_loss', statistic='max', bootstrap=0)
        summaries[method] = {k: v for k, v in s.items() if k != 'rows'} | dict(
            expected_requests=s['supported_cases'] * repetitions, missing_requests=missing,
            study_censored_requests=sum(r['study_censored'] for r in s['rows']),
            timing_scope=next(iter(scope), None), metrics=metrics)
    paired = {}
    for method in METHODS:
        if method == 'XGAP':
            continue
        pairs = paired_xgap_subset(support, observations, method, completed_only=True)
        rows = [dict(own, ratio=other['e2e_ms'] / own['e2e_ms']) for own, other in pairs
                if not own['study_censored'] and not other['study_censored']
                and own['e2e_ms'] is not None and own['e2e_ms'] > 0 and other['e2e_ms'] is not None]
        paired[method] = dict(ratio='comparator latency / XGAP latency; same case, repeat, deployment and timing',
            summary=clustered_summary(rows, 'ratio', bootstrap=spec.get('bootstrap', 2000),
                seed=spec.get('bootstrap_seed', 20260923)))
    return dict(schema_version='xgap-ch6-cohort-summary-v1', cohort_id=spec['cohort_id'],
        dataset=spec['dataset'], stratum=next(iter(strata)), support=spec['support'],
        methods=summaries, paired_xgap=paired, observations=observations,
        fully_observed=all(not s['missing_requests'] and not s['study_censored_requests'] for s in summaries.values()),
        formal_release_admitted=False, model_calls=0, backend_calls=0)
