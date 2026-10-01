"""Reproduce the large-trace handoff failure locally, with no model/backend calls."""
import json
from pathlib import Path

import pytest

from test_one_shot_records import prepared, sha
from xgap.experiments import one_shot_records as records, nl_method_worker as worker
from xgap.experiments.one_shot_profile import MAX_BYTES, read_pinned, REQUEST_SCHEMA


def core():
    return {'success':True,'status':'answered','answer_rows':[{'amount':56,'count':6}],
        'final_plan_executions':1,'interpretation_external_calls':1,'backend_remote_calls':6,
        'input_tokens':31,'output_tokens':17,'end_to_end_ms':4,'planning_ms':1,'execution_ms':2,
        'observation_calls':0,'interpretation':{'elapsed_ms':0.75},'grounding_ms':0.25,
        'execution':{'intermediate_fixture_bytes':'x'*(MAX_BYTES+1)}}


def test_large_trace_actual_record_to_worker_and_score_never_loads_trace(prepared,tmp_path,monkeypatch):
    monkeypatch.setenv('XGAP_EXTERNAL_LLM_API_KEY','fixture-only-no-network')
    monkeypatch.setattr(records,'native_clients',lambda specs:{})
    calls=[]
    def run_question(*args,**kwargs):
        calls.append('injected-core');return core()
    monkeypatch.setattr(records,'run_question',run_question)
    read=records.read_pinned
    def guarded_read(path,pin):
        if Path(path).name=='result.json':pytest.fail('Online handoff must not read full trace')
        return read(path,pin)
    monkeypatch.setattr(records,'read_pinned',guarded_read)
    r=worker.run_nl(**prepared[0],method='xgap-performance',output=tmp_path/'worker')
    assert r['success'] and r['status']=='answered' and calls==['injected-core']
    assert (r['model_calls'],r['input_tokens'],r['output_tokens'],r['top_level_attempts'],r['backend_calls'])==(1,31,17,1,6)
    assert (r['planning_ms'],r['execution_ms'],r['interpretation_ms'],r['grounding_ms'])==(1,2,0.75,0.25)
    assert json.loads(Path(r['result']['path']).read_text())['answer']==[{'amount':56,'count':6}]
    path=tmp_path/'worker/core';child=json.loads((path/'receipt.json').read_text())
    assert child['result']['bytes']>MAX_BYTES and child['outcome']['bytes']<2048
    with pytest.raises(ValueError,match='size/hash'):read_pinned(path/'result.json',child['result']['sha256'])
    reference=records.write_once(tmp_path/'reference.json',{'schema_version':'xgap-normalized-row-reference-v1',
        'question_id':child['question_id'],'dataset':child['dataset'],'ordered':True,'rows':[{'amount':56,'count':6}]})
    score=records.evaluate_record(path/'receipt.json',receipt_sha256=sha(path/'receipt.json'),
        reference_path=reference['path'],reference_sha256=reference['sha256'],output=tmp_path/'score.json')
    assert score['answer_em']==1


def test_corrupt_handoff_retains_usage_after_completed_core(tmp_path,monkeypatch):
    request=records.write_once(tmp_path/'request.json',{'schema_version':REQUEST_SCHEMA,'question_id':'broken-handoff',
        'question':'A fixture.','population':'development','exposure':'no real model'})
    trace=records.write_once(tmp_path/'trace.json',{'unused':'full trace'})
    outcome=records.write_record_outcome(tmp_path,core(),trace)
    Path(outcome['path']).write_text('{}')
    child={'success':True,'status':'answered','dataset':{'fixture':'1'},'model_network_calls':1,'input_tokens':31,'output_tokens':17,
        'final_plan_executions':1,'backend_network_calls':6,'result':trace,'outcome':outcome}
    monkeypatch.setattr(worker,'run_record',lambda **kw:child)
    r=worker.run_nl(request_path=request['path'],request_sha256=request['sha256'],profile_path=tmp_path/'unused',
        profile_sha256='0'*64,method='xgap-precision',output=tmp_path/'worker')
    assert not r['success'] and r['status']=='worker_failed' and 'size/hash' in r['error']
    assert (r['model_calls'],r['input_tokens'],r['output_tokens'],r['top_level_attempts'],r['backend_calls'])==(1,31,17,1,6)
    assert r['result'] is None


def test_handoff_trace_link_new_missing_outcome_and_legacy_read_are_explicit(tmp_path):
    trace=records.write_once(tmp_path/'trace.json',{'success':False,'answer_rows':[]})
    outcome=records.write_record_outcome(tmp_path,core(),trace)
    with pytest.raises(ValueError,match='Outcome/trace identity'):
        records.read_record_outcome({'outcome':outcome,'result':{**trace,'sha256':'0'*64}})
    assert records.read_record_outcome({'outcome':None,'result':trace}) is None
    assert records.read_record_outcome({'result':trace})=={'success':False,'answer_rows':[]}
