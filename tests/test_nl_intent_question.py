"""Ordinary NL API -> the shared certified strong search -> real tiny RDF queries."""
from dataclasses import replace
import json

from test_compact_lowering import inputs,EXPECTED
from test_intent_execution import runtime
from test_intent_strong import clustered_family,private_user,QUESTION
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.intent_strong import FamilyInformationPolicy
from xgap.agent.nl_strong_question import run_nl_strong_question
from xgap.semantic.interpretation import InterpretationRequest,InterpretationResponse


def run(inputs,tmp_path,mode,epsilon,calls=9):
    options,backend_calls=runtime(inputs)
    f=clustered_family(snapshot_identity(options['sources'],options['backends'],options['source_schema']))
    oracle=private_user(tmp_path,f);observations=[]
    class Provider:
        provider_id='controlled-invalid-proposal'
        calls=0
        def interpret(self,request):
            self.calls+=1
            assert 'private' not in json.dumps(request.to_dict()) and 'candidate_id' not in json.dumps(request.to_dict())
            return InterpretationResponse({},provenance={'usage_reported':True},
                external_calls=1,input_tokens=10,output_tokens=5)
    provider=Provider()
    r=run_nl_strong_question(InterpretationRequest(QUESTION,{'source_schema':options.pop('source_schema')}),provider,
        mode=mode,policy=options.pop('physical_profile'),bundle=None,user_oracle=oracle,intent_family=f,
        family_information=FamilyInformationPolicy(max_calls=calls),family_epsilon=epsilon,
        on_user_observation=observations.append,**options)
    return r,backend_calls,provider,observations


def test_main_nl_entry_does_not_promote_model_or_preload_authority(inputs,tmp_path):
    exact,ec,ep,eo=run(inputs,tmp_path,'exact','0')
    perf,pc,pp,po=run(inputs,tmp_path,'performance','1/4')
    assert exact['success'],exact
    assert perf['success'],perf
    assert exact['answer_rows']==EXPECTED[1][:3] and perf['answer_rows']==EXPECTED[1]
    assert not exact['interpretation']['success'] and exact['user_intent_verified']
    assert not perf['interpretation']['success'] and not perf['user_intent_verified']
    assert exact['model_calls']==perf['model_calls']==ep.calls==pp.calls==1
    assert exact['input_tokens']==perf['input_tokens']==10 and exact['output_tokens']==perf['output_tokens']==5
    assert exact['clarification_calls']==len(eo)==1 and perf['clarification_calls']==len(po)==0
    assert exact['strong_plan'] and perf['strong_plan']
    assert exact['physical_prepare_attempts']==5 and perf['physical_prepare_attempts']==1
    assert exact['final_plan_executions']==perf['final_plan_executions']==1
    assert set(ec)==set(pc)=={'graph','control'}


def test_same_zero_information_budget_and_invalid_profile_fail_closed(inputs,tmp_path):
    exact,calls,provider,obs=run(inputs,tmp_path,'exact','0',calls=0)
    assert not exact['success'] and not calls and not obs and provider.calls==1
    perf,calls,provider,obs=run(inputs,tmp_path,'performance','1/4',calls=0)
    assert perf['success'] and calls and not obs and provider.calls==1
