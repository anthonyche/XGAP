"""Use the common process guard for one existing XGAP request or offline replay."""
import hashlib
import json
from pathlib import Path
import sys

from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import RUN_SCHEMA, write_once
from xgap.experiments.process_guard import ProcessBudget, run_guarded_command


def _fingerprint(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return {'path':str(path),'sha256':digest.hexdigest(),'bytes':path.stat().st_size}


def run_guarded_record(*, profile_path, profile_sha256, request_path, request_sha256,
                       mode, output, budget_path, budget_sha256, operation='preflight',
                       replay_path=None,replay_sha256=None):
    if mode not in ('precision','performance') or operation not in ('preflight','execute','replay'):
        raise ValueError('Unknown operation/mode')
    budget_doc=json.loads(read_pinned(budget_path,budget_sha256))
    if set(budget_doc)!={'schema_version','process_budget'} or budget_doc['schema_version']!='xgap-request-budget-v1':
        raise ValueError('Unsupported process budget contract')
    budget=ProcessBudget(**budget_doc['process_budget'])
    profile=json.loads(read_pinned(profile_path,profile_sha256))
    request=json.loads(read_pinned(request_path,request_sha256))
    # These identities survive failure during the child's heavier preparation.
    identity={k:request[k] for k in ('question_id','population','exposure')}
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    repo=Path(__file__).resolve().parents[3]
    command=[sys.executable,str(repo/'scripts/run_one_shot_record.py'),'run',
        '--profile-path',str(Path(profile_path).resolve()),'--profile-sha256',profile_sha256,
        '--request-path',str(Path(request_path).resolve()),'--request-sha256',request_sha256,
        '--mode',mode,'--operation',operation,'--output',str(root/'worker')]
    if operation=='replay':
        if replay_path is None or replay_sha256 is None:raise ValueError('Replay needs a pinned artifact')
        command+=['--replay-path',str(Path(replay_path).resolve()),'--replay-sha256',replay_sha256]
    guard=run_guarded_command(command,cwd=repo,output=root/'guard',budget=budget)
    child=None;child_error=None;partial=[]
    for p in sorted((root/'worker').glob('*.json')):
        # Preserve even interrupted/invalid JSON bytes; never infer success from a filename.
        partial.append(_fingerprint(p))
    receipt_path=root/'worker/receipt.json'
    if receipt_path.exists():
        try:
            child=json.loads(read_pinned(receipt_path,_fingerprint(receipt_path)['sha256']))
            if (child.get('schema_version')!=RUN_SCHEMA or child.get('profile_sha256')!=profile_sha256
                    or child.get('request_sha256')!=request_sha256 or child.get('operation')!=operation):
                raise ValueError('Child receipt identity mismatch')
        except (ValueError,TypeError) as error:
            child_error=str(error);child=None
    receipt={**(child or {}),'schema_version':RUN_SCHEMA,**identity,'dataset':profile['dataset'],
        'mode':mode,'operation':operation,'execution_kind':'offline_replay' if operation=='replay' else 'live' if operation=='execute' else 'preflight',
        'profile_sha256':profile_sha256,'request_sha256':request_sha256,
        'success':bool(guard['success'] and child and child.get('success')),
        'status':(child['status'] if child else 'worker_receipt_missing_or_invalid') if guard['status']=='completed' else 'guard_'+guard['status'],
        'result':child.get('result') if child else None,
        'guard':{'path':str(root/'guard/receipt.json'),'sha256':hashlib.sha256((root/'guard/receipt.json').read_bytes()).hexdigest()},
        'budget_sha256':budget_sha256,'partial_worker_artifacts':partial,'child_receipt_error':child_error,
        'supervised_end_to_end_ms':guard['decision_wall_ms'],'supervisor_cleanup_ms':(guard['cleanup'] or {}).get('elapsed_ms',0),
        'sampled_peak_method_worker_rss_bytes':guard['sampled_peak_group_rss_bytes'],
        'requires_external_quiescence_barrier':guard['requires_external_quiescence_barrier'],
        'automatic_retries':0,'paper_result':False}
    for key in ('model_network_calls','backend_network_calls','input_tokens','output_tokens','final_plan_executions'):
        if key not in receipt:
            receipt[key]=0 if operation in ('preflight','replay') and key!='final_plan_executions' else None
    if child is None:
        receipt['cost_completeness']='unknown interrupted worker usage; original partial artifacts retained'
    write_once(root/'receipt.json',receipt)
    return receipt
