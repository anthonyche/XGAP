import csv
import gzip
import json
from pathlib import Path

import pytest
from rdflib import Graph, Namespace, RDF, URIRef

from xgap.experiments import ch6_financial_materialize as material
from xgap.experiments.ch6_financial_scale import generate


@pytest.fixture
def canonical(tmp_path):
    root = tmp_path/'canonical'
    generate(root, execute=True, nodes_per_bank=9, chunk_rows=37,
             max_output_bytes=4*1024**2, reserve_bytes=0)
    return root


def _materialize(canonical, output, **kw):
    return material.materialize(canonical, output, execute=True,
        canonical_manifest_sha256=material.pin(canonical/'manifest.json')['sha256'],
        max_output_bytes=16*1024**2, reserve_bytes=0, **kw)


def _canonical_rows(root, kind):
    manifest = json.loads((root/'manifest.json').read_text())
    rows = []
    for chunk in manifest['chunks']:
        if chunk['kind'] == kind:
            with gzip.open(root/chunk['path'], 'rt', newline='') as stream:
                rows.extend(csv.DictReader(stream))
    return rows


def _native_rows(ref):
    with gzip.open(ref['path'], 'rt', newline='') as stream:
        return list(csv.DictReader(stream))


def test_fixed_32_sources_dry_and_no_regeneration(canonical, tmp_path, monkeypatch):
    from xgap.experiments import ch6_financial_scale as scale
    def forbidden(*_args, **_kwargs):
        raise AssertionError('Materializer must not regenerate canonical facts')
    monkeypatch.setattr(scale, 'iter_accounts', forbidden)
    monkeypatch.setattr(scale, 'iter_transfers', forbidden)
    dry = material.materialize(canonical, tmp_path/'dry')
    assert not (tmp_path/'dry').exists()
    assert dry['source_count'] == 32 and dry['logical_nodes'] == 288
    result = _materialize(canonical, tmp_path/'load')
    assert result['success'] and result['logical_edge_rows_emitted'] == 2880
    assert result['physical_neo4j_relationships'] == 1440
    assert result['canonical_digests'] == json.loads((canonical/'manifest.json').read_text())['canonical_digests']
    assert result['model_calls'] == result['backend_calls'] == result['query_calls'] == 0
    assert not result['services_prepared'] and result['backend_store_bytes'] is None
    assert result['memory_contract']['account_mmap_bytes'] == 288
    assert result['memory_contract']['endpoint_bitmap_bytes'] == 36
    assert sum(s['endpoint_copies'] for s in result['sources']) == result['additional_endpoint_copies']
    assert result['additional_endpoint_copies'] > 0


def test_native_and_rdf_encode_same_frozen_edges_and_actual_endpoint_properties(canonical, tmp_path):
    result = _materialize(canonical, tmp_path/'load')
    accounts = {r['id']: r for r in _canonical_rows(canonical, 'accounts')}
    transfers = {r['id']: r for r in _canonical_rows(canonical, 'transfers')}
    seen = {}; node_copies = 0; triples = 0
    ns = Namespace(material.NS)
    for source in result['sources']:
        bank = source['atoms'][0]
        assert source['source_id'] == ('neo4j' if bank < 16 else 'rdf')+f'-{bank:02d}'
        assert source['owned_accounts'] == 9 and source['logical_edges'] == 90
        node_copies += source['materialized_nodes']
        if source['engine'] == 'neo4j':
            nodes = _native_rows(source['native_bulk_files']['nodes-Account.csv.gz'])
            edges = _native_rows(source['native_bulk_files']['relationships.csv.gz'])
            assert len(nodes) == len({r['id'] for r in nodes}) == source['materialized_nodes']
            node_ids = {r['xgap_id:ID'] for r in nodes}
            for node in nodes:
                assert node['isBlocked:boolean'] == accounts[node['id']]['isBlocked']
                assert node['xgap_id:ID'] == material.identity(node['id'])
                assert node[':LABEL'] == 'Account'
            for edge in edges:
                original = transfers[edge['id']]
                assert edge[':TYPE'] == 'TRANSFERRED_TO'
                assert edge[':START_ID'] == material.identity(original['source'])
                assert edge[':END_ID'] == material.identity(original['target'])
                assert edge[':START_ID'] in node_ids and edge[':END_ID'] in node_ids
                assert edge['amount:long'] == original['amount'] and edge['timestamp:long'] == original['timestamp']
                assert edge['id'] not in seen; seen[edge['id']] = bank
        else:
            graph = Graph().parse(data=gzip.decompress(Path(source['rdf_load']['path']).read_bytes()).decode(), format='nt')
            assert len(graph) == source['rdf_triples']; triples += len(graph)
            rdf_nodes = list(graph.subjects(RDF.type, ns.Account))
            assert len(rdf_nodes) == source['materialized_nodes']
            for node in rdf_nodes:
                business = str(graph.value(node, ns.id))
                assert graph.value(node, ns.isBlocked).toPython() == (accounts[business]['isBlocked'] == 'true')
                assert str(graph.value(node, ns.xgap_id)) == material.identity(business)
            for edge in graph.subjects(RDF.type, ns.Edge):
                ident = str(graph.value(edge, ns.id)); original = transfers[ident]
                assert graph.value(edge, ns.edgeLabel) == ns.TRANSFERRED_TO
                assert graph.value(edge, ns.source) == URIRef(material.RESOURCE+material.identity(original['source']))
                assert graph.value(edge, ns.target) == URIRef(material.RESOURCE+material.identity(original['target']))
                assert graph.value(edge, ns.amount).toPython() == int(original['amount'])
                assert graph.value(edge, ns.timestamp).toPython() == int(original['timestamp'])
                assert ident not in seen; seen[ident] = bank
    assert set(seen) == set(transfers)
    assert all(seen[ident] == int(row['owner_bank']) for ident, row in transfers.items())
    assert node_copies == result['materialized_node_copies']
    assert triples == result['rdf_triples']


