"""Deterministic intent discrepancy on a host-declared finite query family.

This is not an answer-error bound, a query-equivalence solver, or a guarantee
that model top-K covers the user's intent. Coverage is a separate host premise.
Immutable JSON and exact rational arithmetic keep cached certificates scoped.
"""
from dataclasses import asdict, dataclass
from copy import deepcopy
from fractions import Fraction
from functools import cached_property
import hashlib
import json
import re

from xgap.semantic.compact_query import validate_query

MAX_FAMILY_CANDIDATES = 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def rational(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, Fraction)):
        raise ValueError('Use an integer, fraction or decimal string, never a floating-point threshold')
    if isinstance(value, str) and (len(value) > 128 or not re.fullmatch(r'[0-9]+(?:/[1-9][0-9]*|\.[0-9]+)?', value)):
        raise ValueError('Threshold encoding is bounded; use a plain decimal or fraction without exponents')
    if isinstance(value, Fraction) and max(value.numerator.bit_length(), value.denominator.bit_length()) > 512:
        raise ValueError('Threshold fraction exceeds the bit bound')
    number = Fraction(value)
    if not 0 <= number <= 1:
        raise ValueError('Epsilon must lie in [0,1]')
    return number


def fraction_view(value):
    return None if value is None else {'numerator': value.numerator, 'denominator': value.denominator}


@dataclass(frozen=True)
class IntentSlot:
    name: str
    path: tuple
    weight: int = 1
    hard: bool = False

    def __post_init__(self):
        if (not self.name or not isinstance(self.path, tuple) or not self.path or
                any(type(p) not in (int, str) or isinstance(p, int) and p < 0 for p in self.path) or
                type(self.weight) is not int or not 1 <= self.weight <= 1000000 or type(self.hard) is not bool):
            raise ValueError('A slot needs a fixed JSON path, positive bounded integer weight and hard flag')


@dataclass(frozen=True)
class IntentCandidate:
    candidate_id: str
    query_json: str

    @classmethod
    def create(cls, candidate_id, query):
        return cls(candidate_id, canonical(query))


@dataclass(frozen=True)
class IntentFamily:
    """Trusted host input, not a model response schema.

    Every varying query field must occur in one declared, nonoverlapping slot.
    Fixed fields are hard invariants. No alpha-renaming/graph-isomorphism search
    occurs: slot paths and variable roles are frozen by this restricted language.
    """
    family_id: str
    candidates: tuple[IntentCandidate, ...]
    slots: tuple[IntentSlot, ...]
    source_snapshot: str
    coverage_basis: str | None = None
    language_version: str = 'v1'

    def __post_init__(self):
        if (not self.family_id or not self.source_snapshot or not isinstance(self.candidates, tuple) or
                not isinstance(self.slots, tuple) or not 1 <= len(self.candidates) <= MAX_FAMILY_CANDIDATES or not 0 <= len(self.slots) <= 32):
            raise ValueError('Finite family requires 1..1024 candidates, 0..32 slots and a source snapshot')
        if len({c.candidate_id for c in self.candidates}) != len(self.candidates) or any(not c.candidate_id for c in self.candidates):
            raise ValueError('Candidate identities must be distinct')
        if len({s.name for s in self.slots}) != len(self.slots):
            raise ValueError('Slot identities must be distinct')
        for i, slot in enumerate(self.slots):
            if any(slot.path[:len(other.path)] == other.path or other.path[:len(slot.path)] == slot.path
                   for other in self.slots[:i]):
                raise ValueError('Slot paths must not overlap')
        shells, signatures = [], []
        for candidate in self.candidates:
            if len(candidate.query_json.encode()) > 65536:
                raise ValueError('Candidate exceeds the compact byte limit')
            query = validate_query(json.loads(candidate.query_json), version=self.language_version)
            if canonical(query) != candidate.query_json:
                raise ValueError('Candidates require canonical immutable JSON')
            values = []
            for slot in self.slots:
                parent = query
                for key in slot.path[:-1]:
                    parent = parent[key]
                values.append(canonical(parent[slot.path[-1]]))
                parent[slot.path[-1]] = {'$intent_slot': slot.name}
            shells.append(canonical(query)); signatures.append(tuple(values))
        if len(set(shells)) != 1:
            raise ValueError('Query differences outside declared slots violate the hard family skeleton')
        if len(set(signatures)) != len(signatures):
            raise ValueError('Distinct candidates must have distinct complete slot signatures')
        if any(len({v[j] for v in signatures}) < 2 for j in range(len(self.slots))):
            raise ValueError('Do not dilute the metric with constant slots; fixed fields belong to the skeleton')
        if self.coverage_basis is not None and (not isinstance(self.coverage_basis, str) or not self.coverage_basis.strip()):
            raise ValueError('Coverage requires an explicit external host premise')
        object.__setattr__(self, 'values', tuple(signatures))

    @cached_property
    def identity(self):
        return fingerprint([self.family_id, [(c.candidate_id, c.query_json) for c in self.candidates],
            [(s.name, s.path, s.weight, s.hard) for s in self.slots], self.source_snapshot,
            self.coverage_basis, self.language_version])

    @cached_property
    def distances(self):
        # None denotes +infinity for a hard mismatch, not an unknown small risk.
        total = sum(s.weight for s in self.slots if not s.hard) or 1
        def distance(a, b):
            if any(s.hard and a[j] != b[j] for j, s in enumerate(self.slots)):
                return None
            return Fraction(sum(s.weight for j, s in enumerate(self.slots) if not s.hard and a[j] != b[j]), total)
        return tuple(tuple(distance(a, b) for b in self.values) for a in self.values)

    def worst_distance(self, candidate_index, remaining):
        """Exact maximum without retaining an N-by-N Fraction matrix.

        O(N*u) time and O(u) auxiliary space for one candidate. Fixed skeleton,
        positive coordinate weights and hard-mismatch infinity are unchanged.
        The historical ``distances`` property remains for legacy evidence only.
        """
        a=self.values[candidate_index]
        hard=tuple(j for j,s in enumerate(self.slots) if s.hard)
        soft=tuple((j,s.weight) for j,s in enumerate(self.slots) if not s.hard)
        maximum=0;seen=False
        for i in remaining:
            seen=True;b=self.values[i]
            if any(a[j]!=b[j] for j in hard):return None
            maximum=max(maximum,sum(w for j,w in soft if a[j]!=b[j]))
        if not seen:raise ValueError('Empty intent set has no discrepancy certificate')
        return Fraction(maximum,sum(w for _,w in soft) or 1)

    def consistent(self, observations=()):
        if len(observations) > len(self.slots) or len({i for i, _ in observations}) != len(observations):
            raise ValueError('A slot may be observed once')
        if any(type(i) is not int or not 0 <= i < len(self.slots) or not isinstance(v, str) for i, v in observations):
            raise ValueError('Invalid observation scope')
        remaining = tuple(i for i, values in enumerate(self.values) if all(values[j] == v for j, v in observations))
        if not remaining:
            raise ValueError('Authoritative outcome contradicts the declared closed family; no certificate')
        return remaining

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, raw):
        if set(raw) != {'family_id','candidates','slots','source_snapshot','coverage_basis','language_version'}:
            raise ValueError('Unknown finite-family fields')
        return cls(raw['family_id'], tuple(IntentCandidate(**c) for c in raw['candidates']),
            tuple(IntentSlot(**{**s,'path':tuple(s['path'])}) for s in raw['slots']),
            raw['source_snapshot'],raw['coverage_basis'],raw['language_version'])


