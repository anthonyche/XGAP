#!/usr/bin/env python3
"""Replay one pinned Exact interaction trace without invoking any information tool."""
import argparse
import hashlib
import json
from pathlib import Path

from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.terminal_opportunity import replay_user_prefixes


def main(core_path,core_sha256,request_path,request_sha256,output,legacy_cells=None):
    core=json.loads(read_pinned(core_path,core_sha256))
    request=json.loads(read_pinned(request_path,request_sha256))
    report=replay_user_prefixes(core,question=request['question'])
    report['inputs']={'core':{'path':str(core_path),'sha256':core_sha256},
        'request':{'path':str(request_path),'sha256':request_sha256}}
    if legacy_cells:
        raw=Path(legacy_cells).read_bytes();cells=json.loads(raw)
        exact=[c for c in cells if c['method']=='xgap-nl-strong-exact']
        completed=[]
        for cell in exact:
            if not cell['success']:continue
            path=Path(cell['receipt']).parent/'worker/core.json';data=path.read_bytes();old=json.loads(data)
            if old['profile_id']!='nl-conditional-strong-k1-v1':raise ValueError('Unexpected legacy profile')
            if old['practical']['clarification_calls']!=0 or old['probe_calls']!=0:
                raise ValueError('Legacy trace has unaccounted information actions')
            completed.append({'deployment':cell['deployment'],'question_id':cell['question_id'],
                'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),
                'model_calls':old['model_calls'],'clarification_calls':0,'probe_calls':0})
        report['legacy_nl_only']={'input_sha256':hashlib.sha256(raw).hexdigest(),
            'exact_attempts':len(exact),'complete_exact_traces':len(completed),'complete_traces':completed,
            'scope':'No user acquisition actions enabled; cannot infer an interaction frontier from this cohort'}
    root=Path(output);root.mkdir(parents=True,exist_ok=False)
    pin=write_once(root/'prefix-replay.json',report)
    summary={'schema_version':'xgap-terminal-opportunity-summary-v1','prefixes':len(report['prefixes']),
        'earliest_certified_prefix':report['earliest_certified_prefix'],
        'eligibility_unknown_count':report['eligibility_unknown_count'],
        'optimistic_measured_acquisition_ceiling':report['prefixes'][0]['optimistic_remaining_acquisition_ceiling'],
        'model_calls_already_paid':report['initial_model_calls_already_paid'],'backend_calls_saved':None,
        'total_cost_saved':None,'coverage_gain':None,'empirical_discrepancy':None,'root_gap':None,
        'certificate_available':False,'new_model_calls':0,'new_backend_calls':0,'new_oracle_calls':0,
        'legacy_exact_attempts':report.get('legacy_nl_only',{}).get('exact_attempts'),
        'legacy_complete_traces':report.get('legacy_nl_only',{}).get('complete_exact_traces'),
        'prefix_artifact':pin}
    result=write_once(root/'summary.json',summary)
    print(json.dumps({'summary':summary,'artifact':result}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('core-path','core-sha256','request-path','request-sha256','output'):
        p.add_argument('--'+name,required=True)
    p.add_argument('--legacy-cells')
    main(**vars(p.parse_args()))
