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


def snapshot_identity(sources, backends, schema):
    return fingerprint({'sources': {k: [s.snapshot_version, s.replica_backend_ids] for k, s in sources.items()},
        'backends': {k: {**asdict(b), 'profile': b.profile.to_dict() if b.profile else None}
            for k, b in backends.items()}, 'source_schema': schema})


def run_family_query(question, contract, oracle, *, source_schema, sources, backends, backend_clients,
                     physical_profile, **options):
    started = time.perf_counter(); family = contract.family
    if family.source_snapshot != snapshot_identity(sources, backends, source_schema):
        raise ValueError('Intent certificate belongs to a different source/mapping snapshot')
    if physical_profile.retrieval_rows_per_relation is not None:
        raise ValueError('Intent distance does not authorize truncating query results')
    at = time.perf_counter()
    admitted, capabilities = lookup_practical_capabilities(sources, backends, backend_clients)
    capability_ms = (time.perf_counter()-at)*1000

    def prepare(candidate, certificate):
        program, assignment = lower_compact_query(json.loads(candidate.query_json), source_schema,
            version=family.language_version, optimize=True)
        if len(program.operators) > physical_profile.max_operators:
            raise ValueError('Candidate exceeds the admitted operator bound')
        if program.holes:
            raise ValueError('Finite-family execution requires complete semantic candidates; unresolved entity hole')
        return _baseline(program, assignment, admitted, backends, physical_profile)

    def execute(plan):
        registry = BackendPluginRegistry()
        for backend in {n.parameters['backend_id'] for n in plan.nodes if 'backend_id' in n.parameters}:
            registry.register(NativeBackendPlugin(backend, backend_clients[backend]))
        result = FederatedExecutionTool(FederatedScheduler(BackendInvokeTool(registry), retention='roots')).invoke(
            {'plan': plan.to_dict()}, ToolContext('finite-intent', 0, 'final'))
        return dict(success=result.status is ToolStatus.SUCCESS, result=result.to_dict(),
            physical_plan=plan.to_dict(), answer_rows=(result.value or {}).get('final_rows'))

    report = run_intent_policy(question, contract, oracle, prepare=prepare, execute=execute, **options)
    report['capability_lookup'] = capabilities
    report['capability_lookup_ms'] = capability_ms
    report['adapter_end_to_end_ms'] = (time.perf_counter()-started)*1000
    return report
