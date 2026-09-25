"""A censored cohort can be evaluated, but not declared all-correct or ready."""
import pytest
from xgap.experiments.ch6_backend_eligibility import assess, eligible, check_design, INPUT_SCHEMA
from xgap.experiments.ch6_admission_policy import AdmissionBudgets,CLOSURE_KEYS
from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.one_shot_records import write_once


def evidence(tmp_path, *, bundle_pin=None, prepared_pin=None, runtime=None):
    tmp_path.mkdir(parents=True,exist_ok=True)
    def save(name,doc):return write_once(tmp_path/(name+'.json'),doc)
    norm=dict(schema_version='xgap-row-normalization-v1',fields={'n':'integer'})
    if bundle_pin is None:
        profile=save('profile',{})
        cases=[dict(case_id=k,reference=save(k+'-reference',dict(rows=[{'n':1}],normalization=norm,
            query_sha256='query-'+k,source_snapshot_sha256='snapshot'))) for k in ('a','b')]
        bundle_pin=save('bundle',dict(profile=profile,cases=cases))
        prepared_pin=save('prepared',dict(success=True,profile=profile))
    bundle=load_pin(bundle_pin);profile=bundle['profile'];cases=bundle['cases']
    timeouts=AdmissionBudgets().to_dict();limits=dict(method=10**9,source=2*10**9)
    source_budget=dict(timeout_seconds=60,max_calls=128)
    ready=save('ready',dict(prepared=prepared_pin,profile=profile,source_runtime=runtime,
        query_timeout_seconds=60,tdb2_file_mode='direct' if runtime else 'default',experimental_lazy_range=bool(runtime)))
    rows=[]
    for i,case in enumerate(cases):
        correct=i==0;cid=case['case_id'];reference=load_pin(case['reference'])
        worker=save('worker-'+str(i),dict(case_id=cid,success=correct,bundle=bundle_pin,profile=profile,
            model_calls=0,final_plan_executions=1,query_sha256=reference.get('query_sha256'),
            source_snapshot_sha256=reference.get('source_snapshot_sha256'),
            answer=save('answer-'+str(i),dict(rows=reference['rows'] if correct else []))))
        rows.append(dict(case_id=cid,success=correct,answer_em=1 if correct else None,worker=worker,
            guard=dict(status='completed',success=correct,cleanup=dict(complete=True),
                budget=dict(wall_seconds=120,max_group_rss_bytes=limits['method'])),resources=dict(limits=limits),
            source_observations=dict(requests=1,failed_requests=0 if correct else 1,
                failure_categories={} if correct else {'source_timeout':1},budget=source_budget)))
    receipt=dict(bundle=bundle_pin,prepared=prepared_pin,profile=profile,source_runtime=runtime,
        source_commit='a'*40,admission_budgets=timeouts,model_calls=0,evaluated_method=False,
        closure=dict.fromkeys(CLOSURE_KEYS,True),attempted=len(rows),audited=len(rows),cases=rows,source_ready=ready)
    rp=save('receipt',receipt)
    spec=dict(schema_version=INPUT_SCHEMA,source_commit='a'*40,admission_budgets=timeouts,resource_limits=limits,
        bundle=bundle_pin,prepared=prepared_pin,source_runtime=runtime,segments=[rp])
    return spec,receipt,dict(source_budget=source_budget,method_rss_bytes=limits['method'],source_rss_bytes=limits['source'])


def test_censored_case_stays_supported_but_not_all_correct(tmp_path):
    spec,_,design=evidence(tmp_path);ip=write_once(tmp_path/'input.json',spec);gate=assess(ip)
    assert eligible(gate,bundle_pin=spec['bundle'],prepared_pin=spec['prepared'])
    check_design(gate,design)
    assert gate['counts']=={'correct':1,'source_timeout':1}
    assert not gate['all_answers_correct'] and not gate['full_bundle_admitted'] and not gate['formal_campaign_ready']
    assert gate['cases'][1]['answer_em'] is None
    forged={**gate,'all_answers_correct':True}
    with pytest.raises(ValueError,match='recomputed'):eligible(forged)
    with pytest.raises(ValueError,match='budget differs'):check_design(gate,{**design,'source_budget':{'timeout_seconds':300}})


@pytest.mark.parametrize('change',[
    lambda r:r['cases'][1].update(answer_em=0),
    lambda r:r['cases'][1]['source_observations'].update(failure_categories={'harness_persistence':1}),
    lambda r:r['closure'].update(owned_groups_drained=False),
    lambda r:r.update(source_commit='b'*40),
    lambda r:r.update(attempted=3),
    lambda r:r['cases'][1]['guard']['budget'].update(wall_seconds=300),
    lambda r:r['cases'].reverse(),
    lambda r:r.update(cases=r['cases'][:1],attempted=1,audited=1),
])
def test_blocking_defects_cannot_be_relabelled_as_eligible(tmp_path,change):
    spec,receipt,_=evidence(tmp_path);change(receipt)
    spec['segments']=[write_once(tmp_path/'bad-receipt.json',receipt)]
    with pytest.raises(ValueError):assess(write_once(tmp_path/'input.json',spec))


