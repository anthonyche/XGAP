from dataclasses import replace
import json

import pytest

from test_intent_strong import clustered_family
from xgap.agent.intent_certificate import canonical
from xgap.agent.unified_contract import UnifiedTerminalContract, ValidationRequirement, ValidatedBinding


def contract(**options):
    family = clustered_family()
    requirements = tuple(ValidationRequirement(s.name, s.path, 'user', 'v1') for s in family.slots)
    return UnifiedTerminalContract(family, requirements, **options)


def binding(name, value):
    return ValidatedBinding(name, canonical(value), 'user', 'v1', 'paid-observation')


def test_single_remaining_candidate_and_zero_loss_do_not_validate_other_fields():
    strict = contract()
    observed = (binding('hops', 1),)
    assert strict.consistent(observed) == (1,)
    result = strict.check(1, observed)
    assert result['upper_bound'] == {'numerator': 0, 'denominator': 1}
    assert not result['eligible'] and len(result['missing_validations']) == 3
    relaxed = contract(relaxable=('lower_inclusive', 'upper_inclusive', 'path_semantics'))
    assert relaxed.check(1, observed)['eligible']


def test_direct_validations_filter_family_and_preserve_explicit_authority():
    c = contract()
    all_bindings = tuple(binding(r.name, json.loads(c.values[1][r.name])) for r in c.requirements)
    assert c.check(1, all_bindings)['eligible']
    for bad in (replace(all_bindings[0], source='model'), replace(all_bindings[0], version='v2')):
        with pytest.raises(ValueError, match='authority'):
            c.check(1, (bad,))
    with pytest.raises(ValueError, match='contradict'):
        c.check(1, (binding('hops', 27),))


def test_relaxation_does_not_remove_unplanned_candidates_or_hard_constraints():
    c = contract(relaxable=('hops', 'lower_inclusive', 'upper_inclusive', 'path_semantics'), epsilon='1/4')
    assert c.check(0)['eligible'] and c.check(0)['remaining_intents'] == 5
    hard = clustered_family(hard=True)
    protected = UnifiedTerminalContract(hard, c.requirements, relaxable=c.relaxable, epsilon='1')
    assert protected.check(0)['status'] == 'unresolved_hard_constraint'


def test_coverage_and_lambda_cannot_be_invented():
    c = contract()
    with pytest.raises(ValueError, match='Lambda'):
        UnifiedTerminalContract(c.family, c.requirements, relaxable=('undeclared',))
    without_coverage = UnifiedTerminalContract(replace(c.family, coverage_basis=None), c.requirements,
                                              relaxable=tuple(c.by_name), epsilon='1')
    assert without_coverage.check(0)['status'] == 'unknown_coverage'
