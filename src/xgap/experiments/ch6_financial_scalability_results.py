"""Summarize observed scalability attempts without querying any backend.

All three repetitions contribute to a complete point. A hard 600-second request
deadline is clipped only when its observation is explicitly attested; missing
costs and unfinished repetitions remain unknown. No synthetic attempts are made.
"""
import csv
import hashlib
import html
import json
import math
from pathlib import Path
import statistics

from xgap.experiments.ch6_financial_plan_comparability import SCHEMA as PLAN_SCHEMA, EXCLUSIONS


SCHEMA = 'xgap-financial-scalability-results-v1'
SCANS = ('A_endpoints', 'B_workers')
METHODS = ('XGAP', 'NP', 'SH', 'GR')
QUERIES = ('Q1', 'Q2', 'Q3', 'Q4')
REPETITIONS = (0, 1, 2)
REQUEST_SECONDS = 600
METRICS = ('request_latency_s', 'backend_calls', 'realized_cost', 'planning_wall_ms',
           'planning_cpu_ms', 'execution_ms', 'peak_rss_mb', 'shards_touched',
           'endpoints_actual', 'cross_endpoint_edges')
COUNTS = {'backend_calls', 'shards_touched', 'endpoints_actual', 'cross_endpoint_edges'}
RAW_FIELDS = ('scan_name', 'x_value', 'method', 'query_id', 'repetition', 'status', *METRICS,
              'timestamp', 'request_latency_observed_s', 'hard_deadline_observed', 'latency_censored')
SUMMARY_FIELDS = ('scan_name', 'x_value', 'method', 'query_id', 'complete', 'attempts_observed',
                  'missing_repetitions', 'success_count', 'failed_count', 'timeout_count',
                  'censored_count', 'expected_endpoints', 'endpoint_count_match',
                  'selected_dag_distinct_count', 'selected_dag_unknown_count',
                  'execution_plan_distinct_count', 'execution_plan_unknown_count',
                  'plan_variation_observed',
                  'observed_nodes', 'observed_job_ids', 'node_unknown_count',
                  'allocation_unknown_count', 'hardware_boundary_observed',
                  *(item for metric in METRICS for item in (metric+'_median', metric+'_valid_n')))
OUTPUT_NAMES = {'A_endpoints': {'raw': 'scalability_A.csv', 'summary': 'scalability_A_summary.csv'},
                'B_workers': {'raw': 'scalability_B.csv', 'summary': 'scalability_B_summary.csv'}}


def _levels(values, name):
    values = tuple(values)
    if (not values or len(set(values)) != len(values)
            or any(type(v) is not int or v < 1 or v > 32 for v in values)):
        raise ValueError('Invalid configured levels: '+name)
    return tuple(sorted(values))


def _number(value, name):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('Metric must be finite, nonnegative or null: '+name)
    if name in COUNTS and type(value) is not int:
        raise ValueError('Count must be an integer or null: '+name)
    return value


def _normalize(attempt, levels, methods):
    scan, x = attempt['scan_name'], attempt['x_value']
    query, repetition, status = attempt['query_id'], attempt['repetition'], attempt['status']
    method = attempt.get('method')
    if method not in methods:
        raise ValueError('An explicit configured method is required on every observed attempt')
    if scan not in SCANS or type(x) is not int or x not in levels[scan]:
        raise ValueError('Attempt is outside the configured scan')
    if query not in QUERIES or type(repetition) is not int or repetition not in REPETITIONS:
        raise ValueError('Attempt query/repetition differs from the four-query, three-repeat contract')
    if status not in ('answered', 'failed', 'timeout'):
        raise ValueError('Attempt status must be answered, failed or timeout')
    if not isinstance(attempt.get('timestamp'), str) or not attempt['timestamp'].strip():
        raise ValueError('Observed timestamp required; the summarizer never invents one')
    deadline = attempt.get('hard_deadline_observed', False)
    if type(deadline) is not bool or (deadline and status != 'timeout'):
        raise ValueError('A hard deadline observation requires timeout status')
    row = dict(scan_name=scan, x_value=x, method=method, query_id=query, repetition=repetition, status=status,
               timestamp=attempt['timestamp'])
    row.update({metric: _number(attempt.get(metric), metric) for metric in METRICS})
    observed = _number(attempt.get('request_latency_observed_s', row['request_latency_s']), 'request_latency_observed_s')
    if not deadline and observed != row['request_latency_s']:
        raise ValueError('Unclipped latency and its observed value disagree')
    row.update(request_latency_observed_s=observed, hard_deadline_observed=deadline,
               latency_censored=status == 'timeout')
    if deadline:
        row['request_latency_s'] = REQUEST_SECONDS
    if 'latency_censored' in attempt and attempt['latency_censored'] != row['latency_censored']:
        raise ValueError('Censor flag disagrees with observed status')
    # Keep caller-recorded run identities and actual worker settings in the raw
    # export; they are evidence, not inferred from observed overlap or latency.
    row.update({key: value for key, value in attempt.items() if key not in row})
    return row


