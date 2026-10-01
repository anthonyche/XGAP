"""New published-profile admission/authority/replay risks; no network or fit."""
import hashlib
import json
from pathlib import Path
import socket

import pytest

from xgap.experiments.one_shot_records import BackendReplay, write_once
from xgap.experiments.practical_profile import FrozenPracticalProfile
from xgap.experiments.practical_records import publish_profile, run_record


ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'datasets/practical_model_profile_v1'
REPLAY=Path(__file__).parent/'fixtures/practical_profile_replay'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket,'connect',lambda *a,**k:pytest.fail('Unexpected network access'))


def published(tmp_path):
    pin=publish_profile(profile_path=FIXTURE/'profile.json',profile_sha256=sha(FIXTURE/'profile.json'),
        output=tmp_path/'profile.json')
    return FrozenPracticalProfile.load(pin['path'],expected_sha256=pin['sha256']),pin


def arguments(profile_pin,output,mode='performance'):
    return dict(profile_path=profile_pin['path'],profile_sha256=profile_pin['sha256'],
        request_path=FIXTURE/'request.json',request_sha256=sha(FIXTURE/'request.json'),mode=mode,output=output)


def test_publish_relocates_dependencies_keeps_weights_and_allows_exact_native_replay(tmp_path):
    before=(FIXTURE/'estimator.json').read_bytes()
    p,pin=published(tmp_path)
    cfg=p.materialize();doc,_,_,model,_,_,_,modes=cfg
    assert (FIXTURE/'estimator.json').read_bytes()==before
    assert model.to_dict()['deployment_provenance']['weights_changed'] is False
    assert modes['performance'][1].max_states < modes['exact'][1].max_states
    assert modes['performance'][1].planning_ms < modes['exact'][1].planning_ms
    assert doc['catalog']['bundle_hash']==json.loads((FIXTURE/'profile.json').read_text())['catalog']['bundle_hash']
    result=run_record(**arguments(pin,tmp_path/'replay'),operation='replay',
        replay_path=REPLAY/'replay-v2.json',replay_sha256=sha(REPLAY/'replay-v2.json'))
    assert result['success'] and result['replay_match'],result
    assert result['model_network_calls']==result['source_network_calls']==0
    assert result['acquisition_invocations']==1 and result['source_invocations']==2
    core=json.loads((tmp_path/'replay/result.json').read_text())
    assert core['model_calls']==core['tokens']==0 and core['estimator_sha256']==model.model_sha256
    obs=next(o for o in core['execution_state']['observations'] if o['source']=='practical.llm:predicate')
    assert obs['payload']['metadata']['historical_metrics']['tokens']==372
    with pytest.raises(FileExistsError):publish_profile(profile_path=FIXTURE/'profile.json',
        profile_sha256=sha(FIXTURE/'profile.json'),output=pin['path'])


@pytest.mark.parametrize('mode,clarifications',[('exact',1),('performance',0)])
def test_same_predicted_input_keeps_exact_authority_requirement_and_performance_fast_path(tmp_path,mode,clarifications):
    p,_=published(tmp_path)
    q=json.loads((FIXTURE/'request.json').read_text());q['predictions']={'predicate':'predicate:knows'}
    q['clarifications']['predicate-clarification']['path']=str(FIXTURE/'clarification.json')
    path=tmp_path/'request.json';write_once(path,q)
    records=[json.loads(f.read_text()) for f in sorted(REPLAY.glob('backend-*-result.json'))]
    clients={b:BackendReplay(b,[r for r in records if r['backend_id']==b]) for b in ('neo4j','fuseki')}
    result=p.run(request_path=path,request_sha256=sha(path),mode=mode,backend_clients=clients)
    assert result['success'],result
    assert result['clarification_calls']==clarifications and result['model_calls']==0
    assert result['final_plan_executions']==1 and sum(c.position for c in clients.values())==2
    assert result['execution']['unvalidated_bindings']==([] if mode=='exact' else ['predicate'])
    assert all(result['execution']['bindings'][s]['authoritative'] for s in ('person','age','source','type'))


@pytest.mark.parametrize('change',('snapshot','epsilon','inline_credential','unconsumed_physical_knob'))
def test_profile_drift_and_unsupported_semantics_stop_before_external_action(tmp_path,change):
    p,_=published(tmp_path);doc=json.loads(p.document_json)
    if change=='snapshot':doc['sources']['toy']['version']='stale'
    elif change=='epsilon':doc['modes']['performance']['semantic']['epsilon']=.1
    elif change=='inline_credential':doc['acquisitions']['predicate-model']['provider']['base_url']='http://user:password@localhost/v1'
    else:doc['modes']['performance']['physical']['retrieval_rows_per_relation']=1
    path=tmp_path/'bad.json';write_once(path,doc)
    r=run_record(**arguments({'path':str(path),'sha256':sha(path)},tmp_path/'rejected'),operation='execute')
    assert not r['success'] and r['failure_phase']=='admission'
    assert r['model_network_calls']==r['source_network_calls']==0 and not (tmp_path/'rejected/intent.json').exists()


