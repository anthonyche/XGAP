"""New strong worker handoff; saved responses, no real backend/model service."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from test_practical_profile import FIXTURE, REPLAY, arguments, failed_clients, no_network, published, sha
from xgap.experiments import practical_method_worker as worker
from xgap.experiments import common_method_trial as common
from xgap.experiments import practical_records
from xgap.experiments.nl_method_worker import run_nl
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.process_guard import ProcessBudget, run_guarded_command


def worker_args(pin,output,method='xgap-strong-performance'):
    return {k:v for k,v in arguments(pin,output).items() if k!='mode'}|{'method':method}


def install_replay(monkeypatch,path=REPLAY/'replay-v2.json'):
    def replay(**kwargs):
        assert kwargs['operation']=='execute'
        return practical_records.run_record(**{**kwargs,'operation':'replay','replay_path':path,'replay_sha256':sha(path)})
    monkeypatch.setattr(worker,'run_record',replay)


def test_new_worker_dispatches_real_strong_replay_without_relabeling_historical_cost(tmp_path,monkeypatch):
    _,pin=published(tmp_path);install_replay(monkeypatch)
    result=run_nl(**worker_args(pin,tmp_path/'worker'))
    assert result['success'] and result['track']=='trusted_template' and result['strong_plan'],result
    assert result['execution_kind']=='offline_replay' and result['model_calls']==result['input_tokens']==result['output_tokens']==0
    assert result['backend_calls']==0 and result['top_level_attempts']==1
    assert result['unvalidated_bindings']==['predicate'] and result['semantic_discrepancy_upper_bound'] is None
    assert not result['optimality_certified'] and result['admission_ms']>0
    answer=json.loads(Path(result['result']['path']).read_text())
    assert answer['answer']==[{'edge':'https://xgap.test/toy/e4','person':'https://xgap.test/toy/c'}]
    assert result['planning_ms'] is not None and result['execution_ms'] is not None


def test_faithfully_replayed_failure_remains_a_failed_method_not_a_correct_empty_answer(tmp_path,monkeypatch):
    _,pin=published(tmp_path)
    monkeypatch.setattr(practical_records,'native_clients',lambda specs:failed_clients(True))
    original=practical_records.run_record(**arguments(pin,tmp_path/'original','exact'),operation='execute')
    assert not original['success']
    install_replay(monkeypatch,Path(original['replay']['path']))
    result=run_nl(**worker_args(pin,tmp_path/'worker','xgap-strong-exact'))
    assert not result['success'] and result['top_level_attempts']==1
    assert result['model_calls']==0 and json.loads(Path(result['result']['path']).read_text())['answer'] is None
    replay_receipt=json.loads((tmp_path/'worker/core/receipt.json').read_text())
    assert replay_receipt['replay_match'] and not replay_receipt['original_execution_success']


def test_live_common_trial_refuses_an_offline_replay_receipt_and_closes_phase(tmp_path,monkeypatch):
    _,pin=published(tmp_path);install_replay(monkeypatch);stops=[];commands=[]
    class Resources:
        def __init__(self,*a,**k):pass
        def summary(self):return {'scope':'in-process replay fixture; no owned native services'}
        def stop(self):stops.append(True);return {'complete':True,'recovery_ms':0}
    class Observer:
        def set_phase(self,phase):self.phase=phase
        def snapshot(self,phase):return {'failed_requests':0,'requests':0}
    def guarded(command,**kwargs):
        commands.append(command)
        args={k:command[command.index('--'+k.replace('_','-'))+1] for k in
              ('request_path','request_sha256','profile_path','profile_sha256','method','output')}
        run_nl(**args)
        return {'success':True,'status':'completed'}
    monkeypatch.setattr(common,'OwnedResources',Resources);monkeypatch.setattr(common,'run_guarded_command',guarded)
    result=common.run_practical_trial(**worker_args(pin,tmp_path/'trial'),observer=Observer(),
        owned_services=[SimpleNamespace(role='source')])
    assert not result['success'] and not result['can_continue_session'] and stops==[True]
    assert result['track']=='trusted_template' and 'replay was substituted' in result['error']
    assert len(commands)==1 and Path(commands[0][1]).name=='run_nl_method_worker.py'
    assert result['timing']['total_online_ms']>0 and result['quiescence']['complete']


def test_strong_methods_cannot_enter_the_legacy_nl_population(tmp_path):
    _,pin=published(tmp_path)
    with pytest.raises(ValueError,match='declared track'):
        common.run_nl_trial(**worker_args(pin,tmp_path/'wrong-track'),observer=None,owned_services=[])
    from xgap.experiments.campaign_schedule import METHODS
    assert METHODS['natural_language']==('xgap-precision','xgap-performance','fedx','fedup')
    assert METHODS['fixed_semantics']==('xgap-rdf','fedx','fedup')


def test_missing_invocation_usage_is_unknown_even_when_call_count_is_known():
    # A process may preserve the fact of a model call but lose its usage payload.
    assert worker._usage({},1)=={'input_tokens':None,'output_tokens':None}
    known={'model_invocations':{'model':{'generation_calls':1,'repair_calls':0,
        'usage':{'input_tokens':353,'output_tokens':19}}}}
    assert worker._usage(known,1)=={'input_tokens':353,'output_tokens':19}
    assert worker._usage(known,2)=={'input_tokens':None,'output_tokens':None}


def test_actual_guarded_cli_dispatch_rejects_bad_binding_before_any_call(tmp_path):
    _,pin=published(tmp_path);raw=json.loads((FIXTURE/'request.json').read_text())
    raw['trusted_bindings']['unknown_slot']='entity:alice';request=write_once(tmp_path/'bad.json',raw)
    repo=Path(__file__).resolve().parents[1]
    args={**worker_args(pin,tmp_path/'worker'),'request_path':request['path'],'request_sha256':request['sha256']}
    command=[sys.executable,str(repo/'scripts/run_nl_method_worker.py')]
    for key,value in args.items():command.extend(('--'+key.replace('_','-'),str(value)))
    guarded=run_guarded_command(command,cwd=repo,output=tmp_path/'guard',budget=ProcessBudget(wall_seconds=5))
    assert guarded['success'],guarded
    receipt=json.loads((tmp_path/'worker/receipt.json').read_text())
    assert not receipt['success'] and receipt['track']=='trusted_template'
    assert receipt['model_calls']==receipt['backend_calls']==receipt['top_level_attempts']==0
    assert not (tmp_path/'worker/core/intent.json').exists()
