from __future__ import annotations

import io
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from xgap.backends.fuseki_client import FusekiClient
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import QueryArtifact


REPO_ROOT = Path(__file__).resolve().parents[1]


def _client() -> FusekiClient:
    return FusekiClient(
        BackendDescriptor.from_yaml(
            REPO_ROOT / "descriptors" / "backends" / "fuseki.yaml"
        )
    )


def test_fuseki_http_error_preserves_server_timeout_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"Query timed out after 60000 milliseconds"

    def reject(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "http://127.0.0.1:3030/xgap/sparql",
            500,
            "Server Error",
            {},
            io.BytesIO(body),
        )

    monkeypatch.setattr(urllib.request, "urlopen", reject)
    report = _client().execute(
        QueryArtifact(
            artifact_id="slow-query",
            language="sparql",
            text="SELECT * WHERE { ?s ?p ?o }",
        )
    )

    assert report.success is False
    assert report.error == "Fuseki HTTP 500: Query timed out after 60000 milliseconds"


def test_fuseki_http_error_bounds_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"x" * (64 * 1024 + 100)

    def reject(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "http://127.0.0.1:3030/xgap/sparql",
            500,
            "Server Error",
            {},
            io.BytesIO(body),
        )

    monkeypatch.setattr(urllib.request, "urlopen", reject)
    report = _client().execute(
        QueryArtifact(
            artifact_id="slow-query",
            language="sparql",
            text="SELECT * WHERE { ?s ?p ?o }",
        )
    )

    assert report.success is False
    assert report.error is not None
    assert report.error.startswith("Fuseki HTTP 500: ")
    assert report.error.endswith("[response truncated]")
    assert len(report.error) < 8300
