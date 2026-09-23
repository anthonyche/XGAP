"""Analytic score units, source identity and answer-blind ordering contracts."""
from copy import deepcopy
from dataclasses import replace

import pytest

from xgap.experiments.tiny_work_training import prepare_tiny_work_training
from xgap.planning.relative_source_work import FrozenSourceWorkRanker
from xgap.planning.runtime_estimator import FrozenSourceStatistics
from xgap.planning.runtime_work_estimator import frozen_estimator_from_dict
from xgap.planning.joint_cost import JointCostProfile
from xgap.runtime.contracts import FederatedExecutionPlan,RuntimeNodeKind as R


def fixture():
    stats,entries,*_=prepare_tiny_work_training()
    # Synthetic source-only counts for a ranking contract, no timing labels.
    stats=replace(stats,entries=tuple(replace(s,total_rows=100000) for s in stats.entries))
    model=FrozenSourceWorkRanker(stats,tuple((s.backend_id,100000,0) for s in stats.entries),('id',),'fixture:counts')
    plan=next(e['plan'] for e in entries if e['query_id']=='WORK-TRAIN-MM-neo4j-fuseki-C')
    return model,plan


def test_roundtrip_relative_units_and_snapshot_rejection():
    model,plan=fixture();copy=frozen_estimator_from_dict(model.to_dict())
    prediction=copy.predict(plan);cost,evidence=JointCostProfile().execution(plan,copy)
    assert prediction.estimated_ms is None and prediction.status=='ranked'
    assert cost==prediction.relative_cost>0 and evidence['basis']=='frozen_relative_work'
    assert prediction.provenance['fit_calls']==prediction.provenance['current_query_observation_calls']==0
    assert copy.model_sha256==model.model_sha256
    changed=deepcopy(plan.to_dict());changed['metadata']['source_identities']['neo4j']['snapshot_version']='wrong'
    with pytest.raises(ValueError,match='snapshot'):model.predict(FederatedExecutionPlan.from_dict(changed))
    with pytest.raises(ValueError,match='fallback units refused'):
        JointCostProfile().execution(FederatedExecutionPlan.from_dict(changed),model)
    raw=model.to_dict();raw['record_quantum']=3
    with pytest.raises(ValueError,match='hash'):frozen_estimator_from_dict(raw)


def test_positive_full_scan_work_and_answer_text_independence():
    model,plan=fixture();a=model.predict(plan)
    larger=replace(model,statistics=replace(model.statistics,entries=tuple(replace(s,total_rows=200000)
        for s in model.statistics.entries)),populations=tuple((s.backend_id,200000,0) for s in model.statistics.entries))
    assert larger.predict(plan).relative_cost>a.relative_cost
    changed=deepcopy(plan.to_dict());changed['plan_id']='other';changed['metadata'].update(expected_rows='forbidden',elapsed_ms=0)
    for n in changed['nodes']:
        if n['kind'] in ('remote_query','remote_bind_query'):n['parameters']['artifact']['text']='Must not parse or execute'
    assert model.predict(FederatedExecutionPlan.from_dict(changed)).relative_cost==a.relative_cost


def test_declared_identity_filter_reduces_output_proxy_but_keeps_scan_work():
    model,plan=fixture();raw=deepcopy(plan.to_dict())
    native=next(n for n in raw['nodes'] if n['kind']=='remote_query')
    native['parameters']['artifact']['parameters'].update(scalar_properties={'id':'id'},
        necessary_row_filters={'conditions':[dict(op='eq',field='id',value='chosen-public-id')]})
    before=model.predict(plan);after=model.predict(FederatedExecutionPlan.from_dict(raw))
    assert before.provenance['source_scan_record_units']==after.provenance['source_scan_record_units']
    assert after.provenance['returned_record_proxy']<before.provenance['returned_record_proxy']
    assert next(d for d in after.provenance['nodes'] if d['node']==native['node_id'])['estimated_rows']==1


def test_source_only_publisher_preserves_sources_and_reloads_new_model(tmp_path):
    from test_ch6_fact_materialization import CoreMaterializationTest
    from test_compact_roles_v2 import PARENT,PIN
    from xgap.experiments.ch6_core_profile import publish
    from xgap.experiments.ch6_formal_protocol import load_pin
    from xgap.experiments.one_shot_profile import FrozenOneShotProfile
    from xgap.experiments.one_shot_records import write_once
    from prepare_ch6_relative_work import prepare
    f=CoreMaterializationTest();index=f.index(tmp_path);f.generate(tmp_path/'facts',index)
    profile=publish(tmp_path/'facts/receipt.json',PARENT,PIN,tmp_path/'original')
    old=load_pin(profile)
    seal=write_once(tmp_path/'seal.json',dict(profile=profile))
    parent=write_once(tmp_path/'prepared.json',dict(success=True,profile=profile,input_seal=seal,stores={}))
    result=load_pin(prepare(parent,tmp_path/'revised'))
    doc,model,*_=FrozenOneShotProfile.load(result['profile']['path'],expected_sha256=result['profile']['sha256']).materialize()
    assert isinstance(model,FrozenSourceWorkRanker)
    for key in ('dataset','source_schema','backends','sources'):assert doc[key]==old[key]
    assert doc['offline']['relative_work_revision']['old_estimator']==old['estimator']
    assert doc['offline']['relative_work_revision']['query_reads']==doc['offline']['relative_work_revision']['answer_reads']==0
    from inspect_ch6_core_planning import rebind,inspect
    from xgap.agent.intent_execution import snapshot_identity
    from xgap.agent.scope_authority import private_query_intent
    from xgap.experiments.ch6_fact_index import CORES,pin
    from xgap.experiments.ch6_heldout import template_query
    _,_,_,sources,backends,*_=FrozenOneShotProfile.load(profile['path'],expected_sha256=profile['sha256']).materialize()
    q=template_query(CORES['D2'],'plain_edge','user:1',0)
    request=write_once(tmp_path/'request.json',dict(question='frozen complete-query diagnostic'))
    oracle=write_once(tmp_path/'oracle.json',private_query_intent('frozen complete-query diagnostic',q,language_version='v2'))
    bundle=write_once(tmp_path/'bundle.json',dict(profile=profile,cases=[dict(case_id='diagnostic',request=request,oracle=oracle,
        source_snapshot_sha256=snapshot_identity(sources,backends,old['source_schema']),
        reference=dict(path='/must-not-read-reference-answers',sha256='0'*64))]))
    revised=rebind(bundle,pin(tmp_path/'revised/receipt.json'),tmp_path/'new-bundle.json')
    diagnostic=load_pin(inspect(revised,tmp_path/'diagnostic'))
    assert diagnostic['success'] and not diagnostic['backend_admission']
    assert diagnostic['actual_plan_executions']==diagnostic['backend_calls']==diagnostic['reference_rows_read']==0
    assert len(diagnostic['cases'])==1
