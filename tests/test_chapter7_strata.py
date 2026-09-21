"""Source-only eligibility, sampling invariance and pilot/formal separation."""
from types import SimpleNamespace
import pytest

from xgap.experiments.chapter7_finbench_strata import structural_frames, select_families, STRATA
from xgap.experiments.chapter7_finbench_coverage import fold
from xgap.experiments.chapter7_finbench_families import TEMPLATES


def edge(a,b):
    # Deliberately no amount, time, blocked flag, answer or method properties.
    return SimpleNamespace(from_id=a,to_id=b)


def test_active_eligibility_uses_direction_and_ownership_only():
    frames=structural_frames(['a','b','c','d'], ['owner','sender','idle'],
        [edge('a','b'),edge('a','b'),edge('c','c')], {'a':'sender','b':'owner'})
    assert frames['active_anchors']==dict(account=('a','c'),company=('owner',))
    assert frames['all_ids']['account']==('a','b','c','d')
    assert 'idle' in frames['all_ids']['company']
    assert frames==structural_frames(['d','c','b','a'], ['idle','sender','owner'],
        [edge('c','c'),edge('a','b')], {'b':'owner','a':'sender'})


@pytest.mark.parametrize('args', [
    (['a','a'], ['c'], [], {}),
    (['a'], ['c'], [edge('a','missing')], {}),
    (['a'], ['c'], [], {'missing':'c'}),
    (['a'], ['c'], [], {'a':'missing'}),
])
def test_inconsistent_source_frame_is_not_silently_pruned(args):
    with pytest.raises(ValueError):structural_frames(*args)


def fixture():
    return structural_frames([str(i) for i in range(400)], [str(i) for i in range(200)],
        [edge(str(i),str(i+1)) for i in range(250)], {str(i):str(i//2) for i in range(1,251)})


def test_uniform_and_active_are_separate_deterministic_fold_safe_samples():
    frames=fixture(); selected=select_families(frames,per_shape=8)
    reordered={s:{k:tuple(reversed(v)) for k,v in f.items()} for s,f in frames.items()}
    assert selected==select_families(reordered,per_shape=8)
    assert selected['total_case_records']==48
    for stratum in STRATA:
        rows=[r for r in selected['selected'] if r['stratum']==stratum]
        assert len({r['family_group_id'] for r in rows})==24
        for shape in TEMPLATES:assert sum(r['template']==shape for r in rows)==8
        for row in rows:
            assert fold(row['anchor_type'],row['anchor'])=='formal'
            assert row['anchor'] in frames[stratum][row['anchor_type']]
            assert 0<=row['window']<4 and 0<=row['truth_index']<16


def test_overlap_keeps_cluster_identity_without_excluding_uniform_anchors():
    accounts=[str(i) for i in range(40) if fold('account',str(i))=='formal'][:4]
    companies=[str(i) for i in range(40) if fold('company',str(i))=='formal'][:2]
    frames={s:dict(account=accounts,company=companies) for s in STRATA}
    result=select_families(frames,per_shape=2)
    assert result['total_case_records']==12 and result['distinct_anchor_groups']==6
    assert result['overlap_anchor_groups']==6
    assert {r['family_group_id'] for r in result['selected'] if r['stratum']=='all_ids'}=={
        r['family_group_id'] for r in result['selected'] if r['stratum']=='active_anchors'}


def test_insufficient_active_frame_fails_without_replenishing_from_inactive():
    frames=fixture();frames['active_anchors']['company']=()
    with pytest.raises(ValueError,match='Insufficient'):select_families(frames,per_shape=8)