def _point(rows, scan, x, method, query, expected_endpoints):
    present = {row['repetition'] for row in rows}
    complete = present == set(REPETITIONS)
    point = dict(scan_name=scan, x_value=x, method=method, query_id=query, complete=complete,
        attempts_observed=len(rows), missing_repetitions=[r for r in REPETITIONS if r not in present],
        success_count=sum(row['status'] == 'answered' for row in rows),
        failed_count=sum(row['status'] == 'failed' for row in rows),
        timeout_count=sum(row['status'] == 'timeout' for row in rows),
        censored_count=sum(row['latency_censored'] for row in rows),
        expected_endpoints=expected_endpoints,
        endpoint_count_match=complete and all(row['endpoints_actual'] == expected_endpoints for row in rows))
    point.update(_plan_counts(rows))
    point.update(_hardware_counts(rows))
    for metric in METRICS:
        values = [row[metric] for row in rows if row[metric] is not None]
        point[metric+'_valid_n'] = len(values)
        # Do not silently compute a success-only or partially observed median.
        point[metric+'_median'] = statistics.median(values) if complete and len(values) == 3 else None
    return point


def _valid_hash(value):
    return (isinstance(value, str) and len(value) == 64
            and all(character in '0123456789abcdef' for character in value))


def _plan_counts(rows):
    audit = [row.get('selected_dag_sha256') for row in rows]
    execution = [row.get('execution_plan_sha256')
                 if row.get('execution_plan_fingerprint_schema') == PLAN_SCHEMA else None
                 for row in rows]
    known_audit = sorted({value for value in audit if _valid_hash(value)})
    known_execution = sorted({value for value in execution if _valid_hash(value)})
    return dict(selected_dag_distinct_count=len(known_audit),
        selected_dag_unknown_count=sum(not _valid_hash(value) for value in audit),
        selected_dag_sha256_values=known_audit,
        execution_plan_distinct_count=len(known_execution),
        execution_plan_unknown_count=sum(not _valid_hash(value) for value in execution),
        execution_plan_sha256_values=known_execution,
        plan_variation_observed=len(known_audit) > 1 or len(known_execution) > 1)


def _plan_comparability(first, last):
    """Same executable plan on all six attempts, never guessed from old pins."""
    result = dict(available=False, reason=None, execution_plan_sha256=None,
                  required_repetitions_per_point=3, fingerprint_schema=PLAN_SCHEMA)
    if first is None or last is None:
        result['reason'] = 'required_levels_not_configured'
    elif not first['complete'] or not last['complete']:
        result['reason'] = 'incomplete_repetitions'
    elif first['execution_plan_unknown_count'] or last['execution_plan_unknown_count']:
        result['reason'] = 'execution_fingerprint_unavailable'
    else:
        hashes = set(first['execution_plan_sha256_values'] + last['execution_plan_sha256_values'])
        if len(hashes) != 1:
            result['reason'] = 'execution_plan_varies_across_workers_or_repeats'
        else:
            result.update(available=True, execution_plan_sha256=next(iter(hashes)))
    return result


