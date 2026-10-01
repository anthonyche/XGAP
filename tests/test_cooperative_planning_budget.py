"""Stop optional work at meaningful checkpoints; keep complete feasible plans."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from test_anchor_reduction import tiny
from test_shared_native_reads import case
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.practical_execution import run_practical_semantic_query
from xgap.agent.practical_planning import BindingEvidence, BindingState, PracticalMode, PracticalSemanticDomain, program_identity
from xgap.agent.strong_planning import StrongSearchLimits, search_strong_policy
from xgap.runtime.contracts import FederatedExecutionPlan
from xgap.runtime.one_shot_planning import prepare_one_shot_domain
from xgap.runtime.planning_budget import CooperativePlanningBudget, PlanningBudgetExpired
from xgap.runtime.progressive_binding import progressive_bind
from xgap.runtime.semantic_compiler import compile_semantic_program


class ControlledEstimator:
    """Finite test estimates, not trained weights or measured execution times."""
    def __init__(self,sources,on_predict=lambda count:None):
        self.calls=[];self.on_predict=on_predict
        self.statistics=SimpleNamespace(entries=tuple(SimpleNamespace(backend_id=b,source_id=s.source_id,
            snapshot_version=s.snapshot_version) for s in sources.values() for b in s.replica_backend_ids))
    def predict(self,plan):
        self.calls.append(plan.plan_id);count=len(self.calls);self.on_predict(count)
        return SimpleNamespace(to_dict=lambda:{'status':'estimated','estimated_ms':100.0 if count==1 else 5.0})


def inputs(mode='exact'):
    program,plan,backends,clients,scheduler,calls,sources=case()
    state=BindingState(evidence=(BindingEvidence('$structure',program_identity(program),'trusted_request','tiny','v1'),))
    kwargs=dict(mode=PracticalMode(mode),operator_sources={'left':'graph','right':'graph'},binding_values={},
        sources=sources,backends=backends,physical_profile=replace(OneShotPolicy(),max_parallelism=1))
    return program,plan,state,kwargs,clients,scheduler,calls


@pytest.mark.parametrize('mode',('exact','performance'))
def test_expired_after_atomic_baseline_skips_estimation_but_executes_one_correct_plan(monkeypatch,mode):
    import xgap.agent.practical_execution as execution
    import xgap.agent.practical_planning as planning
    p,_,state,kwargs,clients,_,calls=inputs(mode);now=[0.0]
    budget=CooperativePlanningBudget(10,clock=lambda:now[0]);estimator=ControlledEstimator(kwargs['sources'])
    original=planning._baseline
    def atomic(*args,**opts):
        result=original(*args,**opts);now[0]=1.0;return result
    monkeypatch.setattr(planning,'_baseline',atomic)
    monkeypatch.setattr(execution,'CooperativePlanningBudget',lambda milliseconds:budget)
    result=run_practical_semantic_query(p,initial_state=state,backend_clients=clients,estimator=estimator,
        limits=StrongSearchLimits(improvement_actions=0),**kwargs)
    assert result['success'] and result['answer_rows']==[{'n':14}],result
    assert result['final_plan_executions']==len(calls)==1 and not estimator.calls
    assert result['execution']['estimate_status']=='planning_budget_exhausted'
    assert result['search']['selected_estimated_cost'] is None and result['cooperative_planning_budget']['expired']
    assert not result['cooperative_planning_budget']['hard_real_time_bound']


def test_expiry_inside_strategy_construction_unwinds_without_building_the_rest(monkeypatch):
    import xgap.runtime.physical_strategies as physical
    p,_,state,kwargs,_,scheduler,calls=inputs();now=[0.0];features=[]
    domain=PracticalSemanticDomain(p,estimator=ControlledEstimator(kwargs['sources']),**kwargs)
    domain.planning_checkpoint=CooperativePlanningBudget(10,clock=lambda:now[0])
    original=physical.strategy_features
    def timed(*args,**opts):
        result=original(*args,**opts);features.append(True);now[0]=1.0;return result
    monkeypatch.setattr(physical,'strategy_features',timed)
    result=search_strong_policy(state,domain,limits=StrongSearchLimits(improvement_actions=0))
    assert result.policy is not None and result.policy.estimated_cost==100 and len(features)==1
    assert len(domain.estimator.calls)==1 and any('deadline' in f['error'] for f in domain.failures)
    executed=scheduler.execute(FederatedExecutionPlan.from_dict(result.policy.terminal.payload['physical_plan']))
    assert executed.success and executed.final_rows==({'n':14},) and len(calls)==1


def test_completed_better_score_survives_expiry_before_the_next_score():
    p,_,state,kwargs,_,scheduler,calls=inputs();now=[0.0]
    def timed(count):
        if count==2:now[0]=1.0
    estimator=ControlledEstimator(kwargs['sources'],timed)
    domain=PracticalSemanticDomain(p,estimator=estimator,**kwargs)
    domain.planning_checkpoint=CooperativePlanningBudget(10,clock=lambda:now[0])
    result=search_strong_policy(state,domain,limits=StrongSearchLimits(improvement_actions=0))
    assert result.first_feasible_estimated_cost==100 and result.policy.estimated_cost==5 and len(estimator.calls)==2
    assert any(f['stage']=='optional_physical_scoring' for f in domain.failures)
    executed=scheduler.execute(FederatedExecutionPlan.from_dict(result.policy.terminal.payload['physical_plan']))
    assert executed.success and executed.final_rows==({'n':14},) and len(calls)==1


def test_progressive_checkpoint_does_not_publish_a_partially_composed_candidate(monkeypatch):
    import xgap.runtime.physical_strategies as physical
    p,placements,backends,_,_,_,calls=tiny();now=[0.0];rewrites=[]
    seed=compile_semantic_program(p,source_bindings=placements,backends=backends,max_parallelism=1)
    before=seed.to_dict();original=physical._bound_match_artifact
    def timed(*args,**kwargs):
        result=original(*args,**kwargs);rewrites.append(True);now[0]=1.0;return result
    monkeypatch.setattr(physical,'_bound_match_artifact',timed)
    with pytest.raises(PlanningBudgetExpired):
        progressive_bind(p,seed,source_bindings=placements,backends=backends,max_bindings=100,
            max_binding_bytes=65536,planning_checkpoint=CooperativePlanningBudget(10,clock=lambda:now[0]))
    assert len(rewrites)==1 and seed.to_dict()==before and not calls


def test_optional_checkpoint_keeps_legacy_domain_when_unexpired_and_is_not_a_rejection():
    p,_,_,kwargs,_,_,calls=inputs()
    args={k:v for k,v in kwargs.items() if k in ('operator_sources','sources','backends')}
    a,ma=prepare_one_shot_domain(p,policy=kwargs['physical_profile'],**args)
    b,mb=prepare_one_shot_domain(p,policy=kwargs['physical_profile'],planning_checkpoint=lambda:None,**args)
    assert [v.to_dict() for v in a]==[v.to_dict() for v in b] and ma['construction_bound']==mb['construction_bound']
    now=[0.0];expired=CooperativePlanningBudget(1,clock=lambda:now[0]);now[0]=1.0
    with pytest.raises(PlanningBudgetExpired):prepare_one_shot_domain(p,policy=kwargs['physical_profile'],planning_checkpoint=expired,**args)
    assert not calls
