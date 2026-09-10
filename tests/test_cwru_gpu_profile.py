"""Alternate allocation validation and the actual shell-to-vLLM argument boundary."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

import pytest

from xgap.experiments.cwru_gpu_profile import PROFILES, profile_for, validate_recorded_profile, visible_gpu_record
from xgap.experiments.cwru_vllm import CWRUVLLMContract, verify_preflight_token_budget
from xgap.experiments.grailqa_preflight import GrailQAPreflightSpec

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT/'experiments/environments/cwru_pioneer_qwen3_32b_l40s_pipeline2_v1.json'
SPEC = ROOT/'experiments/specs/grailqa_semantic_preflight_inline_grounding_v1_cwru_qwen3_32b_l40s_pipeline2.json'
LEGACY = ROOT/'experiments/environments/cwru_pioneer_qwen3_32b_vllm.json'


def devices():
    return [{'cuda_index':i,'model':'NVIDIA L40S','memory_mib':46068,'compute_major':8,'compute_minor':9}
            for i in range(2)]


def test_alternate_spec_keeps_exact_inference_population_and_model():
    old = GrailQAPreflightSpec.load(ROOT/'experiments/specs/grailqa_semantic_preflight_inline_grounding_v1_cwru_qwen3_32b.json')
    new = GrailQAPreflightSpec.load(SPEC)
    allowed = {'experiment_id','run_id_prefix','deployment_contract','deployment_contract_hash','freeze_hash'}
    assert {k:v for k,v in old.data.items() if k not in allowed} == {k:v for k,v in new.data.items() if k not in allowed}
    contract = CWRUVLLMContract.load(CONTRACT)
    assert profile_for(contract.data).pipeline_parallel_size == 2
    assert verify_preflight_token_budget(repo_root=ROOT,spec_path=SPEC,contract_path=CONTRACT)['status']=='pass'


@pytest.mark.parametrize('field,value', [('dtype','float16'),('model','Qwen/Qwen3-8B'),
    ('max_model_len',8192),('tensor_parallel_size',True),('pipeline_parallel_size',1)])
def test_resource_fallback_cannot_change_inference_contract(field,value):
    data = deepcopy(CWRUVLLMContract.load(CONTRACT).data)
    data['serving'][field]=value
    with pytest.raises(ValueError): profile_for(data)


@pytest.mark.parametrize('bad', ['one_device','wrong_model','insufficient_memory','old_compute','bad_index'])
def test_every_visible_device_must_fit_the_profile(bad):
    observed = devices()
    if bad=='one_device': observed.pop()
    elif bad=='wrong_model': observed[1]['model']='NVIDIA GeForce RTX 4090'
    elif bad=='insufficient_memory': observed[1]['memory_mib']=24000
    elif bad=='old_compute': observed[1]['compute_major']=7
    else: observed[1]['cuda_index']=0
    with pytest.raises(ValueError): visible_gpu_record(PROFILES['l40s-pipeline2-v1'],observed,job_id='123')


def test_legacy_contract_has_no_extra_arguments_or_cuda_dependency():
    assert profile_for(CWRUVLLMContract.load(LEGACY).data) is None
    result=subprocess.run([sys.executable,'-m','xgap.experiments.cwru_gpu_profile','--contract',str(LEGACY)],
        env={**os.environ,'PYTHONPATH':str(ROOT/'src')},capture_output=True,text=True,timeout=20)
    assert result.returncode==0 and result.stdout==''


def test_recorded_profile_binds_each_device_parallelism_and_job():
    profile=PROFILES['l40s-pipeline2-v1']
    record=visible_gpu_record(profile,devices(),job_id='123')
    environment={'gpu':record,'slurm':{'job_id':'123'},'model':{'tensor_parallel_size':1,'pipeline_parallel_size':2}}
    contract=CWRUVLLMContract.load(CONTRACT).data
    validate_recorded_profile(contract,environment)
    for key,value in [('device_count',1),('tensor_parallel_size',True),('pipeline_parallel_size',1),('slurm_job_id','456')]:
        changed=deepcopy(environment);changed['gpu'][key]=value
        with pytest.raises(ValueError): validate_recorded_profile(contract,changed)
    environment['model']['pipeline_parallel_size']=1
    with pytest.raises(ValueError): validate_recorded_profile(contract,environment)


@pytest.mark.parametrize('mode', ['l40s','wrong','legacy'])
def test_actual_launcher_checks_cuda_before_starting_and_passes_parallel_args(tmp_path,mode):
    valid = mode != 'wrong'
    repo=tmp_path/'repo'; scripts=repo/'scripts/cwru'; scripts.mkdir(parents=True)
    for name in ('common.sh','launch_vllm_qwen3_32b.sh'):
        shutil.copyfile(ROOT/'scripts/cwru'/name,scripts/name)
    src=repo/'src';src.mkdir();(src/'xgap').symlink_to(ROOT/'src/xgap',target_is_directory=True)
    observed=devices()
    if not valid: observed[1]['model']='NVIDIA V100'
    (src/'torch.py').write_text('from types import SimpleNamespace\nDATA='+repr(observed)+'''\nclass cuda:
 @staticmethod
 def device_count(): return len(DATA)
 @staticmethod
 def get_device_properties(i):
  d=DATA[i]
  return SimpleNamespace(name=d['model'],total_memory=d['memory_mib']*1024*1024,major=d['compute_major'],minor=d['compute_minor'])
''')
    envdir=tmp_path/'venv';bins=envdir/'bin';bins.mkdir(parents=True)
    python=bins/'python'
    python.write_text('#!'+sys.executable+'''\nimport os,sys
if sys.argv[1:3]==['-m','xgap.experiments.cwru_vllm']:
 if sys.argv[3]=='verify-environment': sys.exit(0)
 if sys.argv[3]=='resolve-revision': print('a'*40);sys.exit(0)
os.execv(sys.executable,[sys.executable,*sys.argv[1:]])
''');python.chmod(0o755)
    (bins/'activate').write_text('export PATH="'+str(bins)+':$PATH"\n')
    (bins/'nvidia-smi').write_text('#!/bin/sh\nexit 0\n');(bins/'nvidia-smi').chmod(0o755)
    executable=bins/'vllm'
    executable.write_text('#!'+sys.executable+'''\nimport json,os,sys,time
from pathlib import Path
Path(os.environ['TEST_ARGV']).write_text(json.dumps(sys.argv[1:]))
time.sleep(30)
''');executable.chmod(0o755)
    out=tmp_path/'run';argv=tmp_path/'argv.json'
    env={**os.environ,'XGAP_REPO_ROOT':str(repo),'XGAP_CWRU_CONTRACT':str(LEGACY if mode=='legacy' else CONTRACT),'VLLM_ENV':str(envdir),
         'XGAP_MODEL_REVISION':'a'*40,
         'SLURM_JOB_ID':'123','XGAP_CWRU_RUN_ROOT':str(out),'XGAP_VLLM_LOG':str(out/'vllm.log'),
         'XGAP_VLLM_PID_FILE':str(out/'vllm.pid'),'TEST_ARGV':str(argv)}
    # The stand-in daemon belongs to this process group and is stopped in finally.
    process=subprocess.Popen(['bash',str(scripts/'launch_vllm_qwen3_32b.sh')],env=env,
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
    try:
        stdout,stderr=process.communicate(timeout=15)
        if valid:
            assert process.returncode==0,(stdout,stderr)
            args=json.loads(argv.read_text())
            expected=[('--dtype','bfloat16'),('--max-model-len','12288')]
            if mode=='legacy':
                assert '--pipeline-parallel-size' not in args and '--tensor-parallel-size' not in args
            else:
                expected += [('--tensor-parallel-size','1'),('--pipeline-parallel-size','2'),
                             ('--distributed-executor-backend','mp')]
            for flag,value in expected:
                assert args[args.index(flag)+1]==value
        else:
            assert process.returncode!=0 and not argv.exists()
    finally:
        try: os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError: pass
