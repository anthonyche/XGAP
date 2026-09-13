"""Cypher Match wire projection; canonical binding normalization is unchanged."""
from xgap.compilers.cypher import _cypher_identifier
from xgap.compilers.directed import _identifier_safe


def identity_projection(variable, identity_property, profile):
    if identity_property is None:
        return variable  # Direct legacy callers may require the whole native object.
    if not isinstance(identity_property, str) or not identity_property.strip():
        raise ValueError('Match identity projection requires a nonblank property name')
    _identifier_safe(identity_property, profile)
    return variable + '{.' + _cypher_identifier(identity_property) + '}'
