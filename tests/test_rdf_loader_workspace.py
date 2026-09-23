"""Node-local preprocessing must publish identical, durable sealed stores."""
import json
from pathlib import Path
from types import SimpleNamespace

import prepare_rdf_tdb as loader


def inputs(tmp_path, monkeypatch):
    sources = {}
    for name in ('control', 'graph'):
        source = tmp_path / (name + '.ttl')
        source.write_text('<urn:a> <urn:p> <urn:b> .\n')
        sources[name] = loader.stream_pin(source)
    profile = tmp_path / 'profile.json'
    profile.write_text(json.dumps({'dataset': 'toy', 'offline': {'rdf_loads': sources}}))
    java = tmp_path / 'java'; java.write_bytes(b'java fixture')
    jar = tmp_path / 'fuseki.jar'; jar.write_bytes(b'jar fixture')
    monkeypatch.setattr(loader.subprocess, 'check_output',
                        lambda args, **kw: '' if 'status' in args else 'a' * 40)
    monkeypatch.setattr(loader.shutil, 'disk_usage',
                        lambda path: SimpleNamespace(free=1024 * loader.GIB))

    def guarded(args, **kwargs):
        store = Path(args[args.index('--loc') + 1]); store.mkdir()
        (store / 'Data-0001').mkdir()
        (store / 'Data-0001' / 'index.dat').write_bytes(b'frozen index ' + store.name.encode())
        return {'success': True, 'returncode': 0}

    monkeypatch.setattr(loader, 'run_guarded_command', guarded)
    return dict(profile=profile, profile_sha256=loader.stream_pin(profile)['sha256'],
                java=java, fuseki_jar=jar, output=tmp_path / 'durable',
                work_root=tmp_path / 'scratch', max_store_bytes=256 * 1024**2)


def test_verified_node_local_copy_is_durable_and_reclaimed(tmp_path, monkeypatch):
    args = inputs(tmp_path, monkeypatch)
    args['max_rss_bytes']=16*loader.GIB
    assert loader.prepare(**args) == 0
    receipt = json.loads((args['output'] / 'receipt.json').read_text())
    assert receipt['success'] and receipt['sources_unchanged']
    assert receipt['workspace']['reclaimed'] and not args['work_root'].exists()
    assert receipt['durable_store_bytes'] > 0
    seal=json.loads(Path(receipt['input_seal']['path']).read_text())
    assert seal['process_budget_per_source']['max_group_rss_bytes']==16*loader.GIB
    for store in receipt['stores'].values():
        seal = json.loads(Path(store['seal']['path']).read_text())
        assert Path(store['path']).is_relative_to(args['output'])
        assert all(loader.stream_pin(pin['path']) == pin for pin in seal['files'])
    assert all(load['durable_copy_verified'] for load in receipt['loads'])


def test_corrupted_copy_cannot_publish_success(tmp_path, monkeypatch):
    args = inputs(tmp_path, monkeypatch)
    copy = loader.shutil.copytree
    def corrupt(source, destination, *args, **kwargs):
        result = copy(source, destination, *args, **kwargs)
        target = Path(destination) / 'Data-0001' / 'index.dat'
        if target.exists(): target.write_bytes(b'corrupt')
        return result
    monkeypatch.setattr(loader.shutil, 'copytree', corrupt)
    assert loader.prepare(**args) == 1
    receipt = json.loads((args['output'] / 'receipt.json').read_text())
    assert not receipt['success'] and receipt['stores'] == {}
    assert 'differs' in receipt['error'] and args['work_root'].exists()


def test_overlapping_workspace_rejected_before_loading(tmp_path, monkeypatch):
    args = inputs(tmp_path, monkeypatch); args['work_root'] = args['output'] / 'scratch'
    assert loader.prepare(**args) == 1
    receipt = json.loads((args['output'] / 'receipt.json').read_text())
    assert not receipt['loads'] and 'disjoint' in receipt['error']
