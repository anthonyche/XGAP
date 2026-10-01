"""A physical sharing step must not erase an independently usable filter port."""
from dataclasses import replace

from test_ch6_financial_scalability_planning import inputs
from xgap.agent.intent_certificate import IntentCandidate, IntentFamily, fingerprint
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.practical_planning import _baseline
from xgap.experiments.ch6_financial_scalability_queries import build_workload
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.runtime.source_row_filters import pending_source_row_prefilters
from xgap.runtime.unified_physical import PhysicalMoves
from xgap.semantic.compact_lowering import lower_compact_query


def test_every_local_move_preserves_independent_anchor_filter_opportunity():
    schema,assignment,sources,backends,_=inputs(32)
    sid=assignment[16]
    local_schema={k:v for k,v in schema.items() if k==sid or not isinstance(v,dict) or 'nodes' not in v}
    query=build_workload(nodes_per_bank=9)['cases'][0]['branches'][16]['query']
    family=IntentFamily('sharing-regression',(IntentCandidate.create(fingerprint(query),query),),(),
        'fixed-fixture',language_version='v2',coverage_basis='resolved authored query')
    program,placements=lower_compact_query(query,local_schema,version='v2',optimize=True)
    policy=replace(OneShotPolicy.for_mode('performance'),max_parallelism=4,retrieval_rows_per_relation=None)
    seed=_baseline(program,placements,{sid:sources[sid]},{sid:backends[sid]},policy,optimize_reads=False)
    assert 'cq0/native' in pending_source_row_prefilters(program,seed)
    moves=PhysicalMoves(family,local_schema,{sid:backends[sid]},policy,{sid:sources[sid]})
    neighbors=list(moves.neighbors(0,seed))
    assert neighbors and any(p.metadata['unified_rewrite']['rule']=='prefilter' for p in neighbors)
    for plan in neighbors:
        first=next(n for n in plan.nodes if n.node_id=='cq0/native')
        assert first.semantic_operator_ids==('cq0',)
        assert (first.kind is R.REMOTE_BIND_QUERY or
                first.parameters['artifact']['parameters'].get('necessary_row_filters') or
                'cq0/native' in pending_source_row_prefilters(program,plan))
