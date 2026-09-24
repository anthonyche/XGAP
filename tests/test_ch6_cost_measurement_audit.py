"""Audit fixtures are artificial records, never reported experimental costs."""
from copy import deepcopy
from pathlib import Path
import pytest

from audit_ch6_cost_measurement import audit
from xgap.agent.intent_certificate import fingerprint
from xgap.experiments.ch6_cost_pool import freeze, load
from xgap.experiments.one_shot_records import write_once


def evidence(root):
    def save(name, value):return write_once(root/(name+'.json'), value)
    profile=save('profile', {})
    seal=save('seal', dict(profile=profile))
    prepared=save('prepared', dict(success=True, profile=profile, input_seal=seal))
    ready=save('ready', dict(prepared=prepared, preparation_input=seal, profile=profile,
        source_runtime=None, tdb2_file_mode='default', experimental_lazy_range=False, query_timeout_seconds=60))
    reference=save('reference', dict(query_sha256=fingerprint({}), source_snapshot_sha256='snapshot',
        rows=[{'n':3}], normalization=dict(schema_version='xgap-row-normalization-v1', fields={'n':'integer'})))
    pool=dict(schema_version='xgap-ch6-offline-cost-pool-v1', query={}, query_sha256=fingerprint({}),
        source_snapshot_sha256='snapshot', profile=profile, reference=reference, plans=[dict(plan_id='a', plan={})],
        repetitions=1, order=[dict(plan_id='a', repeat=0)], order_seed=2, unit='ms', timing_scope='scheduler',
        budget={'source_rss_bytes':4*1024**3})
    pool_pin=save('pool', pool)
    intent=save('intent', dict(pool=pool_pin, prepared=prepared, source_commit='a'*40, source_runtime=None,
        source_storage='node_local', source_budget={'timeout_seconds':60}))
    placement=save('placement', dict(separate=True, shared_method_contract=True, query_warmup_calls=0))
    answer=save('answer', dict(rows=[{'n':3}]))
    worker=save('worker', dict(success=True, model_calls=0, plan_id='a', execution_ms=10, pool=pool_pin,
        profile=profile, answer=answer))
    guard=save('guard', dict(success=True))
    rows=[dict(plan_id='a', repeat=0, query_sha256=pool['query_sha256'], source_snapshot_sha256='snapshot',
        unit='ms', timing_scope='scheduler', success=True, answer_em=1, actual_cost=10,
        guard=guard, worker=worker, source_observations={'failed_requests':0})]
    costs=freeze(pool, rows, root/'costs.json')
    from xgap.experiments.ch6_fact_index import pin
    measurement=dict(success=True, online_feedback=False, pool=pool_pin, prepared=prepared, intent=intent,
        source_commit='a'*40, source_ready=ready, storage_placement=placement, observations=rows,
        frozen_costs=pin(root/'costs.json'), closure={k:True for k in
        ('owned_groups_drained','owned_processes_terminal','observer_stopped','serving_copy_reclamation_complete')})
    return pool_pin, measurement, save


def test_recomputes_answers_costs_and_closure(tmp_path):
    pool, measured, save=evidence(tmp_path)
    result=load(audit(pool, save('measurement', measured), tmp_path/'audit.json'))
    assert result['trials']==1 and result['answers_rechecked'] and result['medians_recomputed']


@pytest.mark.parametrize('mutation', ['cost','answer','storage','closure','normalizer'])
def test_rejects_plausible_summary_with_wrong_raw_evidence(tmp_path, mutation):
    pool, measured, save=evidence(tmp_path)
    if mutation=='cost':measured['observations'][0]['actual_cost']=9
    elif mutation=='answer':
        worker=load(measured['observations'][0]['worker']);worker['answer']=save('wrong-answer',dict(rows=[{'n':4}]))
        measured['observations'][0]['worker']=save('wrong-worker',worker)
    elif mutation=='storage':measured['storage_placement']=save('wrong-storage',dict(separate=False,shared_method_contract=True,query_warmup_calls=0))
    elif mutation=='closure':measured['closure']['owned_groups_drained']=False
    else:
        costs=load(measured['frozen_costs']);costs['normalizer']=99
        measured['frozen_costs']=save('wrong-costs',costs)
    with pytest.raises(ValueError):audit(pool,save('wrong-measurement',measured),tmp_path/'must-not-publish.json')
    assert not (tmp_path/'must-not-publish.json').exists()
