"""Evidence-progress pruning with real in-process answers and unchanged alternatives."""
from dataclasses import replace

import pytest

from test_practical_planning import prepared, clarification
from test_precision_evidence import model, analytic_weights
from xgap.agent.practical_execution import run_practical_semantic_query
from xgap.agent.practical_planning import BindingAction, PracticalMode
from xgap.agent.strong_planning import ResourceUsage
from xgap.tools import ToolRegistry
from xgap.tools.contracts import FunctionTool, ToolSpec, ToolResult


def with_proposal(kwargs, registry, calls):
    proposal=BindingAction('propose-person','person','fixture.propose',
        (('alice','entity:alice'),('bob','entity:bob'),('error',None)),
        'proposal-only','v1',estimated_ms=None,resources=ResourceUsage(1,20,1))
    kwargs['actions']=(proposal,*(replace(a,estimated_ms=None,search_priority=1) for a in kwargs['actions']))
    def propose(args,context):
        calls.append(args)
        return ToolResult.success('fixture.propose',
            {k:args[k] for k in ('slot','program_sha256','source_id','version')}|{'candidate_id':'entity:alice'},
            metrics={'model_calls':1,'tokens':5,'remote_calls':1})
    registry.register(FunctionTool(ToolSpec('fixture.propose','Controlled unvalidated proposal',{},'binding'),propose))


@pytest.mark.parametrize('person,edge',[('alice','e4'),('bob','e2')])
def test_exact_skips_proposal_but_retains_both_authoritative_answers(model,tmp_path,person,edge):
    program,kwargs,source_calls=prepared(model)
    _,registry=clarification(tmp_path,program,'entity:'+person)
    model_calls=[];with_proposal(kwargs,registry,model_calls)
    result=run_practical_semantic_query(program,resolution_tools=registry,**kwargs)
    assert result['success'],result
    assert result['answer_rows']==[{'person':'https://xgap.test/toy/c','edge':'https://xgap.test/toy/'+edge}]
    assert result['search']['strong'] and set(result['search']['policy']['children'])=={'alice','bob'}
    assert result['acquisition_pruning']['pruned_action_ids']==['propose-person']
    assert [a['action_id'] for a in result['acquisition_actions']]==['propose-person','clarify-person']
    assert result['search']['selected_estimated_cost'] is None
    assert not model_calls and result['model_calls']==0 and result['clarification_calls']==1
    assert result['final_plan_executions']==1 and len(source_calls)==result['backend_remote_calls']
    assert result['execution']['unvalidated_bindings']==[]


@pytest.mark.parametrize('missing_authority',[False,True])
def test_pruning_never_invents_authority_or_drops_its_failure_branch(model,tmp_path,missing_authority):
    program,kwargs,source_calls=prepared(model,unknown_outcome=True)
    _,registry=clarification(tmp_path,program)
    model_calls=[];with_proposal(kwargs,registry,model_calls)
    if missing_authority:
        kwargs['actions']=kwargs['actions'][:1]
    result=run_practical_semantic_query(program,resolution_tools=registry,**kwargs)
    assert result['status']=='no_feasible_plan' and not result['search']['strong']
    assert result['model_calls']==result['clarification_calls']==result['final_plan_executions']==0
    assert not source_calls and not model_calls
    if not missing_authority:
        assert result['search']['action_records'][0]['outcomes']==['alice','bob','unavailable']


def test_invalid_proposal_is_still_rejected_before_pruning(model,tmp_path):
    program,kwargs,source_calls=prepared(model)
    _,registry=clarification(tmp_path,program)
    model_calls=[];with_proposal(kwargs,registry,model_calls)
    kwargs['actions']=(replace(kwargs['actions'][0],outcomes=(('bad','entity:outside'),)),*kwargs['actions'][1:])
    with pytest.raises(ValueError,match='declared slot type'):
        run_practical_semantic_query(program,resolution_tools=registry,**kwargs)
    assert not model_calls and not source_calls


def test_performance_keeps_the_model_and_its_declared_failure_continuation(model,tmp_path):
    program,kwargs,source_calls=prepared(model,mode=PracticalMode('performance',('person',)))
    _,registry=clarification(tmp_path,program)
    model_calls=[];with_proposal(kwargs,registry,model_calls)
    result=run_practical_semantic_query(program,resolution_tools=registry,**kwargs)
    assert result['success'] and result['search']['strong'],result
    assert set(result['search']['policy']['children'])=={'alice','bob','error'}
    assert result['acquisition_pruning']['pruned_action_ids']==[]
    assert len(model_calls)==result['model_calls']==1 and result['clarification_calls']==0
    assert result['execution']['unvalidated_bindings']==['person'] and result['final_plan_executions']==1
    assert result['answer_rows']==[{'person':'https://xgap.test/toy/c','edge':'https://xgap.test/toy/e4'}]


def test_fixed_external_frontend_keeps_its_declared_exact_sequence(tmp_path):
    from test_fixed_information_frontend import setup, prepared as prepare_external, proposal
    from xgap.agent.fixed_information_frontend import prepare_fixed_information_query
    parts=setup(tmp_path,prediction=None)
    exact=prepare_external(parts,'exact');performance=prepare_external(parts,'performance')
    opts=performance.options;calls=[];registry=ToolRegistry()
    def handler(args,context):
        calls.append(args);return proposal(args,context)
    for spec in opts.resolution_tools.specs():
        registry.register(FunctionTool(spec,handler) if spec.remote else opts.resolution_tools.get(spec.name))
    cfg=parts[1]
    result=prepare_fixed_information_query(exact.program,initial_state=exact.options.initial_state,
        mode=exact.options.mode,actions=opts.actions,predictions={},resolution_tools=registry,
        limits=opts.limits,physical_profile=opts.physical_profile,operator_sources=exact.provider.operator_sources,
        binding_values=cfg[2].bindings,sources=cfg[4],backends=cfg[5],mapping=parts[4])
    assert result['success'] and len(calls)==result['model_calls']==1,result
    assert result['clarification_calls']==1 and result['acquisition_attempts']==2
    assert result['selected_program']['operators'][0]['parameters']['edge']['label']=='FOLLOWS'
    assert result['compilations']==1 and result['strong_plan'] is None
