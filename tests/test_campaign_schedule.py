"""New order/at-most-once boundaries only; no native engines or interpretation."""
from collections import Counter
import json

from xgap.experiments.campaign_schedule import balanced_orders, dispatch_one_group, freeze_schedule, METHODS
from xgap.experiments.one_shot_records import write_once


def test_balanced_orders_and_frozen_nl_denominator_without_gold_reads(tmp_path):
    for methods in METHODS.values():
        orders=balanced_orders(methods)
        for position in range(len(methods)):
            assert len(set(Counter(r[position] for r in orders).values()))==1
        pairs=Counter(pair for r in orders for pair in zip(r,r[1:]))
        assert len(pairs)==len(methods)*(len(methods)-1) and len(set(pairs.values()))==1
    dataset={'dataset_id':'tiny','version':'controlled'}
    population=write_once(tmp_path/'population.json',{'schema_version':'xgap-finbench-one-shot-population-v1',
        'dataset':dataset,'artifacts':[{'question_id':str(i),'split':'evaluation','family':'synthetic-order-only',
            'files':{'request':{'path':'unopened-nl'},'reference':{'path':'unopened-reference'},'gold':{'path':'unopened-gold'}}}
            for i in range(48)]})
    profile=write_once(tmp_path/'profile.json',{'dataset':dataset})
    pin=freeze_schedule(population_path=population['path'],population_sha256=population['sha256'],
        profile_path=profile['path'],profile_sha256=profile['sha256'],track='natural_language',output=tmp_path/'schedule.json')
    schedule=json.loads(open(pin['path']).read())
    assert len(schedule['cells'])==192 and schedule['maximum_model_calls']==192
    assert not any('fixed_semantics_input' in c for c in schedule['cells'])
    assert len({c['question_id'] for c in schedule['cells']})==48
    assert set(Counter((c['method'],c['method_position']) for c in schedule['cells']).values())=={12}


def test_partial_journal_never_retries_and_stops_at_one_group(tmp_path):
    cells=[{'cell_id':f'c{i}','block':0,'group_index':i//4,'method':str(i%4),
        'question_id':str(i//4),'track':'natural_language'} for i in range(8)]
    pin=write_once(tmp_path/'schedule.json',{'schema_version':'xgap-balanced-campaign-schedule-v1','cells':cells})
    ledger=tmp_path/'ledger';(ledger/'c0').mkdir(parents=True)  # Interrupted before the durable intent.
    called=[]
    def execute(c,output):
        called.append(c['cell_id']);output.mkdir()
        if c['cell_id']=='c1':raise RuntimeError('controlled failure after dispatch')
        return write_once(output/'receipt.json',{k:c[k] for k in ('method','question_id','track')})
    args={'schedule_path':pin['path'],'schedule_sha256':pin['sha256'],'ledger':ledger,'execute':execute}
    r=dispatch_one_group(**args,ready=lambda c:{'ready':True})
    assert called==['c1','c2','c3'] and r[0]['status']=='indeterminate_prior_intent'
    assert r[1]['status']=='dispatch_failed'
    paused=dispatch_one_group(**args,ready=lambda c:{'ready':False,'reason':'owned hosts unavailable'})
    assert paused[-1]['status']=='unrun_prerequisite' and not (ledger/'c4').exists()
    dispatch_one_group(**args,ready=lambda c:{'ready':True})
    assert called==['c1','c2','c3','c4','c5','c6','c7']
