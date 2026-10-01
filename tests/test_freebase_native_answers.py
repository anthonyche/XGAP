"""Independent RDF execution and finite native-answer boundaries."""

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.rdf_terms import RDF_TERMS_V1, RdfTerm
from xgap.backends.sparql_bindings import IRI_VALUES_MARKER, bind_sparql_iris
from xgap.experiments.freebase_backend_loading import FactSnapshot, load_fact_snapshot
from xgap.experiments.freebase_fact_snapshot import SCHEMA
from xgap.experiments.freebase_native_answers import FactAnswerQuery, ResourceStep, answer_pairs, compile_fact_answer, execute_fact_answer
from xgap.experiments.m15_fixture_loader import BackendLoadReport
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import ExecutionReport, QueryArtifact
from xgap.pattern.ast import Direction


NS = "http://example.org/"


def parameters(values):
    return {"sparql_iri_binding": {"parameter": "ids", "variable": "entity", "max_bindings": 8,
            "max_bytes": 4096}, "ids": values}


def test_binding_only_explicit_iris_and_deduplication():
    text = f"SELECT ?entity WHERE {{ {IRI_VALUES_MARKER} }}"
    assert bind_sparql_iris(text, {}) == text
    actual = bind_sparql_iris(text, parameters([NS+'b', NS+'a', NS+'a']))
    assert actual == f"SELECT ?entity WHERE {{ VALUES ?entity {{ <{NS}a> <{NS}b> }} }}"


@pytest.mark.parametrize("values", [[None], [1], ['relative'], ['http://e/a> } UNION { ?s ?p ?o'],
                                    ['http://e/space here'], [NS+'x']*9, 'not-a-list'])
def test_bad_bindings_fail_before_transport(values):
    client = FusekiClient(BackendDescriptor('fuseki', 'fuseki', 'sparql', 'rdf'))
    client._post_query = lambda _: pytest.fail('invalid binding reached the backend')
    report = client.execute(QueryArtifact('bad', 'sparql', IRI_VALUES_MARKER, parameters=parameters(values)))
    assert not report.success and report.error


@pytest.mark.parametrize("change", ['missing-values', 'zero-limit', 'bool-limit', 'bad-variable', 'byte-budget', 'extra-field'])
def test_binding_contract_failures(change):
    params = parameters([NS+'a'])
    spec = params['sparql_iri_binding']
    if change == 'missing-values': del params['ids']
    if change == 'zero-limit': spec['max_bindings'] = 0
    if change == 'bool-limit': spec['max_bindings'] = True
    if change == 'bad-variable': spec['variable'] = 'x) }'
    if change == 'byte-budget': spec['max_bytes'] = 1
    if change == 'extra-field': spec['extra'] = True
    with pytest.raises(ValueError): bind_sparql_iris(IRI_VALUES_MARKER, params)


@pytest.mark.parametrize('text', ['SELECT * {}', IRI_VALUES_MARKER*2])
def test_binding_marker_must_be_unique(text):
    with pytest.raises(ValueError): bind_sparql_iris(text, parameters([]))


class RdfEngine(FusekiClient):
    def __init__(self, graph):
        super().__init__(BackendDescriptor('fuseki', 'fuseki', 'sparql', 'rdf'))
        self.graph = graph
        self.queries = []

    def _post_query(self, query):
        self.queries.append(query)
        return json.loads(self.graph.query(query).serialize(format='json'))


@dataclass
class ResourceClient:
    resources: list[str]
    fail: bool = False
    backend_id: str = 'neo4j'

    def execute(self, artifact):
        assert 'MATCH' in artifact.text
        return ExecutionReport('neo4j', artifact.artifact_id, 'cypher', not self.fail,
            rows=[{'entity_iri': r} for r in self.resources] if not self.fail else [],
            error='backend unavailable' if self.fail else None)


@pytest.fixture
def graph():
    rdflib = pytest.importorskip('rdflib')
    return rdflib.Graph().parse(data='''
      @prefix e: <http://example.org/> .
      e:p1 e:author e:a ; e:name "One"@en, "Uno"@es, "One alternative"@en .
      e:p2 e:author e:b ; e:name "Two"@en .
      e:a e:affiliation e:university . e:b e:affiliation e:other .
      e:string e:author "http://example.org/a" ; e:name "Decoy"@en .
      e:p1 e:year "2024"^^<http://www.w3.org/2001/XMLSchema#integer>, "2020"^^<http://www.w3.org/2001/XMLSchema#integer> .
    ''', format='turtle')


