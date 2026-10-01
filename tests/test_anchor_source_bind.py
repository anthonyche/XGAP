"""New fanout source-binding risks on tiny RDF facts; no external services."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from test_anchor_reduction import tiny, EXPECTED, PREFIX
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.experiments.schema_source_routing import source_assignments
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.runtime.one_shot_planning import prepare_one_shot_domain
from xgap.runtime.physical_strategies import prepare_physical_strategies
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.program import SemanticGraphProgram


def space(p,s,b,**kwargs):
    return prepare_physical_strategies(p,source_bindings=s,backends=b,max_parallelism=1,**kwargs)


def fanout(domain):
    return next(c for c in domain.candidates if c.strategy_id=='anchor_fanout_bind')


def test_fanout_restricts_all_first_hops_without_losing_parallel_or_path_answers():
    p,s,b,_,_,scheduler,calls=tiny();before=p.to_dict()
    domain=space(p,s,b);base=domain.candidates[0];bound=fanout(domain)
    assert not calls and p.to_dict()==before
    assert bound.features['bind_query_count']==3
    assert len(domain.candidates)<=domain.candidate_count_upper_bound==2+2*domain.join_count
    a,z=scheduler.execute(base.plan),scheduler.execute(bound.plan)
    assert a.success and z.success and a.final_rows==z.final_rows==EXPECTED
    assert a.total_remote_calls==z.total_remote_calls==len(s)
    targets=bound.plan.metadata['anchor_reduction']['target_matches']
    rows_a={n.node_id:n.row_count for n in a.node_results};rows_z={n.node_id:n.row_count for n in z.node_results}
    assert all(rows_a[t+'/native']==8 and rows_z[t+'/native']==4 for t in targets)
    assert z.total_bytes_moved<a.total_bytes_moved
    assert len(calls)==2*len(s) and sum('VALUES ?source' in text for _,text in calls)==3
    print(json.dumps({'gate':'tiny-anchor-source-bind','answer_rows':len(EXPECTED),
        'coordinator_logical_exchange_bytes':a.total_bytes_moved,'bound_logical_exchange_bytes':z.total_bytes_moved,
        'source_calls_each':len(s),'three_first_hop_rows_before':24,'three_first_hop_rows_after':12,
        'actual_HTTP_measured':False}))


@pytest.mark.parametrize('boundary',['empty','count','bytes'])
def test_empty_or_excessive_key_relations_never_retry_truncate_or_fallback(boundary):
    p,s,b,graphs,_,scheduler,calls=tiny()
    if boundary=='empty':
        raw=p.to_dict();f=next(o for o in raw['operators'] if o['kind']=='filter' and o['parameters']['condition'].get('value')==20)
        f['parameters']['condition']['value']=999;p=SemanticGraphProgram.from_dict(raw)
    elif boundary=='count':
        graphs['rdf_b'].parse(data=PREFIX+'t:b a t:Person; t:age 20.',format='turtle')
    domain=space(p,s,b,max_bindings=1 if boundary=='count' else 100,
                 max_binding_bytes=1 if boundary=='bytes' else 1048576)
    result=scheduler.execute(fanout(domain).plan)
    assert len(calls)==len(s)-3  # Only nonbound source reads reached the transport.
    assert not any('VALUES ?source' in text for _,text in calls)
    if boundary=='empty':
        assert result.success and result.final_rows==()
    else:
        assert not result.success
        assert any(n.error for n in result.node_results if n.kind is R.REMOTE_BIND_QUERY)


def test_a_single_unavailable_target_does_not_publish_a_partial_fanout(monkeypatch):
    import xgap.runtime.physical_strategies as module
    p,s,b,_,_,_,calls=tiny();original=module._bound_match_artifact
    first=next(o.operator_id for o in p.operators if o.kind.value=='match' and 'edge' in o.parameters)
    def reject_one(artifact,*args,**kwargs):
        if artifact.artifact_id==first+'-match':raise module._NotAdmitted('declared test-only unsupported target')
        return original(artifact,*args,**kwargs)
    monkeypatch.setattr(module,'_bound_match_artifact',reject_one)
    domain=space(p,s,b)
    assert not any(c.strategy_id=='anchor_fanout_bind' for c in domain.candidates)
    assert any(r['strategy_id']=='anchor_fanout_bind' for r in domain.rejected_strategies)
    assert domain.candidates[0].strategy_id=='coordinator' and not calls


def test_actual_frozen_model_supports_the_new_domain_without_weights_or_input_changes():
    # The analytic estimator previously missed an actual deployment support gap.
    # Read the existing tiny frozen profile only; never start native clients.
    path=Path('/Users/anthonyche/xgap-data/compact-anchor-native-20260913-v1/session/contribution-v2/profile.json')
    profile=FrozenOneShotProfile.load(path,expected_sha256='d8b2dc69978be2ebf66bb9b65a86a381ef17efd02352cff4b79b4784c4bd57b2')
    doc,model,_,sources,backends,_,modes=profile.materialize()
    q=json.loads(Path('tests/fixtures/compact_anchor_v1.json').read_text())['cases'][0]['gold_compact']
    p,_=lower_compact_query(q,doc['source_schema'],version='v2');before=deepcopy(p.to_dict())
    slots,_=source_assignments(p,doc['source_schema'],sources)
    candidates,domain=prepare_one_shot_domain(p,operator_sources=slots,sources=sources,backends=backends,policy=modes['performance'][0])
    assert domain['construction_bound']==18 and domain['anchor_candidate_upper_bound_per_placement']==1
    assert len(candidates)==9 and p.to_dict()==before
    selected=next(c for c in candidates if c.strategy_id.endswith('/anchor_fanout_bind'))
    prediction=model.predict(selected.plan)
    assert prediction.estimated_ms is not None,prediction.to_dict()
    assert prediction.provenance['fit_calls']==0
    estimates=[(model.predict(c.plan).estimated_ms,c.strategy_id) for c in candidates]
    print(json.dumps({'gate':'real-frozen-model-offline','minimum_estimated_strategy':min(estimates)[1],
        'new_candidate_estimate':prediction.estimated_ms,'candidate_count':len(candidates),'bound':domain['construction_bound']}))
