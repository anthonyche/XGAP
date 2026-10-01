"""Construct a finite scope from proposals and public, frozen coordinate domains."""
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from itertools import product
import json
import math

from xgap.agent.intent_certificate import IntentCandidate, IntentFamily, IntentSlot, canonical, fingerprint, MAX_FAMILY_CANDIDATES
from xgap.semantic.compact_query import validate_query


@dataclass(frozen=True)
class ScopeDomain:
    slot: IntentSlot
    values: tuple
    where_selector: dict | None = None
    edge_selector: dict | None = None

    def __post_init__(self):
        if not isinstance(self.values, tuple) or not 1 <= len(self.values) <= MAX_FAMILY_CANDIDATES:
            raise ValueError('Finite nonempty coordinate domain required')
        encoded = [canonical(v) for v in self.values]
        if len(set(encoded)) != len(encoded) or any(len(v.encode()) > 65536 for v in encoded):
            raise ValueError('Coordinate values must be distinct and bounded')
        if self.where_selector is not None:
            selector=self.where_selector
            if (not isinstance(selector,dict) or set(selector)!={'property','operators'} or
                    not isinstance(selector['property'],str) or not selector['property'] or
                    not isinstance(selector['operators'],list) or not selector['operators'] or
                    not all(isinstance(op,str) for op in selector['operators']) or
                    len(set(selector['operators']))!=len(selector['operators']) or
                    not set(selector['operators'])<={'eq','ne','lt','le','gt','ge'} or
                    len(self.slot.path)<3 or self.slot.path[0]!='where' or
                    type(self.slot.path[1]) is not int or self.slot.path[2:] not in (('op',),('right','value'))):
                raise ValueError('WHERE locator requires a property/operator selector and scalar or operator coordinate')
        if self.edge_selector is not None:
            selector = self.edge_selector
            if (self.where_selector is not None or not isinstance(selector, dict)
                    or set(selector) != {'types'} or not isinstance(selector['types'], list)
                    or not selector['types'] or not all(isinstance(v, str) and v for v in selector['types'])
                    or len(set(selector['types'])) != len(selector['types'])
                    or not all(isinstance(v, str) and v for v in self.values)
                    or set(selector['types']) != set(self.values)
                    or len(self.slot.path) != 3 or self.slot.path[0] != 'edges'
                    or type(self.slot.path[1]) is not int or self.slot.path[1] < 0
                    or self.slot.path[2] != 'type'):
                raise ValueError('Edge locator requires exactly its frozen type domain and an edge type coordinate')


@dataclass(frozen=True)
class ScopePolicy:
    policy_id: str
    domains: tuple[ScopeDomain, ...]
    max_candidates: int = 64
    language_version: str = 'v1'
    expansion: str = 'cartesian'

    def __post_init__(self):
        if not self.policy_id or not isinstance(self.domains, tuple) or len(self.domains) > 32:
            raise ValueError('Named bounded scope policy required')
        if type(self.max_candidates) is not int or not 1 <= self.max_candidates <= MAX_FAMILY_CANDIDATES:
            raise ValueError('Candidate limit must be 1..1024')
        if self.expansion not in ('cartesian', 'proposals_only'):
            raise ValueError('Unknown finite scope construction policy')
        if self.expansion == 'cartesian' and math.prod(len(d.values) for d in self.domains) > self.max_candidates:
            raise ValueError('Scope product exceeds budget before candidate construction')
        paths = [d.slot.path for d in self.domains]
        if len({d.slot.name for d in self.domains}) != len(paths) or any(
            p[:len(q)] == q or q[:len(p)] == p for i, p in enumerate(paths) for q in paths[:i]):
            raise ValueError('Scope coordinate names/paths must be distinct and nonoverlapping')

    def to_dict(self):
        result={'schema_version': 'xgap-finite-scope-policy-v1', **asdict(self)}
        for item in result['domains']:
            if item['where_selector'] is None:del item['where_selector']
            if item['edge_selector'] is None:del item['edge_selector']
        return result

    @classmethod
    def from_dict(cls, value):
        required = {'schema_version','policy_id','domains','max_candidates','language_version'}
        if (not isinstance(value, dict) or not required <= set(value) or set(value)-required-{'expansion'}
                or value['schema_version'] != 'xgap-finite-scope-policy-v1'):
            raise ValueError('Invalid frozen scope policy')
        domains=[]
        for item in value['domains']:
            if set(item)-{'where_selector','edge_selector'} != {'slot','values'} or set(item['slot']) != {'name','path','weight','hard'}:
                raise ValueError('Invalid scope coordinate')
            slot=dict(item['slot']);slot['path']=tuple(slot['path'])
            domains.append(ScopeDomain(IntentSlot(**slot),tuple(item['values']),item.get('where_selector'),item.get('edge_selector')))
        return cls(value['policy_id'],tuple(domains),value['max_candidates'],value['language_version'],
                   value.get('expansion','cartesian'))


