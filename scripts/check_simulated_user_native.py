#!/usr/bin/env python3
"""One real model call, scoped user interaction and one tiny Neo4j+Fuseki plan."""
import argparse
import getpass
import json
import os
from pathlib import Path

from native_store_session import NativeStoreSession
from check_compact_roles_native import PREPARED, PREPARED_SHA
from xgap.agent.simulated_user import PROFILE, intent_state
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.common_method_trial import run_nl_trial
from xgap.experiments.common_row_score import score_trial
from xgap.experiments.compact_profile import derive_compact_prompt_profile
from xgap.experiments.external_federation import deadline
from xgap.experiments.nl_strong_release import freeze_common_profile
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.row_normalization import normalize_rows


def main(output, read_key=False):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    case=json.loads((Path(__file__).resolve().parents[1]/'tests/fixtures/simulated_user_tiny_v1.json').read_text())
    previous=os.environ.get('XGAP_EXTERNAL_LLM_API_KEY')
    if read_key:os.environ['XGAP_EXTERNAL_LLM_API_KEY']=getpass.getpass('Model API key: ')
    receipt={'schema_version':'xgap-simulated-user-native-gate-v1','success':False,
        'maximum_model_calls':1,'maximum_final_executions':1,'maximum_user_calls':2,
        'scope':'tiny integration, not paper evaluation','closures':[]}
    session=None
    try:
        if not os.environ.get('XGAP_EXTERNAL_LLM_API_KEY'):
            raise ValueError('Model credential is unavailable')
        request=write_once(root/'request.json',{k:case[k] for k in ('question_id','question','population','exposure')}|
            {'schema_version':'xgap-one-shot-evaluation-request-v1'})
        private=write_once(root/'private-intent.json',intent_state(case['question'],case['gold_compact'],
            case['private_entity_bindings'],source_id='authoritative-tiny-user',version='v1'))
        write_once(root/'intent.json',receipt)
        session=NativeStoreSession(root=root/'session',prepared_path=PREPARED,prepared_sha256=PREPARED_SHA,
            discard_serving_copies=True,budget=SourceObservationBudget(max_calls=32,request_bytes=1024**2,
                phase_request_bytes=4*1024**2,response_bytes=2*1024**2,phase_response_bytes=8*1024**2,timeout_seconds=20))
        with deadline(120):session.start()
        profile=derive_compact_prompt_profile(parent_path=session.profile['path'],parent_sha256=session.profile['sha256'],
            output=root/'roles-profile')
        profile=freeze_common_profile(profile,root/'nl-profile.json')
        doc=json.loads(read_pinned(profile['path'],profile['sha256']))
        doc['profile_id'] += ':'+PROFILE
        doc['offline']['simulated_user']={'profile_id':PROFILE,'max_calls':2,
            'private_artifact_supplied_separately':True,'declared_user_wait_ms_per_call':0,
            'execution_rewrite':'early-path-constraints-v1','joint_information_policy_search':False}
        profile=write_once(root/'interaction-profile.json',doc)
        dataset=doc['dataset']
        norm={'schema_version':'xgap-row-normalization-v1','fields':{'other_id':'text','account_distance':'integer',
            'medium_id':'text','medium_type':'text'}}
        reference=write_once(root/'reference.json',{'schema_version':'xgap-normalized-row-reference-v1',
            'question_id':case['question_id'],'dataset':dataset,'ordered':True,'normalization':norm,
            'rows':normalize_rows(case['expected_rows'],norm),'derivation':case['derivation']})
        outcome=run_nl_trial(request_path=request['path'],request_sha256=request['sha256'],
            method='xgap-nl-user-exact',output=root/'execution',owned_services=session.owned,observer=session.observer,
            profile_path=profile['path'],profile_sha256=profile['sha256'],oracle_path=private['path'],
            oracle_sha256=private['sha256'],user_max_calls=2)
        score=score_trial(outcome['receipt']['path'],receipt_sha256=outcome['receipt']['sha256'],
            reference_path=reference['path'],reference_sha256=reference['sha256'],output=root/'score.json')
        receipt.update(outcome=outcome['receipt'],score=score,
            success=bool(outcome['success'] and score['answer_em']==1 and outcome['model_calls']==1
                and outcome['clarification_calls']==2 and outcome['user_intent_verified']),
            measurements={k:outcome.get(k) for k in ('status','model_calls','input_tokens','output_tokens',
                'clarification_calls','oracle_processing_ms','planning_ms','execution_ms','source_observations','timing')})
    except Exception as error:
        receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        if session:
            closure=session.close();receipt['closures'].append(closure)
            receipt['success'] &= bool(closure['owned_groups_drained'] and closure['owned_processes_terminal'] and closure['observer_stopped'])
        if previous is None:os.environ.pop('XGAP_EXTERNAL_LLM_API_KEY',None)
        else:os.environ['XGAP_EXTERNAL_LLM_API_KEY']=previous
        pin=write_once(root/'receipt.json',receipt)
    print(json.dumps({'success':receipt['success'],'receipt':pin,'error':receipt.get('error')}))
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True);parser.add_argument('--read-key',action='store_true')
    with deadline(600):raise SystemExit(main(**vars(parser.parse_args())))
