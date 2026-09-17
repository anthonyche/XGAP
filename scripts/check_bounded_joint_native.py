#!/usr/bin/env python3
"""Two current-entry development calls on a caller-pinned eight-node native store."""
import argparse
import json
from pathlib import Path
import subprocess

from native_store_session import NativeStoreSession
from prepare_rdf_tdb import REPO
from xgap.agent.scope_authority import private_query_intent
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.experiments.bounded_joint_toy import QUESTION, TemplateProposalProvider, load_inputs, toy_scope
from xgap.experiments.bounded_joint_worker import run
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.compact_profile import derive_compact_prompt_profile
from xgap.experiments.evidence_store import read_json_evidence
from xgap.experiments.external_federation import deadline
from xgap.experiments.nl_strong_release import freeze_common_profile
from xgap.experiments.one_shot_records import write_once


def main(output,prepared_path,prepared_sha256):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False);session=None
    result=dict(schema_version='xgap-bounded-joint-native-gate-v1',success=False,cases=[],closures=[],
        scope='authored eight-node system correctness; deterministic NL grammar; no model-quality/performance claim',
        maximum_model_calls=0,maximum_final_plans=2,catalog_builds=0,baseline_runs=0)
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):
            raise ValueError('Commit before external boundary gate')
        result['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
        data,_=load_inputs()
        request=write_once(root/'request.json',dict(schema_version='xgap-one-shot-evaluation-request-v1',
            question_id='BOUNDED-JOINT-TINY',question=QUESTION,population='authored synthetic tiny graph',exposure='development'))
        scope=write_once(root/'scope.json',toy_scope().to_dict())
        oracle=write_once(root/'private-user.json',private_query_intent(QUESTION,data['query_template']))
        session=NativeStoreSession(root=root/'session',prepared_path=prepared_path,prepared_sha256=prepared_sha256,
            discard_serving_copies=True,budget=SourceObservationBudget(capture_compression='gzip',
                max_calls=64,request_bytes=1024**2,phase_request_bytes=4*1024**2,
                response_bytes=2*1024**2,phase_response_bytes=8*1024**2,timeout_seconds=20))
        with deadline(120):session.start()
        pin=derive_compact_prompt_profile(parent_path=session.profile['path'],parent_sha256=session.profile['sha256'],
            output=session.root/'compact')
        pin=freeze_common_profile(pin,session.root/'common-profile.json')
        result['inputs']=dict(request=request,scope=scope,private_user=oracle,profile=pin,
            prepared=dict(path=str(prepared_path),sha256=prepared_sha256))
        for mode,epsilon in (('exact','0'),('performance','1/2')):
            session.observer.set_phase(mode)
            with deadline(120):
                receipt=run(profile_path=pin['path'],profile_sha256=pin['sha256'],
                    request_path=request['path'],request_sha256=request['sha256'],
                    scope_path=scope['path'],scope_sha256=scope['sha256'],
                    oracle_path=oracle['path'],oracle_sha256=oracle['sha256'],mode=mode,epsilon=epsilon,
                    output=root/mode,provider_override=TemplateProposalProvider(data['query_template']),
                    limits=StrongSearchLimits(planning_ms=10000,improvement_actions=16))
            observation=session.observer.seal_phase(mode)
            outcome=write_once(root/(mode+'-outcome.json'),dict(worker=receipt,source_observations=observation))
            session.observer.release_phase(mode,outcome)
            answer=read_json_evidence(receipt['result']) if receipt.get('result') else {}
            case={k:receipt.get(k) for k in ('success','status','scope_confirmed','candidate_count','model_calls',
                'final_plan_executions','total_user_calls','clarification_calls','strong_plan','backend_calls','terminal_certificate')}
            case.update(mode=mode,epsilon=epsilon,outcome=outcome,answer_rows=answer.get('answer'),
                exact_answer_match=answer.get('answer')==data['expected'],source_observations=observation)
            result['cases'].append(case)
            if not receipt['success']:raise ValueError('Tiny current worker failed: '+str(receipt.get('error',receipt['status'])))
        result['success']=(all(c['success'] and c['strong_plan'] and c['scope_confirmed'] and c['model_calls']==0
            and c['final_plan_executions']==1 and c['source_observations']['failed_requests']==0 for c in result['cases'])
            and result['cases'][0]['exact_answer_match'])
    except Exception as error:result.update(error_type=type(error).__name__,error=str(error))
    finally:
        if session:result['closures'].append(session.close())
        result['success'] &= bool(result['closures']) and all(c['owned_groups_drained'] and c['owned_processes_terminal']
            and c['observer_stopped'] for c in result['closures'])
        pin=write_once(root/'receipt.json',result)
    print(json.dumps(dict(success=result['success'],receipt=pin,error=result.get('error'),cases=result['cases'])))
    return 0 if result['success'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('output','prepared-path','prepared-sha256'):p.add_argument('--'+name,required=True)
    with deadline(360):raise SystemExit(main(**vars(p.parse_args())))
