from dataclasses import replace
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from urllib.parse import parse_qs

import pytest

from xgap.algebra.conditions import NodeRef, PropertyGreaterThan
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.rdf_terms import RdfTerm, XSD_STRING
from xgap.compilers.directed import compile_directed_rows
from xgap.compilers.rdf_encoding import RdfRowEncoding
from xgap.experiments.freebase_facts import FactSource, RdfFact, fact_from_parquet_row
from xgap.experiments.freebase_fact_snapshot import export_fact_snapshot
from xgap.experiments.freebase_sources import (
    EXPECTED_PARQUET_COLUMNS, HF_ARCHIVAL_PARQUET, HF_FREEBASE_REVISION,
    PARQUET_SOURCE_MANIFEST_SCHEMA_VERSION, parquet_row_to_triple,
)
from xgap.experiments.m15_fixture_loader import FusekiGraphStoreFixtureLoader
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.pattern.ast import Direction, EdgePattern, NodePattern, PathMode, PathPatternQuery, Rel, Selector, SelectorKind, Seq
from xgap.runtime.answers import AnswerProjection


ROOT = Path(__file__).resolve().parents[1]
NS = 'http://rdf.freebase.com/ns/'
XSD = 'http://www.w3.org/2001/XMLSchema#'


def row(s='m.p1', p='demo.year', o='2024', kind='literal', dtype=XSD+'integer', lang=None):
    return dict(zip(EXPECTED_PARQUET_COLUMNS, [NS+s, NS+p, NS+o if kind == 'uri' else o, kind, dtype, lang]))


