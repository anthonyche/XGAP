"""Validation obligations are independent of finite-family interpretation loss.

Inputs are trusted host declarations and checked tool observations, never model
attestations. This first profile admits direct authority only; unsupported
inference rules do not silently turn singleton candidates into validations.
"""
from dataclasses import asdict, dataclass
import json
import time
from copy import deepcopy

from xgap.agent.intent_certificate import canonical, fingerprint, fraction_view, rational


@dataclass(frozen=True)
class ValidationRequirement:
    name: str
    path: tuple
    source: str
    version: str

    def __post_init__(self):
        if (not all(isinstance(x, str) and x for x in (self.name, self.source, self.version))
                or not isinstance(self.path, tuple) or not self.path
                or any(type(x) not in (str, int) or isinstance(x, int) and x < 0 for x in self.path)):
            raise ValueError('Validation requires a named, versioned authority and query path')


@dataclass(frozen=True)
class ValidatedBinding:
    name: str
    value_json: str
    source: str
    version: str
    observation_id: str

    def __post_init__(self):
        if (not all(isinstance(x, str) and x for x in
                    (self.name, self.source, self.version, self.observation_id))
                or not isinstance(self.value_json, str) or len(self.value_json.encode()) > 65536
                or canonical(json.loads(self.value_json)) != self.value_json):
            raise ValueError('Validation requires canonical bounded content and observation provenance')


class UnifiedTerminalContract:
    def __init__(self, family, requirements, *, relaxable=(), epsilon='0'):
        self.family = family
        self.requirements = tuple(requirements)
        self.relaxable = frozenset(relaxable)
        self.epsilon = rational(epsilon)
        names = [r.name for r in self.requirements]
        if (len(names) > 64 or len(set(names)) != len(names)
                or not self.relaxable <= set(names)):
            raise ValueError('Distinct bounded requirements and declared Lambda required')
        self.by_name = {r.name: r for r in self.requirements}
        def read(query, path):
            for key in path:
                query = query[key]
            return canonical(query)
        self.values = tuple({r.name: read(json.loads(c.query_json), r.path)
                             for r in self.requirements} for c in family.candidates)
        self.identity = fingerprint([family.identity, [asdict(r) for r in self.requirements],
                                     sorted(self.relaxable), fraction_view(self.epsilon)])
        self.checks = 0
        self.cache_hits = 0
        self.elapsed_ms = 0.0
        self.cache = {}

    def consistent(self, bindings=()):
        if len(bindings) > len(self.requirements) or len({b.name for b in bindings}) != len(bindings):
            raise ValueError('One checked observation per validation requirement')
        for binding in bindings:
            requirement = self.by_name.get(binding.name)
            if requirement is None or (binding.source, binding.version) != (requirement.source, requirement.version):
                raise ValueError('Unregistered or wrong-version validation authority')
        remaining = tuple(i for i, values in enumerate(self.values)
                          if all(values[b.name] == b.value_json for b in bindings))
        if not remaining:
            raise ValueError('Authorized observations contradict the complete candidate family')
        return remaining

    def check(self, candidate_index, bindings=()):
        started=time.perf_counter();self.checks+=1
        try:
            key=(candidate_index,tuple(bindings))
            if key in self.cache:
                self.cache_hits+=1
                return deepcopy(self.cache[key])
            result=self._check(candidate_index,bindings)
            if len(self.cache)>=1024:self.cache.pop(next(iter(self.cache)))
            self.cache[key]=deepcopy(result)
            return result
        finally:
            self.elapsed_ms+=(time.perf_counter()-started)*1000

    def _check(self, candidate_index, bindings=()):
        remaining = self.consistent(bindings)
        if type(candidate_index) is not int or candidate_index not in remaining:
            raise ValueError('Selected query is inconsistent with actual validation evidence')
        missing = sorted(set(self.by_name) - self.relaxable - {b.name for b in bindings})
        # Orientation is d(intended, selected), including for future asymmetric losses.
        distances = [self.family.distances[i][candidate_index] for i in remaining]
        bound = None if any(d is None for d in distances) else max(distances)
        if self.family.coverage_basis is None:
            status = 'unknown_coverage'
        elif missing:
            status = 'mandatory_validation_missing'
        elif bound is None:
            status = 'unresolved_hard_constraint'
        else:
            status = 'certified' if bound <= self.epsilon else 'above_epsilon'
        return dict(schema_version='xgap-unified-terminal-v1', eligible=status == 'certified',
            status=status, candidate_id=self.family.candidates[candidate_index].candidate_id,
            family_sha256=self.family.identity, contract_sha256=self.identity,
            source_snapshot=self.family.source_snapshot, remaining_intents=len(remaining),
            missing_validations=missing, validated=sorted(b.name for b in bindings),
            relaxable=sorted(self.relaxable), epsilon=fraction_view(self.epsilon),
            upper_bound=fraction_view(bound), scope='interpretation loss; not result-set error')
