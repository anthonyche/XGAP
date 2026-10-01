"""Fixed logical bank queries with independent physical grouping and execution P.

The selected branch DAG is freshly planned on every measured request. Each method
keeps its declared depth, H=12 and planning P=4 at every worker level; executor P is set
only after selection. This isolates scheduling parallelism from plan selection.
"""
from copy import deepcopy
from dataclasses import asdict, replace
import time

from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.intent_certificate import fingerprint
from xgap.agent.live_probe import LiveProbePolicy
from xgap.experiments.ch6_financial_calibration_planning import (
    _branch, _compose, CalibrationPlanningError, SETTINGS, REMOTE)
from xgap.experiments.ch6_financial_scalability_queries import bind_sources
from xgap.planning.joint_cost import JointCostProfile
from xgap.runtime.unified_physical import identity
from xgap.experiments.ch6_financial_plan_comparability import plan_fingerprints

VERSION = 'xgap-financial-fixed-scalability-planning-v1'
WORKERS = (1, 2, 4, 8, 16)
METHODS = ('XGAP', 'NP', 'SH', 'GR')


def settings_for(method, *, probes=True):
    if method not in METHODS:
        raise ValueError('Mixed deployment supports XGAP,NP,SH,GR; TS is unsupported')
    return replace(SETTINGS,
        limits=replace(SETTINGS.limits, depth=1 if method in ('SH','GR') else 2,
                       aggregation='expectation' if probes else SETTINGS.limits.aggregation),
        information_mode='no_probe' if method == 'NP' else 'all',
        action_objective='myopic' if method == 'GR' else 'continuation',
        live_probe_policy=LiveProbePolicy('financial-scale-public-match-v1',
            'Existing bounded compiled-Match probe policy defaults; public prior frozen before measurements; not fitted to calibration answers') if probes else None)


def plan_case(case, source_schema, sources, backends, *, bank_to_source,
              estimator, workers=4, method='XGAP', costs=JointCostProfile(), backend_clients=None, probes=False):
    started = time.perf_counter(); cpu = time.process_time()
    if type(workers) is not int or workers not in WORKERS:
        raise ValueError('Execution workers must be one of 1,2,4,8,16')
    branches = bind_sources(case, source_schema, bank_to_source)
    settings = settings_for(method, probes=probes)
    if estimator is None or not getattr(estimator, 'strict_relative_units', False):
        raise ValueError('Frozen source-count relative work estimator required')
    physical = replace(OneShotPolicy.for_mode('performance'), max_parallelism=4,
                       retrieval_rows_per_relation=None)
    selected, reports = [], []
    for branch in branches:
        try:
            plan, report = _branch(branch, source_schema=source_schema, sources=sources,
                backends=backends, costs=costs, estimator=estimator, physical=physical, grouped=True,
                settings=settings, backend_clients=backend_clients)
        except CalibrationPlanningError as error:
            error.planning_evidence.update(case_id=case['case_id'], completed_branch_reports=reports)
            raise
        selected.append(plan); reports.append(report)
    composed = _compose(dict(case, branches=branches), selected, 4)
    raw = composed.to_dict()
    # Exclude runtime worker setting and timing from the common selected-DAG pin.
    raw['metadata']['financial_composition']['profile'] = VERSION
    selection = deepcopy(raw); selection.pop('plan_id', None)
    selection_sha = fingerprint(selection)
    raw['max_parallelism'] = workers
    raw['plan_id'] = 'financial-scale:'+fingerprint(raw)[:24]
    plan = type(composed).from_dict(raw)
    report = dict(schema_version=VERSION, method=method, status='planned_without_final_execution',
        case_id=case['case_id'], query_sha256=case['query_sha256'], plan_identity=identity(plan),
        selected_dag_sha256=selection_sha, execution_parallelism=workers, planning_parallelism=4,
        **plan_fingerprints(plan),
        planning_cpu_ms=(time.process_time()-cpu)*1000,
        planning_wall_ms=(time.perf_counter()-started)*1000,
        controller_planning_cpu_ms=sum(r['controller']['planning_cpu_ms'] for r in reports),
        settings=asdict(settings), branch_count=len(reports), branches=reports,
        algorithm='Fixed-depth planning per logical bank, exact scalar composition; executor workers varied after plan selection',
        global_joint_search=False, model_calls=0,
        backend_calls=sum(r.get('probe_calls',0) for r in reports),
        probe_calls=sum(r.get('probe_calls',0) for r in reports), clarification_calls=0,
        scope_confirmation_calls=0, final_plan_executions=0, final_runtime_executions_required=1,
        selected_remote_nodes=sum(n.kind in REMOTE for n in plan.nodes),
        bank_to_source={str(k):v for k,v in sorted(bank_to_source.items())})
    return plan, report
