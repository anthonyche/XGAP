#!/usr/bin/env python3
"""Bounded Chapter 7 logging gate: controlled cells OR two live NL generations."""
import argparse
from dataclasses import asdict
import getpass
import json
import os
from pathlib import Path

from native_store_session import NativeStoreSession
from run_bounded_joint_batch import source_commit, BatchBudget, closed
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.scope_authority import private_query_intent
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.experiments.bounded_joint_toy import FIXTURE,toy_scope
from xgap.experiments.bounded_joint_contract import METHODS,configuration
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.common_method_trial import run_nl_trial
from xgap.experiments.common_row_score import score_trial
from xgap.experiments.compact_profile import derive_compact_prompt_profile
from xgap.experiments.controlled_state import publish_state
from xgap.experiments.evidence_store import file_pin,read_json_evidence
from xgap.experiments.external_federation import deadline
from xgap.experiments.one_shot_profile import FrozenOneShotProfile,read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.process_guard import ProcessBudget
from xgap.experiments.query_loss_score import score_query_loss
from xgap.semantic.intent_scope import construct_scope

QUESTION=('For account with business ID 1, list reachable accounts and their blocked sign-in media. '
    'Follow outgoing money transfers along acyclic paths, with strictly increasing transfer createTime '
    'between 2020-01-01 00:00:00.000 and 2020-01-04 00:00:00.000. Paths start at one hop; '
    'the maximum depth (one or three) and whether each time boundary is inclusive are unspecified conventions '
    'to clarify with the user if needed. Include every reachable account and path length with each medium '
    'that signed in to that account and has isBlocked=true. Return other_id, account_distance, medium_id, '
    'medium_type, ordered by account_distance, other_id, medium_id ascending, without a result limit.')


