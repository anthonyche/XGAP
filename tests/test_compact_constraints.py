from copy import deepcopy
import hashlib
import json

import pytest

from xgap.experiments.ch6_fact_index import CORES
from xgap.experiments.ch6_heldout import template_query
from xgap.semantic.compact_constraints import PublicCompactConstraints, SCHEMA, canonicalize_with_constraints
from xgap.semantic.compact_identity import representation_key


def constraints(*, nonnull_measure=True):
    node = dict(identity_keys=['id', 'xgap_id'], nonnull=['id', 'xgap_id'],
                functional=['id', 'xgap_id', 'name'])
    edge = dict(identity_keys=['id', 'xgap_id'],
                nonnull=['id', 'xgap_id', 'timestamp'] + (['amount'] if nonnull_measure else []),
                functional=['id', 'xgap_id', 'timestamp', 'amount'])
    schema = dict(identity_property='xgap_id', graph=dict(nodes={'Account': dict(properties=node['functional'])},
        edges=[dict(label='TRANSFERRED_TO', properties=edge['functional'])]))
    digest = hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    doc = dict(schema_version=SCHEMA, contract_id='public-source-only-test', source_schema_sha256=digest,
        source_proof=dict(path='/public/materialization.json', sha256='a'*64, bytes=100), scale='1',
        nodes={'Account': node}, edges={'TRANSFERRED_TO': edge})
    return PublicCompactConstraints.from_dict(doc).validate_source_schema(schema), schema


def query(name='witnessed_count'):
    return template_query(CORES['D3'], name, 'account:1', 100)


def key(q, contract=None):
    return representation_key(q, version='v2', constraints=contract)


def test_node_business_and_canonical_identity_equal_only_with_total_key_proof():
    q = query('zigzag'); changed = deepcopy(q)
    for predicate in changed['where']:
        if predicate['op'] == 'ne':
            predicate['left']['property'] = predicate['right']['property'] = None
    c, _ = constraints()
    assert key(q) != key(changed)
    assert key(q, c) == key(changed, c)
    rewritten, ledger = canonicalize_with_constraints(q, c)
    assert len(ledger) == 2 and q['where'][1]['left']['property'] == 'id'
    assert rewritten['select'] == q['select'] and rewritten['order_by'] == q['order_by']


@pytest.mark.parametrize('change', ['mixed_keys', 'literal', 'ordered', 'cross_type'])
def test_unproved_comparisons_are_not_canonicalized(change):
    q = query('zigzag'); p = deepcopy(q['where'][1]); q['where'] = [p]
    if change == 'mixed_keys': p['right']['property'] = 'xgap_id'
    elif change == 'literal': p['right'] = {'value': 'account:1'}
    elif change == 'ordered': p['op'] = 'lt'
    elif change == 'cross_type': q['nodes'][0]['type'] = 'Different'
    c, _ = constraints(); actual, ledger = canonicalize_with_constraints(q, c)
    assert actual == q and not ledger


def test_count_distinct_edge_key_and_nonnull_contribution_count_are_equivalent():
    q = query(); changed = deepcopy(q)
    changed['select']['total'] = dict(aggregate='count', field=dict(var='e', property='id'), distinct=True)
    c, _ = constraints()
    assert key(q) != key(changed) and key(q, c) == key(changed, c)
    assert json.loads(key(q, c))['public_constraints_sha256'] == c.identity


@pytest.mark.parametrize('change', ['nullable', 'distinct_measure', 'missing_grain', 'extra_grain', 'witness_group', 'other_aggregate'])
def test_count_rule_preserves_nulls_values_and_joint_witness_multiplicity(change):
    q = query(); changed = deepcopy(q)
    changed['select']['total'] = dict(aggregate='count', field=dict(var='e', property='id'), distinct=True)
    c, _ = constraints(nonnull_measure=change != 'nullable')
    if change == 'distinct_measure': q['select']['total']['distinct'] = True
    elif change == 'missing_grain': q['contribution_by'] = changed['contribution_by'] = None
    elif change == 'extra_grain': q['contribution_by'] = changed['contribution_by'] = ['e', 'f']
    elif change == 'witness_group':
        # Two c nodes can have the same name, retaining two e,c identity tuples
        # in one displayed name group. COUNT(amount) can then exceed DISTINCT id.
        q['select']['witness'] = changed['select']['witness'] = dict(var='c', property='name')
    elif change == 'other_aggregate':
        q['select']['total']['aggregate'] = changed['select']['total']['aggregate'] = 'sum'
    assert key(q, c) != key(changed, c)


def test_constraints_are_explicitly_source_bound_and_do_not_claim_replica_key_uniqueness():
    c, schema = constraints(); raw = c.to_dict()
    raw['scale'] = '4'
    with pytest.raises(ValueError, match='unreplicated'):
        PublicCompactConstraints.from_dict(raw)
    changed = deepcopy(schema); changed['identity_property'] = 'different'
    with pytest.raises(ValueError, match='different source schema'):
        c.validate_source_schema(changed)
    raw = c.to_dict(); raw['edges']['TRANSFERRED_TO']['nonnull'].remove('id')
    with pytest.raises(ValueError, match='total, scalar and non-null'):
        PublicCompactConstraints.from_dict(raw)
