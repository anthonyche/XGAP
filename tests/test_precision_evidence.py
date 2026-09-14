"""Independent name ambiguity and quality/cost counterexamples; no real model."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from test_one_shot_grounding import inputs
from test_one_shot_split import parent as analytic_weights
from test_semantic_binding_execution import setup
from xgap.agent.one_shot_grounding import ground_interpretation
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.quality_band import quality_band
from xgap.agent.question import run_question
from xgap.experiments.toy_binding import BUNDLE_FIXTURE
from xgap.experiments.tiny_work_training import op, _program
from xgap.planning.runtime_estimator import FrozenSourceStatistics, SourceStatistics
from xgap.planning.runtime_instance_work import FrozenInstanceWorkDeployment
from xgap.semantic.interpretation import InterpretationRequest, InterpretationResponse
from xgap.semantic.interpretation_candidates import SCHEMA
from xgap.semantic.program import hard_constraints_sha256


@pytest.fixture
def model(analytic_weights):
    stats=FrozenSourceStatistics('independent-precision-mechanics','v1',tuple(
        SourceStatistics(b,'toy','toy-v1',13,100,'five entities/eight edges; width is analytic')
        for b in ('rdf_a','rdf_b')))
    return FrozenInstanceWorkDeployment('independent-precision-mechanics',analytic_weights,
        stats,(('rdf_a','fuseki'),('rdf_b','fuseki')),'analytic-frozen-no-fit')


class Authored:
    provider_id='independent-precision-candidate-fixture'
    def __init__(self,candidates):self.candidates=candidates;self.calls=0
    def interpret(self,request):
        self.calls+=1
        return InterpretationResponse({'schema_version':SCHEMA,'candidates':deepcopy(self.candidates)})


def args(model,case):
    tool,calls=setup(case)
    pin=json.loads((BUNDLE_FIXTURE/'reference.json').read_text())
    return dict(mode='precision',estimator=model,catalog_root=BUNDLE_FIXTURE/pin['root'],
        catalog_hash=pin['bundle_hash'],sources=tool.sources,backends=tool.backends,backend_clients=tool.backend_clients),calls


def test_actual_ambiguous_name_answer_changes_without_authority_or_extra_requests(model):
    case,program,_=inputs(4)
    question='In the toy graph, find people aged at least 30 known by Alex (canonical name Bob). Return people and edges.'
    required=tuple({'operator_id':o.operator_id,'constraint':c.to_dict()} for o in program.operators for c in o.constraints)
    request=InterpretationRequest(question,context={'query_id':'precision-new-alias','require_complete_results':True},
        required_constraints=required)
    provider=Authored([{'candidate_id':'alias','quality_proxy':.9,'program':program.to_dict(),
        'operator_sources':case['operator_sources']}])
    kwargs,calls=args(model,case);before=model.to_dict();original=program.to_dict()
    old=replace(OneShotPolicy.for_mode('precision'),max_parallelism=1)
    new=replace(old,grounding_ranking='canonical_context_v1',max_quality_deficit=.1)
    legacy=run_question(request,provider,one_shot_policy=old,**kwargs)
    current=run_question(request,provider,one_shot_policy=new,**kwargs)
    assert legacy['success'] and current['success'],(legacy.get('error'),current.get('error'))
    assert legacy['answer_rows']==[{'person':'https://xgap.test/toy/c','edge':'https://xgap.test/toy/e4'}]
    assert current['answer_rows']==[{'person':'https://xgap.test/toy/c','edge':'https://xgap.test/toy/e2'}]
    chosen=next(r for r in current['selected_grounding']['candidate_sets'] if r['hole_id']=='person')
    assert chosen['selected_candidate_id']=='entity:bob' and chosen['original_candidate_ids']==['entity:alice','entity:bob']
    assert chosen['ranking_evidence'][0]['canonical_label_in_question'] and not chosen['authoritative']
    assert not chosen['evidence_is_authority'] and current['approximation']['grounding']['approximate']
    assert current['selected_grounding']['resolution']['hard_constraints_sha256']==hard_constraints_sha256(program)
    assert model.to_dict()==before and program.to_dict()==original
    assert current['final_plan_executions']==legacy['final_plan_executions']==1 and provider.calls==2
    assert len(calls)==current['backend_remote_calls']+legacy['backend_remote_calls']
    assert current['selection']['algorithm']=='estimated_argmin_within_proxy_quality_band_v1'
    assert not current['observation_calls']
    print(json.dumps({'gate':'precision-alias','legacy_rows':legacy['answer_rows'],'contextual_rows':current['answer_rows'],
        'one_final_plan_per_request':True,'provider_kind':'authored','model_calls':0}))


@pytest.mark.parametrize('question,expected',[
    ('Find Alex (Bob).','entity:bob'),
    ('Find Alex, with Bobby nearby.','entity:alice'),
    ('Find Alex; both Alice and Bob are mentioned.','entity:alice')])
def test_context_word_boundary_and_ambiguous_ties_keep_predictions(question,expected):
    case,program,bundle=inputs(4)
    _,trace=ground_interpretation(program,case['operator_sources'],bundle,question,
        ranking_policy='canonical_context_v1')
    person=next(r for r in trace['candidate_sets'] if r['hole_id']=='person')
    assert person['selected_candidate_id']==expected and not person['authoritative']
    assert trace['candidate_combinations_materialized'] is False and trace['external_calls']==0


def test_cap_and_authoritative_singleton_cannot_be_overridden_by_context():
    case,program,bundle=inputs(4)
    _,trace=ground_interpretation(program,case['operator_sources'],bundle,'Alex (Bob)',
        max_candidates_per_hole=1,ranking_policy='canonical_context_v1')
    person=next(r for r in trace['candidate_sets'] if r['hole_id']=='person')
    assert person['selected_candidate_id']=='entity:alice' and person['truncated'] and not person['authoritative']
    program=replace(program,holes=tuple(replace(h,mention='Alice') if h.hole_id=='person' else h for h in program.holes))
    _,trace=ground_interpretation(program,case['operator_sources'],bundle,'Alice and Bob',ranking_policy='canonical_context_v1')
    person=next(r for r in trace['candidate_sets'] if r['hole_id']=='person')
    assert person['selected_candidate_id']=='entity:alice' and person['authoritative']


def test_quality_band_scope_ties_and_unknown_fallback_are_explicit():
    winners=[{'candidate_id':name,'quality_proxy':q,'ranking_quality_proxy':q,'estimated_ms':cost}
        for name,q,cost in [('high',.9,10000),('near',.85,100),('cheap',.4,1)]]
    allowed,trace=quality_band(winners,.1)
    chosen=min(allowed,key=lambda r:r['estimated_ms'])
    assert chosen['candidate_id']=='near' and trace['excluded_candidate_ids']==['cheap']
    assert chosen['ranking_quality_proxy']>=trace['minimum_eligible_ranking_quality_proxy']
    assert trace['all_quality_proxies_known'] and not trace['quality_proxy_calibrated']
    unknown=[{**row,'quality_proxy':None,'ranking_quality_proxy':.5} for row in winners]
    allowed,trace=quality_band(unknown,0)
    assert len(allowed)==3 and not trace['all_quality_proxies_known']
    assert not trace['legacy_soft_penalty_used']
    with pytest.raises(ValueError,match='precision mode'):
        replace(OneShotPolicy.for_mode('performance'),max_quality_deficit=.1)
    with pytest.raises(ValueError,match='finite'):
        replace(OneShotPolicy.for_mode('precision'),max_quality_deficit=float('nan'))
    for mode in ('precision','performance'):
        old=OneShotPolicy.for_mode(mode).to_dict()
        assert old['schema_version']=='xgap-one-shot-policy-v1'
        assert 'max_quality_deficit' not in old and 'grounding_ranking' not in old


def test_quality_band_changes_actual_single_selected_answer_when_cost_favors_wrong_meaning(model):
    case,_,_=inputs(0);kwargs,calls=args(model,case)
    def candidate(identifier,entity,quality,extra=False):
        nodes=[op('person','match',parameters={'node':{'label':'Person','properties':{'id':entity}},
            'entity_field':'person','properties':{'name':'name'}})]
        if extra:nodes.append(op('answer','project',('person',),parameters={'projections':{
            'person':{'kind':'field','field':'person'},'name':{'kind':'field','field':'name'}}}))
        return {'candidate_id':identifier,'quality_proxy':quality,'program':_program(identifier,nodes).to_dict(),
            'operator_sources':{'person':'toy'}}
    provider=Authored([candidate('cheap','a',.4),candidate('supported','b',.9,True)])
    request=InterpretationRequest('Return Bob and his name.',context={'query_id':'precision-cost-counterexample'})
    # Lambda=0 isolates cost from the explicit quality-band constraint; no fitted or observed timings.
    base=replace(OneShotPolicy.for_mode('precision'),max_parallelism=1,quality_penalty_ms=0)
    legacy=run_question(request,provider,one_shot_policy=base,**kwargs)
    constrained=run_question(request,provider,one_shot_policy=replace(base,max_quality_deficit=.1),**kwargs)
    assert legacy['success'] and constrained['success'],(legacy.get('error'),constrained.get('error'))
    assert legacy['selection']['candidate_id']=='cheap'
    assert constrained['selection']['candidate_id']=='supported'
    assert legacy['answer_rows']==[{'person':'https://xgap.test/toy/a','name':'Alice'}]
    assert constrained['answer_rows']==[{'person':'https://xgap.test/toy/b','name':'Bob'}]
    assert constrained['selection']['quality_band']['excluded_candidate_ids']==['cheap']
    assert constrained['final_plan_executions']==legacy['final_plan_executions']==1 and provider.calls==2
    assert len(calls)==2 and not constrained['observation_calls']
    print(json.dumps({'gate':'precision-quality-band','unconstrained':legacy['answer_rows'],
        'constrained':constrained['answer_rows'],'quality_deficit':.1,'model_calls':0}))
