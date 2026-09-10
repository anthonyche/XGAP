"""Offline synthetic fact-to-answer example; requires parquet and test-sparql extras."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from xgap.algebra.conditions import NodeRef, PropertyGreaterThan
from xgap.backends.rdf_terms import RdfTerm
from xgap.compilers.directed import compile_directed_rows
from xgap.compilers.rdf_encoding import RdfRowEncoding
from xgap.experiments.freebase_fact_snapshot import export_fact_snapshot
from xgap.experiments.freebase_sources import (
    EXPECTED_PARQUET_COLUMNS, HF_ARCHIVAL_PARQUET, HF_FREEBASE_REVISION,
    PARQUET_SOURCE_MANIFEST_SCHEMA_VERSION,
)
from xgap.pattern.ast import Direction, EdgePattern, NodePattern, PathMode, PathPatternQuery, Rel, Selector, SelectorKind
from xgap.runtime.answers import AnswerProjection


def main() -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    import rdflib

    ns = 'http://rdf.freebase.com/ns/'
    rows = [
        [ns+'m.paper2024', ns+'demo.author', ns+'m.researcher', 'uri', None, None],
        [ns+'m.paper2024', ns+'demo.year', '2024', 'literal', 'http://www.w3.org/2001/XMLSchema#integer', None],
        [ns+'m.paper2020', ns+'demo.author', ns+'m.researcher', 'uri', None, None],
        [ns+'m.paper2020', ns+'demo.year', '2020', 'literal', 'http://www.w3.org/2001/XMLSchema#integer', None],
    ]
    with TemporaryDirectory(prefix='xgap-fact-demo-') as temporary:
        root = Path(temporary)
        source = root/'source'
        source.mkdir()
        shard = source/'fixture.parquet'
        pq.write_table(pa.table({name: pa.array([r[i] for r in rows], type=pa.string())
                                for i,name in enumerate(EXPECTED_PARQUET_COLUMNS)}), shard)
        schema = {'fields': [{'name': name, 'type': 'string', 'nullable': True} for name in EXPECTED_PARQUET_COLUMNS]}
        inventory = {'schema_version':PARQUET_SOURCE_MANIFEST_SCHEMA_VERSION, 'source_mode':HF_ARCHIVAL_PARQUET,
            'repo_id':'CleverThis/freebase', 'revision':HF_FREEBASE_REVISION, 'resolved_parquet_revision':HF_FREEBASE_REVISION,
            'fixture_only':True, 'parquet_schema':schema,
            'schema_fingerprint':hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(',',':')).encode()).hexdigest(),
            'shard_count':1, 'total_bytes':shard.stat().st_size,
            'shards':[{'path':shard.name, 'size_bytes':shard.stat().st_size,
                'sha256':hashlib.sha256(shard.read_bytes()).hexdigest(),
                'url':f'https://huggingface.co/datasets/CleverThis/freebase/resolve/{HF_FREEBASE_REVISION}/{shard.name}'}]}
        manifest_path = root/'source.json'
        manifest_path.write_text(json.dumps(inventory))
        built = export_fact_snapshot(parquet_root=source, source_manifest_path=manifest_path,
            expected_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(), output_root=root/'facts',
            max_input_bytes=shard.stat().st_size, max_output_bytes=10000, max_rows=10, part_bytes=512)
        graph = rdflib.Graph()
        for part in built['parts']:
            graph.parse(root/'facts'/part['path'], format='nt')
        mapping = {'mapping_id':'synthetic-fact-demo','version':'1',
            'backends':{'fuseki':{'namespace':ns,'compiler_tokens':{
                'node_labels':{},'edge_labels':{'author':'demo.author'},'properties':{'year':'demo.year','mid':'type.object.mid'}}}},
            'term_mappings':{'fuseki':{name:{'kind':kind,'representation':ns+name}
                for name,kind in [('demo.author','relation'),('demo.year','property'),('type.object.mid','property')]}}}
        query = PathPatternQuery(None, NodePattern(properties={'mid':'m.researcher'}),
            Rel(EdgePattern(label='author', direction=Direction.IN)), NodePattern(),
            Selector(SelectorKind.ALL), PathMode.WALK, condition=PropertyGreaterThan(NodeRef.last(),'year',2022))
        artifact = compile_directed_rows(query,backend_id='fuseki',backend_mapping=mapping,
            rdf_encoding=RdfRowEncoding('synthetic-fact-demo',ns+'type.object.type','mid',ns))
        payload = json.loads(graph.query(artifact.text).serialize(format='json'))
        answers = AnswerProjection('target').project_rows(payload['results']['bindings'])
        if answers != (RdfTerm('uri',ns+'m.paper2024'),):
            raise AssertionError('Unexpected answer from the independent SPARQL engine.')
        print(json.dumps({'scope':'synthetic offline fact-to-answer demonstration',
            'question':'Papers by this researcher published after 2022',
            'fact_occurrences':built['fact_occurrences'], 'snapshot_parts':len(built['parts']),
            'answers':[a.to_binding() for a in answers], 'verification_engine':'RDFLib '+rdflib.__version__,
            'catalog_rebuilds':0, 'external_model_calls':0, 'external_backend_calls':0}, indent=2))


if __name__ == '__main__':
    main()
