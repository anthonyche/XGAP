"""Mixed family configurations must preserve mandatory hard coordinates."""
import json
from copy import deepcopy

import pytest
import release_ch6_five_method_batch as batch
from prepare_ch6_execution_units import prepare,case_configuration
from xgap.agent.scope_authority import private_query_intent
from xgap.experiments.ch6_fact_index import CORES
from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.ch6_heldout import make_family
from xgap.experiments.controlled_state import publish_state
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from dataclasses import asdict


@pytest.mark.parametrize('admission_mode',['legacy','eligible_with_timeout'])
def test_actual_multi_family_manifest_and_repetitions_keep_hard_scope(tmp_path,monkeypatch,admission_mode):
    monkeypatch.setattr(batch,'source_commit',lambda:'fixture')
    def save(name,doc):return write_once(tmp_path/(name+'.json'),doc)
    profile=save('profile',{})
    prepared=save('prepared',dict(success=True,profile=profile))
    gate=save('gate',dict(success=True,backend_roundtrip=True,profile=profile))
    cases=[]
    for workload in ('W1','W4'):
        q,scope,family=make_family(CORES['D1'],'window_edge',['a','b'],42,workload,'s',workload)
        question='case '+workload
        choices=[dict(name=s.name,type='coordinate',slots=[s.name]) for s in family.slots]
        cases.append(dict(case_id=workload,request=save(workload+'-request',dict(question=question,question_id=workload)),
            controlled_state=save(workload+'-state',publish_state(question,family,q,semantic_choices=choices)),
            scope=save(workload+'-scope',scope.to_dict()),oracle=save(workload+'-private',private_query_intent(question,q,language_version='v2')),
            reference=save(workload+'-reference',dict(question_id=workload,rows=[],query_sha256='query-'+workload,
                source_snapshot_sha256='snapshot',normalization=dict(schema_version='xgap-row-normalization-v1',fields={'n':'integer'})))))
    bundle=save('bundle',dict(cases=cases,dataset='D1',deployment='rdf',profile=profile))
    spec=dict(schema_version='xgap-ch6-unit-preparation-v1',method_results_read=0,input_track='nl',repetitions=2,
        bundle=bundle,prepared=prepared,backend_admission=gate,external_runtime=save('external',{}),
        order_seed=1,unit_prefix='test',figures=['E1'],design=dict(total_wall_seconds=3600,package_max_bytes=10**9,
        free_disk_reserve_bytes=10**9,method_wall_seconds=300,method_rss_bytes=10**9,source_rss_bytes=10**9,startup_seconds=120,
        source_budget=asdict(SourceObservationBudget())))
    if admission_mode=='eligible_with_timeout':
        from test_ch6_backend_eligibility import evidence
        from xgap.experiments.ch6_backend_eligibility import assess
        eligibility,_,design=evidence(tmp_path/'eligibility',bundle_pin=bundle,prepared_pin=prepared)
        spec['backend_admission']=save('eligibility-gate',assess(save('eligibility-input',eligibility)))
        spec['design'].update(design)
    ip=save('input',spec);receipt=load_pin(prepare(ip['path'],ip['sha256'],tmp_path/'units'))
    assert receipt['unique_cases']==2 and len(receipt['units'])==2
    for unit in receipt['units']:
        manifest=load_pin(unit['manifest']);assert len(manifest['cells'])==10
        for cell in manifest['cells']:
            if cell['method']=='aruqula-fedx':
                assert set(cell)=={'cell_id','method','request','reference'};continue
            settings=load_pin(cell['config'])['settings']
            assert settings['relaxable']==([] if unit['cell_cases'][cell['cell_id']]=='W1' else ['anchor','control'])
            assert settings['limits']['horizon']==12 and settings['epsilon']=='1/3'
            assert settings['limits']['depth']==(1 if cell['method'].endswith(('shallow','myopic')) else 2)
    # A fixed external NL reference is executed once and referenced across plots;
    # it must not silently schedule the four internal NL methods again.
    external_only={**spec,'methods':['TS'],'unit_prefix':'fixed-reference'}
    ep=save('external-only',external_only)
    reference_units=load_pin(prepare(ep['path'],ep['sha256'],tmp_path/'fixed-reference'))
    for unit in reference_units['units']:
        cells=load_pin(unit['manifest'])['cells']
        assert len(cells)==2 and all(c['method']=='aruqula-fedx' for c in cells)
        assert all(set(c)=={'cell_id','method','request','reference'} for c in cells)
    spec['backend_admission']=save('failed-gate',dict(success=False))
    bad=save('bad-input',spec)
    with pytest.raises(ValueError,match='actual admitted'):prepare(bad['path'],bad['sha256'],tmp_path/'bad')


def test_configuration_does_not_read_hidden_intent_or_reference(tmp_path):
    q,scope,family=make_family(CORES['D1'],'window_edge',['a','b'],42,'W3','s','q')
    request=write_once(tmp_path/'request.json',dict(question='q'))
    state=write_once(tmp_path/'state.json',publish_state('q',family,q,
        semantic_choices=[dict(name=s.name,type='coordinate',slots=[s.name]) for s in family.slots]))
    c=dict(request=request,controlled_state=state,oracle='unreadable',reference='unreadable')
    assert case_configuration(c)['settings']['relaxable']==('anchor','control','lower_time')
