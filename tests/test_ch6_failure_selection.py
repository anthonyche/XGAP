import pytest
from check_ch6_core_backend import selected_cases


def test_replay_keeps_original_index_and_does_not_change_bundle():
    b={'cases':[{'case_id':str(i)} for i in range(8)]}
    assert selected_cases(b,'4')==[(4,b['cases'][4])]
    assert len(selected_cases(b))==len(b['cases'])==8
    with pytest.raises(ValueError):selected_cases(b,'missing')
    with pytest.raises(ValueError):selected_cases({'cases':[{'case_id':'4'},{'case_id':'4'}]},'4')


def test_single_case_success_cannot_release_a_whole_cohort(tmp_path,monkeypatch):
    import prepare_ch6_execution_units as module
    spec=dict(schema_version='xgap-ch6-unit-preparation-v1',method_results_read=0,
        input_track='nl',repetitions=1,bundle={},prepared={},backend_admission={})
    values=iter([spec,{},dict(success=True),dict(success=True,backend_roundtrip=True,
        admission_scope='single_case_replay',full_bundle_admitted=False)])
    monkeypatch.setattr(module,'load_pin',lambda _:next(values))
    with pytest.raises(ValueError,match='actual admitted source'):
        module.prepare('spec','hash',tmp_path/'not-created')
    assert not (tmp_path/'not-created').exists()
