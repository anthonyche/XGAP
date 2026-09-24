"""Constant node type lookup preserves explicit-domain and row semantics."""
import json

import pytest

from test_anchor_reduction import tiny, PREFIX, NS
from xgap.compilers.node_match import compile_node_match
from xgap.pattern.ast import NodePattern
from xgap.runtime.scalars import stable_text


@pytest.mark.parametrize('label',('Person',None))
def test_domain_access_matches_original_variable_type_query(label):
    _,_,backends,graphs,_,_,_=tiny()
    backend=backends['rdf_a'];graph=graphs['rdf_a'];graph.remove((None,None,None))
    graph.parse(data=PREFIX+'''t:a a t:Person; t:age "keep", "drop".
        t:b a t:Person, t:Outside; t:age 2.
        t:c a t:Person. t:d a t:Outside; t:age "exclude".
        t:e a t:Edge; t:age "exclude edge".''',format='turtle')
    artifact=compile_node_match(NodePattern(label=label),{'age':'age'},backend_id='rdf_a',
        backend_mapping=backend.backend_mapping,rdf_node_classes=backend.rdf_node_classes,profile=backend.profile)
    domain=' '.join('<'+iri+'>' for iri in backend.rdf_node_classes)
    original=artifact.text.replace('?n0 a <'+NS+'Person> .',
        '?n0 a ?nodeDomain . VALUES ?nodeDomain { '+domain+' }',1)
    def rows(text):
        return sorted(stable_text(r) for r in json.loads(graph.query(text).serialize(format='json'))['results']['bindings'])
    assert rows(artifact.text)==rows(original)
    assert len(rows(artifact.text))==4
    assert ('?nodeDomain' not in artifact.text)==(label is not None)
    checkpoint=artifact.parameters['rdf_binding_checkpoint']
    assert artifact.text[checkpoint['offset']:].startswith('\n?n0 a ')


def test_label_outside_domain_still_requires_domain_membership():
    _,_,backends,graphs,_,_,_=tiny()
    backend=backends['rdf_a'];graph=graphs['rdf_a'];graph.remove((None,None,None))
    graph.parse(data=PREFIX+'''t:a a t:Person, t:Outside.
        t:b a t:Person. t:c a t:Outside.''',format='turtle')
    # Same logical label mapping, a deliberately different admitted RDF domain.
    artifact=compile_node_match(NodePattern(label='Person'),{},backend_id='rdf_a',
        backend_mapping=backend.backend_mapping,rdf_node_classes=(NS+'Outside',),profile=backend.profile)
    assert '?nodeDomain' in artifact.text
    assert [str(r.entity) for r in graph.query(artifact.text)]==[NS+'a']
