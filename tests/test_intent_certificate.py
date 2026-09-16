"""Exhaustive small-domain proof checks; no LLM, backend or gold in checker."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from itertools import combinations
import json

import pytest

from test_compact_lowering import financial_intents, pred
from xgap.agent.intent_certificate import (IntentCandidate, IntentFamily, IntentSlot,
    TerminalContract, fraction_view)


def family(snapshot='tiny-v1', *, hard=False, coverage='authored exhaustive two-slot toy-v1'):
    candidates = []
    for depth in (1, 2):
        for day in (1, 2):
            q = financial_intents()[1]
            q['nodes'][0]['entity'] = None
            q['where'].append(pred('start', 'id', 'eq', '1'))
            q['path']['max_hops'] = depth
            q['path']['time']['lower'] = f'2020-01-0{day} 00:00:00.000'
            candidates.append(IntentCandidate.create(f'depth{depth}-since0{day}', q))
    return IntentFamily('toy-depth-window-v1', tuple(candidates),
        (IntentSlot('depth', ('path','max_hops'), hard=hard),
         IntentSlot('since', ('path','time','lower'))), snapshot, coverage)


def test_every_truth_every_prefix_bound_and_monotonicity():
    f = family()
    for truth in range(4):
        for count in range(3):
            for slots in combinations(range(2), count):
                observations = tuple((j, f.values[truth][j]) for j in slots)
                for candidate in f.consistent(observations):
                    for eps in ('0', '0.499999999999999999999', '1/2', '1'):
                        cert = TerminalContract(f, mode='performance', epsilon=eps).check(candidate, observations)
                        bound = Fraction(**cert['upper_bound'])
                        assert f.distances[candidate][truth] <= bound
                        assert cert['eligible'] == (bound <= Fraction(eps))
                        for j in set(range(2)) - set(slots):
                            next_state = observations + ((j, f.values[truth][j]),)
                            if candidate in f.consistent(next_state):
                                after = TerminalContract(f, mode='performance', epsilon=eps).check(candidate, next_state)
                                assert Fraction(**after['upper_bound']) <= bound


def test_hard_constraints_other_support_and_zero_epsilon():
    hard = family(hard=True)
    assert TerminalContract(hard, mode='performance', epsilon='1').check(0)['status'] == 'unresolved_hard_constraint'
    unknown = TerminalContract(family(coverage=None), mode='performance', epsilon='1')
    assert unknown.check(0)['status'] == 'unknown_coverage'
    f = family()
    for observations in ((), ((0,f.values[0][0]),), ((0,f.values[0][0]),(1,f.values[0][1]))):
        a = TerminalContract(f).check(0, observations)
        b = TerminalContract(f, mode='performance').check(0, observations)
        assert (a['eligible'],a['upper_bound']) == (b['eligible'],b['upper_bound'])
    with pytest.raises(ValueError, match='contradicts'):
        f.consistent(((0,'999'),))


def test_no_hidden_difference_weight_trick_or_cache_poisoning():
    f = family(); changed = deepcopy(json.loads(f.candidates[-1].query_json))
    changed['path']['mode'] = 'WALK'
    with pytest.raises(ValueError, match='outside declared slots'):
        replace(f, candidates=(*f.candidates[:-1], IntentCandidate.create('changed',changed)))
    with pytest.raises(ValueError, match='overlap'):
        replace(f, slots=(IntentSlot('allpath',('path',)), *f.slots))
    with pytest.raises(ValueError, match='positive'):
        IntentSlot('zero',('path',),weight=0)
    with pytest.raises(ValueError, match='constant slots'):
        replace(f, slots=(*f.slots, IntentSlot('dummy',('path','min_hops'))))
    with pytest.raises(ValueError, match='floating'):
        TerminalContract(f, mode='performance', epsilon=.5)
    with pytest.raises(ValueError, match='encoding is bounded'):
        TerminalContract(f, mode='performance', epsilon='1e-1000000000')
    contract = TerminalContract(f, mode='performance', epsilon='1/2')
    state = ((0,f.values[0][0]),)
    result = contract.check(0,state); result['upper_bound']['numerator'] = 0
    assert contract.check(0,state)['upper_bound'] == fraction_view(Fraction(1,2))
    assert contract.cache_hits == 1
    assert not contract.check(0)['eligible']  # invalidates on changed prefix
    assert replace(f, source_snapshot='other').identity != f.identity
    with pytest.raises(ValueError, match='contradict'):
        contract.check(2,state)
