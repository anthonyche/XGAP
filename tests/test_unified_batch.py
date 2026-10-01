"""The new method is separately pinned, scored and resumed, never relabelled old runs."""
from dataclasses import asdict,replace
import json

import pytest
import run_bounded_joint_batch as batch
from test_bounded_joint_batch import fixture,install_fake_runtime,launch
from xgap.experiments.unified_contract import METHODS,TRACK,configuration,load_configuration
from xgap.agent.unified_family import UnifiedSettings
from xgap.agent.unified_lookahead import Limits
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.nl_method_worker import run_nl


def test_export_keeps_common_request_cost_and_observed_online_work_separate():
    from xgap.experiments.unified_contract import metric_values
    core=dict(realized_trace_work_estimate=20,initial_decision_estimate_including_common_actions=25,
        joint_policy=dict(realized_trace_work_estimate=3,realized_acquisition_cost_estimate=2,
            selected_execution_cost_estimate=1,expanded_states=18,local_action_ms=4,acquisition_ms=7))
    row=metric_values(core)
    assert row['realized_trace_work_estimate']==20
    assert row['initial_decision_estimate_including_common_actions']==25
    assert row['realized_acquisition_cost_estimate']==2 and row['selected_execution_cost_estimate']==1
    assert (row['expanded_states'],row['local_action_ms'],row['acquisition_ms'])==(18,4,7)
    assert metric_values(dict(status='proposal_failed'))['realized_trace_work_estimate'] is None


def test_new_settings_roundtrip_and_strict_method_boundary(tmp_path):
    pin=write_once(tmp_path/'settings.json',configuration(settings=UnifiedSettings(limits=Limits(depth=2))))
    raw,_,settings,_=load_configuration(pin['path'],pin['sha256'])
    assert settings.limits.depth==2
    manifest=fixture(tmp_path)
    manifest['schema_version']=batch.UNIFIED_SCHEMA
    with pytest.raises(ValueError):batch.validate(manifest)
    for c in manifest['cells']:c['method']=METHODS[0]
    batch.validate(manifest)
    manifest['schema_version']=batch.SCHEMA
    with pytest.raises(ValueError):batch.validate(manifest)


def test_new_worker_dispatch_and_no_accidental_old_config(tmp_path,monkeypatch):
    from xgap.experiments import bounded_joint_worker
    seen=[]
    monkeypatch.setattr(bounded_joint_worker,'run',lambda **kwargs:seen.append(kwargs) or {})
    run_nl(request_path='r',request_sha256='a',profile_path='p',profile_sha256='b',method=METHODS[0],output=tmp_path,
        oracle_path='o',oracle_sha256='c',scope_path='s',scope_sha256='d',joint_config_path='c',joint_config_sha256='e')
    assert seen[0]['mode'] is None and seen[0]['method']==METHODS[0]


def test_new_batch_resume_keeps_attempt_identity_and_skips_sealed_failures(tmp_path,monkeypatch):
    seen,sessions=install_fake_runtime(monkeypatch,fail_cell='1')
    manifest=fixture(tmp_path);manifest['schema_version']=batch.UNIFIED_SCHEMA
    for c in manifest['cells']:c['method']=METHODS[0]
    first,args=launch(tmp_path,manifest,max_new_cells=2)
    assert first['schema_version']=='xgap-unified-batch-invocation-v1'
    assert first['counts']['sealed']==2
    second=batch.run(**args)
    assert second['counts']['sealed']==3 and seen==['0','1','2'] and all(s.closed for s in sessions)
    assert batch.run(**args)['new_cells']==0
