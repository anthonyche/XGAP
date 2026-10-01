"""Bounded workload construction and independent CSV reference boundaries."""
from collections import defaultdict
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path

import pytest

from xgap.agent.intent_certificate import IntentSlot
from xgap.experiments.chapter7_finbench_families import TEMPLATES, make_family, reference_rows
from xgap.experiments.m15_finbench_workload import FinBenchQueryData, Transfer
from xgap.semantic.compact_identity import representation_key
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.intent_scope import ScopeDomain, ScopePolicy, construct_scope


LOW = '2020-01-01 00:00:00.000'
MID = '2020-01-02 00:00:00.000'
HIGH = '2020-01-03 00:00:00.000'


def family(template):
    return make_family(template, 'C' if template == TEMPLATES[2] else '1', LOW, HIGH, 'tiny')


def keys(value):
    return {representation_key(json.loads(c.query_json), version='v2') for c in value.candidates}


@pytest.mark.parametrize('template', TEMPLATES)
def test_all_legal_candidates_lower_and_reordered_predicates_preserve_scope(template):
    source, policy, question, normalization = family(template)
    schema = json.loads(Path('datasets/bounded_joint_toy_v1/fixture.json').read_text())['schema']
    assert len(source.candidates) == 16 and sum(s.weight for s in source.slots) == 6
    assert source.coverage_basis is None and question and normalization['fields']
    assert ScopePolicy.from_dict(json.loads(json.dumps(policy.to_dict()))) == policy
    for candidate in source.candidates:
        query = json.loads(candidate.query_json)
        program, assignments = lower_compact_query(query, schema, version='v2', optimize=True)
        assert not program.holes and 0 < len(program.operators) <= 64
        assert set(assignments.values()) == {'graph', 'control'}
        query['where'].reverse()
        draft = construct_scope([query], policy, 'tiny')
        assert keys(draft) == keys(source)
        assert sum(s.weight for s in draft.slots) == 6
        assert all(next(p['right']['value'] for p in json.loads(c.query_json)['where']
                        if p['left']['property'] == 'id') == ('C' if template == TEMPLATES[2] else '1')
                   for c in draft.candidates)


def test_selector_does_not_repair_missing_or_ambiguous_predicates():
    source, policy, _, _ = family(TEMPLATES[1])
    query = json.loads(source.candidates[0].query_json)
    missing = deepcopy(query)
    missing['where'] = [p for p in missing['where'] if p['left']['property'] != 'isBlocked']
    duplicate = deepcopy(query)
    duplicate['where'].append(deepcopy(duplicate['where'][1]))
    for bad in (missing, duplicate):
        with pytest.raises(ValueError, match='exactly one'):
            construct_scope([bad], policy, 'tiny')
    reordered = deepcopy(query)
    reordered['where'].reverse()
    with pytest.raises(ValueError, match='coordinate locations'):
        construct_scope([query, reordered], policy, 'tiny')


def test_resolved_locations_cannot_overlap_a_fixed_coordinate():
    source, _, _, _ = family(TEMPLATES[1])
    query = json.loads(source.candidates[0].query_json)
    # Distinct declared locations would both resolve to where[1].right.value.
    selector = {'property': 'isBlocked', 'operators': ['eq']}
    policy = ScopePolicy('collision', (
        ScopeDomain(IntentSlot('fixed', ('where', 1, 'right', 'value')), (False, True)),
        ScopeDomain(IntentSlot('located', ('where', 2, 'right', 'value')), (False, True), selector)
    ), language_version='v2')
    with pytest.raises(ValueError, match='nonoverlapping'):
        construct_scope([query], policy, 'tiny')


@pytest.mark.parametrize('selector', [
    {'property': 'isBlocked', 'operators': [{}]},
    {'property': 'isBlocked', 'operators': ['eq', 'eq']},
    {'property': 'isBlocked', 'operators': ['invented']},
])
def test_selector_rejects_malformed_operators(selector):
    with pytest.raises(ValueError, match='WHERE locator'):
        ScopeDomain(IntentSlot('blocked', ('where', 1, 'right', 'value')), (False, True), selector)


def test_legacy_scope_serialization_does_not_add_null_selector():
    policy = ScopePolicy('legacy', (ScopeDomain(IntentSlot('hops', ('path', 'max_hops')), (1, 2)),))
    serialized = json.loads(json.dumps(policy.to_dict()))
    assert 'where_selector' not in serialized['domains'][0]
    assert ScopePolicy.from_dict(serialized) == policy
    with pytest.raises(ValueError, match='WHERE locator'):
        replace(policy.domains[0], where_selector={'property': 'id', 'operators': ['eq']})


