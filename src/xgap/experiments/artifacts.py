"""Frozen M12 run layout and traceable experiment manifests."""

from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from xgap.experiments.bundles import DatasetBundle, ModelBundle
from xgap.experiments.contracts import ExperimentMetrics, ExperimentSpec


RUN_DIRECTORIES = (
    "plans/logical",
    "plans/physical",
    "queries",
    "results/raw",
    "results/normalized",
)

RUN_FILES = (
    "experiment_manifest.json",
    "questions.jsonl",
    "prompt.json",
    "model_config.json",
    "ontology_manifest.json",
    "candidates.jsonl",
    "validation.jsonl",
    "plans/search_trace.jsonl",
    "metrics.json",
    "cost_model.json",
    "feature_schema.json",
    "observation_snapshot.json",
    "baseline_config.json",
)


@dataclass(frozen=True)
class RunArtifactLayout:
    root: Path

    @classmethod
    def create(cls, output_root: str | Path, run_id: str) -> "RunArtifactLayout":
        root = Path(output_root) / run_id
        if root.exists() and any(root.iterdir()):
            raise FileExistsError(f"Run artifact directory is not empty: {root}")
        root.mkdir(parents=True, exist_ok=True)
        for relative in RUN_DIRECTORIES:
            (root / relative).mkdir(parents=True, exist_ok=True)
        for relative in RUN_FILES:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if relative.endswith(".jsonl"):
                path.touch()
        return cls(root)

    def path(self, relative: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def write_json(self, relative: str, value: object) -> Path:
        path = self.path(relative)
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )
        return path

    def write_jsonl(self, relative: str, records: Iterable[object]) -> Path:
        path = self.path(relative)
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(
                    json.dumps(
                        record,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                        allow_nan=False,
                    )
                    + "\n"
                )
        return path

    def inventory(self) -> tuple[str, ...]:
        return tuple(
            str(path.relative_to(self.root))
            for path in sorted(self.root.rglob("*"))
            if path.is_file()
        )


@dataclass(frozen=True)
class ExperimentManifest:
    data: Mapping[str, Any]
    schema_version: str = "m12-experiment-manifest-v1"

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, **dict(self.data)}


def create_manifest(
    *,
    repo_root: str | Path,
    spec: ExperimentSpec,
    dataset: DatasetBundle,
    model: ModelBundle,
    backend_versions: Mapping[str, str | None],
    estimator: Mapping[str, Any],
    feature_schema: Mapping[str, Any],
) -> ExperimentManifest:
    repository = Path(repo_root)
    commit, dirty = _git_metadata(repository)
    backend_records = []
    for backend_id in spec.backend_ids:
        version = backend_versions.get(backend_id)
        backend_records.append(
            {
                "backend_id": backend_id,
                "version": version,
                "version_status": "available" if version else "not_available",
            }
        )
    machine = _machine_metadata()
    unavailable = {
        "status": "not_available",
        "reason": "not collected by the offline M12-A development runner",
    }
    return ExperimentManifest(
        {
            "run_id": spec.run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "git": {"commit": commit, "dirty": dirty},
            "experiment": {
                "experiment_id": spec.experiment_id,
                "spec_version": spec.schema_version,
                "spec_hash": spec.spec_hash,
            },
            "dataset": {
                "id": dataset.dataset_id,
                "version": dataset.version,
                "hash": dataset.bundle_hash,
            },
            "ontology": {
                "id": dataset.ontology.ontology_id,
                "version": dataset.ontology.version,
                "hash": dataset.ontology.ontology_hash,
            },
            "schema_snapshot": {
                "version": dataset.schema_snapshot.version,
                "hash": dataset.schema_snapshot.content_hash,
            },
            "model": {
                "id": model.config.model_id,
                "version": model.config.version,
                "exact_snapshot": model.config.exact_model_snapshot,
                "config_hash": model.config.config_hash,
            },
            "prompt_hash": model.prompt.prompt_hash,
            "backends": backend_records,
            "estimator": dict(estimator),
            "feature_schema": dict(feature_schema),
            "semantic_deviation": {
                "config": spec.semantic_deviation.to_dict(),
                "hash": spec.semantic_deviation.config_hash,
            },
            "seeds": {
                "experiment": spec.random_seed,
                "calibration": spec.gp_protocol.calibration.random_seed,
                "model": model.config.seed,
                "model_seed_status": (
                    "available" if model.config.seed is not None else "not_available"
                ),
            },
            "execution_protocol": spec.execution_protocol.to_dict(),
            "machine": machine,
            "cuda": dict(unavailable),
            "gpu": dict(unavailable),
            "docker": dict(unavailable),
        }
    )


def initialize_run_contract_files(
    layout: RunArtifactLayout,
    *,
    spec: ExperimentSpec,
    dataset: DatasetBundle,
    model: ModelBundle,
    metrics: ExperimentMetrics,
) -> None:
    layout.write_json("prompt.json", {**model.prompt.to_dict(), "prompt_hash": model.prompt.prompt_hash})
    layout.write_json("model_config.json", model.config.to_dict())
    layout.write_json(
        "ontology_manifest.json",
        {
            "schema_version": "m12-ontology-manifest-v1",
            "ontology_id": dataset.ontology.ontology_id,
            "version": dataset.ontology.version,
            "ontology_hash": dataset.ontology.ontology_hash,
            "schema_snapshot_hash": dataset.schema_snapshot.content_hash,
            "max_relaxation_hops": dataset.ontology.max_relaxation_hops,
        },
    )
    layout.write_json("metrics.json", metrics.to_dict())
    layout.write_json("baseline_config.json", spec.baseline.to_dict())
    layout.write_json(
        "observation_snapshot.json",
        {
            "schema_version": "m12-observation-snapshot-v1",
            "status": spec.gp_protocol.calibration.observation_artifact.status.value,
            "reason": spec.gp_protocol.calibration.observation_artifact.reason,
            "observations": None,
        },
    )


def _git_metadata(repo_root: Path) -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None, None
    return commit or None, bool(dirty_result.stdout.strip())


def _machine_metadata() -> dict[str, Any]:
    return {
        "status": "available",
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "processor": platform.processor() or None,
        "cpu_count": os.cpu_count(),
    }
