#!/usr/bin/env python3
"""One live bounded non-authoritative proposal; no source query or retry."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess

from xgap.agent.practical_planning import program_identity
from xgap.agent.practical_tools import openai_candidate_acquisition
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.toy_binding import load_binding_cases
from xgap.llm.openai_compatible import OpenAICompatibleProviderConfig
from xgap.llm.resolution import M15_RESOLUTION_BASE_SCHEMA, OpenAICompatibleResolutionCandidateProvider
from xgap.semantic.program import SemanticGraphProgram
from xgap.tools.contracts import ToolContext, ToolStatus


def main(output,read_key=False):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    receipt={'schema_version':'xgap-practical-live-proposal-gate-v1','success':False,
        'model_call_budget':1,'source_calls':0,'fit_calls':0,'automatic_retries':0,'paper_result':False,
        'scope':'live candidate adapter only; not end-to-end interpretation/answer accuracy'}
    key_name='XGAP_EXTERNAL_LLM_API_KEY';previous=os.environ.get(key_name)
    try:
        if subprocess.check_output(['git','status','--porcelain'],text=True):
            raise ValueError('Commit before the live adapter gate')
        receipt['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
        key=getpass.getpass('LLM credential (not recorded): ') if read_key else previous
        if not key:raise ValueError('Missing configured model credential')
        os.environ[key_name]=key;key=None
        case=load_binding_cases()[0];program=SemanticGraphProgram.from_dict(case['program'])
        prompt=('Select the single candidate ID that best matches the requested semantic slot. '
            'Use only the supplied candidate IDs. Return a JSON object with hole_id and candidate_ids. '
            'Never return a native query or claim semantic authority.')
        config=OpenAICompatibleProviderConfig(provider_id='practical-live-slot-v1',
            base_url='http://112.95.75.67:9018/v1',api_key_env=key_name,model='qwen3.8-27b',
            temperature=0,top_p=1,max_tokens=512,candidate_cap=2,timeout_seconds=45,
            structured_output_mode='json_schema',structured_schema=M15_RESOLUTION_BASE_SCHEMA,
            prompt_hash=hashlib.sha256(prompt.encode()).hexdigest(),max_repair_calls=0,
            extra_parameters={'chat_template_kwargs':{'enable_thinking':False}})
        provider=OpenAICompatibleResolutionCandidateProvider(config,prompt)
        action,tool=openai_candidate_acquisition(program,'predicate',('predicate:knows','predicate:works_for'),
            provider,question=case['nl'],token_budget=4096)
        arguments={'action_id':action.action_id,'slot':action.slot,'program_sha256':program_identity(program),
            'source_id':action.source_id,'version':action.version,
            'candidates':[c for _,c in action.outcomes if c is not None]}
        receipt['intent']=write_once(root/'intent.json',{'question':case['nl'],'arguments':arguments,
            'config':config.safe_dict(),'system_prompt_sha256':config.prompt_hash,
            'declared_outcomes':list(action.outcomes),'authority':action.authority,
            'model_call_budget':1,'expected_candidate_for_protocol_check':'predicate:knows',
            'expected_candidate_supplied_to_model':False})
        result=tool.invoke(arguments,ToolContext('live-proposal-gate',0,'one-call'))
        receipt['result']=write_once(root/'result.json',result.to_dict())
        if provider.last_invocation is not None:
            receipt['invocation']=write_once(root/'invocation.json',provider.last_invocation.to_dict())
        receipt.update(status=result.status.value,metrics=dict(result.metrics),
            success=(result.status is ToolStatus.SUCCESS and result.value['candidate_id']=='predicate:knows'
                     and result.metrics.get('model_calls')==1 and result.metadata.get('authoritative') is False))
    except Exception as error:
        receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        if previous is None:os.environ.pop(key_name,None)
        else:os.environ[key_name]=previous
        receipt['credential_recorded']=False
        pin=write_once(root/'receipt.json',receipt)
    print(json.dumps({'success':receipt['success'],'receipt':pin,'status':receipt.get('status'),
        'metrics':receipt.get('metrics'),'error':receipt.get('error')}),flush=True)
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--read-key',action='store_true')
    raise SystemExit(main(**vars(parser.parse_args())))