def main(*,track,output,prepared_path,prepared_sha256,read_key=False):
    commit=source_commit();root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    prior=os.environ.get('XGAP_EXTERNAL_LLM_API_KEY');session=None
    result=dict(schema_version='xgap-chapter7-native-readiness-v1',track=track,source_commit=commit,
        gate_complete=False,answers_pass=False,cases=[],closures=[],maximum_model_calls=2 if track=='nl' else 0,
        maximum_final_plans=2 if track=='nl' else 4,paper_result=False,automatic_retries=0)
    source_budget=SourceObservationBudget(capture_compression='gzip',max_calls=64,request_bytes=1024**2,
        phase_request_bytes=4*1024**2,response_bytes=2*1024**2,phase_response_bytes=8*1024**2,timeout_seconds=20)
    design=dict(total_wall_seconds=900,package_max_bytes=1024**3,free_disk_reserve_bytes=6*1024**3)
    import time
    budget=BatchBudget(root,design,time.time())
    try:
        if track=='nl':
            key=getpass.getpass('Qwen credential (not recorded): ') if read_key else prior
            if not key:raise ValueError('Configured model credential unavailable')
            os.environ['XGAP_EXTERNAL_LLM_API_KEY']=key;key=None
        data=json.loads((FIXTURE/'fixture.json').read_text())
        request=write_once(root/'request.json',dict(schema_version='xgap-one-shot-evaluation-request-v1',
            question_id='CH7-'+track.upper()+'-TINY',question=QUESTION,population='authored tiny readiness graph',exposure='development'))
        scope=write_once(root/'scope.json',toy_scope().to_dict())
        oracle=write_once(root/'private-user.json',private_query_intent(QUESTION,data['query_template']))
        prepared=json.loads(read_pinned(prepared_path,prepared_sha256))
        original=json.loads(read_pinned(prepared['profile']['path'],prepared['profile']['sha256']))
        reference=write_once(root/'reference.json',dict(schema_version='xgap-normalized-row-reference-v1',
            dataset=original['dataset'],question_id='CH7-'+track.upper()+'-TINY',ordered=True,rows=data['expected'],
            normalization=dict(schema_version='xgap-row-normalization-v1',fields=dict(
                account_distance='integer',medium_id='text',medium_type='text',other_id='text'))))
        configs={on:write_once(root/('feedback-'+str(on)+'.json'),configuration(epsilon='1/2',
            execution_cost_feedback=on,limits=StrongSearchLimits(planning_ms=10000,improvement_actions=16)))
            for on in ([True] if track=='nl' else [True,False])}
        cells=[dict(id=mode+'-'+str(on),method=method,mode=mode,feedback=on) for on in configs
            for mode,method in zip(('exact','performance'),METHODS)]
        result['inputs']=write_once(root/'input-manifest.json',dict(prepared=dict(path=prepared_path,sha256=prepared_sha256),
            request=request,scope=scope,oracle=oracle,reference=reference,configurations={str(k):v for k,v in configs.items()},
            source_budget=asdict(source_budget),study_budget=design,cells=cells,
            initial_clues=['hops'] if track=='controlled' else None))
        for cell in cells:
            if budget.sample([]):raise ValueError(budget.status)
            if session is None:
                session=NativeStoreSession(root=root/('session-'+cell['id']),prepared_path=prepared_path,
                    prepared_sha256=prepared_sha256,discard_serving_copies=True,budget=source_budget)
                with deadline(120):session.start()
                profile=derive_compact_prompt_profile(parent_path=session.profile['path'],parent_sha256=session.profile['sha256'],
                    output=session.root/'prompt-v2')
            kwargs={}
            if track=='controlled':
                frozen=FrozenOneShotProfile.load(profile['path'],expected_sha256=profile['sha256'])
                doc,_,_,sources,backends,_,_=frozen.materialize()
                family=construct_scope([data['query_template']],toy_scope(),snapshot_identity(sources,backends,doc['source_schema']))
                choices=[dict(name=s.name,type='path_depth' if s.name=='hops' else 'time_boundary',slots=[s.name]) for s in family.slots]
                state=write_once(root/(cell['id']+'-state.json'),publish_state(QUESTION,family,data['query_template'],
                    clue_names=('hops',),semantic_choices=choices))
                kwargs.update(controlled_state_path=state['path'],controlled_state_sha256=state['sha256'])
            config=configs[cell['feedback']];path=root/cell['id'];path.mkdir()
            outcome=run_nl_trial(**kwargs,request_path=request['path'],request_sha256=request['sha256'],
                scope_path=scope['path'],scope_sha256=scope['sha256'],oracle_path=oracle['path'],oracle_sha256=oracle['sha256'],
                joint_config_path=config['path'],joint_config_sha256=config['sha256'],method=cell['method'],output=path/'execution',
                profile_path=profile['path'],profile_sha256=profile['sha256'],owned_services=session.owned,observer=session.observer,
                budget=ProcessBudget(wall_seconds=90,max_group_rss_bytes=1024**3),source_rss_bytes=2*1024**3,package_monitor=budget)
            score=score_trial(outcome['receipt']['path'],receipt_sha256=outcome['receipt']['sha256'],
                reference_path=reference['path'],reference_sha256=reference['sha256'],output=path/'answer-score.json')
            loss=score_query_loss(receipt=outcome['receipt'],request=request,oracle=oracle,output=path/'query-loss.json')
            core=read_json_evidence(outcome['core']) if outcome.get('core') else {}
            policy=core.get('joint_policy') or core
            case={**cell,'outcome':outcome['receipt'],'answer_em':score['answer_em'],'answer_f1':score['answer_row_multiset_f1'],
                'loss':loss,'model_calls':outcome['model_calls'],'status':outcome['status'],'success':outcome['success'],
                'final_plan_executions':outcome.get('final_plan_executions'),'clarification_calls':outcome.get('clarification_calls'),
                'policy_nodes':len((policy.get('policy_evidence') or {}).get('nodes',[])),
                'observed_states':policy.get('observed_policy_state_ids'),'initial_state':outcome.get('initial_state'),
                'controlled_processing_ms':outcome.get('controlled_processing_ms'),'online_ms':outcome['timing']['total_online_ms']}
            write_once(path/'terminal.json',case);result['cases'].append(case)
            print(json.dumps({k:case[k] for k in ('id','status','answer_em','model_calls','clarification_calls','policy_nodes')}),flush=True)
            if not outcome['can_continue_session']:
                closure=session.close();result['closures'].append(closure);session=None
                if not closed(closure):raise ValueError('Unverified source closure')
        result['gate_complete']=True
        result['answers_pass']=all(c['success'] and (c['mode']!='exact' or c['answer_em']==1)
            and c['loss']['status']=='measured' and c['loss']['certificate_violation'] is False for c in result['cases'])
    except Exception as error:result.update(error_type=type(error).__name__,error=str(error))
    finally:
        if session:result['closures'].append(session.close())
        result['all_owned_closed']=all(closed(c) for c in result['closures'])
        if prior is None:os.environ.pop('XGAP_EXTERNAL_LLM_API_KEY',None)
        else:os.environ['XGAP_EXTERNAL_LLM_API_KEY']=prior
        pin=write_once(root/'receipt.json',result)
    print(json.dumps(dict(receipt=pin,gate_complete=result['gate_complete'],answers_pass=result['answers_pass'],
        all_owned_closed=result['all_owned_closed'],error=result.get('error'))))
    return 0 if result['gate_complete'] and result['answers_pass'] and result['all_owned_closed'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--track',choices=('nl','controlled'),required=True)
    p.add_argument('--read-key',action='store_true')
    for name in ('output','prepared-path','prepared-sha256'):p.add_argument('--'+name,required=True)
    raise SystemExit(main(**vars(p.parse_args())))
