from pathlib import Path
import pytest
from prepare_rdf_tdb import stream_pin
from xgap.experiments.verified_store_copy import copy_sealed_store


def test_copy_verifies_stream_once_and_preserves_native_parts(tmp_path,monkeypatch):
    source=tmp_path/'frozen';(source/'data/empty').mkdir(parents=True);(source/'transactions').mkdir()
    (source/'data/index').write_bytes(b'a'*1500000);(source/'transactions/log').write_bytes(b'tx')
    (source/'engine-not-part-of-store').write_bytes(b'not copied')
    files=[stream_pin(p) for p in (source/'data/index',source/'transactions/log')]
    original=Path.open;reads=[]
    def counted(p,mode='r',*a,**kw):
        if p in [Path(x['path']) for x in files] and mode=='rb':reads.append(p)
        return original(p,mode,*a,**kw)
    monkeypatch.setattr(Path,'open',counted)
    destination=tmp_path/'serving';report=copy_sealed_store(source,destination,files,parts=('data','transactions'))
    assert report['content_verified'] and len(reads)==2 and report['bytes']==1500002
    assert (destination/'data/index').read_bytes()==b'a'*1500000
    assert (destination/'data/empty').is_dir() and not (destination/'engine-not-part-of-store').exists()
    with pytest.raises(ValueError,match='new'):copy_sealed_store(source,destination,files,parts=('data','transactions'))


def test_copy_refuses_changed_bytes_inventory_and_links(tmp_path):
    source=tmp_path/'frozen';source.mkdir();p=source/'index';p.write_bytes(b'one');files=[stream_pin(p)]
    p.write_bytes(b'two')
    with pytest.raises(ValueError,match='content changed'):copy_sealed_store(source,tmp_path/'bad-content',files)
    p.write_bytes(b'one');(source/'extra').write_bytes(b'x')
    with pytest.raises(ValueError,match='inventory'):copy_sealed_store(source,tmp_path/'bad-inventory',files)
    (source/'extra').unlink();(source/'redirect').symlink_to(p)
    with pytest.raises(ValueError,match='links'):copy_sealed_store(source,tmp_path/'bad-link',files)


def test_separate_workspace_is_accounted_and_only_copies_are_removed(tmp_path):
    import time
    from rdf_tdb_session import RdfTdbSession
    from run_bounded_joint_batch import BatchBudget
    from xgap.experiments.one_shot_records import write_once
    from xgap.experiments.campaign_source_observer import SourceObservationBudget
    from xgap.experiments.m15_native_services import _neo4j_configuration
    frozen=tmp_path/'input';frozen.mkdir();(frozen/'original').write_bytes(b'source')
    pin=write_once(frozen/'prepared.json',dict(success=True,input_seal={'path':'unused','sha256':'frozen'},stores={'graph':{}}))
    root=tmp_path/'evidence';local=tmp_path/'node-local'
    session=RdfTdbSession(root=root,prepared_path=pin['path'],prepared_sha256=pin['sha256'],
        budget=SourceObservationBudget(),serving_root=local,discard_serving_copies=True)
    (local/'graph-tdb2').mkdir();(local/'graph-tdb2/store').write_bytes(b'x'*100)
    (root/'evidence.txt').write_bytes(b'evidence')
    budget=BatchBudget(root,dict(total_wall_seconds=100,package_max_bytes=100,free_disk_reserve_bytes=1),
        time.time(),extra_roots=(local,))
    assert budget.sample([])=='study_disk_budget' and budget.size>=108
    cfg=_neo4j_configuration(neo4j_root=Path('/engine'),state_root=root,http_port=1,bolt_port=2,
        resource_profile=dict(heap_initial_size='256m',heap_max_size='768m',pagecache_size='128m'),
        query_timeout_seconds=60,data_root=local/'neo4j')
    assert 'server.directories.data='+str(local/'neo4j/data') in cfg
    assert 'server.directories.logs='+str(root/'neo4j/logs') in cfg
    report=session.close()
    assert report['serving_copy_reclamation_complete'] and not (local/'graph-tdb2').exists()
    assert (root/'evidence.txt').read_bytes()==b'evidence' and (frozen/'original').read_bytes()==b'source'
    with pytest.raises(ValueError,match='disjoint'):
        BatchBudget(root,{},time.time(),extra_roots=(root/'nested',))
