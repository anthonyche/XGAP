import csv
import gzip
import hashlib
import io
import importlib.util
import itertools
import json
import tracemalloc
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from xgap.experiments import ch6_financial_scale as scale


def _read(root):
    manifest = json.loads((root/'manifest.json').read_text())
    all_rows = defaultdict(list)
    for chunk in manifest['chunks']:
        raw = (root/chunk['path']).read_bytes()
        assert len(raw) == chunk['bytes']
        assert hashlib.sha256(raw).hexdigest() == chunk['sha256']
        decoded = gzip.decompress(raw)
        assert hashlib.sha256(decoded).hexdigest() == chunk['decoded_sha256']
        rows = list(csv.DictReader(io.StringIO(decoded.decode())))
        assert len(rows) == chunk['rows'] <= manifest['recipe']['chunk_rows']
        assert {int(r['owner_bank']) for r in rows} == {chunk['owner_bank']}
        all_rows[chunk['kind']].extend(rows)
    return manifest, all_rows


def _generate(path, monkeypatch, **kwargs):
    monkeypatch.setattr(scale.shutil, 'disk_usage', lambda _: SimpleNamespace(free=2**50))
    return scale.generate(path, execute=True, nodes_per_bank=16, max_output_bytes=8*1024**2,
                          reserve_bytes=0, **kwargs)


def test_dry_default_is_exact_target_without_writes(tmp_path):
    result = scale.generate(tmp_path/'not-created')
    assert not result['executed'] and not (tmp_path/'not-created').exists()
    spec = result['recipe']
    assert spec['counts'] == dict(accounts=10000000, logical_edges=100000000,
        intra_bank_edges=80000000, inter_bank_edges=20000000, out_degree=10)
    assert spec['atom_counts'] == dict(accounts=312500, logical_edges=3125000)
    assert spec['representation']['temporal_view_copies'] == 0
    assert not spec['benchmark_equivalence'] and not spec['services_prepared']
    assert spec['core']['measure'] == 'amount' and spec['core']['control'] == 'isBlocked'


def test_tiny_streaming_facts_unique_owned_and_layout_conserved(tmp_path, monkeypatch):
    result = _generate(tmp_path/'facts', monkeypatch, chunk_rows=37)
    manifest, rows = _read(tmp_path/'facts')
    assert result['success'] and result['chunks'] == manifest['recipe']['expected_chunks']
    accounts, transfers = rows['accounts'], rows['transfers']
    ids = {r['id'] for r in accounts}
    assert len(accounts) == len(ids) == 512
    assert len(transfers) == len({r['id'] for r in transfers}) == 5120
    owned = Counter(int(r['owner_bank']) for r in transfers)
    assert set(owned.values()) == {160}
    outgoing = defaultdict(list)
    for row in transfers:
        assert row['source'] in ids and row['target'] in ids and row['source'] != row['target']
        assert row['owner_bank'] == row['source_bank']
        assert int(row['source'].split(':')[1])//16 == int(row['source_bank'])
        assert int(row['target'].split(':')[1])//16 == int(row['target_bank'])
        assert 1 <= int(row['amount']) <= 1000000
        assert scale.START_MS <= int(row['timestamp']) < scale.START_MS+scale.WINDOW_MS
        outgoing[row['source']].append(row)
    for group in outgoing.values():
        assert len(group) == len({r['target'] for r in group}) == 10
        assert sum(r['source_bank'] == r['target_bank'] for r in group) == 8
        assert len({r['target_bank'] for r in group if r['source_bank'] != r['target_bank']}) == 2
    original = Counter(r['id'] for r in transfers)
    for source_count in scale.SOURCE_COUNTS:
        layout = scale.source_layout(source_count, nodes_per_bank=16)
        atoms = [a for source in layout['sources'] for a in source['atoms']]
        assert sorted(atoms) == list(range(32))
        merged = Counter()
        for source in layout['sources']:
            assert all((a < 16) == (source['engine'] == 'neo4j') for a in source['atoms'])
            group = [r for r in transfers if int(r['owner_bank']) in source['atoms']]
            assert len(group) == source['logical_edges']
            merged.update(r['id'] for r in group)
        assert merged == original


