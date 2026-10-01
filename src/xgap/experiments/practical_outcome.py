"""Small practical-worker handoff, with the full trace retained under its pin."""
import json

from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once


SCHEMA='xgap-practical-outcome-v1'


def write_outcome(root,core,trace):
    """Copy only consumed answer/usage fields; never intermediate result rows."""
    result={k:core.get(k) for k in ('success','status','answer_rows','final_plan_executions',
        'backend_remote_calls','model_calls','tokens','acquisition_ms','clarification_calls',
        'request_total_ms','semantic_discrepancy_upper_bound','discrepancy_status')}
    result['search']={k:core.get('search',{}).get(k) for k in ('strong','elapsed_ms')}
    result['interpretation']={'elapsed_ms':(core.get('interpretation') or {}).get('elapsed_ms')}
    execution=core.get('execution') or {}
    result['execution']={k:execution.get(k) for k in ('semantic_validation','unvalidated_bindings')}
    result['execution']['result']={'value':{'elapsed_ms':
        ((execution.get('result') or {}).get('value') or {}).get('elapsed_ms')}}
    result['model_invocations']={name:{k:value[k] for k in ('generation_calls','repair_calls','usage') if k in value}
        for name,value in core.get('model_invocations',{}).items()}
    return write_once(root/'outcome.json',{'schema_version':SCHEMA,'trace':trace,'result':result})


def read_outcome(receipt):
    if 'outcome' in receipt:
        pin=receipt['outcome']
        if pin is None:return {}
        outcome=json.loads(read_pinned(pin['path'],pin['sha256']))
        if outcome.get('schema_version')!=SCHEMA or outcome.get('trace')!=receipt.get('result'):
            raise ValueError('Practical outcome/trace identity mismatch')
        return outcome['result']
    # Legacy bounded development records remain readable; no large trace fallback
    # is attempted when a new producer explicitly failed to seal an outcome.
    pin=receipt.get('result')
    return json.loads(read_pinned(pin['path'],pin['sha256'])) if pin else {}
