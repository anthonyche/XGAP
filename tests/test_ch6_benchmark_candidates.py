import hashlib,json
import pytest
from prepare_ch6_benchmark_candidates import source_bytes,intake,root_tree_hash


def test_benchmark_source_identity_is_content_bound_not_a_user_supplied_label(tmp_path):
    raw=b'[{"uid":1}]';source=tmp_path/'raw.json';source.write_bytes(raw)
    blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    leaf=dict(path='test.json',type='blob',mode='100644',sha=blob,size=len(raw))
    entries=[dict(path='dataset',type='tree',mode='040000',sha=root_tree_hash([leaf])),
             dict(path='dataset/test.json',type='blob',mode='100644',sha=blob,size=len(raw))]
    tree=tmp_path/'tree.json';tree.write_text(json.dumps(dict(sha='commit',truncated=False,tree=entries)))
    commit=tmp_path/'commit.json';commit.write_text(json.dumps(dict(commit='commit',tree=root_tree_hash(entries))))
    assert source_bytes(source,tree,commit)[0]==raw
    source.write_bytes(b'[{"uid":2}]')
    with pytest.raises(ValueError,match='Git tree'):source_bytes(source,tree,commit)


def test_intake_preserves_rejection_and_exposure_without_claiming_domain_workload(tmp_path,monkeypatch):
    import prepare_ch6_benchmark_candidates as module
    rows=[{}]*128+[dict(uid=1,sparql_wikidata='old'),dict(uid=2,sparql_wikidata='new'),dict(uid=3,sparql_wikidata='bad')]
    monkeypatch.setattr(module,'source_bytes',lambda *a:(json.dumps(rows).encode(),dict(commit='c',sha256='s')))
    previous=tmp_path/'old.jsonl';previous.write_text(json.dumps(dict(source_version=dict(commit='c',sha256='s'),structure_hash='old'))+'\n')
    def extract(row,**kwargs):
        h=row['sparql_wikidata'];return dict(uid=row['uid'],status='rejected' if h=='bad' else 'extracted_pending_domain_admission',
            structure_hash=h,raw_query_sha256=h,structure_categories=['S01'],raw_query=h)
    monkeypatch.setattr(module,'extract',extract)
    out=tmp_path/'out';receipt=intake('unused','unused','unused',previous,out,count=3)
    records=[json.loads(s) for s in (out/'source-candidates.jsonl').read_text().splitlines()]
    assert len(records)==3 and receipt['new_source_structures']==1
    assert receipt['counts']==dict(previously_exposed_source_structure=1,pending_domain_admission=1,source_rejected=1)
    assert all(not r['formal_evaluation_ready'] and not r['cross_ir_development_overlap_checked'] for r in records)
    assert receipt['domain_queries_generated']==receipt['model_calls']==receipt['backend_calls']==0