def test_deterministic_compressed_chunks_and_chunk_independent_facts(tmp_path, monkeypatch):
    _generate(tmp_path/'a', monkeypatch, chunk_rows=37)
    _generate(tmp_path/'b', monkeypatch, chunk_rows=37)
    _generate(tmp_path/'c', monkeypatch, chunk_rows=101)
    a, _ = _read(tmp_path/'a'); b, _ = _read(tmp_path/'b'); c, _ = _read(tmp_path/'c')
    assert a == b
    assert a['logical_facts_sha256'] == c['logical_facts_sha256']
    assert a['canonical_digests'] == c['canonical_digests']
    assert a['chunks'] != c['chunks']
    assert list(scale.iter_transfers(1, nodes_per_bank=16, seed=1)) != list(scale.iter_transfers(1, nodes_per_bank=16, seed=2))


def test_iterator_memory_does_not_allocate_target_graph():
    tracemalloc.start()
    try:
        count = sum(1 for _ in itertools.islice(scale.iter_transfers(0), 10000))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert count == 10000 and peak < 256*1024


def test_minimum_bank_has_no_repeated_or_self_destination():
    for bank in (0, 15, 31):
        rows = list(scale.iter_transfers(bank, nodes_per_bank=9))
        for start in range(0, len(rows), 10):
            group = rows[start:start+10]
            assert len({r[3] for r in group}) == 10
            assert all(r[2] != r[3] for r in group)


def test_disk_preflight_and_existing_output_fail_before_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(scale.shutil, 'disk_usage', lambda _: SimpleNamespace(free=0))
    with pytest.raises(ValueError, match='Insufficient space'):
        scale.generate(tmp_path/'missing', execute=True, nodes_per_bank=9)
    assert not (tmp_path/'missing').exists()
    with pytest.raises(ValueError, match='below conservative'):
        scale.generate(tmp_path/'low-cap', execute=True, max_output_bytes=1024)
    assert not (tmp_path/'low-cap').exists()
    existing = tmp_path/'existing'; existing.mkdir(); (existing/'keep').write_text('old')
    with pytest.raises(ValueError, match='already exists'):
        scale.generate(existing, execute=True, nodes_per_bank=9)
    assert (existing/'keep').read_text() == 'old'


def test_dynamic_disk_loss_leaves_no_success_receipt(tmp_path, monkeypatch):
    calls = []
    def capacity(_):
        calls.append(1)
        return SimpleNamespace(free=2**50 if len(calls) == 1 else 0)
    monkeypatch.setattr(scale.shutil, 'disk_usage', capacity)
    with pytest.raises(ValueError, match='reserve reached'):
        scale.generate(tmp_path/'interrupted', execute=True, nodes_per_bank=9,
                       max_output_bytes=8*1024**2, reserve_bytes=1)
    assert not (tmp_path/'interrupted/receipt.json').exists()
    assert not (tmp_path/'interrupted/manifest.json').exists()


@pytest.mark.parametrize('kwargs', [dict(nodes_per_bank=8), dict(nodes_per_bank=True),
    dict(nodes_per_bank=312501), dict(seed=-1), dict(chunk_rows=0), dict(chunk_rows=1)])
def test_recipe_rejects_unbounded_or_invalid_parameters(kwargs):
    with pytest.raises(ValueError):
        scale.recipe(**kwargs)


def test_source_layout_rejects_cross_engine_or_unsupported_counts():
    for count in (1, 3, 64, True):
        with pytest.raises(ValueError):
            scale.source_layout(count)


