"""Prompt revision integrity and unchanged required-identity semantics."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from xgap.agent.one_shot_grounding import ground_interpretation, OneShotGroundingError
from xgap.experiments.compact_profile import load_compact_graph_provider, derive_compact_prompt_profile
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.semantic.compact_lowering import lower_compact_query

PARENT=Path('/Users/anthonyche/xgap-data/financial-nl-native-20260912-compact-v1/profile/profile.json')
PIN='1b9af9d4e60e3428e8f5ac235bb5aab8237da1b329e91510a5992171deb78bd8'
CASES=Path('tests/fixtures/compact_roles_v2.json')


def test_prompt_only_child_keeps_data_policy_model_and_legacy_provider(tmp_path):
    raw=PARENT.read_bytes();parent=FrozenOneShotProfile.load(PARENT,expected_sha256=PIN)
    old,_,_,_,_,_,old_modes=parent.materialize()
    pin=derive_compact_prompt_profile(parent_path=PARENT,parent_sha256=PIN,output=tmp_path/'child')
    child=FrozenOneShotProfile.load(pin['path'],expected_sha256=pin['sha256'])
    new,_,_,_,_,_,new_modes=child.materialize()
    for key in ('dataset','source_schema','sources','backends'):
        assert new[key]==old[key]
    for key in ('catalog','estimator'):
        expected={**old[key],'path':str((PARENT.parent/old[key]['path']).resolve())}
        assert new[key]==expected
    assert {k:v for k,v in new['offline'].items() if k!='interpretation_revision'}==old['offline']
    for mode in old_modes:
        a,b=old_modes[mode],new_modes[mode]
        assert a[0]==b[0] and a[1].system_prompt!=b[1].system_prompt
        before,after=a[1].config.safe_dict(),b[1].config.safe_dict()
        assert {k:v for k,v in before.items() if k not in ('provider_id','prompt_hash')}=={
            k:v for k,v in after.items() if k not in ('provider_id','prompt_hash')}
        assert load_compact_graph_provider(mode=mode).system_prompt==a[1].system_prompt
    assert PARENT.read_bytes()==raw
    with pytest.raises(ValueError,match='same prompt'):
        derive_compact_prompt_profile(parent_path=pin['path'],parent_sha256=pin['sha256'],output=tmp_path/'again')
    with pytest.raises(ValueError,match='Unknown compact prompt'):
        load_compact_graph_provider(prompt_version='v999')


def test_name_id_variable_gold_contract_preserves_explicit_id_and_lookup_boundaries():
    profile=FrozenOneShotProfile.load(PARENT,expected_sha256=PIN)
    doc,_,bundle,*_=profile.materialize()
    for case in json.loads(CASES.read_text())['cases']:
        p,s=lower_compact_query(case['gold_compact'],doc['source_schema'])
        assert [h.mention for h in p.holes]==case['expected_mentions']
        _,trace=ground_interpretation(p,s,bundle,case['question'])
        assert trace['success'] and trace['lookup_count']==len(case['expected_mentions'])
        assert trace['external_calls']==trace['model_calls']==0
        if case['kind']=='business_id':
            comparisons=[c for op in p.operators if op.kind.value=='filter'
                for c in op.parameters['condition'].get('args',[op.parameters['condition']])]
            assert any(c.get('value')=='1' and c['op']=='eq' for c in comparisons)
        for entry in trace['candidate_sets']:
            assert entry['authoritative'] is False


def test_unresolved_required_role_is_retained_and_fails_without_repair():
    profile=FrozenOneShotProfile.load(PARENT,expected_sha256=PIN)
    doc,_,bundle,*_=profile.materialize()
    case=json.loads(CASES.read_text())['cases'][1];bad=deepcopy(case['gold_compact'])
    bad['nodes'][0]['entity']='person'
    p,s=lower_compact_query(bad,doc['source_schema'])
    assert p.holes[0].mention=='person' and p.holes[0].required
    with pytest.raises(OneShotGroundingError) as caught:
        ground_interpretation(p,s,bundle,case['question'])
    trace=caught.value.trace
    assert trace['candidate_sets'][0]['candidate_ids']==[]
    assert trace['lookup_count']==1 and trace['automatic_retries']==0
