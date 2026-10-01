"""F6 isolates the real terminal selector on one already eligible retained pool.

No interpretation, information acquisition, physical-pool search, or backend
execution occurs here. The four internal variants share this selector, so their
curves are expected to coincide. This is not a five-method end-to-end comparison.
"""
from dataclasses import asdict

from xgap.agent.intent_certificate import IntentCandidate, IntentFamily, fingerprint
from xgap.agent.unified_contract import UnifiedTerminalContract
from xgap.agent.unified_family import FamilyDomain, FamilyState, UnifiedSettings
from xgap.agent.unified_lookahead import Limits, Resources, State, Terminal, choose
from xgap.experiments.ch6_cost_pool import load, score_selection
from xgap.experiments.ch6_formal_protocol import METHODS
from xgap.experiments.unified_contract import validate_method
from xgap.runtime.contracts import FederatedExecutionPlan
from xgap.runtime.unified_physical import identity


def select(query, snapshot, plans, estimates, method, *, language_version='v2'):
    """Only estimates enter the shared controller; actual costs are not an input."""
    if method not in ('XGAP', 'NP', 'SH', 'GR'):
        raise ValueError('External TS cannot be replaced by the XGAP selector')
    if not 1 <= len(plans) <= 16 or set(estimates) != {identity(p) for p in plans}:
        raise ValueError('An explicit bounded retained pool and complete estimates are required')
    family=IntentFamily('F6-fixed-complete-Q', (IntentCandidate.create(fingerprint(query), query),), (), snapshot,
        coverage_basis='offline fixed complete query, independently admitted equivalent pool', language_version=language_version)
    contract=UnifiedTerminalContract(family, ())
    settings=UnifiedSettings(limits=Limits(depth=1 if method in ('SH','GR') else 2, horizon=12),
        plan_pool=len(plans), information_mode='no_probe' if method=='NP' else 'all',
        action_objective='myopic' if method=='GR' else 'continuation')
    validate_method(METHODS[method], settings)

    class FrozenEstimates:
        def execution(self, plan, estimator):
            return estimates[identity(plan)], None

    domain=FamilyDomain('offline fixed complete Q', contract, {0:(plans[0], 0, Resources())},
        FrozenEstimates(), authority_name='offline-complete-Q', authority_version=fingerprint(query), settings=settings)
    keys=tuple(domain.store(0, plan, protected=True) for plan in plans)
    state=FamilyState(pools=((0, keys),))
    decision=choose(State(state), domain, limits=settings.limits, action_objective=settings.action_objective)
    terminal=decision['choice']
    if not isinstance(terminal, Terminal) or not domain.check_terminal(state, terminal):
        raise ValueError('No valid terminal selected from the independently admitted pool')
    return dict(plan_id=identity(terminal.payload['plan']), estimated_cost=terminal.estimated_cost,
        terminal_key=terminal.key, status=decision['status'], expanded_states=decision['expanded_states'],
        selection_ms=decision['elapsed_ms'], settings=asdict(settings),
        scope='fixed eligible retained pool terminal selection only', backend_calls=0, model_calls=0)


def study(pool, frozen):
    for key in ('query_sha256', 'source_snapshot_sha256', 'unit', 'timing_scope'):
        if pool[key] != frozen[key]:
            raise ValueError('F6 complete-query/source/measurement identity mismatch')
    if fingerprint(pool['query']) != pool['query_sha256']:
        raise ValueError('Fixed complete query changed')
    originals={p['plan_id']:p for p in pool['plans']}
    if len(originals)!=len(pool['plans']) or set(originals)!={p['plan_id'] for p in frozen['pool']}:
        raise ValueError('Measured and declared pools differ')
    plans=[]
    for record in frozen['pool']:
        if not record['equivalence_admitted'] or record['plan']!=originals[record['plan_id']]['plan']:
            raise ValueError('Measured plan lacks the original identity/equivalence gate')
        plan=FederatedExecutionPlan.from_dict(load(record['plan']))
        if identity(plan)!=record['plan_id']:
            raise ValueError('Executable plan identity differs')
        plans.append(plan)
    costs={p['plan_id']:p['actual_cost'] for p in frozen['pool']}
    rows=[]
    for perturbation in frozen['perturbations']:
        for method in METHODS:
            if method=='TS':
                rows.append(dict(method=method, eta=perturbation['eta'], value=None, status='unscorable_metric',
                    reason='Original TS exposes no comparable selection on this fixed same-Q same-unit pool', bound_applicable=False))
                continue
            picked=select(pool['query'], pool['source_snapshot_sha256'], plans, perturbation['estimates'], method)
            selection=dict(plan_id=picked['plan_id'], query_sha256=pool['query_sha256'], equivalence_admitted=True,
                actual_cost=costs[picked['plan_id']], unit=pool['unit'], timing_scope=pool['timing_scope'],
                uses_perturbed_estimator=True, estimates=perturbation['estimates'])
            rows.append(dict(method=method, eta=perturbation['eta'], selection=picked,
                             **score_selection(frozen, perturbation['eta'], selection)))
    return dict(schema_version='xgap-ch6-terminal-cost-sensitivity-v1', success=True, rows=rows,
        model_calls=0, backend_calls=0, complete_query=pool['query_sha256'],
        scope='Offline terminal subproblem only; internal variants share the same selector and may coincide',
        excluded='No end-to-end or global-plan optimality claim; no measured-winner online feedback')
