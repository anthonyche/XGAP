"""Non-mutating environment and artifact readiness checks for M12-D."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.backends import registry
from xgap.backends.compatibility import check_backend_support
from xgap.experiments.bundles import DatasetBundle, ModelBundle
from xgap.experiments.backend_mapping_audit import audit_dataset_backend_mapping
from xgap.experiments.contracts import ExperimentSpec
from xgap.experiments.hashing import content_hash
from xgap.experiments.matrix import expand_matrix


@dataclass(frozen=True)
class ReadinessCheck:
    check_id: str
    status: str
    message: str
    details: Mapping[str, Any]

    @property
    def passed(self) -> bool:
        return self.status in {"pass", "warning"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "status": self.status,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class BackendImageIdentity:
    service: str
    configured_reference: str
    repository: str
    tag: str | None
    digest: str | None
    pinned: bool
    immutable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "configured_reference": self.configured_reference,
            "repository": self.repository,
            "tag": self.tag,
            "digest": self.digest,
            "pinned": self.pinned,
            "immutable": self.immutable,
        }


@dataclass(frozen=True)
class ReadinessReport:
    mode: str
    checks: tuple[ReadinessCheck, ...]
    environment: Mapping[str, Any]

    @property
    def ready(self) -> bool:
        return all(item.passed for item in self.checks)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "schema_version": "m12d-readiness-report-v1",
            "mode": self.mode,
            "ready": self.ready,
            "checks": [item.to_dict() for item in self.checks],
            "environment": dict(self.environment),
        }
        return {**data, "report_hash": content_hash(data)}


def check_readiness(
    config_path: str | Path,
    *,
    check_backends: bool = False,
    python_version_override: tuple[int, int, int] | None = None,
    image_overrides: Mapping[str, str] | None = None,
) -> ReadinessReport:
    repo_root = _repo_root()
    path = _resolve(config_path, repo_root)
    raw = _load_json(path)
    if "matrix_id" in raw:
        matrix, instances = expand_matrix(path)
        specs = tuple(item.spec for item in instances)
        mode = str(_mapping(matrix.get("orchestration", {}), "orchestration").get("experiment_mode", "development"))
        calibration_ref = matrix.get("calibration_run")
    else:
        specs = (ExperimentSpec.from_dict(raw),)
        mode = str(specs[0].orchestration.get("experiment_mode", "development"))
        calibration_ref = specs[0].orchestration.get("calibration_run")
    checks: list[ReadinessCheck] = []
    version = python_version_override or tuple(sys.version_info[:3])
    python_ok = version >= (3, 10, 0)
    checks.append(
        _check(
            "python_version",
            python_ok or mode == "development",
            "pass" if python_ok else "warning" if mode == "development" else "fail",
            f"Python {'.'.join(map(str, version))}; project requires 3.10+.",
            {"version": list(version), "non_paper_environment": not python_ok},
        )
    )
    git = _git_metadata(repo_root)
    clean = git["dirty"] is False
    git_status = "pass" if clean else "warning" if mode != "paper" else "fail"
    checks.append(
        ReadinessCheck(
            "repository_state",
            git_status,
            "Repository commit and dirty state captured.",
            git,
        )
    )

    bundle_records: dict[tuple[str, str, str], dict[str, str]] = {}
    environment_variables: set[str] = set()
    backend_ids: set[str] = set()
    descriptor_dirs: set[str] = set()
    mapping_audits: dict[str, dict[str, Any]] = {}
    dataset_mapping_hashes: set[str] = set()
    for spec in specs:
        dataset = DatasetBundle.load(_resolve(spec.dataset_bundle_ref, repo_root))
        model = ModelBundle.load(_resolve(spec.model_bundle_ref, repo_root))
        record = {
            "dataset_id": dataset.dataset_id,
            "dataset_hash": dataset.bundle_hash,
            "model_id": model.config.model_id,
            "model_hash": model.bundle_hash,
            "prompt_hash": model.prompt.prompt_hash,
        }
        key = (dataset.bundle_hash, model.bundle_hash, model.prompt.prompt_hash)
        bundle_records[key] = record
        if model.config.provider != "mock" and model.config.api_key_env:
            environment_variables.add(model.config.api_key_env)
        backend_ids.update(spec.backend_ids)
        descriptor_dirs.add(spec.descriptor_dir)
        if dataset.bundle_hash not in mapping_audits:
            mapping_audits[dataset.bundle_hash] = audit_dataset_backend_mapping(dataset)
        dataset_mapping_hashes.add(content_hash(dataset.backend_mapping))
    checks.append(
        ReadinessCheck(
            "artifact_hashes",
            "pass",
            "Dataset, model, and prompt artifacts loaded and hashed.",
            {"bundles": [bundle_records[key] for key in sorted(bundle_records)]},
        )
    )
    mapping_failures = [
        report
        for report in mapping_audits.values()
        if report.get("status") != "pass"
    ]
    checks.append(
        ReadinessCheck(
            "backend_mapping_compiler_contract",
            "pass" if not mapping_failures else "fail",
            "Dataset RDF IRIs, backend mappings, and M9 SPARQL IRIs audited.",
            {
                "audits": [mapping_audits[key] for key in sorted(mapping_audits)],
                "unresolved_count": len(mapping_failures),
            },
        )
    )
    missing_env = sorted(name for name in environment_variables if not os.environ.get(name))
    env_status = "pass" if not missing_env else "warning" if mode == "development" else "fail"
    checks.append(
        ReadinessCheck(
            "required_environment",
            env_status,
            "Required model credentials checked without recording secret values.",
            {"required": sorted(environment_variables), "missing": missing_env},
        )
    )

    for descriptor_dir in descriptor_dirs:
        registry.load_descriptors(_resolve(descriptor_dir, repo_root))
    unsupported = []
    for backend_id in sorted(backend_ids):
        profile = registry.get_capability_profile(backend_id)
        support = check_backend_support(profile, "pattern.PathPatternQuery")
        if support.level.value == "unsupported":
            unsupported.append(backend_id)
    checks.append(
        ReadinessCheck(
            "compiler_backend_compatibility",
            "pass" if not unsupported else "fail",
            "M8 PathPatternQuery capability boundary checked.",
            {"backends": sorted(backend_ids), "unsupported": unsupported},
        )
    )

    calibration_path = _resolve(str(calibration_ref), repo_root) if calibration_ref else None
    calibration_files = []
    if calibration_path is not None:
        calibration_files = [
            str(calibration_path / "cost_models" / backend_id / "model.json")
            for backend_id in sorted(backend_ids)
        ]
    calibration_ok = bool(calibration_files) and all(Path(item).is_file() for item in calibration_files)
    calibration_status = (
        "pass" if calibration_ok else "warning" if mode == "development" else "fail"
    )
    checks.append(
        ReadinessCheck(
            "calibrated_gp_artifacts",
            calibration_status,
            "Backend-local calibrated GP artifacts checked.",
            {"root": str(calibration_path) if calibration_path else None, "files": calibration_files},
        )
    )
    calibration_mapping = _calibration_mapping_identity(
        calibration_path,
        expected_mapping_hashes=dataset_mapping_hashes,
        require_fuseki="fuseki" in backend_ids,
    )
    calibration_mapping_ok = calibration_mapping["status"] in {
        "pass",
        "not_applicable",
    }
    checks.append(
        ReadinessCheck(
            "calibration_mapping_identity",
            (
                "pass"
                if calibration_mapping_ok
                else "warning"
                if mode == "development"
                else "fail"
            ),
            "Calibration query artifacts checked against the active backend mapping hash.",
            calibration_mapping,
        )
    )

    output_roots = {_resolve(spec.output_root, repo_root) for spec in specs}
    unwritable = [str(path) for path in output_roots if not _writable_without_mutation(path)]
    checks.append(
        ReadinessCheck(
            "output_path",
            "pass" if not unwritable else "fail",
            "Output-path writability checked without creating files.",
            {"paths": sorted(str(item) for item in output_roots), "unwritable": unwritable},
        )
    )

    images = dict(
        image_overrides
        or configured_backend_images(repo_root / "services" / "docker-compose.yml")
    )
    image_identities = {
        name: parse_backend_image_identity(name, image)
        for name, image in sorted(images.items())
    }
    floating = {
        name: identity.configured_reference
        for name, identity in image_identities.items()
        if not identity.pinned
    }
    image_status = "pass" if not floating else "warning" if mode != "paper" else "fail"
    checks.append(
        ReadinessCheck(
            "backend_image_pinning",
            image_status,
            "Backend image tags/digests checked for reproducibility.",
            {
                "images": {
                    name: identity.to_dict()
                    for name, identity in image_identities.items()
                },
                "floating": floating,
                "paper_policy": "exact_version_tag_or_sha256_digest",
                "preferred_policy": "sha256_digest",
            },
        )
    )

    backend_health: dict[str, Any] = {}
    if check_backends:
        for backend_id in sorted(backend_ids):
            if backend_id == "neo4j":
                from xgap.backends.neo4j_client import Neo4jClient

                status = Neo4jClient(registry.get(backend_id)).healthcheck()
            elif backend_id == "fuseki":
                from xgap.backends.fuseki_client import FusekiClient

                status = FusekiClient(registry.get(backend_id)).healthcheck()
            else:
                continue
            backend_health[backend_id] = status.to_dict()
    health_ok = bool(backend_health) and all(item["ok"] for item in backend_health.values())
    health_status = (
        "pass"
        if health_ok
        else "warning"
        if not check_backends and mode != "paper"
        else "fail"
    )
    checks.append(
        ReadinessCheck(
            "backend_health_and_dataset",
            health_status,
            (
                "Backend health checked; dataset row/cardinality remains a separate smoke artifact."
                if check_backends
                else "Backend health was not requested for this readiness invocation."
            ),
            {
                "health": backend_health,
                "dataset_loaded_check": "not_checked_by_health_only",
                "recommended_command": "bash scripts/server/healthcheck_backends.sh",
            },
        )
    )
    environment = capture_environment_manifest(
        repo_root,
        images=images,
        backend_health=backend_health,
    )
    return ReadinessReport(mode, tuple(checks), environment)


def capture_environment_manifest(
    repo_root: str | Path,
    *,
    images: Mapping[str, str] | None = None,
    backend_health: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(repo_root)
    memory_bytes = _memory_bytes()
    identities = {
        name: parse_backend_image_identity(name, reference)
        for name, reference in sorted((images or {}).items())
    }
    return {
        "schema_version": "m12d-server-environment-v2",
        "python_version": platform.python_version(),
        "python_requirement": ">=3.10",
        "os": platform.platform(),
        "machine": platform.machine(),
        "cpu": platform.processor() or None,
        "cpu_count": os.cpu_count(),
        "ram_bytes": memory_bytes,
        "gpu_cuda": _command_record(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"]),
        "docker": _command_record(["docker", "version", "--format", "{{json .}}"]),
        "backend_images": dict(images or {}),
        "backend_image_identities": {
            name: {
                **identity.to_dict(),
                "local_image": _local_docker_image_metadata(identity.configured_reference),
                "backend_reported_software_version": _backend_reported_version(
                    name, backend_health or {}
                ),
            }
            for name, identity in identities.items()
        },
        "git": _git_metadata(root),
    }


def _check(
    check_id: str,
    passed: bool,
    status: str,
    message: str,
    details: Mapping[str, Any],
) -> ReadinessCheck:
    del passed
    return ReadinessCheck(check_id, status, message, details)


def _git_metadata(root: Path) -> dict[str, Any]:
    commit = _run(["git", "rev-parse", "HEAD"], cwd=root)
    status = _run(["git", "status", "--porcelain"], cwd=root)
    return {
        "commit": commit.strip() if commit and commit.strip() else None,
        "dirty": bool(status.strip()) if status is not None else None,
    }


def configured_backend_images(path: str | Path) -> dict[str, str]:
    path = Path(path)
    if not path.exists():
        return {}
    images: dict[str, str] = {}
    service: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        service_match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if service_match and service_match.group(1) != "volumes":
            service = service_match.group(1)
        image_match = re.match(r"^    image:\s*(.+?)\s*$", line)
        if service and image_match:
            raw = image_match.group(1).strip('"\'')
            default = re.search(r":-([^}]+)", raw)
            images[service] = os.environ.get(
                f"{service.upper()}_IMAGE", default.group(1) if default else raw
            )
    return images


def parse_backend_image_identity(service: str, image: str) -> BackendImageIdentity:
    reference = image.strip()
    name, separator, digest_value = reference.partition("@")
    digest = digest_value if separator else None
    last_slash = name.rfind("/")
    last_colon = name.rfind(":")
    tag = name[last_colon + 1 :] if last_colon > last_slash else None
    repository = name[:last_colon] if tag is not None else name
    digest_pinned = bool(digest and re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest))
    version_pinned = bool(
        tag
        and tag.lower() != "latest"
        and re.search(r"(?:^|[^0-9])\d+\.\d+(?:\.\d+)?(?:[^0-9]|$)", tag)
    )
    return BackendImageIdentity(
        service=service,
        configured_reference=reference,
        repository=repository,
        tag=tag,
        digest=digest,
        pinned=digest_pinned or version_pinned,
        immutable=digest_pinned,
    )


def _image_is_pinned(image: str) -> bool:
    return parse_backend_image_identity("backend", image).pinned


def _local_docker_image_metadata(reference: str) -> dict[str, Any]:
    if shutil.which("docker") is None:
        return {
            "status": "not_available",
            "image_id": None,
            "repo_digests": [],
        }
    raw = _run(
        [
            "docker",
            "image",
            "inspect",
            reference,
            "--format",
            "{{json .}}",
        ]
    )
    if raw is None:
        return {
            "status": "not_available",
            "image_id": None,
            "repo_digests": [],
        }
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "status": "unparseable",
            "image_id": None,
            "repo_digests": [],
        }
    repo_digests = data.get("RepoDigests", []) if isinstance(data, Mapping) else []
    return {
        "status": "available",
        "image_id": data.get("Id") if isinstance(data, Mapping) else None,
        "repo_digests": list(repo_digests) if isinstance(repo_digests, list) else [],
    }


def _backend_reported_version(
    backend_id: str,
    backend_health: Mapping[str, Any],
) -> Any:
    env_name = f"{backend_id.upper()}_SOFTWARE_VERSION"
    if os.environ.get(env_name):
        return {"source": env_name, "value": os.environ[env_name]}
    status = backend_health.get(backend_id)
    if isinstance(status, Mapping):
        details = status.get("details")
        if isinstance(details, Mapping):
            value = details.get("software_version") or details.get("server_header")
            if value:
                return {"source": "backend_healthcheck", "value": value}
    return {"source": "not_available", "value": None}


def _writable_without_mutation(path: Path) -> bool:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current.exists() and os.access(current, os.W_OK)


def _calibration_mapping_identity(
    calibration_root: Path | None,
    *,
    expected_mapping_hashes: set[str],
    require_fuseki: bool,
) -> dict[str, Any]:
    if not require_fuseki:
        return {"status": "not_applicable", "records": []}
    plans_path = (
        calibration_root / "calibration" / "fuseki" / "calibration_plans.jsonl"
        if calibration_root is not None
        else None
    )
    if plans_path is None or not plans_path.is_file():
        return {
            "status": "missing",
            "plans_path": str(plans_path) if plans_path else None,
            "expected_mapping_hashes": sorted(expected_mapping_hashes),
            "records": [],
        }
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        plans_path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        plan = json.loads(line)
        if not isinstance(plan, Mapping) or plan.get("status") != "success":
            continue
        artifact = plan.get("query_artifact")
        artifact = artifact if isinstance(artifact, Mapping) else {}
        parameters = artifact.get("parameters")
        parameters = parameters if isinstance(parameters, Mapping) else {}
        mapping = parameters.get("backend_mapping")
        mapping = mapping if isinstance(mapping, Mapping) else {}
        mapping_hash = mapping.get("mapping_hash")
        matches = mapping_hash in expected_mapping_hashes
        records.append(
            {
                "line_number": line_number,
                "case_id": plan.get("case_id"),
                "query_id": plan.get("query_id"),
                "mapping_id": mapping.get("mapping_id"),
                "mapping_version": mapping.get("version"),
                "mapping_hash": mapping_hash,
                "matches_active_dataset_mapping": matches,
            }
        )
    return {
        "status": (
            "pass"
            if records and all(item["matches_active_dataset_mapping"] for item in records)
            else "mismatch"
        ),
        "plans_path": str(plans_path),
        "expected_mapping_hashes": sorted(expected_mapping_hashes),
        "records": records,
    }


def _memory_bytes() -> int | None:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        size = os.sysconf("SC_PAGE_SIZE")
        return int(pages * size)
    except (ValueError, OSError, AttributeError):
        return None


def _command_record(command: list[str]) -> dict[str, Any]:
    if shutil.which(command[0]) is None:
        return {"status": "not_available", "command": command, "output": None}
    output = _run(command)
    return {
        "status": "available" if output is not None else "not_available",
        "command": command,
        "output": output.strip() if output else None,
    }


def _run(command: list[str], cwd: Path | None = None) -> str | None:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object.")
    return dict(value)


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"{path} must contain a JSON object.")
    return dict(data)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve(path: str | Path, repo_root: Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else repo_root / value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check M12-D experiment readiness.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--check-backends", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    report = check_readiness(args.config, check_backends=args.check_backends)
    text = json.dumps(report.to_dict(), indent=2, sort_keys=True, ensure_ascii=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
