"""Large intermediate traces must not make successful small answers unreadable."""
import json
from pathlib import Path

from test_practical_method_worker import install_replay,worker_args
from test_practical_profile import no_network,published
from xgap.experiments import practical_method_worker as worker
from xgap.experiments import practical_outcome
from xgap.experiments.one_shot_profile import MAX_BYTES
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.practical_profile import FrozenPracticalProfile


def test_worker_reads_small_outcome_when_successful_saved_execution_has_a_large_intermediate_trace(tmp_path,monkeypatch):
    _,pin=published(tmp_path);install_replay(monkeypatch)
    original=FrozenPracticalProfile.run_prepared
    def padded(self,*args,**kwargs):
        core=original(self,*args,**kwargs)
        # Controlled size boundary only: the actual saved source calls, final
        # answer and outcome fingerprint are unchanged. No large query is run.
        core['execution']['result']['value']['node_results'][0]['rows']=[{'payload':'x'*(MAX_BYTES+1)}]
        return core
    monkeypatch.setattr(FrozenPracticalProfile,'run_prepared',padded)
    result=worker.run_practical(**worker_args(pin,tmp_path/'worker'))
    assert result['success'] and result['execution_kind']=='offline_replay',result
    assert result['model_calls']==result['backend_calls']==result['input_tokens']==result['output_tokens']==0
    receipt=json.loads((tmp_path/'worker/core/receipt.json').read_text())
    assert receipt['result']['bytes']>MAX_BYTES and receipt['outcome']['bytes']<4096
    summary=json.loads(Path(receipt['outcome']['path']).read_text())
    assert summary['trace']==receipt['result']==result['core_result']
    assert json.loads(Path(result['result']['path']).read_text())['answer']==[
        {'edge':'https://xgap.test/toy/e4','person':'https://xgap.test/toy/c'}]
    assert result['strong_plan'] and result['planning_ms'] is not None and result['execution_ms'] is not None


def test_another_traces_summary_cannot_be_substituted_and_missing_summary_never_falls_back(tmp_path,monkeypatch):
    _,pin=published(tmp_path);install_replay(monkeypatch);original=worker.run_record
    def substitute(**kwargs):
        receipt=original(**kwargs)
        summary=json.loads(Path(receipt['outcome']['path']).read_text())
        summary['trace']={**summary['trace'],'sha256':'0'*64}
        receipt['outcome']=write_once(tmp_path/'foreign-outcome.json',summary)
        return receipt
    monkeypatch.setattr(worker,'run_record',substitute)
    result=worker.run_practical(**worker_args(pin,tmp_path/'worker'))
    assert not result['success'] and 'outcome/trace identity mismatch' in result['error']
    assert result['model_calls']==result['backend_calls']==0
    assert practical_outcome.read_outcome({'outcome':None,'result':{'path':'/never/read/trace','sha256':'0'*64}})=={}


def test_old_bounded_records_remain_readable(tmp_path):
    pin=write_once(tmp_path/'old-result.json',{'success':False,'status':'original_failure','answer_rows':[]})
    assert practical_outcome.read_outcome({'result':pin})=={'success':False,'status':'original_failure','answer_rows':[]}


def test_missing_usage_and_null_execution_value_remain_unknown(tmp_path):
    core={'success':False,'status':'failed','execution':{'result':{'value':None}},
        'model_invocations':{'model':{'generation_calls':1,'repair_calls':0}}}
    trace=write_once(tmp_path/'trace.json',core)
    outcome=practical_outcome.write_outcome(tmp_path,core,trace)
    loaded=practical_outcome.read_outcome({'result':trace,'outcome':outcome})
    assert worker._usage(loaded,1)=={'input_tokens':None,'output_tokens':None}
    assert loaded['execution']['result']['value']['elapsed_ms'] is None and loaded['success'] is False
