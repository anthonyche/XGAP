"""Decimal factors survive publication and dispatch without renaming frozen cases."""
from dataclasses import asdict
import pytest
import release_ch6_five_method_batch as publication
import run_bounded_joint_batch as dispatch
from xgap.experiments.batch_cell_identity import validate_cell_id
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.unified_contract import configuration


@pytest.mark.parametrize('scale',['0.25','1.0','4.0'])
def test_scale_identity_reaches_real_publisher_and_manifest_validator(tmp_path,monkeypatch,scale):
    monkeypatch.setattr(publication,'source_commit',lambda:'test-fixture')
    def save(n,d):return write_once(tmp_path/(n+'.json'),d)
    cid='D1-graph_scale-'+scale+'-D1-test-uniform-window_edge-000-W3'
    prepared=save('prepared',dict(success=True,profile=save('profile',{})))
    config=save('config',configuration())
    request=save('request',dict(question_id=cid,question='Fixed original NL'))
    reference=save('reference',dict(question_id=cid,rows=[]))
    unused=dict(path=str(tmp_path/'private-not-read.json'),sha256='a'*64)
    spec=dict(schema_version='xgap-ch6-batch-input-v1',deployment='rdf',input_track='nl',exposure='test',
        order_seed=20260923,prepared=prepared,external_runtime=save('external',{}),base_configuration=config,
        design=dict(total_wall_seconds=3600,package_max_bytes=10**9,free_disk_reserve_bytes=10**9,
            method_wall_seconds=300,method_rss_bytes=10**9,source_rss_bytes=10**9,startup_seconds=120,
            source_budget=asdict(SourceObservationBudget())),
        cases=[dict(case_id=cid,request=request,reference=reference,scope=unused,oracle=unused)])
    ip=save('input',spec);result=publication.publish(spec_path=ip['path'],spec_sha256=ip['sha256'],output=tmp_path/'units')
    manifest=load_pin(result['manifest']);dispatch.validate(manifest)
    assert len(manifest['cells'])==5
    assert all(b['case_id']==cid for b in result['bindings'])
    assert {c['cell_id'] for c in manifest['cells']}=={cid+'-'+m for m in ('XGAP','NP','SH','GR','TS')}
    assert all(c['request']==request and c['reference']==reference for c in manifest['cells'])
    ts=next(c for c in manifest['cells'] if c['method']=='aruqula-fedx')
    assert set(ts)=={'cell_id','method','request','reference'}


@pytest.mark.parametrize('value',['','.', '..', '../escape', '/abs', 'q/child', 'q\\child',
    '.hidden', '-option', 'q\n', 'q\x00', 'q'*97, None])
def test_unsafe_path_components_and_unbounded_names_remain_rejected(value):
    with pytest.raises(ValueError,match='Invalid cell ID'):validate_cell_id(value)


@pytest.mark.parametrize('ids',[['../escape'],['same','same']])
def test_bad_ids_fail_before_partial_publication(tmp_path,monkeypatch,ids):
    monkeypatch.setattr(publication,'source_commit',lambda:pytest.fail('Must reject before creating outputs'))
    ip=write_once(tmp_path/'input.json',dict(schema_version='xgap-ch6-batch-input-v1',methods=['XGAP'],
        cases=[dict(case_id=i) for i in ids]))
    with pytest.raises(ValueError,match='cell ID'):
        publication.publish(spec_path=ip['path'],spec_sha256=ip['sha256'],output=tmp_path/'units')
    assert not (tmp_path/'units').exists()
