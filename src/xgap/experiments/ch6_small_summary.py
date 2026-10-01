"""Actual small-study records only; missing values remain missing, no scaling."""
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re
import statistics

from xgap.experiments.ch6_formal_protocol import METHODS
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once

SCHEMA = 'xgap-ch6-small-actual-summary-v1'
TOTALS = ('model_calls', 'input_tokens', 'output_tokens', 'backend_calls',
          'backend_forwarded_calls', 'transferred_bytes', 'clarification_calls',
          'probe_calls', 'planning_cpu_ms', 'method_cpu_seconds', 'source_cpu_seconds')
MEANS = ('decision_e2e_ms', 'planning_ms', 'planning_cpu_ms', 'execution_ms',
         'answer_em', 'answer_f1', 'input_tokens', 'output_tokens', 'model_calls',
         'backend_calls', 'backend_forwarded_calls', 'transferred_bytes', 'probe_calls',
         'clarification_calls', 'method_cpu_seconds', 'source_cpu_seconds',
         'method_peak_rss_bytes', 'source_peak_rss_bytes')
GROUPS = {
    'overall': (),
    'detail': ('dataset', 'deployment', 'frame', 'workload', 'method'),
    'dataset_method': ('dataset', 'method'),
    'deployment_method': ('dataset', 'deployment', 'method'),
    'frame_method': ('dataset', 'frame', 'method'),
    'workload_method': ('dataset', 'workload', 'method'),
}


class Reader:
    def __init__(self, root, original_prefix=None):
        self.root = Path(root).resolve()
        self.original_prefix = Path(original_prefix) if original_prefix else None

    def load(self, pin):
        path = Path(pin['path'])
        if self.original_prefix is not None and path.is_relative_to(self.original_prefix):
            path = self.root / path.relative_to(self.original_prefix)
        return json.loads(read_pinned(path, pin['sha256']))


def extract_cell(metadata, directory, reader):
    """Sealed receipt + independent score; never open private intent or query."""
    row = dict(metadata)
    row.update({k: None for k in set(TOTALS) | set(MEANS)})
    row.update(status='unattempted', observation='unattempted', answer_returned=None,
               outcome_sha256=None, score_sha256=None, timing_scope=None)
    if metadata['support'] != 'supported':
        row.update(status=metadata['support'], observation='unsupported')
        return row
    terminal_path = directory / 'terminal.json'
    if not terminal_path.exists():
        if directory.exists():
            row.update(status='unsealed_attempt', observation='unsealed')
        return row
    terminal = json.loads(terminal_path.read_text())
    if terminal['cell_id'] != metadata['cell_id']:
        raise ValueError('Terminal cell identity differs')
    trial, score = reader.load(terminal['outcome']), reader.load(terminal['score'])
    if (score['receipt_sha256'] != terminal['outcome']['sha256']
            or trial['method'] != METHODS[metadata['method']]
            or trial['question_id'] != metadata['case_id']):
        raise ValueError('Outcome/score identity differs from the declared cell')
    harness = trial.get('harness_failures') or {}
    censored = (bool(score.get('comparison_error'))
        or trial.get('failure_scope') == 'study_budget_censoring_not_method_incorrectness'
        or bool(harness) or trial['status'] in (
            'harness_observation_failure', 'study_budget_censored', 'supervisor_failed', 'guard_monitor_failed'))
    returned = bool(trial['success'] and not score.get('comparison_error'))
    observation = ('study_censored' if censored else 'answered_correct' if returned and score['answer_em'] == 1
                   else 'answered_incorrect' if returned else 'method_failure')
    row.update(status=trial['status'], observation=observation,
        outcome_sha256=terminal['outcome']['sha256'], score_sha256=terminal['score']['sha256'],
        answer_returned=None if censored else returned,
        answer_em=None if censored else score.get('answer_em'),
        answer_f1=None if censored else score.get('answer_row_multiset_f1'),
        decision_e2e_ms=trial.get('decision_e2e_ms'),
        timing_scope='outer entry through durable outcome; scoring/final telemetry excluded',
        failure_scope=trial.get('failure_scope'))
    for metric in ('planning_ms', 'planning_cpu_ms', 'execution_ms', 'model_calls',
                   'input_tokens', 'output_tokens', 'clarification_calls', 'probe_calls'):
        row[metric] = trial.get(metric)
    source = trial.get('source_observations') or (trial.get('observations') or {}).get('source') or {}
    row['backend_calls'] = source.get('requests')
    row['backend_forwarded_calls'] = source.get('forwarded_requests')
    fields = ('request_body_bytes', 'request_target_bytes', 'response_body_bytes')
    if all(source.get(k) is not None for k in fields):
        row['transferred_bytes'] = sum(source[k] for k in fields)
    resources = trial.get('resources') or {}
    for role in ('method', 'source'):
        row[role + '_peak_rss_bytes'] = (resources.get('sampled_peak_rss_bytes') or {}).get(role)
        row[role + '_cpu_seconds'] = (resources.get('sampled_cpu_seconds') or {}).get(role)
    return row


