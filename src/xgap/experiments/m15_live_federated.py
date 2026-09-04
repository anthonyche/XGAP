"""Artifact-first M15 live Neo4j-plus-Fuseki vertical slice."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.backends.protocol import BackendClient
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import DatasetSpec, QueryArtifact
from xgap.runtime import FederatedExecutionPlan, FederatedRunResult, FederatedScheduler
from xgap.runtime import RuntimeNode, RuntimeNodeKind
from xgap.semantic import (
    ConstraintPolicy,
    SemanticConstraint,
    SemanticGraphProgram,
    SemanticOperator,
    SemanticOperatorKind,
    SemanticValueKind,
)
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


RUN_SCHEMA_VERSION = "m15-b3-live-federated-run-v1"
DATASET_PATH = Path("examples/datasets/m15_split_financial_risk.yaml")
EXPECTED_PATH = Path("examples/m15_split_financial_risk/expected_result.json")
EXPECTED_SOURCE_PATH = Path(
    "examples/m15_split_financial_risk/expected_source_results.json"
)
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class M15LiveRunRecord:
    run_id: str
    run_root: Path
    success: bool
    status_path: Path
    manifest_path: Path
    result_path: Path | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_root": str(self.run_root),
            "success": self.success,
            "status_path": str(self.status_path),
            "manifest_path": str(self.manifest_path),
            "result_path": str(self.result_path) if self.result_path else None,
            "error": self.error,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _repo_path(repo_root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    resolved = candidate.resolve() if candidate.is_absolute() else (repo_root / candidate).resolve()
    if resolved != repo_root and repo_root not in resolved.parents:
        raise ValueError(f"experiment path escapes repository: {value}")
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


def build_m15_semantic_program() -> SemanticGraphProgram:
    bindings = SemanticValueKind.BINDING_SET
    return SemanticGraphProgram(
        program_id="m15-split-financial-risk-exact",
        operators=(
            SemanticOperator(
                "resolved-person",
                SemanticOperatorKind.MATCH,
                (),
                (),
                bindings,
                parameters={"entity_id": "person-alice-smith", "entity_type": "Person"},
                constraints=(
                    SemanticConstraint(
                        "person-identity",
                        "entity_id = person-alice-smith",
                        ConstraintPolicy.HARD,
                    ),
                ),
            ),
            SemanticOperator(
                "recent-large-transfers",
                SemanticOperatorKind.TRAVERSE,
                ("resolved-person",),
                (bindings,),
                bindings,
                parameters={"predicate": "transfer_to_company"},
                constraints=(
                    SemanticConstraint(
                        "frozen-window",
                        "occurred_on >= 2026-08-05",
                        ConstraintPolicy.HARD,
                    ),
                    SemanticConstraint(
                        "fixture-large-transfer",
                        "amount >= 50000 USD",
                        ConstraintPolicy.HARD,
                    ),
                ),
                required_capabilities=("native.cypher",),
            ),
            SemanticOperator(
                "align-transfer-company",
                SemanticOperatorKind.ALIGN,
                ("recent-large-transfers",),
                (bindings,),
                bindings,
                parameters={"identity_space": "m15-company"},
            ),
            SemanticOperator(
                "high-risk-companies",
                SemanticOperatorKind.MATCH,
                (),
                (),
                bindings,
                parameters={"entity_type": "Company", "risk": "HIGH"},
                constraints=(
                    SemanticConstraint(
                        "risk-classification",
                        "risk = HIGH",
                        ConstraintPolicy.RELAXABLE,
                    ),
                ),
                required_capabilities=("native.sparql",),
            ),
            SemanticOperator(
                "align-risk-company",
                SemanticOperatorKind.ALIGN,
                ("high-risk-companies",),
                (bindings,),
                bindings,
                parameters={"identity_space": "m15-company"},
            ),
            SemanticOperator(
                "federated-company-join",
                SemanticOperatorKind.JOIN,
                ("align-transfer-company", "align-risk-company"),
                (bindings, bindings),
                bindings,
                parameters={"join_key": "canonical_company_id"},
            ),
            SemanticOperator(
                "answer-projection",
                SemanticOperatorKind.PROJECT,
                ("federated-company-join",),
                (bindings,),
                bindings,
                parameters={
                    "fields": [
                        "person",
                        "company",
                        "amount",
                        "currency",
                        "occurred_on",
                        "risk",
                    ]
                },
            ),
        ),
        roots=("answer-projection",),
        metadata={
            "dataset_id": "m15_split_financial_risk",
            "entity_resolution": "pre-resolved exact fixture identity",
            "llm_required": False,
            "ontology_required": False,
        },
    )


def _query_artifact(
    repo_root: Path,
    dataset: DatasetSpec,
    backend_id: str,
) -> QueryArtifact:
    backend = dataset.backend_config(backend_id)
    raw_path = backend.get("query_file")
    if not isinstance(raw_path, str):
        raise ValueError(f"dataset has no query_file for '{backend_id}'")
    path = _repo_path(repo_root, raw_path)
    language = backend.get("language")
    if not isinstance(language, str):
        raise ValueError(f"dataset has no language for '{backend_id}'")
    return QueryArtifact(
        artifact_id=f"m15-split-{backend_id}",
        language=language,
        text=path.read_text(encoding="utf-8"),
        kind="native",
        source_path=str(path.relative_to(repo_root)),
    )


def build_m15_execution_plan(
    repo_root: Path | None = None,
) -> FederatedExecutionPlan:
    root = (repo_root or _repo_root()).resolve()
    dataset = DatasetSpec.from_yaml(_repo_path(root, DATASET_PATH))
    neo4j_query = _query_artifact(root, dataset, "neo4j")
    fuseki_query = _query_artifact(root, dataset, "fuseki")
    return FederatedExecutionPlan(
        plan_id="m15-live-split-financial-risk",
        nodes=(
            RuntimeNode(
                "recent-transfers",
                RuntimeNodeKind.REMOTE_QUERY,
                parameters={"backend_id": "neo4j", "artifact": neo4j_query.to_dict()},
                semantic_operator_ids=("resolved-person", "recent-large-transfers"),
            ),
            RuntimeNode(
                "high-risk",
                RuntimeNodeKind.REMOTE_QUERY,
                parameters={"backend_id": "fuseki", "artifact": fuseki_query.to_dict()},
                semantic_operator_ids=("high-risk-companies",),
            ),
            RuntimeNode(
                "align-transfers",
                RuntimeNodeKind.ALIGN,
                inputs=("recent-transfers",),
                parameters={
                    "field": "company_id",
                    "output_field": "canonical_company_id",
                    "mapping": {"neo:C1": "C1", "neo:C2": "C2", "neo:C3": "C3"},
                },
                semantic_operator_ids=("align-transfer-company",),
            ),
            RuntimeNode(
                "align-risk",
                RuntimeNodeKind.ALIGN,
                inputs=("high-risk",),
                parameters={
                    "field": "company_id",
                    "output_field": "canonical_company_id",
                    "mapping": {"rdf:C1": "C1", "rdf:C2": "C2", "rdf:C3": "C3"},
                },
                semantic_operator_ids=("align-risk-company",),
            ),
            RuntimeNode(
                "exchange-transfers",
                RuntimeNodeKind.EXCHANGE,
                inputs=("align-transfers",),
                semantic_operator_ids=("federated-company-join",),
            ),
            RuntimeNode(
                "exchange-risk",
                RuntimeNodeKind.EXCHANGE,
                inputs=("align-risk",),
                semantic_operator_ids=("federated-company-join",),
            ),
            RuntimeNode(
                "answer",
                RuntimeNodeKind.COORDINATOR_JOIN,
                inputs=("exchange-transfers", "exchange-risk"),
                parameters={
                    "left_on": "canonical_company_id",
                    "right_on": "canonical_company_id",
                },
                semantic_operator_ids=("federated-company-join",),
            ),
            RuntimeNode(
                "project-answer",
                RuntimeNodeKind.PROJECT,
                inputs=("answer",),
                parameters={
                    "fields": [
                        "person",
                        "company",
                        "amount",
                        "currency",
                        "occurred_on",
                        "risk",
                    ]
                },
                semantic_operator_ids=("answer-projection",),
            ),
        ),
        roots=("project-answer",),
        max_remote_calls=2,
        max_parallelism=2,
        metadata={
            "dataset_id": dataset.id,
            "execution_mode": "live_black_box_backends",
            "coordinator": "in_process",
        },
    )


def _default_clients(repo_root: Path) -> dict[str, BackendClient]:
    descriptors = repo_root / "descriptors" / "backends"
    neo4j = BackendDescriptor.from_yaml(descriptors / "neo4j.yaml")
    fuseki = BackendDescriptor.from_yaml(descriptors / "fuseki.yaml")
    return {"neo4j": Neo4jClient(neo4j), "fuseki": FusekiClient(fuseki)}


def _validate_result(
    result: FederatedRunResult,
    expected_rows: list[dict[str, Any]],
    expected_source_rows: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    node_results = {item.node_id: item for item in result.node_results}
    left = node_results["recent-transfers"].rows
    right = node_results["high-risk"].rows
    checks = {
        "runtime_success": result.success,
        "exact_expected_answer": [dict(row) for row in result.final_rows] == expected_rows,
        "exact_neo4j_source_rows": [dict(row) for row in left]
        == expected_source_rows.get("neo4j"),
        "exact_fuseki_source_rows": [dict(row) for row in right]
        == expected_source_rows.get("fuseki"),
        "neo4j_has_no_risk_or_company_name": all(
            "risk" not in row and "company" not in row for row in left
        ),
        "fuseki_has_no_person_or_transfer_fact": all(
            not ({"person", "person_id", "amount", "occurred_on"} & set(row))
            for row in right
        ),
        "both_sources_nonempty": bool(left) and bool(right),
        "exact_remote_call_count": result.total_remote_calls == 2,
        "positive_exchange_bytes": result.total_bytes_moved > 0,
    }
    return {"passed": all(checks.values()), "checks": checks}


def run_m15_live_federated(
    *,
    output_root: str | Path = "runs",
    run_id: str | None = None,
    repo_root: str | Path | None = None,
    clients: Mapping[str, BackendClient] | None = None,
) -> M15LiveRunRecord:
    root = Path(repo_root).resolve() if repo_root is not None else _repo_root()
    selected_run_id = run_id or f"m15-live-federated-{_now_slug()}"
    if not _SAFE_RUN_ID.fullmatch(selected_run_id):
        raise ValueError("run_id contains unsupported characters")
    destination = Path(output_root)
    if not destination.is_absolute():
        destination = root / destination
    run_root = destination.resolve() / selected_run_id
    run_root.mkdir(parents=True, exist_ok=False)

    status_path = run_root / "run_status.json"
    manifest_path = run_root / "run_manifest.json"
    result_path = run_root / "result.json"
    started_at = _now()
    source_paths = (
        DATASET_PATH,
        Path("examples/m15_split_financial_risk/load_neo4j.cypher"),
        Path("examples/m15_split_financial_risk/load_fuseki.ttl"),
        Path("examples/m15_split_financial_risk/query_recent_transfers.cypher"),
        Path("examples/m15_split_financial_risk/query_high_risk.rq"),
        EXPECTED_SOURCE_PATH,
        EXPECTED_PATH,
    )
    source_hashes = {
        str(path): _sha256_file(_repo_path(root, path)) for path in source_paths
    }
    git_state = _git_state(root)
    program = build_m15_semantic_program()
    plan = build_m15_execution_plan(root)
    _write_json(run_root / "semantic_program.json", program.to_dict())
    _write_json(run_root / "execution_plan.json", plan.to_dict())
    selected_clients = dict(clients) if clients is not None else _default_clients(root)

    error: str | None = None
    result: FederatedRunResult | None = None
    validation: dict[str, Any] | None = None
    health: dict[str, Any] = {}
    try:
        if set(selected_clients) != {"neo4j", "fuseki"}:
            raise ValueError("live run requires exactly neo4j and fuseki clients")
        for backend_id in ("neo4j", "fuseki"):
            status = selected_clients[backend_id].healthcheck()
            health[backend_id] = status.to_dict()
        _write_json(run_root / "health.json", health)
        unavailable = [key for key, value in health.items() if not value["ok"]]
        if unavailable:
            raise RuntimeError(f"backend healthcheck failed: {', '.join(unavailable)}")

        plugins = BackendPluginRegistry()
        for backend_id in ("neo4j", "fuseki"):
            plugins.register(NativeBackendPlugin(backend_id, selected_clients[backend_id]))
        result = FederatedScheduler(BackendInvokeTool(plugins)).execute(
            plan,
            goal_id="m15-live-federated-vertical-slice",
        )
        _write_json(result_path, result.to_dict())
        expected = json.loads(_repo_path(root, EXPECTED_PATH).read_text(encoding="utf-8"))
        if not isinstance(expected, list) or any(not isinstance(row, dict) for row in expected):
            raise ValueError("expected result must be a JSON list of objects")
        expected_sources = json.loads(
            _repo_path(root, EXPECTED_SOURCE_PATH).read_text(encoding="utf-8")
        )
        if not isinstance(expected_sources, dict):
            raise ValueError("expected source results must be a JSON object")
        source_rows: dict[str, list[dict[str, Any]]] = {}
        for backend_id in ("neo4j", "fuseki"):
            rows = expected_sources.get(backend_id)
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError(f"expected source rows for {backend_id} must be objects")
            source_rows[backend_id] = [dict(row) for row in rows]
        validation = _validate_result(result, [dict(row) for row in expected], source_rows)
        _write_json(run_root / "validation.json", validation)
        if not validation["passed"]:
            raise RuntimeError("live federated acceptance checks failed")
    except Exception as exc:  # Persist every failed external attempt as evidence.
        error = str(exc)
        if not (run_root / "health.json").exists():
            _write_json(run_root / "health.json", health)

    success = error is None
    ended_at = _now()
    status = {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": selected_run_id,
        "status": "success" if success else "failed",
        "error": error,
        "started_at": started_at,
        "ended_at": ended_at,
    }
    _write_json(status_path, status)
    artifacts = sorted(
        {
            *(path.name for path in run_root.iterdir() if path.is_file()),
            manifest_path.name,
        }
    )
    manifest = {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": selected_run_id,
        "dataset_id": "m15_split_financial_risk",
        "started_at": started_at,
        "ended_at": ended_at,
        "status": status["status"],
        "error": error,
        "git": git_state,
        "environment": {
            "hostname": platform.node(),
            "python": sys.version,
            "platform": platform.platform(),
        },
        "input_sha256": source_hashes,
        "semantic_program_id": program.program_id,
        "execution_plan_id": plan.plan_id,
        "backend_health": health,
        "validation": validation,
        "artifacts": artifacts,
        "no_llm": True,
        "no_ontology": True,
        "automatic_retries": 0,
    }
    _write_json(manifest_path, manifest)
    return M15LiveRunRecord(
        run_id=selected_run_id,
        run_root=run_root,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        result_path=result_path if result_path.exists() else None,
        error=error,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default="runs")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    if os.environ.get("XGAP_RUN_M15_LIVE") != "1":
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "error": "set XGAP_RUN_M15_LIVE=1 after both split fixtures are loaded",
                },
                sort_keys=True,
            )
        )
        return 3
    try:
        record = run_m15_live_federated(
            output_root=args.output_root,
            run_id=args.run_id,
        )
    except (FileExistsError, ValueError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps(record.to_dict(), indent=2, sort_keys=True))
    return 0 if record.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
