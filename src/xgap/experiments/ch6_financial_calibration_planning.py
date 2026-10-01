"""Real fixed-depth planning of disjoint financial owner-bank branches.

The unchanged unified controller chooses each branch plan using frozen source
statistics. A checked coordinator UNION/SUM then composes their scalar results
into ONE final runtime DAG. This is compositional fixed-query planning, not a
global joint search over the Cartesian product of branch strategies. The original
calibration entrypoint is zero-call; an explicit scalability-only settings/client
extension permits selected cardinality probes, never alternative plan trials.
"""
from copy import deepcopy
from dataclasses import asdict, replace
import time

from xgap.agent.intent_certificate import IntentCandidate, IntentFamily, fingerprint
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.practical_planning import _baseline
from xgap.agent.unified_contract import UnifiedTerminalContract
from xgap.agent.unified_family import FamilyDomain, FamilyState, UnifiedSettings
from xgap.agent.unified_lookahead import ActionFailure, Limits, Observation, Resources, run_online
from xgap.experiments.ch6_financial_calibration_queries import build_workload
from xgap.planning.joint_cost import JointCostProfile
from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNode, RuntimeNodeKind as R
from xgap.runtime.unified_physical import PhysicalMoves, identity
from xgap.semantic.compact_lowering import lower_compact_query


VERSION = 'xgap-financial-compositional-fixed-depth-v1'
REMOTE = {R.REMOTE_QUERY, R.REMOTE_BIND_QUERY}
SETTINGS = UnifiedSettings(limits=Limits(depth=2, horizon=12), information_targets=())


class CalibrationPlanningError(ValueError):
    """Failed selection retains its local trace; it never causes a source call."""
    def __init__(self, message, evidence):
        super().__init__(message)
        self.planning_evidence = evidence


def _source_schema(schema, sid, bank, *, grouped=False):
    owners = schema.get(sid, {}).get('owner_banks', schema.get(sid, {}).get('atoms'))
    if grouped:
        if not isinstance(owners, list) or bank not in owners:
            raise ValueError('Planning requires the declared owner bank inside this source')
    elif sid not in schema or owners != [bank]:
        raise ValueError('Planning requires the exact single owner-bank source')
    return {key: deepcopy(value) for key, value in schema.items()
            if key == sid or not (isinstance(value, dict) and 'nodes' in value and 'edges' in value)}


