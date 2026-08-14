"""Load and verify persisted M12-C backend-local calibration artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from xgap.experiments.calibration_contracts import CalibratedGPModelArtifact, D0Record
from xgap.experiments.cost_calibration import BackendCostModelRegistry
from xgap.planning.protocols import StateFeatureExtractor


def load_calibrated_registry(
    calibration_root: str | Path,
    *,
    backend_ids: tuple[str, ...],
    feature_extractor: StateFeatureExtractor,
) -> tuple[BackendCostModelRegistry, dict[str, tuple[D0Record, ...]]]:
    root = Path(calibration_root)
    artifacts: dict[str, CalibratedGPModelArtifact] = {}
    d0_records: dict[str, tuple[D0Record, ...]] = {}
    for backend_id in sorted(backend_ids):
        model_data = _load_json(root / "cost_models" / backend_id / "model.json")
        artifacts[backend_id] = CalibratedGPModelArtifact.from_dict(model_data)
        d0_records[backend_id] = tuple(
            D0Record.from_dict(item)
            for item in _load_jsonl(root / "calibration" / backend_id / "D0.jsonl")
        )
    registry = BackendCostModelRegistry.from_calibration(
        model_artifacts=artifacts,
        d0_records=d0_records,
        feature_extractors={backend_id: feature_extractor for backend_id in backend_ids},
    )
    return registry, d0_records


def _load_json(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"{path} must contain a JSON object.")
    return dict(data)


def _load_jsonl(path: Path) -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        data = json.loads(line)
        if not isinstance(data, Mapping):
            raise ValueError(f"{path}:{line_number} must contain a JSON object.")
        records.append(dict(data))
    if not records:
        raise ValueError(f"Calibration D0 artifact is empty: {path}")
    return tuple(records)