def test_raw_wrong_answer_blocks_even_if_receipt_claims_em_one(tmp_path):
    spec,receipt,_=evidence(tmp_path);worker=load_pin(receipt['cases'][0]['worker'])
    worker['answer']=write_once(tmp_path/'wrong-answer.json',dict(rows=[{'n':7}]))
    receipt['cases'][0]['worker']=write_once(tmp_path/'bad-worker.json',worker)
    spec['segments']=[write_once(tmp_path/'bad-receipt.json',receipt)]
    with pytest.raises(ValueError,match='independent reference'):assess(write_once(tmp_path/'input.json',spec))


def test_duplicate_case_and_purely_failed_deployment_do_not_admit(tmp_path):
    spec,receipt,_=evidence(tmp_path)
    spec['segments']*=2
    with pytest.raises(ValueError,match='Complete frozen'):assess(write_once(tmp_path/'dup.json',spec))
    spec['segments']=spec['segments'][:1]
    row=receipt['cases'][0];row.update(success=False,answer_em=None)
    row['guard']['success']=False
    row['source_observations'].update(failed_requests=1,failure_categories={'source_timeout':1})
    # Each failed attempt closes its session before the next one starts.
    spec['segments']=[write_once(tmp_path/('failed-'+str(i)+'.json'),
        {**receipt,'cases':[r],'attempted':1,'audited':1}) for i,r in enumerate(receipt['cases'])]
    with pytest.raises(ValueError,match='actual backend roundtrip'):assess(write_once(tmp_path/'failed-spec.json',spec))


def test_same_runtime_pin_with_optional_byte_count_keeps_identity(tmp_path):
    runtime=write_once(tmp_path/'runtime.json',{})
    spec,receipt,_=evidence(tmp_path,runtime=runtime)
    spec['source_runtime']={k:v for k,v in runtime.items() if k!='bytes'}
    assert assess(write_once(tmp_path/'input.json',spec))['eligible_for_evaluation']


def test_new_certificate_reaches_shared_repaired_runtime(tmp_path,monkeypatch):
    import ch6_source_runtime as runtime
    from test_ch6_source_runtime import artifacts
    sources,build=artifacts(tmp_path);monkeypatch.setattr(runtime,'JAVA_ROOT',sources)
    contract=write_once(tmp_path/'contract.json',runtime.current_contract(build))
    spec,_,design=evidence(tmp_path/'cohort',runtime=contract)
    gate=assess(write_once(tmp_path/'input.json',spec))
    config=dict(contract=contract,admission=write_once(tmp_path/'gate.json',gate))
    design['source_runtime']=config
    assert runtime.validate_admission(design,'rdf',spec['prepared'],bundle_pin=spec['bundle'])==config


def test_timeout_does_not_remove_method_support_from_mixed_cohort(tmp_path):
    from freeze_ch6_mixed_support import freeze
    from xgap.experiments.ch6_formal_protocol import METHOD_ORDER
    entries=[]
    for deployment in ('rdf','native'):
        root=tmp_path/deployment;root.mkdir()
        def save(name,doc):return write_once(root/(name+'.json'),doc)
        profile=save('profile',{})
        prepared=save('prepared',dict(success=True,profile=profile))
        cases=[dict(case_id=deployment+'-'+name,deployment=deployment,
            contributing_sources=['source-a'] if name=='single' else ['source-a','source-b'],
            source_snapshot_sha256='snapshot',stratum='uniform',workload='W1',
            reference=save(name+'-ref',dict(rows=[{'n':1}],query_sha256=name,
                source_snapshot_sha256='snapshot',normalization=dict(
                    schema_version='xgap-row-normalization-v1',fields={'n':'integer'}))))
            for name in ('single','cross')]
        bundle=save('bundle',dict(profile=profile,cases=cases,deployment=deployment,
            deployment_selection='balanced',dataset='D2',input_track='nl'))
        spec,_,_=evidence(root/'evidence',bundle_pin=bundle,prepared_pin=prepared)
        gate=save('gate',assess(save('gate-input',spec)))
        entries.append(dict(bundle=bundle,prepared=prepared,backend_admission=gate))
    ip=write_once(tmp_path/'support-input.json',dict(schema_version='xgap-ch6-support-input-v1',
        method_outputs_used=False,bundles=entries,
        external_interface_gate=write_once(tmp_path/'external.json',dict(success=True))))
    output=tmp_path/'support.json';freeze(ip['path'],ip['sha256'],output)
    import json
    support=json.loads(output.read_text())
    assert len(support['cases'])==4
    for row in support['cases']:
        for method in METHOD_ORDER:
            expected='unsupported_deployment' if method=='TS' and row['deployment']=='native' else 'supported'
            assert row['methods'][method]['status']==expected
