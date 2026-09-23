#!/usr/bin/env python3
"""Bounded CWRU CPU preflight. Credentials are inherited, never written.

Run on a Slurm CPU allocation, not a login node. This checks storage and one
existing external LLM call; it does not start a formal campaign or a local model.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import time
from urllib.request import Request,urlopen


def check(output, *,model_smoke=False):
    if not os.environ.get('SLURM_JOB_ID'):
        raise ValueError('CPU preflight requires a scheduler allocation')
    if os.environ.get('SLURM_JOB_GPUS') or os.environ.get('SLURM_GPUS_ON_NODE') not in (None,'','0'):
        raise ValueError('This preparation must not allocate GPUs')
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    receipt=dict(schema_version='xgap-ch6-cpu-host-v1',success=False,host=socket.gethostname(),
        job_id=os.environ['SLURM_JOB_ID'],python=platform.python_version(),platform=platform.platform(),
        gpu_requested=False,local_model=False,model_calls=0,formal_campaign_started=False,
        root=str(root),personal_quota_verified=False)
    try:
        payload=b'\0'*(4*1024**2);sample=root/'storage-probe.bin'
        with sample.open('xb') as stream:
            stream.write(payload);stream.flush();os.fsync(stream.fileno())
        digest=hashlib.sha256(sample.read_bytes()).hexdigest()
        if digest!=hashlib.sha256(payload).hexdigest():raise ValueError('Storage round trip mismatch')
        receipt.update(storage_probe_sha256=digest,filesystem_free_bytes=shutil.disk_usage(root).free)
        if receipt['filesystem_free_bytes']<8*1024**3:raise ValueError('Insufficient filesystem reserve')
        repo=Path(__file__).resolve().parents[1]
        receipt['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
        if subprocess.check_output(['git','status','--porcelain'],cwd=repo):raise ValueError('Source worktree dirty')
        from xgap.api import answer_unified,answer_unified_controlled
        from xgap.experiments.ch6_formal_protocol import registry
        receipt['interfaces_imported']=bool(answer_unified and answer_unified_controlled)
        receipt['figures']=registry()['figure_count']
        if model_smoke:
            key=os.environ['XGAP_EXTERNAL_LLM_API_KEY']
            url='http://112.95.75.67:9018/v1/chat/completions'
            body=json.dumps(dict(model='qwen3.8-27b',messages=[dict(role='user',content='Reply with OK only.')],
                max_tokens=8,temperature=0,chat_template_kwargs=dict(enable_thinking=False))).encode()
            start=time.perf_counter();receipt['model_calls']=1
            with urlopen(Request(url,data=body,headers={'Content-Type':'application/json','Authorization':'Bearer '+key}),timeout=45) as response:
                result=json.loads(response.read(65536))
            text=result['choices'][0]['message']['content']
            receipt.update(model_id=result.get('model'),model_ms=(time.perf_counter()-start)*1000,
                model_usage=result.get('usage'),model_output=text)
            if not isinstance(text,str) or not text.strip():raise ValueError('Empty model response')
        receipt['success']=True
    except Exception as error:
        receipt.update(error_type=type(error).__name__)
    finally:
        (root/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt));return 0 if receipt['success'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    parser.add_argument('--model-smoke',action='store_true');args=parser.parse_args()
    raise SystemExit(check(**vars(args)))
