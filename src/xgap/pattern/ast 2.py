"""Path-pattern query placeholder types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PathPatternQuery:
    """Shape for future candidate path-pattern queries."""

    text: str
