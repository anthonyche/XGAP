"""Representation-only identity must not become a semantic repair mechanism."""
from copy import deepcopy
import json

import pytest

from test_bounded_joint import base_query, scope, user, ControlledCompactProvider
from test_chapter7_controls import inputs
from xgap.api import answer, answer_controlled
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.experiments.bounded_joint_toy import local_runtime
from xgap.experiments.evidence_store import write_json_evidence
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.query_loss_score import score_query_loss
from xgap.semantic.compact_identity import representation_key
from xgap.semantic.intent_scope import construct_scope
from xgap.semantic.interpretation import InterpretationRequest
from test_intent_strong import QUESTION


def renamed(query):
    """The different legal spelling observed in the frozen live Qwen response."""
    value=deepcopy(query)
    mapping={'start':'src','other':'dst','medium':'med','signin':'e_sign','reach':'p'}
    def walk(item):
        if isinstance(item,list):return [walk(x) for x in item]
        if isinstance(item,dict):return {k:mapping.get(v,v) if k in ('var','source','target') else walk(v) for k,v in item.items()}
        return item
    value=walk(value)
    for key in ('deduplicate_by','contribution_by'):
        if value.get(key):value[key]=[mapping.get(v,v) for v in value[key]]
    value['where'].reverse()
    return value


def test_representation_key_preserves_original_and_literal_values():
    q=base_query();q['where'][-1]['right']['value']='start';q['nodes'][0]['entity']='start'
    alias=renamed(q);before=deepcopy(alias)
    assert representation_key(q)==representation_key(alias)
    assert alias==before
    alias['where'][0]['right']['value']='src'
    assert representation_key(q)!=representation_key(alias)
    alias=renamed(q);alias['nodes'][0]['entity']='src'
    assert representation_key(q)!=representation_key(alias)
    alias=renamed(q);alias['select']['other_id']['var']='missing'
    with pytest.raises(ValueError,match='Undeclared'):representation_key(alias)


@pytest.mark.parametrize('change',['direction','filter','aggregate','ordering','limit','duplicates'])
def test_authority_still_rejects_changed_meaning(tmp_path,change):
    q=base_query();other=renamed(q)
    if change=='direction':other['edges'][0]['source'],other['edges'][0]['target']=other['edges'][0]['target'],other['edges'][0]['source']
    elif change=='filter':other['where'][0]['right']['value']='2'
    elif change=='aggregate':other['select']['account_distance']={'aggregate':'count','field':None,'distinct':False}
    elif change=='ordering':other['order_by'][0]['direction']='desc'
    elif change=='limit':other['limit']=1
    else:other['deduplicate_by']=['src','dst']
    reply=user(tmp_path,q).confirm_scope(QUESTION,construct_scope([other],scope(),'tiny'))
    assert reply.status.value=='success' and reply.value['covered'] is False


@pytest.mark.parametrize('version',['v1','v2'])
def test_aggregate_and_contribution_references_are_renamed(version):
    q=base_query();q['select']['account_distance']={'aggregate':'count','field':{'var':'other','property':'id'},'distinct':True}
    q['deduplicate_by']=['start','other']
    if version=='v2':q['contribution_by']=q.pop('deduplicate_by')
    assert representation_key(q,version=version)==representation_key(renamed(q),version=version)


def test_renamed_model_proposal_reaches_real_rdf_execution(tmp_path):
    data,options,calls=local_runtime();q=data['query_template'];schema=options.pop('source_schema')
    provider=ControlledCompactProvider(renamed(q))
    result=answer(InterpretationRequest(QUESTION,{'source_schema':schema}),provider,mode='exact',
        scope_policy=scope(),authority=user(tmp_path,q),limits=StrongSearchLimits(planning_ms=10000),**options)
    assert result['success'],result
    assert result['answer_rows']==data['expected'] and result['final_plan_executions']==1
    assert result['model_calls']==0 and result['clarification_calls']==1 and calls


def test_independent_loss_aligns_private_spelling_after_sealing(tmp_path):
    data,runtime,_,_,family,initial,_,simulator,oracle=inputs(tmp_path,('hops',))
    core=answer_controlled(QUESTION,family,simulator,initial_observations=initial,
        mode='performance',epsilon='1/2',limits=StrongSearchLimits(planning_ms=10000),**runtime)
    # Different private spelling, same meaning. This file is only opened by scorer.
    private=json.loads(open(oracle['path']).read());private['query']=renamed(private['query'])
    from xgap.agent.intent_certificate import fingerprint
    private['question_sha256']=fingerprint(QUESTION)
    oracle=write_once(tmp_path/'aliased-private.json',private)
    request=write_once(tmp_path/'request.json',dict(question=QUESTION))
    receipt=write_once(tmp_path/'receipt.json',dict(schema_version='xgap-common-method-trial-v1',
        request_sha256=request['sha256'],oracle_sha256=oracle['sha256'],final_plan_executions=1,
        core=write_json_evidence(tmp_path/'core.json.gz',core)))
    score=score_query_loss(receipt=receipt,request=request,oracle=oracle,output=tmp_path/'loss.json')
    assert score['status']=='measured' and score['loss']==.5 and score['certificate_violation'] is False
