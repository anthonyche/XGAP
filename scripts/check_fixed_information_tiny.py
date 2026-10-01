#!/usr/bin/env python3
"""One new shared partially bound group; native outcomes are never repaired."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

from campaign_method_hosts import CampaignMethodHosts
from rdf_tdb_session import RdfTdbSession
from xgap.agent.practical_planning import program_identity
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.practical_methods import PRACTICAL_METHODS, external_engine
from xgap.experiments.practical_profile import FrozenPracticalProfile
from xgap.experiments.practical_study import SCHEMA_V2, freeze_study, dispatch_practical_group

REPO = Path(__file__).resolve().parents[1]
BASE = Path('/Users/anthonyche/xgap-data/disjoint-rdf-trial-20260913-v2/rdf-profile-v2/profile.json')
BASE_SHA = 'ef8131b3316f2ea83921a3b857576347f4d6058d4d52285b32b7a461cfa7ed89'


def pin(path):
    path=Path(path).resolve()
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def publish_inputs(root):
    root.mkdir(parents=True,exist_ok=False)
    base=json.loads(read_pinned(BASE,BASE_SHA))
    template={'schema_version':'m15-e3-semantic-intake-template-v1','template_id':'shared-class-tiny',
        'template_version':'1','holes':[{'hole_id':'entity_type','kind':'type','phrases':['selected entity class'],'required':True}],
        'constraints':[],'roots':['result'],'metadata':{'scope':'authored trusted structure; controlled conflicting prediction'},
        'operators':[{'operator_id':'entities','kind':'match','input_ids':[],'input_kinds':[],'output_kind':'binding_set',
            'parameters':{'node':{'label':{'$hole':'entity_type'}},'entity_field':'entity','properties':{'business_id':'id'}},
            'required_capabilities':[],'hole_ids':['entity_type']},
            {'operator_id':'result','kind':'project','input_ids':['entities'],'input_kinds':['binding_set'],'output_kind':'binding_set',
            'parameters':{'projections':{'business_id':{'kind':'field','field':'business_id'}}},
            'required_capabilities':[],'hole_ids':[]}]}
    write_once(root/'intake.json',template)
    modes=json.loads((REPO/'datasets/practical_model_profile_v1/profile.json').read_text())['modes']
    for mode,spec in modes.items():
        spec['semantic']['allowed_unvalidated']=['entity_type'] if mode=='performance' else []
        spec['search'].update(max_depth=1,max_states=8,max_actions=2,max_outcomes=2,
            resources={'model_calls':0,'tokens':0,'remote_calls':16})
        spec['actions']={'type-clarification':{'search_priority':0,'estimated_ms':None,'token_budget':0}}
    doc={k:deepcopy(base[k]) for k in ('dataset','catalog','estimator','sources','backends')}
    for k in ('catalog','estimator'):doc[k]['path']=str((BASE.parent/doc[k]['path']).resolve())
    for source in doc['sources'].values():
        if 'equality_key_bounds' in source:
            source['equality_key_bounds']['path']=str((BASE.parent/source['equality_key_bounds']['path']).resolve())
    for spec in doc['backends'].values():spec['client']['url']='http://127.0.0.1:1'
    doc.update(schema_version='xgap-frozen-practical-profile-v1',profile_id='shared-class-tiny-v1',
        intake=pin(root/'intake.json'),operator_sources={'entities':'graph'},modes=modes,
        acquisitions={'type-clarification':{'kind':'clarification','slot':'entity_type',
            'candidate_ids':['type:account','type:person'],'source_id':'tiny-request-authority','version':'1','failed_outcomes':[]}},
        external_frontend={'policy':'fixed_action_order_v1','mapping':pin(BASE.parent/'mapping.json')},
        offline={'parent_profile':{'path':str(BASE),'sha256':BASE_SHA},'formal_campaign_ready':False,
            'catalog_builds':0,'fit_calls':0,'scope':'controlled authority boundary; not a paper preset or quality sample',
            'clarification_cost':'actual frozen-answer file access; no invented human waiting charge'})
    profile_pin=write_once(root/'profile.json',doc)
    profile,cfg=FrozenPracticalProfile.load_materialized(profile_pin['path'],expected_sha256=profile_pin['sha256'])
    raw={'schema_version':'xgap-practical-request-v1','question_id':'SHARED-CLASS-01',
        'question':'Return business IDs for the selected entity class.', 'population':'controlled-tiny',
        'exposure':'new shared binding/frontend/author boundary; intentionally conflicting prediction',
        'trusted_bindings':{},'predictions':{'entity_type':'type:person'},'clarifications':{}}
    q=profile.prepare(raw,request_sha256='0'*64,request_root=root,mode='exact',materialized=cfg)
    write_once(root/'clarification.json',{'schema_version':'xgap-clarification-bindings-v1',
        'program_sha256':program_identity(q.program),'source_id':'tiny-request-authority','version':'1',
        'bindings':{'entity_type':'type:account'}})
    raw['clarifications']={'type-clarification':pin(root/'clarification.json')}
    request=write_once(root/'request.json',raw)
    # Authored tiny fixture account IDs, independent of any method response.
    reference=write_once(root/'reference.json',{'schema_version':'xgap-normalized-row-reference-v1',
        'question_id':raw['question_id'],'dataset':base['dataset'],'ordered':False,
        'rows':[{'business_id':str(i)} for i in (1,2,3,4)],
        'normalization':{'schema_version':'xgap-row-normalization-v1','fields':{'business_id':'text'}}})
    study=write_once(root/'study-input.json',{'schema_version':SCHEMA_V2,'study_id':'shared-class-tiny-v1',
        'methods':list(PRACTICAL_METHODS),'groups':[{'request':request,'profile':profile_pin,'reference':reference}]})
    return freeze_study(input_path=study['path'],input_sha256=study['sha256'],output=root/'frozen')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--prepare-only',action='store_true')
    args=p.parse_args();root=args.output.resolve();root.mkdir(parents=True,exist_ok=False)
    if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True) and not args.prepare_only:
        raise ValueError('Commit before the new real boundary')
    r={'success':False,'paper_result':False,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        'model_calls':0,'automatic_retries':0,'maximum_final_method_queries':6,'runs':[],
        'expected_semantic_boundary':'EXACT reads authority; PERFORMANCE may retain the wrong type prediction',
        'scope':'one new shared partial-input group; not a baseline tuning or comparison campaign'}
    session=None
    try:
        schedule=publish_inputs(root/'inputs');r['schedule']=schedule
        if args.prepare_only:
            r.update(success=True,mode='prepare_only',source_calls=0)
        else:
            session=RdfTdbSession(root=root/'session',
                prepared_path='/Users/anthonyche/xgap-data/rdf-tdb-tiny-20260913-v1/receipt.json',
                prepared_sha256='cf4190cb71ec7ad635c34ab9a852b3f6bfe14d649b2048c9f897905564e2577d',
                prepared_input_sha256='5e8d77a2a70789e677258f31baddbda49a4ea67d972a8019c974df16bdef4c0c',
                budget=SourceObservationBudget(),discard_serving_copies=True)
            session.start()
            hosts=CampaignMethodHosts(session,
                summary_path='/Users/anthonyche/xgap-data/fedup-summary-tiny-20260913-v2/receipt.json',
                summary_sha256='d42a45b1a8436f80ee431f423bd383465bde4deb7f9a81b7e0ad4a1b118eb02c')
            for engine in ('fedup','fedx'):hosts.start(engine)
            def deploy(cell):
                doc=json.loads(read_pinned(cell['practical_profile']['path'],cell['practical_profile']['sha256']))
                for spec in doc['backends'].values():spec['client']['url']=session.observer.base_url
                return write_once(root/('deployment-'+cell['cell_id']+'.json'),doc)
            r['dispatch']=dispatch_practical_group(schedule_path=schedule['path'],schedule_sha256=schedule['sha256'],
                ledger=root/'ledger',observer=session.observer,owned_services=lambda c:hosts.owned_for(external_engine(c['method'])),
                deployment_for=deploy,endpoint_for=lambda c:hosts.endpoints[external_engine(c['method'])])
            for receipt in sorted((root/'ledger').rglob('receipt.json')):
                row=json.loads(receipt.read_text())
                if row.get('schema_version')!='xgap-common-method-trial-v1':continue
                timing=json.loads((receipt.parent/'timing.json').read_text())
                score_path=receipt.parent/'score.json';score=json.loads(score_path.read_text()) if score_path.exists() else {}
                r['runs'].append({'method':row['method'],'receipt':pin(receipt),'success':row['success'],
                    'status':row['status'],'answer_em':score.get('answer_em'),'actual_rows':score.get('actual_rows'),
                    'source_requests':row['source_observations']['requests'],'source_failed':row['source_observations']['failed_requests'],
                    'online_ms':timing['total_online_ms'],'model_calls':row['model_calls'],
                    'clarification_calls':row['clarification_calls'],'top_level_attempts':row['top_level_attempts'],
                    'unvalidated_bindings':row['unvalidated_bindings']})
            r['initializations']=hosts.initializations
            r['success']=len(r['runs'])==6 and all(q['success'] and q['source_failed']==0 for q in r['runs'])
            # Do not require a preferred method to win or rewrite native errors.
    except Exception as error:r.update(error_type=type(error).__name__,error=str(error))
    finally:
        if session:
            r['closure']=session.close()
            r['success'] &= r['closure']['owned_groups_drained'] and r['closure']['observer_stopped']
        result=write_once(root/'receipt.json',r)
    print(json.dumps({'receipt':result,**r}));return 0 if r['success'] else 1


if __name__=='__main__':raise SystemExit(main())
