"""Offline actual-resource scoring, never a planner-estimate feedback path."""
import math

RESOURCES=('clarification_calls','disclosed_fields','probe_calls','metadata_calls','execution_backend_calls',
           'backend_http_attempts','transferred_bytes','planner_cpu_ms','execution_cpu_ms')


def trace_cost(actual,weights):
    if set(weights)-set(RESOURCES):raise ValueError('Unknown actual resource weight')
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in weights.values()):
        raise ValueError('Common weights must be finite nonnegative')
    missing=[k for k,w in weights.items() if w>0 and actual.get(k) is None]
    for k in weights:
        v=actual.get(k)
        if v is not None and (type(v) not in (int,float) or not math.isfinite(v) or v<0):raise ValueError('Invalid measured resource')
    return dict(trace_cost=None if missing else sum(w*actual[k] for k,w in weights.items() if w>0),
                missing_resources=missing,weights=weights,unit='actual_resource_work_units',
                includes_initialization=False,uses_execution_estimate=False)
