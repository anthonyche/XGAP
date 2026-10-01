"""Keep mandatory anchor bindings ahead of truncation; independent tiny witnesses."""
from dataclasses import replace
import json

import pytest
from rdflib import Graph

from test_anchor_reduction import tiny, EXPECTED, PREFIX, NS
from test_anchor_source_bind import space, fanout
from test_budgeted_retrieval import model, analytic_weights
from test_one_shot_question import PIN, BUNDLE_FIXTURE
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.question import run_question
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.runtime.one_shot_planning import prepare_one_shot_domain
from xgap.runtime.retrieval_budget import apply_retrieval_budget, retrieval_observation
from xgap.runtime.semantic_planning import LogicalSource
from xgap.semantic.interpretation import InterpretationRequest, InterpretationResponse
from xgap.semantic.interpretation_candidates import SCHEMA


LATE_EXPECTED=tuple({'other':NS+entity,'length':length}
                   for length,entity in [(1,'a'),(2,'b'),(2,'c'),(3,'c'),(3,'d')])


@pytest.mark.parametrize('anchor,budget',[('a',2),('e',1)])
def test_real_bind_before_cap_preserves_independent_nonempty_witnesses(anchor,budget):
    p,slots,b,graphs,_,scheduler,calls=tiny()
    graphs['rdf_b']=Graph().parse(data=PREFIX+f't:{anchor} a t:Person; t:age 20.',format='turtle')
    choices=space(p,slots,b);base=choices.candidates[0].plan
    protected=apply_retrieval_budget(fanout(choices).plan,p,budget,scope='bind_after_anchor_v1')
    baseline,limited=scheduler.execute(base),scheduler.execute(protected)
    expected=EXPECTED if anchor=='a' else LATE_EXPECTED
    assert baseline.success and limited.success
    assert baseline.final_rows==expected
    assert limited.final_rows and {json.dumps(r,sort_keys=True) for r in limited.final_rows} <= {
        json.dumps(r,sort_keys=True) for r in expected}
    if anchor=='e':assert limited.final_rows==expected
    remote=lambda result:sum(n.metadata.get('retrieval_budget',{}).get('source_rows_received',n.row_count)
        for n in result.node_results if n.kind in (R.REMOTE_QUERY,R.REMOTE_BIND_QUERY))
    assert remote(limited)<remote(baseline)
    spec=protected.metadata['retrieval_budget']
    assert spec['anchor_binding_guard_applied'] and spec['uncapped_relationship_nodes']
    by_id={n.node_id:n for n in protected.nodes}
    assert all(by_id[n].kind is R.REMOTE_BIND_QUERY for n in spec['bounded_nodes'])
    assert all('retrieval_budget' not in by_id[n].parameters['artifact']['parameters']
        for n in spec['uncapped_relationship_nodes'])
    observed=retrieval_observation(protected,limited.to_dict())
    assert observed['source_rows_omitted']==(anchor=='a')
    if anchor=='e':
        naive=apply_retrieval_budget(base,p,budget)
        wrong=scheduler.execute(naive)
        assert wrong.success and not wrong.final_rows  # Global prefix loses the late anchor.
    print(json.dumps({'gate':'anchor-before-budget','anchor':anchor,'row_budget':budget,
        'full_source_rows':remote(baseline),'budgeted_source_rows':remote(limited),
        'answer_rows':len(limited.final_rows),'full_gold_rows':len(expected),
        'independent_answer_exact':limited.final_rows==expected}))


def test_coordinator_anchor_fragments_stay_complete_and_equivalence_keys_agree(model):
    p,slots,b,_,_,_,calls=tiny()
    sources={s:LogicalSource(s,'tiny-v1',(backend,)) for s,backend in [('graph','rdf_a'),('control','rdf_b')]}
    op_sources={op:'graph' if backend=='rdf_a' else 'control' for op,backend in slots.items()}
    policy=replace(OneShotPolicy.for_mode('performance'),max_parallelism=1,retrieval_rows_per_relation=1,
        retrieval_scope='bind_after_anchor_v1')
    candidates,_=prepare_one_shot_domain(p,operator_sources=op_sources,sources=sources,backends=b,policy=policy)
    full=next(c for c in candidates if c.strategy_id=='placement-0/coordinator')
    assert full.plan.metadata['retrieval_budget']['bounded_nodes']==[]
    assert full.plan.metadata['retrieval_budget']['uncapped_relationship_nodes']
    for c in candidates:
        assert c.semantic_equivalence_key==c.plan.metadata['semantic_equivalence_key']
        assert c.plan.metadata['semantic_equivalence_scope']=='this budgeted plan only'
        assert model.predict(c.plan).status=='estimated'
    assert not calls and len({c.semantic_equivalence_key for c in candidates})==len(candidates)


def test_ordinary_estimated_selection_keeps_late_anchor_without_probing(model):
    p,slots,b,graphs,clients,_,calls=tiny()
    graphs['rdf_b']=Graph().parse(data=PREFIX+'t:e a t:Person; t:age 20.',format='turtle')
    sources={s:LogicalSource(s,'tiny-v1',(backend,)) for s,backend in [('graph','rdf_a'),('control','rdf_b')]}
    op_sources={op:'graph' if backend=='rdf_a' else 'control' for op,backend in slots.items()}
    policy=replace(OneShotPolicy.for_mode('performance'),max_parallelism=1,retrieval_rows_per_relation=1,
        retrieval_scope='bind_after_anchor_v1')
    class Authored:
        provider_id='independent-late-anchor'
        calls=0
        def interpret(self,request):
            self.calls+=1
            return InterpretationResponse({'schema_version':SCHEMA,'candidates':[{'candidate_id':'late',
                'quality_proxy':1,'program':p.to_dict(),'operator_sources':op_sources}]})
    provider=Authored()
    result=run_question(InterpretationRequest('Follow one to three acyclic links from the person aged 20.',
        context={'query_id':'independent-late-anchor'}),provider,mode='performance',one_shot_policy=policy,
        estimator=model,catalog_root=BUNDLE_FIXTURE/PIN['root'],catalog_hash=PIN['bundle_hash'],
        sources=sources,backends=b,backend_clients=clients)
    assert result['success'],result.get('error')
    assert result['answer_rows']==list(LATE_EXPECTED)
    predictions=[r['prediction']['estimated_ms'] for r in result['candidates'][0]['plans'] if r['status']=='estimated']
    assert result['selection']['estimated_ms']==min(predictions)
    assert provider.calls==result['final_plan_executions']==1 and len(calls)==result['backend_remote_calls']
    assert not result['observation_calls']
    print(json.dumps({'gate':'ordinary-anchor-budget','selected':result['selection']['strategy_id'],
        'answer_rows':len(result['answer_rows']),'source_calls':len(calls),'model_calls':0}))
