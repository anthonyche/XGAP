"""Deployment-neutral loader for the M15 split Neo4j/Fuseki fixture."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.backends.protocol import BackendClient
from xgap.experiments.m15_workload import (
    M15WorkloadBundle,
    load_m15_workload_bundle,
)
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import ExecutionReport, QueryArtifact


RUN_SCHEMA_VERSION = "m15-b2a-fixture-load-v1"
FIXTURE_ROOT = Path("examples/m15_split_financial_risk")
NEO4J_LOAD_PATH = FIXTURE_ROOT / "load_neo4j.cypher"
FUSEKI_LOAD_PATH = FIXTURE_ROOT / "load_fuseki.ttl"
NEO4J_QUERY_PATH = FIXTURE_ROOT / "query_recent_transfers.cypher"
FUSEKI_QUERY_PATH = FIXTURE_ROOT / "query_high_risk.rq"
EXPECTED_SOURCE_PATH = FIXTURE_ROOT / "expected_source_results.json"
EXPECTED_RESULT_PATH = FIXTURE_ROOT / "expected_result.json"
DATASET_PATH = Path("examples/datasets/m15_split_financial_risk.yaml")
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class BackendLoadReport:
    backend_id: str
    success: bool
    operations_attempted: int
    bytes_sent: int
    elapsed_ms: float
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_id": self.backend_id,
            "success": self.success,
            "operations_attempted": self.operations_attempted,
            "bytes_sent": self.bytes_sent,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
            "metadata": dict(self.metadata),
        }


class BackendFixtureLoader(Protocol):
    backend_id: str

    def load(self, path: Path) -> BackendLoadReport:
        """Load one namespaced fixture without automatic retry."""


@dataclass(frozen=True)
class M15FixtureLoadRecord:
    run_id: str
    run_root: Path
    success: bool
    status_path: Path
    manifest_path: Path
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_root": str(self.run_root),
            "success": self.success,
            "status_path": str(self.status_path),
            "manifest_path": str(self.manifest_path),
            "error": self.error,
        }


def split_cypher_statements(text: str) -> tuple[str, ...]:
    """Split fixture Cypher on unquoted semicolons."""

    statements: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = 0
    while index < len(text):
        character = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""

        if line_comment:
            buffer.append(character)
            if character == "\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            buffer.append(character)
            if character == "*" and following == "/":
                buffer.append(following)
                block_comment = False
                index += 2
            else:
                index += 1
            continue
        if quote is not None:
            buffer.append(character)
            if escaped:
                escaped = False
            elif character == "\\" and quote != "`":
                escaped = True
            elif character == quote:
                if following == quote:
                    buffer.append(following)
                    index += 2
                    continue
                quote = None
            index += 1
            continue

        if character in {"'", '"', "`"}:
            quote = character
            buffer.append(character)
            index += 1
            continue
        if character == "/" and following == "/":
            line_comment = True
            buffer.extend((character, following))
            index += 2
            continue
        if character == "/" and following == "*":
            block_comment = True
            buffer.extend((character, following))
            index += 2
            continue
        if character == ";":
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer.clear()
            index += 1
            continue
        buffer.append(character)
        index += 1

    if quote is not None or block_comment:
        raise ValueError("unterminated quote or block comment in Cypher fixture")
    statement = "".join(buffer).strip()
    if statement:
        statements.append(statement)
    if not statements:
        raise ValueError("Cypher fixture contains no statements")
    return tuple(statements)


class Neo4jCypherFixtureLoader:
    backend_id = "neo4j"

    def __init__(self, client: BackendClient):
        self._client = client

    def load(self, path: Path) -> BackendLoadReport:
        started = time.perf_counter()
        text = path.read_text(encoding="utf-8")
        statements = split_cypher_statements(text)
        attempted = 0
        for index, statement in enumerate(statements, start=1):
            attempted += 1
            try:
                report = self._client.execute(
                    QueryArtifact(
                        artifact_id=f"m15-load-neo4j-{index:03d}",
                        language="cypher",
                        text=statement,
                        kind="native",
                        source_path=str(path),
                    )
                )
                operation_error = (
                    report.error or f"Neo4j load statement {index} failed"
                    if not report.success
                    else None
                )
            except Exception as exc:  # Preserve an unexpected adapter failure as evidence.
                operation_error = str(exc)
            if operation_error is not None:
                return BackendLoadReport(
                    backend_id=self.backend_id,
                    success=False,
                    operations_attempted=attempted,
                    bytes_sent=sum(len(item.encode("utf-8")) for item in statements[:attempted]),
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    error=operation_error,
                    metadata={
                        "strategy": "sequential_idempotent_cypher",
                        "statement_count": len(statements),
                        "failed_statement_index": index,
                    },
                )
        return BackendLoadReport(
            backend_id=self.backend_id,
            success=True,
            operations_attempted=attempted,
            bytes_sent=len(text.encode("utf-8")),
            elapsed_ms=(time.perf_counter() - started) * 1000,
            metadata={
                "strategy": "sequential_idempotent_cypher",
                "statement_count": len(statements),
            },
        )


class FusekiGraphStoreFixtureLoader:
    backend_id = "fuseki"

    def __init__(self, descriptor: BackendDescriptor):
        runtime = descriptor.runtime
        self.base_url = os.environ.get(
            str(runtime.get("base_url_env", "FUSEKI_URL")),
            str(runtime.get("default_base_url", "http://127.0.0.1:3030")),
        ).rstrip("/")
        self.dataset = os.environ.get(
            str(runtime.get("dataset_env", "FUSEKI_DATASET_NAME")),
            str(runtime.get("default_dataset", "xgap")),
        )
        self.admin_user = os.environ.get("FUSEKI_ADMIN_USER", "admin")
        self.admin_password = os.environ.get(
            "FUSEKI_ADMIN_PASSWORD", "xgap-lab-password"
        )
        self.timeout_seconds = float(runtime.get("timeout_seconds", 30))

    def load(self, path: Path) -> BackendLoadReport:
        started = time.perf_counter()
        payload = path.read_bytes()
        endpoint = f"{self.base_url}/{self.dataset}/data?default"
        auth = base64.b64encode(
            f"{self.admin_user}:{self.admin_password}".encode("utf-8")
        ).decode("ascii")
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "text/turtle",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                status = int(response.status)
            if not 200 <= status < 300:
                raise ValueError(f"Fuseki Graph Store POST returned HTTP {status}")
            return BackendLoadReport(
                backend_id=self.backend_id,
                success=True,
                operations_attempted=1,
                bytes_sent=len(payload),
                elapsed_ms=(time.perf_counter() - started) * 1000,
                metadata={
                    "strategy": "graph_store_post",
                    "dataset": self.dataset,
                    "endpoint": endpoint,
                    "http_status": status,
                },
            )
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            return BackendLoadReport(
                backend_id=self.backend_id,
                success=False,
                operations_attempted=1,
                bytes_sent=len(payload),
                elapsed_ms=(time.perf_counter() - started) * 1000,
                error=str(exc),
                metadata={
                    "strategy": "graph_store_post",
                    "dataset": self.dataset,
                    "endpoint": endpoint,
                },
            )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _repo_path(repo_root: Path, path: Path) -> Path:
    resolved = (repo_root / path).resolve()
    if resolved != repo_root and repo_root not in resolved.parents:
        raise ValueError(f"experiment path escapes repository: {path}")
    return resolved


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_state(repo_root: Path) -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        return {"commit": commit, "clean": not bool(dirty)}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"commit": None, "clean": None, "error": str(exc)}


def _default_components(
    repo_root: Path,
) -> tuple[dict[str, BackendClient], dict[str, BackendFixtureLoader]]:
    descriptors = repo_root / "descriptors" / "backends"
    neo4j_descriptor = BackendDescriptor.from_yaml(descriptors / "neo4j.yaml")
    fuseki_descriptor = BackendDescriptor.from_yaml(descriptors / "fuseki.yaml")
    clients: dict[str, BackendClient] = {
        "neo4j": Neo4jClient(neo4j_descriptor),
        "fuseki": FusekiClient(fuseki_descriptor),
    }
    loaders: dict[str, BackendFixtureLoader] = {
        "neo4j": Neo4jCypherFixtureLoader(clients["neo4j"]),
        "fuseki": FusekiGraphStoreFixtureLoader(fuseki_descriptor),
    }
    return clients, loaders


def _query_artifact(
    repo_root: Path,
    backend_id: str,
    workload_bundle: M15WorkloadBundle | None = None,
) -> QueryArtifact:
    if workload_bundle is not None:
        filename = (
            "query_recent_transfers.cypher"
            if backend_id == "neo4j"
            else "query_high_risk.rq"
        )
        language = "cypher" if backend_id == "neo4j" else "sparql"
        resolved = workload_bundle.path(filename)
        return QueryArtifact(
            artifact_id=(
                f"m15-f0-{workload_bundle.spec.workload_id}-verify-{backend_id}"
            ),
            language=language,
            text=resolved.read_text(encoding="utf-8"),
            kind="native",
            source_path=f"bundle:{workload_bundle.spec.workload_id}/{filename}",
        )
    path = NEO4J_QUERY_PATH if backend_id == "neo4j" else FUSEKI_QUERY_PATH
    language = "cypher" if backend_id == "neo4j" else "sparql"
    resolved = _repo_path(repo_root, path)
    return QueryArtifact(
        artifact_id=f"m15-verify-{backend_id}",
        language=language,
        text=resolved.read_text(encoding="utf-8"),
        kind="native",
        source_path=str(path),
    )


def _validate_verification(
    reports: Mapping[str, ExecutionReport],
    expected: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    for backend_id in ("neo4j", "fuseki"):
        report = reports[backend_id]
        checks[f"{backend_id}_query_success"] = report.success
        checks[f"{backend_id}_exact_rows"] = report.rows == expected[backend_id]
    return {"passed": all(checks.values()), "checks": checks}


def load_m15_split_fixture(
    *,
    output_root: str | Path = "runs",
    run_id: str | None = None,
    repo_root: str | Path | None = None,
    clients: Mapping[str, BackendClient] | None = None,
    loaders: Mapping[str, BackendFixtureLoader] | None = None,
    workload_bundle: M15WorkloadBundle | str | Path | None = None,
) -> M15FixtureLoadRecord:
    """Load and verify the namespaced M15 fixture exactly once."""

    if (clients is None) != (loaders is None):
        raise ValueError("clients and loaders must be supplied together")
    root = Path(repo_root).resolve() if repo_root is not None else _repo_root()
    selected_bundle = (
        load_m15_workload_bundle(
            workload_bundle.root
            if isinstance(workload_bundle, M15WorkloadBundle)
            else workload_bundle
        )
        if workload_bundle is not None
        else None
    )
    selected_run_id = run_id or f"m15-fixture-load-{_now_slug()}"
    if not _SAFE_RUN_ID.fullmatch(selected_run_id):
        raise ValueError("run_id contains unsupported characters")
    destination = Path(output_root)
    if not destination.is_absolute():
        destination = root / destination
    run_root = destination.resolve() / selected_run_id
    run_root.mkdir(parents=True, exist_ok=False)

    status_path = run_root / "run_status.json"
    manifest_path = run_root / "run_manifest.json"
    started_at = _now()
    _write_json(
        status_path,
        {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": selected_run_id,
            "status": "running",
            "started_at": started_at,
        },
    )

    if selected_bundle is None:
        dataset_id = "m15_split_financial_risk"
        source_paths = (
            DATASET_PATH,
            NEO4J_LOAD_PATH,
            FUSEKI_LOAD_PATH,
            NEO4J_QUERY_PATH,
            FUSEKI_QUERY_PATH,
            EXPECTED_SOURCE_PATH,
            EXPECTED_RESULT_PATH,
        )
        source_hashes = {
            str(path): _sha256_file(_repo_path(root, path)) for path in source_paths
        }
        load_paths = {
            "neo4j": _repo_path(root, NEO4J_LOAD_PATH),
            "fuseki": _repo_path(root, FUSEKI_LOAD_PATH),
        }
        expected_payload: Mapping[str, list[dict[str, Any]]] | None = None
    else:
        dataset_id = f"m15_f0:{selected_bundle.spec.workload_id}"
        source_hashes = {
            f"bundle:{selected_bundle.spec.workload_id}/{name}": digest
            for name, digest in selected_bundle.source_hashes.items()
        }
        source_hashes[
            f"bundle:{selected_bundle.spec.workload_id}/manifest.json"
        ] = _sha256_file(selected_bundle.root / "manifest.json")
        load_paths = {
            "neo4j": selected_bundle.path("load_neo4j.cypher"),
            "fuseki": selected_bundle.path("load_fuseki.ttl"),
        }
        expected_payload = selected_bundle.expected_source_rows
    if clients is None and loaders is None:
        selected_clients, selected_loaders = _default_components(root)
    elif clients is not None and loaders is not None:
        selected_clients = dict(clients)
        selected_loaders = dict(loaders)

    health_before: dict[str, Any] = {}
    health_after: dict[str, Any] = {}
    load_reports: dict[str, Any] = {}
    verification_reports: dict[str, ExecutionReport] = {}
    validation: dict[str, Any] | None = None
    error: str | None = None
    try:
        required = {"neo4j", "fuseki"}
        if set(selected_clients) != required or set(selected_loaders) != required:
            raise ValueError("fixture load requires exactly neo4j and fuseki components")
        for backend_id in ("neo4j", "fuseki"):
            health_before[backend_id] = selected_clients[backend_id].healthcheck().to_dict()
        _write_json(run_root / "health_before.json", health_before)
        unavailable = [key for key, value in health_before.items() if not value["ok"]]
        if unavailable:
            raise RuntimeError(f"backend healthcheck failed: {', '.join(unavailable)}")

        for backend_id in ("neo4j", "fuseki"):
            report = selected_loaders[backend_id].load(load_paths[backend_id])
            load_reports[backend_id] = report.to_dict()
            _write_json(run_root / "load_reports.json", load_reports)
            if not report.success:
                raise RuntimeError(f"{backend_id} fixture load failed: {report.error}")

        for backend_id in ("neo4j", "fuseki"):
            health_after[backend_id] = selected_clients[backend_id].healthcheck().to_dict()
        _write_json(run_root / "health_after.json", health_after)
        unavailable = [key for key, value in health_after.items() if not value["ok"]]
        if unavailable:
            raise RuntimeError(f"post-load healthcheck failed: {', '.join(unavailable)}")

        for backend_id in ("neo4j", "fuseki"):
            verification_reports[backend_id] = selected_clients[backend_id].execute(
                _query_artifact(root, backend_id, selected_bundle)
            )
        expected_raw = (
            json.loads(
                _repo_path(root, EXPECTED_SOURCE_PATH).read_text(encoding="utf-8")
            )
            if expected_payload is None
            else expected_payload
        )
        if not isinstance(expected_raw, dict):
            raise ValueError("expected source results must be a JSON object")
        expected: dict[str, list[dict[str, Any]]] = {}
        for backend_id in ("neo4j", "fuseki"):
            rows = expected_raw.get(backend_id)
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError(f"expected source rows for {backend_id} must be objects")
            expected[backend_id] = [dict(row) for row in rows]
        validation = _validate_verification(verification_reports, expected)
        _write_json(
            run_root / "verification.json",
            {
                "reports": {
                    key: value.to_dict() for key, value in verification_reports.items()
                },
                "validation": validation,
            },
        )
        if not validation["passed"]:
            raise RuntimeError("fixture source verification failed")
    except Exception as exc:  # Persist every failed external attempt as evidence.
        error = str(exc)
        if not (run_root / "health_before.json").exists():
            _write_json(run_root / "health_before.json", health_before)
        if not (run_root / "load_reports.json").exists():
            _write_json(run_root / "load_reports.json", load_reports)
        if health_after and not (run_root / "health_after.json").exists():
            _write_json(run_root / "health_after.json", health_after)

    ended_at = _now()
    success = error is None
    _write_json(
        status_path,
        {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": selected_run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    artifacts = sorted(
        {
            *(path.name for path in run_root.iterdir() if path.is_file()),
            manifest_path.name,
        }
    )
    _write_json(
        manifest_path,
        {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": selected_run_id,
            "dataset_id": dataset_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
            "git": _git_state(root),
            "environment": {
                "hostname": platform.node(),
                "python": sys.version,
                "platform": platform.platform(),
            },
            "input_sha256": source_hashes,
            "workload_bundle": (
                dict(selected_bundle.manifest) if selected_bundle is not None else None
            ),
            "health_before": health_before,
            "health_after": health_after,
            "load_reports": load_reports,
            "validation": validation,
            "mutation_scope": "namespaced_idempotent_append",
            "automatic_retries": 0,
            "credentials_persisted": False,
            "artifacts": artifacts,
        },
    )
    return M15FixtureLoadRecord(
        run_id=selected_run_id,
        run_root=run_root,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        error=error,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default="runs")
    parser.add_argument("--run-id")
    parser.add_argument("--workload-bundle")
    args = parser.parse_args(argv)
    if os.environ.get("XGAP_LOAD_M15_FIXTURE") != "1":
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "error": "set XGAP_LOAD_M15_FIXTURE=1 for dedicated M15 services",
                },
                sort_keys=True,
            )
        )
        return 3
    try:
        record = load_m15_split_fixture(
            output_root=args.output_root,
            run_id=args.run_id,
            workload_bundle=args.workload_bundle,
        )
    except (FileExistsError, ValueError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps(record.to_dict(), indent=2, sort_keys=True))
    return 0 if record.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
