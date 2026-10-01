"""Timed worker lifecycle over real frozen metadata and fake method execution."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ch6_financial_scalability_worker as worker
from xgap.experiments.ch6_financial_scale import generate
from xgap.experiments.ch6_financial_materialize import materialize, pin
from xgap.experiments.ch6_financial_scalability_queries import build_workload, ownership_basis
from xgap.experiments.one_shot_records import write_once


@pytest.fixture(scope='module')
def frozen(tmp_path_factory):
    root = tmp_path_factory.mktemp('scale-worker-canonical')
    generate(root/'canonical', execute=True, nodes_per_bank=9, chunk_rows=100,
        max_output_bytes=4*1024**2, reserve_bytes=0)
    material = materialize(root/'canonical', root/'materialized', execute=True,
        canonical_manifest_sha256=pin(root/'canonical/manifest.json')['sha256'],
        max_output_bytes=16*1024**2, reserve_bytes=0)
    return material, pin(root/'materialized/receipt.json')


def _spec(frozen):
    material, material_pin = frozen
    return dict(case=build_workload(nodes_per_bank=9)['cases'][0], repetition=0, workers=4, method='XGAP',
        materialization=material_pin, client_specs={s['source_id']:dict(engine='fixture') for s in material['sources']})


def _mock_clients(monkeypatch):
    monkeypatch.setattr(worker, 'native_clients', lambda specs:{sid:SimpleNamespace(backend_id=sid) for sid in specs})


def test_actual_frozen_metadata_adds_ownership_proof_without_changing_old_schema(frozen, monkeypatch):
    _mock_clients(monkeypatch); material, _ = frozen
    original = Path(material['source_schema']['path']).read_bytes()
    schema, sources, backends, estimator, assignment, _, clients = worker.prepare_inputs(_spec(frozen))
    assert schema['financial_canonical_ownership'] == ownership_basis(9)
    assert len(sources) == len(backends) == len(set(assignment.values())) == 32
    assert set(assignment) == set(range(32)) and estimator.strict_relative_units
    assert set(clients) == set(sources)
    assert Path(material['source_schema']['path']).read_bytes() == original


@pytest.mark.parametrize('fault', ['gold', 'workers', 'method', 'repetition', 'clients', 'canonical_identity', 'ownership'])
def test_input_errors_stop_before_timed_planning(frozen, tmp_path, monkeypatch, fault):
    _mock_clients(monkeypatch); spec = _spec(frozen)
    if fault == 'gold': spec['gold'] = [{'total':99}]
    elif fault == 'workers': spec['workers'] = 3
    elif fault == 'method': spec['method'] = 'TS'
    elif fault == 'repetition': spec['repetition'] = 3
    elif fault == 'clients': spec['client_specs'].pop(next(iter(spec['client_specs'])))
    else:
        material = deepcopy(frozen[0])
        if fault == 'canonical_identity': material['logical_facts_sha256'] = 'wrong'
        else: material['sources'][1]['atoms'] = [0]
        spec['materialization'] = write_once(tmp_path/'bad-materialization.json', material)
    input_pin = write_once(tmp_path/'input.json', spec)
    monkeypatch.setattr(worker, 'plan_case', lambda *args, **kwargs:pytest.fail('Invalid input reached planning'))
    output = tmp_path/'worker'
    assert worker.worker(input_pin['path'], output) == 2
    receipt = json.loads((output/'receipt.json').read_text())
    assert receipt['status'] == 'startup_failed' and receipt['final_plan_executions'] == 0
    assert receipt['request_latency_s'] is None and not (output/'request-start.json').exists()


def _fake_plan(output, called, workers, method='XGAP'):
    def plan(*args, **kwargs):
        called.append('plan')
        assert kwargs['workers'] == workers and kwargs['method'] == method and set(kwargs['bank_to_source']) == set(range(32))
        assert kwargs['probes'] is True and set(kwargs['backend_clients']) == set(kwargs['bank_to_source'].values())
        assert (output/'request-start.json').exists() and not (output/'request-end.json').exists()
        return SimpleNamespace(to_dict=lambda:dict(plan_id='fake-plan')), dict(
            selected_dag_sha256='same-dag', plan_identity='fake-plan', selected_remote_nodes=32,
            execution_plan_sha256='execution-pin',execution_plan_fingerprint_schema='schema',plan_audit_sha256='audit-pin',
            model_calls=0, backend_calls=0, probe_calls=0)
    return plan


def test_fresh_planning_and_execution_markers_bound_each_request(frozen, tmp_path, monkeypatch):
    _mock_clients(monkeypatch); called = []
    for index, (workers, method) in enumerate(((1, 'XGAP'), (16, 'NP'), (4, 'SH'), (4, 'GR'))):
        spec = _spec(frozen); spec.update(workers=workers, method=method)
        input_pin = write_once(tmp_path/f'input-{index}.json', spec); output = tmp_path/f'worker-{index}'
        monkeypatch.setattr(worker, 'plan_case', _fake_plan(output, called, workers, method))
        def execute(plan, tool, *, parallelism):
            called.append('execute')
            assert parallelism == workers and (output/'planning-checkpoint.json').exists()
            assert (output/'execution-start.json').exists() and not (output/'request-end.json').exists()
            run = SimpleNamespace(success=True, final_rows=({'total':3},), elapsed_ms=12,
                total_remote_calls=2, total_bytes_moved=100, node_results=[])
            return run, dict(events=[dict(backend_id='neo4j-00')], observed_peak_inflight=1)
        monkeypatch.setattr(worker, 'execute', execute)
        assert worker.worker(input_pin['path'], output) == 0
        result = json.loads((output/'receipt.json').read_text())
        start = worker.load(result['request_start']); end = worker.load(result['request_end'])
        assert start['monotonic'] <= end['monotonic'] and result['request_latency_s'] == end['monotonic']-start['monotonic']
        assert result['answer'] == [{'total':3}] and result['planning_cpu_ms'] >= 0
        assert result['execution_ms'] == 12 and result['runtime_backend_calls'] == 2
        assert result['source_ids_touched'] == ['neo4j-00'] and result['workers'] == workers
        assert result['method'] == start['method'] == end['method'] == method
        assert result['endpoints_actual'] == 32 and result['selected_dag_sha256'] == 'same-dag'
        assert result['final_plan_executions'] == 1 and result['model_calls'] == 0
        assert worker.load(result['plan']) == {'plan_id':'fake-plan'}
    assert called == ['plan', 'execute']*4


@pytest.mark.parametrize('phase', ['planning', 'execution'])
def test_request_errors_keep_end_marker_and_completed_phase_metrics(frozen, tmp_path, monkeypatch, phase):
    _mock_clients(monkeypatch); spec = _spec(frozen); output = tmp_path/'worker'
    input_pin = write_once(tmp_path/'input.json', spec)
    monkeypatch.setattr(worker, 'plan_case', _fake_plan(output, [], 4))
    class Failure(RuntimeError): pass
    def fail(*args, **kwargs):
        error = Failure('fixture failure'); error.planning_evidence = dict(partial=True)
        raise error
    if phase == 'planning': monkeypatch.setattr(worker, 'plan_case', fail)
    else: monkeypatch.setattr(worker, 'execute', fail)
    assert worker.worker(input_pin['path'], output) == 2
    result = json.loads((output/'receipt.json').read_text())
    assert result['status'] == 'worker_failure' and result['failure_phase'] == phase
    assert result['planning_cpu_ms'] >= 0 and result['runtime_backend_calls'] is None
    assert result['final_plan_executions'] == (1 if phase == 'execution' else 0)
    assert (output/'request-end.json').exists() and result['request_latency_s'] >= 0


def test_external_interruption_keeps_planning_checkpoint_without_inventing_completion(frozen, tmp_path, monkeypatch):
    _mock_clients(monkeypatch); output = tmp_path/'worker'
    input_pin = write_once(tmp_path/'input.json', _spec(frozen))
    monkeypatch.setattr(worker, 'plan_case', _fake_plan(output, [], 4))
    def interrupted(*args, **kwargs): raise KeyboardInterrupt()
    monkeypatch.setattr(worker, 'execute', interrupted)
    with pytest.raises(KeyboardInterrupt): worker.worker(input_pin['path'], output)
    checkpoint = json.loads((output/'planning-checkpoint.json').read_text())
    assert checkpoint['execution_plan_sha256']=='execution-pin'
    assert checkpoint['execution_plan_fingerprint_schema']=='schema'
    assert checkpoint['plan_audit_sha256']=='audit-pin'
    assert checkpoint['planning_cpu_ms'] >= 0 and checkpoint['final_plan_executions'] == 0
    assert (output/'execution-start.json').exists() and not (output/'request-end.json').exists()
    assert not (output/'receipt.json').exists()