@pytest.mark.parametrize('steps,anchor', [
    ((ResourceStep(NS+'author', Direction.IN),), NS+'a'),
    ((ResourceStep(NS+'affiliation', Direction.IN), ResourceStep(NS+'author', Direction.IN)), NS+'university'),
    ((ResourceStep(NS+'author', Direction.OUT), ResourceStep(NS+'author', Direction.IN)), NS+'p1'),
])
def test_compiled_paths_and_federated_literal_answers(graph, steps, anchor):
    query = FactAnswerQuery(anchor, steps, NS+'name', 'EN')
    program = compile_fact_answer(query, max_rows=10, max_binding_bytes=4096)
    engine = RdfEngine(graph)
    result = execute_fact_answer(program, neo4j=ResourceClient([NS+'p1']), fuseki=engine)
    assert result['success'] and result['answers_equal']
    rows = result['federated']['root_rows']['answer']
    assert {r['answer']['value'] for r in rows} == {'One', 'One alternative'}
    assert all(RdfTerm.from_binding(r['entity']) == RdfTerm('uri', NS+'p1') for r in rows)
    assert len(engine.queries) == 2 and IRI_VALUES_MARKER not in engine.queries[0]
    assert f'VALUES ?entity {{ <{NS}p1> }}' in engine.queries[0]


def test_typed_multivalued_literal_projection(graph):
    program = compile_fact_answer(FactAnswerQuery(NS+'a', (ResourceStep(NS+'author', Direction.IN),), NS+'year'),
                                  max_rows=10, max_binding_bytes=4096)
    result = execute_fact_answer(program, neo4j=ResourceClient([NS+'p1']), fuseki=RdfEngine(graph))
    assert result['success']
    assert {r['answer']['datatype'] for r in result['baseline']['rows']} == {'http://www.w3.org/2001/XMLSchema#integer'}
    assert len(answer_pairs(result['baseline']['rows'])) == 2


def test_successful_empty_short_circuits_only_the_bound_call(graph):
    engine = RdfEngine(graph)
    program = compile_fact_answer(FactAnswerQuery(NS+'absent', (ResourceStep(NS+'author', Direction.IN),), NS+'name'),
                                  max_rows=10, max_binding_bytes=4096)
    result = execute_fact_answer(program, neo4j=ResourceClient([]), fuseki=engine)
    assert result['success'] and not result['baseline']['rows']
    assert len(engine.queries) == 1  # only the independent full-query baseline


@pytest.mark.parametrize('failure', ['neo4j', 'resource-overflow', 'literal-overflow', 'binding-bytes'])
def test_failure_never_becomes_a_complete_empty_answer(graph, failure):
    limit = 1 if failure in {'resource-overflow', 'literal-overflow'} else 10
    program = compile_fact_answer(FactAnswerQuery(NS+'a', (ResourceStep(NS+'author', Direction.IN),), NS+'name', 'en'),
        max_rows=limit, max_binding_bytes=1 if failure == 'binding-bytes' else 4096)
    result = execute_fact_answer(program, neo4j=ResourceClient(
        [NS+'p1', NS+'p2'] if failure == 'resource-overflow' else [NS+'p1'], fail=failure == 'neo4j'),
        fuseki=RdfEngine(graph))
    assert not result['success'] and not result['federated']['success']
    assert 'baseline' not in result


def snapshot(tmp_path):
    root = tmp_path/'snapshot'
    root.mkdir()
    content = (f'<{NS}p1> <{NS}author> <{NS}a> .\n'*2 +
               f'<{NS}p1> <{NS}name> "One"@en .\n').encode()
    (root/'part-000000.nt').write_bytes(content)
    manifest = {'schema_version': SCHEMA, 'status': 'complete', 'selected_shards_fully_consumed': True,
        'output_bytes': len(content), 'fact_occurrences': 3,
        'parts': [{'path': 'part-000000.nt', 'bytes': len(content), 'fact_occurrences': 3,
                   'sha256': hashlib.sha256(content).hexdigest()}]}
    body = json.dumps(manifest).encode()
    (root/'manifest.json').write_bytes(body)
    return FactSnapshot.load(root, expected_manifest_sha256=hashlib.sha256(body).hexdigest(),
                             max_bytes=4096, max_part_bytes=1024)


