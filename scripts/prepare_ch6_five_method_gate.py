#!/usr/bin/env python3
"""Freeze one exposed tiny NL case for five-method plumbing, not paper results."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from check_unified_readiness_native import MODEL_QUESTION
from xgap.agent.scope_authority import private_query_intent
from xgap.agent.unified_family import UnifiedSettings
from xgap.agent.unified_lookahead import Limits
from xgap.experiments.bounded_joint_toy import FIXTURE,toy_scope
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.ch6_formal_protocol import load_pin,pin_file
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.unified_contract import configuration


def prepare(prepared_path,external_runtime_path,output):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    prepared_pin=pin_file(prepared_path);prepared=load_pin(prepared_pin);profile=load_pin(prepared['profile'])
    fixture=json.loads((FIXTURE/'fixture.json').read_text());qid='CH6-FIVE-METHOD-PIPELINE-01'
    request=write_once(root/'request.json',dict(schema_version='xgap-one-shot-evaluation-request-v1',question_id=qid,
        question=MODEL_QUESTION,population='exposed eight-entity real-service development gate',exposure='development'))
    oracle=write_once(root/'private-user.json',private_query_intent(MODEL_QUESTION,fixture['query_template']))
    reference=write_once(root/'reference.json',dict(schema_version='xgap-normalized-row-reference-v1',
        dataset=profile['dataset'],question_id=qid,ordered=True,
        normalization=dict(schema_version='xgap-row-normalization-v1',fields=dict(account_distance='integer',
            medium_id='text',medium_type='text',other_id='text')),rows=fixture['expected']))
    scope=write_once(root/'scope.json',toy_scope().to_dict())
    config=write_once(root/'base-config.json',configuration(settings=UnifiedSettings(limits=Limits(depth=2,optional_ms=1000,horizon=12))))
    design=dict(total_wall_seconds=1800,package_max_bytes=1024**3,free_disk_reserve_bytes=6*1024**3,
        method_wall_seconds=300,method_rss_bytes=3*1024**3,source_rss_bytes=2*1024**3,startup_seconds=120,
        source_budget=asdict(SourceObservationBudget(max_calls=256,request_bytes=1024**2,phase_request_bytes=16*1024**2,
            response_bytes=8*1024**2,phase_response_bytes=64*1024**2,timeout_seconds=20,capture_compression='gzip')))
    spec=dict(schema_version='xgap-ch6-batch-input-v1',prepared=prepared_pin,external_runtime=pin_file(external_runtime_path),
        deployment='rdf',input_track='nl',exposure='development',order_seed=20260923,base_configuration=config,design=design,
        cases=[dict(case_id='pipe01',request=request,scope=scope,oracle=oracle,reference=reference)])
    pin=write_once(root/'input.json',spec)
    write_once(root/'budget.json',dict(maximum_requests=5,maximum_model_calls=68,maximum_final_submissions=5,
        automatic_retries=0,quality_not_admission_criterion=True,formal_result=False,
        purpose='same public question and shared sources; verify actual five-method dispatcher and evaluator boundary'))
    print(json.dumps(pin))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('prepared-path','external-runtime-path','output'):p.add_argument('--'+name,required=True)
    prepare(**vars(p.parse_args()))
