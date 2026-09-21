#!/usr/bin/env python3
"""Bounded prerelease admission, never a formal dataset campaign."""
import argparse
from dataclasses import asdict
import getpass
import json
import os
from pathlib import Path

from run_bounded_joint_batch import run,source_commit,UNIFIED_SCHEMA
from xgap.agent.intent_certificate import canonical
from xgap.agent.intent_strong import FamilyInformationPolicy
from xgap.agent.scope_authority import private_query_intent
from xgap.agent.unified_family import UnifiedSettings
from xgap.agent.unified_information import InformationTarget
from xgap.agent.unified_lookahead import Limits,Resources
from xgap.experiments.unified_contract import METHODS,configuration
from xgap.experiments.bounded_joint_toy import QUESTION,FIXTURE,toy_scope
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.compact_profile import derive_compact_prompt_profile
from xgap.experiments.nl_strong_release import freeze_common_profile
from xgap.experiments.evidence_store import read_json_evidence
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.infrastructure.runtime import QueryArtifact


def main(output,prepared_path,prepared_sha256,with_model=False,read_key=False):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    result=dict(schema_version='xgap-unified-readiness-gate-v1',source_commit=source_commit(),success=False,
        maximum_model_calls=int(with_model),maximum_final_plans=3+int(with_model),automatic_retries=0,
        scope='frozen eight-node development inputs; interface/correctness admission, not evaluation or speed evidence',cases=[])
    prior=os.environ.get('XGAP_EXTERNAL_LLM_API_KEY')
    try:
        if read_key:os.environ['XGAP_EXTERNAL_LLM_API_KEY']=getpass.getpass('Model credential (not recorded): ')
        if with_model and not os.environ.get('XGAP_EXTERNAL_LLM_API_KEY'):raise ValueError('Configured model credential missing')
        prepared=json.loads(read_pinned(prepared_path,prepared_sha256));old=prepared['profile']
        revised=derive_compact_prompt_profile(parent_path=old['path'],parent_sha256=old['sha256'],output=root/'compact')
        profile_pin=freeze_common_profile(revised,root/'common-profile.json')
        profile=json.loads(read_pinned(profile_pin['path'],profile_pin['sha256']))
        build=json.loads(read_pinned(prepared['input_seal']['path'],prepared['input_seal']['sha256']))
        build['profile']=dict(path=profile_pin['path'],sha256=profile_pin['sha256'])
        prepared['profile']=build['profile'];prepared['input_seal']=write_once(root/'input-seal.json',build)
        prepared['unified_association']=dict(parent=dict(path=prepared_path,sha256=prepared_sha256),stores_changed=False)
        prepared_pin=write_once(root/'prepared.json',prepared)
        data=json.loads((FIXTURE/'fixture.json').read_text())
        request=write_once(root/'request.json',dict(schema_version='xgap-one-shot-evaluation-request-v1',question_id='UNIFIED-ADMISSION',
            question=QUESTION,population='authored eight-node graph',exposure='development'))
        scope=write_once(root/'scope.json',toy_scope().to_dict())
        oracle=write_once(root/'private-user.json',private_query_intent(QUESTION,data['query_template']))
        reference=write_once(root/'reference.json',dict(schema_version='xgap-normalized-row-reference-v1',
            dataset=profile['dataset'],question_id='UNIFIED-ADMISSION',ordered=True,
            normalization=dict(schema_version='xgap-row-normalization-v1',fields=dict(
                account_distance='integer',medium_id='text',medium_type='text',other_id='text')),rows=data['expected']))
        targets=(InformationTarget(name='graph-count',backend='neo4j',source_id='graph',version='financial-tiny-v1',kind='probe',
            artifact_json=canonical(QueryArtifact('graph-count','cypher','MATCH (n) RETURN count(n) AS value').to_dict()),
            probabilities=(.6,.3,.1)),)
        definitions=[('strict',METHODS[0],UnifiedSettings(limits=Limits(optional_ms=3000)),'development_toy_template'),
            ('information',METHODS[0],UnifiedSettings(limits=Limits(depth=1,optional_ms=3000,aggregation='expectation'),
                candidate_weights=(1,)*8,information_targets=targets),'development_toy_template'),
            ('sequential',METHODS[1],UnifiedSettings(decision_order='semantic_then_physical',limits=Limits(optional_ms=3000)),
             'development_toy_template')]
        if with_model:definitions.append(('model',METHODS[0],UnifiedSettings(limits=Limits(optional_ms=3000)),'frozen_compact_model'))
        definitions.append(('reserve-refusal',METHODS[0],UnifiedSettings(limits=Limits(resources=Resources(
            user_calls=0,remote_calls=32,bytes=None,peak_bytes=None))),'development_toy_template'))
        cells=[]
        for name,method,settings,provider in definitions:
            config=write_once(root/(name+'-config.json'),configuration(settings=settings,provider=provider))
            cells.append(dict(cell_id=name,method=method,request=request,scope=scope,oracle=oracle,config=config,reference=reference))
        design=dict(total_wall_seconds=900,package_max_bytes=1024**3,free_disk_reserve_bytes=6*1024**3,
            method_wall_seconds=120,method_rss_bytes=1024**3,source_rss_bytes=2*1024**3,startup_seconds=120,
            source_budget=asdict(SourceObservationBudget(capture_compression='gzip',max_calls=64,
                request_bytes=1024**2,phase_request_bytes=4*1024**2,response_bytes=2*1024**2,phase_response_bytes=8*1024**2,timeout_seconds=20)))
        manifest=write_once(root/'manifest.json',dict(schema_version=UNIFIED_SCHEMA,deployment='native',prepared=prepared_pin,design=design,cells=cells))
        result['manifest']=manifest
        args=dict(manifest_path=manifest['path'],manifest_sha256=manifest['sha256'],output=root/'batch')
        executed=run(**args,max_new_cells=len(cells));resumed=run(**args,max_new_cells=len(cells))
        result.update(invocation=executed,resume=resumed)
        for cell in cells:
            directory=root/'batch/cells'/cell['cell_id']
            outcome=json.loads((directory/'execution/receipt.json').read_text())
            score=json.loads((directory/'score.json').read_text())
            loss=json.loads((directory/'query-loss.json').read_text())
            core=read_json_evidence(outcome['core']);online=core.get('joint_policy') or core
            result['cases'].append(dict(cell_id=cell['cell_id'],success=outcome['success'],status=outcome['status'],
                answer_em=score['answer_em'],loss_status=loss['status'],certificate_violation=loss['certificate_violation'],
                model_calls=outcome['model_calls'],input_tokens=outcome['input_tokens'],output_tokens=outcome['output_tokens'],
                final_plan_executions=outcome['final_plan_executions'],probe_calls=outcome['probe_calls'],
                physical_actions=outcome['physical_actions'],source_requests=outcome['source_observations']['requests'],
                selected_facts=online.get('selected_facts'),external_calls_during_search=online.get('external_calls_during_search')))
        positives=result['cases'][:-1];negative=result['cases'][-1]
        result['success']=(all(c['success'] and c['answer_em']==1 and c['loss_status']=='measured'
            and c['certificate_violation'] is False and c['final_plan_executions']==1 for c in positives)
            and negative['status']=='completion_witness_unavailable' and negative['source_requests']==0
            and result['cases'][1]['probe_calls']==1
            and all(c['external_calls_during_search']==0 for c in result['cases'])
            and sum(c['model_calls'] or 0 for c in result['cases'])==int(with_model)
            and executed['all_owned_closed'] and resumed['status']=='no_unattempted_cells' and resumed['new_cells']==0)
    except Exception as error:result.update(error_type=type(error).__name__,error=str(error))
    finally:
        if prior is None:os.environ.pop('XGAP_EXTERNAL_LLM_API_KEY',None)
        else:os.environ['XGAP_EXTERNAL_LLM_API_KEY']=prior
        pin=write_once(root/'receipt.json',result)
    print(json.dumps(dict(success=result['success'],receipt=pin,error=result.get('error'),cases=result['cases'])))
    return 0 if result['success'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('output','prepared-path','prepared-sha256'):p.add_argument('--'+name,required=True)
    p.add_argument('--with-model',action='store_true');p.add_argument('--read-key',action='store_true')
    raise SystemExit(main(**vars(p.parse_args())))
