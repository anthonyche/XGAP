"""A graph label cannot substitute for an actual configuration or source input."""
from copy import deepcopy
from xgap.experiments import ch6_figure_bindings as bindings
from xgap.experiments.ch6_formal_protocol import matrix
from xgap.experiments.unified_contract import configuration


def test_bound_axis_uses_actual_depth_and_one_fixed_reference_set(monkeypatch):
    rows=[r for r in matrix() if r['figure']=='E5' and r['method']=='SH']
    monkeypatch.setattr(bindings,'matrix',lambda:rows)
    config=configuration();config['settings']['limits']['depth']=1
    docs={'config':config,'manifest':{'cells':[dict(cell_id='SH',method='xgap-unified-shallow',config='config',controlled_state='state')], 'deployment':'rdf'}}
    monkeypatch.setattr(bindings,'load_pin',lambda p:docs[p])
    release=dict(units=[dict(unit_id='u',manifest='manifest')],figure_bindings=[
        dict(figure='E5',method='SH',x_value=r['x_value'],status='fixed_reference',cells=[dict(unit_id='u',cell_id='SH')]) for r in rows])
    assert all(c['passed'] for c in bindings.audit_bindings(release))
    config['settings']['limits']['depth']=2
    assert any(not c['passed'] and c['check'].startswith('plot_configuration_') for c in bindings.audit_bindings(release))
    config['settings']['limits']['depth']=1
    changed=deepcopy(release);changed['figure_bindings'][-1]['cells']=[]
    assert any(not c['passed'] and c['check'].startswith('one_fixed_observation_set_') for c in bindings.audit_bindings(changed))


def test_absence_requires_evidence_and_never_invents_a_zero(monkeypatch):
    row=next(r for r in matrix() if r['figure']=='F6' and r['method']=='TS')
    monkeypatch.setattr(bindings,'matrix',lambda:[row]);monkeypatch.setattr(bindings,'load_pin',lambda _:dict(success=True))
    release=dict(units=[],figure_bindings=[dict(figure='F6',method='TS',x_value=row['x_value'],status='unscorable_metric',reason='No comparable selection interface',value=None,evidence_pin='checked')])
    assert all(c['passed'] for c in bindings.audit_bindings(release))
    release['figure_bindings'][0]['value']=0
    assert any(not c['passed'] for c in bindings.audit_bindings(release))