def test_cli_requires_execute_and_uses_same_recipe(tmp_path, capsys, monkeypatch):
    path = Path(scale.__file__).resolve().parents[3]/'scripts/generate_ch6_financial_scale.py'
    spec = importlib.util.spec_from_file_location('financial_scale_cli', path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    root = tmp_path/'cli'
    assert cli.main(['--output', str(root)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert not result['executed'] and not root.exists()
    monkeypatch.setattr(scale.shutil, 'disk_usage', lambda _: SimpleNamespace(free=2**50))
    assert cli.main(['--output', str(root), '--execute', '--nodes-per-bank', '9',
                     '--max-output-bytes', str(8*1024**2), '--reserve-bytes', '0']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['counts']['logical_edges'] == 2880
    assert result['success'] and (root/'manifest.json').exists()


def test_reported_metrics_are_readback_counts_types_and_bytes(tmp_path, monkeypatch):
    root = tmp_path/'metrics'
    receipt = _generate(root, monkeypatch, chunk_rows=37)
    manifest, rows = _read(root)
    measured = json.loads((root/'graph-statistics.json').read_text())
    assert measured == manifest['graph_statistics']
    nodes, edges = rows['accounts'], rows['transfers']
    assert measured['nodes'] == len(nodes) == 512
    assert measured['edges'] == len(edges) == 5120
    assert measured['node_types'] == dict(Counter(n['type'] for n in nodes))
    assert measured['relation_types'] == dict(Counter(e['type'] for e in edges))
    attributes = measured['semantic_attributes']
    assert attributes['total_schema_count'] == 3
    assert attributes['total_value_count'] == len(nodes)+2*len(edges)
    assert attributes['account_isBlocked']['true_count'] == sum(n['isBlocked'] == 'true' for n in nodes)
    assert attributes['account_isBlocked']['false_count'] == sum(n['isBlocked'] == 'false' for n in nodes)
    for field, key in [('amount', 'transfer_amount'), ('timestamp', 'transfer_timestamp')]:
        assert attributes[key]['min'] == min(int(e[field]) for e in edges)
        assert attributes[key]['max'] == max(int(e[field]) for e in edges)
    for kind in ('accounts', 'transfers'):
        for field in measured['fields'][kind]:
            assert field['non_null_values'] == field['type_valid_values'] == len(rows[kind])
            assert all(row[field['name']] != '' for row in rows[kind])
            assert (field['role'] == 'semantic_attribute') == (field['name'] in ('amount', 'timestamp', 'isBlocked'))
            assert field['null_values'] == 0
    top = measured['topology']
    assert top['intra_bank_edges'] == sum(e['source_bank'] == e['target_bank'] for e in edges)
    assert top['cross_engine_edges'] == sum((int(e['source_bank']) < 16) != (int(e['target_bank']) < 16) for e in edges)
    assert top['mean_in_degree'] == top['mean_out_degree'] == 10
    assert top['directed_density'] == len(edges)/(len(nodes)*(len(nodes)-1))
    for group in top['cross_source_edges']:
        width = 32//group['source_count']
        cross = sum(int(e['source_bank'])//width != int(e['target_bank'])//width for e in edges)
        assert group['cross_source_edges'] == cross
        assert group['within_source_edges'] == len(edges)-cross
    assert measured['shards']['actual_atomic_shards'] == 32
    assert sum(b['nodes'] for b in measured['shards']['banks']) == len(nodes)
    assert sum(b['edges'] for b in measured['shards']['banks']) == len(edges)
    compressed = sum((root/c['path']).stat().st_size for c in manifest['chunks'])
    uncompressed = sum(len(gzip.decompress((root/c['path']).read_bytes())) for c in manifest['chunks'])
    assert measured['storage']['compressed_data_bytes'] == compressed
    assert measured['storage']['uncompressed_csv_bytes'] == uncompressed
    assert measured['storage']['filesystem_allocated_data_bytes'] == sum((root/c['path']).stat().st_blocks*512 for c in manifest['chunks'])
    assert measured['storage']['rdf_triples_materialized'] is None
    assert measured['storage']['neo4j_relationships_materialized'] is None
    assert receipt['artifact_total_bytes'] == sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
    assert receipt['receipt_bytes'] == (root/'receipt.json').stat().st_size
    assert receipt['generation_resources']['wall_seconds'] > 0
    assert receipt['generation_resources']['process_peak_rss_bytes'] > 0
    for key in ('statistics', 'metrics_csv', 'metrics_markdown'):
        pin = receipt[key]
        b = (root/pin['path']).read_bytes()
        assert len(b) == pin['bytes'] and hashlib.sha256(b).hexdigest() == pin['sha256']
    csv_rows = {r['metric']:r for r in csv.DictReader((root/'graph-metrics.csv').open())}
    assert int(csv_rows['nodes']['value']) == len(nodes)
    assert int(csv_rows['edges']['value']) == len(edges)


def test_bad_generated_scalar_never_publishes_measured_success(tmp_path, monkeypatch):
    original = scale.iter_transfers
    def invalid(*args, **kwargs):
        for row in original(*args, **kwargs):
            yield row[:-2]+('1.5', row[-1])
    monkeypatch.setattr(scale, 'iter_transfers', invalid)
    with pytest.raises(ValueError, match='invalid type'):
        _generate(tmp_path/'invalid', monkeypatch)
    assert not (tmp_path/'invalid/receipt.json').exists()
    assert not (tmp_path/'invalid/graph-statistics.json').exists()
