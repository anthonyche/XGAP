"""Post-seal metrics and clustered summaries; never called by the planner."""
from collections import defaultdict
import math
import random
import statistics

from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.ch6_metrics import trace_cost

# Published before outcomes. These are work units, not dollars or predicted ms.
# Source calls are not double-counted with their parent federation requests.
DEFAULT_WEIGHTS={'backend_http_attempts':1.0,'clarification_calls':1.0,'transferred_bytes':1/1048576}


def extract_metrics(*,outcome_pin,score_pin,timing_pin,loss_pin=None,weights=DEFAULT_WEIGHTS):
    trial=load_pin(outcome_pin);score=load_pin(score_pin);timing=load_pin(timing_pin)
    if (score['receipt_sha256']!=outcome_pin['sha256'] or timing['receipt']['sha256']!=outcome_pin['sha256']):
        raise ValueError('Metric inputs do not refer to the same sealed request')
    observed=trial.get('source_observations') or {}
    byte_fields=('request_body_bytes','request_target_bytes','response_body_bytes')
    transferred=sum(observed[k] for k in byte_fields) if all(k in observed for k in byte_fields) else None
    actual=dict(backend_http_attempts=observed.get('requests'),clarification_calls=trial.get('clarification_calls'),
                transferred_bytes=transferred)
    cost=trace_cost(actual,weights)
    loss=load_pin(loss_pin) if loss_pin else None
    if loss and loss['receipt_sha256']!=outcome_pin['sha256']:raise ValueError('Loss receipt differs')
    # Historical seals are immutable. Correct their interpretation here when an
    # observer limit cut off the method; this is not evidence of a wrong answer.
    harness=trial.get('harness_failures') or {}
    categories={k for failures in harness.values() for k in failures if k.startswith('harness_')}
    censored=(trial.get('failure_scope')=='study_budget_censoring_not_method_incorrectness'
              or bool(categories) or trial['status'] in ('harness_observation_failure','supervisor_failed','guard_monitor_failed'))
    if censored:
        scored_em=scored_f1=None
    else:scored_em=score['answer_em'];scored_f1=score['answer_row_multiset_f1']
    return dict(method_id=trial['method'],question_id=trial['question_id'],dataset=trial['dataset'],
        timing_scope='nl' if trial['track'].startswith('natural_language') else trial['track'],
        execution_success=trial['success'],status=trial['status'],study_censored=censored,
        e2e_ms=timing['total_online_ms'],request_ms=timing['total_online_ms'],planning_ms=trial.get('planning_ms'),
        answer_em=scored_em,answer_f1=scored_f1,
        answer_coverage=None if censored else int(bool(trial['success'] and not score['comparison_error'])),
        interpretation_loss=loss.get('loss') if loss and loss['status']=='measured' else None,
        interpretation_loss_status=loss['status'] if loss else 'unscorable_metric',
        certificate_violation=loss.get('certificate_violation') if loss else None,
        backend_calls=observed.get('requests'),backend_forwarded_calls=observed.get('forwarded_requests'),
        backend_failed_calls=observed.get('failed_requests'),transferred_bytes=transferred,
        clarification_calls=actual['clarification_calls'],trace_cost=cost['trace_cost'],trace_cost_audit=cost,
        coordinator_rss_bytes=((trial.get('resources') or {}).get('sampled_peak_rss_bytes') or {}).get('method'),
        model_calls=trial.get('model_calls'),input_tokens=trial.get('input_tokens'),output_tokens=trial.get('output_tokens'),
        evidence=dict(outcome=outcome_pin,score=score_pin,timing=timing_pin,loss=loss_pin))


