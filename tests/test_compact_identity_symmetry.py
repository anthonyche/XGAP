from copy import deepcopy
from itertools import permutations

import pytest

from test_compact_identity import renamed
from test_bounded_joint import base_query, scope, user
from test_intent_strong import QUESTION
from xgap.semantic.compact_identity import representation_key
from xgap.semantic.intent_scope import construct_scope


def identity(q, version='v1'):
    return representation_key(q, version=version)


@pytest.mark.parametrize('op', ['eq', 'ne'])
def test_reference_equality_is_symmetric_before_alpha_role_coloring(op):
    query = base_query()
    query['where'].append(dict(left=dict(var='other',property='id'), op=op,
        right=dict(var='start',property='id'), value_type='scalar'))
    alternate = renamed(query)
    last = alternate['where'][0]
    last['left'], last['right'] = last['right'], last['left']
    alternate['nodes'].reverse(); alternate['edges'].reverse()
    before = deepcopy(alternate)
    assert identity(query) == identity(alternate)
    assert alternate == before


def test_endpoint_property_ownership_and_inequality_direction_remain_exact():
    q = base_query()
    q['where'].append(dict(left=dict(var='other',property='id'), op='eq',
        right=dict(var='start',property='name'), value_type='scalar'))
    changed = deepcopy(q)
    changed['where'][-1]['left']['property'] = 'name'
    changed['where'][-1]['right']['property'] = 'id'
    assert identity(q) != identity(changed)
    q['where'][-1]['op'] = 'gt'
    reversed_ = deepcopy(q)
    p = reversed_['where'][-1]; p['left'],p['right'] = p['right'],p['left']
    assert identity(q) != identity(reversed_)


@pytest.mark.parametrize('version', ['v1','v2'])
def test_joint_contribution_key_order_is_not_an_output_order(version):
    q = base_query()
    q['select']['account_distance'] = dict(aggregate='count',field=dict(var='other',property='id'),distinct=True)
    key = 'deduplicate_by' if version == 'v1' else 'contribution_by'
    if version == 'v2': q.pop('deduplicate_by')
    q[key] = ['start', 'other', 'signin']
    for order in permutations(q[key]):
        alternate = deepcopy(q); alternate[key] = list(order)
        assert identity(q,version) == identity(renamed(alternate),version)
    changed = deepcopy(q); changed[key] = ['start', 'other']
    assert identity(q,version) != identity(changed,version)


def test_v2_nonaggregate_contribution_equivalence_is_symmetric_only():
    q = base_query(); q['contribution_by'] = q.pop('deduplicate_by')
    alternate = deepcopy(q); alternate['contribution_by'] = ['signin']
    assert identity(q,'v2') == identity(alternate,'v2')
    changed = deepcopy(alternate); changed['limit'] = 1
    assert identity(q,'v2') != identity(changed,'v2')


def test_count_field_and_distinct_cannot_be_inferred_from_business_id():
    q = base_query(); q['contribution_by'] = ['signin']; q.pop('deduplicate_by')
    q['select'] = dict(total=dict(aggregate='count',field=dict(var='signin',property='value'),distinct=False))
    q['order_by'] = [dict(field='total',direction='desc')]
    changed = deepcopy(q); changed['select']['total']['field']['property'] = 'id'
    assert identity(q,'v2') != identity(changed,'v2')
    changed = deepcopy(q); changed['select']['total']['distinct'] = True
    assert identity(q,'v2') != identity(changed,'v2')


def test_paid_authority_accepts_reference_symmetry_without_revealing_choice(tmp_path):
    q = base_query()
    q['where'].append(dict(left=dict(var='other',property='id'), op='ne',
        right=dict(var='start',property='id'), value_type='scalar'))
    alternate = renamed(q)
    predicate = alternate['where'][0]
    predicate['left'], predicate['right'] = predicate['right'], predicate['left']
    draft = construct_scope([alternate], scope(), 'public-snapshot')
    authority = user(tmp_path,q)
    response = authority.confirm_scope(QUESTION,draft)
    assert response.status.value == 'success' and response.value['covered']
    assert set(response.value) == {'covered','question_sha256','proposed_scope_sha256'}
    assert response.metrics['user_calls'] == 1 and response.metrics['disclosed_coordinates'] == 0
    assert response.metrics['query_identity'] == 'xgap-compact-representation-identity-v3'
