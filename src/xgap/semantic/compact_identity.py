"""Bounded representation equality, not arbitrary query equivalence.

Declaration positions determine alpha-renaming. Only the pure WHERE conjunction
is sorted. This neither reorders declarations nor rewrites the stored AST/slot
coordinates. For bounded query size B and P predicates: O(B + P log P) key work
(including serialized comparison keys); no graph-isomorphism search.
"""
from copy import deepcopy
import json

from xgap.semantic.compact_query import validate_query


IDENTITY_VERSION = 'xgap-compact-representation-identity-v1'


def representation_key(query, *, version='v1'):
    value = deepcopy(validate_query(query, version=version))
    names = {}
    for prefix, declarations in (('n', value['nodes']), ('e', value['edges']),
                                 ('p', [value['path']] if value['path'] else [])):
        for index, declaration in enumerate(declarations):
            names[declaration['var']] = prefix + str(index)

    def renamed(name):
        if name not in names:
            raise ValueError('Undeclared compact variable reference')
        return names[name]

    def reference(ref):
        ref['var'] = renamed(ref['var'])

    for declaration in value['nodes'] + value['edges'] + ([value['path']] if value['path'] else []):
        declaration['var'] = renamed(declaration['var'])
        if 'source' in declaration:
            declaration['source'] = renamed(declaration['source'])
            declaration['target'] = renamed(declaration['target'])
    for predicate in value['where']:
        reference(predicate['left'])
        if 'var' in predicate['right']:
            reference(predicate['right'])
    for expression in value['select'].values():
        if 'aggregate' in expression:
            if expression['field'] is not None:
                reference(expression['field'])
        else:
            reference(expression)
    grain = 'deduplicate_by' if version == 'v1' else 'contribution_by'
    if value[grain] is not None:
        value[grain] = [renamed(name) for name in value[grain]]
    encode = lambda item: json.dumps(item, sort_keys=True, separators=(',', ':'), allow_nan=False)
    value['where'].sort(key=encode)
    # Literal values, entities, output aliases/order, direction and semantics stay exact.
    return encode(dict(identity_version=IDENTITY_VERSION, language_version=version, query=value))


def matching_candidates(query, candidates, *, version='v1'):
    key = representation_key(query, version=version)
    return [i for i, candidate in enumerate(candidates)
            if representation_key(json.loads(candidate.query_json), version=version) == key]
