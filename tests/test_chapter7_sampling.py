"""Frozen sampling must be independent of outcomes and preserve family folds."""
import json
from xgap.experiments.chapter7_finbench_pilot import sample_families,split_group,make_family,windows
from xgap.semantic.intent_scope import construct_scope
from xgap.semantic.compact_identity import representation_key


def test_sampling_is_order_independent_unique_and_disjoint_from_formal():
    accounts=[str(i) for i in range(2000)]
    first=sample_families(accounts);second=sample_families(reversed(accounts))
    assert first==second and len(first)==24 and len({c['anchor'] for c in first})==24
    assert all(split_group(c['anchor'])=='pilot' and 0<=c['truth_index']<8 and 0<=c['window']<4 for c in first)
    assert len({c['family_group_id'] for c in first})==24
    for track in ('nl','controlled'):
        cases=[c for c in first if c['track']==track]
        assert len(cases)==12
        assert sum(c['method_order'][0].endswith('-exact') for c in cases)==6


def test_scope_regenerates_the_full_legal_family_without_hidden_truth():
    family,scope=make_family('123','2020-01-01 00:00:00.000','2020-01-02 00:00:00.000','test-snapshot')
    assert family.language_version=='v2' and family.coverage_basis is None
    assert len(family.candidates)==8 and sum(s.weight for s in family.slots)==4
    for source in family.candidates:
        draft=construct_scope([json.loads(source.query_json)],scope,'test-snapshot')
        keys=lambda f:{representation_key(json.loads(c.query_json),version='v2') for c in f.candidates}
        assert keys(draft)==keys(family)


def test_time_windows_depend_only_on_source_snapshot_and_do_not_overlap_interiors():
    values=windows('2020-01-01 00:00:00.000','2020-01-05 00:00:00.003')
    assert len(values)==4 and values[0][0]=='2020-01-01 00:00:00.000' and values[-1][1]=='2020-01-05 00:00:00.003'
    assert all(a<b for a,b in values) and all(a[1]==b[0] for a,b in zip(values,values[1:]))


def test_three_shape_sample_preserves_folds_balance_and_distinct_anchor_groups():
    from xgap.experiments.chapter7_finbench_coverage import sample, fold, TEMPLATES
    accounts = [str(i) for i in range(2000)]
    companies = [str(i) for i in range(500)]
    chosen = sample(accounts, companies)
    assert chosen == sample(reversed(accounts), reversed(companies))
    assert len(chosen) == len({c['family_group_id'] for c in chosen}) == 24
    assert all(fold(c['anchor_type'],c['anchor'])=='pilot' and 0<=c['truth_index']<16 and 0<=c['window']<4 for c in chosen)
    for shape in TEMPLATES:
        for track in ('nl','controlled'):
            rows = [c for c in chosen if c['template']==shape and c['track']==track]
            assert len(rows)==4 and sum(c['method_order'][0].endswith('-exact') for c in rows)==2
    assert all(fold('account',a)==split_group(a) for a in accounts)
