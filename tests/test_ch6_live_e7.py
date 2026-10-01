"""Live E7 measures an actual policy price, preserving inputs and fixed methods."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from prepare_ch6_live_e7 import prepare
from release_ch6_five_method_batch import configuration_for
from xgap.agent.live_probe import LiveProbePolicy
from xgap.experiments.ch6_formal_protocol import METHODS, load_pin
from xgap.experiments.ch6_figure_bindings import audit_bindings
from xgap.experiments.ch6_figure_recipes import build_live_e7, live_e7_configuration, PROBE_PRICES
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.unified_contract import configuration


def fixture(tmp_path):
    def save(name, value): return write_once(tmp_path/(name+'.json'),value)
    policy=LiveProbePolicy(policy_id='e7-test',basis='Declared uncalibrated public priors')
    pp=save('policy',asdict(policy)); cells=[]; ts=[]; cases={}; tscases={}
    for name,slots in [('a',['anchor']),('b',['anchor','control'])]:
        base=configuration();base['settings']['relaxable']=slots
        for label in ('XGAP','NP','SH','GR'):
            cid=name+'-'+label;cases[cid]=name
            cells.append(dict(cell_id=cid,method=METHODS[label],request={'frozen':name},
                reference={'frozen':name},controlled_state={'frozen':name},scope={'frozen':name},oracle={'unread':name},
                config=save(cid,configuration_for(base,label))))
        tscases[name+'-TS']=name
        ts.append(dict(cell_id=name+'-TS',method=METHODS['TS'],request={'frozen':name},reference={'frozen':name}))
    contract=dict(deployment='rdf',prepared={'same':'source-snapshot'},design={'fixed':'budgets'})
    bu=save('base-unit',dict(manifest=save('base-manifest',dict(**contract,cells=cells)),cell_cases=cases))
    tu=save('ts-unit',dict(manifest=save('ts-manifest',dict(**contract,cells=ts)),cell_cases=tscases))
    spec=dict(schema_version='xgap-ch6-live-e7-input-v1',method_results_read=0,aggregation='expectation',
              base_unit=bu,ts_unit=tu,live_probe_policy=pp)
    return spec,policy,save


def test_live_e7_publishes_all_five_methods_and_fixed_references(tmp_path):
    spec,policy,save=fixture(tmp_path); before=deepcopy(spec)
    ip=save('input',spec); out=load_pin(prepare(ip['path'],ip['sha256'],tmp_path/'published'))
    assert spec==before and out['launch_ready'] is False
    assert out['method_measurements_created']==out['model_calls']==out['backend_calls']==0
    assert load_pin(out['audit'])['success']
    assert len(out['figure_bindings'])==25
    assert sum(len(load_pin(u['manifest'])['cells']) for u in out['units'])==34
    rows=out['figure_bindings']
    for label in ('NP','TS'):
        refs=[r['cells'] for r in rows if r['method']==label]
        assert all(x==refs[0] for x in refs) and len(refs)==5
    for unit in out['units']:
        for cell in load_pin(unit['manifest'])['cells']:
            if cell['method']==METHODS['TS']: continue
            raw=load_pin(cell['config']); actual=raw['settings']['live_probe_policy']
            price=float(unit['unit_id'].removeprefix('E7-live-price-'))
            assert actual['action_cost']==policy.action_cost*price
            comparison=deepcopy(actual); comparison['action_cost']=policy.action_cost
            assert comparison==json.loads(json.dumps(asdict(policy)))
    # Same entire query/state/source contract across prices, not just same labels.
    tampered=deepcopy(out); first=tampered['units'][0]
    manifest=deepcopy(load_pin(first['manifest']));manifest['cells'][0]['controlled_state']={'different':'family'}
    first['manifest']=save('changed-input',manifest)
    assert any(not c['passed'] and c['check'].startswith('live_probe_same_inputs')
               for c in audit_bindings(tampered,figures=('E7',)))


def test_live_e7_rejects_prior_and_policy_mutation(tmp_path):
    spec,policy,save=fixture(tmp_path)
    old=configuration();before=deepcopy(old)
    for p in PROBE_PRICES:
        new=live_e7_configuration(old,policy,'XGAP',p)
        assert new['settings']['live_probe_policy']['action_cost']==policy.action_cost*p
    assert old==before
    old['settings']['candidate_weights']=[1]
    with pytest.raises(ValueError,match='another registry'):live_e7_configuration(old,policy,'XGAP',1)
    bad=deepcopy(spec);bad['method_results_read']=1
    with pytest.raises(ValueError,match='pre-result'):build_live_e7(bad)
    ip=save('input',spec);out=load_pin(prepare(ip['path'],ip['sha256'],tmp_path/'published'))
    unit=out['units'][0];manifest=deepcopy(load_pin(unit['manifest']))
    raw=load_pin(manifest['cells'][0]['config']);raw['settings']['live_probe_policy']['threshold']+=1
    manifest['cells'][0]['config']=save('mutated-prior',raw);unit['manifest']=save('mutated-manifest',manifest)
    assert any(not c['passed'] and c['check'].startswith('plot_price_configuration')
               for c in audit_bindings(out,figures=('E7',)))


def test_live_e7_requires_complete_same_source_cohort(tmp_path):
    spec,_,save=fixture(tmp_path);ts=load_pin(spec['ts_unit']);manifest=load_pin(ts['manifest'])
    manifest['cells'].pop();ts['manifest']=save('partial-ts-manifest',manifest);spec['ts_unit']=save('partial-ts',ts)
    with pytest.raises(ValueError,match='every frozen'):build_live_e7(spec)
