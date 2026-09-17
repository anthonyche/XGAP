"""Durable method router and pin isolation with live local RDF query evaluation."""
from dataclasses import asdict
import json
from types import SimpleNamespace

import pytest

from test_compact_lowering import inputs,EXPECTED
from test_intent_execution import runtime
from test_intent_strong import clustered_family,QUESTION
from xgap.agent.intent_certificate import fingerprint
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.intent_strong import FamilyInformationPolicy
from xgap.agent.intent_user import private_family_intent
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.nl_method_worker import run_nl
from xgap.semantic.interpretation import InterpretationRequest


def test_pinned_worker_routes_both_modes_without_model_or_gold_in_request(inputs,tmp_path,monkeypatch):
    from xgap.experiments import nl_strong_worker as worker
    options,calls=runtime(inputs)
    f=clustered_family(snapshot_identity(options['sources'],options['backends'],options['source_schema']))
    public=write_once(tmp_path/'family.json',dict(schema_version='xgap-family-strong-profile-v1',
        question_sha256=fingerprint(QUESTION),family=f.to_dict(),information_policy=asdict(FamilyInformationPolicy()),
        search_limits=asdict(StrongSearchLimits()),performance_epsilon='1/2',propose_with_model=False))
    oracle=write_once(tmp_path/'private.json',private_family_intent(f,QUESTION,'central'))
    request=write_once(tmp_path/'request.json',dict(schema_version='xgap-one-shot-evaluation-request-v1',
        question_id='FAMILY-01',question=QUESTION,population='toy',exposure='known family'))
    class Config:
        api_key_env='ABSENT_TEST_MODEL_KEY'
        def safe_dict(self):return {'provider_id':'unused-controlled-provider'}
    class Profile:
        def materialize(self):
            return ({'dataset':{'id':'tiny'}},None,None,options['sources'],options['backends'],{},
                {'performance':(options['physical_profile'],SimpleNamespace(config=Config()))})
        def request(self,raw,mode,materialized):
            return InterpretationRequest(raw['question'],{'source_schema':options['source_schema']})
    monkeypatch.setattr(worker.FrozenOneShotProfile,'load',lambda *_a,**_k:Profile())
    monkeypatch.setattr(worker,'native_clients',lambda _:options['backend_clients'])
    for mode,expected,user_calls in [('exact',EXPECTED[1],1),('performance',EXPECTED[1][:3],0)]:
        result=run_nl(request_path=request['path'],request_sha256=request['sha256'],profile_path='injected',
            profile_sha256='injected-profile',method='xgap-nl-family-'+mode,output=tmp_path/mode,
            oracle_path=oracle['path'],oracle_sha256=oracle['sha256'],
            intent_family_path=public['path'],intent_family_sha256=public['sha256'])
        assert result['success'],result
        assert result['track']=='natural_language_finite_family' and result['intent_family_sha256']==public['sha256']
        assert result['clarification_calls']==user_calls and result['model_calls']==0
        assert json.loads(open(result['result']['path']).read())['answer']==expected
        assert result['search']['strong'] and result['top_level_attempts']==1


@pytest.mark.parametrize('method',['fedx','fedup','xgap-nl-user-exact','xgap-nl-strong-exact'])
def test_public_family_cannot_be_silently_added_to_other_methods(method,tmp_path):
    with pytest.raises(ValueError,match='finite-family method'):
        run_nl(request_path='unused',request_sha256='unused',profile_path='unused',profile_sha256='unused',
            method=method,output=tmp_path/'unused',intent_family_path='private-scope',intent_family_sha256='unused')
