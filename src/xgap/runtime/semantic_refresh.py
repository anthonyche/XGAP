"""Warm-only one-observation policy; no claim of optimal information value."""

from dataclasses import dataclass

from xgap.runtime.contracts import RuntimeNodeKind
from xgap.tools.backends import BackendOperation


@dataclass(frozen=True)
class SemanticRefreshPolicy:
    mode: str = "refresh_reselect"

    def __post_init__(self):
        if self.mode not in ("refresh_reselect", "refresh_only", "no_refresh"):
            raise ValueError("Unknown semantic refresh mode")

    def to_dict(self):
        return {"mode": self.mode, "scope": "warm_pre_execution",
            "request_rule": "largest historical elapsed estimate in initial plan, then observation key",
            "max_acquisition_calls": 0 if self.mode == "no_refresh" else 1,
            "max_reselections": 1 if self.mode == "refresh_reselect" else 0,
            "memory_write_policy": "read_only", "hard_wall_time_bound": False}

    def choose_request(self, space, initial_plan, snapshot):
        keys = {n.parameters["observation_key"] for n in initial_plan.nodes
                if n.kind is RuntimeNodeKind.REMOTE_QUERY}
        by_key = snapshot.by_key
        requests = {r.observation_key: r for r in space.observation_requests}
        if not keys or not keys <= requests.keys() or not keys <= by_key.keys():
            raise ValueError("Refresh requires registered observations for the initial plan")
        key = min(keys, key=lambda k: (-by_key[k].elapsed_ms, k))
        request = requests[key]
        if request.backend_id != by_key[key].backend_id or request.operation is not BackendOperation.PROFILE:
            raise ValueError("Refresh requires a matching registered profile request")
        return request