def tiny_data():
    # Equal-valued parallel transfers, boundary times, a cycle, a non-increasing
    # continuation and a second sender owned by the same company are deliberate.
    values = [('1', '2', '10', LOW), ('1', '2', '10', LOW),
              ('2', '3', '7', MID), ('2', '1', '9', MID),
              ('1', '3', '5', HIGH), ('1', '4', '2', MID),
              ('4', '3', '4', LOW), ('9', '2', '3', MID)]
    transfers = tuple(Transfer(a, b, Decimal(v), t, str(i)) for i, (a, b, v, t) in enumerate(values))
    outgoing = defaultdict(list)
    for transfer in transfers:
        outgoing[transfer.from_id].append(transfer)
    accounts = {a: {'isBlocked': 'true' if a in ('2', '3') else 'false'} for a in ('1', '2', '3', '4', '9')}
    return FinBenchQueryData({}, accounts, {'C': {}}, {}, {}, {'2': 'C', '3': 'C'}, {},
                            transfers, dict(outgoing), LOW, HIGH)


def query_for(template, *, blocked=True, inclusive=True, aggregation='sum'):
    value = json.loads(family(template)[0].candidates[0].query_json)
    value['where'][1]['right']['value'] = blocked
    if value['path']:
        value['path']['max_hops'] = 2
        value['path']['time'].update(lower_inclusive=inclusive, upper_inclusive=inclusive)
    else:
        value['where'][2]['op'] = 'ge' if inclusive else 'gt'
        value['where'][3]['op'] = 'le' if inclusive else 'lt'
        value['select']['total']['aggregate'] = aggregation
    return value


def test_csv_reference_path_deduplicates_endpoints_and_enforces_time_and_acyclicity():
    query = query_for(TEMPLATES[0])
    assert reference_rows(tiny_data(), TEMPLATES[0], query) == [
        {'account_id': '2', 'distance': 1}, {'account_id': '3', 'distance': 1},
        {'account_id': '3', 'distance': 2}]
    query['path']['max_hops'] = 1
    assert len(reference_rows(tiny_data(), TEMPLATES[0], query)) == 2
    assert reference_rows(tiny_data(), TEMPLATES[0], query_for(TEMPLATES[0], inclusive=False)) == []
    assert reference_rows(tiny_data(), TEMPLATES[0], query_for(TEMPLATES[0], blocked=False)) == [
        {'account_id': '4', 'distance': 1}]


@pytest.mark.parametrize('template,expected', [
    (TEMPLATES[1], [{'account_id': '2', 'total': '20'}, {'account_id': '3', 'total': '5'}]),
    (TEMPLATES[2], [{'account_id': '2', 'total': '23'}, {'account_id': '3', 'total': '16'}]),
])
def test_csv_reference_aggregates_keep_parallel_edges_and_distinguish_ownership(template, expected):
    assert reference_rows(tiny_data(), template, query_for(template)) == expected
    counted = reference_rows(tiny_data(), template, query_for(template, aggregation='count'))
    assert counted == ([{'account_id': '2', 'total': '2'}, {'account_id': '3', 'total': '1'}]
                       if template == TEMPLATES[1] else
                       [{'account_id': '2', 'total': '3'}, {'account_id': '3', 'total': '3'}])
    assert reference_rows(tiny_data(), template, query_for(template, inclusive=False)) == (
        [] if template == TEMPLATES[1] else
        [{'account_id': '2', 'total': '3'}, {'account_id': '3', 'total': '7'}])
    assert reference_rows(tiny_data(), template, query_for(template, blocked=False)) == (
        [{'account_id': '4', 'total': '2'}] if template == TEMPLATES[1] else [])


@pytest.mark.parametrize('template', TEMPLATES)
def test_every_new_intent_matches_independent_reference_on_portable_rdf(template):
    from release_chapter7_shapes_native import reference_data
    from test_compact_lowering import execute
    from xgap.experiments.bounded_joint_toy import load_inputs
    from xgap.experiments.row_normalization import normalize_rows
    data, graphs = load_inputs()
    inputs = data['schema'], data['catalog'], data['bindings'], data['mapping'], graphs
    raw = reference_data()
    family, _, _, normalization = make_family(template, '1', raw.minimum_transfer_time,
                                              raw.maximum_transfer_time, 'tiny')
    for candidate in family.candidates:
        query = json.loads(candidate.query_json)
        actual, _, _ = execute(query, inputs, version='v2')
        assert normalize_rows(actual, normalization) == normalize_rows(reference_rows(raw, template, query), normalization)
