"""Local synchronization tests: no databases, network, or timing benchmarks."""
from threading import Event, Lock

import pytest

from xgap.runtime.contracts import (FederatedExecutionPlan, RuntimeNode,
    RuntimeNodeKind as K, RuntimeNodeResult, RuntimeNodeStatus as S)
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.execution_limits import ExecutionLimits


def remote(name, inputs=()):
    return RuntimeNode(name, K.REMOTE_BIND_QUERY if inputs else K.REMOTE_QUERY, inputs=inputs,
        parameters={'backend_id': 'fake', 'artifact': {
            'artifact_id': name, 'language': 'sparql', 'text': 'SELECT * WHERE {}'}})


@pytest.mark.parametrize('retention', ['all', 'roots'])
def test_fast_branch_advances_while_unrelated_source_is_blocked(retention):
    child_finished = Event()
    nodes = (remote('a-slow'), remote('b-fast'),
             RuntimeNode('c-local', K.EXCHANGE, inputs=('b-fast',)),
             remote('d-child', ('c-local',)))
    plan = FederatedExecutionPlan('progress', nodes, roots=('a-slow', 'd-child'),
                                 max_remote_calls=3, max_parallelism=2)

    class Scheduler(FederatedScheduler):
        def _execute_remote(self, node, goal_id, results):
            if node.node_id == 'a-slow':
                assert child_finished.wait(2), 'Unrelated slow source blocked a ready descendant'
            if node.node_id == 'd-child':
                assert results['c-local'].rows == ({'id': 'b-fast'},)
                child_finished.set()
            return RuntimeNodeResult(node.node_id, node.kind, S.SUCCESS,
                                     rows=({'id': node.node_id},))

    result = Scheduler(None, retention=retention).execute(plan)
    assert result.success and child_finished.is_set()
    assert [r.node_id for r in result.node_results] == [n.node_id for n in nodes]
    if retention == 'roots':
        assert next(r for r in result.node_results if r.node_id == 'b-fast').rows is None


def test_remote_concurrency_is_bounded_and_inputs_survive_other_consumers():
    lock = Lock()
    active = peak = 0
    first_wave = Event()
    nodes = (remote('seed'), *(remote('consumer-'+str(i), ('seed',)) for i in range(6)))
    plan = FederatedExecutionPlan('bounded', nodes, roots=tuple(n.node_id for n in nodes[1:]),
                                 max_remote_calls=7, max_parallelism=2)

    class Scheduler(FederatedScheduler):
        def _execute_remote(self, node, goal_id, results):
            nonlocal active, peak
            if node.inputs:
                with lock:
                    active += 1
                    peak = max(peak, active)
                    if active == 2: first_wave.set()
                assert first_wave.wait(2)
                assert results['seed'].rows == ({'id': 'seed'},)
                with lock: active -= 1
            return RuntimeNodeResult(node.node_id, node.kind, S.SUCCESS,
                                     rows=({'id': node.node_id},))

    result = Scheduler(None, retention='roots').execute(plan)
    assert result.success and peak == 2
    assert result.node_results[0].rows is None


def test_per_backend_cap_does_not_block_other_sources():
    from dataclasses import replace
    other_finished = Event()
    nodes = (remote('a1'), remote('a2'), replace(remote('b1'),
        parameters={**remote('b1').parameters, 'backend_id': 'other'}))
    plan = FederatedExecutionPlan('sources', nodes, roots=tuple(n.node_id for n in nodes),
                                 max_remote_calls=3, max_parallelism=2)
    order = []
    class Scheduler(FederatedScheduler):
        def _execute_remote(self, node, goal_id, results):
            order.append(node.node_id)
            if node.node_id == 'a1':assert other_finished.wait(2)
            if node.node_id == 'b1':other_finished.set()
            return RuntimeNodeResult(node.node_id, node.kind, S.SUCCESS, rows=({'x': 1},), remote_calls=1)
    result = Scheduler(None, limits=ExecutionLimits(per_backend_parallelism=1)).execute(plan)
    assert result.success and order.index('b1') < order.index('a2')
    assert result.total_remote_calls == 3


def test_dispatch_deadline_keeps_actual_calls_and_does_not_launch_next_node(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr('xgap.runtime.scheduler.time.perf_counter', lambda: clock[0])
    nodes = (remote('a'), remote('b', ('a',)))
    plan = FederatedExecutionPlan('deadline', nodes, roots=('b',), max_remote_calls=2)
    calls = []
    class Scheduler(FederatedScheduler):
        def _execute_remote(self, node, goal_id, results):
            calls.append(node.node_id)
            clock[0] = 2.0
            return RuntimeNodeResult(node.node_id, node.kind, S.SUCCESS, rows=({'x': 1},), remote_calls=1)
    result = Scheduler(None, limits=ExecutionLimits(dispatch_timeout_s=1)).execute(plan)
    assert not result.success and calls == ['a'] and result.total_remote_calls == 1
    assert result.retention['execution_stop_reason'] == 'dispatch_timeout'
    assert result.node_results[0].metadata['discarded_row_count'] == 1
    assert result.node_results[1].status is S.SKIPPED


def test_zero_dispatch_budget_does_not_call_backend():
    node = remote('a')
    result = FederatedScheduler(None, limits=ExecutionLimits(dispatch_timeout_s=0)).execute(
        FederatedExecutionPlan('zero', (node,), roots=('a',), max_remote_calls=1))
    assert not result.success and result.total_remote_calls == 0


def test_payload_admission_counts_actual_rows_not_claimed_size():
    nodes = (remote('a'), remote('b', ('a',)))
    plan = FederatedExecutionPlan('bytes', nodes, roots=('b',), max_remote_calls=2)
    calls = []
    class Scheduler(FederatedScheduler):
        def _execute_remote(self, node, goal_id, results):
            calls.append(node.node_id)
            return RuntimeNodeResult(node.node_id, node.kind, S.SUCCESS,
                rows=({'x': 'z'*100},), output_bytes=0, remote_calls=1)
    result = Scheduler(None, limits=ExecutionLimits(max_registered_bytes=32), retention='roots').execute(plan)
    assert not result.success and calls == ['a'] and result.total_remote_calls == 1
    assert result.retention['execution_stop_reason'] == 'registered_payload_budget'
    assert result.node_results[0].metadata['observed_output_bytes'] > 32
    assert result.node_results[0].rows is None  # Released after its last skipped consumer.
    assert result.node_results[0].row_count == 0


@pytest.mark.parametrize('options', [dict(dispatch_timeout_s=float('nan')),
    dict(dispatch_timeout_s=-1), dict(max_registered_bytes=0), dict(per_backend_parallelism=True)])
def test_invalid_execution_limits_rejected(options):
    with pytest.raises(ValueError):ExecutionLimits(**options)