def _hardware_counts(rows):
    """Use observed provenance only; scheduler feature names are not CPU models."""
    provenance = [row.get('measurement_provenance') for row in rows]
    provenance = [value if isinstance(value, dict) else {} for value in provenance]
    valid = lambda value: isinstance(value, str) and bool(value.strip())
    nodes = [value.get('node') for value in provenance]
    jobs = [value.get('job_id') for value in provenance]
    known_nodes = sorted({value for value in nodes if valid(value)})
    known_jobs = sorted({value for value in jobs if valid(value)})
    return dict(observed_nodes=known_nodes, observed_job_ids=known_jobs,
        node_unknown_count=sum(not valid(value) for value in nodes),
        allocation_unknown_count=sum(not valid(value) for value in jobs),
        hardware_boundary_observed=len(known_nodes) > 1 or len(known_jobs) > 1)


def _hardware_comparability(first, last):
    result = dict(available=False, reason=None, observed_nodes=[], observed_job_ids=[],
        node_unknown_count=0, allocation_unknown_count=0, physical_node_changed=False,
        allocation_changed=False, required_repetitions_per_point=3)
    points = [point for point in (first, last) if point is not None]
    result.update(observed_nodes=sorted({node for point in points for node in point['observed_nodes']}),
        observed_job_ids=sorted({job for point in points for job in point['observed_job_ids']}),
        node_unknown_count=sum(point['node_unknown_count'] for point in points),
        allocation_unknown_count=sum(point['allocation_unknown_count'] for point in points))
    result['physical_node_changed'] = len(result['observed_nodes']) > 1
    result['allocation_changed'] = len(result['observed_job_ids']) > 1
    if first is None or last is None:
        result['reason'] = 'required_levels_not_configured'
    elif not first['complete'] or not last['complete']:
        result['reason'] = 'incomplete_repetitions'
    elif result['node_unknown_count']:
        result['reason'] = 'physical_node_provenance_unavailable'
    elif result['allocation_unknown_count']:
        result['reason'] = 'allocation_provenance_unavailable'
    elif result['physical_node_changed']:
        result['reason'] = 'physical_node_varies_across_workers_or_repeats'
    elif result['allocation_changed']:
        result['reason'] = 'allocation_varies_across_workers_or_repeats'
    else:
        result['available'] = True
    return result


def _pure_executor_comparison(first, last):
    comparison = _comparison(first, last, 'execution_ms')
    comparability = _plan_comparability(first, last)
    reason = None
    if not comparability['available']:
        reason = comparability['reason']
    elif first['success_count'] != 3 or last['success_count'] != 3:
        reason = 'failed_execution_not_comparable'
    elif not comparison['hardware_comparability']['available']:
        reason = comparison['hardware_comparability']['reason']
    if reason:
        comparison.update(available=False, reason=reason, first_value=None, last_value=None,
            ratio_last_over_first=None, additive_difference=None, log_log_slope=None)
    return dict(comparison, plan_comparability=comparability,
                speedup=(1/comparison['ratio_last_over_first'] if comparison['available'] else None),
                scope='Same-plan execution-phase comparison on one observed physical node and one job allocation; source/cache conditions remain governed by the run manifest')


def _quantiles(values):
    """Linear empirical quantiles: position (n-1)*p; singleton stays observed."""
    ordered = sorted(values)
    result = dict(valid_n=len(ordered))
    for label, p in (('p25', .25), ('p50', .5), ('p75', .75)):
        if not ordered:
            result[label] = None
        else:
            position = (len(ordered)-1)*p; lower = math.floor(position); upper = math.ceil(position)
            result[label] = ordered[lower]+(ordered[upper]-ordered[lower])*(position-lower)
    return result


def _phase_fractions(rows):
    valid = [row for row in rows if not row['latency_censored']
             and row['request_latency_s'] is not None and row['request_latency_s'] > 0
             and row['planning_wall_ms'] is not None and row['execution_ms'] is not None]
    denominator_ms = sum(row['request_latency_s']*1000 for row in valid)
    eligible = [row for row in rows if not row['latency_censored']
                and row['request_latency_s'] is not None and row['request_latency_s'] > 0]
    ratio_quantiles = {phase: _quantiles([row[phase]/(1000*row['request_latency_s'])
        for row in eligible if row[phase] is not None]) for phase in ('planning_wall_ms', 'execution_ms')}
    return dict(attempts_total=len(rows), valid_phase_n=len(valid),
        censored_excluded_n=sum(row['latency_censored'] for row in rows),
        other_missing_phase_n=len(rows)-len(valid)-sum(row['latency_censored'] for row in rows),
        measured_request_ms_denominator=denominator_ms,
        planning_wall_fraction=(sum(row['planning_wall_ms'] for row in valid)/denominator_ms if valid else None),
        execution_fraction=(sum(row['execution_ms'] for row in valid)/denominator_ms if valid else None),
        ratio_quantiles=ratio_quantiles,
        quantile_definition='Per-attempt measured phase/request wall-time ratios; each phase uses its own valid_n; linear quantiles at (n-1)*p; timeout attempts excluded',
        definition='Ratios of summed measured phase time to summed request time on the same uncensored attempts; not CPU fractions')


