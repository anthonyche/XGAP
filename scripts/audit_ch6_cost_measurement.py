#!/usr/bin/env python3
"""Recompute F6 cost evidence from sealed worker outputs; zero executions."""
import argparse
import json
from pathlib import Path
import tempfile

from xgap.agent.intent_certificate import fingerprint
from xgap.experiments.ch6_cost_pool import load, freeze, pin_identity
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.row_normalization import normalize_rows


def require(value, message):
    if not value:
        raise ValueError(message)


def audit(pool_pin, measurement_pin, output):
    pool, measurement = load(pool_pin), load(measurement_pin)
    require(measurement.get('success') is True and measurement.get('online_feedback') is False,
            'Successful offline measurement required')
    require(pin_identity(measurement['pool']) == pin_identity(pool_pin), 'Measured pool differs')
    intent = load(measurement['intent'])
    require(intent['source_commit'] == measurement['source_commit'] and
            pin_identity(intent['pool']) == pin_identity(pool_pin) and
            pin_identity(intent['prepared']) == pin_identity(measurement['prepared']), 'Measurement intent differs')
    require(all(measurement['closure'].get(k) is True for k in
                ('owned_groups_drained', 'owned_processes_terminal', 'observer_stopped',
                 'serving_copy_reclamation_complete')), 'Unverified source closure')
    prepared = load(measurement['prepared'])
    require(prepared['success'] is True and prepared['profile']['sha256'] == pool['profile']['sha256'],
            'Prepared source profile differs')
    ready = load(measurement['source_ready'])
    require(pin_identity(ready['prepared']) == pin_identity(measurement['prepared']) and
            pin_identity(ready['preparation_input']) == pin_identity(prepared['input_seal']),
            'Actual source startup differs')
    build = load(ready['preparation_input'])
    load(ready['profile'])
    require(build['profile']['sha256'] == prepared['profile']['sha256'], 'Engine seal profile differs')
    storage = load(measurement['storage_placement'])
    require(storage['separate'] == (intent['source_storage'] == 'node_local') and
            storage['shared_method_contract'] is True and storage['query_warmup_calls'] == 0,
            'Serving storage or warmup differs')
    runtime = intent['source_runtime']
    require(ready.get('source_runtime') == runtime, 'Actual runtime differs')
    if runtime:
        from ch6_source_runtime import validate_contract
        validate_contract(load(runtime))
        require(ready.get('tdb2_file_mode') == 'direct' and ready.get('experimental_lazy_range') is True,
                'Actual repaired file mode differs')
    else:
        require(ready.get('tdb2_file_mode', 'default') == 'default' and not ready.get('experimental_lazy_range'),
                'Undeclared repaired runtime')
    require(ready['query_timeout_seconds'] == intent['source_budget']['timeout_seconds'], 'Source timeout differs')
    reference = load(pool['reference'])
    require(fingerprint(pool['query']) == pool['query_sha256'] and all(reference[k] == pool[k]
        for k in ('query_sha256', 'source_snapshot_sha256')), 'Fixed complete Q/reference differs')
    rows = measurement['observations']
    require([(r['plan_id'], r['repeat']) for r in rows] ==
            [(r['plan_id'], r['repeat']) for r in pool['order']], 'Trial order or repetition differs')
    expected = normalize_rows(reference['rows'], reference['normalization'])
    for row in rows:
        guard, worker = load(row['guard']), load(row['worker'])
        require(guard['success'] is True and worker['success'] is True and worker['model_calls'] == 0 and
                worker['plan_id'] == row['plan_id'] and worker['execution_ms'] == row['actual_cost'] and
                pin_identity(worker['pool']) == pin_identity(pool_pin) and
                pin_identity(worker['profile']) == pin_identity(ready['profile']), 'Worker/guard cost evidence differs')
        require(row['source_observations']['failed_requests'] == 0, 'Source request failed')
        answer = load(worker['answer'])
        require(normalize_rows(answer['rows'], reference['normalization']) == expected, 'Actual answer differs')
    frozen = load(measurement['frozen_costs'])
    with tempfile.TemporaryDirectory(prefix='xgap-f6-audit-') as temporary:
        require(freeze(pool, rows, Path(temporary)/'costs.json') == frozen,
                'Frozen medians, normalizer or perturbations differ from raw observations')
    return write_once(Path(output).resolve(), dict(schema_version='xgap-ch6-cost-measurement-audit-v1',
        success=True, pool=pool_pin, measurement=measurement_pin, frozen_costs=measurement['frozen_costs'],
        prepared=measurement['prepared'], source_ready=measurement['source_ready'],
        source_commit=measurement['source_commit'], source_storage=intent['source_storage'], source_runtime=runtime,
        source_budget=intent['source_budget'], source_rss_bytes=pool['budget']['source_rss_bytes'],
        query_sha256=pool['query_sha256'], source_snapshot_sha256=pool['source_snapshot_sha256'],
        unit=pool['unit'], timing_scope=pool['timing_scope'], trials=len(rows),
        plan_count=len(pool['plans']), repetitions=pool['repetitions'],
        medians_recomputed=True, answers_rechecked=True, closure_verified=True,
        backend_calls=0, model_calls=0, online_feedback=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('pool-path', 'pool-sha256', 'measurement-path', 'measurement-sha256', 'output'):
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(dict(path=args.pool_path, sha256=args.pool_sha256),
        dict(path=args.measurement_path, sha256=args.measurement_sha256), args.output)))
