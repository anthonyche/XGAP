#!/usr/bin/env python3
"""Replay the sealed tiny retention gate after a replay-only correction."""
import argparse
import json
from pathlib import Path
import socket
import subprocess

from prepare_rdf_tdb import REPO
from xgap.agent.question import run_question
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned
from xgap.experiments.one_shot_records import BackendReplay, write_once
from xgap.semantic.interpretation import InterpretationRequest, InterpretationResponse
from xgap.semantic.interpretation_candidates import SCHEMA


def main(receipt_path, receipt_sha256, output):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):
        raise ValueError('Commit before recorded replay')
    old=json.loads(read_pinned(receipt_path,receipt_sha256))
    if old['schema_version']!='xgap-retention-native-v1' or old.get('answer_em')!=1:
        raise ValueError('Expected the sealed exact tiny native result')
    outcome=json.loads(read_pinned(old['outcome']['path'],old['outcome']['sha256']))
    original=json.loads(read_pinned(outcome['core']['path'],outcome['core']['sha256']))
    profile=FrozenOneShotProfile.load(old['serving_profile']['path'],expected_sha256=old['serving_profile']['sha256'])
    doc,model,_,sources,backends,_,modes=profile.materialize()
    recorded=original['interpretation']['candidates'][0]
    class Saved:
        provider_id='saved-tiny-retention-interpretation'
        def interpret(self,request):
            return InterpretationResponse({'schema_version':SCHEMA,'candidates':[{
                k:recorded[k] for k in ('candidate_id','quality_proxy','program','operator_sources')}]})
    records=json.loads(read_pinned(old['backend_ledger']['path'],old['backend_ledger']['sha256']))
    clients={b:BackendReplay(b,[r for r in records if r['backend_id']==b]) for b in backends}
    def no_network(*args,**kwargs):raise RuntimeError('Offline replay forbids network access')
    socket.socket.connect=no_network
    result=run_question(InterpretationRequest('Execute the independently authored tiny constrained path request.',
        context={'query_id':'tiny-frozen-key-bound-v1'}),Saved(),mode='performance',
        one_shot_policy=modes['performance'][0],estimator=model,
        catalog_root=profile.root/doc['catalog']['path'],catalog_hash=doc['catalog']['bundle_hash'],
        sources=sources,backends=backends,backend_clients=clients)
    core=write_once(root/'core.json',result)
    ok=(result['success'] and result['answer_rows']==original['answer_rows']
        and result['selected_plan']==original['selected_plan']
        and all(c.position==len(c.records) for c in clients.values()))
    receipt={'schema_version':'xgap-retention-native-replay-v1','success':ok,'core':core,
        'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        'original_receipt':{'path':str(Path(receipt_path).resolve()),'sha256':receipt_sha256},
        'original_record_unchanged':True,'same_selected_plan':result['selected_plan']==original['selected_plan'],
        'same_exact_answer':result['answer_rows']==original['answer_rows'],
        'response_records_consumed':sum(c.position for c in clients.values()),
        'model_calls':0,'backend_network_calls':0,'fit_calls':0,'data_loads':0,'paper_result':False}
    pin=write_once(root/'receipt.json',receipt)
    print(json.dumps({'success':ok,'receipt':pin,'response_records_consumed':receipt['response_records_consumed']}))
    return 0 if ok else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for field in ('receipt-path','receipt-sha256','output'):parser.add_argument('--'+field,required=True)
    raise SystemExit(main(**vars(parser.parse_args())))
