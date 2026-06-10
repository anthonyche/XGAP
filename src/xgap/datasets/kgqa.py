"""KGQA dataset interface."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_kgqa_dataset(path: str | Path) -> list[dict[str, Any]]:
    raise NotImplementedError("KGQA dataset loading is planned for M8 and is not implemented yet.")
