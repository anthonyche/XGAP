"""Bounded representation equality, not arbitrary query equivalence.

Structural roles color declarations before alpha-renaming. The final complete
renamed AST must still match exactly: colors alone never establish equivalence.
Unresolved color ties retain declaration order (possible false negatives). This
does not rewrite the stored AST/slot coordinates or search permutations. At most
V refinement rounds on V declarations and E references: polynomial bounded work.
"""
from copy import deepcopy
import json

from xgap.semantic.compact_query import validate_query


IDENTITY_VERSION = 'xgap-compact-representation-identity-v3'


def _role_order(value):
    """Resolve ordinary declaration permutations; no semantic query rewrites."""
    encode = lambda x: json.dumps(x, sort_keys=True, separators=(',', ':'), allow_nan=False)
    groups = [('node', value['nodes']), ('edge', value['edges']),
              ('path', [value['path']] if value['path'] else [])]
    features, links = {}, {}
    for kind, declarations in groups:
        for declaration in declarations:
            name = declaration['var']
            features[name] = [[kind, {k:v for k,v in declaration.items() if k not in ('var','source','target')}]]
            links[name] = []

    def connect(left, right, label):
        links[left].append((['out', label], right))
        links[right].append((['in', label], left))

    for _, declarations in groups[1:]:
        for declaration in declarations:
            for role in ('source', 'target'):
                connect(declaration['var'], declaration[role], role)
    for alias, expression in value['select'].items():
        ref = expression.get('field') if 'aggregate' in expression else expression
        if ref is not None:
            features[ref['var']].append(['select', alias, ref['property'],
                {k:v for k,v in expression.items() if k not in ('var','property','field')}])
    for predicate in value['where']:
        left, right = predicate['left'], predicate['right']
        spec = [left['property'], predicate['op'], predicate['value_type']]
        if 'var' in right:
            if predicate['op'] in ('eq', 'ne'):
                # Equality is undirected, but the property belongs to its own
                # endpoint. Normalize roles before alpha colors: sorting raw
                # variable names here would make equality spelling-dependent.
                for a, b in ((left, right), (right, left)):
                    links[a['var']].append((['symmetric_predicate', predicate['op'],
                        predicate['value_type'], a['property'], b['property']], b['var']))
            else:
                connect(left['var'], right['var'], ['predicate', spec, right['property']])
        else:
            features[left['var']].append(['predicate', spec, right])
    grain = value.get('contribution_by', value.get('deduplicate_by'))
    for name in grain or []:
        # A distinct tuple's key order changes neither its equivalence classes
        # nor aggregate groups; output order remains separately explicit.
        features[name].append(['contribution'])
    seeds = {name: encode(sorted(items, key=encode)) for name, items in features.items()}

    def ranks(signatures):
        labels = {value:i for i,value in enumerate(sorted(set(signatures.values())))}
        return {name:labels[value] for name,value in signatures.items()}

    colors = ranks(seeds)
    for _ in range(len(features)):
        refined = ranks({name:encode([seeds[name], colors[name], sorted(
            ([role, colors[other]] for role, other in links[name]), key=encode)]) for name in features})
        if refined == colors:
            break
        colors = refined
    for _, declarations in groups:
        declarations.sort(key=lambda d: colors[d['var']])


def representation_key(query, *, version='v1', constraints=None):
    value = deepcopy(validate_query(query, version=version))
    if constraints is not None:
        if version != 'v2':
            raise ValueError('Public compact constraints require language v2')
        from xgap.semantic.compact_constraints import canonicalize_with_constraints
        value, _ = canonicalize_with_constraints(value, constraints)
    if version == 'v2' and all('var' in e for e in value['select'].values()):
        # Same exact rule as compact-safe-equivalence-v1, applied symmetrically
        # to authority and proposal. Final set projection removes witnesses.
        value['contribution_by'] = None
    try:
        _role_order(value)
    except KeyError as error:
        raise ValueError('Undeclared compact variable reference') from error
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
            if predicate['op'] in ('eq', 'ne'):
                encoded = lambda ref: json.dumps(ref, sort_keys=True, separators=(',', ':'))
                if encoded(predicate['left']) > encoded(predicate['right']):
                    predicate['left'], predicate['right'] = predicate['right'], predicate['left']
    for expression in value['select'].values():
        if 'aggregate' in expression:
            if expression['field'] is not None:
                reference(expression['field'])
        else:
            reference(expression)
    grain = 'deduplicate_by' if version == 'v1' else 'contribution_by'
    if value[grain] is not None:
        value[grain] = sorted(renamed(name) for name in value[grain])
    encode = lambda item: json.dumps(item, sort_keys=True, separators=(',', ':'), allow_nan=False)
    value['where'].sort(key=encode)
    # Literal values, entities, output aliases/order, direction and semantics stay exact.
    result = dict(identity_version=IDENTITY_VERSION, language_version=version, query=value)
    if constraints is not None:
        result['public_constraints_sha256'] = constraints.identity
    return encode(result)


def matching_candidates(query, candidates, *, version='v1', constraints=None):
    key = representation_key(query, version=version, constraints=constraints)
    return [i for i, candidate in enumerate(candidates)
            if representation_key(json.loads(candidate.query_json), version=version, constraints=constraints) == key]