def clustered_summary(rows,metric,*,statistic='mean',bootstrap=2000,seed=20260923):
    """Mean repetitions within cases, then resample complete template clusters.

    Call separately for each declared sampling stratum/workload. Repeated
    reference rows must already have been deduplicated by observation identity.
    """
    if statistic not in ('mean','max'):raise ValueError('Unknown statistic')
    cases={};seen=set();missing=0
    for row in rows:
        identity=(row['case_id'],row['repeat'])
        if identity in seen:raise ValueError('A repeated reference is not a new sample')
        seen.add(identity)
        value=row.get(metric)
        if value is None:missing+=1;continue
        if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Nonfinite measurement')
        key=(row['family_id'],row['case_id']);cases.setdefault(key,[]).append(value)
    if not cases:return dict(value=None,ci_low=None,ci_high=None,cases=0,families=0,missing_observations=missing)
    # Maximum interpretation loss is over every actual trial, not averaged repeats.
    reduce=max if statistic=='max' else statistics.mean
    clusters=defaultdict(list)
    for (family,_),values in cases.items():clusters[family].append(reduce(values))
    values=[v for group in clusters.values() for v in group];value=reduce(values)
    names=sorted(clusters);interval=(None,None)
    if statistic=='mean' and len(names)>=2 and bootstrap>0:
        rng=random.Random(seed);samples=[]
        for _ in range(bootstrap):
            sample=[v for name in rng.choices(names,k=len(names)) for v in clusters[name]]
            samples.append(statistics.mean(sample))
        samples.sort();interval=(samples[int(.025*(bootstrap-1))],samples[int(.975*(bootstrap-1))])
    return dict(value=value,ci_low=interval[0],ci_high=interval[1],cases=len(cases),families=len(names),
                missing_observations=missing,statistic=statistic,ci='clustered percentile' if interval[0] is not None else 'not estimated')


def terminal_cost_gap(*,query_sha256,pool,selection,eta,normalizer):
    """Audit an offline cost-sensitivity observation, not an online plan oracle."""
    if type(eta) not in (int,float) or eta<0 or not math.isfinite(eta):raise ValueError('Invalid eta')
    if type(normalizer) not in (int,float) or normalizer<=0 or not math.isfinite(normalizer):raise ValueError('Invalid cost normalizer')
    for p in pool:
        if p['query_sha256']!=query_sha256 or p.get('equivalence_admitted') is not True:
            raise ValueError('Cost pool must contain equivalent plans for the fixed Q')
        if not math.isfinite(p['actual_cost']) or p['actual_cost']<0:raise ValueError('Invalid measured cost')
    if not pool:raise ValueError('An eligible retained pool is required')
    if selection.get('query_sha256')!=query_sha256 or selection.get('equivalence_admitted') is not True:
        return dict(value=None,status='unscorable_metric',reason='Selected query not proven equivalent to the fixed Q',bound_applicable=False)
    if selection.get('actual_cost') is None:
        return dict(value=None,status='unscorable_metric',reason='Comparable terminal cost unavailable',bound_applicable=False)
    actual=selection['actual_cost']
    if not math.isfinite(actual) or actual<0:raise ValueError('Invalid selected cost')
    uses_estimator=selection.get('uses_perturbed_estimator') is True
    bound=False
    if uses_estimator:
        estimates=selection['estimates'];ids={p['plan_id'] for p in pool}
        if set(estimates)!=ids:raise ValueError('Estimates do not cover the frozen pool')
        if any(not math.isfinite(estimates[p['plan_id']]) or abs(estimates[p['plan_id']]-p['actual_cost']/normalizer)>eta+1e-12 for p in pool):
            raise ValueError('Injected errors exceed the declared uniform bound')
        selected=selection['plan_id']
        if selected not in ids:raise ValueError('Selected plan outside the audited pool')
        expected=next(p['actual_cost'] for p in pool if p['plan_id']==selected)
        if actual!=expected:raise ValueError('Selected cost differs from its frozen measurement')
        bound=estimates[selected]==min(estimates.values())
    gap=(actual-min(p['actual_cost'] for p in pool))/normalizer
    return dict(value=gap,status='measured' if uses_estimator else 'fixed_reference',
        bound_applicable=bound,two_eta=2*eta if bound else None,
        bound_violation=gap>2*eta+1e-12 if bound else None,
        scope='relative to the fixed retained pool, not a global optimum or a policy ratio')
