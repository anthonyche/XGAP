"""Exact-context observation reuse through the existing agent memory store."""

from dataclasses import dataclass
import hashlib
import json
import math
import time
from typing import Callable

from xgap.agent.memory import MemoryRecord, MemoryScope, MemoryStore
from xgap.runtime.planning import PlanObservationSnapshot


@dataclass(frozen=True)
class SemanticPlanMemory:
    store: MemoryStore
    environment_episode: str
    max_age_seconds: float
    clock: Callable[[], float] = time.time

    def __post_init__(self):
        if not isinstance(self.environment_episode, str) or not self.environment_episode.strip():
            raise ValueError("Planning memory requires an explicit environment episode")
        if (isinstance(self.max_age_seconds, bool) or not isinstance(self.max_age_seconds, (int, float))
                or not math.isfinite(self.max_age_seconds) or self.max_age_seconds <= 0):
            raise ValueError("Planning memory requires a finite positive maximum age")

    def lookup(self, space, *, bandwidth_bytes_per_ms, exchange_fixed_ms, coordinator_row_ms):
        costs = dict(bandwidth_bytes_per_ms=bandwidth_bytes_per_ms,
                     exchange_fixed_ms=exchange_fixed_ms, coordinator_row_ms=coordinator_row_ms)
        validated = PlanObservationSnapshot("context", "v1", (), **costs)
        costs = {name: float(getattr(validated, name)) for name in costs}
        if not space.candidates or len({c.semantic_equivalence_key for c in space.candidates}) != 1:
            raise ValueError("Planning memory requires one nonempty semantic equivalence class")
        context = {"schema": "semantic-observation-memory-v1", "episode": self.environment_episode,
            "meaning": space.candidates[0].semantic_equivalence_key,
            "requests": [r.to_dict() for r in space.observation_requests], "cost_model": costs}
        if hasattr(space, "memory_context"):
            context["local_placement_problem"] = space.memory_context()
        else:
            context["plans"] = [c.plan.to_dict() for c in sorted(space.candidates, key=lambda c: c.plan.plan_id)]
        digest = hashlib.sha256(json.dumps(context, sort_keys=True, separators=(",", ":"),
                                          allow_nan=False).encode()).hexdigest()
        key = "semantic-observation/" + digest
        detail = {"state": "miss", "key": key, "reads": 1, "writes": 0,
                  "historical_acquisition": None, "snapshot": None}
        entry = self.store.get(MemoryScope.EXECUTION, key)
        if entry is None:
            return None, detail
        age = self.clock() - entry.created_at
        if not math.isfinite(age) or age < 0:
            raise ValueError("Planning memory timestamp is invalid for this environment")
        if age >= self.max_age_seconds or entry.is_expired(self.clock()):
            return None, {**detail, "state": "expired"}
        value = entry.value
        if not isinstance(value, dict) or not isinstance(value.get("snapshot"), dict):
            raise ValueError("Planning memory has no recorded snapshot")
        snapshot = PlanObservationSnapshot.from_dict(value["snapshot"])
        expected = {r.observation_key: r.backend_id for r in space.observation_requests}
        if (snapshot.snapshot_id != key or snapshot.version != entry.version
                or {e.observation_key: e.backend_id for e in snapshot.estimates} != expected
                or any(getattr(snapshot, name) != number for name, number in costs.items())):
            raise ValueError("Planning memory snapshot disagrees with its exact context")
        acquisition = value.get("acquisition")
        if (not isinstance(acquisition, dict) or type(acquisition.get("remote_calls")) is not int
                or acquisition["remote_calls"] != len(expected)
                or type(acquisition.get("elapsed_ms")) not in (int, float)
                or not math.isfinite(acquisition["elapsed_ms"]) or acquisition["elapsed_ms"] < 0):
            raise ValueError("Planning memory acquisition accounting is invalid")
        return snapshot, {**detail, "state": "hit", "age_seconds": age,
            "historical_acquisition": dict(acquisition), "snapshot": snapshot.to_dict()}

    def remember(self, key, collection, *, goal_id):
        if not collection.success or collection.snapshot.snapshot_id != key:
            raise ValueError("Only a complete matching observation collection may enter memory")
        now = self.clock()
        snapshot = collection.snapshot
        self.store.put(MemoryRecord(scope=MemoryScope.EXECUTION, key=key,
            value={"snapshot": snapshot.to_dict(), "acquisition": {
                "remote_calls": collection.attempted_calls, "elapsed_ms": collection.elapsed_ms,
                "goal_id": goal_id}}, source="registered semantic planning observations",
            version=snapshot.version, created_at=now, expires_at=now + self.max_age_seconds))
