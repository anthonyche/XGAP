"""Serving publication risks only; reuse accepted tiny files, no live gates."""
import hashlib
import json
from pathlib import Path
import shutil
import socket

import pytest

from xgap.agent.one_shot_grounding import ground_interpretation
from xgap.experiments.financial_nl_profile import INPUT_ROOT, MANIFEST_HASH
from xgap.experiments.finbench_serving_profile import publish_serving_profile, verify_asset
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.runtime.one_shot_planning import prepare_one_shot_domain
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.program import SemanticHoleKind
from xgap.tools.resolution import ResolutionCandidateRequest
from test_compact_lowering import financial_intents


MODEL = Path('/Users/anthonyche/xgap-data/edge-bind-training-native-20260912-v1/frozen_work_estimator.json')
MODEL_HASH = '80c3dc09856d1379b1bc28c63de19f23f42a2931b101926b83d334cc21322873'


def lookup_request(kind, mention):
    return ResolutionCandidateRequest(program_id='serving-test', hole_id='lookup',
        hole_kind=kind, mention=mention, max_candidates=64, candidate_ids=(),
        question='Serving contract check', hard_constraints_sha256='0'*64)


def publish(root, **overrides):
    args = dict(rdf_root=INPUT_ROOT, manifest_sha256=MANIFEST_HASH,
        model_path=MODEL, model_sha256=MODEL_HASH, output=root, dataset_id='serving-test',
        endpoints={'neo4j':'http://localhost:1','fuseki':'http://localhost:2'})
    args.update(overrides)
    return publish_serving_profile(**args)


@pytest.fixture(scope='module')
def published(tmp_path_factory):
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(socket.socket, 'connect', lambda *a,**kw:pytest.fail('Network in offline publication'))
        from xgap.planning import runtime_work_estimator
        monkeypatch.setattr(runtime_work_estimator, 'fit_work_estimator', lambda *a,**kw:pytest.fail('Unexpected training'))
        original = Path.open
        def guarded(path,*a,**kw):
            if any(v in path.parts for v in ('references','gold','requests')) or path.name in ('reference.json','result.json'):
                pytest.fail('Serving publication read query/gold/result')
            return original(path,*a,**kw)
        monkeypatch.setattr(Path, 'open', guarded)
        pin = publish(tmp_path_factory.mktemp('serving')/'profile')
        return FrozenOneShotProfile.load(pin['path'], expected_sha256=pin['sha256'])


def test_complete_source_catalog_keeps_ids_names_control_categories_and_ambiguity(published):
    doc, _, bundle, _, _, _, modes = published.materialize()
    assert set(modes)=={'precision','performance'}
    summary=json.loads((published.root/'source_summary.json').read_text())
    assert summary['entity_count']==8 and summary['relationship_count']==16
    assert summary['catalog_kind_counts']['entity']==8
    assert 'isBlocked' not in doc['source_schema']['graph']['nodes']['XGAPFinBenchAccount']['properties']
    for mention,expected in [('person 1',{'entity:person_31'}),('Alice',{'entity:person_31'}),
                             ('1',{'entity:person_31','entity:company_31','entity:account_31','entity:medium_31'})]:
        q=lookup_request(SemanticHoleKind.ENTITY,mention)
        r=bundle.catalog.resolve(q,None)
        assert set(r.candidate_ids)==expected and not r.authoritative
    q=lookup_request(SemanticHoleKind.CONSTRAINT,'High risk')
    r=bundle.catalog.resolve(q,None)
    assert len(r.candidate_ids)==1 and bundle.bindings[r.candidate_ids[0]].value=='High risk'
    # Transfer amounts/timestamps are ordinary literals, not catalog enumeration.
    q=lookup_request(SemanticHoleKind.CONSTRAINT,'10.125')
    assert not bundle.catalog.resolve(q,None).candidate_ids


def test_new_statistics_preserve_original_model_and_reach_estimated_domain(published):
    doc, model, bundle, sources, backends, _, modes = published.materialize()
    original=json.loads(MODEL.read_text())
    assert model.to_dict()['trained_model']==original
    assert model.to_dict()['deployment_provenance']['transfer_calibrated'] is False
    assert {s.source_id:s.total_rows for s in model.statistics.entries}=={'graph':24,'control':8}
    for s in model.statistics.entries:
        assert s.snapshot_version==doc['sources'][s.source_id]['version']
        assert s.mean_row_bytes>0 and s.mean_row_bytes!=128
    program,assignments=lower_compact_query(financial_intents()[0],doc['source_schema'])
    bound,trace=ground_interpretation(program,assignments,bundle,'Find transfers from Alice.')
    candidates,domain=prepare_one_shot_domain(bound.program,operator_sources=bound.operator_sources,
        sources=sources,backends=backends,policy=modes['performance'][0])
    predictions=[model.predict(c.plan) for c in candidates]
    assert predictions and all(p.status=='estimated' for p in predictions)
    assert all(p.provenance['weights_changed'] is False for p in predictions)
    assert domain['candidate_count']<=domain['construction_bound']
    assert trace['external_calls']==0 and doc['offline']['formal_campaign_ready'] is False


def test_changed_load_fails_before_publishing_and_counts_are_not_just_trusted(tmp_path):
    source=tmp_path/'source'; shutil.copytree(INPUT_ROOT,source)
    target=tmp_path/'output'
    with (source/'control.ttl').open('a') as stream:stream.write('\n')
    with pytest.raises(ValueError,match='size/hash mismatch'):
        publish(target,rdf_root=source)
    assert not target.exists()
    shutil.copyfile(INPUT_ROOT/'control.ttl',source/'control.ttl')
    m=json.loads((source/'manifest.json').read_text());m['entity_count']+=1
    (source/'manifest.json').write_text(json.dumps(m))
    with pytest.raises(ValueError,match='counts differ'):
        publish(target,rdf_root=source,manifest_sha256=hashlib.sha256((source/'manifest.json').read_bytes()).hexdigest())
    assert not target.exists()


def test_large_load_artifact_streaming_preserves_the_small_metadata_boundary(tmp_path):
    path=tmp_path/'large.ttl'; digest=hashlib.sha256()
    with path.open('wb') as stream:
        for _ in range(17):
            block=b'x'*(1024*1024);stream.write(block);digest.update(block)
    pin={'path':path.name,'size_bytes':17*1024*1024,'sha256':digest.hexdigest()}
    verify_asset(path,pin)
    with path.open('r+b') as stream:stream.write(b'y')
    with pytest.raises(ValueError,match='size/hash mismatch'):verify_asset(path,pin)
