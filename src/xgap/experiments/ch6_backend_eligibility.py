"""Evaluation eligibility is distinct from all-query success.

A new certificate covers the whole frozen cohort using audited, closed segments
from ONE source revision. Only typed resource cuts may remain. It cannot turn
wrong/unknown answers into success, release a diagnostic subset, or select cases.
Old strict admission receipts retain their original meaning.
"""
from collections import Counter
import re

from xgap.experiments.ch6_admission_policy import (
    AdmissionBudgets, CLOSURE_KEYS, CONTINUABLE, checked_segment, classify,
)
from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.row_normalization import normalize_rows

SCHEMA = 'xgap-ch6-backend-eligibility-v1'
INPUT_SCHEMA = 'xgap-ch6-backend-eligibility-input-v1'


def _same(a, b):
    return isinstance(a, dict) and isinstance(b, dict) and a.get('sha256') == b.get('sha256') and bool(a.get('sha256'))


def _runtime_same(a, b):
    return a is None and b is None or _same(a, b)


def _worker(row, case, ready, bundle_pin, outcome):
    child = load_pin(row['worker']) if row.get('worker') else None
    if child is not None and (child.get('case_id') != case['case_id']
            or not _same(child.get('bundle'), bundle_pin)
            or not _same(child.get('profile'), ready.get('profile'))
            or child.get('model_calls') != 0
            or type(child.get('final_plan_executions')) is not int
            or not 0 <= child['final_plan_executions'] <= 1):
        raise ValueError('Worker identity or one-shot execution differs')
    if outcome == 'correct':
        if not child or child.get('success') is not True or child['final_plan_executions'] != 1:
            raise ValueError('Correctness requires a successful worker')
        reference = load_pin(case['reference'])
        actual = load_pin(child['answer'])
        if (any(child.get(k) != reference[k] for k in ('query_sha256','source_snapshot_sha256'))
                or normalize_rows(actual['rows'], reference['normalization']) !=
                   normalize_rows(reference['rows'], reference['normalization'])):
            raise ValueError('Actual answer or identity differs from independent reference')


