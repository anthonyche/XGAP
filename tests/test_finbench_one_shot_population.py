"""New source-only selection, reference and value-equivalence risks only."""

from collections import Counter
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from test_finbench_rdf import tiny_partition, parameters, expected_rows
from xgap.experiments.finbench_one_shot_population import (DESIGN, FAMILIES, normalization,
    reference_rows, select_population, overlap, build_population)
from xgap.experiments.m15_finbench_artifacts import load_finbench_artifact_lock
from xgap.experiments.m15_finbench_workload import load_finbench_query_data
from xgap.experiments.one_shot_records import write_once, evaluate_record
from xgap.experiments.row_normalization import normalize_rows


@pytest.fixture(scope='module')
def data(tmp_path_factory):
    root=tmp_path_factory.mktemp('new-reference')
    tiny_partition(root)
    return load_finbench_query_data(root/'tiny.tar.gz',load_finbench_artifact_lock(root/'lock.json'))


def test_independent_csv_reference_retains_financial_boundary_and_parallel_meanings(data):
    for f,p,wanted in zip(FAMILIES,parameters(),expected_rows()):
        assert normalize_rows(reference_rows(data,f,p),normalization(f))==normalize_rows(wanted,normalization(f))
    duplicate=replace(data.transfers[0],order_num='new-equal-valued-edge')
    augmented=replace(data,transfers=data.transfers+(duplicate,))
    assert normalize_rows(reference_rows(augmented,FAMILIES[2],parameters()[2]),normalization(FAMILIES[2]))==[
        {'company_id':'1','total_amount':'66.125'}]


def frame_data(data):
    # Source-only frame with200 anchors; emptiness cannot influence selection.
    return replace(data,people={str(i):{} for i in range(200)},accounts={str(i):{} for i in range(200)},
        person_by_account={str(i):str(i) for i in range(200)},company_by_account={},
        transfers=(),outgoing={},media_by_account={})


def test_sampling_balances_disjoint_groups_and_excludes_old_anchors_without_answers(data,monkeypatch):
    from xgap.experiments import finbench_one_shot_population as module
    monkeypatch.setattr(module,'reference_rows',lambda *a,**kw:pytest.fail('Reference consulted while sampling'))
    design=json.loads(DESIGN.read_text())
    old=[{'family_id':FAMILIES[0],'parameters':{**parameters()[0],'person_id':str(i)}} for i in range(16)]
    old += [{'family_id':FAMILIES[1],'parameters':{**parameters()[1],'start_account_id':str(i)}} for i in range(16)]
    selected,summary=select_population(frame_data(data),old,design)
    assert len(selected)==120 and Counter(i['split'] for i in selected)=={'development':24,'estimator_training':48,'evaluation':48}
    assert len({(i['family_id'],i['group_key']) for i in selected})==120
    assert all(i['group_key'] not in {str(j) for j in range(16)} for i in selected if i['family_id']!=FAMILIES[2])
    windows=[i['parameters'] for i in selected if i['family_id']==FAMILIES[2]]
    assert all(overlap(a,b)==0 for n,a in enumerate(windows) for b in windows[n+1:])
    # Existing identical interval must be excluded before sampling, without answers.
    old.append({'family_id':FAMILIES[2],'parameters':windows[0]})
    _,changed=select_population(frame_data(data),old,design)
    assert summary['excluded_near_duplicate_intervals']==0 and changed['excluded_near_duplicate_intervals']==1


def score(tmp_path,actual,expected,*,success=True):
    root=tmp_path/str(len(list(tmp_path.iterdir())));root.mkdir()
    result=write_once(root/'result.json',{'success':success,'answer_rows':actual})
    dataset={'dataset_id':'controlled-test','version':'v1'}
    receipt=write_once(root/'receipt.json',{'schema_version':'xgap-one-shot-evaluation-record-v1',
        'operation':'execute','result':result,'success':success,'question_id':'q','dataset':dataset,
        'mode':'performance','execution_kind':'controlled-test','population':'toy','exposure':'development','status':'answered' if success else 'failed'})
    reference=write_once(root/'reference.json',{'schema_version':'xgap-normalized-row-reference-v1',
        'question_id':'q','dataset':dataset,'ordered':True,'rows':expected,'normalization':normalization(FAMILIES[2])})
    return evaluate_record(receipt['path'],receipt_sha256=receipt['sha256'],reference_path=reference['path'],
        reference_sha256=reference['sha256'],output=root/'score.json')


def test_normalization_preserves_order_and_bag_evidence(tmp_path):
    expected=[{'company_id':'a','total_amount':'2.000'},{'company_id':'b','total_amount':'1.200'}]
    actual=[{'company_id':'a','total_amount':2},{'company_id':'b','total_amount':1.2}]
    assert score(tmp_path,actual,expected)['answer_em']==1
    reversed_score=score(tmp_path,actual[::-1],expected)
    assert reversed_score['answer_em']==0 and reversed_score['answer_row_multiset_f1']==1
    duplicate_score=score(tmp_path,actual+[actual[0]],expected)
    assert duplicate_score['answer_em']==0 and duplicate_score['answer_row_multiset_f1']==0.8
    assert actual[0]['total_amount']==2  # Input rows were not mutated or reordered.


def test_invalid_and_failed_answers_never_match_empty_reference(tmp_path):
    invalid=score(tmp_path,[{'wrong_field':3}],[])
    assert invalid['execution_success'] and invalid['comparison_error'] and invalid['answer_em']==invalid['answer_row_multiset_f1']==0
    assert score(tmp_path,[],[],success=False)['answer_em']==0
    assert score(tmp_path,[],[])['answer_em']==1
    for value in (True,float('nan'),'1e999999'):
        with pytest.raises(ValueError):normalize_rows([{'company_id':'a','total_amount':value}],normalization(FAMILIES[2]))


def test_population_files_seal_selection_before_references_and_keep_gold_separate(data,monkeypatch,tmp_path):
    from xgap.experiments import finbench_one_shot_population as module
    design=json.loads(DESIGN.read_text()); old=tmp_path/'old.json';old.write_text('{"instances":[]}')
    design['excluded_public_sha256']=hashlib.sha256(old.read_bytes()).hexdigest()
    design_path=tmp_path/'design.json';design_path.write_text(json.dumps(design))
    monkeypatch.setattr(module,'load_finbench_query_data',lambda *a:frame_data(data))
    root=tmp_path/'population'; original=reference_rows
    def checked_reference(*args):
        assert (root/'selection.json').is_file()
        return original(*args)
    monkeypatch.setattr(module,'reference_rows',checked_reference)
    result=build_population(archive='not-opened-in-controlled-fixture',
        lock_path='experiments/artifacts/m15_finbench_v010_sf0_1_sources.json',excluded_public=old,output=root,design_path=design_path)
    manifest=json.loads(Path(result['path']).read_text())
    assert manifest['instance_count']==120 and manifest['model_calls']==manifest['backend_calls']==0
    for entry in manifest['artifacts']:
        request=json.loads(Path(entry['files']['request']['path']).read_text())
        assert set(request)=={'schema_version','question_id','question','population','exposure'}
        assert request['question_id']==entry['question_id']
        gold=json.loads(Path(entry['files']['gold']['path']).read_text())
        assert not gold['runtime_input'] and gold['program']['operators'] and 'SERVICE' not in gold['reference_sparql']
