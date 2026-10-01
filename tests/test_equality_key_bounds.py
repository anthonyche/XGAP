"""Only new frozen-bound risks: complete source stats, propagation, one-shot ranking."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest
from rdflib import Literal

from test_anchor_reduction import tiny, EXPECTED, PREFIX
from test_anchor_source_bind import fanout, space
from xgap.experiments.equality_key_bounds import freeze_equality_key_bounds, derive_equality_profile
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.planning.equality_key_bounds import FrozenEqualityKeyBounds
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.runtime.one_shot_planning import prepare_one_shot_domain
from xgap.runtime.semantic_planning import LogicalSource
from xgap.semantic.program import SemanticGraphProgram


def freeze(root, rows, *, source='toy', properties=None, namespace='https://example.org/toy/'):
    root.mkdir(); path=root/'records.jsonl'
    payload=b''.join((json.dumps(r)+'\n').encode() for r in rows);path.write_bytes(payload)
    pin=freeze_equality_key_bounds(records_path=path,records_sha256=hashlib.sha256(payload).hexdigest(),
        source_id=source,snapshot_version='tiny-v1',resource_namespace=namespace,
        expected_records=len(rows),properties=properties or {'Person':['age','absent']},output=root/'stats.json')
    stats=FrozenEqualityKeyBounds.from_bytes(Path(pin['path']).read_bytes(),expected_sha256=pin['sha256'],
                                           source_id=source,snapshot_version='tiny-v1')
    return pin,stats


def record(value):return {'label':'Person','properties':{'age':value}}


def test_complete_maximum_counts_duplicates_and_typed_strings_without_type_coercion(tmp_path):
    rows=[record('20'),record('20'),record({'type':'literal','value':'20'}),record(20),record(True),record(None)]
    pin,stats=freeze(tmp_path/'source',rows,properties={'Person':['age','absent'],'Empty':['id']})
    assert stats.bound('Person','age')==3 and stats.bound('Person','absent')==0 and stats.bound('Empty','id')==0
    assert stats.bound('Unknown','id') is None
    doc=json.loads(Path(pin['path']).read_text())
    assert doc['offline']['query_reads']==doc['offline']['answer_reads']==doc['offline']['backend_calls']==0


@pytest.mark.parametrize('corruption',['hash','snapshot','incomplete','export_count'])
def test_invalid_provenance_never_yields_a_small_bound(tmp_path,corruption):
    pin,_=freeze(tmp_path/'source',[record('20')]);data=Path(pin['path']).read_bytes()
    if corruption=='export_count':
        with pytest.raises(ValueError,match='hash/count'):
            freeze_equality_key_bounds(records_path=tmp_path/'source/records.jsonl',records_sha256='0'*64,
                source_id='toy',snapshot_version='tiny-v1',resource_namespace='urn:test:',expected_records=2,
                properties={'Person':['age']},output=tmp_path/'bad.json')
        assert not (tmp_path/'bad.json').exists();return
    if corruption=='incomplete':
        doc=json.loads(data);doc['coverage']['complete_node_records']=False;data=json.dumps(doc).encode()
    with pytest.raises(ValueError):
        FrozenEqualityKeyBounds.from_bytes(data,expected_sha256='0'*64 if corruption=='hash' else hashlib.sha256(data).hexdigest(),
            source_id='toy',snapshot_version='other' if corruption=='snapshot' else 'tiny-v1')


def string_tiny(tmp_path):
    p,placement,backends,graphs,_,scheduler,calls=tiny()
    raw=p.to_dict()
    for op in raw['operators']:
        if op['kind']=='filter' and op['parameters']['condition'].get('value')==20:
            op['parameters']['condition']['value']='20'
    bounds={}
    for name,graph in graphs.items():
        rows=[]
        for s,pred,value in list(graph.triples((None,None,Literal(10))))+list(graph.triples((None,None,Literal(20)))):
            graph.remove((s,pred,value));graph.add((s,pred,Literal(str(value))))
            rows.append(record(str(value)))
        _,stat=freeze(tmp_path/name,rows,source=name,namespace=backends[name].resource_namespace)
        bounds[name]=stat
    p=SemanticGraphProgram.from_dict(raw)
    by_op={op:bounds[b] for op,b in placement.items()}
    return p,placement,backends,scheduler,calls,by_op


def test_provider_sum_tightens_actual_adapter_limit_and_preserves_independent_answers(tmp_path):
    p,s,b,scheduler,calls,stats=string_tiny(tmp_path)
    candidate=fanout(space(p,s,b,operator_equality_bounds=stats))
    details=candidate.plan.metadata['strategy_details']
    assert details['max_bindings']==6 and details['frozen_key_bound']['distinct_keys_upper_bound']==6
    assert len(details['frozen_key_bound']['leaves'])==2
    bound_nodes=[n for n in candidate.plan.nodes if n.kind is R.REMOTE_BIND_QUERY]
    assert all(n.parameters['max_bindings']==6 and n.parameters['artifact']['parameters']['sparql_iri_binding']['max_bindings']==6
               for n in bound_nodes)
    result=scheduler.execute(candidate.plan)
    assert result.success and result.final_rows==EXPECTED and len(calls)==len(s)
    # Metadata is not allowed to raise a smaller caller cap.
    assert fanout(space(p,s,b,max_bindings=2,operator_equality_bounds=stats)).plan.metadata['strategy_details']['max_bindings']==2


def test_incomplete_coverage_and_nonstring_anchors_retain_original_limit(tmp_path):
    p,s,b,_,calls,stats=string_tiny(tmp_path)
    absent={op:st for op,st in stats.items() if st.source_id=='rdf_a'}
    assert fanout(space(p,s,b,operator_equality_bounds=absent)).plan.metadata['strategy_details']['max_bindings']==10000
    omitted={op:replace(st,entries=()) for op,st in stats.items()}
    assert fanout(space(p,s,b,operator_equality_bounds=omitted)).plan.metadata['strategy_details']['max_bindings']==10000
    numeric,_,_,_,_,_,_=tiny()
    assert fanout(space(numeric,s,b,operator_equality_bounds=stats)).plan.metadata['strategy_details']['max_bindings']==10000
    assert not calls


def test_statistics_snapshot_and_identity_mismatches_are_rejected(tmp_path):
    _,stats=freeze(tmp_path/'source',[record('20')])
    with pytest.raises(ValueError,match='snapshot'):
        LogicalSource('toy','different',('rdf_a',),stats)
    p,s,b,_,_,_=string_tiny(tmp_path)
    with pytest.raises(ValueError,match='namespace'):
        space(p,s,b,operator_equality_bounds={op:replace(stats,resource_namespace='urn:wrong:') for op in s})


def test_zero_string_coverage_keeps_positive_limit_and_skips_empty_bound_transports(tmp_path):
    p,s,b,_,_,scheduler,calls=tiny()  # All actual age values are numeric.
    raw=p.to_dict()
    next(o for o in raw['operators'] if o['kind']=='filter' and o['parameters']['condition'].get('value')==20
         )['parameters']['condition']['value']='20'
    p=SemanticGraphProgram.from_dict(raw)
    stats={}
    for name in b:
        _,st=freeze(tmp_path/name,[record(10)]*5 if name=='rdf_a' else [record(20)],
                    source=name,namespace=b[name].resource_namespace)
        stats[name]=st
    selected=fanout(space(p,s,b,operator_equality_bounds={op:stats[name] for op,name in s.items()}))
    details=selected.plan.metadata['strategy_details']
    assert details['frozen_key_bound']['distinct_keys_upper_bound']==0 and details['max_bindings']==1
    result=scheduler.execute(selected.plan)
    assert result.success and result.final_rows==() and len(calls)==len(s)-3


def test_actual_frozen_model_reads_published_bounds_and_preserves_parent(tmp_path):
    from prepare_tiny_equality_bounds import prepare
    from xgap.experiments.schema_source_routing import source_assignments
    from xgap.semantic.compact_lowering import lower_compact_query
    path=Path('/Users/anthonyche/xgap-data/compact-anchor-native-20260913-v1/session/contribution-v2/profile.json')
    pin='d8b2dc69978be2ebf66bb9b65a86a381ef17efd02352cff4b79b4784c4bd57b2'
    receipt=prepare(parent_path=path,parent_sha256=pin,output=tmp_path/'published')
    prepared=json.loads(Path(receipt['path']).read_text());child=prepared['profile']
    profile=FrozenOneShotProfile.load(child['path'],expected_sha256=child['sha256'])
    doc,model,_,sources,backends,_,modes=profile.materialize()
    old=FrozenOneShotProfile.load(path,expected_sha256=pin).materialize()
    assert doc['estimator']==old[0]['estimator'] and all(s.equality_key_bounds is None for s in old[3].values())
    query=json.loads(Path('tests/fixtures/compact_anchor_v1.json').read_text())['cases'][0]['gold_compact']
    program,_=lower_compact_query(query,doc['source_schema'],version='v2')
    slots,_=source_assignments(program,doc['source_schema'],sources)
    candidates,domain=prepare_one_shot_domain(program,operator_sources=slots,sources=sources,backends=backends,policy=modes['performance'][0])
    assert domain['construction_bound']==18 and len(candidates)==9
    bound=next(c for c in candidates if c.strategy_id.endswith('/anchor_fanout_bind'))
    assert bound.plan.metadata['strategy_details']['max_bindings']==2
    estimates=[(model.predict(c.plan).estimated_ms,c.strategy_id) for c in candidates]
    assert all(ms is not None for ms,_ in estimates)
    assert model.predict(bound.plan).provenance['fit_calls']==0
    print(json.dumps({'gate':'frozen-equality-bound-actual-model','new_bound':2,'predictions':estimates,
                      'estimated_winner':min(estimates)[1],'bound':domain['construction_bound']}))
    # Bad dependent hash fails profile validation before native clients/interpretation.
    corrupted=json.loads(profile.document_json);corrupted['sources']['graph']['equality_key_bounds']['sha256']='0'*64
    with pytest.raises(ValueError,match='hash'):
        FrozenOneShotProfile(profile.root,'unpublished',json.dumps(corrupted)).materialize()
