"""Load and verify one F2C parameterized workload on live graph backends."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from xgap.backends.protocol import BackendClient
from xgap.experiments.m15_fixture_loader import BackendFixtureLoader
from xgap.experiments.m15_parameterized_federation import (
    build_m15_parameterized_query_artifacts,
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_parameterized_workload import (
    M15ParameterizedWorkloadBundle,
    load_m15_parameterized_workload_bundle,
)


PARAMETERIZED_FIXTURE_SCHEMA_VERSION = "m15-f2c4-parameterized-fixture-v1"
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class M15ParameterizedFixtureRecord:
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _verification(
    *,
    bundle: M15ParameterizedWorkloadBundle,
    clients: Mapping[str, BackendClient],
) -> tuple[dict[str, Any], dict[str, bool]]:
    reports: dict[str, Any] = {}
    checks: dict[str, bool] = {}
    for query_id in bundle.instance_ids():
        instance = load_m15_parameterized_instance(bundle, query_id)
        artifacts = build_m15_parameterized_query_artifacts(
            bundle,
            query_id=query_id,
        )
        expected = instance["source_oracles"]
        query_reports: dict[str, Any] = {}
        for backend_id, role in (
            ("neo4j", "neo4j_full"),
            ("fuseki", "fuseki_risk"),
        ):
            report = clients[backend_id].execute(artifacts[role])
            query_reports[role] = report.to_dict()
            checks[f"{query_id}:{role}:success"] = report.success
            checks[f"{query_id}:{role}:exact_rows"] = (
                report.rows == expected[role]
            )
        reports[query_id] = query_reports
    return reports, checks


def load_m15_parameterized_fixture(
    *,
    workload_bundle: M15ParameterizedWorkloadBundle | str | Path,
    clients: Mapping[str, BackendClient],
    loaders: Mapping[str, BackendFixtureLoader],
    output_root: str | Path,
    run_id: str = "parameterized-fixture-load",
    repo_root: str | Path | None = None,
    bundle_loader: Callable[[Path], M15ParameterizedWorkloadBundle] | None = None,
) -> M15ParameterizedFixtureRecord:
    """Load once and verify every exact instance without automatic retry."""

    root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else Path(__file__).resolve().parents[3]
    )
    bundle_root = Path(
        workload_bundle.root
        if isinstance(workload_bundle, M15ParameterizedWorkloadBundle)
        else workload_bundle
    ).resolve()
    selected_loader = bundle_loader or load_m15_parameterized_workload_bundle
    bundle = selected_loader(bundle_root)
    if bundle.root.resolve() != bundle_root:
        raise ValueError(
            "bundle loader returned a different parameterized workload root"
        )
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("run_id contains unsupported characters")
    if set(clients) != {"neo4j", "fuseki"} or set(loaders) != {
        "neo4j",
        "fuseki",
    }:
        raise ValueError(
            "parameterized fixture requires exactly neo4j and fuseki components"
        )
    destination = Path(output_root)
    if not destination.is_absolute():
        destination = root / destination
    run_root = destination.resolve() / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    status_path = run_root / "run_status.json"
    manifest_path = run_root / "run_manifest.json"
    started_at = _now()
    _write_json(
        status_path,
        {
            "schema_version": PARAMETERIZED_FIXTURE_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "running",
            "started_at": started_at,
        },
    )

    health_before: dict[str, Any] = {}
    health_after: dict[str, Any] = {}
    load_reports: dict[str, Any] = {}
    verification_reports: dict[str, Any] = {}
    checks: dict[str, bool] = {}
    error: str | None = None
    try:
        for backend_id in ("neo4j", "fuseki"):
            health_before[backend_id] = clients[backend_id].healthcheck().to_dict()
        _write_json(run_root / "health_before.json", health_before)
        unavailable = [
            backend_id
            for backend_id, status in health_before.items()
            if not status["ok"]
        ]
        if unavailable:
            raise RuntimeError(
                f"backend healthcheck failed: {', '.join(unavailable)}"
            )

        load_paths = {
            "neo4j": bundle.path("load_neo4j.cypher"),
            "fuseki": bundle.path("load_fuseki.ttl"),
        }
        for backend_id in ("neo4j", "fuseki"):
            report = loaders[backend_id].load(load_paths[backend_id])
            load_reports[backend_id] = report.to_dict()
            _write_json(run_root / "load_reports.json", load_reports)
            if not report.success:
                raise RuntimeError(
                    f"{backend_id} fixture load failed: {report.error}"
                )

        for backend_id in ("neo4j", "fuseki"):
            health_after[backend_id] = clients[backend_id].healthcheck().to_dict()
        _write_json(run_root / "health_after.json", health_after)
        unavailable = [
            backend_id
            for backend_id, status in health_after.items()
            if not status["ok"]
        ]
        if unavailable:
            raise RuntimeError(
                f"post-load healthcheck failed: {', '.join(unavailable)}"
            )

        verification_reports, checks = _verification(
            bundle=bundle,
            clients=clients,
        )
        validation = {"passed": all(checks.values()), "checks": checks}
        _write_json(
            run_root / "verification.json",
            {"reports": verification_reports, "validation": validation},
        )
        if not validation["passed"]:
            raise RuntimeError("parameterized fixture source verification failed")
    except Exception as exc:  # Preserve the first external failure as evidence.
        error = str(exc)
        for name, value in (
            ("health_before.json", health_before),
            ("load_reports.json", load_reports),
        ):
            if not (run_root / name).exists():
                _write_json(run_root / name, value)

    ended_at = _now()
    success = error is None
    _write_json(
        status_path,
        {
            "schema_version": PARAMETERIZED_FIXTURE_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    _write_json(
        manifest_path,
        {
            "schema_version": PARAMETERIZED_FIXTURE_SCHEMA_VERSION,
            "run_id": run_id,
            "dataset_id": f"m15_f2c:{bundle.spec.workload_id}",
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
            "input_sha256": {
                **{
                    f"bundle:{bundle.spec.workload_id}/{name}": digest
                    for name, digest in bundle.manifest["files_sha256"].items()
                },
                f"bundle:{bundle.spec.workload_id}/manifest.json": _sha256_file(
                    bundle.root / "manifest.json"
                ),
            },
            "workload_bundle": dict(bundle.manifest),
            "health_before": health_before,
            "health_after": health_after,
            "load_reports": load_reports,
            "verification": {
                "query_instance_count": len(bundle.instance_ids()),
                "backend_query_count": len(verification_reports) * 2,
                "passed": bool(checks) and all(checks.values()),
                "checks": checks,
            },
            "mutation_scope": "namespaced_idempotent_append",
            "automatic_retries": 0,
            "credentials_persisted": False,
            "paper_result": False,
            "artifacts": sorted(path.name for path in run_root.iterdir()),
        },
    )
    return M15ParameterizedFixtureRecord(
        run_id=run_id,
        run_root=run_root,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        error=error,
    )
