"""Publication recovery cannot authorize a query, hide a cut, or replace evidence."""
from copy import deepcopy
import pytest
from prepare_ch6_recovered_release import completed_cohorts,bind_recipes
from test_ch6_backend_eligibility import evidence
from xgap.experiments.ch6_backend_eligibility import assess
from xgap.experiments.one_shot_records import write_once


def completed(tmp_path):
    def save(name,doc):return write_once(tmp_path/(name+'.json'),doc)
    spec,receipt,_=evidence(tmp_path/'evidence')
    gate=assess(save('eligibility-input',spec));ep=save('eligibility',gate)
    census=dict(census_complete=True,remaining=[],stop_reason=None,error=None,
        case_order=['a','b'],counts=gate['counts'],model_calls=0,automatic_retries=0,
        segments=[dict(receipt=s) for s in spec['segments']])
    cohort=dict(cohort_id='toy',bundle=spec['bundle'],prepared=spec['prepared'],case_order=['a','b'])
    contract=dict(source_commit='a'*40,cohorts=[cohort],maximum_final_plan_executions=2)
    prior=dict(source_commit='a'*40,error='Invalid cell ID',success=False,model_calls=0,
        automatic_retries=0,formal_campaign_started=False,cohorts=dict(toy=dict(
            complete=True,remaining=[],stop_reason=None,counts=gate['counts'],
            census=save('census',census),eligibility=ep)))
    return contract,prior,census,save


def test_recovery_preserves_complete_censored_evidence_and_pins(tmp_path):
    c,p,_,_=completed(tmp_path);before=deepcopy((c,p))
    result=completed_cohorts(c,p)
    assert (c,p)==before
    assert result['toy']['eligibility']==p['cohorts']['toy']['eligibility']
    assert p['cohorts']['toy']['counts']=={'correct':1,'source_timeout':1}


@pytest.mark.parametrize('change',[
    lambda p:p.update(error='wrong answer'),
    lambda p:p.update(model_calls=1),
    lambda p:p.update(formal_campaign_started=True),
    lambda p:p['cohorts']['toy'].update(complete=False),
    lambda p:p['cohorts']['toy'].update(remaining=['b']),
    lambda p:p['cohorts']['toy'].update(counts={'correct':2}),
])
def test_unfinished_or_changed_attempt_cannot_recover(tmp_path,change):
    c,p,_,_=completed(tmp_path);change(p)
    with pytest.raises(ValueError):completed_cohorts(c,p)


def test_recovery_does_not_trust_census_summary_over_eligibility(tmp_path):
    c,p,census,save=completed(tmp_path);census['case_order'].reverse()
    p['cohorts']['toy']['census']=save('changed-census',census)
    with pytest.raises(ValueError,match='diagnostic cohort'):completed_cohorts(c,p)


def test_bindings_require_exact_coverage_and_use_original_f6_status(tmp_path):
    def save(name,doc):return write_once(tmp_path/(name+'.json'),doc)
    config=save('config',{})
    default='D1-mechanism-default-r0';cost='D1-mechanism-clarification_price-0.1-r0'
    units=[dict(unit_id=u,manifest=save(u,dict(cells=[dict(cell_id='a-XGAP',config=config)]))) for u in (default,cost)]
    refs=[dict(unit_id=u,cell_id='a-XGAP') for u in (default,cost)]
    recipes=dict(recipes=[dict(figure='E7',method='XGAP',x_value=1,status='fixed_reference',future_cells=refs[:1]),
        dict(figure='E8',method='XGAP',x_value=.1,status='planned',future_cells=refs[1:]),
        dict(figure='F6',method='TS',x_value=.1,status='pending_offline_audit_binding',future_cells=[])])
    sensitivity=save('f6',dict(rows=[dict(method='TS',eta=.1,status='unscorable_metric',value=None,reason='No plan handle')]))
    original=deepcopy(recipes)
    bound=bind_recipes(recipes,units,sensitivity_pin=sensitivity,interface_pin=config)
    assert recipes==original and bound[1]['status']=='scheduled'
    assert bound[1]['cost_references']==[{**refs[1],'configuration':config}]
    assert bound[2]['value'] is None and bound[2]['status']=='unscorable_metric'
    with pytest.raises(ValueError,match='no published cell'):
        bind_recipes(recipes,units[:1],sensitivity_pin=sensitivity,interface_pin=config)
    with pytest.raises(ValueError,match='exactly cover'):
        bind_recipes(dict(recipes=recipes['recipes'][:1]),units,sensitivity_pin=sensitivity,interface_pin=config)
    with pytest.raises(ValueError,match='Duplicate execution unit'):
        bind_recipes(recipes,units+units[:1],sensitivity_pin=sensitivity,interface_pin=config)


def test_dataset_handoff_keeps_rdf_and_excludes_mechanisms(tmp_path):
    from prepare_ch6_recovered_release import dataset_handoffs
    units=[]
    for dataset in ('D1','D3'):
        for deployment in ('native','rdf'):
            for repeat in range(3):
                uid=f'{dataset}-{deployment}-final-r{repeat}'
                manifest=write_once(tmp_path/(uid+'.json'),dict(cells=[{}]*2))
                units.append(dict(unit_id=uid,repetition=repeat,manifest=manifest))
    units.append(dict(unit_id='D1-mechanism-default-r0'))
    result=dataset_handoffs(units)
    for dataset in ('D1','D3'):
        assert len(result[dataset]['units'])==6 and result[dataset]['method_requests']==12
        assert result[dataset]['first_repetition']==[dataset+'-native-final-r0',dataset+'-rdf-final-r0']
