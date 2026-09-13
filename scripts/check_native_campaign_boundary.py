#!/usr/bin/env python3
"""One new native serving-copy/common-worker boundary, reusing frozen tiny data."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from native_store_session import NativeStoreSession
from prepare_rdf_tdb import REPO, stream_pin
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.common_method_trial import run_fixed_trial
from xgap.experiments.common_row_score import score_trial
from xgap.experiments.external_federation import deadline
from xgap.experiments.finbench_one_shot_population import normalization
from xgap.experiments.finbench_rdf import fixed_semantics_query, FAMILIES
from xgap.experiments.finbench_semantic import financial_program
from xgap.experiments.fixed_semantic_worker import REQUEST_SCHEMA
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once

sys.path.insert(0,str(REPO/'tests'))
from test_finbench_rdf import parameters, expected_rows

TINY=Path('/Users/anthonyche/xgap-data/native-store-freeze-tiny-20260913-v1/prepared/receipt.json')
TINY_SHA='a4cdd89da4dffa872128244977fa204dd0b6bce79604ab6a89c9b0f213017176'
PROFILE=Path('/Users/anthonyche/xgap-data/financial-nl-native-20260912-compact-v1/profile/profile.json')
PROFILE_SHA='1b9af9d4e60e3428e8f5ac235bb5aab8237da1b329e91510a5992171deb78bd8'


def main(output):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    receipt={'schema_version':'xgap-native-campaign-boundary-v1','success':False,'model_calls':0,
        'data_load_calls':0,'catalog_builds':0,'fit_calls':0,'maximum_final_executions':1,
        'automatic_retries':0,'paper_result':False}
    session=None
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):raise ValueError('Commit before native gate')
        receipt['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
        original=json.loads(read_pinned(TINY,TINY_SHA))
        build=json.loads(read_pinned(original['input_seal']['path'],original['input_seal']['sha256']))
        doc=json.loads(read_pinned(PROFILE,PROFILE_SHA))
        # Same source bytes, new association with the already accepted tiny
        # schema/catalog/model. The old minimal loader profile is left intact.
        loads={}
        for name,pin in build['sources'].items():
            p=stream_pin(PROFILE.parent/name)
            if (p['sha256'],p['bytes'])!=(pin['sha256'],pin['bytes']):raise ValueError('Tiny profile/load facts differ')
            loads[name]={'path':name,'sha256':p['sha256'],'size_bytes':p['bytes']}
        for key in ('catalog','estimator'):doc[key]['path']=str((PROFILE.parent/doc[key]['path']).resolve())
        doc['offline'].update(materialization_root=str(PROFILE.parent),load_files=loads,
            serving_profile_parent={'path':str(PROFILE),'sha256':PROFILE_SHA},no_data_reloaded=True)
        profile=write_once(root/'profile.json',doc)
        build={**build,'profile':profile,'parent_input_seal':original['input_seal']}
        bound_input=write_once(root/'input-seal.json',build)
        prepared=write_once(root/'prepared.json',{**original,'profile':profile,'dataset':doc['dataset'],
            'input_seal':bound_input,'parent_prepared':{'path':str(TINY),'sha256':TINY_SHA},
            'binding_only_no_load':True})
        program,_=financial_program('F3',parameters()[2])
        request=write_once(root/'request.json',{'schema_version':REQUEST_SCHEMA,'question_id':'NATIVE-COPY-F3',
            'dataset':doc['dataset'],'population':'development','exposure':'accepted tiny facts; new serving/worker boundary',
            'program':program.to_dict(),'sparql':fixed_semantics_query(FAMILIES[2],parameters()[2])})
        reference=write_once(root/'reference.json',{'schema_version':'xgap-normalized-row-reference-v1',
            'question_id':'NATIVE-COPY-F3','dataset':doc['dataset'],'ordered':True,
            'normalization':normalization(FAMILIES[2]),'rows':expected_rows()[2]})
        session=NativeStoreSession(root=root/'session',prepared_path=prepared['path'],prepared_sha256=prepared['sha256'],
            budget=SourceObservationBudget(),discard_serving_copies=True)
        with deadline(120):session.start()
        receipt['ready']=session.ready_pin
        run=run_fixed_trial(request_path=request['path'],request_sha256=request['sha256'],method='xgap-native',
            output=root/'execution',owned_services=session.owned,observer=session.observer,
            profile_path=session.profile['path'],profile_sha256=session.profile['sha256'])
        receipt['run']=run['receipt']
        receipt['score']=score_trial(run['receipt']['path'],receipt_sha256=run['receipt']['sha256'],
            reference_path=reference['path'],reference_sha256=reference['sha256'],output=root/'score.json')
        receipt['success']=run['success'] and receipt['score']['answer_em']==1
        receipt['online_ms']=run['timing']['total_online_ms']
        receipt['source_calls']=run['source_observations']['requests']
    except Exception as error:receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        if session:
            receipt['closure']=session.close()
            receipt['success'] &= receipt['closure']['owned_groups_drained'] and receipt['closure']['observer_stopped']
        original=json.loads(read_pinned(TINY,TINY_SHA))
        unchanged=True
        for store in original['stores'].values():
            seal=json.loads(read_pinned(store['seal']['path'],store['seal']['sha256']))
            unchanged &= all(stream_pin(pin['path'])==pin for pin in seal['files'])
        receipt['original_frozen_stores_unchanged']=unchanged;receipt['success'] &= unchanged
        pin=write_once(root/'receipt.json',receipt)
    print(json.dumps({'success':receipt['success'],'receipt':pin,'error':receipt.get('error'),
        'source_calls':receipt.get('source_calls'),'online_ms':receipt.get('online_ms')}))
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    raise SystemExit(main(**vars(parser.parse_args())))
