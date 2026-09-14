"""One strong-mode worker with an explicit trusted-template measurement scope.

This adapter changes no baseline and reads no answer oracle. Common trial owns
process/source budgets; standalone use also has the supplied wall deadline.
"""
import json
import math
from pathlib import Path
import time

from xgap.experiments.external_federation import deadline
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.practical_profile import REQUEST_SCHEMA
from xgap.experiments.practical_records import run_record


METHODS={'xgap-strong-exact':'exact','xgap-strong-performance':'performance'}


def _usage(core,calls):
    if calls==0:return {'input_tokens':0,'output_tokens':0}
    invocations=list(core.get('model_invocations',{}).values())
    complete=(calls is not None and invocations and
        sum(v.get('generation_calls',0)+v.get('repair_calls',0) for v in invocations)==calls)
    usage={}
    for key in ('input_tokens','output_tokens'):
        values=[v.get('usage',{}).get(key) for v in invocations]
        usage[key]=sum(values) if complete and all(type(v) is int and v>=0 for v in values) else None
    return usage


def run_practical(*,request_path,request_sha256,profile_path,profile_sha256,method,output,endpoint=None,seconds=180):
    root=Path(output);root.mkdir(parents=True,exist_ok=False);started=time.perf_counter();active=False
    r={'schema_version':'xgap-nl-method-worker-v1','method':method,'track':'trusted_template',
        'success':False,'status':'preparing','request_sha256':request_sha256,'profile_sha256':profile_sha256,
        'result':None,'model_calls':0,'input_tokens':0,'output_tokens':0,'fit_calls':0,'probe_calls':0,
        'automatic_retries':0,'top_level_attempts':0,'alternative_executions':0,'paper_result':False,
        'input_scope':'pinned trusted template and declared binding authority; not unaided open-domain NL'}
    try:
        if method not in METHODS or endpoint is not None:raise ValueError('Expected an explicitly named strong method without an external method endpoint')
        if type(seconds) not in (int,float) or not math.isfinite(seconds) or seconds<=0:raise ValueError('Finite positive worker deadline required')
        request=json.loads(read_pinned(request_path,request_sha256))
        if request.get('schema_version')!=REQUEST_SCHEMA:raise ValueError('Strong worker requires its declared trusted-template request schema')
        r.update({k:request[k] for k in ('question_id','population','exposure')})
        doc=json.loads(read_pinned(profile_path,profile_sha256));r['dataset']=doc['dataset']
        active=True
        with deadline(seconds):
            child=run_record(profile_path=profile_path,profile_sha256=profile_sha256,request_path=request_path,
                request_sha256=request_sha256,mode=METHODS[method],output=root/'core',operation='execute')
        active=False
        r.update(model_calls=child['model_network_calls'],backend_calls=child['source_network_calls'],
            top_level_attempts=child['final_plan_executions'],status=child.get('status','record_failed'),
            execution_kind=child.get('execution_kind'),admission_ms=child.get('admission_ms'))
        # Read only the just-sealed method output, never a scoring/reference artifact.
        pin=child.get('result');core=json.loads(read_pinned(pin['path'],pin['sha256'])) if pin else {}
        r.update(_usage(core,r['model_calls']))
        execution=core.get('execution',{})
        r.update(success=bool(child['success'] and core.get('success')),status=core.get('status',r['status']),
            planning_ms=core.get('search',{}).get('elapsed_ms'),
            execution_ms=execution.get('result',{}).get('value',{}).get('elapsed_ms'),
            acquisition_ms=core.get('acquisition_ms'),clarification_calls=core.get('clarification_calls'),
            interpretation_ms=(core.get('interpretation') or {}).get('elapsed_ms'),
            grounding_ms=None,frontend_ms=None,compilation_ms=None,
            request_total_ms=core.get('request_total_ms'),core_result=pin,
            strong_plan=core.get('search',{}).get('strong'),optimality_certified=False,
            semantic_discrepancy_upper_bound=core.get('semantic_discrepancy_upper_bound'),
            discrepancy_status=core.get('discrepancy_status'),
            semantic_validation=execution.get('semantic_validation'),
            unvalidated_bindings=execution.get('unvalidated_bindings'),
            usage_complete=all(r[k] is not None for k in ('model_calls','input_tokens','output_tokens')))
        r['result']=write_once(root/'answer.json',{'answer_format':'json_rows',
            'answer':core.get('answer_rows') if r['success'] else None,
            'input_scope':r['input_scope'],'semantic_validation':r['semantic_validation'],
            'unvalidated_bindings':r['unvalidated_bindings'],'discrepancy_status':r['discrepancy_status'],
            'semantic_discrepancy_upper_bound':r['semantic_discrepancy_upper_bound']})
    except Exception as error:
        r.update(success=False,status='worker_failed',error_type=type(error).__name__,error=str(error))
        if active:r.update(model_calls=None,input_tokens=None,output_tokens=None,usage_complete=False)
    finally:
        r['worker_ms_before_receipt']=(time.perf_counter()-started)*1000;write_once(root/'receipt.json',r)
    return r