def test_clarification_pin_is_not_read_during_preflight_and_mismatch_never_executes(tmp_path,monkeypatch):
    p,pin=published(tmp_path)
    q=json.loads((FIXTURE/'request.json').read_text());response=tmp_path/'response.json'
    q['clarifications']['predicate-clarification']={'path':str(response),'sha256':'0'*64}
    path=tmp_path/'request.json';write_once(path,q)
    r=run_record(**{**arguments(pin,tmp_path/'preflight','exact'),'request_path':path,'request_sha256':sha(path)})
    assert r['success'] and not response.exists()
    response.write_bytes((FIXTURE/'clarification.json').read_bytes())
    # Calling the returned policy reveals the hash error. No unmodeled recovery
    # may execute, even though a valid source response is available in replay.
    records=[json.loads(f.read_text()) for f in sorted(REPLAY.glob('backend-*-result.json'))]
    clients={b:BackendReplay(b,[r for r in records if r['backend_id']==b]) for b in ('neo4j','fuseki')}
    result=p.run(request_path=path,request_sha256=sha(path),mode='exact',backend_clients=clients)
    assert not result['success'] and result['final_plan_executions']==0
    assert result['model_calls']==0 and all(c.position==0 for c in clients.values())


@pytest.mark.parametrize('change',('override_validated','unauthorized_prediction','request_hash'))
def test_bad_request_cannot_change_trusted_semantics_or_claim_a_different_pin(tmp_path,change):
    p,_=published(tmp_path);q=json.loads((FIXTURE/'request.json').read_text())
    if change=='override_validated':q['predictions']['person']='entity:bob'
    elif change=='unauthorized_prediction':q['trusted_bindings'].pop('age');q['predictions']['age']='constraint:45'
    path=tmp_path/'bad-request.json';write_once(path,q)
    with pytest.raises(ValueError):p.run(request_path=path,request_sha256='0'*64 if change=='request_hash' else sha(path),
        mode='performance',execute=False)


def test_changed_acquisition_domain_cannot_consume_another_requests_observation(tmp_path):
    p,pin=published(tmp_path);doc=json.loads(p.document_json)
    doc['acquisitions']['predicate-model']['candidate_ids'].reverse()
    path=tmp_path/'changed-domain.json';write_once(path,doc)
    r=run_record(**arguments({'path':str(path),'sha256':sha(path)},tmp_path/'rejected'),operation='replay',
        replay_path=REPLAY/'replay-v2.json',replay_sha256=sha(REPLAY/'replay-v2.json'))
    assert not r['success'] and not r.get('replay_match',False)
    assert r['model_network_calls']==r['source_network_calls']==0


def failed_clients(returned):
    from xgap.infrastructure.runtime import ExecutionReport
    class Client:
        def __init__(self,name):self.backend_id=name
        def execute(self,artifact):
            if not returned:raise OSError('controlled indeterminate source call')
            return ExecutionReport(backend_id=self.backend_id,artifact_id=artifact.artifact_id,
                language=artifact.language,success=False,elapsed_ms=1.0,error='controlled original source failure')
    return {b:Client(b) for b in ('neo4j','fuseki')}


def test_indeterminate_source_capture_is_preserved_and_refused_as_complete_replay(tmp_path,monkeypatch):
    p,pin=published(tmp_path)
    import xgap.experiments.practical_records as records
    monkeypatch.setattr(records,'native_clients',lambda specs:failed_clients(False))
    result=run_record(**arguments(pin,tmp_path/'failure','exact'),operation='execute')
    assert not result['success'] and result['final_plan_executions']==1
    replay=json.loads(Path(result['replay']['path']).read_text())
    assert replay['captures_complete'] is False
    again=run_record(**arguments(pin,tmp_path/'replay','exact'),operation='replay',
        replay_path=result['replay']['path'],replay_sha256=result['replay']['sha256'])
    assert not again['success'] and again['failure_phase']=='admission'
    assert 'Incomplete capture' in again['error'] and not (tmp_path/'replay/intent.json').exists()


def test_recorded_failure_replays_its_actual_reason_not_merely_any_failure(tmp_path,monkeypatch):
    p,pin=published(tmp_path)
    import xgap.experiments.practical_records as records
    monkeypatch.setattr(records,'native_clients',lambda specs:failed_clients(True))
    original=run_record(**arguments(pin,tmp_path/'failure','exact'),operation='execute')
    assert not original['success']
    replay_path=Path(original['replay']['path'])
    replay=json.loads(replay_path.read_text());assert replay['captures_complete'] is True
    match=run_record(**arguments(pin,tmp_path/'replay','exact'),operation='replay',
        replay_path=replay_path,replay_sha256=sha(replay_path))
    assert match['success'] and match['replay_match'] and match['original_execution_success'] is False,match
    assert json.loads((tmp_path/'replay/result.json').read_text())['success'] is False
    old=replay['backends'][0];changed=json.loads(Path(old['path']).read_text())
    changed['execution']['error']='a different failure must not count as reproduced'
    change=tmp_path/'different-source.json';write_once(change,changed)
    replay['backends'][0]={'path':str(change),'sha256':sha(change)}
    changed_manifest=tmp_path/'different-replay.json';write_once(changed_manifest,replay)
    mismatch=run_record(**arguments(pin,tmp_path/'mismatch','exact'),operation='replay',
        replay_path=changed_manifest,replay_sha256=sha(changed_manifest))
    assert not mismatch['success'] and mismatch['original_execution_success'] is False
    assert mismatch['model_network_calls']==mismatch['source_network_calls']==0
