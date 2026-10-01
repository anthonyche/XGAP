"""One offline publication/preflight boundary; no model, native service or fit."""
import json
from pathlib import Path

from test_one_shot_records import prepared
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.experiments.one_shot_records import run_record
from xgap.experiments.refined_modes_profile import derive_refined_modes_profile


def test_published_modes_preserve_pinned_parent_dependencies_and_preflight(prepared,tmp_path):
    args,old=prepared;before=Path(args['profile_path']).read_bytes()
    old=json.loads(before)  # Compare persisted JSON, not the fixture's pre-serialization tuples.
    child=derive_refined_modes_profile(parent_path=args['profile_path'],parent_sha256=args['profile_sha256'],
        output=tmp_path/'refined.json',rows_per_relation=2,max_quality_deficit=.1)
    profile=FrozenOneShotProfile.load(child['path'],expected_sha256=child['sha256'])
    doc,_,_,_,_,_,modes=profile.materialize()
    assert Path(args['profile_path']).read_bytes()==before
    assert doc['catalog']==old['catalog'] and doc['estimator']==old['estimator']
    assert doc['backends']==old['backends'] and doc['source_schema']==old['source_schema']
    assert modes['precision'][0].max_quality_deficit==.1 and modes['precision'][0].retrieval_rows_per_relation is None
    assert modes['performance'][0].retrieval_scope=='bind_after_anchor_v1'
    assert modes['performance'][0].retrieval_rows_per_relation==2
    for name in modes:
        assert doc['modes'][name]['provider']['prompt']['sha256']==old['modes'][name]['provider']['prompt']['sha256']
        receipt=run_record(profile_path=child['path'],profile_sha256=child['sha256'],
            request_path=args['request_path'],request_sha256=args['request_sha256'],mode=name,
            output=tmp_path/name,operation='preflight')
        assert receipt['success'] and receipt['model_network_calls']==receipt['backend_network_calls']==0
        assert receipt['policy']['schema_version']=='xgap-one-shot-policy-v3'
