"""Failure boundaries observed in actual Pioneer job 3799649."""

import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from xgap.experiments import cwru_vllm
from xgap.experiments.cwru_gpu_profile import verify_cuda_health


@pytest.mark.parametrize('phase', ['allocation', 'kernel', 'synchronize', 'healthy'])
def test_every_device_is_exercised_and_second_device_failure_stops(phase, monkeypatch):
    events = []

    def action(stage, index):
        events.append((stage, index))
        if index == 1 and stage == phase:
            raise RuntimeError('CUDA error: uncorrectable ECC error encountered')

    def empty(count, *, dtype, device):
        assert count == 1 and dtype == 'bf16'
        index = int(device.split(':')[1])
        action('allocation', index)
        return SimpleNamespace(fill_=lambda value: action('kernel', index))

    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(
        bfloat16='bf16', empty=empty,
        cuda=SimpleNamespace(synchronize=lambda i: action('synchronize', i))))
    record = {'devices': [{'cuda_index': i} for i in range(3)]}
    if phase == 'healthy':
        verify_cuda_health(record)
        assert events == [(stage, i) for i in range(3)
                          for stage in ('allocation', 'kernel', 'synchronize')]
    else:
        with pytest.raises(ValueError, match='device 1.*uncorrectable ECC'):
            verify_cuda_health(record)
        assert events[:3] == [('allocation', 0), ('kernel', 0), ('synchronize', 0)]
        assert events[-1] == (phase, 1)
        assert all(index < 2 for _, index in events)


def test_dead_server_stops_readiness_before_http_or_sleep():
    def forbidden(*args):
        pytest.fail('Dead server must not perform another HTTP observation or sleep')
    with pytest.raises(cwru_vllm.VLLMReadinessError, match='process exited'):
        cwru_vllm.wait_for_vllm_model(
            base_url='http://127.0.0.1:8000/v1', model='Qwen/Qwen3-32B', api_key='local',
            timeout_seconds=900, process_is_alive=lambda: False,
            fetch_json=forbidden, sleep=forbidden)


def test_server_death_after_one_not_ready_observation_stops_next_poll():
    alive = iter([True, False])
    events = []
    def fetch(*args):
        events.append('fetch')
        return {'data': [{'id': 'wrong-model'}]}
    with pytest.raises(cwru_vllm.VLLMReadinessError, match='process exited'):
        cwru_vllm.wait_for_vllm_model(
            base_url='http://127.0.0.1:8000/v1', model='Qwen/Qwen3-32B', api_key='local',
            timeout_seconds=900, process_is_alive=lambda: next(alive),
            fetch_json=fetch, sleep=lambda _: events.append('sleep'), monotonic=lambda: 0)
    assert events == ['fetch', 'sleep']


def test_live_server_still_requires_exact_model_identity():
    responses = iter([{'data': [{'id': 'wrong-model'}]}, {'data': [{'id': 'Qwen/Qwen3-32B'}]}])
    result = cwru_vllm.wait_for_vllm_model(
        base_url='http://127.0.0.1:8000/v1', model='Qwen/Qwen3-32B', api_key='local',
        timeout_seconds=900, process_is_alive=lambda: True,
        fetch_json=lambda *args: next(responses), sleep=lambda _: None, monotonic=lambda: 0)
    assert result['ready'] and result['attempts'] == 2


@pytest.mark.parametrize('pid', [0, -1, True])
def test_process_probe_rejects_non_specific_pid(pid):
    with pytest.raises(ValueError, match='positive integer'):
        cwru_vllm.server_process_alive(pid)


def test_real_owned_child_exit_is_detected():
    child = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'])
    try:
        assert cwru_vllm.server_process_alive(child.pid)
        child.terminate()
        child.wait(timeout=5)
        assert not cwru_vllm.server_process_alive(child.pid)
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)


def test_linux_zombie_is_not_a_live_server(monkeypatch):
    monkeypatch.setattr(cwru_vllm.sys, 'platform', 'linux')
    monkeypatch.setattr(cwru_vllm.os, 'kill', lambda pid, sig: None)
    monkeypatch.setattr(Path, 'read_text', lambda path: '123 (name with ) parens) Z 1 2 3')
    assert not cwru_vllm.server_process_alive(123)


def test_actual_readiness_shell_passes_owned_pid_and_fails_after_exit(tmp_path):
    root = Path(__file__).resolve().parents[1]
    child = subprocess.Popen([sys.executable, '-c', 'pass'])
    child.wait(timeout=5)
    (tmp_path/'vllm.pid').write_text(str(child.pid)+'\n')
    (tmp_path/'vllm.log').write_text('retained ECC failure\n')
    env = {**os.environ, 'XGAP_REPO_ROOT': str(root), 'XGAP_CWRU_RUN_ROOT': str(tmp_path),
           'VLLM_ENV': str(Path(sys.executable).parent.parent),
           'XGAP_VLLM_PID_FILE': str(tmp_path/'vllm.pid'),
           'XGAP_VLLM_LOG': str(tmp_path/'vllm.log'), 'XGAP_VLLM_READY_TIMEOUT': '900'}
    result = subprocess.run(['bash', str(root/'scripts/cwru/check_vllm_ready.sh')],
                            env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 1
    assert 'server process exited before readiness' in result.stderr
    assert 'retained ECC failure' in result.stderr
