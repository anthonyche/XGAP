from collections import Counter
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from xgap.experiments import ch6_entry_gate as gate
from xgap.experiments.one_shot_records import write_once
from xgap.semantic.interpretation import InterpretationRequest
from xgap.tools.contracts import ToolResult


def test_selection_uses_only_public_domain_template_and_id_not_results():
    selection = {'cohorts': [dict(dataset=d, deployment='rdf', cases=[
        dict(template=t, case_id=f'{d}-{t}-{i}', recorded_status='failed' if i else 'answered')
        for t in gate.STRUCTURES for i in range(2)]) for d in ('D3','D1','D2')]}
    expected = gate.select_public_structures(selection)
    changed = deepcopy(selection)
    changed['cohorts'].reverse()
    for cohort in changed['cohorts']:
        cohort['cases'].reverse()
        for case in cohort['cases']:
            case['recorded_status'] = 'unrelated outcome'
    actual = gate.select_public_structures(changed)
    assert [c['case_id'] for _,c in actual] == [c['case_id'] for _,c in expected]
    assert Counter(d['dataset'] for d,_ in actual) == {'D1':3,'D2':3,'D3':2}
    assert len({c['template'] for _,c in actual}) == 8
    assert all(c['case_id'].endswith('-0') for _,c in actual)


def test_preflight_rejects_expanded_calls_and_tokens_before_loading_inputs(tmp_path,monkeypatch):
    manifest = dict(schema_version=gate.SCHEMA,provider=gate.PROVIDER,
        cases=[dict(template=t,dataset=('D1','D2','D3')[i%3]) for i,t in enumerate(gate.STRUCTURES)],
        automatic_retries=0,budget={**gate.BUDGET,'max_output_tokens_per_call':8192})
    pin=write_once(tmp_path/'manifest.json',manifest)
    monkeypatch.setattr(gate,'entry_inputs',lambda *args:pytest.fail('Budget must fail before input loading'))
    with pytest.raises(ValueError,match='eight bounded'):
        gate.preflight(pin['path'],pin['sha256'])


def _run_inputs(tmp_path,monkeypatch,reports,confirmation=None):
    manifest = dict(purpose='entry only',budget=gate.BUDGET,not_tested=['answers'],
        cases=[dict(case_id=f'c{i}',dataset='D1',deployment='rdf',template='zigzag',stratum='uniform',
                    workload='W1',oracle=dict(path='private.json',sha256='a'*64)) for i in range(8)])
    pin=write_once(tmp_path/'manifest.json',manifest)
    monkeypatch.setattr(gate,'preflight',lambda *a:None)
    request=InterpretationRequest('Public question',{},())
    provider=SimpleNamespace(config=SimpleNamespace(api_key_env='ENTRY_TEST_API_KEY'))
    monkeypatch.setenv('ENTRY_TEST_API_KEY','synthetic-unit-test-key')
    monkeypatch.setattr(gate,'entry_inputs',lambda *a:(request,provider,None,SimpleNamespace(identity='proof'),{},'snapshot'))
    calls=[]; scopes=[]
    def interpret(*args,**kw):
        assert kw == {'candidate_cap':1}
        calls.append(1)
        return deepcopy(reports[min(len(calls)-1,len(reports)-1)])
    monkeypatch.setattr(gate,'interpret_candidate_question',interpret)
    def construct(queries,scope,snapshot):
        assert snapshot == 'snapshot' and queries == [{'public':'proposal'}]
        return object()
    monkeypatch.setattr(gate,'construct_scope',construct)
    class Authority:
        def __init__(self,*a,**kw):pass
        def confirm_scope(self,question,draft):
            assert question == 'Public question'
            scopes.append(1)
            return confirmation or ToolResult.success('user.confirm_scope',{'covered':True})
    monkeypatch.setattr(gate,'QueryIntentAuthority',Authority)
    return pin,calls,scopes


def report(*,success=True,tokens=True,calls=True):
    return dict(success=success,external_calls=1,input_tokens=17,output_tokens=3,
        token_usage_complete=tokens,external_call_count_complete=calls,
        candidates=[dict(candidate_id='p',status='admitted')],
        provenance=dict(raw_compact_response=dict(candidates=[dict(candidate_id='p',query={'public':'proposal'})])))


def test_runner_stops_after_eight_proposals_and_meters_one_scope_per_admitted_proposal(tmp_path,monkeypatch):
    pin,calls,scopes=_run_inputs(tmp_path,monkeypatch,[report()])
    result=gate.run(manifest_path=pin['path'],manifest_sha256=pin['sha256'],output=tmp_path/'results')
    assert len(calls) == len(scopes) == 8
    assert result['counts'] == {'entry_admitted':8}
    assert result['usage']['model_calls'] == 8 and result['usage']['user_calls'] == 8
    assert result['usage']['input_tokens'] == 136 and result['usage']['output_tokens'] == 24
    assert result['backend_calls'] == result['planner_calls'] == result['answer_executions'] == 0


def test_unknown_tokens_preserve_known_calls_and_stop_without_retry_or_scope(tmp_path,monkeypatch):
    pin,calls,scopes=_run_inputs(tmp_path,monkeypatch,[report(success=False,tokens=False)])
    result=gate.run(manifest_path=pin['path'],manifest_sha256=pin['sha256'],output=tmp_path/'results')
    assert len(calls) == 1 and scopes == [] and len(result['remaining']) == 7
    assert result['usage']['model_calls'] == result['usage']['known_model_calls'] == 1
    assert result['usage']['input_tokens'] is None and result['usage']['output_tokens'] is None
    assert result['usage']['unknown_tokens'] and not result['usage']['unknown_model_calls']


def test_unknown_calls_preserve_known_tokens_and_stop(tmp_path,monkeypatch):
    pin,calls,scopes=_run_inputs(tmp_path,monkeypatch,[report(success=False,calls=False)])
    result=gate.run(manifest_path=pin['path'],manifest_sha256=pin['sha256'],output=tmp_path/'results')
    assert len(calls) == 1 and scopes == []
    assert result['usage']['model_calls'] is None and result['usage']['known_model_calls'] == 0
    assert result['usage']['input_tokens'] == 17 and result['usage']['output_tokens'] == 3
    assert result['usage']['unknown_model_calls'] and not result['usage']['unknown_tokens']


def test_authority_error_is_not_a_model_scope_quality_failure(tmp_path,monkeypatch):
    pin,_,_=_run_inputs(tmp_path,monkeypatch,[report()],ToolResult.error_result('user.confirm_scope','Pin mismatch'))
    result=gate.run(manifest_path=pin['path'],manifest_sha256=pin['sha256'],output=tmp_path/'results')
    assert result['counts'] == {'scope_authority_failed':8}
    assert result['usage']['user_calls'] == 8
