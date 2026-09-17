"""Finite-family semantic terminals wired to existing compiler and scheduler.

No changes to the legacy NL or practical strong profiles. This restricted entry
accepts complete compact queries with literal entity constraints, not holes.
"""
import json
import time
from dataclasses import asdict

from xgap.agent.intent_certificate import fingerprint
from xgap.agent.intent_policy import run_intent_policy
from xgap.agent.practical_planning import _baseline
from xgap.agent.practical_tools import lookup_practical_capabilities
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.tool import FederatedExecutionTool
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin
from xgap.tools.contracts import ToolContext, ToolStatus
from xgap.runtime.one_shot_planning import prepare_one_shot_domain


def snapshot_identity(sources, backends, schema):
    return fingerprint({'sources': {k: [s.snapshot_version, s.replica_backend_ids] for k, s in sources.items()},
        'backends': {k: {**asdict(b), 'profile': b.profile.to_dict() if b.profile else None}
            for k, b in backends.items()}, 'source_schema': schema})


def family_runtime(family, *, source_schema, sources, backends, backend_clients, physical_profile,
                   joint_cost=None, estimator=None, planning_deadline=None):
    """Shared lazy preparation and one-final-execution callbacks for both controllers."""
    if family.source_snapshot != snapshot_identity(sources, backends, source_schema):
        raise ValueError('Intent certificate belongs to a different source/mapping snapshot')
    if physical_profile.retrieval_rows_per_relation is not None:
        raise ValueError('Intent distance does not authorize truncating query results')
    at = time.perf_counter()
    admitted, capabilities = lookup_practical_capabilities(sources, backends, backend_clients)
    capability_ms = (time.perf_counter()-at)*1000

    def checkpoint():
        if planning_deadline is not None and time.perf_counter() >= planning_deadline:
            raise TimeoutError('Optional physical improvement reached planning deadline')

    def prepare(candidate, certificate):
        program, assignment = lower_compact_query(json.loads(candidate.query_json), source_schema,
            version=family.language_version, optimize=True)
        if len(program.operators) > physical_profile.max_operators:
            raise ValueError('Candidate exceeds the admitted operator bound')
        if program.holes:
            raise ValueError('Finite-family execution requires complete semantic candidates; unresolved entity hole')
        baseline = _baseline(program, assignment, admitted, backends, physical_profile)
        if joint_cost is None:
            return baseline
        # Retain the independently feasible seed if optional neighborhood
        # generation is unavailable; never execute alternatives to select one.
        plans = [baseline]
        domain = {'status': 'baseline_only'}
        try:
            alternatives, domain = prepare_one_shot_domain(program, operator_sources=assignment,
                sources=admitted, backends=backends, policy=physical_profile,
                progressive_bindings=True, shared_native_reads=True, source_row_prefilters=True,
                planning_checkpoint=checkpoint)
            plans.extend(c.plan for c in alternatives)
        except (ValueError, TimeoutError) as error:
            domain = {'status': 'optional_domain_unavailable', 'reason': str(error)}
        scored = [(joint_cost.execution(baseline, estimator), 0, baseline)]
        for index, candidate_plan in enumerate(plans[1:], 1):
            try:
                checkpoint()
            except TimeoutError:
                domain = {**domain, 'scoring_stopped': 'planning_deadline'}
                break
            scored.append((joint_cost.execution(candidate_plan, estimator), index, candidate_plan))
        (score, evidence), _, plan = min(scored, key=lambda item: (item[0][0], item[1]))
        from dataclasses import replace
        return replace(plan, metadata={**plan.metadata, 'joint_execution_cost': score,
            'joint_execution_estimate': evidence, 'joint_physical_domain': domain,
            'joint_compared_plans': len(scored), 'alternative_executions': 0})

    def execute(plan):
        registry = BackendPluginRegistry()
        for backend in {n.parameters['backend_id'] for n in plan.nodes if 'backend_id' in n.parameters}:
            registry.register(NativeBackendPlugin(backend, backend_clients[backend]))
        result = FederatedExecutionTool(FederatedScheduler(BackendInvokeTool(registry), retention='roots')).invoke(
            {'plan': plan.to_dict()}, ToolContext('finite-intent', 0, 'final'))
        return dict(success=result.status is ToolStatus.SUCCESS, result=result.to_dict(),
            physical_plan=plan.to_dict(), answer_rows=(result.value or {}).get('final_rows'))

    return prepare, execute, capabilities, capability_ms


def run_family_query(question, contract, oracle, *, source_schema, sources, backends, backend_clients,
                     physical_profile, **options):
    started = time.perf_counter()
    prepare, execute, capabilities, capability_ms = family_runtime(contract.family,source_schema=source_schema,
        sources=sources,backends=backends,backend_clients=backend_clients,physical_profile=physical_profile)
    report = run_intent_policy(question, contract, oracle, prepare=prepare, execute=execute, **options)
    report['capability_lookup'] = capabilities
    report['capability_lookup_ms'] = capability_ms
    report['adapter_end_to_end_ms'] = (time.perf_counter()-started)*1000
    return report
