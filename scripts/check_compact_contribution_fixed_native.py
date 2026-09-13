#!/usr/bin/env python3
"""Independent gold-intent chain after one retained NL failure; zero model calls."""
import argparse
import json
from pathlib import Path
import subprocess

from check_compact_roles_native import PREPARED, PREPARED_SHA, reference_spec
from native_store_session import NativeStoreSession
from prepare_rdf_tdb import REPO, stream_pin
from xgap.compilers.global_semantic_sparql import compile_global_program
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.common_method_trial import run_fixed_trial
from xgap.experiments.common_row_score import score_trial
from xgap.experiments.compact_profile import derive_compact_contribution_profile
from xgap.experiments.external_federation import deadline
from xgap.experiments.fixed_semantic_worker import REQUEST_SCHEMA
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.row_normalization import normalize_rows
from xgap.semantic.compact_lowering import lower_compact_query


def main(output):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False);session=None
    r={'schema_version':'xgap-compact-contribution-fixed-native-v2','success':False,
        'model_calls':0,'maximum_final_executions':1,'automatic_retries':0,'data_loads':0,
        'catalog_builds':0,'fit_calls':0,'baseline_calls':0,'paper_result':False,
        'nl_failure_replaced':False,'track':'authored_tiny_deterministic_compilation_planning_execution'}
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):raise ValueError('Commit before live gate')
        r['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
        fixture_path=REPO/'tests/fixtures/compact_contribution_v2.json'
        fixture=json.loads(fixture_path.read_text());case=fixture['cases'][0]
        prepared=json.loads(read_pinned(PREPARED,PREPARED_SHA))
        doc=json.loads(read_pinned(prepared['profile']['path'],prepared['profile']['sha256']))
        program,sources=lower_compact_query(case['gold_compact'],doc['source_schema'],version='v2')
        mapping_path=Path('/Users/anthonyche/xgap-data/disjoint-rdf-trial-20260913-v2/rdf-profile-v2/mapping.json')
        mapping_pin=stream_pin(mapping_path)
        artifact=compile_global_program(program,json.loads(read_pinned(mapping_path,mapping_pin['sha256'])))
        r['input']=write_once(root/'input.json',{'fixture':stream_pin(fixture_path),
            'prepared':{'path':str(PREPARED),'sha256':PREPARED_SHA},'mapping':mapping_pin,
            'lowering':program.metadata['compact_lowering'],'derived_source_reads':sources,
            'model_answer_not_read_or_repaired':True})
        request=write_once(root/'request.json',{'schema_version':REQUEST_SCHEMA,
            'question_id':case['id']+'-GOLD','dataset':doc['dataset'],'population':fixture['population'],
            'exposure':fixture['exposure']+' Separate gold-intent module chain; not an NL answer.',
            'program':program.to_dict(),'sparql':artifact.text})
        spec=reference_spec(case)
        reference=write_once(root/'reference.json',{'schema_version':'xgap-normalized-row-reference-v1',
            'question_id':case['id']+'-GOLD','dataset':doc['dataset'],'ordered':True,'normalization':spec,
            'rows':normalize_rows(case['expected_rows'],spec),'derivation':fixture['derivation']})
        session=NativeStoreSession(root=root/'session',prepared_path=PREPARED,prepared_sha256=PREPARED_SHA,
            discard_serving_copies=True,budget=SourceObservationBudget(max_calls=64,request_bytes=1024**2,
                phase_request_bytes=4*1024**2,response_bytes=2*1024**2,phase_response_bytes=8*1024**2,timeout_seconds=20))
        with deadline(120):session.start()
        profile=derive_compact_contribution_profile(parent_path=session.profile['path'],parent_sha256=session.profile['sha256'],
            output=session.root/'contribution-v2')
        r['profile']=profile;r['ready']=session.ready_pin
        run=run_fixed_trial(request_path=request['path'],request_sha256=request['sha256'],method='xgap-native',
            output=root/'execution',owned_services=session.owned,observer=session.observer,
            profile_path=profile['path'],profile_sha256=profile['sha256'])
        score=score_trial(run['receipt']['path'],receipt_sha256=run['receipt']['sha256'],
            reference_path=reference['path'],reference_sha256=reference['sha256'],output=root/'score.json')
        worker=json.loads((root/'execution/worker/receipt.json').read_text())
        selection=json.loads((root/'execution/worker/selection.json').read_text())
        r.update(run=run['receipt'],score=stream_pin(root/'score.json'),answer_em=score['answer_em'],
            online_ms=run['timing']['total_online_ms'],source_calls=run['source_observations']['requests'],
            response_bytes=run['source_observations']['response_body_bytes'],selected_strategy=selection['selected_strategy'],
            candidates=selection['domain']['candidate_count'],construction_bound=selection['domain']['construction_bound'])
        r['success']=run['success'] and score['answer_em']==1 and worker['top_level_attempts']==1 and worker['alternative_executions']==0
    except Exception as e:r.update(error_type=type(e).__name__,error=str(e))
    finally:
        if session:
            r['closure']=session.close()
            r['success'] &= all(r['closure'][k] for k in ('owned_groups_drained','owned_processes_terminal','observer_stopped'))
        pin=write_once(root/'receipt.json',r)
    print(json.dumps({'success':r['success'],'receipt':pin,'error':r.get('error'),
        'answer_em':r.get('answer_em'),'source_calls':r.get('source_calls'),'online_ms':r.get('online_ms')}))
    return 0 if r['success'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    with deadline(600):raise SystemExit(main(**vars(parser.parse_args())))
