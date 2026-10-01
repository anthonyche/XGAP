"""Frozen factors for the authorized two-scan financial experiment."""
import json
from xgap.experiments.ch6_financial_scalability_queries import build_workload, build_schedule

VERSION = 'xgap-financial-scalability-contract-v1'
SOURCES = (2, 4, 8, 16, 32)
WORKERS = (1, 2, 4, 8, 16)
METHODS = ('XGAP', 'NP', 'SH', 'GR')
REQUEST_SECONDS = 600


def contract():
    workload = build_workload()
    schedule = build_schedule(workload, source_counts=SOURCES, worker_counts=WORKERS,
        source_scan_workers=4, worker_scan_sources=32, repetitions=3)
    configurations = []
    for scan, levels in (('A_endpoints', SOURCES), ('B_workers', WORKERS)):
        for level in levels:
            s, p = (level, 4) if scan == 'A_endpoints' else (32, level)
            requests=[]
            for qi,c in enumerate(workload['cases']):
                # Each method occupies each cache-order position once across Q1..Q4.
                order=METHODS[qi:]+METHODS[:qi]
                requests.extend(dict(method=m,query_id=c['case_id'],query_sha256=c['query_sha256'],repetition=r)
                                for m in order for r in range(3))
            configurations.append(dict(configuration_id=scan+'-'+str(level), scan_name=scan,
                x_value=level, source_count=s, workers=p, requests=requests))
    # Reuse already loaded S32 first to return a four-method baseline without
    # waiting for any merged-store import. This order is fixed before outcomes.
    order = ['A_endpoints-32', 'B_workers-4', 'B_workers-8', 'B_workers-16',
             'B_workers-2', 'B_workers-1', 'A_endpoints-16', 'A_endpoints-8',
             'A_endpoints-4', 'A_endpoints-2']
    configurations.sort(key=lambda c:order.index(c['configuration_id']))
    from xgap.experiments.ch6_financial_scalability_planning import settings_for
    from dataclasses import asdict
    value = dict(schema_version=VERSION, methods=list(METHODS), unsupported_methods={'TS':'Mixed Neo4j/RDF deployment'},
        workload=workload, per_method_schedule=schedule,
        method_settings={m:asdict(settings_for(m,probes=True)) for m in METHODS},
        configurations=configurations, total_requests=480, repetitions=3,
        request_seconds=REQUEST_SECONDS, sequential_requests=True, automatic_retries=0,
        source_layout='Single copy of every logical edge; same-engine contiguous atom groups; S/2 Neo4j and S/2 Fuseki',
        memory=dict(profile='fixed-aggregate-v1', total_heap_gib=32, total_native_pagecache_gib=16),
        planning=dict(depth_by_method=dict(XGAP=2,NP=2,SH=1,GR=1), horizon_per_bank=12, planning_parallelism=4, branches=32,
            fresh_planning_each_request=True, execute_selected_plan_once=True),
        probe_policy='Declared public compiled-Match policy; selected live probes allowed in XGAP/SH/GR, disabled in NP; no forced probe or semantic confirmation',
        method_order='Cyclic method block order by Q index, same at every X; three consecutive repeats per method; no flush or warmup',
        configuration_order=order,
        frozen_factors=dict(logical_edges=100000000, logical_accounts=10000000, atomic_shards=32,
            cpu_allocation=32, memory_allocation_gib=128, engine_profile='same sealed binaries and indexes',
            model_calls=0, clarification_calls=0, warmup_queries=0, cache_flushes=0),
        metrics=dict(realized_cost='HTTP source request attempts + (request body bytes + response body bytes)/MiB',
            peak_rss_mb='Sampled method plus all owned source processes; MiB; shared pages may be double counted',
            shards_touched='Observed physical sources receiving forwarded calls; atomic_shards_declared remains 32',
            cross_endpoint_edges='Canonical edges crossing sender/target owner-bank groups; not actual network movements'),
        censoring='Hard request timeout at 600s; retain observed time and clipping flag; failures are never retried or discarded',
        scope='Resolved fixed query to answer; no NL/semantic ambiguity evaluation; offline load/copy/reference excluded')
    return json.loads(json.dumps(value))


def configuration(configuration_id):
    candidates = [c for c in contract()['configurations'] if c['configuration_id'] == configuration_id]
    if len(candidates) != 1:
        raise ValueError('Unknown frozen scan configuration')
    return candidates[0]
