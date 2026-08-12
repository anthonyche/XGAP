"""Deterministic feature extraction from represented physical state."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Mapping

from xgap.planning.contracts import FeatureVector, PhysicalState


M11_OPERATOR_NAMES = (
    "AntiSemiJoin",
    "BindEdge",
    "BindNode",
    "BindingJoin",
    "BindingProject",
    "Edges",
    "FocusProjection",
    "GroupBy",
    "Join",
    "Nodes",
    "OrderBy",
    "Projection",
    "QuantifiedCheck",
    "Recursive",
    "Selection",
    "Union",
)


@dataclass(frozen=True)
class DeterministicStateFeatureExtractor:
    backend_ids: tuple[str, ...]
    optional_stat_names: tuple[str, ...] = ()
    optional_statistics: Mapping[str, float] = field(default_factory=dict)
    schema_version: str = "m11-state-features-v1"
    extractor_id: str = "deterministic-m11-state-features"

    def __post_init__(self) -> None:
        backend_ids = tuple(sorted(set(self.backend_ids)))
        stat_names = tuple(sorted(set(self.optional_stat_names)))
        unknown = set(self.optional_statistics) - set(stat_names)
        if unknown:
            raise ValueError(
                "Optional statistics contain undeclared names: " + ", ".join(sorted(unknown))
            )
        stats: dict[str, float] = {}
        for name, value in self.optional_statistics.items():
            if isinstance(value, bool):
                raise ValueError(f"Optional statistic '{name}' must be numeric.")
            stats[name] = float(value)
        object.__setattr__(self, "backend_ids", backend_ids)
        object.__setattr__(self, "optional_stat_names", stat_names)
        object.__setattr__(self, "optional_statistics", stats)

    @property
    def feature_names(self) -> tuple[str, ...]:
        names = [
            "state.operator_count",
            "state.dependency_count",
            "state.assigned_operator_count",
            "state.unassigned_operator_count",
            "state.exchange_count",
            "state.resolved_dependency_count",
            "state.unresolved_dependency_count",
            "state.selected_backend_count",
            "state.complete",
        ]
        names.extend(f"operator.{name}.count" for name in M11_OPERATOR_NAMES)
        names.extend(f"placement.{backend_id}.count" for backend_id in self.backend_ids)
        for name in self.optional_stat_names:
            names.extend((f"stat.{name}.value", f"stat.{name}.present"))
        return tuple(names)

    @property
    def schema_hash(self) -> str:
        payload = "\n".join((self.schema_version, *self.feature_names))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]

    def features(self, state: PhysicalState) -> FeatureVector:
        operator_counts = {
            name: sum(item.operator_name == name for item in state.operators)
            for name in M11_OPERATOR_NAMES
        }
        placement_counts = {
            backend_id: sum(item.backend_id == backend_id for item in state.placements)
            for backend_id in self.backend_ids
        }
        values: list[float] = [
            float(len(state.operators)),
            float(len(state.dependencies)),
            float(len(state.assigned_operator_ids)),
            float(len(state.unassigned_operator_ids)),
            float(len(state.exchanges)),
            float(len(state.resolved_dependency_ids)),
            float(len(state.unresolved_dependency_ids)),
            float(len(state.selected_backend_ids)),
            float(state.is_complete),
        ]
        missing: list[bool] = [False] * len(values)
        for name in M11_OPERATOR_NAMES:
            values.append(float(operator_counts[name]))
            missing.append(False)
        for backend_id in self.backend_ids:
            values.append(float(placement_counts[backend_id]))
            missing.append(False)
        for name in self.optional_stat_names:
            present = name in self.optional_statistics
            values.extend((float(self.optional_statistics.get(name, 0.0)), float(present)))
            missing.extend((not present, False))
        return FeatureVector(
            schema_version=self.schema_version,
            schema_hash=self.schema_hash,
            names=self.feature_names,
            values=tuple(values),
            missing=tuple(missing),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "extractor_id": self.extractor_id,
            "schema_version": self.schema_version,
            "schema_hash": self.schema_hash,
            "feature_names": list(self.feature_names),
            "backend_ids": list(self.backend_ids),
            "optional_stat_names": list(self.optional_stat_names),
            "optional_statistics": dict(self.optional_statistics),
        }
