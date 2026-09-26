"""Public role selection must commute with equivalent edge declaration order."""
from copy import deepcopy
from dataclasses import replace
from itertools import permutations
import json
import pytest

from xgap.experiments.ch6_heldout import make_family
from xgap.semantic.compact_identity import representation_key
from xgap.semantic.intent_scope import ScopeDomain, ScopePolicy, construct_scope, upgrade_edge_type_domains


def fixture():
    core = dict(node_type='Person', target_type='Person', relation='KNOWS', measure='value',
                control='isBlocked', control_values=[False, True])
    return make_family(core, 'zigzag', ['a1', 'a2'], 100, 'W4', 'toy-snapshot', 'public-toy')


def keys(family):
    return {representation_key(json.loads(c.query_json), version='v2') for c in family.candidates}


def test_public_scope_preserves_role_under_every_edge_permutation():
    query, policy, expected = fixture()
    before = deepcopy(query)
    for edges in permutations(query['edges']):
        proposal = {**query, 'edges': list(edges)}
        assert representation_key(proposal, version='v2') == representation_key(query, version='v2')
        actual = construct_scope([proposal], policy, 'toy-snapshot')
        assert keys(actual) == keys(expected)
        for candidate in actual.candidates:
            labels = {e['var']: e['type'] for e in json.loads(candidate.query_json)['edges']}
            assert labels['e'] in ('KNOWS_EARLY', 'KNOWS_LATE')
            assert labels['f'] == labels['g'] == 'KNOWS'
    assert query == before


@pytest.mark.parametrize('case', ['missing', 'ambiguous'])
def test_selector_refuses_missing_or_ambiguous_role(case):
    query, policy, _ = fixture()
    if case == 'missing': query['edges'][0]['type'] = 'KNOWS'
    else: query['edges'][1]['type'] = 'KNOWS_LATE'
    with pytest.raises(ValueError, match='exactly one proposed edge'):
        construct_scope([query], policy, 'toy-snapshot')


def test_old_policy_is_unchanged_until_explicit_public_migration():
    query, policy, expected = fixture()
    old = replace(policy, domains=tuple(replace(d, edge_selector=None) for d in policy.domains))
    raw = old.to_dict(); assert all('edge_selector' not in d for d in raw['domains'])
    assert ScopePolicy.from_dict(raw).to_dict() == raw
    upgraded = upgrade_edge_type_domains(old)
    assert old.to_dict() == raw and upgraded.policy_id.endswith(':edge-type-domain-v1')
    assert ScopePolicy.from_dict(upgraded.to_dict()) == upgraded
    assert upgrade_edge_type_domains(upgraded) == upgraded
    query['edges'].reverse()
    assert keys(construct_scope([query], upgraded, 'toy-snapshot')) == keys(expected)
    assert keys(construct_scope([query], old, 'toy-snapshot')).isdisjoint(keys(expected))


def test_selector_cannot_widen_domain_or_target_an_unrelated_coordinate():
    _, policy, _ = fixture(); domain = policy.domains[-1]
    with pytest.raises(ValueError, match='frozen type domain'):
        replace(domain, edge_selector={'types': ['KNOWS']})
    with pytest.raises(ValueError, match='edge type coordinate'):
        replace(domain, slot=replace(domain.slot, path=('nodes',0,'type')))