def _comparison(first, last, metric):
    result = dict(metric=metric, available=False, reason=None,
        first_x=first['x_value'] if first else None, last_x=last['x_value'] if last else None,
        first_value=None, last_value=None, ratio_last_over_first=None, additive_difference=None,
        log_log_slope=None, hardware_comparability=_hardware_comparability(first, last),
        interpretation='Descriptive observed ratio; hardware or allocation differences are separate factors, not an isolated X-factor effect')
    if first is None or last is None:
        result['reason'] = 'required_levels_not_configured'
    elif not first['complete'] or not last['complete']:
        result['reason'] = 'incomplete_repetitions'
    elif not first['endpoint_count_match'] or not last['endpoint_count_match']:
        result['reason'] = 'actual_endpoint_count_not_confirmed'
    elif first['censored_count'] or last['censored_count']:
        result['reason'] = 'censored_point_not_an_uncensored_scaling_claim'
    elif metric in ('request_latency_s', 'execution_ms') and (first['failed_count'] or last['failed_count']):
        result['reason'] = 'failed_request_not_a_successful_latency_comparison'
    else:
        a, b = first[metric+'_median'], last[metric+'_median']
        if a is None or b is None:
            result['reason'] = 'metric_missing_in_one_or_more_attempts'
        elif a <= 0 or b <= 0:
            result['reason'] = 'nonpositive_metric_ratio_undefined'
        else:
            result.update(available=True, first_value=a, last_value=b,
                ratio_last_over_first=b/a, additive_difference=b-a,
                log_log_slope=math.log(b/a)/math.log(last['x_value']/first['x_value']))
    return result


def _failure_note(row):
    """Retain reported diagnostics without turning them into inferred causes."""
    keys = ('error_type', 'error', 'failure_phase', 'worker_status', 'worker_failures',
            'observation_error', 'observation_failure_categories', 'closure_error')
    evidence = {key: row[key] for key in keys if row.get(key) not in (None, '', [], {})}
    guard = row.get('guard')
    if isinstance(guard, dict):
        fields = {key: guard[key] for key in ('status', 'decision_status', 'exit_code', 'error')
                  if guard.get(key) is not None}
        if fields:
            evidence['guard'] = fields
    if row['hard_deadline_observed']:
        evidence['hard_request_deadline_seconds'] = REQUEST_SECONDS
    if row.get('answer_em') == 0:
        evidence['answer_em'] = 0
    return {**{key: row[key] for key in ('scan_name', 'x_value', 'method', 'query_id', 'repetition', 'status')},
            'reported_evidence': evidence or None,
            'reason': 'Reported diagnostics below; no unobserved cause inferred' if evidence else 'Reason unavailable in observed attempt'}


