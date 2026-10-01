"""Complete-AND seed precedes optional refinement; caps span both phases."""
from dataclasses import replace

import pytest

from test_strong_planning import Domain, action
from xgap.agent.strong_planning import ResourceUsage, StrongSearchLimits, TerminalAlternative as Terminal, search_strong_policy


class TimedDomain:
    def __init__(self,missing=False):
        self.seconds=0.;self.trace=[];self.missing=missing
    def clock(self):return self.seconds
    def terminals(self,state):
        if state=='root' or (state=='c' and self.missing):return
        self.seconds+=.001;self.trace.append('seed:'+state)
        yield Terminal('seed:'+state,100,{})
        self.seconds+=.010;self.trace.append('improved:'+state)
        yield Terminal('improved:'+state,90,{})
    def actions(self,state):
        if state=='root':yield action('resolve',[(s,s) for s in ('a','b','c')],cost=0)


@pytest.mark.parametrize('budget,estimate',[(15,100),(35,90)])
def test_complete_seed_survives_partial_refinement_or_improves_with_more_budget(budget,estimate):
    domain=TimedDomain()
    result=search_strong_policy('root',domain,limits=StrongSearchLimits(planning_ms=budget,max_depth=1,
        max_terminals_per_state=2,improvement_actions=0),clock=domain.clock)
    assert result.policy is not None and {k for k,_ in result.policy.children}=={'a','b','c'}
    assert result.first_feasible_ms==pytest.approx(3) and result.first_feasible_estimated_cost==100
    assert domain.trace[:3]==['seed:a','seed:b','seed:c']
    assert result.policy.estimated_cost==estimate and result.generated_actions==1 and result.retained_states==4
    assert sum(r['candidates'] for r in result.terminal_refinement_records)==(2 if budget==15 else 3)
    if budget==15:
        assert 'planning_deadline' in result.limit_events and domain.trace[-1]=='improved:b'
        assert dict(result.policy.children)['c'].terminal.terminal_id=='seed:c'


def test_no_optional_work_when_any_and_outcome_remains_unsolved():
    domain=TimedDomain(missing=True)
    result=search_strong_policy('root',domain,limits=StrongSearchLimits(max_depth=1),clock=domain.clock)
    assert result.policy is None and result.first_feasible_ms is None
    assert domain.trace==['seed:a','seed:b'] and not result.terminal_refinement_records


def test_refinement_respects_prefix_resources_and_never_resets_the_terminal_cap():
    # First terminal is not feasible; second is the seed; third would be cheaper
    # but exceeds the remaining path budget; fourth is outside the total cap.
    visited=[]
    class Capped(Domain):
        def terminals(self,state):
            if state!='leaf':return
            for name,cost,remote in [('unusable',0,5),('seed',100,1),('overspend',1,2),('outside-cap',0,0)]:
                visited.append(name);yield Terminal(name,cost,{},ResourceUsage(remote_calls=remote))
    domain=Capped({}, {'root':[action('resolve',[('ok','leaf')],resources=ResourceUsage(remote_calls=1))]})
    result=search_strong_policy('root',domain,limits=StrongSearchLimits(max_depth=1,max_terminals_per_state=3,
        resources=ResourceUsage(remote_calls=2)))
    assert result.policy.estimated_cost==101 and result.policy.children[0][1].terminal.terminal_id=='seed'
    assert visited==['unusable','seed','overspend']
    assert result.terminal_refinement_records[0]['resource_rejections']==1


def test_nested_strong_policy_survives_optional_generation_exception():
    class Broken(Domain):
        def terminals(self,state):
            if state not in ('a','b','c'):return
            yield Terminal('seed:'+state,10,{})
            raise ValueError('controlled optional optimizer failure')
    domain=Broken({}, {'root':[action('outer',[('left','middle'),('right','c')])],
        'middle':[action('inner',[('a','a'),('b','b')])]})
    result=search_strong_policy('root',domain,limits=StrongSearchLimits(max_depth=2))
    assert result.policy is not None and result.policy.estimated_cost==12
    assert len(result.terminal_refinement_records)==3 and 'optional_terminal_error' in result.limit_events
    assert all(r['status']=='optional_generation_error' and r['error_type']=='ValueError' for r in result.terminal_refinement_records)


def test_unknown_refinement_cannot_replace_known_feasible_estimate():
    domain=Domain({'root':[Terminal('known',3,{}),Terminal('unknown',None,{})]}, {})
    result=search_strong_policy('root',domain)
    assert result.policy.terminal.terminal_id=='known' and result.first_feasible_estimated_cost==3
    assert result.terminal_refinement_records[0]['candidates']==1
    assert result.terminal_refinement_records[0]['accepted']==0


def test_practical_all_authority_seeds_precede_optimization_and_one_answer_executes(tmp_path,monkeypatch):
    from test_practical_planning import prepared,clarification
    from xgap.agent.practical_execution import run_practical_semantic_query
    from xgap.agent import practical_planning as planning
    program,kwargs,calls=prepared(None)
    _,registry=clarification(tmp_path,program)
    kwargs['mode']=replace(kwargs['mode'],improve_physical=True)
    seeds=[];optional=[];baseline=planning._baseline;improve=planning.prepare_one_shot_domain
    def initial(*args,**kw):
        value=baseline(*args,**kw);seeds.append(value);return value
    def refined(*args,**kw):
        assert len(seeds)==2,'Optional work started before both authority outcomes were feasible'
        optional.append(True);return improve(*args,**kw)
    monkeypatch.setattr(planning,'_baseline',initial);monkeypatch.setattr(planning,'prepare_one_shot_domain',refined)
    result=run_practical_semantic_query(program,resolution_tools=registry,**kwargs)
    assert result['success'] and result['search']['strong'] and len(optional)==2,result
    assert result['answer_rows']==[{'person':'https://xgap.test/toy/c','edge':'https://xgap.test/toy/e2'}]
    assert result['final_plan_executions']==1 and result['clarification_calls']==1 and result['model_calls']==0
    assert len(calls)==result['backend_remote_calls']


def test_interleaved_practical_stream_can_finish_and_share_one_pending_cache(monkeypatch):
    from test_practical_planning import prepared
    from xgap.agent import practical_planning as planning
    program,kwargs,calls=prepared(None,person='bob')
    state=kwargs.pop('initial_state');kwargs.pop('backend_clients');kwargs.pop('limits')
    domain=planning.PracticalSemanticDomain(program,**kwargs)
    attempts=[];improve=planning.prepare_one_shot_domain
    def counted(*args,**kw):attempts.append(True);return improve(*args,**kw)
    monkeypatch.setattr(planning,'prepare_one_shot_domain',counted)
    first=iter(domain.terminals(state));second=iter(domain.terminals(state))
    assert next(first).terminal_id==next(second).terminal_id
    assert not attempts and domain.compiled_states==1
    resumed=list(second);original=list(first)
    assert len(resumed)==len(original)==1 and resumed[0].terminal_id==original[0].terminal_id
    assert len(attempts)==1 and not calls
