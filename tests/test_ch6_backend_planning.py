"""The admission planner executes one selected plan on a real tiny RDF graph."""
from copy import deepcopy
from types import SimpleNamespace
import json
import pytest
import check_ch6_core_backend as gate
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.scope_authority import private_query_intent
from xgap.experiments.bounded_joint_toy import local_runtime,QUESTION
from xgap.experiments.ch6_fact_index import pin,write


@pytest.mark.parametrize('planning',('fixed_scan','unified'))
def test_complete_query_admission_executes_only_one_selected_plan(tmp_path,monkeypatch,planning):
    data,options,calls=local_runtime();q=deepcopy(data['query_template']);q['contribution_by']=q.pop('deduplicate_by')
    doc={'source_schema':options['source_schema']}
    predictions=[]
    def predict(plan):
        predictions.append(plan)
        return SimpleNamespace(status='unavailable',estimated_ms=None,to_dict=lambda:{'status':'unavailable'})
    # FrozenOneShotProfile returns estimator second, catalog third. Neither is
    # None: the fixture must catch accidentally swapping these two contracts.
    materialized=(doc,SimpleNamespace(predict=predict),object(),options['sources'],options['backends'],{}, {'performance':(options['physical_profile'],None)})
    monkeypatch.setattr(gate,'FrozenOneShotProfile',SimpleNamespace(load=lambda *_args,**_kwargs:SimpleNamespace(materialize=lambda:materialized)))
    monkeypatch.setattr(gate,'native_clients',lambda _:options['backend_clients'])
    write(tmp_path/'oracle.json',private_query_intent(QUESTION,q,language_version='v2'))
    write(tmp_path/'request.json',dict(question=QUESTION))
    snapshot=snapshot_identity(options['sources'],options['backends'],options['source_schema'])
    write(tmp_path/'bundle.json',dict(cases=[dict(case_id='case',oracle=pin(tmp_path/'oracle.json'),request=pin(tmp_path/'request.json'),source_snapshot_sha256=snapshot)]))
    assert gate.worker(pin(tmp_path/'bundle.json'),'case',dict(path='fixture',sha256='fixture'),tmp_path/'worker',planning)==0
    result=json.loads((tmp_path/'worker/receipt.json').read_text())
    answer=json.loads((tmp_path/'worker/answer.json').read_text())
    assert result['success'] and result['final_plan_executions']==1 and result['model_calls']==0
    assert result['backend_calls']==len(calls)>0
    assert answer['rows']==data['expected']
    if planning=='unified':
        assert predictions
        report=json.loads((tmp_path/'worker/planning.json').read_text())
        assert report['external_calls_during_search']==0 and report['final_plan_executions']==1
