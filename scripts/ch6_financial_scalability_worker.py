"""One fresh resolved financial scale request; no gold, models or source setup.

The supervisor owns the 600-second request deadline, source observation and
source cleanup. Durable phase markers retain completed planning metrics if the
worker is interrupted during execution. No partial answer is called complete.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from xgap.experiments.financial_runtime_inputs import load, runtime_inputs
from xgap.experiments.ch6_financial_scale import BANKS, DEGREE, SOURCE_COUNTS, VERSION as CANONICAL_VERSION
from xgap.experiments.ch6_financial_materialize import VERSION as MATERIALIZATION_VERSION
from xgap.experiments.ch6_financial_scalability_queries import bind_sources, ownership_basis
from xgap.experiments.ch6_financial_scalability_planning import plan_case, WORKERS
from xgap.experiments.ch6_parallel import execute
from xgap.experiments.one_shot_profile import native_clients
from xgap.experiments.one_shot_records import write_once
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin

SCHEMA = 'xgap-financial-scalability-worker-v1'
METHODS = ('XGAP', 'NP', 'SH', 'GR')


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def prepare_inputs(spec):
    """Only frozen metadata/clients are prepared here; no plan or query runs."""
    if any(key in spec for key in ('gold', 'answer', 'expected_result', 'reference', 'reference_answers', 'gold_path')):
        raise ValueError('Scale worker input must not contain reference answers')
    if (spec.get('method') not in METHODS or type(spec['workers']) is not int or spec['workers'] not in WORKERS
            or type(spec['repetition']) is not int or spec['repetition'] not in range(3)):
        raise ValueError('Supported mixed method, frozen worker levels and repetitions 0..2 required')
    materialized = load(spec['materialization']); canonical = load(materialized['canonical_manifest'])
    n = spec['case']['nodes_per_bank']; basis = ownership_basis(n)
    if (canonical.get('schema_version') != CANONICAL_VERSION or canonical.get('success') is not True
            or canonical.get('recipe', {}).get('nodes_per_bank') != n
            or canonical.get('counts', {}).get('accounts') != BANKS*n
            or canonical.get('counts', {}).get('logical_edges') != BANKS*n*DEGREE
            or materialized.get('schema_version') != MATERIALIZATION_VERSION or materialized.get('success') is not True
            or materialized.get('logical_facts_sha256') != canonical.get('logical_facts_sha256')
            or materialized.get('canonical_digests') != canonical.get('canonical_digests')
            or materialized.get('logical_nodes') != BANKS*n or materialized.get('logical_edges') != BANKS*n*DEGREE):
        raise ValueError('Verified canonical graph and materialization identities differ')
    bank_to_source = {}; ids = set()
    for source in materialized['sources']:
        sid, atoms = source['source_id'], source['atoms']
        if (not isinstance(sid, str) or not sid or sid in ids or not atoms
                or any(type(bank) is not int or not 0 <= bank < BANKS for bank in atoms)
                or len(atoms) != len(set(atoms)) or set(atoms) & set(bank_to_source)
                or source['logical_edges'] != len(atoms)*n*DEGREE
                or source['owned_accounts'] != len(atoms)*n
                or source['engine'] != ('neo4j' if max(atoms) < 16 else 'rdf')
                or (min(atoms) < 16 <= max(atoms))):
            raise ValueError('Physical source owner-bank partition or counts differ')
        ids.add(sid); bank_to_source.update({bank:sid for bank in atoms})
    if (set(bank_to_source) != set(range(BANKS)) or len(ids) not in SOURCE_COUNTS
            or materialized.get('source_count') != len(ids) or set(spec['client_specs']) != ids):
        raise ValueError('Complete physical endpoint/client and owner-bank coverage required')
    schema, sources, backends, estimator = runtime_inputs(materialized)
    schema = deepcopy(schema)
    if schema.get('financial_canonical_ownership', basis) != basis:
        raise ValueError('Existing schema ownership declaration differs from canonical proof')
    # The old 32-source receipt is immutable and has no such annotation. Add the
    # canonical proof only to this request's metadata after the pinned checks.
    schema['financial_canonical_ownership'] = basis
    bind_sources(spec['case'], schema, bank_to_source)
    plugins = BackendPluginRegistry()
    clients = native_clients(spec['client_specs'])
    if set(clients) != ids:
        raise ValueError('Native client construction changed the source domain')
    for sid, client in clients.items():
        plugins.register(NativeBackendPlugin(sid, client))
    return schema, sources, backends, estimator, bank_to_source, BackendInvokeTool(plugins), clients


def worker(input_path, output):
    root = Path(output); root.mkdir(parents=True, exist_ok=False)
    result = dict(schema_version=SCHEMA, success=False, status='startup_failed',
        model_calls=0, scope_confirmation_calls=0, coverage_confirmation_calls=0,
        clarification_calls=0, final_plan_executions=0, runtime_backend_calls=None,
        probe_calls=0,
        request_latency_s=None, planning_cpu_ms=None, planning_wall_ms=None, execution_ms=None)
    startup = time.monotonic()
    try:
        spec = json.loads(Path(input_path).read_text())
        schema, sources, backends, estimator, assignment, tool, clients = prepare_inputs(spec)
        case = spec['case']; workers = spec['workers']
        result.update(case_id=case['case_id'], repetition=spec['repetition'], workers=workers, method=spec['method'],
            query_sha256=case['query_sha256'], endpoints_actual=len(set(assignment.values())),
            materialization=spec['materialization'], bank_to_source={str(k):v for k,v in sorted(assignment.items())})
        result['estimator'] = write_once(root/'estimator.json', estimator.to_dict())
    except Exception as error:
        result.update(error_type=type(error).__name__, error=str(error), startup_seconds=time.monotonic()-startup)
        write_once(root/'receipt.json', result)
        return 2
    result['startup_seconds'] = time.monotonic()-startup
    plan = None; planning = None; run = None; phase = 'planning'
    started = time.monotonic(); cpu = time.process_time()
    result['request_start'] = write_once(root/'request-start.json', dict(schema_version=SCHEMA,
        monotonic=started, timestamp=timestamp(), pid=os.getpid(), phase=phase,
        case_id=case['case_id'], repetition=spec['repetition'], workers=workers,
        method=spec['method'],
        query_sha256=case['query_sha256'], endpoints_actual=result['endpoints_actual']))
    try:
        plan, planning = plan_case(case, schema, sources, backends, bank_to_source=assignment,
            estimator=estimator, workers=workers, method=spec['method'], backend_clients=clients, probes=True)
        result.update(planning_cpu_ms=(time.process_time()-cpu)*1000,
            planning_wall_ms=(time.monotonic()-started)*1000, planning_complete=True,
            probe_calls=planning['probe_calls'],
            selected_dag_sha256=planning['selected_dag_sha256'], plan_identity=planning['plan_identity'])
        result.update({k:planning.get(k) for k in ('execution_plan_sha256',
            'execution_plan_fingerprint_schema','plan_audit_sha256')})
        result['planning_checkpoint'] = write_once(root/'planning-checkpoint.json', dict(
            schema_version=SCHEMA, monotonic=time.monotonic(), timestamp=timestamp(), phase='planned',
            case_id=case['case_id'], query_sha256=case['query_sha256'],
            method=spec['method'],
            planning_cpu_ms=result['planning_cpu_ms'], planning_wall_ms=result['planning_wall_ms'],
            selected_dag_sha256=result['selected_dag_sha256'], plan_identity=result['plan_identity'],
            execution_plan_sha256=result.get('execution_plan_sha256'),
            execution_plan_fingerprint_schema=result.get('execution_plan_fingerprint_schema'),
            plan_audit_sha256=result.get('plan_audit_sha256'),
            selected_remote_nodes=planning.get('selected_remote_nodes'), execution_parallelism=workers,
            model_calls=0, backend_calls=planning.get('backend_calls'), probe_calls=result['probe_calls'], final_plan_executions=0))
        phase = 'execution'
        result['execution_start'] = write_once(root/'execution-start.json', dict(schema_version=SCHEMA,
            monotonic=time.monotonic(), timestamp=timestamp(), phase=phase,
            case_id=case['case_id'], plan_identity=result['plan_identity'], workers=workers, method=spec['method'],
            final_plan_executions=1))
        result['final_plan_executions'] = 1
        run, overlap = execute(plan, tool, parallelism=workers)
        ended = time.monotonic()
        result.update(success=run.success, status='answered' if run.success else 'execution_failed',
            answer=list(run.final_rows), execution_ms=run.elapsed_ms,
            runtime_backend_calls=run.total_remote_calls, runtime_bytes_moved=run.total_bytes_moved,
            source_ids_touched=sorted({event['backend_id'] for event in overlap['events']}), overlap=overlap,
            source_ids_touched_scope='Runtime execution events; supervisor source HTTP ledger additionally includes planning probes',
            failures=[dict(node_id=node.node_id, error=node.error) for node in run.node_results if node.error])
        phase = 'returned'
    except Exception as error:
        ended = time.monotonic()
        result.update(status='worker_failure', failure_phase=phase, error_type=type(error).__name__, error=str(error))
        if phase == 'planning':
            result.update(planning_complete=False, planning_cpu_ms=(time.process_time()-cpu)*1000,
                planning_wall_ms=(ended-started)*1000, probe_calls=None)
        if hasattr(error, 'planning_evidence'):
            planning = error.planning_evidence
    result['request_latency_s'] = ended-started
    # Full plan, report, estimator and receipt serialization are outside this
    # interval. Small durable phase markers inside it are declared overhead.
    result['request_end'] = write_once(root/'request-end.json', dict(schema_version=SCHEMA,
        monotonic=ended, timestamp=timestamp(), pid=os.getpid(), status=result['status'], phase=phase,
        method=spec['method'],
        request_latency_s=result['request_latency_s'], planning_cpu_ms=result['planning_cpu_ms'],
        planning_wall_ms=result['planning_wall_ms'], execution_ms=result['execution_ms']))
    result['measurement_boundary'] = ('Resolved s0 through returned materialized scalar/error; fresh lowering/planning and execution plus compact durable phase markers; '
        'excludes source initialization, input parsing, gold, query-independent estimator serialization and post-request full artifacts')
    if plan is not None:
        result['plan'] = write_once(root/'plan.json', plan.to_dict())
    if planning is not None:
        result['planning'] = write_once(root/'planning.json', planning)
    write_once(root/'receipt.json', result)
    return 0 if result['success'] else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', '--worker-input', dest='input', required=True)
    parser.add_argument('--output', '--worker-output', dest='output', required=True)
    args = parser.parse_args()
    return worker(args.input, args.output)


if __name__ == '__main__':
    raise SystemExit(main())
