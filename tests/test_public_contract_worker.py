"""Exercise the real worker boundary with no network and a pinned tiny source proof."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_compact_constraints_profile import source_profile
from xgap.experiments import bounded_joint_worker as worker
from xgap.experiments.compact_constraints_profile import build_public_compact_constraints
from xgap.experiments.compact_profile import load_compact_graph_provider
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.unified_contract import configuration
from xgap.llm.public_typed_compact import PROFILE
from xgap.semantic.intent_scope import ScopePolicy
from xgap.semantic.interpretation import InterpretationRequest


@pytest.mark.parametrize('proved',[False,True])
def test_public_contract_loaded_before_any_model_or_authority_access(tmp_path,monkeypatch,proved):
    doc=source_profile(tmp_path,monkeypatch)
    contract=build_public_compact_constraints(doc,profile_root=tmp_path)
    if proved:doc['offline']['compact_public_constraints']=write_once(tmp_path/'constraints.json',contract.to_dict())
    profile_pin=write_once(tmp_path/'profile.json',doc)
    provider=load_compact_graph_provider(language_version='v2',prompt_version='v2')
    provider.token_guard=SimpleNamespace(check=lambda *args,**kw:dict(passed=True))
    monkeypatch.setenv(provider.config.api_key_env,'fixture-not-sent')
    backends={name:SimpleNamespace(identity_property=b['semantic']['identity_property'],
        resource_namespace=b['semantic']['resource_namespace']) for name,b in doc['backends'].items()}
    materialized=(doc,None,None,{},backends,{},dict(performance=(None,provider)))
    fake=SimpleNamespace(root=tmp_path,materialize=lambda:materialized,
        request=lambda raw,mode,values:InterpretationRequest(raw['question'],dict(source_schema=doc['source_schema'])))
    monkeypatch.setattr(worker.FrozenOneShotProfile,'load',lambda *args,**kw:fake)
    monkeypatch.setattr(worker,'native_clients',lambda specs:{})
    entered=[]
    def controlled_answer(request,actual_provider,*,authority,**kwargs):
        entered.append(True)
        assert authority.constraints.identity==contract.identity
        assert not authority.response_path.exists()  # worker has not pre-read private intent.
        assert actual_provider.config.safe_dict()['request_schema_profile']==PROFILE
        return dict(success=False,status='fixture_gate',model_calls=0,input_tokens=0,output_tokens=0,
                    final_plan_executions=0,answer_rows=[])
    monkeypatch.setattr(worker,'answer_unified',controlled_answer)
    request=write_once(tmp_path/'request.json',dict(schema_version='public-fixture',question_id='one',
        question='An explicit public-role question.',population='test',exposure='development'))
    scope=write_once(tmp_path/'scope.json',ScopePolicy('public-empty',(),language_version='v2').to_dict())
    config=write_once(tmp_path/'config.json',configuration(provider='frozen_compact_model_public_contract_v1'))
    result=worker.run(profile_path=profile_pin['path'],profile_sha256=profile_pin['sha256'],
        request_path=request['path'],request_sha256=request['sha256'],scope_path=scope['path'],scope_sha256=scope['sha256'],
        oracle_path=tmp_path/'never-read.json',oracle_sha256='a'*64,method='xgap-unified-lookahead',mode=None,
        output=tmp_path/'worker',joint_config_path=config['path'],joint_config_sha256=config['sha256'])
    assert result['model_calls']==result['backend_calls']==result['final_plan_executions']==0
    if proved:
        assert entered and result['status']=='fixture_gate',result
        assert result['public_compact_constraints']['identity']==contract.identity
        assert result['public_compact_constraints']['profile']['sha256']==profile_pin['sha256']
    else:
        assert not entered and result['status']=='worker_failed'
        assert 'requires pinned source constraints' in result['error']