class TerminalContract:
    """Same checker for ExactTerminal (epsilon=0) and BoundedTerminal."""
    def __init__(self, family, *, mode='exact', epsilon='0'):
        if mode not in ('exact', 'performance'):
            raise ValueError('Unknown terminal mode')
        self.family, self.mode, self.epsilon = family, mode, rational(epsilon)
        if mode == 'exact' and self.epsilon:
            raise ValueError('ExactTerminal requires epsilon=0')
        self.cache = {}; self.checks = self.cache_hits = 0

    def check(self, candidate_index, observations=()):
        if type(candidate_index) is not int or not 0 <= candidate_index < len(self.family.candidates):
            raise ValueError('Invalid candidate index')
        self.checks += 1
        key = (candidate_index, tuple(sorted(observations)), self.family.identity, self.mode, self.epsilon)
        if key in self.cache:
            self.cache_hits += 1
            return deepcopy(self.cache[key])
        family = self.family; remaining = family.consistent(observations)
        if candidate_index not in remaining:
            raise ValueError('A terminal cannot contradict already acquired authoritative observations')
        bound = None; status = 'unknown_coverage'
        if family.coverage_basis is not None:
            distances = [family.distances[candidate_index][i] for i in remaining]
            if any(d is None for d in distances):
                status = 'unresolved_hard_constraint'
            else:
                bound = max(distances)
                status = 'certified' if bound <= self.epsilon else 'above_epsilon'
        result = dict(status=status, eligible=status == 'certified', mode=self.mode,
            candidate_id=family.candidates[candidate_index].candidate_id,
            upper_bound=fraction_view(bound), epsilon=fraction_view(self.epsilon),
            family_sha256=family.identity, source_snapshot=family.source_snapshot,
            state_sha256=fingerprint(key[1]), coverage_basis=family.coverage_basis,
            remaining_intents=len(remaining), scope='structured intent, not answer error')
        # At most (m+1)*K entries in the realized controller; standalone callers
        # also have a hard memory cap. Eviction changes cost, never semantics.
        if len(self.cache) >= 4096:
            self.cache.clear()
        self.cache[key] = result
        return deepcopy(result)
