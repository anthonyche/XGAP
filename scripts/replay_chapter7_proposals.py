#!/usr/bin/env python3
"""Replay pinned failed Qwen proposals on toy RDF without new model calls.

This is deterministic failure diagnosis, not a fresh end-to-end/model-quality
measurement. The original failed receipts stay immutable and remain failures.
"""
import argparse
from fractions import Fraction
import json
from pathlib import Path

from run_bounded_joint_batch import source_commit
from xgap.api import answer
from xgap.agent.scope_authority import QueryIntentAuthority
from xgap.experiments.bounded_joint_contract import load_configuration
from xgap.experiments.bounded_joint_toy import local_runtime
from xgap.experiments.evidence_store import read_json_evidence,write_json_evidence
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.query_loss_score import aligned_query_loss
from xgap.semantic.compact_identity import IDENTITY_VERSION
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.compact_query import SCHEMA as COMPACT_SCHEMA
from xgap.semantic.intent_scope import ScopePolicy
from xgap.semantic.interpretation import InterpretationRequest,InterpretationResponse
from xgap.semantic.interpretation_candidates import SCHEMA


class RecordedProposal:
    provider_id='sealed-compact-proposal-failure-replay-v1'

    def __init__(self,payload,source):
        if payload['schema_version']!=COMPACT_SCHEMA:raise ValueError('Replay gate requires compact v1')
        self.payload=payload;self.source=source

    def interpret(self,request):
        candidates=[]
        for index,item in enumerate(self.payload['candidates']):
            program,sources=lower_compact_query(item['query'],request.context['source_schema'],program_id='compact-'+str(index))
            candidates.append(dict(candidate_id=item['candidate_id'],quality_proxy=item['quality_proxy'],
                program=program.to_dict(),operator_sources=sources))
        return InterpretationResponse(dict(schema_version=SCHEMA,candidates=candidates),
            provenance=dict(usage_reported=True,raw_compact_response=self.payload,recorded_source=self.source,
                interpretation_kind='recorded_failure_replay'),external_calls=0,input_tokens=0,output_tokens=0)


def read(pin):return json.loads(read_pinned(pin['path'],pin['sha256']))


def main(*,receipt_path,receipt_sha256,output):
    commit=source_commit();root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    source=dict(path=receipt_path,sha256=receipt_sha256);gate=read(source);inputs=read(gate['inputs'])
    if gate['track']!='nl' or len(gate['cases'])!=2 or not gate['all_owned_closed']:
        raise ValueError('Expected sealed two-call NL readiness source with closed services')
    request=read(inputs['request']);policy=ScopePolicy.from_dict(read(inputs['scope']))
    oracle=inputs['oracle'];cases=[]
    for case in gate['cases']:
        path=root/case['id'];path.mkdir()
        old=read(case['outcome']);saved=read_json_evidence(old['core'])
        if old['status']!='intent_outside_proposed_scope' or old['model_calls']!=1:
            raise ValueError('Unexpected source failure class')
        config_pin=inputs['configurations'][str(case['feedback'])]
        config,information,limits,costs=load_configuration(config_pin['path'],config_pin['sha256'])
        _,runtime,calls=local_runtime();schema=runtime.pop('source_schema')
        provider=RecordedProposal(saved['interpretation']['provenance']['raw_compact_response'],old['core'])
        result=answer(InterpretationRequest(request['question'],{'source_schema':schema}),provider,
            mode=case['mode'],epsilon='0' if case['mode']=='exact' else config['epsilon'],scope_policy=policy,
            authority=QueryIntentAuthority(Path(oracle['path']),oracle['sha256']),
            information=information,limits=limits,costs=costs,**runtime)
        sealed=write_json_evidence(path/'core.json.gz',result)
        # Private/reference data are scored after the replay outcome is durable.
        private=read(oracle);reference=read(inputs['reference']);observed=read_json_evidence(sealed);loss=None;violation=None
        if observed['final_plan_executions']==1:
            joint=observed['joint_policy'];cert=joint['terminal_certificate']
            loss=aligned_query_loss(joint['selected_query'],private['query'],observed['intent_family'],
                language_version=private['language_version'])
            upper=Fraction(**cert['upper_bound']);epsilon=Fraction(**cert['epsilon'])
            violation=loss is None or loss>upper or upper>epsilon
        row=dict(id=case['id'],mode=case['mode'],source_failed_outcome=case['outcome'],core=sealed,
            status=observed['status'],success=observed['success'],model_calls=observed['model_calls'],
            final_plan_executions=observed['final_plan_executions'],clarification_calls=observed['clarification_calls'],
            answer_em=int(observed['answer_rows']==reference['rows']),loss=float(loss) if loss is not None else None,
            certificate_violation=violation,rdf_query_calls=len(calls))
        write_once(path/'terminal.json',row);cases.append(row)
    passed=all(c['success'] and c['model_calls']==0 and c['final_plan_executions']==1 and c['certificate_violation'] is False
        and (c['mode']!='exact' or c['answer_em']==1) for c in cases)
    pin=write_once(root/'receipt.json',dict(schema_version='xgap-sealed-proposal-replay-v1',source=source,
        source_commit=commit,query_identity=IDENTITY_VERSION,deployment='toy RDFLib sources',paper_result=False,
        new_model_calls=0,fresh_model_quality_measurement=False,cases=cases,passed=passed))
    print(json.dumps(dict(receipt=pin,passed=passed,cases=cases)))
    return 0 if passed else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('receipt-path','receipt-sha256','output'):p.add_argument('--'+name,required=True)
    raise SystemExit(main(**vars(p.parse_args())))
