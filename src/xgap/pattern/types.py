"""GPC-Lite pattern variable types."""

from __future__ import annotations

from enum import Enum, auto


class PatternVarType(Enum):
    NODE = auto()
    EDGE = auto()
    PATH = auto()
    GROUP = auto()
    MAYBE = auto()