def summarize_rows(rows, *, expected_membership_known):
    summaries = []
    for level, axes in GROUPS.items():
        groups = defaultdict(list)
        for row in rows:
            groups[tuple(row[k] for k in axes)].append(row)
        for key, items in sorted(groups.items()):
            states = Counter(r['observation'] for r in items)
            supported = [r for r in items if r['support'] == 'supported']
            attempted = [r for r in supported if r['observation'] not in ('unattempted', 'unsupported')]
            sealed = [r for r in attempted if r['observation'] != 'unsealed']
            completed = [r for r in sealed if r['answer_returned'] is True]
            scorable = [r for r in sealed if r['answer_em'] is not None]
            out = dict(zip(axes, key), group_level=level,
                expected_supported=len(supported) if expected_membership_known else None,
                observed_sealed=len(sealed), attempted=len(attempted), completed=len(completed),
                correct=states['answered_correct'], wrong_answers=states['answered_incorrect'],
                method_failures=states['method_failure'], study_censored=states['study_censored'],
                unsealed=states['unsealed'], unsupported=states['unsupported'],
                unattempted=states['unattempted'] if expected_membership_known else None,
                coverage_over_expected=len(completed) / len(supported)
                    if expected_membership_known and supported else None,
                coverage_over_observed_scorable=len(completed) / len(scorable) if scorable else None,
                answer_scoring_denominator=len(scorable), expected_membership_known=expected_membership_known,
                fully_observed=expected_membership_known and len(sealed) == len(supported),
                totals_scope='all attempted requests, including failures and censoring; missing stays null')
            for metric in MEANS:
                population = completed if metric == 'decision_e2e_ms' else sealed
                values = [r[metric] for r in population if r[metric] is not None]
                out[metric + '_mean'] = statistics.mean(values) if values else None
                out[metric + '_n'] = len(values)
                out[metric + '_missing'] = len(population) - len(values)
            all_latency = [r['decision_e2e_ms'] for r in sealed if r['decision_e2e_ms'] is not None]
            out['all_attempt_decision_e2e_ms_mean'] = statistics.mean(all_latency) if all_latency else None
            out['all_attempt_decision_e2e_ms_n'] = len(all_latency)
            for metric in TOTALS:
                values = [r[metric] for r in attempted if r[metric] is not None]
                out[metric + '_observed_sum'] = sum(values) if values else None
                out[metric + '_total_complete'] = bool(attempted) and len(values) == len(attempted)
                out[metric + '_total'] = sum(values) if out[metric + '_total_complete'] else None
                out[metric + '_missing_attempts'] = len(attempted) - len(values)
            for role in ('method', 'source'):
                metric = role + '_peak_rss_bytes'
                values = [r[metric] for r in sealed if r[metric] is not None]
                out[metric + '_max'] = max(values) if values else None
            summaries.append(out)
    return summaries


