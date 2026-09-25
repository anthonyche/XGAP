#!/usr/bin/env python3
"""Cover frozen cases without retrying resource failures or certifying readiness.

Each segment reuses a source session until the original fail-fast runner stops.
Only verified shutdown permits the next segment; no failed case is rerun. Source
setup remains offline and is recorded for each new session. This is diagnostic
coverage, not the five-method experiment or full_bundle_admitted evidence.
"""
import argparse
from collections import Counter
from pathlib import Path
import time

from check_ch6_core_backend import run
from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.ch6_fact_index import pin
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.ch6_admission_policy import AdmissionBudgets, CONTINUABLE, checked_segment


def census(bundle_pin, prepared_pin, output, *, case_ids, segment_size=8,
           max_census_seconds=3600, source_timeout_seconds=60, worker_seconds=120,
           **runtime):
    budgets = AdmissionBudgets(source_timeout_seconds, worker_seconds)
    bundle = load_pin(bundle_pin)
    frozen = [c['case_id'] for c in bundle['cases']]
    selected = list(case_ids)
    if (not 1 <= len(selected) <= 1024 or len(set(frozen)) != len(frozen)
            or len(set(selected)) != len(selected)
            or [c for c in frozen if c in set(selected)] != selected):
        raise ValueError('Explicit distinct cases in frozen bundle order required')
    if type(segment_size) is not int or not 1 <= segment_size <= 8:
        raise ValueError('Segment size must be 1..8')
    if type(max_census_seconds) is not int or not 1 <= max_census_seconds <= 86400:
        raise ValueError('Explicit bounded census wall budget required')
    if set(runtime) - {'planning', 'serving_root', 'startup_seconds', 'rdf_file_mode',
                       'source_rss_bytes', 'rdf_lazy_range', 'source_runtime'}:
        raise ValueError('Unknown runtime setting')
    if runtime.get('serving_root') is not None:
        runtime['serving_root'] = str(Path(runtime['serving_root']).resolve())
    startup = runtime.get('startup_seconds', 300)
    if type(startup) is not int or not 1 <= startup < 3600:
        raise ValueError('Bounded positive source startup budget required')
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    write_once(root/'intent.json', dict(bundle=bundle_pin, prepared=prepared_pin,
        case_order=selected, segment_size=segment_size, max_census_seconds=max_census_seconds,
        admission_budgets=budgets.to_dict(), runtime=runtime, automatic_retries=0,
        scope='diagnostic coverage only; no formal readiness claim'))
    start = time.monotonic()
    segments, outcomes, error, stop = [], [], None, None
    cursor = 0
    try:
        while cursor < len(selected):
            # Reserve declared work and cleanup allowance before starting it.
            # This is admission control, not an OS wall-time guarantee.
            size = min(segment_size, len(selected)-cursor)
            inner_capacity = (3600-startup-30)//(worker_seconds+5)
            if inner_capacity < 1:
                stop = 'segment_budget'; break
            size = min(size, inner_capacity)
            reserve = startup + size*(worker_seconds+5) + 30
            if time.monotonic()-start+reserve > max_census_seconds:
                stop = 'census_budget'; break
            target = root/f'segment-{len(segments):04d}'
            settings = dict(runtime)
            if settings.get('serving_root'):
                settings['serving_root'] = Path(settings['serving_root'])/target.name
            requested = selected[cursor:cursor+size]
            code = run(bundle_pin, prepared_pin, target, case_ids=requested,
                       **budgets.to_dict(), **settings)
            receipt_pin = pin(target/'receipt.json')
            receipt = load_pin(receipt_pin)
            segments.append(dict(receipt=receipt_pin, exit_code=code, requested=requested))
            if receipt.get('bundle', {}).get('sha256') != bundle_pin['sha256']:
                raise ValueError('Segment bundle differs')
            if receipt.get('admission_budgets') != budgets.to_dict():
                raise ValueError('Segment time budgets differ')
            if receipt.get('prepared') != prepared_pin:
                raise ValueError('Segment prepared stores differ')
            if code not in (0, 2) or (code == 0) != (receipt.get('success') is True):
                raise ValueError('Segment exit status and receipt disagree')
            checked = checked_segment(receipt, requested)
            outcomes.extend(checked)
            cursor += len(checked)
            if any(r['outcome'] not in CONTINUABLE for r in checked):
                stop = 'correctness_or_infrastructure_blocker'; break
    except Exception as exc:
        error = dict(type=type(exc).__name__, message=str(exc))
        stop = 'unverified_segment'
    counts = dict(Counter(r['outcome'] for r in outcomes))
    return write_once(root/'receipt.json', dict(schema_version='xgap-admission-census-v1',
        census_complete=cursor == len(selected) and stop is None,
        all_answers_correct=cursor == len(selected) and stop is None and counts.get('correct') == len(selected),
        full_bundle_admitted=False, formal_campaign_ready=False, evaluated_method=False,
        bundle=bundle_pin, prepared=prepared_pin, admission_budgets=budgets.to_dict(),
        case_order=selected, runtime=runtime,
        cases=outcomes, classified=len(outcomes), remaining=selected[cursor:],
        segments=segments, counts=counts, stop_reason=stop, error=error,
        remaining_safe_to_dispatch=stop not in ('unverified_segment', 'correctness_or_infrastructure_blocker'),
        model_calls=0, automatic_retries=0, elapsed_seconds=time.monotonic()-start,
        scope='Classified diagnostic coverage; unknown/unverified segments remain blocking'))


if __name__ == '__main__':
    import json
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('bundle-path','bundle-sha256','prepared-path','prepared-sha256','output'):
        p.add_argument('--'+key, required=True)
    p.add_argument('--case-ids', nargs='+', required=True)
    p.add_argument('--source-timeout-seconds', type=int, default=60)
    p.add_argument('--worker-seconds', type=int, default=120)
    p.add_argument('--max-census-seconds', type=int, default=3600)
    p.add_argument('--segment-size', type=int, default=8)
    p.add_argument('--startup-seconds', type=int, default=300)
    p.add_argument('--serving-root')
    p.add_argument('--planning', choices=('fixed_scan','unified'), default='unified')
    p.add_argument('--rdf-file-mode', choices=('default','direct'), default='default')
    p.add_argument('--rdf-lazy-range', action='store_true')
    p.add_argument('--source-runtime-path'); p.add_argument('--source-runtime-sha256')
    a = p.parse_args()
    if bool(a.source_runtime_path) != bool(a.source_runtime_sha256):
        p.error('Source runtime requires both path and digest')
    source_runtime = dict(path=a.source_runtime_path,sha256=a.source_runtime_sha256) if a.source_runtime_path else None
    result = census(dict(path=a.bundle_path,sha256=a.bundle_sha256),
        dict(path=a.prepared_path,sha256=a.prepared_sha256), a.output, case_ids=a.case_ids,
        source_timeout_seconds=a.source_timeout_seconds, worker_seconds=a.worker_seconds,
        max_census_seconds=a.max_census_seconds, segment_size=a.segment_size,
        startup_seconds=a.startup_seconds, serving_root=a.serving_root, planning=a.planning,
        rdf_file_mode=a.rdf_file_mode, rdf_lazy_range=a.rdf_lazy_range, source_runtime=source_runtime)
    receipt = load_pin(result)
    print(json.dumps(dict(receipt=result,census_complete=receipt['census_complete'],counts=receipt['counts'],stop_reason=receipt['stop_reason'])))
    raise SystemExit(0 if receipt['census_complete'] else 2)
