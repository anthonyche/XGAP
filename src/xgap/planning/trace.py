"""JSONL persistence for deterministic M11 search traces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from xgap.planning.contracts import JsonMap, PlanningTraceEvent, canonical_json


def write_search_trace(
    path: str | Path,
    events: Iterable[PlanningTraceEvent],
    *,
    append: bool = False,
) -> Path:
    trace_path = Path(path)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with trace_path.open(mode, encoding="utf-8") as handle:
        for event in events:
            handle.write(canonical_json(event.to_dict()) + "\n")
    return trace_path


def read_search_trace(path: str | Path) -> tuple[JsonMap, ...]:
    trace_path = Path(path)
    if not trace_path.exists():
        return ()
    records: list[JsonMap] = []
    for line_number, line in enumerate(trace_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"Trace line {line_number} must be a JSON object.")
        records.append(value)
    return tuple(records)
