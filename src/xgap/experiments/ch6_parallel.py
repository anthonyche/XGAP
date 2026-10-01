"""Fixed-plan scheduler parallelism: same query artifacts, actual overlapping calls.

This isolates execution concurrency, not planner selection or request throughput.
"""
from dataclasses import replace
import threading
import time

from xgap.runtime.contracts import RuntimeNodeKind
from xgap.runtime.scheduler import FederatedScheduler

LEVELS = (1, 2, 4, 8, 16)
REMOTE = {RuntimeNodeKind.REMOTE_QUERY, RuntimeNodeKind.REMOTE_BIND_QUERY}


def ready_width(plan):
    remaining = {n.node_id: n for n in plan.nodes}
    done = set(); width = 0
    while remaining:
        ready = [n for n in remaining.values() if set(n.inputs) <= done]
        if not ready: raise ValueError('Invalid plan dependency graph')
        width = max(width, sum(n.kind in REMOTE for n in ready))
        for node in ready:
            done.add(node.node_id); remaining.pop(node.node_id)
    return width


def variant(plan, parallelism):
    if type(parallelism) is not int or parallelism not in LEVELS:
        raise ValueError('Declared execution parallelism levels are 1,2,4,8,16')
    # Preserve all artifact/query text, row/remote-call bounds, IDs and dependencies.
    return replace(plan, max_parallelism=parallelism)


class OverlapTool:
    def __init__(self, delegate):
        self.delegate = delegate; self.lock = threading.Lock()
        self.active = 0; self.peak = 0; self.events = []

    def invoke(self, arguments, context):
        started = time.perf_counter_ns()
        with self.lock:
            self.active += 1; self.peak = max(self.peak, self.active)
        try:
            return self.delegate.invoke(arguments, context)
        finally:
            ended = time.perf_counter_ns()
            with self.lock:
                self.events.append(dict(backend_id=arguments.get('backend_id'),
                    operation=arguments.get('operation'), start_ns=started, end_ns=ended))
                self.active -= 1


def execute(plan, backend_tool, *, parallelism):
    instrumented = OverlapTool(backend_tool)
    run = FederatedScheduler(instrumented, retention='roots').execute(variant(plan, parallelism))
    return run, dict(requested_parallelism=parallelism,
        static_ready_layer_width=ready_width(plan), observed_peak_inflight=instrumented.peak,
        calls=len(instrumented.events), events=sorted(instrumented.events, key=lambda e:e['start_ns']),
        scope='actual backend-tool request overlap, not backend-internal threads or concurrent user queries',
        fixed_plan=True, planner_reexecuted=False, model_calls=0)