def _branch(branch, *, source_schema, sources, backends, costs, estimator, physical, grouped=False,
            settings=SETTINGS, backend_clients=None):
    started = time.perf_counter(); cpu = time.process_time()
    sid, bank = branch['source_id'], branch['bank']
    schema = _source_schema(source_schema, sid, bank, grouped=grouped)
    if sid not in sources or sources[sid].source_id != sid:
        raise ValueError('Branch source is absent or has a different identity')
    local_sources = {sid: sources[sid]}
    local_backends = {b: backends[b] for b in sources[sid].replica_backend_ids}
    if len(local_backends) != 1:
        raise ValueError('The 32-shard calibration has exactly one backend per source')
    family = IntentFamily('fixed-financial-bank-'+str(bank),
        (IntentCandidate.create(branch['query_sha256'], branch['query']),), (),
        snapshot_identity(local_sources, local_backends, schema),
        coverage_basis='Explicit resolved fixed query supplied by the frozen calibration request',
        language_version='v2')
    program, assignment = lower_compact_query(branch['query'], schema,
        program_id=f'bank-{bank:02d}', version='v2', optimize=True)
    seed = _baseline(program, assignment, local_sources, local_backends, physical, optimize_reads=False)
    seed_estimate, seed_detail = costs.execution(seed, estimator)
    calls = sum(n.kind in REMOTE for n in seed.nodes)
    contract = UnifiedTerminalContract(family, (), epsilon='0')
    moves = PhysicalMoves(family, schema, local_backends, physical, local_sources)
    seeds = {0: (seed, seed_estimate, Resources(remote_calls=calls, bytes=None, peak_bytes=None))}
    live_binding = None
    if settings.live_probe_policy is not None:
        from xgap.agent.live_probe import bind_live_probes
        settings, live_binding = bind_live_probes(settings, family, seeds, local_sources)
    domain = FamilyDomain('Frozen resolved bank query', contract, seeds, costs,
        authority_name='frozen-fixed-query', authority_version=family.identity,
        settings=settings, moves=moves, estimator=estimator)
    actual = FamilyState(); selected = []; information_records = []
    preparation_cpu_ms = (time.process_time()-cpu)*1000

    def perform(action):
        nonlocal actual
        if action.kind == 'probe':
            target = domain.targets[action.arguments['target']]
            if target.identity != action.arguments['identity'] or backend_clients is None:
                raise ValueError('Selected probe requires matching target and actual backend clients')
            try:
                label, record = target.invoke(backend_clients, local_sources)
            except Exception as error:
                information_records.append(dict(kind='probe', target=target.name,
                    status='failed', error_type=type(error).__name__, error=str(error)))
                raise ActionFailure(str(error), Resources(remote_calls=1, bytes=None, peak_bytes=None)) from error
            information_records.append(record)
            facts = dict(actual.facts)
            if label != 'unknown': facts[target.name] = label
            actual = replace(actual, facts=tuple(sorted(facts.items())))
            return Observation(label, actual, Resources(remote_calls=1, bytes=None, peak_bytes=None), record)
        if action.kind != 'transform':
            raise ValueError('Resolved calibration cannot invoke acquisition or clarification')
        applied = next((a for a in domain.physical_actions(actual) if a.key == action.key), None)
        if applied is None:
            raise ValueError('Selected physical rewrite is no longer admissible')
        actual = applied.outcomes[0].payload
        return Observation('applied', actual, Resources(),
            dict(kind='transform', rule=action.arguments['rule'], external_calls=0))

    def select_only(terminal):
        # run_online normally dispatches execution at this callback. This
        # adapter captures an eligible terminal and explicitly re-labels its
        # report below; it does not execute or manufacture answer rows.
        if selected:
            raise ValueError('More than one selected terminal for one branch')
        selected.append(terminal.payload['plan'])
        return dict(success=True, terminal_selection_only=True)

    controller = run_online(actual, domain, perform=perform, execute=select_only, limits=settings.limits,
                            action_objective=settings.action_objective)
    if not controller['success'] or len(selected) != 1 or controller['external_calls_during_search'] != 0:
        raise CalibrationPlanningError('Branch planning failed without execution: '+str(controller.get('status')),
            dict(source_id=sid, bank=bank, controller=controller, backend_calls=len(information_records),
                 information_records=information_records, probe_calls=len(information_records),
                 final_plan_executions=0, terminal_selection_callbacks=len(selected)))
    plan = selected[0]
    estimate, detail = costs.execution(plan, estimator)
    # Never expose the controller's callback count as backend execution evidence.
    controller.update(status='terminal_selected_without_execution', final_plan_executions=0,
        terminal_selection_callbacks=controller.pop('final_plan_executions'),
        execution_ms=0.0, execution=None, answer_rows=None)
    metadata = dict(bank=bank, source_id=sid, query_sha256=branch['query_sha256'],
        family_sha256=family.identity, selected_plan_identity=identity(plan), selected_plan=plan.to_dict(),
        seed_estimate=seed_estimate, seed_estimate_detail=seed_detail,
        selected_estimate=estimate, selected_estimate_detail=detail, controller=controller,
        preparation_cpu_ms=preparation_cpu_ms, planning_cpu_ms=(time.process_time()-cpu)*1000,
        planning_wall_ms=(time.perf_counter()-started)*1000,
        selected_remote_nodes=sum(n.kind in REMOTE for n in plan.nodes),
        plan_registry_count=len(domain.plans), plan_registry_bytes=domain.plan_bytes,
        certificate_checks=contract.checks, certificate_ms=contract.elapsed_ms,
        source_access=[dict(node_id=n.node_id, kind=n.kind.value,
            compiler=n.parameters['artifact']['parameters'].get('compiler'),
            necessary_row_filters=n.parameters['artifact']['parameters'].get('necessary_row_filters'),
            leaf_witness=n.parameters['artifact']['parameters'].get('leaf_witness'))
            for n in plan.nodes if n.kind in REMOTE],
        final_plan_executions=0, model_calls=0, backend_calls=len(information_records), clarification_calls=0,
        probe_calls=len(information_records), information_records=information_records,
        live_probe_binding=live_binding, settings=asdict(settings))
    return plan, metadata


