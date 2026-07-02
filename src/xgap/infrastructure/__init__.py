"""Infrastructure data objects for backend experiments."""

from __future__ import annotations

from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import (
    BackendStatus,
    DatasetSpec,
    ExecutionReport,
    QueryArtifact,
    RunRecord,
)

__all__ = [
    "BackendDescriptor",
    "BackendStatus",
    "DatasetSpec",
    "ExecutionReport",
    "QueryArtifact",
    "RunRecord",
]
