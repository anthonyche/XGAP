"""Pre-result recipes for the fixed 21-figure study, not executable manifests.

Resolve these recipes against actual admitted unit manifests before release.
Repeated figures and inapplicable knobs point to the same observations. No
reference answers, oracle replies, method outputs or source queries are read.
"""
from collections import Counter
import json

from xgap.experiments.ch6_formal_protocol import DEFAULTS, METHOD_ORDER, matrix, load_pin
from xgap.experiments.batch_cell_identity import validate_cell_id

PARAMETERS = ('depth', 'horizon', 'epsilon', 'probe_price', 'clarification_price')
PROBE_PRICES = (.1, .5, 1, 2, 5)


def live_e7_configuration(base, policy, method, price):
    """New explicit expected-cost study; change only price across its levels."""
    from copy import deepcopy
    from dataclasses import asdict
    from xgap.agent.live_probe import LiveProbePolicy
    if method not in ('XGAP','NP','SH','GR') or type(price) not in (int,float) or price not in PROBE_PRICES:
        raise ValueError('Declared internal method and E7 price level required')
    if not isinstance(policy, LiveProbePolicy) or policy.action_cost <= 0:
        raise ValueError('A positive frozen base probe cost is required')
    out = deepcopy(base); settings = out['settings']
    frozen = json.loads(json.dumps(asdict(policy)))
    if (out['provider'] != 'frozen_compact_model' or settings['information_targets']
            or settings['candidate_weights'] is not None
            or settings.get('live_probe_policy') not in (None, frozen)):
        raise ValueError('Controlled E7 cannot replace another registry, prior or live policy')
    if settings['information_mode'] != ('no_probe' if method == 'NP' else 'all'):
        raise ValueError('E7 method permissions differ')
    settings['limits']['aggregation'] = 'expectation'
    settings['live_probe_policy'] = frozen
    settings['live_probe_policy']['action_cost'] *= 1 if method == 'NP' else price
    out['schema_version'] = 'xgap-unified-run-config-v3'
    return out


def build_live_e7(spec, *, load=load_pin):
    """Separate E7 preparation; never alter/relabel the old inactive recipes."""
    from xgap.agent.live_probe import policy_from_dict
    from xgap.experiments.ch6_formal_protocol import METHODS
    if (set(spec) != {'schema_version','method_results_read','aggregation','base_unit','ts_unit','live_probe_policy'}
            or spec['schema_version'] != 'xgap-ch6-live-e7-input-v1'
            or spec['method_results_read'] != 0 or spec['aggregation'] != 'expectation'):
        raise ValueError('Explicit pre-result live E7 input required')
    policy = policy_from_dict(load(spec['live_probe_policy']))
    base, ts = load(spec['base_unit']), load(spec['ts_unit'])
    bm, tm = load(base['manifest']), load(ts['manifest'])
    if bm['deployment'] != 'rdf' or tm['deployment'] != 'rdf' or bm['prepared'] != tm['prepared']:
        raise ValueError('Controlled E7 and TS reference require the identical RDF source deployment')
    case_ids = sorted(set(base['cell_cases'].values()))
    if not case_ids or len(case_ids) > 64: raise ValueError('Bounded frozen E7 cohort required')
    pairs = {}; ts_cells = {}
    for cell in bm['cells']:
        label = next((k for k,v in METHODS.items() if v == cell['method']), None)
        key = (base['cell_cases'][cell['cell_id']], label)
        if label not in ('XGAP','NP','SH','GR') or key in pairs or 'controlled_state' not in cell:
            raise ValueError('Exactly four controlled methods per frozen case required')
        pairs[key] = cell['cell_id']
        live_e7_configuration(load(cell['config']), policy, label, 1)
    if set(pairs) != {(c,m) for c in case_ids for m in ('XGAP','NP','SH','GR')}:
        raise ValueError('Incomplete four-method controlled cohort')
    for cell in tm['cells']:
        case = ts['cell_cases'][cell['cell_id']]
        if cell['method'] == METHODS['TS'] and case in case_ids:
            if case in ts_cells or 'controlled_state' in cell: raise ValueError('Invalid TS NL reference')
            ts_cells[case] = cell['cell_id']
    if set(ts_cells) != set(case_ids): raise ValueError('TS reference must retain every frozen E7 case')
    units = [dict(unit_id='E7-live-price-'+str(p), price=p,
        methods=['XGAP','NP','SH','GR'] if p == 1 else ['XGAP','SH','GR'], parent=spec['base_unit'])
        for p in PROBE_PRICES]
    units.append(dict(unit_id='E7-TS-fixed', price=None, methods=['TS'], parent=spec['ts_unit']))
    recipes = []
    for price in PROBE_PRICES:
        for method in ('XGAP','NP','SH','GR','TS'):
            unit = 'E7-TS-fixed' if method == 'TS' else 'E7-live-price-'+str(1 if method == 'NP' else price)
            recipes.append(dict(figure='E7', method=method, x_value=price, value=None,
                status='fixed_reference' if method in ('NP','TS') else 'planned',
                timing_scope='nl_reference' if method=='TS' else 'controlled',
                reason='Frozen NL reference; probe price is inapplicable.' if method=='TS' else
                    'Probe disabled; reuse the same observation at every price.' if method=='NP' else
                    'Only the declared acquisition price changes; actual probe selection is not forced.',
                future_cells=[dict(unit_id=unit,cell_id=ts_cells[c] if method=='TS' else pairs[(c,method)]) for c in case_ids]))
    return dict(schema_version='xgap-ch6-live-e7-recipes-v1', recipes=recipes, unit_requests=units,
        case_ids=case_ids, live_probe_policy=spec['live_probe_policy'], probe_axis_active=True,
        aggregation='expectation', method_results_read=0, model_calls=0, backend_calls=0,
        submitted_jobs=0, formal_campaign_ready=False,
        source_scope='Same frozen controlled inputs and RDF deployment; TS retains its separate NL timing boundary',
        counts=dict(positions=25, unique_cases=len(case_ids), method_requests=17*len(case_ids)),
        remaining=['Source/admission and cumulative API/token/wall budget launch audit',
                   'Actual probe eligibility, selections, source work and method results remain unmeasured'])


