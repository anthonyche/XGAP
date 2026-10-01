"""New per-question dispatch glue; no model, backend service or new scores."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_practical_profile import FIXTURE,no_network,sha
from xgap.experiments import practical_study as study
from xgap.experiments.one_shot_records import write_once


def prepared(tmp_path,duplicate=False):
    groups=[];profile={'path':str(FIXTURE/'profile.json'),'sha256':sha(FIXTURE/'profile.json')}
    for i in range(2):
        raw=json.loads((FIXTURE/'request.json').read_text());raw['question_id']='same' if duplicate else f'group-{i}'
        raw['clarifications']['predicate-clarification']['path']=str(FIXTURE/'clarification.json')
        pin=write_once(tmp_path/f'request-{i}.json',raw)
        groups.append({'request':pin,'profile':profile,'reference':{'path':str(tmp_path/f'reference-{i}.json'),'sha256':'0'*64}})
    source=write_once(tmp_path/'input.json',{'schema_version':study.SCHEMA,'study_id':'tiny-handoff','groups':groups})
    return study.freeze_study(input_path=source['path'],input_sha256=source['sha256'],output=tmp_path/'frozen')


def invoke(pin,tmp_path,monkeypatch,*,fail=False,mutate=None):
    calls=[];scores=[];deployments=[];observer=SimpleNamespace(base_url='http://127.0.0.1:9981')
    def deploy(cell):
        assert 'reference_for_post_seal_scoring_only' not in cell
        raw=json.loads(Path(cell['practical_profile']['path']).read_text())
        for spec in raw['backends'].values():spec['client']['url']=observer.base_url
        if mutate=='config':raw['modes']['exact']['search']['planning_ms']+=1
        if mutate=='unobserved':next(iter(raw['backends'].values()))['client']['url']='http://127.0.0.1:9982'
        dest=tmp_path/f'deployment-{len(list(tmp_path.glob("deployment-*.json"))):03}.json'
        deployments.append(cell['cell_id']);return write_once(dest,raw)
    def trial(**kwargs):
        assert 'reference_path' not in kwargs and 'gold' not in kwargs
        q=json.loads(Path(kwargs['request_path']).read_text());calls.append((q['question_id'],kwargs['method']))
        output=Path(kwargs['output']);output.mkdir(parents=True)
        result={'schema_version':'xgap-common-method-trial-v1','method':kwargs['method'],'question_id':q['question_id'],
            'track':'trusted_template','success':not fail,'status':'controlled-failed' if fail else 'controlled-success',
            'can_continue_session':not fail,'paper_result':False}
        return {**result,'receipt':write_once(output/'receipt.json',result),'timing':{'total_online_ms':1}}
    def score(receipt_path,**kwargs):
        assert Path(receipt_path).exists() and Path(kwargs['output']).parent.joinpath('study-timing.json').exists()
        scores.append(receipt_path)
        # Unreadable reference deliberately persists. The existing scorer's
        # error record must not change a successful method or cause its retry.
        raise ValueError('Controlled unavailable post-seal reference')
    monkeypatch.setattr(study,'run_practical_trial',trial);monkeypatch.setattr(study,'score_trial',score)
    rows=study.dispatch_practical_group(schedule_path=pin['path'],schedule_sha256=pin['sha256'],ledger=tmp_path/'ledger',
        owned_services=[],observer=observer,deployment_for=deploy,
        ready=lambda cell:{'ready':'reference_for_post_seal_scoring_only' not in cell})
    return rows,calls,scores,deployments


def test_freeze_preserves_explicit_population_and_method_profile_mapping_without_reading_answers(tmp_path):
    pin=prepared(tmp_path);schedule=json.loads(Path(pin['path']).read_text())
    assert len(schedule['cells'])==4 and schedule['groups']==2 and schedule['maximum_top_level_method_attempts']==4
    assert [c['method'] for c in schedule['cells']]==[*study.METHODS,*reversed(study.METHODS)]
    assert len(list((tmp_path/'frozen').glob('profile-*.json')))==1
    assert not schedule['reference_answers_read'] and not schedule['formal_campaign_ready']
    assert all(c['practical_profile']==schedule['cells'][0]['practical_profile'] for c in schedule['cells'])
    assert not list(tmp_path.glob('reference-*.json'))
    from xgap.experiments.campaign_schedule import METHODS
    assert 'trusted_template' not in METHODS


def test_dispatch_one_group_then_resume_never_reexecutes_and_scores_only_after_seal(tmp_path,monkeypatch):
    pin=prepared(tmp_path)
    _,calls,scores,_=invoke(pin,tmp_path,monkeypatch)
    assert calls==[('group-0',method) for method in study.METHODS] and len(scores)==2
    # Preserve an indeterminate second-group intent; never redispatch it.
    schedule=json.loads(Path(pin['path']).read_text());cell=schedule['cells'][2]
    (tmp_path/'ledger'/cell['cell_id']).mkdir();(tmp_path/'ledger'/cell['cell_id']/'intent.json').write_text('{}')
    rows,calls,scores,_=invoke(pin,tmp_path,monkeypatch)
    assert calls==[('group-1',study.METHODS[0])] and len(scores)==1
    assert any(r['status']=='indeterminate_prior_intent' for r in rows)
    rows,calls,scores,deployed=invoke(pin,tmp_path,monkeypatch)
    assert not calls and not scores and not deployed
    assert len(list((tmp_path/'ledger').glob('*/execution/score-error.json')))==3


def test_failed_method_stops_remaining_cell_until_new_dispatch_without_repeating_failure(tmp_path,monkeypatch):
    pin=prepared(tmp_path)
    rows,calls,_,_=invoke(pin,tmp_path,monkeypatch,fail=True)
    assert calls==[('group-0',study.METHODS[0])]
    assert rows[-1]['status']=='unrun_prerequisite'
    rows,calls,_,_=invoke(pin,tmp_path,monkeypatch)
    assert calls==[('group-0',study.METHODS[1])]


@pytest.mark.parametrize('mutate',('config','unobserved'))
def test_deployment_may_only_change_endpoint_and_must_use_owned_observer(tmp_path,monkeypatch,mutate):
    pin=prepared(tmp_path)
    with pytest.raises(ValueError,match='frozen practical inputs|owned observation boundary'):
        invoke(pin,tmp_path,monkeypatch,mutate=mutate)
    assert not list((tmp_path/'ledger').glob('trusted-template-*'))


def test_duplicate_question_groups_rejected_before_dispatch(tmp_path):
    with pytest.raises(ValueError,match='distinct IDs'):prepared(tmp_path,duplicate=True)
