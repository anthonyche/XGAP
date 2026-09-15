"""New composed-method scheduling and supervision; no author/model network calls."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_fixed_information_frontend import setup
from test_practical_profile import no_network
from xgap.experiments import common_method_trial as common, practical_study as study, fixed_information_worker as worker
from xgap.experiments.nl_method_worker import run_nl
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.practical_methods import PRACTICAL_METHODS, FIXED_INFORMATION_METHODS


def schedule(root):
    _,_,p,q,_=setup(root)
    groups=[]
    for i in range(2):
        raw=json.loads(Path(q['path']).read_text());raw['question_id']=f'group-{i}'
        request=write_once(root/f'group-{i}.json',raw)
        groups.append({'profile':p,'request':request,'reference':{'path':str(root/f'unread-reference-{i}.json'),'sha256':'0'*64}})
    pin=write_once(root/'study-input.json',{'schema_version':study.SCHEMA_V2,'study_id':'explicit-compositions',
        'methods':list(PRACTICAL_METHODS),'groups':groups})
    return study.freeze_study(input_path=pin['path'],input_sha256=pin['sha256'],output=root/'frozen')


def test_explicit_v2_rotation_endpoints_and_resume_preserve_old_method_sets(tmp_path,monkeypatch):
    p=schedule(tmp_path);raw=json.loads(Path(p['path']).read_text());methods=list(PRACTICAL_METHODS)
    assert raw['methods']==methods and raw['maximum_top_level_method_attempts']==12
    assert [c['method'] for c in raw['cells']]==methods+methods[1:]+methods[:1]
    assert raw['profile_kind']=='practical_per_question_v2' and not raw['formal_campaign_ready']
    deployments=[];endpoints=[];calls=[];scores=[]
    observer=SimpleNamespace(base_url='http://localhost:9800')
    def deploy(cell):
        assert 'reference_for_post_seal_scoring_only' not in cell
        doc=json.loads(Path(cell['practical_profile']['path']).read_text())
        for spec in doc['backends'].values():spec['client']['url']=observer.base_url
        deployments.append(cell['cell_id'])
        return write_once(tmp_path/f'deployment-{cell["cell_id"]}.json',doc)
    def endpoint(cell):
        assert 'reference_for_post_seal_scoring_only' not in cell
        endpoints.append(cell['cell_id']);return 'http://method.invalid/'+cell['method']
    def trial(**kwargs):
        assert 'reference_path' not in kwargs
        method=kwargs['method'];q=json.loads(Path(kwargs['request_path']).read_text());calls.append(method)
        assert kwargs['owned_services']==['sources',method]
        assert kwargs['endpoint']==('http://method.invalid/'+method if method in FIXED_INFORMATION_METHODS else None)
        out=Path(kwargs['output']);out.mkdir(parents=True)
        r={'schema_version':'xgap-common-method-trial-v1','method':method,'track':'trusted_template',
            'question_id':q['question_id'],'success':True,'status':'controlled-response','can_continue_session':True}
        return {**r,'receipt':write_once(out/'receipt.json',r),'timing':{'total_online_ms':1}}
    monkeypatch.setattr(study,'run_practical_trial',trial)
    monkeypatch.setattr(study,'score_trial',lambda receipt,**kw:scores.append(receipt))
    def owned(cell):
        assert 'reference_for_post_seal_scoring_only' not in cell
        return ['sources',cell['method']]
    kwargs=dict(schedule_path=p['path'],schedule_sha256=p['sha256'],ledger=tmp_path/'ledger',
        observer=observer,owned_services=owned,deployment_for=deploy,endpoint_for=endpoint)
    rows=study.dispatch_practical_group(**kwargs)
    assert len(rows)==len(calls)==len(scores)==6 and len(endpoints)==4
    study.dispatch_practical_group(**kwargs)
    before=(len(calls),len(scores),len(deployments),len(endpoints))
    study.dispatch_practical_group(**kwargs)
    assert before==(12,12,12,8)==(len(calls),len(scores),len(deployments),len(endpoints))
    assert not list(tmp_path.glob('unread-reference-*.json'))
    from xgap.experiments.campaign_schedule import METHODS
    assert METHODS['natural_language']==('xgap-precision','xgap-performance','fedx','fedup')
    assert study.METHODS==('xgap-strong-exact','xgap-strong-performance')


@pytest.mark.parametrize('hosted',[False,True])
def test_common_supervision_requires_method_host_and_routes_composition_without_replay_substitution(tmp_path,monkeypatch,hosted):
    _,_,p,q,_=setup(tmp_path);commands=[];queries=[];stops=[]
    class Resources:
        def __init__(self,*a,**kw):pass
        def summary(self):return {'scope':'controlled local supervisor fixture'}
        def stop(self):stops.append(True);return {'complete':True,'recovery_ms':0}
    class Observer:
        def set_phase(self,phase):self.phase=phase
        def snapshot(self,phase):return {'requests':0,'failed_requests':0}
    def query(endpoint,text,*,seconds,output):
        queries.append(endpoint)
        result={'status':'returned','http_status':200,'body_utf8':'{"head":{"vars":[]},"results":{"bindings":[]}}','client_wall_ms':2}
        write_once(output,result);return result
    def guarded(command,**kw):
        commands.append(command)
        args={k:command[command.index('--'+k.replace('_','-'))+1] for k in
            ('request_path','request_sha256','profile_path','profile_sha256','method','output','endpoint')}
        run_nl(**args)
        return {'success':True,'status':'completed'}
    monkeypatch.setattr(worker,'query_once',query)
    monkeypatch.setattr(common,'OwnedResources',Resources);monkeypatch.setattr(common,'run_guarded_command',guarded)
    owned=[SimpleNamespace(role='source')]+([SimpleNamespace(role='method_host')] if hosted else [])
    result=common.run_practical_trial(request_path=q['path'],request_sha256=q['sha256'],profile_path=p['path'],profile_sha256=p['sha256'],
        method='fixed-info-performance-fedx',endpoint='http://method.invalid/sparql',output=tmp_path/'trial',
        owned_services=owned,observer=Observer())
    assert result['success'] is hosted,result
    assert len(queries)==len(commands)==int(hosted)
    if hosted:
        assert result['external_engine']=='fedx' and result['information_strategy']=='fixed_action_order_v1'
        assert result['track']=='trusted_template' and result['strong_plan'] is None
        assert result['model_calls']==0 and result['top_level_attempts']==1
        assert result['timing']['total_online_ms']>0 and result['can_continue_session']
    else:
        assert 'must be owned' in result['error'] and len(stops)==1


def test_composed_methods_cannot_be_inserted_into_legacy_nl_track(tmp_path):
    _,_,p,q,_=setup(tmp_path)
    with pytest.raises(ValueError,match='declared track'):
        common.run_nl_trial(request_path=q['path'],request_sha256=q['sha256'],profile_path=p['path'],profile_sha256=p['sha256'],
            method='fixed-info-exact-fedup',endpoint='http://method.invalid/sparql',output=tmp_path/'trial',owned_services=[],observer=None)
