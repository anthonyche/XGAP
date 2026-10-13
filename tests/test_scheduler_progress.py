"""Local synchronization tests: no databases, network, or timing benchmarks."""
from threading import Event, Lock

import pytest

from xgap.runtime.contracts import (FederatedExecutionPlan, RuntimeNode,
    RuntimeNodeKind as K, RuntimeNodeResult, RuntimeNodeStatus as S)
from xgap.runtime.scheduler import FederatedScheduler


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
