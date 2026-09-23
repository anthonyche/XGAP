"""Cypher Match wire projection; canonical binding normalization is unchanged."""
import hashlib
from xgap.compilers.cypher import _cypher_identifier
from xgap.compilers.directed import _identifier_safe


def identity_projection(variable, identity_property, profile):
    if identity_property is None:
        return variable  # Direct legacy callers may require the whole native object.
    if not isinstance(identity_property, str) or not identity_property.strip():
        raise ValueError('Match identity projection requires a nonblank property name')
    _identifier_safe(identity_property, profile)
    return variable + '{.' + _cypher_identifier(identity_property) + '}'


def binding_checkpoint(text,base,variables):
    """Compiler-owned insertion point before the innermost DISTINCT barrier."""
    prefix='CALL {\n'
    before,separator,_=base.rpartition('\nRETURN DISTINCT ')
    if not separator or not text.startswith(prefix+base+'\n}'):
        raise ValueError('Unknown native Match construction')
    return dict(profile='typed-match-before-distinct-v1',offset=len(prefix)+len(before)+1,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),variables=dict(variables))


def rdf_binding_checkpoint(text,base,variables):
    """Bind inside the innermost generated BGP, before subquery projection."""
    prefix,separator,_=text.partition('WHERE { {\n')
    head,where,_=base.partition(' WHERE {')
    if not separator or not where or not text.startswith(prefix+separator+base+'\n}'):
        raise ValueError('Unknown RDF Match construction')
    return dict(profile='typed-match-inner-values-v1',offset=len(prefix)+len(separator)+len(head)+len(where),
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),variables=dict(variables))
