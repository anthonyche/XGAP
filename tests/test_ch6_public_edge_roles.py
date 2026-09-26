from copy import deepcopy

import pytest

from xgap.experiments.ch6_fact_index import CORES
from xgap.experiments.ch6_heldout import QUESTION_VERSION, make_family, question_text, public_edge_role_text


@pytest.mark.parametrize('name,roles', [
    ('zigzag', ('e is the directed edge from a to b', 'f is the directed edge from c to b', 'g is the directed edge from c to d')),
    ('cycle', ('e is the directed edge from a to b', 'h is the directed edge from a to d')),
    ('witnessed_count', ('e is the directed edge from a to b', 'f is the directed edge from c to b')),
    ('bounded_path', ('f is the directed edge from c to b', 'reach names the directed path from a to b')),
])
def test_public_roles_bind_later_attribute_names(name, roles):
    core = CORES['D3']
    query, policy, _ = make_family(core, name, ['account:1', 'account:2'], 1000, 'W3', 'snapshot', 'family')
    before = deepcopy(query)
    text = question_text(core, name, query, policy, version=QUESTION_VERSION)
    assert all(role in text for role in roles)
    assert query == before
    assert 'Edge names used below:' not in question_text(core, name, query, policy)


def test_public_roles_keep_w4_choice_unresolved_and_witness_base_relation():
    core = CORES['D2']
    query, policy, _ = make_family(core, 'witnessed_sum', ['user:1', 'user:2'], 1000, 'W4', 'snapshot', 'family')
    text = question_text(core, 'witnessed_sum', query, policy, version=QUESTION_VERSION)
    assert 'e is the directed edge from a to b using one of the unresolved relations RATED_EARLY or RATED_LATE' in text
    assert 'f is the directed edge from c to b using the RATED relation' in text
    changed = deepcopy(query)
    changed['edges'][0]['type'] = 'RATED_LATE'
    assert question_text(core, 'witnessed_sum', changed, policy, version=QUESTION_VERSION) == text


def test_unknown_question_wording_version_is_rejected():
    core = CORES['D1']
    query, policy, _ = make_family(core, 'window_edge', ['person:1', 'person:2'], 1000, 'W1', 'snapshot', 'family')
    with pytest.raises(ValueError, match='wording version'):
        question_text(core, 'window_edge', query, policy, version='unknown')


def test_public_addendum_needs_no_query_or_selected_private_value():
    core = CORES['D2']
    _, policy, _ = make_family(core, 'zigzag', ['user:secret1', 'user:secret2'], 1000, 'W4', 'snapshot', 'family')
    text = public_edge_role_text(core, 'zigzag', policy)
    assert 'secret' not in text and '1000' not in text
    assert 'e is the directed edge from a to b using one of the unresolved relations RATED_EARLY or RATED_LATE' in text
    assert 'f is the directed edge from c to b using the RATED relation' in text
