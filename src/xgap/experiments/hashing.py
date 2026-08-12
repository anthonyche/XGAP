"""Deterministic content hashing for experiment-facing artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, Mapping


def json_value(value: object) -> Any:
    if hasattr(value, "to_hash_dict"):
        return json_value(value.to_hash_dict())  # type: ignore[attr-defined]
    if hasattr(value, "to_dict"):
        return json_value(value.to_dict())  # type: ignore[attr-defined]
    if is_dataclass(value):
        return json_value(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple | list):
        return [json_value(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"Value of type {type(value).__name__} is not JSON serializable.")


def canonical_json(value: object) -> str:
    return json.dumps(
        json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