def make_source(tmp_path, rows=None, shard_count=2):
    pa = pytest.importorskip('pyarrow')
    pq = pytest.importorskip('pyarrow.parquet')
    rows = rows if rows is not None else [row(), row(o='2020'), row(p='demo.name', o='论文 😀', dtype=None, lang='ZH')]
    root = tmp_path/'parquet'
    (root/'default/data').mkdir(parents=True)
    schema = {'fields': [{'name': name, 'nullable': True, 'type': 'string'} for name in EXPECTED_PARQUET_COLUMNS]}
    shards = []
    for i in range(shard_count):
        path = root/f'default/data/{i:04d}.parquet'
        records = rows[i::shard_count]
        table = pa.table({name: pa.array([r[name] for r in records], type=pa.string()) for name in EXPECTED_PARQUET_COLUMNS})
        pq.write_table(table, path, row_group_size=2)
        relative = path.relative_to(root).as_posix()
        shards.append({'path': relative, 'size_bytes': path.stat().st_size,
                       'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                       'url': f'https://huggingface.co/datasets/CleverThis/freebase/resolve/{HF_FREEBASE_REVISION}/{relative}'})
    manifest = {'schema_version': PARQUET_SOURCE_MANIFEST_SCHEMA_VERSION, 'source_mode': HF_ARCHIVAL_PARQUET,
                'repo_id': 'CleverThis/freebase', 'revision': HF_FREEBASE_REVISION,
                'resolved_parquet_revision': HF_FREEBASE_REVISION,
                'parquet_schema': schema,
                'schema_fingerprint': hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                'shard_count': len(shards), 'total_bytes': sum(s['size_bytes'] for s in shards), 'shards': shards}
    path = tmp_path/'source.json'
    path.write_text(json.dumps(manifest))
    return {'parquet_root': root, 'source_manifest_path': path,
            'expected_manifest_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'max_input_bytes': manifest['total_bytes']}


def export(tmp_path, source, **kwargs):
    return export_fact_snapshot(**{**source, 'output_root': tmp_path/'facts',
        'max_output_bytes': 1_000_000, 'max_rows': 1000, 'part_bytes': 512, 'batch_size': 1, **kwargs})


@pytest.mark.parametrize('raw,expected', [
    (row(), RdfTerm('literal', '2024', XSD+'integer')),
    (row(o='01'), RdfTerm('literal', '01', XSD+'integer')),
    (row(o='3.1400', dtype=XSD+'decimal'), RdfTerm('literal', '3.1400', XSD+'decimal')),
    (row(o='2026-09-10', dtype=XSD+'date'), RdfTerm('literal', '2026-09-10', XSD+'date')),
    (row(o='true', dtype=XSD+'boolean'), RdfTerm('literal', 'true', XSD+'boolean')),
    (row(o='NaN', dtype=XSD+'double'), RdfTerm('literal', 'NaN', XSD+'double')),
    (row(o='text', dtype=None), RdfTerm('literal', 'text', XSD_STRING)),
    (row(o='text', dtype='', lang=''), RdfTerm('literal', 'text', XSD_STRING)),
    (row(o='text', dtype=None, lang='EN-gb'), RdfTerm('literal', 'text', language='en-gb')),
    (row(o='m.a', kind='uri', dtype=None), RdfTerm('uri', NS+'m.a')),
    (row(o=NS+'m.a', dtype=None), RdfTerm('literal', NS+'m.a')),
    (row(o='unknown lexical form', dtype='urn:custom:type'), RdfTerm('literal', 'unknown lexical form', 'urn:custom:type')),
    (row(kind='typed-literal'), RdfTerm('literal', '2024', XSD+'integer')),
])
def test_typed_facts_preserve_terms_without_value_coercion(raw, expected):
    fact = fact_from_parquet_row(raw)
    assert fact.object == expected
    assert fact.subject == RdfTerm('uri', raw['subject'])
    assert fact.predicate == RdfTerm('uri', raw['predicate'])


@pytest.mark.parametrize('changes', [
    {'object_type': 'bnode'}, {'object_type': 'unknown'}, {'object': None},
    {'object': 42}, {'subject': 'm.relative'}, {'predicate': 'not an IRI'},
    {'object_type': 'uri', 'object': NS+'m.a', 'object_datatype': XSD+'integer'},
    {'object_language': 'en', 'object_datatype': XSD+'integer'},
    {'object_language': 'not valid'}, {'object_datatype': 42},
    {'object_type': 'typed-literal', 'object_datatype': None},
    {'gold_answer': 'forbidden extra column'}, {'object': '\ud800'},
])
def test_malformed_facts_never_become_silent_skips(changes):
    with pytest.raises(ValueError):
        fact_from_parquet_row({**row(), **changes})


def test_legacy_catalog_contract_is_intentionally_unchanged():
    raw = row()
    assert parquet_row_to_triple(raw) is None
    assert fact_from_parquet_row(raw).object.datatype == XSD+'integer'
    with pytest.raises(ValueError):
        RdfFact(RdfTerm('bnode', 'a'), RdfTerm('uri', 'urn:p'), RdfTerm('literal', 'x'))


def test_actual_parquet_full_columns_and_provenance(tmp_path):
    data = [row(o=str(2000+i), p='arbitrary.predicate') for i in range(9)]
    source = FactSource.load(**make_source(tmp_path, data))
    records = list(source.records(batch_size=1))
    assert [r.fact.object.value for r in records] == [str(2000+i) for i in [0,2,4,6,8,1,3,5,7]]
    assert [(r.row_group, r.row_index) for r in records[:5]] == [(0,0),(0,1),(1,0),(1,1),(2,0)]
    assert len({r.source_shard for r in records}) == 2
    assert source.description()['selection'] == 'all_manifest_shards'
    assert source.description()['original_freebase_completeness_claimed'] is False


@pytest.mark.parametrize('selection', [[], ['missing'], ['default/data/0000.parquet']*2, 'default/data/0000.parquet'])
def test_bad_shard_selection_fails_before_output(tmp_path, selection):
    source = make_source(tmp_path)
    with pytest.raises(ValueError):
        export(tmp_path, source, shard_paths=selection)
    assert not (tmp_path/'facts').exists()


def test_explicit_partial_shards_are_complete_only_for_that_selection(tmp_path):
    source = make_source(tmp_path)
    manifest = export(tmp_path, source, shard_paths=['default/data/0001.parquet'])
    assert manifest['fact_occurrences'] == 1
    assert manifest['selected_shards_fully_consumed'] is True
    assert manifest['source']['selection'] == 'explicit_partial_shards'
    assert len(manifest['source']['selected_shards']) == 1


def test_chunked_nt_independent_roundtrip_keeps_lexical_identity_and_duplicates(tmp_path, monkeypatch):
    rdf = pytest.importorskip('rdflib', minversion='7.1.4')
    monkeypatch.setattr(rdf, 'NORMALIZE_LITERALS', False)
    data = [row(o='01'), row(o='01'), row(dtype=None, o='1'),
            row(o='m.a', kind='uri', dtype=None), row(o=NS+'m.a', dtype=None),
            row(o='quote " slash \\ control\b\f\n 😀', dtype=None, lang='ZH'),
            row(o='2024-01-02Z', dtype=XSD+'date')]
    source = make_source(tmp_path, data)
    original = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob('*') if p.is_file()}
    manifest = export(tmp_path, source, part_bytes=300)
    assert len(manifest['parts']) > 1 and manifest['fact_occurrences'] == len(data)
    assert manifest['rdf_set_deduplication_performed'] is False
    graph = rdf.Graph()
    for part in manifest['parts']:
        path = tmp_path/'facts'/part['path']
        content = path.read_bytes()
        assert len(content) == part['bytes'] <= 300
        assert hashlib.sha256(content).hexdigest() == part['sha256']
        graph.parse(data=content.decode(), format='nt')
    expected = {(r['subject'], r['predicate'], fact_from_parquet_row(r).object.identity) for r in data}
    actual = {(str(s), str(p), RdfTerm('uri', str(o)).identity if isinstance(o, rdf.URIRef)
               else RdfTerm('literal', str(o), str(o.datatype) if o.datatype else None, o.language).identity) for s,p,o in graph}
    assert actual == expected
    assert len(graph) == len(data)-1
    assert sum(p['bytes'] for p in manifest['parts']) == manifest['output_bytes']
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p,h in original.items())


@pytest.mark.parametrize('limit', [{'max_rows': 1}, {'max_output_bytes': 1}, {'part_bytes': 1}])
def test_output_budget_does_not_publish_truncated_success(tmp_path, limit):
    source = make_source(tmp_path)
    with pytest.raises(ValueError):
        export(tmp_path, source, **limit)
    assert not (tmp_path/'facts/manifest.json').exists()
    failure = json.loads((tmp_path/'facts/snapshot_failure.json').read_text())
    assert failure['status'] == 'failed' and failure['selected_shards_fully_consumed'] is False
    if limit.get('max_rows') == 1:
        assert failure['completed_fact_occurrences'] == 1 and failure['parts']


@pytest.mark.parametrize('limit', [{'max_input_bytes':1}, {'max_rows':True}, {'batch_size':0}, {'part_bytes':-1}])
def test_invalid_or_insufficient_input_budget_does_not_start(tmp_path, limit):
    source = make_source(tmp_path)
    with pytest.raises(ValueError):
        export(tmp_path, source, **limit)
    assert not (tmp_path/'facts').exists()


def test_bad_record_preserves_prior_parts_without_success(tmp_path):
    source = make_source(tmp_path, [row(), row(o='bad', kind='unknown')], shard_count=1)
    with pytest.raises(ValueError, match='row group 0, row 1'):
        export(tmp_path, source)
    failure = json.loads((tmp_path/'facts/snapshot_failure.json').read_text())
    assert failure['completed_fact_occurrences'] == 1
    assert not (tmp_path/'facts/manifest.json').exists()


@pytest.mark.parametrize('change', ['hash', 'size', 'symlink'])
def test_changed_source_never_publishes(tmp_path, change):
    source = make_source(tmp_path)
    path = source['parquet_root']/'default/data/0000.parquet'
    content = path.read_bytes()
    if change == 'hash':
        path.write_bytes(content[:-1]+bytes([content[-1]^1]))
    elif change == 'size':
        path.write_bytes(content+b'changed')
    else:
        other = tmp_path/'outside.parquet'
        other.write_bytes(content)
        path.unlink()
        path.symlink_to(other)
    with pytest.raises(ValueError):
        export(tmp_path, source)
    assert not (tmp_path/'facts/manifest.json').exists()


def test_manifest_mismatch_and_existing_output_preserve_inputs(tmp_path):
    source = make_source(tmp_path)
    with pytest.raises(ValueError, match='manifest digest'):
        export(tmp_path, source, expected_manifest_sha256='0'*64)
    out = tmp_path/'facts'
    out.mkdir()
    (out/'keep.txt').write_text('keep')
    with pytest.raises(FileExistsError):
        export(tmp_path, source)
    assert (out/'keep.txt').read_text() == 'keep'
    with pytest.raises(ValueError, match='outside protected'):
        export(tmp_path, source, output_root=source['parquet_root']/'facts')


@pytest.mark.parametrize('target', ['shard', 'manifest'])
def test_mutation_during_stream_is_detected_before_complete_consumption(tmp_path, target):
    source = make_source(tmp_path)
    stream = FactSource.load(**source).records(batch_size=1)
    assert next(stream).fact.object.value == '2024'
    if target == 'shard':
        path = source['parquet_root']/'default/data/0000.parquet'
        status = path.stat()
        os.utime(path, ns=(status.st_atime_ns, status.st_mtime_ns+1_000_000))
    else:
        path = source['source_manifest_path']
        path.write_text(path.read_text()+'\n')
    with pytest.raises(ValueError, match='changed while reading'):
        list(stream)


def test_zero_row_shard_is_explicit_empty_unloaded_snapshot(tmp_path):
    manifest = export(tmp_path, make_source(tmp_path, [], shard_count=1))
    assert manifest['status'] == 'complete' and manifest['fact_occurrences'] == 0
    assert manifest['parts'] == [] and manifest['backend_loaded'] is False


def test_missing_datatype_column_fails_instead_of_using_catalog_projection(tmp_path):
    pq = pytest.importorskip('pyarrow.parquet')
    source = make_source(tmp_path)
    path = source['parquet_root']/'default/data/0000.parquet'
    table = pq.read_table(path).drop_columns(['object_datatype'])
    pq.write_table(table, path)
    manifest_path = source['source_manifest_path']
    manifest = json.loads(manifest_path.read_text())
    entry = manifest['shards'][0]
    entry.update(size_bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    manifest['total_bytes'] = sum(s['size_bytes'] for s in manifest['shards'])
    manifest_path.write_text(json.dumps(manifest))
    source.update(expected_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                  max_input_bytes=manifest['total_bytes'])
    with pytest.raises(ValueError, match='Parquet schema'):
        export(tmp_path, source)
    assert not (tmp_path/'facts/manifest.json').exists()


def test_real_module_cli_builds_the_same_declared_snapshot(tmp_path):
    source = make_source(tmp_path)
    args = [sys.executable, '-m', 'xgap.experiments.freebase_fact_snapshot']
    options = {**source, 'output_root':tmp_path/'facts', 'max_rows':20, 'max_output_bytes':10000}
    for key,value in options.items():
        args.extend(['--'+key.replace('_','-'), str(value)])
    result = subprocess.run(args, env={**os.environ, 'PYTHONPATH':str(ROOT/'src')}, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['fact_occurrences'] == 3
    again = subprocess.run(args, env={**os.environ, 'PYTHONPATH':str(ROOT/'src')}, text=True, capture_output=True)
    assert again.returncode == 1 and json.loads(again.stdout)['status'] == 'failed'


def test_export_http_load_compile_execute_and_typed_answers(tmp_path):
    rdf = pytest.importorskip('rdflib', minversion='7.1.4')
    data = [row('m.a1','demo.affiliation','m.cwru','uri',None),
            row('m.a2','demo.affiliation','m.other','uri',None)]
    for paper,author,year,dtype in [('m.p1','m.a1','2024',XSD+'integer'),('m.p2','m.a1','2020',XSD+'integer'),
                                    ('m.p3','m.a2','2025',XSD+'integer'),('m.p4','m.a1','2024',None)]:
        data += [row(paper,'demo.author',author,'uri',None), row(paper,'demo.year',year,dtype=dtype),
                 row(paper,'type.object.type','demo.paper','uri',None)]
    manifest = export(tmp_path, make_source(tmp_path, data), part_bytes=512)
    graph = rdf.Graph()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            requests.append(self.path)
            if self.path.endswith('/data?default'):
                graph.parse(data=body.decode(), format='turtle')
                self.send_response(204); self.end_headers()
            else:
                query = parse_qs(body.decode())['query'][0]
                response = graph.query(query).serialize(format='json')
                self.send_response(200)
                self.send_header('Content-Type', 'application/sparql-results+json')
                self.end_headers(); self.wfile.write(response)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        descriptor = BackendDescriptor.from_yaml(ROOT/'descriptors/backends/fuseki.yaml')
        loader = FusekiGraphStoreFixtureLoader(descriptor)
        loader.base_url = f'http://127.0.0.1:{server.server_port}'
        for part in manifest['parts']:
            loaded = loader.load(tmp_path/'facts'/part['path'])
            assert loaded.success and loaded.operations_attempted == 1
        assert len(graph) == len(data)
        mapping = {'mapping_id':'typed-fact-fixture','version':'1','backends':{'fuseki':{'namespace':NS,
                   'compiler_tokens':{'node_labels':{'Paper':'demo.paper'},
                       'edge_labels':{'affiliation':'demo.affiliation','author':'demo.author'},
                       'properties':{'year':'demo.year','mid':'type.object.mid'}}}},
                   'term_mappings':{'fuseki':{name:{'kind':kind,'representation':NS+name} for name,kind in
                       [('demo.paper','class'),('demo.affiliation','relation'),('demo.author','relation'),
                        ('demo.year','property'),('type.object.mid','property')]}}}
        encoding = RdfRowEncoding('typed-fact-fixture',NS+'type.object.type','mid',NS)
        query = PathPatternQuery(None,NodePattern(properties={'mid':'m.cwru'}),
            Seq(Rel(EdgePattern(label='affiliation',direction=Direction.IN)),Rel(EdgePattern(label='author',direction=Direction.IN))),
            NodePattern(label='Paper'),Selector(SelectorKind.ALL),PathMode.WALK,
            condition=PropertyGreaterThan(NodeRef.last(),'year',2022))
        backend = FusekiClient(descriptor); backend.base_url = loader.base_url
        artifact = compile_directed_rows(query,backend_id='fuseki',backend_mapping=mapping,rdf_encoding=encoding)
        answer = backend.execute(artifact)
        assert answer.success, answer.error
        assert AnswerProjection('target').project_execution(answer) == (RdfTerm('uri',NS+'m.p1'),)
        empty = backend.execute(compile_directed_rows(replace(query, condition=PropertyGreaterThan(NodeRef.last(),'year',2030)),
                                backend_id='fuseki',backend_mapping=mapping,rdf_encoding=encoding))
        assert empty.success and AnswerProjection('target').project_execution(empty) == ()
        assert len(requests) == len(manifest['parts'])+2
    finally:
        server.shutdown(); server.server_close(); thread.join()
