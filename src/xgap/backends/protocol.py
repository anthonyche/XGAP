"""Backend client protocol for native query execution."""

from __future__ import annotations

from typing import Protocol

from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact


class BackendClient(Protocol):
    """Minimal protocol for backends that execute native query artifacts."""

    def healthcheck(self) -> BackendStatus:
        """Return the backend's runtime status."""

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        """Execute a native query artifact and return a normalized report."""
