import json
from types import SimpleNamespace
import pytest

from xgap.experiments.ch6_direct import METHOD
from xgap.experiments.nl_method_worker import run_nl
from xgap.experiments import ch6_direct_worker
from test_bounded_joint_batch import fixture, install_fake_runtime, launch
import run_bounded_joint_batch as batch
from release_ch6_finbench_first import family3, selection
from xgap.experiments.chapter7_finbench_families import TEMPLATES
from xgap.experiments.bounded_joint_toy import local_runtime
from xgap.agent.intent_execution import snapshot_identity


def test_direct_worker_accepts_no_private_or_controlled_inputs(tmp_path, monkeypatch):
    seen=[]
    monkeypatch.setattr(ch6_direct_worker,'run',lambda **kwargs:seen.append(kwargs) or {})
    args=dict(request_path='public',request_sha256='a',profile_path='profile',profile_sha256='b',
              method=METHOD,output=tmp_path,joint_config_path='settings',joint_config_sha256='c')
    run_nl(**args)
    assert len(seen)==1 and not any(k.startswith(('oracle','scope','controlled')) for k in seen[0])
    for extra in (dict(oracle_path='secret'),dict(scope_path='scope'),dict(controlled_state_path='truth')):
        with pytest.raises(ValueError,match='no intent oracle'):run_nl(**args,**extra)
    assert len(seen)==1


def test_direct_batch_keeps_private_reference_at_supervisor(tmp_path,monkeypatch):
    install_fake_runtime(monkeypatch)
    original=batch.run_nl_trial;seen=[]
    def checked(**kwargs):
        seen.append(kwargs)
        assert not any(k.startswith(('oracle','scope','controlled')) for k in kwargs)
        return original(**kwargs)
    monkeypatch.setattr(batch,'run_nl_trial',checked)
    manifest=fixture(tmp_path);manifest['schema_version']=batch.UNIFIED_SCHEMA
    for cell in manifest['cells']:cell['method']=METHOD
    result,_=launch(tmp_path,manifest)
    assert result['counts']['execution_success']==3 and len(seen)==3
    manifest['cells'][0]['controlled_state']=manifest['cells'][0]['scope']
    with pytest.raises(ValueError,match='natural-language'):batch.validate(manifest)


def test_three_binary_slots_preserve_hard_upper_boundary_and_equal_weights():
    _,options,_=local_runtime()
    snapshot=snapshot_identity(options['sources'],options['backends'],options['source_schema'])
    for template in TEMPLATES:
        family,policy,question,_=family3(template,'1','2020-01-01 00:00:00.000','2020-01-04 00:00:00.000',snapshot)
        assert len(family.candidates)==8 and len(family.slots)==3
        assert {s.weight for s in family.slots}=={1}
        for candidate in family.candidates:
            q=json.loads(candidate.query_json)
            assert (q['path']['time']['upper_inclusive'] if q['path'] else q['where'][3]['op']=='le')
        assert 'upper time boundary is always inclusive' in question


def test_source_only_selection_does_not_require_answers_or_performance():
    data=SimpleNamespace(accounts={str(i):{} for i in range(1000)},companies={str(i):{} for i in range(1000)},
        transfers=[SimpleNamespace(from_id=str(i),to_id=str(i)) for i in range(0,1000,2)],
        company_by_account={str(i):str(i) for i in range(1000)})
    chosen=selection(data)
    assert chosen==selection(data) and len(chosen)==6
    assert len({(c['anchor_type'],c['anchor']) for c in chosen})==6
    assert all(int(c['anchor'])%2==0 for c in chosen if c['stratum']=='active')
