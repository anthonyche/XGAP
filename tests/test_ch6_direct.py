from dataclasses import replace
from xgap.experiments.ch6_direct import answer_direct
from xgap.experiments.bounded_joint_toy import local_runtime,TemplateProposalProvider,QUESTION
from xgap.semantic.interpretation import InterpretationRequest
from xgap.agent.unified_family import UnifiedSettings


def test_direct_single_proposal_same_runtime_without_authority():
    data,options,calls=local_runtime();request=InterpretationRequest(QUESTION,{'source_schema':options['source_schema']})
    class Count(TemplateProposalProvider):
        n=0
        def interpret(self,request):self.n+=1;return super().interpret(request)
    provider=Count(data['query_template'])
    report=answer_direct(request,provider,settings=UnifiedSettings(physical_moves=False),**options)
    assert report['success'],report
    assert report['answer_rows']==data['expected']
    assert provider.n==report['final_plan_executions']==1 and calls
    assert report['intent_guarantee'] is False and report['loss_certificate'] is None and report['terminal_certificate'] is None
    assert report['clarification_calls']==report['scope_confirmation_calls']==0


def test_direct_bad_proposal_is_retained_without_repair_or_execution():
    data,options,calls=local_runtime()
    provider=TemplateProposalProvider(data['query_template'])
    report=answer_direct(InterpretationRequest('outside grammar',{'source_schema':options['source_schema']}),provider,**options)
    assert not report['success'] and not calls
    assert report['final_plan_executions']==report['automatic_retries']==0
