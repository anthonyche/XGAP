import pytest
from check_ch6_core_backend import selected_cases


def test_replay_keeps_original_index_and_does_not_change_bundle():
    b={'cases':[{'case_id':str(i)} for i in range(8)]}
    assert selected_cases(b,'4')==[(4,b['cases'][4])]
    assert len(selected_cases(b))==len(b['cases'])==8
    with pytest.raises(ValueError):selected_cases(b,'missing')
    with pytest.raises(ValueError):selected_cases({'cases':[{'case_id':'4'},{'case_id':'4'}]},'4')