def test_snapshot_loading_preserves_occurrences_and_explicit_resource_set(tmp_path):
    rdflib = pytest.importorskip('rdflib')
    graph = rdflib.Graph()
    edges = set()

    class NeoLoader:
        backend_id = 'neo4j'
        def execute(self, artifact):
            if 'UNWIND' in artifact.text:
                rows = artifact.parameters['rows']
                edges.update((r['s'],r['p'],r['o']) for r in rows)
                result = [{'loaded':len(rows)}]
            elif 'resource_edges' in artifact.text: result = [{'resource_edges':len(edges)}]
            elif 'count(n)' in artifact.text: result = [{'count':0}]
            else: result = []
            return ExecutionReport('neo4j',artifact.artifact_id,'cypher',True,rows=result)

    class RdfLoader:
        def load(self, path):
            graph.parse(path, format='nt')
            return BackendLoadReport('fuseki',True,1,path.stat().st_size,0)

    result = load_fact_snapshot(snapshot(tmp_path), neo4j=NeoLoader(), fuseki=RdfEngine(graph),
                               fuseki_loader=RdfLoader(), output_root=tmp_path/'load', batch_rows=1)
    assert result['success'] and result['fact_occurrences'] == 3 and result['resource_occurrences'] == 2
    assert len(edges) == 1 and len(graph) == 2
    assert result['literal_occurrences'] == 1


def test_snapshot_mutation_fails_before_part_delivery(tmp_path):
    source = snapshot(tmp_path)
    (source.root/'part-000000.nt').write_text('changed')
    with pytest.raises(ValueError): list(source.parts())


@pytest.mark.parametrize('failure', ['nonempty-neo4j', 'unavailable-fuseki', 'operation-budget'])
def test_loader_failure_retains_partial_evidence_without_retry(tmp_path, failure):
    pytest.importorskip('rdflib')
    calls = []
    class Client:
        def __init__(self, backend_id): self.backend_id = backend_id
        def execute(self, artifact):
            calls.append(self.backend_id)
            return ExecutionReport(self.backend_id, artifact.artifact_id, artifact.language,
                self.backend_id != 'fuseki', rows=[{'count':1 if failure == 'nonempty-neo4j' else 0}],
                error='unavailable' if self.backend_id == 'fuseki' else None)
    result = load_fact_snapshot(snapshot(tmp_path), neo4j=Client('neo4j'), fuseki=Client('fuseki'),
        fuseki_loader=None, output_root=tmp_path/'load', max_operations=1 if failure == 'operation-budget' else 20)
    assert not result['success'] and result['partial_target'] and result['error']
    assert calls == (['neo4j','fuseki'] if failure == 'unavailable-fuseki' else ['neo4j'])
    assert (tmp_path/'load/result.json').is_file()


@pytest.mark.skipif(os.environ.get('XGAP_RUN_LIVE_FACT_ANSWERS') != '1', reason='explicit live fact-answer gate')
def test_real_owned_fact_backends_match_independent_source():
    from xgap.backends.neo4j_client import Neo4jClient
    neo = Neo4jClient(BackendDescriptor('neo4j','neo4j','cypher','property_graph'))
    rdf = FusekiClient(BackendDescriptor('fuseki','fuseki','sparql','rdf'))
    neo.http_url = os.environ['XGAP_FACT_NEO4J_URL']
    rdf.base_url = os.environ['XGAP_FACT_FUSEKI_URL']
    neo.database, rdf.dataset = 'neo4j', 'xgap'
    ns = 'http://rdf.freebase.com/ns/'
    program = compile_fact_answer(FactAnswerQuery(ns+'type.property',
        (ResourceStep(ns+'type.object.type',Direction.IN),),ns+'type.object.name','en'),
        max_rows=100000,max_binding_bytes=16*1024**2)
    result = execute_fact_answer(program,neo4j=neo,fuseki=rdf)
    assert result['success']
    expected = json.loads(Path(os.environ['XGAP_FACT_SOURCE_ANSWER']).read_text())
    assert answer_pairs(result['federated']['root_rows']['answer']) == answer_pairs(expected['rows'])
