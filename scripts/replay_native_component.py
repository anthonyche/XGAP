#!/usr/bin/env python3
"""Replay a bounded native component using exact captured requests; zero network."""
import argparse
import hashlib
import json
from pathlib import Path

from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import BackendReplay, write_once
from xgap.runtime.contracts import FederatedExecutionPlan
from xgap.runtime.scheduler import FederatedScheduler
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


def pin(path):
    raw=path.read_bytes()
    return {'path':str(path.resolve()),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}


def main(component_root,output):
    source=Path(component_root).resolve();root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    receipt={'schema_version':'xgap-native-component-replay-v1','success':False,'network_calls':0,
             'model_calls':0,'paper_result':False,'original_execution_repeated':False}
    try:
        selection=pin(source/'selection.json');outcome_pin=pin(source/'outcome.json')
        selected=json.loads(read_pinned(selection['path'],selection['sha256']))
        outcome=json.loads(read_pinned(outcome_pin['path'],outcome_pin['sha256']))
        original=json.loads(read_pinned(outcome['result']['path'],outcome['result']['sha256']))
        plan=FederatedExecutionPlan.from_dict(selected['selected_plan'])
        if plan.plan_id!=original['plan_id']:raise ValueError('Selected plan and original result differ')
        captures=sorted(source.glob('backend-*-result.json'))
        if not 1<=len(captures)<=64:raise ValueError('Replay requires 1..64 bounded component captures')
        records=[]
        for path in captures:
            reference=pin(path);record=json.loads(read_pinned(reference['path'],reference['sha256']))
            if record['status']!='returned':raise ValueError('Incomplete original source capture')
            records.append({'backend_id':record['backend_id'],'artifact':record['artifact'],
                            'status':'returned','response_record':reference})
        receipt['input']=write_once(root/'input.json',{'selection':selection,'outcome':outcome_pin,
            'original_result':outcome['result'],'records':records})
        clients={b:BackendReplay(b,[r for r in records if r['backend_id']==b])
                 for b in {r['backend_id'] for r in records}}
        registry=BackendPluginRegistry()
        for b,c in clients.items():registry.register(NativeBackendPlugin(b,c))
        replay=FederatedScheduler(BackendInvokeTool(registry)).execute(plan)
        receipt['result']=write_once(root/'replay.json',replay.to_dict())
        consumed=all(c.position==len(c.records) for c in clients.values())
        outcomes=lambda rows:{n['node_id']:(n['kind'],n['status'],n['error'],n['row_count']) for n in rows}
        same_nodes=outcomes(replay.to_dict()['node_results'])==outcomes(original['node_results'])
        same_roots=replay.to_dict()['root_rows']==original['root_rows']
        receipt.update(success=(replay.success==original['success'] and list(replay.final_rows)==original['final_rows']
                               and consumed and same_nodes and same_roots),all_captures_consumed_once=consumed,
            same_node_outcomes=same_nodes,same_root_rows=same_roots,
            original_execution_success=original['success'],replayed_execution_success=replay.success,
            replayed_request_count=sum(c.position for c in clients.values()),
            actual_capture_count=len(records),same_final_rows=list(replay.final_rows)==original['final_rows'])
    except Exception as error:
        receipt.update(error_type=type(error).__name__,error=str(error))
    record=write_once(root/'receipt.json',receipt)
    print(json.dumps({'success':receipt['success'],'receipt':record,'network_calls':0,
        'all_captures_consumed_once':receipt.get('all_captures_consumed_once'),'error':receipt.get('error')}))
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--component-root',required=True);parser.add_argument('--output',required=True)
    raise SystemExit(main(**vars(parser.parse_args())))