def build(spec, *, load=load_pin):
    if (spec.get('schema_version') != 'xgap-ch6-figure-recipe-input-v1'
            or spec.get('method_results_read') != 0 or spec.get('repetitions') != 3
            or spec.get('probe_axis_active') is not False):
        raise ValueError('Frozen three-repeat, pre-result, inactive-probe recipe required')
    entries = {}; bundles = {}; seen = set()
    for entry in spec['cohorts']:
        cid = entry['cohort_id']
        if cid in entries: raise ValueError('Duplicate cohort')
        bundle = load(entry['bundle'])
        constructed = (entry['kind'] == 'factor' and bundle.get('schema_version') == 'xgap-ch6-factor-inputs-v1'
            and bundle.get('model_outputs_used') is False)
        if (bundle.get('split') != 'test' and not constructed) or not bundle['cases']:
            raise ValueError('Nonempty held-out cohort required')
        for case in bundle['cases']:
            if case['case_id'] in seen: raise ValueError('Overlapping case identities')
            seen.add(case['case_id'])
        entries[cid] = entry; bundles[cid] = bundle
    overall = [k for k, e in entries.items() if e['kind'] == 'overall']
    if sorted((bundles[k]['dataset'], bundles[k]['deployment']) for k in overall) != [
            (d, t) for d in ('D1', 'D2', 'D3') for t in ('native', 'rdf')]:
        raise ValueError('Exactly one mixed native/RDF cohort per dataset required')
    base = next(k for k in overall if bundles[k]['dataset'] == 'D1' and bundles[k]['deployment'] == 'rdf')
    mechanism_cases = [c for c in bundles[base]['cases'] if c['workload'] == 'W3']
    if not mechanism_cases or {c['stratum'] for c in mechanism_cases} != {'uniform', 'active-anchor'}:
        raise ValueError('Mechanism cohort retains every D1 RDF W3 case and both strata')
    factors = [k for k, e in entries.items() if e['kind'] == 'factor']
    nu = [k for k in factors if bundles[k]['schema_version'] == 'xgap-ch6-factor-inputs-v1']
    if len(nu) != 1: raise ValueError('One actual N/u bundle required')
    nu = nu[0]
    deployments = [k for k in factors if bundles[k]['schema_version'] == 'xgap-ch6-deployment-factor-v1']
    if len(factors) != 7 or len(deployments) != 6:
        raise ValueError('Six materialized source/scale cohorts required')
    defaults = {k: DEFAULTS[k] for k in PARAMETERS}
    units = []; requests = {}; prefixes = set()

    def effective(method, parameters, track):
        if method == 'TS': return {}
        result = {**defaults, **parameters}
        if method in ('SH', 'GR'): result['depth'] = 1
        # No probe target: different price labels do not create new measurements.
        result['probe_price'] = 1
        return result

    def key(cid, case, method, track, parameters, repeat):
        return (cid, case['case_id'], method, track,
                json.dumps(effective(method, parameters, track), sort_keys=True), repeat)

    def add(cid, cases, methods, track, parameters, prefix, existing=False):
        needed = []
        for method in methods:
            present = [key(cid, c, method, track, parameters, r) in requests for c in cases for r in range(3)]
            if any(present) and not all(present): raise ValueError('Partially overlapping execution group')
            if not any(present): needed.append(method)
        if not needed: return
        if prefix in prefixes: raise ValueError('Duplicate unit prefix')
        prefixes.add(prefix)
        group = dict(cohort_id=cid, bundle=entries[cid]['bundle'], unit_prefix=prefix,
            case_ids=[c['case_id'] for c in cases], methods=needed, input_track=track,
            parameters={**defaults, **parameters}, repetitions=3, existing_preparation=existing,
            figures=[], manifest_resolution='required',
            ts_nl_reference=track == 'nl' and cid in deployments)
        units.append(group)
        for case in cases:
            for method in needed:
                for repeat in range(3):
                    requests[key(cid, case, method, track, parameters, repeat)] = dict(
                        unit_id=prefix + '-r' + str(repeat), cell_id=validate_cell_id(case['case_id'] + '-' + method),
                        case_id=case['case_id'], method=method, input_track=track, repeat=repeat,
                        group=group)

    for cid, entry in entries.items():
        track = 'nl' if cid in overall else 'controlled'
        methods = METHOD_ORDER if track == 'nl' and bundles[cid]['deployment'] == 'rdf' else METHOD_ORDER[:-1]
        add(cid, bundles[cid]['cases'], methods, track, {}, entry['unit_prefix'], True)
    add(base, mechanism_cases, METHOD_ORDER[:-1], 'controlled', {}, 'D1-mechanism-default')
    axes = dict(depth=(1, 2, 3, 5, 10), horizon=(2, 4, 8, 12, 16),
                epsilon=('0', '1/6', '1/3', '1/2', '1'), clarification_price=(.1, .5, 1, 2, 5))
    for axis, levels in axes.items():
        for level in levels:
            add(base, mechanism_cases, METHOD_ORDER[:2] if axis == 'depth' else METHOD_ORDER[:-1],
                'controlled', {axis: level}, 'D1-mechanism-' + axis + '-' + str(level).replace('/', '_'))
    for cid in deployments:
        add(cid, bundles[cid]['cases'], ['TS'], 'nl', {}, cid + '-TS-nl-reference')

    def refs(cid, cases, method, track, parameters, figure):
        result = []
        for c in cases:
            for repeat in range(3):
                item = requests[key(cid, c, method, track, parameters, repeat)]
                if figure not in item['group']['figures']: item['group']['figures'].append(figure)
                result.append({k: item[k] for k in ('unit_id', 'cell_id')})
        return result

    recipes = []
    for row in matrix():
        fig, method, level = row['figure'], row['method'], row['x_value']
        recipe = dict(figure=fig, method=method, x_value=level, value=None,
            timing_scope=row['timing_scope'], future_cells=[],
            status='fixed_reference' if row['configuration_kind'] == 'fixed_reference' else 'planned',
            reason=row['reason'])
        if fig == 'F6':
            recipe.update(status='pending_offline_audit_binding', evidence_role='retained_F6_sensitivity',
                source_unit_id=entries[base]['unit_prefix'] + '-r0')
        elif method == 'TS' and row['y_metric'] == 'planning_ms':
            recipe.update(status='unscorable_metric', evidence_role='TS_original_interface')
        elif fig in ('E1', 'E2', 'F1', 'F2', 'F7', 'F8', 'C1'):
            for cid in overall:
                bundle = bundles[cid]
                if method == 'TS' and bundle['deployment'] == 'native': continue
                wanted_dataset = level if fig in ('E1', 'E2', 'F1', 'F2') else 'D1'
                if bundle['dataset'] != wanted_dataset: continue
                cases = bundle['cases']
                if fig in ('F7', 'F8'): cases = [c for c in cases if c['workload'] == 'W3']
                if fig == 'C1': cases = mechanism_cases[:1] if cid == base else []
                recipe['future_cells'] += refs(cid, cases, method, 'nl', {}, fig)
            if fig == 'C1':
                recipe['future_cells'] = [c for c in recipe['future_cells'] if c['unit_id'].endswith('-r0')]
                recipe['preselection'] = 'First frozen D1 RDF W3 case, repeat 0, even if its outcome fails'
        elif fig in ('S2', 'S3', 'S4'):
            axis = row['x_factor']
            selected = [k for k in deployments if bundles[k]['factor'] == axis and bundles[k]['level'] == level]
            if len(selected) != 1: raise ValueError('Unique deployment per actual factor level required')
            cid = selected[0]
            recipe['future_cells'] = refs(cid, bundles[cid]['cases'], method,
                'nl' if method == 'TS' else 'controlled', {}, fig)
            if method == 'TS': recipe['reason'] += ' Original NL on the level-specific snapshot; not a controlled input.'
        elif method == 'TS':
            recipe['status'] = 'fixed_reference'
            recipe['future_cells'] = refs(base, mechanism_cases, method, 'nl', {}, fig)
            recipe['reason'] += ' Reuse all D1 RDF W3 NL cases; independent reference cohort, no paired controlled/NL speedup.'
        elif fig in ('E3', 'E4', 'S1'):
            factor = 'u' if fig == 'E4' else 'N'
            cases = [c for c in bundles[nu]['cases'] if c['factor'] == factor and c['level'] == level]
            if not cases or {c['stratum'] for c in cases} != {'uniform', 'active-anchor'}:
                raise ValueError('Missing actual factor stratum')
            recipe['future_cells'] = refs(nu, cases, method, 'controlled', {}, fig)
        else:
            parameters = {row['x_factor']: row['defaults'][row['x_factor']]}
            if fig == 'E7':
                parameters = {}; recipe.update(status='fixed_reference', inactive_factor=True,
                    reason='No registered probe target; reuse the default observations at every price. No sensitivity claim.')
            recipe['future_cells'] = refs(base, mechanism_cases, method, 'controlled', parameters, fig)
        if recipe['status'] in ('planned', 'fixed_reference') and not recipe['future_cells']:
            raise ValueError('A proposed plot position has no real input recipe')
        recipes.append(recipe)
    referenced = {(c['unit_id'], c['cell_id']) for r in recipes for c in r['future_cells']}
    if referenced != {(r['unit_id'], r['cell_id']) for r in requests.values()}:
        raise ValueError('Do not schedule requests unused by the figure plan')
    counts = Counter((r['method'], r['input_track']) for r in requests.values())
    return dict(schema_version='xgap-ch6-figure-recipes-v1', formal_campaign_ready=False,
        method_results_read=0, model_calls=0, backend_calls=0, submitted_jobs=0,
        recipes=recipes, unit_requests=units,
        counts=dict(figures=len({r['figure'] for r in recipes}), positions=len(recipes),
            overall_unique_cases=sum(len(bundles[k]['cases']) for k in overall),
            factor_unique_cases=sum(len(bundles[k]['cases']) for k in factors),
            proposed_method_requests=len(requests), execution_groups=len(units),
            proposed_requests_by_method_track=[dict(method=m, input_track=t, count=n) for (m, t), n in sorted(counts.items())]),
        unresolved=['Actual admitted manifests and input pins for every recipe',
            'TS factor-specific NL runtime metadata and support declaration',
            'Pinned F6 serving-contract match', 'Global API/token/wall reservations',
            'Complete release audit and launch authorization'])