def upgrade_edge_type_domains(policy):
    """Opt-in migration using public frozen domains only; never reads a proposal.

    Old artifacts retain their positional behavior unless a new run explicitly
    uses this returned policy. The selector's unique role is checked against
    each actual proposal by construct_scope, before expanding any coordinates.
    """
    domains = []
    changed = False
    for domain in policy.domains:
        path = domain.slot.path
        if len(path) == 3 and path[0] == 'edges' and path[2] == 'type' and domain.edge_selector is None:
            domain = replace(domain, edge_selector={'types': list(domain.values)})
            changed = True
        domains.append(domain)
    return replace(policy, policy_id=policy.policy_id+':edge-type-domain-v1', domains=tuple(domains)) if changed else policy


def construct_scope(proposals, policy, source_snapshot):
    """No oracle read, backend call or gold row; no truncation of a large product."""
    if not isinstance(proposals, (list, tuple)) or not 1 <= len(proposals) <= 8:
        raise ValueError('One to eight compact proposals required')
    combinations = math.prod(len(d.values) for d in policy.domains) if policy.expansion == 'cartesian' else 1
    if combinations * len(proposals) > policy.max_candidates:
        raise ValueError('Proposal/domain product exceeds budget before construction')
    queries = {};resolved_domains=None
    for proposal in proposals:
        if len(canonical(proposal).encode()) > 65536:
            raise ValueError('Compact proposal exceeds byte bound')
        base = validate_query(deepcopy(proposal), version=policy.language_version)
        domains=[]
        for domain in policy.domains:
            if domain.where_selector is not None:
                selector=domain.where_selector
                matches=[i for i,c in enumerate(base['where']) if
                    c['left']['property']==selector['property'] and c['op'] in selector['operators'] and
                    set(c['right'])=={'value'}]
                if len(matches)!=1:raise ValueError('WHERE scope locator needs exactly one proposed predicate')
                domain=replace(domain,slot=replace(domain.slot,path=('where',matches[0],*domain.slot.path[2:])))
            if domain.edge_selector is not None:
                matches = [i for i, edge in enumerate(base['edges']) if edge['type'] in domain.edge_selector['types']]
                if len(matches) != 1:
                    raise ValueError('Edge scope locator needs exactly one proposed edge in its frozen type domain')
                domain = replace(domain, slot=replace(domain.slot, path=('edges', matches[0], 'type')))
            domains.append(domain)
        domains=tuple(domains)
        if resolved_domains is not None and domains!=resolved_domains:
            raise ValueError('Proposals disagree on coordinate locations')
        resolved_domains=domains
        # Recheck nonoverlap after resolution, before any candidate expansion.
        ScopePolicy(policy.policy_id,domains,policy.max_candidates,policy.language_version,policy.expansion)
        if policy.expansion == 'proposals_only':
            for domain in domains:
                value = base
                for key in domain.slot.path:
                    value = value[key]
                if canonical(value) not in {canonical(v) for v in domain.values}:
                    raise ValueError('Proposed coordinate is outside its frozen domain')
            queries[canonical(base)] = base
            continue
        for values in product(*(domain.values for domain in domains)):
            query = deepcopy(base)
            for domain, value in zip(domains, values):
                parent = query
                for key in domain.slot.path[:-1]:
                    parent = parent[key]
                if isinstance(parent, dict) and domain.slot.path[-1] not in parent:
                    raise ValueError('Scope path is outside the proposed query')
                parent[domain.slot.path[-1]] = deepcopy(value)
            valid = validate_query(query, version=policy.language_version)
            queries[canonical(valid)] = valid
    def values_at(path):
        for query in queries.values():
            value = query
            for key in path:
                value = value[key]
            yield canonical(value)
    # Constant coordinates are fixed skeleton fields, not metric dilution.
    slots = tuple(d.slot for d in resolved_domains if len(set(values_at(d.slot.path))) > 1)
    candidates = tuple(IntentCandidate.create(fingerprint(q), q) for q in queries.values())
    return IntentFamily(policy.policy_id, candidates, slots, source_snapshot,
                        coverage_basis=None, language_version=policy.language_version)