def _compose(case, selected, parallelism):
    nodes, tagged, identities, versions, bindings, outputs, schemas = [], [], {}, {}, {}, {}, {}
    for branch, plan in zip(case['branches'], selected):
        if len(plan.roots) != 1:
            raise ValueError('A bank partial requires exactly one scalar output root')
        prefix = f"bank{branch['bank']:02d}/"
        rename = {n.node_id: prefix+n.node_id for n in plan.nodes}
        for node in plan.nodes:
            nodes.append(replace(node, node_id=rename[node.node_id],
                inputs=tuple(rename[i] for i in node.inputs),
                semantic_operator_ids=tuple(prefix+i for i in node.semantic_operator_ids)))
        for key, value in plan.metadata.get('source_identities', {}).items():
            if key in identities and identities[key] != value:
                raise ValueError('Different branch snapshots share one backend')
            identities[key] = value
        versions.update(plan.metadata.get('source_snapshot_versions', {}))
        bindings.update({prefix+k: v for k, v in plan.metadata.get('source_bindings', {}).items()})
        outputs.update({prefix+k: rename[v] for k, v in plan.metadata.get('operator_outputs', {}).items() if v in rename})
        schemas.update({prefix+k: v for k, v in plan.metadata.get('schemas', {}).items()})
        tag = prefix+'partial-tag'
        nodes.append(RuntimeNode(tag, R.COORDINATOR_ROW_PROJECT, (rename[plan.roots[0]],),
            dict(projections={'total': dict(kind='field', field='total'),
                              'owner_bank': dict(kind='literal', value=branch['bank'])})))
        tagged.append(tag)
    merged = 'financial-partials/merge'
    nodes.append(RuntimeNode(merged, R.MERGE, tuple(tagged)))
    answer = 'financial-answer/sum'
    nodes.append(RuntimeNode(answer, R.COORDINATOR_GROUP_AGGREGATE, (merged,),
        dict(group_by=[], aggregations={'total': dict(op='sum', field='total', distinct=False)}, allow_global=True)))
    remote = sum(n.kind in REMOTE for n in nodes)
    # Preserve each admitted branch's execution-call allowance. Static remote
    # node count is a descriptor, not an assertion that future bind adapters
    # always issue exactly one transport call per node.
    remote_budget = sum(plan.max_remote_calls for plan in selected)
    if not remote <= remote_budget <= 4096:
        raise ValueError('Composed branch call allowances exceed the calibration bound')
    metadata = dict(financial_composition=dict(profile=VERSION, query_sha256=case['query_sha256'],
        selected_branch_plans=[identity(p) for p in selected], owner_banks=case['banks'],
        proof='Disjoint edge ownership; same-bank witness scope; contribution dedup inside each branch; bank tags prevent equal partial totals collapsing under set union; sum is exact',
        global_joint_search=False, final_runtime_executions_required=1),
        source_identities=identities, source_snapshot_versions=versions,
        source_bindings=bindings, operator_outputs=outputs, schemas=schemas)
    raw = dict(nodes=[n.to_dict() for n in nodes], roots=[answer], max_remote_calls=remote_budget,
               max_parallelism=parallelism, metadata=metadata)
    return FederatedExecutionPlan.from_dict(dict(plan_id='financial:'+fingerprint(raw)[:24], **raw))


def plan_case(case, source_schema, sources, backends, costs=JointCostProfile(), estimator=None, parallelism=4):
    """Return (one executable composed DAG, planning evidence); zero live calls.

    CPU includes validation, lowering, compilation, per-branch current-controller
    search and final composition. controller_planning_cpu_ms records only the
    current controller's search timer for direct attribution. D=2 and H=12 apply
    independently to each of at most 32 compact branches, not to a global family.
    """
    started = time.perf_counter(); cpu = time.process_time()
    if parallelism != 4 or type(parallelism) is not int:
        raise ValueError('Calibration fixes execution parallelism at four')
    expected = next((c for c in build_workload(nodes_per_bank=case['nodes_per_bank'])['cases'] if c['case_id'] == case['case_id']), None)
    if expected != case:
        raise ValueError('Calibration case differs from the frozen recipe')
    if estimator is None or not getattr(estimator, 'strict_relative_units', False):
        raise ValueError('Calibration requires the frozen source-count relative work estimator')
    physical = replace(OneShotPolicy.for_mode('performance'), max_parallelism=parallelism,
                       retrieval_rows_per_relation=None)
    selected, reports = [], []
    for branch in case['branches']:
        try:
            plan, report = _branch(branch, source_schema=source_schema, sources=sources, backends=backends,
                                  costs=costs, estimator=estimator, physical=physical)
        except CalibrationPlanningError as error:
            error.planning_evidence.update(case_id=case['case_id'], completed_branch_reports=reports)
            raise
        selected.append(plan); reports.append(report)
    plan = _compose(case, selected, parallelism)
    result = dict(schema_version=VERSION, method='XGAP', status='planned_without_execution',
        case_id=case['case_id'], query_sha256=case['query_sha256'], plan_identity=identity(plan),
        planning_cpu_ms=(time.process_time()-cpu)*1000, planning_wall_ms=(time.perf_counter()-started)*1000,
        controller_planning_cpu_ms=sum(r['controller']['planning_cpu_ms'] for r in reports),
        branch_planning_cpu_ms=sum(r['planning_cpu_ms'] for r in reports),
        settings=asdict(SETTINGS), branch_count=len(reports), branches=reports,
        algorithm='Current fixed-depth controller per disjoint fixed-query branch, followed by exact scalar partial composition',
        complexity_scope=dict(branches_max=32, compact_operators_per_branch_max=64,
            fixed_depth=2, horizon_per_branch=12, cross_branch_strategy_products_enumerated=False),
        global_joint_search=False, model_calls=0, backend_calls=0, clarification_calls=0,
        scope_confirmation_calls=0, final_plan_executions=0, final_runtime_executions_required=1,
        selected_remote_nodes=sum(n.kind in REMOTE for n in plan.nodes), execution_parallelism=parallelism)
    return plan, result
