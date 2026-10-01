"""Known-cost search ordering changes only XGAP information choices, not fixed baselines."""
from dataclasses import replace

import pytest

from test_exact_information_pruning import with_proposal
from test_practical_planning import prepared, clarification
from test_precision_evidence import model, analytic_weights
from xgap.agent.practical_execution import run_practical_semantic_query
from xgap.agent.practical_planning import PracticalMode


@pytest.mark.parametrize('proposal_ms,authority_ms,chosen,edge',[
    (100,1,'clarify-person','e2'),(1,100,'propose-person','e4')])
def test_actual_followed_branch_uses_known_cost_and_keeps_semantic_permissions(model,tmp_path,proposal_ms,authority_ms,chosen,edge):
    program,kwargs,source_calls=prepared(model,mode=PracticalMode('performance',('person',)))
    _,registry=clarification(tmp_path,program)
    model_calls=[];with_proposal(kwargs,registry,model_calls)
    kwargs['actions']=tuple(replace(a,estimated_ms=proposal_ms if a.authority is None else authority_ms) for a in kwargs['actions'])
    result=run_practical_semantic_query(program,resolution_tools=registry,**kwargs)
    assert result['success'] and result['search']['strong'],result
    assert result['search']['policy']['action_id']==chosen
    assert result['answer_rows']==[{'person':'https://xgap.test/toy/c','edge':'https://xgap.test/toy/'+edge}]
    assert result['model_calls']==len(model_calls)==int(chosen=='propose-person')
    assert result['clarification_calls']==int(chosen=='clarify-person') and result['final_plan_executions']==1
    assert result['execution']['unvalidated_bindings']==(['person'] if chosen=='propose-person' else [])
    if chosen=='propose-person':assert set(result['search']['policy']['children'])=={'alice','bob','error'}


def test_fixed_exact_frontend_does_not_adopt_xgap_cost_order(tmp_path,monkeypatch):
    import test_fixed_information_frontend as fixture
    parts=fixture.setup(tmp_path,prediction=None)
    q=fixture.prepared(parts,'performance');exact=fixture.prepared(parts,'exact')
    q=replace(q,options=replace(q.options,mode=exact.options.mode,
        actions=tuple(replace(a,estimated_ms=100 if a.authority is None else 1) for a in q.options.actions)))
    monkeypatch.setattr(fixture,'prepared',lambda parts,mode:q)
    calls=[]
    def handler(args,context):
        calls.append(args);return fixture.proposal(args,context)
    result=fixture.run(parts,'exact',handler=handler)
    assert result['success'] and result['model_calls']==len(calls)==1,result
    assert result['clarification_calls']==1 and result['acquisition_attempts']==2
    assert result['actions'][0]['tool_name']=='practical.llm:predicate'
    assert result['selected_program']['operators'][0]['parameters']['edge']['label']=='FOLLOWS'
