"""Strong-policy -> typed binding/compiler -> real in-process SPARQL answers."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from test_one_shot_grounding import inputs
from test_precision_evidence import model, analytic_weights
from test_semantic_binding_execution import setup
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.practical_execution import FrozenClarificationTool, run_practical_semantic_query
from xgap.agent.practical_planning import (BindingAction, BindingEvidence, BindingState, PracticalMode,
    PracticalSemanticDomain, program_identity)
from xgap.agent.strong_planning import StrongSearchLimits, search_strong_policy
from xgap.tools import ToolRegistry


def prepared(model, *, person=None, mode=PracticalMode(), unknown_outcome=False, improve=False):
    case, program, bundle = inputs(4)
    tool, calls = setup(case)
    # These are authored query input slots. No expected answer rows enter the planner.
    fixed = {'predicate':'KNOWS', 'type':'Person', 'age':30, 'source':'toy'}
    values = {slot: next(key for key, value in bundle.bindings.items() if value.value == scalar and
              value.kind == next(h.kind for h in program.holes if h.hole_id == slot)) for slot, scalar in fixed.items()}
    if person is not None:
        values['person'] = 'entity:' + person
    evidence = [BindingEvidence('$structure', program_identity(program), 'trusted_request', 'toy-template', 'v1')]
    evidence += [BindingEvidence(slot, candidate, 'trusted_request', 'toy-request', 'v1') for slot, candidate in values.items()]
    initial = BindingState(tuple(sorted(values.items())), tuple(evidence))
    outcomes = (('alice','entity:alice'),('bob','entity:bob')) + ((('unavailable',None),) if unknown_outcome else ())
    action = BindingAction('clarify-person','person','practical.clarify',outcomes,'toy-clarification','v1','clarification',2)
    kwargs = dict(initial_state=initial, operator_sources=case['operator_sources'], binding_values=bundle.bindings,
        sources=tool.sources, backends=tool.backends, backend_clients=tool.backend_clients, estimator=model,
        actions=(action,), mode=mode, physical_profile=replace(OneShotPolicy(),max_parallelism=1),
        limits=StrongSearchLimits(improvement_actions=0))
    return program, kwargs, calls


def clarification(tmp_path, program, candidate='entity:bob'):
    path=tmp_path/'bindings-only.json'
    path.write_text(json.dumps({'schema_version':'xgap-clarification-bindings-v1',
        'program_sha256':program_identity(program),'source_id':'toy-clarification','version':'v1',
        'bindings':{'person':candidate}}))
    registry=ToolRegistry(); registry.register(FrozenClarificationTool(path))
    return path, registry


@pytest.mark.parametrize('person,edge', [('alice','e4'),('bob','e2')])
def test_each_declared_clarification_branch_compiles_and_only_actual_branch_executes(model,tmp_path,monkeypatch,person,edge):
    program,kwargs,calls=prepared(model)
    path,registry=clarification(tmp_path,program,'entity:'+person)
    reads=[]; original=Path.read_text
    def watched(self,*args,**kw):
        if self==path: reads.append(str(self))
        return original(self,*args,**kw)
    monkeypatch.setattr(Path,'read_text',watched)
    planned=run_practical_semantic_query(program, resolution_tools=registry,execute=False,**kwargs)
    assert planned['status']=='planned' and not reads and not calls
    assert set(planned['search']['policy']['children'])=={'alice','bob'}
    result=run_practical_semantic_query(program,resolution_tools=registry,**kwargs)
    assert result['success'], result
    assert result['answer_rows']==[{'person':'https://xgap.test/toy/c','edge':'https://xgap.test/toy/'+edge}]
    assert len(reads)==1 and result['final_plan_executions']==1
    assert len(calls)==result['backend_remote_calls'] and result['model_calls']==0
    assert result['clarification_calls']==1 and result['execution']['unvalidated_bindings']==[]
    assert result['search']['external_calls_during_search']==0 and not result['optimality_certified']


def test_authoritative_fast_path_needs_no_clarification_or_model(model):
    program,kwargs,calls=prepared(model,person='bob')
    result=run_practical_semantic_query(program,**kwargs)
    assert result['success'] and result['search']['generated_actions']==0
    assert result['clarification_calls']==result['model_calls']==0 and result['final_plan_executions']==1
    assert result['answer_rows']==[{'person':'https://xgap.test/toy/c','edge':'https://xgap.test/toy/e2'}]


def test_performance_root_prediction_is_explicit_and_metric_is_not_invented(model):
    program,kwargs,calls=prepared(model,mode=PracticalMode('performance',('person',)))
    kwargs['predictions']={'person':'entity:alice'}
    result=run_practical_semantic_query(program,**kwargs)
    assert result['success'] and result['search']['generated_actions']==0 and result['clarification_calls']==0
    assert result['answer_rows']==[{'person':'https://xgap.test/toy/c','edge':'https://xgap.test/toy/e4'}]
    assert result['execution']['unvalidated_bindings']==['person']
    assert not result['execution']['bindings']['person']['authoritative']
    assert result['semantic_discrepancy_upper_bound'] is None and result['discrepancy_status']=='metric_deferred'
    with pytest.raises(ValueError,match='metric is deferred'):
        PracticalMode('performance',('person',),epsilon=.1)


def test_required_authority_and_authorized_prediction_have_distinct_admission(model):
    for mode in (PracticalMode(),PracticalMode('performance')):
        program,kwargs,calls=prepared(model,mode=mode)
        result=run_practical_semantic_query(program,predictions={'person':'entity:bob'},**kwargs)
        assert result['status']=='no_feasible_plan' and result['final_plan_executions']==0 and not calls
    with pytest.raises(ValueError,match='trusted scoped authority'):
        BindingEvidence('person','entity:bob','llm','model','v1')


def test_unknown_declared_outcome_prevents_false_strong_plan(model,tmp_path):
    program,kwargs,calls=prepared(model,unknown_outcome=True)
    path,registry=clarification(tmp_path,program)
    result=run_practical_semantic_query(program,resolution_tools=registry,**kwargs)
    assert not result['success'] and not calls
    assert result['search']['action_records'][0]['outcomes']==['alice','bob','unavailable']
    assert result['status']=='no_feasible_plan'


def test_missing_estimator_and_physical_domain_cap_keep_feasible_fallback(model):
    program,kwargs,calls=prepared(None,person='bob')
    kwargs['physical_profile']=replace(kwargs['physical_profile'],max_physical_candidates=1)
    result=run_practical_semantic_query(program,**kwargs)
    assert result['success'] and result['final_plan_executions']==1 and result['search']['strong']
    assert result['search']['selected_estimated_cost'] is None
    assert any(f['stage']=='optional_physical_improvement' for f in result['planning_failures'])
    assert result['execution']['estimate_status']=='estimator_unavailable'


def test_unmodeled_provider_failure_is_terminal_and_does_not_retry_or_execute(model,tmp_path):
    program,kwargs,calls=prepared(model)
    path,registry=clarification(tmp_path,program,'entity:outside')
    result=run_practical_semantic_query(program,resolution_tools=registry,**kwargs)
    assert not result['success'] and result['final_plan_executions']==0 and not calls
    obs=[o for o in result['execution_state']['observations'] if o['kind']=='tool_result']
    assert len(obs)==1 and 'Unmodeled' in result['execution_state']['message']


def test_trusted_structure_must_match_and_validation_cannot_be_overwritten(model,tmp_path):
    program,kwargs,calls=prepared(model,person='bob')
    wrong=replace(kwargs['initial_state'].evidence[0],candidate_id='different-query')
    kwargs['initial_state']=replace(kwargs['initial_state'],evidence=(wrong,*kwargs['initial_state'].evidence[1:]))
    with pytest.raises(ValueError,match='query skeleton'):
        run_practical_semantic_query(program,**kwargs)
    assert not calls


def test_common_nl_entry_reuses_template_interpretation_and_one_strong_terminal(model):
    from xgap.agent.practical_question import PracticalQuestionOptions
    from xgap.agent.question import run_question
    from xgap.experiments.toy_binding import interpretation_inputs, BUNDLE_FIXTURE, load_binding_cases
    from xgap.semantic.program import SemanticGraphProgram
    # Trusted template preparation, independent of rows; this is not live LLM evidence.
    case=load_binding_cases()[0]
    request,provider=interpretation_inputs(case)
    template_program=SemanticGraphProgram.from_dict(provider.interpret(request).payload['program'])
    _,kwargs,calls=prepared(model,person='alice')
    state=kwargs['initial_state']
    state=replace(state,evidence=(BindingEvidence('$structure',program_identity(template_program),
        'trusted_request','frozen-intake-template','v1'),*state.evidence[1:]))
    options=PracticalQuestionOptions(state,limits=kwargs['limits'],physical_profile=kwargs['physical_profile'])
    pin=json.loads((BUNDLE_FIXTURE/'reference.json').read_text())
    result=run_question(request,provider,practical_options=options,estimator=model,
        catalog_root=BUNDLE_FIXTURE/pin['root'],catalog_hash=pin['bundle_hash'],
        sources=kwargs['sources'],backends=kwargs['backends'],backend_clients=kwargs['backend_clients'])
    assert result['success'], result
    assert result['answer_rows']==case['expected_rows']
    assert result['final_plan_executions']==1 and result['model_calls']==0 and result['clarification_calls']==0
    assert len(calls)==result['backend_remote_calls'] and result['search']['strong']


def test_final_backend_failure_is_not_replaced_with_another_policy_branch(model):
    from xgap.experiments.toy_binding import load_binding_cases
    program,kwargs,calls=prepared(model,person='bob')
    broken,attempts=setup(load_binding_cases()[4],fail=True)
    kwargs['backend_clients']=broken.backend_clients
    result=run_practical_semantic_query(program,**kwargs)
    assert not result['success'] and result['final_plan_executions']==1
    # A federated plan has multiple distinct fragments; these are not retries.
    assert len(attempts)==result['backend_remote_calls'] and len(set(attempts))==len(attempts)
    assert result['answer_rows'] is None and not calls


def test_missing_proposal_usage_is_reserved_but_not_reported_as_zero(model):
    from xgap.agent.strong_planning import ResourceUsage
    from xgap.tools.contracts import FunctionTool, ToolSpec, ToolResult
    program,kwargs,calls=prepared(model,mode=PracticalMode('performance',('person',)))
    kwargs['actions']=(BindingAction('propose','person','fixture.propose',(('bob','entity:bob'),),
        'bounded-proposal','v1',resources=ResourceUsage(1,20,0)),)
    registry=ToolRegistry()
    registry.register(FunctionTool(ToolSpec('fixture.propose','Controlled proposal with unavailable usage',{},'binding'),
        lambda args,ctx: ToolResult.success('fixture.propose',
            {k:args[k] for k in ('slot','program_sha256','source_id','version')}|{'candidate_id':'entity:bob'})))
    result=run_practical_semantic_query(program,resolution_tools=registry,**kwargs)
    assert result['success'] and result['model_calls'] is None and result['tokens'] is None
    assert not result['actual_acquisition_usage_complete']
    assert result['resource_reservation_used']=={'model_calls':1,'tokens':20,'remote_calls':0}


@pytest.mark.parametrize('available',[('rdf_b',),()])
def test_known_adapter_availability_is_part_of_strong_plan_admission(model,available):
    program,kwargs,calls=prepared(model,person='bob')
    kwargs['backend_clients']={b:c for b,c in kwargs['backend_clients'].items() if b in available}
    result=run_practical_semantic_query(program,**kwargs)
    if available:
        assert result['success'],result
        assert all(backend=='rdf_b' for backend,_ in calls)
        assert result['answer_rows']==[{'person':'https://xgap.test/toy/c','edge':'https://xgap.test/toy/e2'}]
    else:
        assert result['status']=='no_feasible_plan' and not result['search']['strong'] and not calls
