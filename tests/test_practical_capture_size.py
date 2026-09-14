"""Large saved capture admission without new native/model requests."""
import hashlib
import json
from pathlib import Path

import pytest

from test_practical_profile import REPLAY,arguments,no_network,published,sha
from xgap.experiments.one_shot_profile import MAX_BYTES
from xgap.experiments.one_shot_records import MAX_CAPTURE_REPLAY_BYTES,write_once
from xgap.experiments.practical_records import _capture_bytes,run_record


def test_saved_capture_above_config_limit_replays_identical_outcome_without_network(tmp_path):
    _,pin=published(tmp_path)
    manifest=json.loads((REPLAY/'replay-v2.json').read_text())
    for entry in manifest['backends']:entry['path']=str(REPLAY/entry['path'])
    first=manifest['backends'][0]
    # JSON whitespace changes file size only. All source values, artifacts and
    # expected observations remain identical; no simulated large graph claim.
    data=Path(first['path']).read_bytes()+b' '*(MAX_BYTES+1)
    path=tmp_path/'large-capture.json';path.write_bytes(data)
    manifest['backends'][0]={'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
    replay=write_once(tmp_path/'replay.json',manifest)
    result=run_record(**arguments(pin,tmp_path/'result'),operation='replay',replay_path=replay['path'],replay_sha256=replay['sha256'])
    assert result['success'] and result['replay_match'],result
    assert result['model_network_calls']==result['source_network_calls']==0
    assert result['source_invocations']==2 and result['final_plan_executions']==1


@pytest.mark.parametrize('size',(MAX_CAPTURE_REPLAY_BYTES+1,-1,True))
def test_invalid_capture_size_rejected_before_opening_nonexistent_payload(tmp_path,size):
    with pytest.raises(ValueError,match='bounded replay contract'):
        _capture_bytes(tmp_path,{'path':'never-opened','sha256':'0'*64,'bytes':size})


def test_optional_size_does_not_weaken_hash_or_truncation_checks(tmp_path):
    path=tmp_path/'capture.json';path.write_bytes(b'{}\n')
    assert _capture_bytes(tmp_path,{'path':path.name,'sha256':sha(path)})==b'{}\n'
    for pin in ({'path':path.name,'sha256':'0'*64}, {'path':path.name,'sha256':sha(path),'bytes':2}):
        with pytest.raises(ValueError,match='size/hash mismatch'):_capture_bytes(tmp_path,pin)
