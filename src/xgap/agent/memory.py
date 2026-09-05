"""Typed, provenance-bearing memory for the XGAP agent."""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
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
        if not isinstance(self.scope, MemoryScope):
            raise ValueError("memory scope must be a MemoryScope")
        if any(
            not isinstance(value, str)
            for value in (self.key, self.source, self.version)
        ):
            raise ValueError("memory key, source, and version must be strings")
        if not self.key.strip() or not self.source.strip() or not self.version.strip():
            raise ValueError("memory key, source, and version must be nonempty")
        if not isinstance(self.confidence, (int, float)) or isinstance(
            self.confidence,
            bool,
        ):
            raise ValueError("memory confidence must be numeric")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("memory confidence must be in [0, 1]")
        if not isinstance(self.created_at, (int, float)) or isinstance(
            self.created_at,
            bool,
        ):
            raise ValueError("memory creation time must be numeric")
        if not math.isfinite(self.created_at):
            raise ValueError("memory creation time must be finite")
        if self.expires_at is not None:
            if not isinstance(self.expires_at, (int, float)) or isinstance(
                self.expires_at,
                bool,
            ):
                raise ValueError("memory expiry must be numeric")
            if not math.isfinite(self.expires_at):
                raise ValueError("memory expiry must be finite")
        if self.expires_at is not None and self.expires_at < self.created_at:
            raise ValueError("memory expiry cannot precede creation")

    def is_expired(self, now: float) -> bool:
        return self.expires_at is not None and now >= self.expires_at

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MemoryRecord":
        try:
            scope = MemoryScope(data["scope"])
            key = data["key"]
            source = data["source"]
            version = data["version"]
            confidence = data.get("confidence", 1.0)
            created_at = data["created_at"]
            raw_expiry = data.get("expires_at")
            expires_at = None if raw_expiry is None else raw_expiry
            value = data["value"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid memory record: {exc}") from exc
        return cls(
            scope=scope,
            key=key,
            value=value,
            source=source,
            version=version,
            confidence=confidence,
            created_at=created_at,
            expires_at=expires_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope.value,
            "key": self.key,
            "value": self.value,
            "source": self.source,
            "version": self.version,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


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


class JsonlMemoryStore:
    """Single-writer persistent memory with an append-only JSONL history."""

    def __init__(
        self,
        path: str | Path,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path)
        self._live = InMemoryStore(clock)
        self._history: list[MemoryRecord] = []
        if self.path.is_symlink():
            raise ValueError("JSONL memory path must be a regular file")
        if self.path.exists():
            if not self.path.is_file():
                raise ValueError("JSONL memory path must be a regular file")
            for line_number, raw_line in enumerate(
                self.path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                if not raw_line.strip():
                    raise ValueError(
                        f"JSONL memory contains an empty line at {line_number}"
                    )
                try:
                    payload = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"invalid JSONL memory line {line_number}: {exc}"
                    ) from exc
                if not isinstance(payload, Mapping):
                    raise ValueError(
                        f"JSONL memory line {line_number} must be an object"
                    )
                record = MemoryRecord.from_dict(payload)
                self._history.append(record)
                self._live.put(record)

    def put(self, record: MemoryRecord) -> None:
        try:
            encoded = json.dumps(
                record.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"memory record is not JSON serializable: {exc}") from exc
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._history.append(record)
        self._live.put(record)

    def get(self, scope: MemoryScope, key: str) -> MemoryRecord | None:
        return self._live.get(scope, key)

    def records(self, scope: MemoryScope | None = None) -> tuple[MemoryRecord, ...]:
        return self._live.records(scope)

    def history(self, scope: MemoryScope | None = None) -> tuple[MemoryRecord, ...]:
        return tuple(
            record
            for record in self._history
            if scope is None or record.scope is scope
        )