def summarize_attempts(attempts, *, endpoint_levels, worker_levels=(1, 2, 4, 8, 16), worker_scan_endpoints=32,
                       methods=METHODS, deployment_metadata=None):
    """Return raw rows, configured summary points and evidence-limited notes.

    Endpoint levels are supplied by the frozen deployment manifest. Scan B
    defaults to 32 endpoints; scan A fixes configured execution workers at four.
    ``endpoints_actual`` is the deployed count, whereas
    ``shards_touched`` is an observed access count. An answered status means the
    method returned an answer, not that a separate gold comparison passed.
    Each observed row must name its method explicitly. A deliberately restricted
    older batch can set ``methods=('XGAP',)``; absent methods are never inferred.
    """
    levels = dict(A_endpoints=_levels(endpoint_levels, 'endpoints'), B_workers=_levels(worker_levels, 'workers'))
    methods = tuple(methods)
    if not methods or len(set(methods)) != len(methods) or any(method not in METHODS for method in methods):
        raise ValueError('Configured methods must be distinct members of XGAP, NP, SH, GR')
    if deployment_metadata is not None:
        if not isinstance(deployment_metadata, dict):
            raise ValueError('Deployment metadata must be an explicit JSON object or null')
        # Preserve supplied layout/cross-edge evidence; never use it to invent
        # observed endpoint/call counts or fill missing raw measurements.
        deployment_metadata = json.loads(json.dumps(deployment_metadata, allow_nan=False))
    if type(worker_scan_endpoints) is not int or not 1 <= worker_scan_endpoints <= 32:
        raise ValueError('Explicit worker-scan endpoint count required')
    raw = []; seen = set()
    for attempt in attempts:
        row = _normalize(attempt, levels, methods)
        key = tuple(row[field] for field in ('scan_name', 'x_value', 'method', 'query_id', 'repetition'))
        if key in seen:
            raise ValueError('Duplicate observed attempt; never select a retry or overwrite an outcome')
        seen.add(key); raw.append(row)
    raw.sort(key=lambda row: (SCANS.index(row['scan_name']), row['x_value'], methods.index(row['method']), row['query_id'], row['repetition']))
    summary = []; phases = []
    for scan in SCANS:
        for x in levels[scan]:
            for method in methods:
                for query in QUERIES:
                    rows = [row for row in raw if (row['scan_name'], row['x_value'], row['method'], row['query_id']) == (scan, x, method, query)]
                    summary.append(_point(rows, scan, x, method, query, x if scan == 'A_endpoints' else worker_scan_endpoints))
                    phases.append(dict(scan_name=scan, x_value=x, method=method, query_id=query, **_phase_fractions(rows)))
    points = {(p['scan_name'], p['x_value'], p['method'], p['query_id']): p for p in summary}
    endpoint_scaling = []; worker_scaling = []; phase_groups = []
    for method in methods:
        for query in QUERIES:
            for scan in SCANS:
                rows = [row for row in raw if (row['scan_name'], row['method'], row['query_id']) == (scan, method, query)]
                phase_groups.append(dict(scan_name=scan, method=method, query_id=query, **_phase_fractions(rows)))
            for metric in ('request_latency_s', 'backend_calls', 'realized_cost'):
                endpoint_scaling.append(dict(method=method, query_id=query, **_comparison(
                    points.get(('A_endpoints', 4, method, query)), points.get(('A_endpoints', 32, method, query)), metric)))
            first, last = points.get(('B_workers', 1, method, query)), points.get(('B_workers', 16, method, query))
            comparison = _comparison(first, last, 'request_latency_s')
            adjacent = []
            for a, b in zip(levels['B_workers'], levels['B_workers'][1:]):
                left, right = points['B_workers', a, method, query], points['B_workers', b, method, query]
                pair = _comparison(left, right, 'request_latency_s')
                adjacent.append(dict(pair, speedup=(1/pair['ratio_last_over_first'] if pair['available'] else None),
                    fractional_latency_gain=(1-pair['ratio_last_over_first'] if pair['available'] else None),
                    plan_comparability=_plan_comparability(left, right),
                    pure_executor_comparison=_pure_executor_comparison(left, right)))
            worker_scaling.append(dict(method=method, query_id=query, comparison_1_to_16=comparison,
                speedup_1_to_16=(1/comparison['ratio_last_over_first'] if comparison['available'] else None),
                comparison_scope='end_to_end_configuration_effect_with_fresh_planning',
                plan_comparability_1_to_16=_plan_comparability(first, last),
                pure_executor_comparison_1_to_16=_pure_executor_comparison(first, last),
                adjacent_gains=adjacent, saturation_selected=False))
    notes = dict(schema_version=SCHEMA, request_timeout_seconds=REQUEST_SECONDS,
        configured_levels=levels, endpoint_scan_workers=4, worker_scan_endpoints=worker_scan_endpoints,
        methods=list(methods), unsupported_methods={'TS': 'unsupported_mixed_native_rdf_deployment'},
        queries=list(QUERIES), repetitions=list(REPETITIONS), deployment_metadata=deployment_metadata,
        raw_attempts=len(raw), complete_points=sum(p['complete'] for p in summary), total_configured_points=len(summary),
        latency_policy='Only explicitly observed hard deadlines are clipped to 600 seconds; all timeout observations are censored; raw observed latency is retained',
        median_policy='All three repetitions, including failed and timeout attempts; a metric median is null unless all three values are known',
        status_policy='Success count means answered, not answer correctness; failures are retained; missing attempts are never generated',
        resource_policy='CPU, calls, cost, RSS and touched-source counts are never extrapolated or zero-filled',
        plan_policy='Fresh planning remains inside every request. Plan variation is observed behavior, not a reason to discard an attempt or abort scan A. Original selected-DAG identities are retained; missing execution fingerprints stay unknown',
        worker_comparison_policy='Worker request-latency ratios describe end-to-end configuration effects with fresh planning, not pure executor speedup. Execution-phase attribution requires one identical known execution fingerprint across all three repetitions at both compared levels, as well as complete uncensored execution measurements',
        hardware_policy='All raw outcomes and medians are preserved across recovery allocations. Every comparison reports observed physical nodes and job allocations; pure-executor speedup additionally requires one known physical node and one known job allocation across all six attempts. The icosa256gb scheduler feature does not establish an identical CPU model; actual allocation lscpu records remain the hardware evidence',
        execution_fingerprint_schema=PLAN_SCHEMA,
        execution_fingerprint_exclusions=list(EXCLUSIONS),
        plan_points=[{key: value for key, value in p.items() if key in (
            'scan_name', 'x_value', 'method', 'query_id', 'complete', 'attempts_observed',
            'selected_dag_distinct_count', 'selected_dag_unknown_count', 'selected_dag_sha256_values',
            'execution_plan_distinct_count', 'execution_plan_unknown_count', 'execution_plan_sha256_values',
            'plan_variation_observed')} for p in summary],
        hardware_points=[{key: value for key, value in p.items() if key in (
            'scan_name', 'x_value', 'method', 'query_id', 'complete', 'attempts_observed',
            'observed_nodes', 'observed_job_ids', 'node_unknown_count',
            'allocation_unknown_count', 'hardware_boundary_observed')} for p in summary],
        phase_fractions=phases, phase_fraction_groups=phase_groups,
        failures=[_failure_note(row) for row in raw if row['status'] != 'answered' or row.get('answer_em') == 0],
        endpoint_scaling_4_to_32=endpoint_scaling, worker_scaling=worker_scaling,
        saturation_policy='No saturation point is selected without a separately declared criterion; negative adjacent gains remain negative',
        claim_boundary='Calibration summaries only; varying-query, deployment and hardware comparability must be enforced by the frozen run manifest')
    return dict(schema_version=SCHEMA, raw=raw, summary=summary, notes=notes)


