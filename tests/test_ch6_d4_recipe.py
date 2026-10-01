import json
from types import SimpleNamespace

from xgap.experiments.ch6_d4_recipe import prepare, execute, queries
from xgap.experiments.ch6_synthetic import generate
from xgap.experiments.ch6_materialize import materialize
from xgap.experiments.ch6_sql_reference import evaluate
from xgap.semantic.compact_query import validate_query
from xgap.semantic.compact_lowering import lower_compact_query


def test_d4_tiny_index_materialization_schema_reference_boundary(tmp_path, monkeypatch):
    # Only the free-capacity gate is mocked; actual files/schema/SQL are exercised.
    monkeypatch.setattr('shutil.disk_usage', lambda _: SimpleNamespace(free=1024**4))
    index=generate(tmp_path/'index',nodes=32,degree=8,seed=20260926,reserve_bytes=0)
    material=materialize(index['path'],tmp_path/'material',scale='1',source_count=2)
    assert material['success'] and material['dataset']=='D4'
    assert material['counts']==dict(nodes=32,original_edges=256,view_edges=512)
    schema=json.loads((tmp_path/'material/source-schema.json').read_text())
    generator=json.loads((tmp_path/'index/generator.json').read_text())
    for name,q in queries().items():
        validate_query(q,version='v2')
        program,assignment=lower_compact_query(q,schema,version='v2',optimize=True)
        assert program.operators
        assert 'graph' in assignment.values()
        assert set(assignment.values()) <= {'graph','control'}
        if name=='anchored_marked_edge': assert 'control' in assignment.values()
        expected=sorted(f'entity:{i:09d}' for i in generator['offsets']
                        if name=='anchored_edge' or i%4==0)
        actual=evaluate(q,index['path'])
        assert actual['rows']==[dict(result=i) for i in expected]


def test_d4_recipe_dry_run_keeps_declared_grid_and_does_not_require_server(tmp_path):
    recipe=prepare(tmp_path/'recipe',source_commit='a'*40,
                   remote_output='/home/hxc859/xgap-ch6-artifacts/D4-offline-new-v1')
    result=execute(recipe['path'],recipe['sha256'])
    assert result['executed'] is False
    assert [r['nodes'] for r in result['levels']]==[16384,65536,262144]
    assert [r['edges'] for r in result['levels']]==[131072,524288,2097152]
    assert all(r['materializer_scale']=='1' for r in result['levels'])
