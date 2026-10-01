from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from xgap.backends.neo4j_client import Neo4jClient
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import QueryArtifact


REPO_ROOT = Path(__file__).resolve().parents[1]


def _client() -> Neo4jClient:
    return Neo4jClient(
        BackendDescriptor.from_yaml(
            REPO_ROOT / "descriptors" / "backends" / "neo4j.yaml"
        )
    )


def test_neo4j_http_error_preserves_bounded_structured_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = json.dumps(
        {
            "errors": [
                {
                    "code": "Neo.TransientError.Transaction.TransactionTimedOut",
                    "message": "The transaction timed out.",
                }
            ]
        }
    ).encode("utf-8")

    def reject(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "http://127.0.0.1:7474/db/neo4j/tx/commit",
            500,
            "Server Error",
            {},
            io.BytesIO(body),
        )

    monkeypatch.setattr(urllib.request, "urlopen", reject)
    report = _client().execute(
        QueryArtifact(
            artifact_id="load-batch",
            language="cypher",
            text="RETURN 1",
        )
    )

    assert report.success is False
    assert report.error == (
        "Neo4j HTTP 500: "
        "Neo.TransientError.Transaction.TransactionTimedOut: "
        "The transaction timed out."
    )


def test_neo4j_http_error_bounds_non_json_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"x" * (64 * 1024 + 100)

    def reject(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "http://127.0.0.1:7474/db/neo4j/tx/commit",
            500,
            "Server Error",
            {},
            io.BytesIO(body),
        )

    monkeypatch.setattr(urllib.request, "urlopen", reject)
    report = _client().execute(
        QueryArtifact(
            artifact_id="load-batch",
            language="cypher",
            text="RETURN 1",
        )
    )

    assert report.success is False
    assert report.error is not None
    assert report.error.startswith("Neo4j HTTP 500: ")
    assert report.error.endswith("[response truncated]")
    assert len(report.error) < 8300
