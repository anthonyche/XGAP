"""Real supervisor boundaries with tiny fixtures; no model or database calls."""
import json
import pytest

import run_bounded_joint_batch as batch
import run_ch6_dataset_pilot as pilot
from test_bounded_joint_batch import fixture, install_fake_runtime
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.ch6_pilot_release import TOKEN_POLICY


def test_cell_budget_stops_inside_shared_session_before_creating_next_attempt(tmp_path,monkeypatch):
    seen,sessions=install_fake_runtime(monkeypatch)
    pin=write_once(tmp_path/'manifest.json',fixture(tmp_path))
    result=batch.run(pin['path'],pin['sha256'],tmp_path/'run',before_cell=lambda c:'token_threshold' if len(seen)==1 else None)
    assert seen==['0'] and len(sessions)==1 and sessions[0].closed
    assert result['budget_status']=='token_threshold' and result['all_owned_closed']
    assert result['counts']['unattempted']==2 and not (tmp_path/'run/cells/1').exists()


def test_cell_budget_can_refuse_before_any_service_or_query_starts(tmp_path,monkeypatch):
    seen,sessions=install_fake_runtime(monkeypatch)
    pin=write_once(tmp_path/'manifest.json',fixture(tmp_path))
    result=batch.run(pin['path'],pin['sha256'],tmp_path/'run',before_cell=lambda c:'calls_exhausted')
    assert not seen and not sessions and result['new_cells']==0 and result['all_owned_closed']


def test_callback_failure_closes_existing_session_without_starting_another_cell(tmp_path,monkeypatch):
    seen,sessions=install_fake_runtime(monkeypatch)
    def stop(cell):
        if seen:raise ValueError('Cannot account for usage')
    pin=write_once(tmp_path/'manifest.json',fixture(tmp_path))
    result=batch.run(pin['path'],pin['sha256'],tmp_path/'run',before_cell=stop)
    assert seen==['0'] and sessions[0].closed and result['status']=='failed'
    assert not (tmp_path/'run/cells/1').exists()


def test_unknown_usage_is_not_zero_or_a_token_reservation():
    budget=dict(model_calls_cap=65,input_tokens_stop_threshold=100,output_tokens_stop_threshold=100)
    spent=dict(unsealed_cells=0,unknown_model_usage=False,model_calls=1,input_tokens=50,output_tokens=20)
    def stop(**changes):
        return pilot.stop_reason({**spent,**changes},budget,remaining_seconds=1000,needed_seconds=900,next_call_cap=64)
    assert stop() is None
    assert stop(input_tokens=100)=='observed_input_tokens_threshold'
    assert stop(model_calls=2)=='model_call_budget'
    assert stop(unknown_model_usage=True)=='unknown_usage_requires_accounting'
    assert stop(unsealed_cells=1)=='unsealed_cell_requires_accounting'


@pytest.mark.parametrize('tokens,unknown,expected',[(150,False,'observed_input_tokens_threshold'),(0,True,'accounting_incomplete')])
def test_pilot_checks_each_cell_and_never_retries_its_first_terminal(tmp_path,monkeypatch,tokens,unknown,expected):
    manifest=write_once(tmp_path/'manifest.json',dict(cells=[dict(cell_id=str(i),method='internal') for i in range(3)],
        design=dict(startup_seconds=2,method_wall_seconds=5,package_max_bytes=100000),external_runtime=None))
    release=dict(source_commit='fixture',output_root=str(tmp_path/'results'),token_policy=TOKEN_POLICY,
        units=[dict(unit_id='pilot',manifest=manifest)],max_cells_per_source_session=32,
        budget=dict(total_wall_seconds=1000,model_calls_cap=10,input_tokens_stop_threshold=100,
                    output_tokens_stop_threshold=100,package_max_bytes=1000000))
    rp=write_once(tmp_path/'release.json',release);attempts=[]
    monkeypatch.setattr(pilot,'audit_pilot',lambda _:dict(success=True))
    monkeypatch.setattr(pilot,'source_commit',lambda:'fixture')
    monkeypatch.setenv('XGAP_EXTERNAL_LLM_API_KEY','nonsecret-fixture')
    def run(**args):
        count=0;status='returned';reason=None
        for cell in pilot.load_pin(manifest)['cells']:
            target=args['output']/'cells'/cell['cell_id']
            if target.exists():continue
            reason=args['before_cell'](cell)
            if reason:status='budget_stopped';break
            target.mkdir(parents=True);attempts.append(cell['cell_id']);count+=1
            outcome=write_once(target/'outcome.json',dict(model_calls=1,input_tokens=None if unknown else tokens,output_tokens=10))
            write_once(target/'terminal.json',dict(outcome=outcome))
        return dict(status=status,budget_status=reason,new_cells=count,all_owned_closed=True)
    monkeypatch.setattr(pilot,'run',run)
    result=pilot.dispatch(rp['path'],rp['sha256'],execute=True)
    assert result['status']==expected and attempts==['0'] and result['usage']['sealed_cells']==1
    result=pilot.dispatch(rp['path'],rp['sha256'],execute=True)
    assert result['status']==expected and attempts==['0']
