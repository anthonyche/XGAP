"""Public metadata retains typed resource identity and literal contents."""
from dataclasses import asdict
import rdflib

from prepare_chapter7_public_metadata import metadata_lines, label, RDF, RDFS, OWL
from xgap.compilers.rdf_encoding import RdfEdgeEncoding


def test_existing_aliases_survive_without_turning_edge_kinds_into_predicates():
    ns = 'https://example.org/schema/'
    terms = {'Account': dict(kind='class', representation=ns+'Account'),
             'TRANSFERRED_TO': dict(kind='relation', representation=ns+'TRANSFERRED_TO'),
             'id': dict(kind='property', representation=ns+'sourceId')}
    mapping = dict(resource_namespace='https://example.org/resource/',
        backend_mapping=dict(term_mappings={'fuseki': terms}, backends={'fuseki': {'namespace': ns}}),
        rdf_edge_encoding=asdict(RdfEdgeEncoding('test', ns+'Edge', ns+'source', ns+'target', ns+'edgeLabel')))
    catalog = {'entries': [dict(candidate_id='e', canonical_label='account 7', aliases=['7', '七']),
                           dict(candidate_id='r', canonical_label='TRANSFERRED_TO', aliases=['sent']),
                           dict(candidate_id='s', canonical_label='true', aliases=[])]}
    bindings = {'e': dict(kind='entity', value='account_37', identity_property='xgap_id'),
                'r': dict(kind='predicate', value='TRANSFERRED_TO'), 's': dict(kind='scalar', value=True)}
    lines = list(metadata_lines(catalog, bindings, mapping))
    assert len(lines) == len(set(lines))
    graph = rdflib.Graph().parse(data=''.join(lines), format='nt')
    uri = rdflib.URIRef
    assert (uri(ns+'TRANSFERRED_TO'), uri(RDF+'type'), uri(ns+'EdgeKind')) in graph
    assert (uri(ns+'TRANSFERRED_TO'), uri(RDF+'type'), uri(RDF+'Property')) not in graph
    assert (uri(ns+'source'), uri(RDF+'type'), uri(RDF+'Property')) in graph
    assert (uri(ns+'Account'), uri(RDF+'type'), uri(OWL+'Class')) in graph
    assert (uri('https://example.org/resource/account_37'), uri(RDFS+'label'), rdflib.Literal('七', lang='en')) in graph
    assert not any(str(s).endswith('True') for s in graph.subjects())


def test_rdf_labels_preserve_controls_quotes_and_literal_backslashes():
    value = 'literal \\b \\f path, actual \b\f\n\r\t and "quote"'
    graph = rdflib.Graph().parse(data='<https://a> <https://p> '+label(value)+' .', format='nt')
    assert str(next(graph.objects())) == value