def _markdown_notes(notes):
    def cell(value):
        if value is None:
            return 'unknown'
        text = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (list, dict)) else str(value)
        return html.escape(text, quote=False).replace('|', '\\|').replace('\r\n', '\n').replace('\r', '\n').replace('\n', '<br>')
    def number(value):
        return 'unknown' if value is None else f'{value:.6g}'
    def quantiles(row, phase):
        quantile = row['ratio_quantiles'][phase]
        return ' / '.join(number(quantile[key]) for key in ('p25', 'p50', 'p75'))
    lines = ['# Observed scalability summary', '',
        f"Observed attempts: {notes['raw_attempts']}; complete points: {notes['complete_points']}/{notes['total_configured_points']}.", '',
        'Methods: '+', '.join(notes['methods'])+'. TS is unsupported for this mixed Neo4j/RDF deployment; no TS measurements are generated.', '',
        notes['latency_policy']+'.', '', notes['median_policy']+'.', '', notes['status_policy']+'.', '',
        notes['resource_policy']+'.', '', notes['plan_policy']+'.', '', notes['worker_comparison_policy']+'.', '',
        notes['hardware_policy']+'.', '',
        notes['saturation_policy']+'.', '', notes['claim_boundary']+'.', '',
        '## Actual deployment metadata', '',
        'Values below are supplied deployment evidence. Unknown fields stay unknown; the configured level alone is not proof of actual deployment.', '',
        '| Layout | Actual endpoints | Neo4j | Fuseki | Atoms per endpoint | Cross-endpoint edges | Actual source groups |',
        '| --- | ---: | ---: | ---: | ---: | ---: | --- |']
    deployment = notes.get('deployment_metadata') or {}
    layouts = deployment.get('layouts', deployment)
    deployment_rows = [(key, value) for key, value in layouts.items() if isinstance(value, dict)] if isinstance(layouts, dict) else []
    for key, value in sorted(deployment_rows, key=lambda pair: str(pair[0])):
        groups = value.get('source_groups')
        groups_text = ('; '.join(str(group.get('source_id', 'unknown'))+' ('+
            str(group.get('engine', 'unknown'))+'): atoms '+str(group.get('atoms', 'unknown'))
            for group in groups) if isinstance(groups, list) and all(isinstance(group, dict) for group in groups) else groups)
        fields = (key, value.get('endpoints_actual', value.get('actual_sources')), value.get('neo4j'),
                  value.get('fuseki'), value.get('atoms_per_endpoint'), value.get('cross_endpoint_edges'), groups_text)
        lines.append('| '+' | '.join(cell(value) for value in fields)+' |')
    if not deployment_rows:
        lines.extend(['', 'No per-layout deployment metadata was provided.'])
    if 'logical_edges' in deployment:
        lines.extend(['', 'Supplied graph logical edges: '+cell(deployment['logical_edges'])+'.'])
    lines.extend(['', '## Failed, timeout, or incorrect-answer observations', '',
        'All observed attempts remain in the raw CSVs. These rows report recorded diagnostics, not an inferred root cause.', '',
        '| Scan | X | Method | Query | Repetition | Status | Reason / observed diagnostics |',
        '| --- | ---: | --- | --- | ---: | --- | --- |'])
    for failure in notes['failures']:
        evidence = failure['reported_evidence']
        reason = ('; '.join(key+': '+(json.dumps(value, ensure_ascii=False, sort_keys=True)
            if isinstance(value, (list, dict)) else str(value)) for key, value in evidence.items())
            if evidence is not None else failure['reason'])
        fields = [failure[key] for key in ('scan_name', 'x_value', 'method', 'query_id', 'repetition', 'status')]
        lines.append('| '+' | '.join(cell(value) for value in [*fields, reason])+' |')
    if not notes['failures']:
        lines.extend(['', 'No failed, timeout, or incorrect-answer status was recorded among the observed attempts.'])
    lines.extend(['', '## Measured phase/request fractions', '',
        'Values are p25 / p50 / p75 of per-attempt wall-time fractions. Each phase has its own valid n; timeout attempts are excluded. '+
        'Quantiles use linear interpolation at (n−1)p. Rows pool configured x levels within the same scan, method and query. '+
        'Per-point values and measured denominators remain in notes.json.', '',
        '| Scan | Method | Query | Attempts | Censored | Planning n | Planning p25 / p50 / p75 | Execution n | Execution p25 / p50 / p75 |',
        '| --- | --- | --- | ---: | ---: | ---: | --- | ---: | --- |'])
    for row in notes['phase_fraction_groups']:
        if row['attempts_total']:
            p, e = row['ratio_quantiles']['planning_wall_ms'], row['ratio_quantiles']['execution_ms']
            lines.append(f"| {row['scan_name']} | {row['method']} | {row['query_id']} | {row['attempts_total']} | {row['censored_excluded_n']} | {p['valid_n']} | {quantiles(row,'planning_wall_ms')} | {e['valid_n']} | {quantiles(row,'execution_ms')} |")
    lines.extend(['', '## Endpoint scaling from 4 to 32', '',
        'These descriptive ratios require complete uncensored points with confirmed endpoint counts. Node/allocation boundaries are retained separately and prevent an isolated endpoint-count attribution.', '',
        '| Method | Query | Metric | 32/4 ratio | Additive difference | Log-log slope | Availability |',
        '| --- | --- | --- | ---: | ---: | ---: | --- |'])
    for row in notes['endpoint_scaling_4_to_32']:
        lines.append(f"| {row['method']} | {row['query_id']} | {row['metric']} | {number(row['ratio_last_over_first'])} | {number(row['additive_difference'])} | {number(row['log_log_slope'])} | {row['reason'] or 'available'} |")
    lines.extend(['', '## Observed plan identities', '',
        'Counts include every observed repetition. Execution fingerprints are not inferred from legacy audit pins. A nonzero unknown count prevents same-plan attribution.', '',
        '| Scan | X | Method | Query | Attempts | Audit variants | Unknown audit | Execution variants | Unknown execution |',
        '| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |'])
    for row in notes['plan_points']:
        if row['attempts_observed']:
            fields = [row[key] for key in ('scan_name', 'x_value', 'method', 'query_id', 'attempts_observed',
                'selected_dag_distinct_count', 'selected_dag_unknown_count',
                'execution_plan_distinct_count', 'execution_plan_unknown_count')]
            lines.append('| '+' | '.join(cell(value) for value in fields)+' |')
    lines.extend(['', '## Observed hardware and allocation boundaries', '',
        'Unknown provenance remains unknown. Matching scheduler feature names alone do not establish matching CPU models.', '',
        '| Scan | X | Method | Query | Observed nodes | Observed jobs | Unknown node | Unknown allocation |',
        '| --- | ---: | --- | --- | --- | --- | ---: | ---: |'])
    for row in notes['hardware_points']:
        if row['attempts_observed']:
            fields = [row[key] for key in ('scan_name', 'x_value', 'method', 'query_id',
                'observed_nodes', 'observed_job_ids', 'node_unknown_count', 'allocation_unknown_count')]
            lines.append('| '+' | '.join(cell(value) for value in fields)+' |')
    lines.extend(['', '## Worker scaling at 32 endpoints', '',
        'Request ratios retain fresh planning. The separate execution-phase column also requires a single known physical node and job allocation, with matching known plans across all six attempts. Hardware and allocation boundaries remain explicit in notes.json.', '',
        '| Method | Query | End-to-end 1-to-16 ratio (latency at 1 / latency at 16) | E2E availability | Same-plan execution-phase speedup | Execution attribution availability |',
        '| --- | --- | ---: | --- | ---: | --- |'])
    for row in notes['worker_scaling']:
        pure = row['pure_executor_comparison_1_to_16']
        lines.append(f"| {row['method']} | {row['query_id']} | {number(row['speedup_1_to_16'])} | {row['comparison_1_to_16']['reason'] or 'available'} | {number(pure['speedup'])} | {pure['reason'] or 'available'} |")
    lines.extend(['', 'Adjacent worker gains, including slowdowns, are retained in notes.json. No saturation point is selected.', ''])
    return '\n'.join(lines)


