"""Offline equivalent-plan pools. No measured winner enters online planning."""
from copy import deepcopy
import json
import math
from pathlib import Path
import random
import statistics

from xgap.agent.intent_certificate import IntentCandidate,IntentFamily,fingerprint
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.practical_planning import _baseline
from xgap.experiments.ch6_fact_index import pin,write
from xgap.experiments.ch6_formal_metrics import terminal_cost_gap
from xgap.experiments.one_shot_profile import FrozenOneShotProfile,read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.runtime.unified_physical import PhysicalMoves,identity
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.compact_query import validate_query

ETA_LEVELS=(0,.05,.1,.2,.5)


def load(ref):return json.loads(read_pinned(ref['path'],ref['sha256']))


def prepare(*,query,profile_path,profile_sha256,reference,output,max_plans=4,repetitions=3,seed=20260923):
    if not 1<=max_plans<=16 or not 1<=repetitions<=6:raise ValueError('Bounded pool/repetitions required')
    query=validate_query(deepcopy(query),version='v2');qhash=fingerprint(query)
    profile=FrozenOneShotProfile.load(profile_path,expected_sha256=profile_sha256)
    doc,_,_,sources,backends,_,modes=profile.materialize();policy=modes['performance'][0]
    snapshot=snapshot_identity(sources,backends,doc['source_schema'])
    ref=load(reference)
    if ref.get('query_sha256')!=qhash or ref.get('source_snapshot_sha256')!=snapshot:
        raise ValueError('Independent reference must identify the exact complete Q and source snapshot')
    family=IntentFamily('offline-cost-pool',(IntentCandidate.create(qhash,query),),(),snapshot,language_version='v2')
    program,assignment=lower_compact_query(query,doc['source_schema'],version='v2',optimize=True)
    initial=_baseline(program,assignment,sources,backends,policy,optimize_reads=False)
    moves=PhysicalMoves(family,doc['source_schema'],backends,policy,sources)
    plans=[initial];seen={identity(initial)};checked=0;ancestry={identity(initial):None}
    for parent in plans:
        if len(plans)>=max_plans:break
        for candidate in moves.neighbors(0,parent):
            checked+=1
            if checked>1024:break
            key=identity(candidate)
            if key in seen:continue
            seen.add(key);ancestry[key]=identity(parent);plans.append(candidate)
            if len(plans)>=max_plans:break
        if checked>1024:break
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    records=[]
    for plan in plans:
        key=identity(plan);p=write_once(root/(key+'.json'),plan.to_dict())
        records.append(dict(plan_id=key,plan=p,query_sha256=qhash,parent_plan_id=ancestry[key],
            derivation=plan.metadata.get('unified_rewrite') if ancestry[key] else 'same complete compact query lowered and compiled',
            structural_equivalence_admitted=True,answer_gate='required',actual_cost=None))
    order=[dict(plan_id=r['plan_id'],repeat=i) for i in range(repetitions) for r in records]
    random.Random(seed).shuffle(order)
    document=dict(schema_version='xgap-ch6-offline-cost-pool-v1',query=query,query_sha256=qhash,
        source_snapshot_sha256=snapshot,profile=dict(path=str(Path(profile_path).resolve()),sha256=profile_sha256),
        reference=reference,plans=records,repetitions=repetitions,order=order,order_seed=seed,
        unit='ms',timing_scope='scheduler_execution_including_observation_transport',statistic='median',
        cache_policy='one fresh serving session; no warmup; randomized repeated schedule; shared cache evolves in that fixed order',
        model_calls=0,online_feedback=False,measurements_read=0,formal_costs_frozen=False,
        method_interpretation='Fixed complete Q and retained pool; not an end-to-end five-method result',
        budget=dict(worker_seconds=180,worker_rss_bytes=3*1024**3,source_rss_bytes=4*1024**3,
                    total_seconds=3600,output_bytes=2*1024**3,free_reserve_bytes=6*1024**3))
    write(root/'pool.json',document);return pin(root/'pool.json')


def freeze(pool,observations,output):
    """No failed trial deletion, unit conversion or imputed cost."""
    if pool['schema_version']!='xgap-ch6-offline-cost-pool-v1':raise ValueError('Pinned pool required')
    planned={(o['plan_id'],o['repeat']) for o in pool['order']};seen=set();costs={r['plan_id']:[] for r in pool['plans']}
    for row in observations:
        key=(row['plan_id'],row['repeat'])
        if key not in planned or key in seen:raise ValueError('Unexpected or duplicated pool observation')
        seen.add(key)
        for field in ('query_sha256','source_snapshot_sha256','unit','timing_scope'):
            if row[field]!=pool[field]:raise ValueError('Mixed fixed-Q/source/cost contract: '+field)
        if not row['success'] or row['answer_em']!=1:raise ValueError('Pool measurement failed or reference differs; do not prune that plan')
        cost=row['actual_cost']
        if type(cost) not in (int,float) or not math.isfinite(cost) or cost<=0:raise ValueError('A real positive cost is required')
        costs[row['plan_id']].append(cost)
    if seen!=planned:raise ValueError('Incomplete offline measurements')
    records=[dict(plan_id=r['plan_id'],query_sha256=pool['query_sha256'],equivalence_admitted=True,
                  actual_cost=statistics.median(costs[r['plan_id']]),measurements=costs[r['plan_id']],plan=r['plan']) for r in pool['plans']]
    normalizer=max(p['actual_cost'] for p in records)
    if normalizer<=0:raise ValueError('Degenerate fixed cost normalizer')
    rng=random.Random(pool['order_seed']);noise={r['plan_id']:rng.uniform(-1,1) for r in records}
    perturbations=[]
    for eta in ETA_LEVELS:
        estimates={r['plan_id']:max(0,r['actual_cost']/normalizer+eta*noise[r['plan_id']]) for r in records}
        actual_eta=max(abs(estimates[r['plan_id']]-r['actual_cost']/normalizer) for r in records)
        perturbations.append(dict(eta=eta,actual_uniform_error=actual_eta,estimates=estimates))
    result=dict(schema_version='xgap-ch6-frozen-cost-pool-v1',query_sha256=pool['query_sha256'],
        source_snapshot_sha256=pool['source_snapshot_sha256'],unit=pool['unit'],timing_scope=pool['timing_scope'],
        pool=records,normalizer=normalizer,normalizer_rule='maximum median cost in the complete prespecified pool',
        perturbations=perturbations,methods=['XGAP','NP','SH','GR','TS'],
        selections_required=True,TS=dict(value=None,status='unscorable_metric',reason='No same-Q same-unit comparable external selection yet'),
        theoretical_scope='2eta only for a witnessed estimated argmin over this exact retained pool',online_feedback=False)
    write(output,result);return result


def score_selection(frozen,eta,selection):
    if selection.get('unit')!=frozen['unit'] or selection.get('timing_scope')!=frozen['timing_scope']:
        return dict(value=None,status='unscorable_metric',reason='Terminal cost unit/timing scope differs',bound_applicable=False)
    return terminal_cost_gap(query_sha256=frozen['query_sha256'],pool=frozen['pool'],selection=selection,
                             eta=eta,normalizer=frozen['normalizer'])