def assess(input_pin):
    """Recompute the certificate from pinned receipts; never execute queries."""
    spec = load_pin(input_pin)
    if (spec.get('schema_version') != INPUT_SCHEMA
            or not re.fullmatch('[a-f0-9]{40}', spec.get('source_commit', ''))
            or not isinstance(spec.get('segments'), list) or not 1 <= len(spec['segments']) <= 1024):
        raise ValueError('Explicit bounded eligibility input and source revision required')
    budgets = AdmissionBudgets(**spec['admission_budgets'])
    limits = spec['resource_limits']
    if set(limits) != {'method','source'} or any(type(v) is not int or v <= 0 for v in limits.values()):
        raise ValueError('Explicit method and source memory limits required')
    bundle, prepared = load_pin(spec['bundle']), load_pin(spec['prepared'])
    if not prepared.get('success') or not _same(bundle['profile'], prepared['profile']):
        raise ValueError('Prepared deployment and cohort differ')
    frozen = [c['case_id'] for c in bundle['cases']]
    cases_by_id = {c['case_id']:c for c in bundle['cases']}
    if not 1 <= len(frozen) <= 1024 or len(set(frozen)) != len(frozen):
        raise ValueError('Nonempty distinct frozen cohort required')
    rows, evidence, source_ready, common_budget = [], [], None, None
    for receipt_pin in spec['segments']:
        receipt = load_pin(receipt_pin)
        if (not _same(receipt.get('bundle'), spec['bundle'])
                or not _same(receipt.get('prepared'), spec['prepared'])
                or not _same(receipt.get('profile'), bundle['profile'])
                or receipt.get('source_commit') != spec['source_commit']
                or receipt.get('admission_budgets') != budgets.to_dict()
                or not _runtime_same(receipt.get('source_runtime'), spec.get('source_runtime'))
                or receipt.get('model_calls') != 0 or receipt.get('evaluated_method') is not False):
            raise ValueError('Diagnostic input, revision, runtime or budget differs')
        if not all(receipt.get('closure', {}).get(k) is True for k in CLOSURE_KEYS):
            raise ValueError('Source closure is unverified')
        cases = receipt.get('cases', [])
        if (type(receipt.get('attempted')) is not int or not cases
                or receipt['attempted'] != receipt.get('audited') or receipt['audited'] != len(cases)):
            raise ValueError('Missing or unaccounted attempted case')
        checked_segment(receipt, [row.get('case_id') for row in cases])
        ready = load_pin(receipt['source_ready'])
        if (not _same(ready.get('prepared'), spec['prepared'])
                or not _runtime_same(ready.get('source_runtime'), spec.get('source_runtime'))
                or ready.get('query_timeout_seconds') != budgets.source_timeout_seconds):
            raise ValueError('Serving attestation differs')
        actual_mode = (ready.get('tdb2_file_mode','default'), ready.get('experimental_lazy_range',False))
        expected_mode = ('direct',True) if spec.get('source_runtime') else ('default',False)
        if actual_mode != expected_mode:
            raise ValueError('Serving mode differs')
        source_ready = source_ready or receipt['source_ready']
        for row in cases:
            if row.get('case_id') not in cases_by_id:
                raise ValueError('Case outside frozen cohort')
            outcome = classify(row)
            if outcome not in CONTINUABLE:
                raise ValueError('Wrong answer or unexplained execution failure blocks eligibility')
            _worker(row,cases_by_id[row['case_id']],ready,spec['bundle'],outcome)
            observed = row['source_observations']; guard = row['guard']
            if (guard.get('budget',{}).get('wall_seconds') != budgets.worker_seconds
                    or guard.get('budget',{}).get('max_group_rss_bytes') != limits['method']
                    or row.get('resources',{}).get('limits') != limits
                    or observed.get('budget',{}).get('timeout_seconds') != budgets.source_timeout_seconds):
                raise ValueError('Actual per-case deadline differs')
            if common_budget is None:common_budget = observed['budget']
            elif common_budget != observed['budget']:raise ValueError('Source observation budgets differ')
            rows.append(dict(case_id=row['case_id'],outcome=outcome,answer_em=row.get('answer_em'),
                receipt=receipt_pin,worker=row.get('worker'),source_requests=observed.get('requests',0)))
        evidence.append(receipt_pin)
    if [r['case_id'] for r in rows] != frozen:
        raise ValueError('Complete frozen cohort order required; no missing, duplicate or resampled cases')
    # No purely symbolic/failed cohort can attest a real successful roundtrip.
    if not any(r['outcome']=='correct' and r['source_requests']>0 for r in rows):
        raise ValueError('At least one successful actual backend roundtrip required')
    counts = dict(Counter(r['outcome'] for r in rows))
    return dict(schema_version=SCHEMA,input=input_pin,eligible_for_evaluation=True,
        all_answers_correct=counts.get('correct')==len(frozen),full_bundle_admitted=False,
        formal_campaign_ready=False,backend_roundtrip=True,admission_scope='complete_bundle',
        bundle=spec['bundle'],prepared=spec['prepared'],profile=bundle['profile'],
        source_runtime=spec.get('source_runtime'),source_commit=spec['source_commit'],
        source_ready=source_ready,source_budget=common_budget,admission_budgets=budgets.to_dict(),resource_limits=limits,
        cases=rows,counts=counts,evidence=evidence,closure=dict.fromkeys(CLOSURE_KEYS,True),
        model_calls=0,backend_calls=0,evaluated_method=False,
        scope='Deployment eligibility only; typed cuts remain censored and supported; no quality or final release claim')


def eligible(gate, *, bundle_pin=None, prepared_pin=None):
    """Recognize a verified new certificate or unchanged legacy strict receipt."""
    if gate.get('schema_version') == SCHEMA:
        if gate != assess(gate['input']):
            raise ValueError('Eligibility certificate differs from recomputed evidence')
        result = gate['eligible_for_evaluation'] is True
    else:
        result = bool(gate.get('success') is True and gate.get('backend_roundtrip') is True
            and gate.get('admission_scope','complete_bundle')=='complete_bundle'
            and gate.get('full_bundle_admitted',True) is True)
    if bundle_pin is not None and 'bundle' in gate and not _same(gate['bundle'],bundle_pin):
        raise ValueError('Admission belongs to a different frozen bundle')
    if prepared_pin is not None and 'prepared' in gate and not _same(gate['prepared'],prepared_pin):
        raise ValueError('Admission belongs to different prepared stores')
    return result


def check_design(gate, design):
    if gate.get('schema_version') != SCHEMA:return
    if (gate['source_budget'] != design.get('source_budget')
            or gate['resource_limits']['source'] != design.get('source_rss_bytes')
            or gate['resource_limits']['method'] != design.get('method_rss_bytes')):
        raise ValueError('Evaluation source/memory budget differs from diagnostic deployment')
