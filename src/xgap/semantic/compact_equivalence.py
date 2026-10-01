"""Opt-in exact surface equivalences; never infer or repair graph meaning."""
from copy import deepcopy

from xgap.semantic.compact_query import validate_query


PROFILE = 'compact-safe-equivalence-v1'


def validate_identity_schema(schema, backends=None):
    """Require the frozen common canonical identity mapping, not an ID guess."""
    identity = schema.get('identity_property')
    namespace = schema.get('shared_identity_namespace')
    if not isinstance(identity, str) or not identity or not isinstance(namespace, str) or not namespace:
        raise ValueError('Compact identity equivalence needs a shared canonical namespace and identity property')
    if backends is not None and (not backends or any(
            b.identity_property != identity or b.resource_namespace != namespace for b in backends.values())):
        raise ValueError('Compact identity equivalence differs from the frozen backend identity mapping')
    return identity


def canonicalize_compact_surface(query, schema):
    """Return an independent equivalent v2 query and a finite rewrite ledger.

Only equality/inequality of two same-type node identity properties is translated
to canonical variable identity. Canonical encoding is a common injective mapping
of the configured identity property, so equality and inequality are preserved.
Literal tests, cross-type comparisons, order, outputs and business IDs stay exact.
For nonaggregate set-valued output, contribution projection only removes witnesses
and keeps every selected value; eliminating that redundant projection is exact.
"""
    identity = validate_identity_schema(schema)
    value = deepcopy(validate_query(query, version='v2'))
    nodes = {n['var']: n['type'] for n in value['nodes']}
    rewrites = []
    for index, predicate in enumerate(value['where']):
        left, right = predicate['left'], predicate['right']
        if (predicate['op'] in ('eq', 'ne') and predicate['value_type'] == 'scalar'
                and left.get('property') == identity and right.get('property') == identity
                and left.get('var') in nodes and right.get('var') in nodes
                and nodes[left['var']] == nodes[right['var']]):
            left['property'] = right['property'] = None
            rewrites.append(dict(rule='same_domain_identity_equality', where_index=index,
                                 operator=predicate['op']))
    if value['contribution_by'] is not None and all('var' in e for e in value['select'].values()):
        value['contribution_by'] = None
        rewrites.append(dict(rule='nonaggregate_set_projection'))
    return value, rewrites