def _csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open('x', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def summarize(*, evidence_root, output, release_pin=None, original_prefix=None):
    root = Path(evidence_root).resolve(); reader = Reader(root, original_prefix)
    rows = []
    if release_pin:
        release = reader.load(release_pin)
        if release['schema_version'] != 'xgap-ch6-small-real-release-v1':
            raise ValueError('An explicit small-real release is required')
        selection = reader.load(release['selection'])
        cases = {(c['dataset'], c['deployment']): c for c in selection['cohorts']}
        for unit in release['units']:
            cohort = cases[(unit['dataset'], unit['deployment'])]
            manifest = reader.load(unit['manifest'])
            cells = {(unit['cell_cases'][c['cell_id']], c['method']): c for c in manifest['cells']}
            for case in cohort['cases']:
                for label, method in METHODS.items():
                    cell = cells.get((case['case_id'], method))
                    support = 'unsupported_deployment' if label == 'TS' and unit['deployment'] == 'native' else 'supported'
                    if support == 'supported' and cell is None:
                        raise ValueError('A supported selected cell is absent from its manifest')
                    cid = cell['cell_id'] if cell else case['case_id'] + '-' + label
                    metadata = dict(dataset=unit['dataset'], deployment=unit['deployment'], frame=case['stratum'],
                        workload=case['workload'], method=label, case_id=case['case_id'], cell_id=cid, support=support)
                    rows.append(extract_cell(metadata, root / 'units' / unit['unit_id'] / 'cells' / cid, reader))
        scope = dict(purpose=release['purpose'], exposure=release['exposure'],
            full_800_claim=False, heldout_claim=release['heldout_claim'], release=release_pin)
    else:
        # Archive validation is deliberately observation-only: no invented
        # denominator or claim that missing cells were part of this extraction.
        for terminal_path in sorted(root.glob('**/cells/*/terminal.json')):
            terminal = json.loads(terminal_path.read_text()); trial = reader.load(terminal['outcome'])
            qid = trial['question_id']
            match = re.fullmatch(r'(D[123])-test-(uniform|active-anchor)-(.+)-(W[1234])', qid)
            if not match:
                raise ValueError('Observed-only case requires explicit dataset/frame/workload identity')
            unit = terminal_path.parent.parent.parent.name
            deployment = 'native' if '-native-' in unit else 'rdf' if '-rdf-' in unit else None
            if deployment is None: raise ValueError('Unknown observed deployment')
            label = next(k for k, v in METHODS.items() if v == trial['method'])
            metadata = dict(dataset=match[1], deployment=deployment, frame=match[2], workload=match[4],
                method=label, case_id=qid, cell_id=terminal['cell_id'], support='supported')
            rows.append(extract_cell(metadata, terminal_path.parent, reader))
        scope = dict(purpose='observed_archive_diagnostic', exposure='incomplete_development_pilot',
                     full_800_claim=False, heldout_claim=False, release=None)
    if not rows: raise ValueError('No selected or observed cells')
    summaries = summarize_rows(rows, expected_membership_known=bool(release_pin))
    out = Path(output).resolve(); out.mkdir(parents=True, exist_ok=False)
    _csv(out / 'actual-cells.csv', rows); _csv(out / 'actual-groups.csv', summaries)
    receipt = dict(schema_version=SCHEMA, scope=scope, evidence_root=str(root), original_prefix=original_prefix,
        cells=len(rows), observations=dict(Counter(r['observation'] for r in rows)), groups=summaries,
        missing_policy='null/blank, never zero imputation; observed sums identify missing attempts',
        traffic_policy='observed source HTTP request/response bodies plus request targets; not all network traffic',
        latency_policy='completed returned-answer mean plus explicit coverage; all-attempt mean separately',
        memory_policy='per-request sampled peak mean/max; never sum or scale peak RSS',
        aggregation_policy='one declared small-study repetition; no extrapolation or simulated values',
        model_calls=0, backend_calls=0)
    pin = write_once(out / 'summary.json', receipt)
    return dict(summary=pin, observations=receipt['observations'], model_calls=0, backend_calls=0)