def test_cross_engine_two_hop_join_keeps_canonical_business_identity(canonical, tmp_path):
    result = _materialize(canonical, tmp_path/'load')
    all_edges = _canonical_rows(canonical, 'transfers')
    # Choose a cross-engine first edge by canonical topology only, not answer cost.
    first = next(r for r in all_edges if int(r['owner_bank']) < 16 and int(r['target_bank']) >= 16)
    bank = int(first['target_bank']); source = result['sources'][bank]
    rdf = Graph().parse(data=gzip.decompress(Path(source['rdf_load']['path']).read_bytes()).decode(), format='nt')
    prefix = material.identity(first['target'])
    query = f'''SELECT ?id ?amount WHERE {{
      ?e <{material.NS}source> <{material.RESOURCE}{prefix}> ;
         <{material.NS}edgeLabel> <{material.NS}TRANSFERRED_TO> ;
         <{material.NS}id> ?id ; <{material.NS}amount> ?amount . }}'''
    rows = sorted((str(r.id), int(r.amount)) for r in rdf.query(query))
    expected = sorted((r['id'], int(r['amount'])) for r in all_edges if r['source'] == first['target'])
    assert rows == expected and len(rows) == 10
    native_source = result['sources'][int(first['owner_bank'])]
    native = _native_rows(native_source['native_bulk_files']['relationships.csv.gz'])
    assert next(e[':END_ID'] for e in native if e['id'] == first['id']) == prefix


def test_tampered_chunk_cannot_publish_success(canonical, tmp_path):
    manifest = json.loads((canonical/'manifest.json').read_text())
    target = canonical/manifest['chunks'][0]['path']
    with target.open('ab') as stream:
        stream.write(b'tampered')
    output = tmp_path/'load'
    with pytest.raises(ValueError, match='compressed chunk changed'):
        _materialize(canonical, output)
    assert not (output/'receipt.json').exists()
    assert json.loads((output/'failure.json').read_text())['partial_inputs_preserved']


def test_invalid_manifest_coverage_and_existing_destination_fail(canonical, tmp_path):
    with pytest.raises(ValueError, match='exactly 32'):
        material.materialize(canonical, tmp_path/'load', source_count=16)
    with pytest.raises(ValueError, match='frozen canonical manifest'):
        material.materialize(canonical, tmp_path/'load', execute=True)
    existing = tmp_path/'keep'; existing.mkdir(); (existing/'old').write_text('preserve')
    with pytest.raises(ValueError, match='New separate'):
        _materialize(canonical, existing)
    assert (existing/'old').read_text() == 'preserve'
    manifest = json.loads((canonical/'manifest.json').read_text())
    manifest['chunks'].append(manifest['chunks'][0])
    (canonical/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Duplicate'):
        _materialize(canonical, tmp_path/'load')


def test_output_budget_retains_partial_data_without_success(canonical, tmp_path):
    output = tmp_path/'bounded'
    with pytest.raises(ValueError, match='output byte limit'):
        material.materialize(canonical, output, execute=True,
            canonical_manifest_sha256=material.pin(canonical/'manifest.json')['sha256'],
            max_output_bytes=9000, reserve_bytes=0)
    assert not (output/'receipt.json').exists()
    failure = json.loads((output/'failure.json').read_text())
    assert not failure['success'] and failure['partial_inputs_preserved']
    assert failure['automatic_retries'] == 0
