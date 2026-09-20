#!/usr/bin/env python3
"""Bounded native batch-interface acceptance, not a paper/model-quality run."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from run_bounded_joint_batch import run, source_commit, SCHEMA
from xgap.agent.intent_strong import FamilyInformationPolicy
from xgap.agent.scope_authority import private_query_intent
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.experiments.bounded_joint_contract import METHODS, configuration
from xgap.experiments.bounded_joint_toy import QUESTION, FIXTURE, toy_scope
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once


def main(output,prepared_path,prepared_sha256):
    commit=source_commit();root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    result=dict(schema_version='xgap-bounded-joint-batch-native-gate-v1',success=False,source_commit=commit,
        maximum_model_calls=0,maximum_final_plans=2,cases=[],invocations=[],
        scope='authored tiny native graph; public deterministic NL grammar; batch plumbing only; no model-quality or speedup claim')
    try:
        data=json.loads((FIXTURE/'fixture.json').read_text())
        prepared=json.loads(read_pinned(prepared_path,prepared_sha256))
        profile=json.loads(read_pinned(prepared['profile']['path'],prepared['profile']['sha256']))
        request=write_once(root/'request.json',dict(schema_version='xgap-one-shot-evaluation-request-v1',
            question_id='BOUNDED-JOINT-BATCH-TINY',question=QUESTION,population='authored tiny graph',exposure='development'))
        scope=write_once(root/'scope.json',toy_scope().to_dict())
        oracle=write_once(root/'private-user.json',private_query_intent(QUESTION,data['query_template']))
        reference=write_once(root/'reference.json',dict(schema_version='xgap-normalized-row-reference-v1',
            dataset=profile['dataset'],question_id='BOUNDED-JOINT-BATCH-TINY',ordered=True,
            normalization=dict(schema_version='xgap-row-normalization-v1',fields=dict(
                account_distance='integer',medium_id='text',medium_type='text',other_id='text')),rows=data['expected']))
        config=write_once(root/'config.json',configuration(epsilon='1/2',provider='development_toy_template',
            limits=StrongSearchLimits(planning_ms=10000,improvement_actions=16)))
        exhausted=write_once(root/'no-information-budget.json',configuration(epsilon='1/2',
            provider='development_toy_template',information=FamilyInformationPolicy(max_calls=0)))
        cells=[dict(cell_id=name,method=method,request=request,scope=scope,oracle=oracle,config=policy,reference=reference)
            for name,method,policy in (('exact',METHODS[0],config),('performance',METHODS[1],config),
                                       ('budget-nonanswer',METHODS[0],exhausted))]
        design=dict(total_wall_seconds=900,package_max_bytes=1024**3,free_disk_reserve_bytes=6*1024**3,
            method_wall_seconds=90,method_rss_bytes=1024**3,source_rss_bytes=2*1024**3,startup_seconds=120,
            source_budget=asdict(SourceObservationBudget(capture_compression='gzip',max_calls=64,
                request_bytes=1024**2,phase_request_bytes=4*1024**2,response_bytes=2*1024**2,
                phase_response_bytes=8*1024**2,timeout_seconds=20)))
        pin=write_once(root/'manifest.json',dict(schema_version=SCHEMA,deployment='native',
            prepared=dict(path=str(Path(prepared_path).resolve()),sha256=prepared_sha256),design=design,cells=cells))
        result['manifest']=pin
        kwargs=dict(manifest_path=pin['path'],manifest_sha256=pin['sha256'],output=root/'batch')
        for bound in (1,2,3):
            invocation=run(**kwargs,max_new_cells=bound);result['invocations'].append(invocation)
            if invocation['status']=='failed':raise ValueError('Batch invocation failed: '+str(invocation.get('error')))
        for cell in cells:
            path=root/'batch/cells'/cell['cell_id'];outcome=json.loads((path/'execution/receipt.json').read_text())
            score=json.loads((path/'score.json').read_text());observation=outcome['source_observations'] or {}
            result['cases'].append(dict(cell_id=cell['cell_id'],status=outcome['status'],
                success=outcome['success'],model_calls=outcome['model_calls'],final_plan_executions=outcome['final_plan_executions'],
                answer_em=score['answer_em'],answer_row_multiset_f1=score['answer_row_multiset_f1'],
                certificate=outcome['terminal_certificate'],disclosed_coordinates=outcome['disclosed_coordinates'],
                total_user_calls=outcome['total_user_calls'],backend_calls=observation.get('requests'),
                response_body_bytes=observation.get('response_body_bytes'),capture_storage_bytes=observation.get('capture_storage_bytes')))
        a,b,c=result['cases']
        result['success']=(a['success'] and b['success'] and a['answer_em']==1 and
            a['final_plan_executions']==b['final_plan_executions']==1 and
            c['status']=='scope_confirmation_budget_exhausted' and c['final_plan_executions']==0 and not c['success'] and
            all(x['model_calls']==0 for x in result['cases']) and
            all(x.get('all_owned_closed') for x in result['invocations'][:2]) and
            result['invocations'][2]['status']=='no_unattempted_cells' and
            result['invocations'][2]['counts']==dict(sealed=3,execution_success=2,execution_failed=1,incomplete=0,unattempted=0))
    except Exception as error:result.update(error_type=type(error).__name__,error=str(error))
    pin=write_once(root/'receipt.json',result)
    print(json.dumps(dict(success=result['success'],receipt=pin,cases=result['cases'],error=result.get('error'))))
    return 0 if result['success'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('output','prepared-path','prepared-sha256'):p.add_argument('--'+name,required=True)
    raise SystemExit(main(**vars(p.parse_args())))
