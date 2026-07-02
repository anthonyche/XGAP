"""Backend smoke harness for native Cypher and SPARQL artifacts."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.backends.protocol import BackendClient
from xgap.backends.registry import get, load_descriptors
from xgap.experiments.results import normalize_smoke_rows
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import DatasetSpec, QueryArtifact, RunRecord


def _now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_repo_path(path: str, repo_root: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return repo_root / candidate


def _load_services_env(repo_root: Path) -> None:
    env_path = repo_root / "services" / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _client_for_descriptor(descriptor: BackendDescriptor) -> BackendClient:
    engine = descriptor.engine.lower()
    if engine == "neo4j":
        return Neo4jClient(descriptor)
    if engine == "fuseki":
        return FusekiClient(descriptor)
    raise NotImplementedError(
        f"No live backend client is implemented for descriptor '{descriptor.id}'"
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_backend_smoke(
    *,
    backend_id: str,
    dataset_spec_path: str | Path,
    descriptors_dir: str | Path = "descriptors/backends",
    runs_dir: str | Path = "runs",
    run_id: str | None = None,
    client: BackendClient | None = None,
) -> RunRecord:
    """Execute one native smoke query and write normalized run artifacts."""

    repo_root = _repo_root()
    _load_services_env(repo_root)
    descriptor_path = _resolve_repo_path(str(descriptors_dir), repo_root)
    dataset_path = _resolve_repo_path(str(dataset_spec_path), repo_root)
    run_id = run_id or f"backend-smoke-{backend_id}-{_now_slug()}"

    load_descriptors(descriptor_path)
    descriptor = get(backend_id)
    dataset = DatasetSpec.from_yaml(dataset_path)
    backend_config = dataset.backend_config(backend_id)
    smoke_query_file = backend_config.get("smoke_query_file")
    if not isinstance(smoke_query_file, str):
        raise ValueError(f"Dataset '{dataset.id}' has no smoke query file for '{backend_id}'")
    query_path = _resolve_repo_path(smoke_query_file, repo_root)
    query_text = query_path.read_text(encoding="utf-8")

    artifact = QueryArtifact(
        artifact_id=f"{dataset.id}-{backend_id}-smoke",
        language=descriptor.language,
        text=query_text,
        kind="native",
        source_path=str(query_path),
    )
    backend_client = client or _client_for_descriptor(descriptor)
    report = backend_client.execute(artifact)
    normalized_rows = normalize_smoke_rows(report.rows)

    run_root = _resolve_repo_path(str(runs_dir), repo_root) / run_id
    log_path = run_root / "query_logs.jsonl"
    result_path = run_root / "results" / f"{backend_id}_{dataset.id}_smoke_results.json"
    _write_json(result_path, normalized_rows)

    record = RunRecord(
        run_id=run_id,
        backend_id=backend_id,
        dataset_id=dataset.id,
        query_artifact=artifact,
        execution=report,
        normalized_result_path=str(result_path),
        log_path=str(log_path),
        metadata={
            "descriptor_id": descriptor.id,
            "engine": descriptor.engine,
            "dataset_spec": str(dataset_path),
        },
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(record.to_json() + "\n")
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an XGAP backend smoke query")
    parser.add_argument("--backend", required=True, choices=["neo4j", "fuseki"])
    parser.add_argument(
        "--dataset",
        default="examples/datasets/financial_risk_toy.yaml",
        help="Dataset spec YAML path",
    )
    parser.add_argument(
        "--descriptors",
        default="descriptors/backends",
        help="Backend descriptor directory",
    )
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)

    record = run_backend_smoke(
        backend_id=args.backend,
        dataset_spec_path=args.dataset,
        descriptors_dir=args.descriptors,
        runs_dir=args.runs_dir,
        run_id=args.run_id,
    )
    if not record.execution.success:
        print(record.execution.error or "Backend smoke query failed")
        return 1
    if not record.execution.rows:
        print("Backend smoke query returned no rows")
        return 1
    print(f"Wrote query log: {record.log_path}")
    print(f"Wrote normalized results: {record.normalized_result_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
