"""Request-local dependency reuse, immutable file exposure and replay authority."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from test_practical_profile import FIXTURE, REPLAY, arguments, no_network, published, sha
from xgap.catalog.bundle import FrozenResolutionBundle
from xgap.experiments.one_shot_records import BackendReplay, write_once
from xgap.experiments.practical_profile import FrozenPracticalProfile
from xgap.experiments.practical_records import run_record


def saved_clients():
    records=[json.loads(f.read_text()) for f in sorted(REPLAY.glob('backend-*-result.json'))]
    return {b:BackendReplay(b,[r for r in records if r['backend_id']==b]) for b in ('neo4j','fuseki')}


def test_ordinary_record_admits_bundle_once_and_preserves_full_replay_outcome(tmp_path,monkeypatch):
    _,pin=published(tmp_path);loads=[];original=FrozenResolutionBundle.load
    def counted(*args,**kwargs):loads.append(str(args[0]));return original(*args,**kwargs)
    monkeypatch.setattr(FrozenResolutionBundle,'load',counted)
    receipt=run_record(**arguments(pin,tmp_path/'record'),operation='replay',
        replay_path=REPLAY/'replay-v2.json',replay_sha256=sha(REPLAY/'replay-v2.json'))
    assert receipt['success'] and receipt['replay_match'] and len(loads)==1,receipt
    assert receipt['source_network_calls']==receipt['model_network_calls']==0
    assert receipt['source_invocations']==2 and receipt['acquisition_invocations']==1
    result=json.loads((tmp_path/'record/result.json').read_text())
    assert result['profile_preparation_ms']==receipt['admission_ms']>0
    assert result['request_total_ms']>=receipt['admission_ms']+result['end_to_end_ms']


def prepared(tmp_path):
    original,pin=published(tmp_path)
    doc=json.loads(original.document_json);intake=tmp_path/'intake.json'
    intake.write_bytes(Path(doc['intake']['path']).read_bytes());doc['intake']['path']=str(intake)
    path=tmp_path/'relocated.json';write_once(path,doc)
    profile,cfg=FrozenPracticalProfile.load_materialized(path,expected_sha256=sha(path))
    raw=json.loads((FIXTURE/'request.json').read_text());raw['predictions']={'predicate':'predicate:knows'}
    raw['clarifications']['predicate-clarification']['path']=str(FIXTURE/'clarification.json')
    request=tmp_path/'request.json';write_once(request,raw)
    q=profile.prepare(raw,request_sha256=sha(request),request_root=tmp_path,mode='performance',materialized=cfg)
    return profile,q,intake,path


def test_late_file_change_cannot_rewrite_admitted_request_but_next_admission_rejects(tmp_path):
    profile,q,intake,path=prepared(tmp_path)
    intake.write_text('{"operators": []}')
    clients=saved_clients();result=profile.run_prepared(q,backend_clients=clients)
    assert result['success'] and result['answer_rows']==[{'edge':'https://xgap.test/toy/e4','person':'https://xgap.test/toy/c'}]
    assert result['model_calls']==result['clarification_calls']==0 and sum(c.position for c in clients.values())==2
    # No stale cache is consulted by the next record/admission.
    with pytest.raises(ValueError,match='hash|SHA'):
        FrozenPracticalProfile.load_materialized(path,expected_sha256=sha(path))


@pytest.mark.parametrize('mismatch',('profile','configuration','bundle'))
def test_mismatched_snapshot_fails_before_source_or_model_call(tmp_path,mismatch):
    profile,q,_,_=prepared(tmp_path);clients=saved_clients()
    if mismatch=='profile':profile=replace(profile,sha256='0'*64)
    elif mismatch=='configuration':
        doc=json.loads(profile.document_json);doc['profile_id']='different'
        q=replace(q,configuration=(doc,*q.configuration[1:]))
    else:
        q=replace(q,options=replace(q.options,resolution_bundle=replace(q.options.resolution_bundle,bundle_hash='0'*64)))
    if mismatch=='bundle':
        result=profile.run_prepared(q,backend_clients=clients)
        assert not result['success'] and result['status']=='catalog_unavailable'
    else:
        with pytest.raises(ValueError,match='profile|configuration'):profile.run_prepared(q,backend_clients=clients)
    assert all(c.position==0 for c in clients.values())
