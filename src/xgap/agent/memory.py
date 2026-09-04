"""Typed, provenance-bearing memory for the XGAP agent."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Protocol


class MemoryScope(str, Enum):
    SESSION = "session"
    SCHEMA = "schema"
    EXECUTION = "execution"
    CACHE = "cache"


@dataclass(frozen=True)
class MemoryRecord:
    scope: MemoryScope
    key: str
    value: Any
    source: str
    version: str
    confidence: float = 1.0
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None

    def __post_init__(self) -> None:
        if not self.key.strip() or not self.source.strip() or not self.version.strip():
            raise ValueError("memory key, source, and version must be nonempty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("memory confidence must be in [0, 1]")
        if self.expires_at is not None and self.expires_at < self.created_at:
            raise ValueError("memory expiry cannot precede creation")

    def is_expired(self, now: float) -> bool:
        return self.expires_at is not None and now >= self.expires_at


class MemoryStore(Protocol):
    def put(self, record: MemoryRecord) -> None:
        """Store or explicitly replace one versioned record."""

    def get(self, scope: MemoryScope, key: str) -> MemoryRecord | None:
        """Return a live record, never an expired one."""

    def records(self, scope: MemoryScope | None = None) -> tuple[MemoryRecord, ...]:
        """Return live records in deterministic order."""


class InMemoryStore:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._records: dict[tuple[MemoryScope, str], MemoryRecord] = {}

    def put(self, record: MemoryRecord) -> None:
        self._records[(record.scope, record.key)] = record

    def get(self, scope: MemoryScope, key: str) -> MemoryRecord | None:
        record = self._records.get((scope, key))
        if record is None:
            return None
        if record.is_expired(self._clock()):
            del self._records[(scope, key)]
            return None
        return record

    def records(self, scope: MemoryScope | None = None) -> tuple[MemoryRecord, ...]:
        live: list[MemoryRecord] = []
        for record_scope, key in sorted(
            self._records,
            key=lambda item: (item[0].value, item[1]),
        ):
            record = self.get(record_scope, key)
            if record is not None and (scope is None or record.scope is scope):
                live.append(record)
        return tuple(live)
