"""New common-input, scoring and owned-process boundaries only."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from xgap.experiments.common_row_score import sparql_values, score_trial, XSD
from xgap.experiments.finbench_one_shot_population import normalization
from xgap.experiments.finbench_rdf import FAMILIES
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.owned_resources import OwnedProcess, OwnedResources
from xgap.experiments.process_guard import ProcessBudget, run_guarded_command, _stop_group
from xgap.experiments.schema_source_routing import source_assignments
from xgap.semantic.program import SemanticGraphProgram

ROOT=Path('/Users/anthonyche/xgap-data/rdf-instances-native-20260913-v1')


def test_source_placement_uses_schema_and_actual_fields_without_gold_slots():
    profile=json.loads((ROOT/'rdf-profile/profile.json').read_text())
    for family in ('F1','F2','F3'):
        saved=json.loads((ROOT/(family+'-plan.json')).read_text())
        program=SemanticGraphProgram.from_dict(saved['program'])
        assigned,trace=source_assignments(program,profile['source_schema'],profile['sources'])
        assert set(assigned.values())=={'graph','control'}
        assert not trace['source_assignment_from_gold']
        for op in program.operators:
            if not op.input_ids and 'edge' in op.parameters:assert assigned[op.operator_id]=='graph'
        # Entity stubs may be read from either schema-declared source. Stable ID
        # order selects control, unlike the historical hand-authored graph slot.
        if family=='F1':assert assigned['companies']=='control' and saved['operator_sources']['companies']=='graph'
    op=program.operators[0]
    bad=replace(op,parameters={**op.parameters,'properties':{'secret':'undeclared_column'}})
    with pytest.raises(ValueError,match='No declared source'):
        source_assignments(replace(program,operators=(bad,*program.operators[1:])),profile['source_schema'],profile['sources'])


def document(rows):
    return {'head':{'vars':['company_id','total_amount']},'results':{'bindings':[
        {'company_id':{'type':'literal','value':company},
         'total_amount':{'type':'literal','value':amount,'datatype':XSD+'decimal'}} for company,amount in rows]}}


def scored(root, *, method='fedx',answer=None,success=True,expected=None):
    root.mkdir();dataset={'dataset_id':'tiny','version':'v1'}
    result=write_once(root/'answer.json',{'answer_format':'sparql_json' if method!='xgap-rdf' else 'json_rows','answer':answer})
    receipt=write_once(root/'receipt.json',{'schema_version':'xgap-common-method-trial-v1','method':method,
        'track':'fixed_semantics','question_id':'q','dataset':dataset,'population':'development','exposure':'synthetic',
        'success':success,'status':'returned' if success else 'failed','result':result})
    reference=write_once(root/'reference.json',{'schema_version':'xgap-normalized-row-reference-v1','question_id':'q',
        'dataset':dataset,'ordered':True,'normalization':normalization(FAMILIES[2]),'rows':expected or []})
    return score_trial(receipt['path'],receipt_sha256=receipt['sha256'],reference_path=reference['path'],
        reference_sha256=reference['sha256'],output=root/'score.json')


def test_external_numeric_equivalence_preserves_wrong_order_and_duplicate_evidence(tmp_path):
    expected=[{'company_id':'001','total_amount':'10.125'},{'company_id':'002','total_amount':'2.000'}]
    a=scored(tmp_path/'rdf',answer=document([('001','10.1250'),('002','2.0')]),expected=expected)
    b=scored(tmp_path/'native',method='xgap-rdf',answer=expected,expected=expected)
    assert a['answer_em']==b['answer_em']==1
    wrong=scored(tmp_path/'order',answer=document([('002','2'),('001','10.125')]),expected=expected)
    assert wrong['answer_em']==0 and wrong['answer_row_multiset_f1']==1
    duplicate=scored(tmp_path/'bag',answer=document([('001','10.125'),('002','2'),('002','2')]),expected=expected)
    assert duplicate['answer_em']==0 and duplicate['answer_row_multiset_f1']==pytest.approx(.8)


def test_failed_empty_and_wrong_rdf_term_types_are_not_repaired(tmp_path):
    result=scored(tmp_path/'failure',success=False,answer=None,expected=[])
    assert result['answer_em']==result['answer_row_multiset_f1']==0
    spec=normalization(FAMILIES[2]);raw=document([('001','10')])
    for change in ({'type':'uri'},{'xml:lang':'en'},{'datatype':XSD+'integer'}):
        altered=deepcopy(raw);altered['results']['bindings'][0]['company_id'].update(change)
        with pytest.raises(ValueError):sparql_values(altered,spec)
    altered=deepcopy(raw);altered['head']['vars'].append('company_id')
    with pytest.raises(ValueError):sparql_values(altered,spec)


def test_common_worker_host_rss_limit_cleans_owned_groups_and_preserves_unrelated_process(tmp_path):
    processes=[]
    def spawn():
        p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)'],start_new_session=True,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);processes.append(p);return p
    try:
        source,host,unrelated=spawn(),spawn(),spawn()
        mon=OwnedResources([OwnedProcess('source','source',source),OwnedProcess('method','method_host',host)],method_rss_bytes=1)
        guard=run_guarded_command([sys.executable,'-c','import time; time.sleep(10)'],cwd=tmp_path,output=tmp_path/'guard',
            budget=ProcessBudget(wall_seconds=3),resource_monitor=mon)
        assert guard['status']=='method_rss_limit_observed' and guard['cleanup']['complete']
        assert guard['requires_external_quiescence_barrier']
        assert mon.summary()['sampled_peak_rss_bytes']['method']>1
        barrier=mon.stop()
        assert barrier['complete'] and barrier['new_serving_session_required']
        assert source.poll() is not None and host.poll() is not None and unrelated.poll() is None
    finally:
        for p in processes:_stop_group(p,ProcessBudget())


def test_host_exit_is_terminal_even_if_worker_would_return_success(tmp_path):
    source=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)'],start_new_session=True)
    host=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)'],start_new_session=True)
    try:
        mon=OwnedResources([OwnedProcess('source','source',source),OwnedProcess('method','method_host',host)])
        _stop_group(host,ProcessBudget())
        guard=run_guarded_command([sys.executable,'-c','pass'],cwd=tmp_path,output=tmp_path/'guard',
            budget=ProcessBudget(wall_seconds=3),resource_monitor=mon)
        assert not guard['success'] and guard['status']=='owned_service_exited'
        assert mon.stop()['complete'] and source.poll() is not None
    finally:
        _stop_group(source,ProcessBudget());_stop_group(host,ProcessBudget())


def test_external_fixed_worker_rejects_source_pinned_query_before_dispatch(tmp_path,monkeypatch):
    from xgap.experiments import fixed_semantic_worker as module
    monkeypatch.setattr(module,'query_once',lambda *a,**k:pytest.fail('Source-pinned query reached external method'))
    q=write_once(tmp_path/'request.json',{'schema_version':module.REQUEST_SCHEMA,'question_id':'q',
        'dataset':{'dataset_id':'tiny','version':'v1'},'population':'development','exposure':'synthetic',
        'program':{},'sparql':'SELECT ?s WHERE { SERVICE <http://example.invalid/query> { ?s ?p ?o } }'})
    result=module.run_fixed(request_path=q['path'],request_sha256=q['sha256'],method='fedx',output=tmp_path/'worker',
        endpoint='http://127.0.0.1:1/sparql')
    assert not result['success'] and result['top_level_attempts']==0
    assert 'source selection unresolved' in result['error']
