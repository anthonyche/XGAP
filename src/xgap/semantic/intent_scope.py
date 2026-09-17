"""Construct a finite scope from proposals and public, frozen coordinate domains."""
from copy import deepcopy
from dataclasses import asdict, dataclass
from itertools import product
import json
import math

from xgap.agent.intent_certificate import IntentCandidate, IntentFamily, IntentSlot, canonical, fingerprint
from xgap.semantic.compact_query import validate_query


@dataclass(frozen=True)
class ScopeDomain:
    slot: IntentSlot
    values: tuple

    def __post_init__(self):
        if not isinstance(self.values, tuple) or not 1 <= len(self.values) <= 64:
            raise ValueError('Finite nonempty coordinate domain required')
        encoded = [canonical(v) for v in self.values]
        if len(set(encoded)) != len(encoded) or any(len(v.encode()) > 65536 for v in encoded):
            raise ValueError('Coordinate values must be distinct and bounded')


@dataclass(frozen=True)
class ScopePolicy:
    policy_id: str
    domains: tuple[ScopeDomain, ...]
    max_candidates: int = 64
    language_version: str = 'v1'

    def __post_init__(self):
        if not self.policy_id or not isinstance(self.domains, tuple) or len(self.domains) > 32:
            raise ValueError('Named bounded scope policy required')
        if type(self.max_candidates) is not int or not 1 <= self.max_candidates <= 64:
            raise ValueError('Candidate limit must be 1..64')
        if math.prod(len(d.values) for d in self.domains) > self.max_candidates:
            raise ValueError('Scope product exceeds budget before candidate construction')
        paths = [d.slot.path for d in self.domains]
        if len({d.slot.name for d in self.domains}) != len(paths) or any(
            p[:len(q)] == q or q[:len(p)] == p for i, p in enumerate(paths) for q in paths[:i]):
            raise ValueError('Scope coordinate names/paths must be distinct and nonoverlapping')

    def to_dict(self):
        return {'schema_version': 'xgap-finite-scope-policy-v1', **asdict(self)}

    @classmethod
    def from_dict(cls, value):
        if (not isinstance(value, dict) or set(value) != {'schema_version','policy_id','domains','max_candidates','language_version'}
                or value['schema_version'] != 'xgap-finite-scope-policy-v1'):
            raise ValueError('Invalid frozen scope policy')
        domains=[]
        for item in value['domains']:
            if set(item) != {'slot','values'} or set(item['slot']) != {'name','path','weight','hard'}:
                raise ValueError('Invalid scope coordinate')
            slot=dict(item['slot']);slot['path']=tuple(slot['path'])
            domains.append(ScopeDomain(IntentSlot(**slot),tuple(item['values'])))
        return cls(value['policy_id'],tuple(domains),value['max_candidates'],value['language_version'])


def construct_scope(proposals, policy, source_snapshot):
    """No oracle read, backend call or gold row; no truncation of a large product."""
    if not isinstance(proposals, (list, tuple)) or not 1 <= len(proposals) <= 8:
        raise ValueError('One to eight compact proposals required')
    combinations = math.prod(len(d.values) for d in policy.domains)
    if combinations * len(proposals) > policy.max_candidates:
        raise ValueError('Proposal/domain product exceeds budget before construction')
    queries = {}
    for proposal in proposals:
        if len(canonical(proposal).encode()) > 65536:
            raise ValueError('Compact proposal exceeds byte bound')
        base = validate_query(deepcopy(proposal), version=policy.language_version)
        for values in product(*(domain.values for domain in policy.domains)):
            query = deepcopy(base)
            for domain, value in zip(policy.domains, values):
                parent = query
                for key in domain.slot.path[:-1]:
                    parent = parent[key]
                if isinstance(parent, dict) and domain.slot.path[-1] not in parent:
                    raise ValueError('Scope path is outside the proposed query')
                parent[domain.slot.path[-1]] = deepcopy(value)
            valid = validate_query(query, version=policy.language_version)
            queries[canonical(valid)] = valid
    slots = tuple(d.slot for d in policy.domains if len(d.values) > 1)
    candidates = tuple(IntentCandidate.create(fingerprint(q), q) for q in queries.values())
    return IntentFamily(policy.policy_id, candidates, slots, source_snapshot,
                        coverage_basis=None, language_version=policy.language_version)