def write_results(attempts, output, **configuration):
    """Write four CSV files plus JSON/Markdown notes into a new directory."""
    result = summarize_attempts(attempts, **configuration)
    if not result['raw']:
        raise ValueError('No observed attempts; no result files are created')
    root = Path(output); root.mkdir(parents=True, exist_ok=False)
    extra_fields = sorted(set().union(*(set(row) for row in result['raw']))-set(RAW_FIELDS))
    for scan in SCANS:
        for kind, fields in (('raw', (*RAW_FIELDS, *extra_fields)), ('summary', SUMMARY_FIELDS)):
            with (root/OUTPUT_NAMES[scan][kind]).open('x', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
                for row in result[kind]:
                    if row['scan_name'] != scan:
                        continue
                    writer.writerow({k: json.dumps(row.get(k), sort_keys=True, allow_nan=False)
                        if isinstance(row.get(k), (list, dict)) else row.get(k) for k in fields})
    (root/'notes.json').write_text(json.dumps(result['notes'], indent=2, sort_keys=True)+'\n')
    (root/'scalability_notes.md').write_text(_markdown_notes(result['notes']))
    files = []
    for path in sorted(root.iterdir()):
        body = path.read_bytes(); files.append(dict(path=str(path.resolve()), bytes=len(body), sha256=hashlib.sha256(body).hexdigest()))
    return dict(schema_version=SCHEMA, files=files, raw_attempts=len(result['raw']), model_calls=0, backend_calls=0)
