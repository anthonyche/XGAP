"""Allocation-scoped lifecycle for the pinned M15 Neo4j and Fuseki services."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Protocol, Sequence

from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.experiments.m15_fixture_loader import (
    FusekiGraphStoreFixtureLoader,
    Neo4jCypherFixtureLoader,
    Neo4jParameterizedFixtureLoader,
    load_m15_split_fixture,
)
from xgap.experiments.m15_finbench_partition import (
    PARTITION_SCHEMA_VERSION as FINBENCH_PARTITION_SCHEMA_VERSION,
    load_finbench_source_partition,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_semantic_estimates import (
    M15DirectEstimateSource,
    load_m15_direct_estimate_source,
)
from xgap.experiments.m15_live_direct_semantic_frontier import (
    M15PreparedDirectSemanticFrontier,
    prepare_m15_direct_semantic_frontier,
    run_m15_live_direct_semantic_frontier,
)
from xgap.experiments.m15_live_direct_family_pilot import (
    run_m15_live_direct_family_pilot,
)
from xgap.experiments.m15_live_current_query_profile_baseline import (
    run_m15_live_current_query_profile_baseline,
)
from xgap.experiments.m15_live_paired_physical_comparison import (
    run_m15_live_paired_physical_comparison,
)
from xgap.experiments.m15_live_resolution_execution_bridge import (
    M15PreparedResolutionExecutionBridge,
    RESOLUTION_EXECUTION_BRIDGE_PREFLIGHT_SCHEMA_VERSION,
    prepare_m15_resolution_execution_bridge,
    run_m15_live_resolution_execution_bridge,
)
from xgap.experiments.m15_live_selected_interpretation_session import (
    M15PreparedSelectedInterpretationSession,
    build_m15_selected_session_preflight,
    prepare_m15_selected_interpretation_session,
    run_m15_live_selected_interpretation_session,
)
from xgap.experiments.m15_live_adaptive import run_m15_live_adaptive
from xgap.experiments.m15_live_campaign_session import (
    prepare_m15_live_campaign_session,
    run_m15_live_campaign_session,
)
from xgap.experiments.m15_live_federated import run_m15_live_federated
from xgap.experiments.m15_live_method_matrix import run_m15_live_method_matrix
from xgap.experiments.m15_live_parameterized_stream import (
    run_m15_live_parameterized_stream,
)
from xgap.experiments.m15_live_family_transfer import (
    run_m15_live_family_transfer,
)
from xgap.experiments.m15_live_finbench_correctness import (
    run_m15_live_finbench_correctness,
)
from xgap.experiments.m15_live_semantic_relaxation import (
    run_m15_live_semantic_risk_relaxation,
)
from xgap.experiments.m15_live_predicate_relaxation import (
    run_m15_live_semantic_predicate_relaxation,
)
from xgap.experiments.m15_live_query_bound_session import (
    prepare_m15_live_query_bound_session,
    run_m15_live_query_bound_session,
)
from xgap.experiments.m15_workload import (
    M15WorkloadBundle,
    load_m15_workload_bundle,
)
from xgap.experiments.m15_native_artifacts import (
    DEFAULT_LOCK_PATH,
    load_native_runtime_lock,
    parse_java_major,
)
from xgap.experiments.m15_parameterized_fixture import (
    load_m15_parameterized_fixture,
)
from xgap.experiments.m15_parameterized_workload import (
    M15ParameterizedWorkloadBundle,
    load_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_direct_semantic_workload import (
    M15DirectSemanticWorkloadBundle,
    load_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_direct_family_pilot import (
    M15DirectFamilyPilotSchedule,
    compile_m15_direct_family_pilot_schedule,
)
from xgap.experiments.m15_current_query_profile_baseline import (
    M15CurrentQueryProfileBaselineSchedule,
    compile_m15_current_query_profile_baseline_schedule,
)
from xgap.experiments.m15_paired_physical_comparison import (
    M15PairedPhysicalComparisonSchedule,
    compile_m15_paired_physical_comparison_schedule,
)
from xgap.experiments.m15_predicate_overlay import (
    M15PredicateMappingSpec,
    M15PredicateOverlayBundle,
    load_m15_predicate_overlay_bundle,
    load_m15_predicate_overlay_workload_bundle,
)
from xgap.experiments.m15_semantic_frontier import (
    M15SemanticRelaxationCatalog,
    load_m15_semantic_relaxation_catalog,
)
from xgap.experiments.m15_semantic_overlay import (
    M15SemanticOverlayBundle,
    load_m15_semantic_overlay_bundle,
)
from xgap.experiments.m15_native_runtime import STAGING_SCHEMA_VERSION
from xgap.infrastructure.descriptors import BackendDescriptor


SERVICE_RUN_SCHEMA_VERSION = "m15-b2d-native-service-run-v1"
ADAPTIVE_SERVICE_RUN_SCHEMA_VERSION = "m15-d2-native-adaptive-service-run-v1"
SCALED_ADAPTIVE_SERVICE_RUN_SCHEMA_VERSION = (
    "m15-f0-native-scaled-adaptive-service-run-v1"
)
METHOD_MATRIX_SERVICE_RUN_SCHEMA_VERSION = (
    "m15-f1-native-live-method-matrix-service-run-v1"
)
CAMPAIGN_SESSION_SERVICE_RUN_SCHEMA_VERSION = (
    "m15-f2-native-live-campaign-session-service-run-v1"
)
QUERY_BOUND_SESSION_SERVICE_RUN_SCHEMA_VERSION = (
    "m15-f2b-native-live-query-bound-session-service-run-v1"
)
PARAMETERIZED_STREAM_SERVICE_RUN_SCHEMA_VERSION = (
    "m15-f2c4-native-live-parameterized-stream-service-run-v1"
)
FAMILY_TRANSFER_SERVICE_RUN_SCHEMA_VERSION = (
    "m15-f2c5-native-live-family-transfer-service-run-v1"
)
SEMANTIC_RELAXATION_SERVICE_RUN_SCHEMA_VERSION = (
    "m15-f2c7b2-native-live-semantic-risk-relaxation-service-run-v1"
)
PREDICATE_RELAXATION_SERVICE_RUN_SCHEMA_VERSION = (
    "m15-f2c8b-native-live-semantic-predicate-relaxation-service-run-v1"
)
DIRECT_SEMANTIC_FRONTIER_SERVICE_RUN_SCHEMA_VERSION = (
    "m15-f2c9b-native-live-direct-semantic-frontier-service-run-v1"
)
DIRECT_SEMANTIC_FRONTIER_PREFLIGHT_SCHEMA_VERSION = (
    "m15-f2c9b-native-direct-semantic-frontier-preflight-v1"
)
DIRECT_FAMILY_PILOT_SERVICE_RUN_SCHEMA_VERSION = (
    "m15-f2c10d-native-live-direct-family-pilot-service-run-v1"
)
DIRECT_FAMILY_PILOT_PREFLIGHT_SCHEMA_VERSION = (
    "m15-f2c10d-native-direct-family-pilot-preflight-v1"
)
CURRENT_QUERY_PROFILE_SERVICE_RUN_SCHEMA_VERSION = (
    "m15-f2c12b-native-live-current-query-profile-service-run-v1"
)
CURRENT_QUERY_PROFILE_PREFLIGHT_SCHEMA_VERSION = (
    "m15-f2c12b-native-current-query-profile-preflight-v1"
)
PAIRED_PHYSICAL_SERVICE_RUN_SCHEMA_VERSION = (
    "m15-f2c13b-native-live-paired-physical-comparison-service-run-v1"
)
PAIRED_PHYSICAL_PREFLIGHT_SCHEMA_VERSION = (
    "m15-f2c13b-native-paired-physical-comparison-preflight-v1"
)
RESOLUTION_EXECUTION_BRIDGE_SERVICE_RUN_SCHEMA_VERSION = (
    "m15-e4b-native-live-resolution-execution-bridge-service-run-v1"
)
SELECTED_INTERPRETATION_SESSION_SERVICE_RUN_SCHEMA_VERSION = (
    "m15-e5d-native-live-selected-interpretation-session-service-run-v1"
)
FINBENCH_CORRECTNESS_SERVICE_RUN_SCHEMA_VERSION = (
    "m15-finbench-native-live-correctness-service-run-v1"
)
FAMILY_RUNTIME_COMPATIBILITY_SCHEMA_VERSION = (
    "m15-f2c5-native-runtime-compatibility-v1"
)
SERVICE_PLAN_SCHEMA_VERSION = "m15-b2d-native-service-plan-v1"
WORKLOAD_MODES = frozenset(
    {
        "vertical_slice",
        "adaptive",
        "scaled_adaptive",
        "scaled_method_matrix",
        "scaled_campaign_session",
        "scaled_query_bound_session",
        "parameterized_stream",
        "parameterized_family_transfer",
        "semantic_risk_relaxation",
        "semantic_predicate_relaxation",
        "semantic_direct_frontier",
        "direct_family_pilot",
        "current_query_profile_baseline",
        "paired_physical_comparison",
        "resolution_execution_bridge",
        "selected_interpretation_session",
        "finbench_correctness",
    }
)
LOCAL_FILESYSTEM_TYPES = frozenset(
    {
        "apfs",
        "btrfs",
        "ext2/ext3",
        "ext4",
        "overlay",
        "overlayfs",
        "tmpfs",
        "xfs",
        "zfs",
    }
)
NETWORK_FILESYSTEM_TYPES = frozenset(
    {
        "afs",
        "cifs",
        "fuse.sshfs",
        "lustre",
        "nfs",
        "nfs4",
        "smb",
        "smb2",
    }
)
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ProcessHandle(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...


@dataclass(frozen=True)
class JavaEvidence:
    command: str
    major: int
    version_output: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "major": self.major,
            "version_output": self.version_output,
        }


@dataclass(frozen=True)
class ServiceSpec:
    service_id: str
    product: str
    version: str
    command: tuple[str, ...]
    working_directory: Path
    environment: Mapping[str, str]
    health_url: str
    log_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "service_id": self.service_id,
            "product": self.product,
            "version": self.version,
            "command": list(self.command),
            "working_directory": str(self.working_directory),
            "environment": dict(self.environment),
            "health_url": self.health_url,
            "log_path": str(self.log_path),
        }


@dataclass(frozen=True)
class NativeServicePlan:
    allocation_id: str
    runtime_root: Path
    filesystem_type: str
    java: JavaEvidence
    runtime_lock_sha256: str
    staging_manifest_sha256: str
    neo4j_resource_profile: Mapping[str, str]
    neo4j_http_url: str
    fuseki_url: str
    fuseki_dataset: str
    services: tuple[ServiceSpec, ...]
    plan_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SERVICE_PLAN_SCHEMA_VERSION,
            "allocation_id": self.allocation_id,
            "runtime_root": str(self.runtime_root),
            "filesystem_type": self.filesystem_type,
            "java": self.java.to_dict(),
            "runtime_lock_sha256": self.runtime_lock_sha256,
            "staging_manifest_sha256": self.staging_manifest_sha256,
            "neo4j_resource_profile": dict(self.neo4j_resource_profile),
            "neo4j_http_url": self.neo4j_http_url,
            "fuseki_url": self.fuseki_url,
            "fuseki_dataset": self.fuseki_dataset,
            "services": [service.to_dict() for service in self.services],
            "public_ports": False,
            "automatic_retries": 0,
            "credentials_persisted": False,
        }


def build_m15_family_runtime_compatibility(
    plan: NativeServicePlan,
) -> dict[str, Any]:
    """Bind family memory to one allocation and its native runtime identity."""

    identity = {
        "schema_version": FAMILY_RUNTIME_COMPATIBILITY_SCHEMA_VERSION,
        "allocation_id": plan.allocation_id,
        "filesystem_type": plan.filesystem_type,
        "java_major": plan.java.major,
        "runtime_lock_sha256": plan.runtime_lock_sha256,
        "staging_manifest_sha256": plan.staging_manifest_sha256,
        "services": [
            {
                "service_id": service.service_id,
                "product": service.product,
                "version": service.version,
            }
            for service in sorted(plan.services, key=lambda item: item.service_id)
        ],
        "reuse_scope": "same_native_service_allocation_only",
    }
    return {**identity, "runtime_compatibility_sha256": content_hash(identity)}


@dataclass(frozen=True)
class HealthObservation:
    service_id: str
    success: bool
    attempts: int
    elapsed_ms: float
    http_status: int | None = None
    process_exit_code: int | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "service_id": self.service_id,
            "success": self.success,
            "attempts": self.attempts,
            "elapsed_ms": self.elapsed_ms,
            "http_status": self.http_status,
            "process_exit_code": self.process_exit_code,
            "last_error": self.last_error,
        }


@dataclass(frozen=True)
class ShutdownObservation:
    service_id: str
    pid: int
    initial_exit_code: int | None
    final_exit_code: int | None
    signal_sent: str | None
    escalated_to_kill: bool
    success: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "service_id": self.service_id,
            "pid": self.pid,
            "initial_exit_code": self.initial_exit_code,
            "final_exit_code": self.final_exit_code,
            "signal_sent": self.signal_sent,
            "escalated_to_kill": self.escalated_to_kill,
            "success": self.success,
            "error": self.error,
        }


@dataclass(frozen=True)
class NativeServiceRunRecord:
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


@dataclass
class RunningService:
    spec: ServiceSpec
    process: ProcessHandle
    log_handle: Any = field(repr=False)


class LoopbackPortReservations:
    """Hold loopback ports until immediately before the services are started."""

    def __init__(self, sockets: Sequence[socket.socket]):
        self._sockets = list(sockets)
        self.ports = tuple(int(item.getsockname()[1]) for item in self._sockets)

    @classmethod
    def acquire(cls, count: int) -> "LoopbackPortReservations":
        if count <= 0:
            raise ValueError("port reservation count must be positive")
        handles: list[socket.socket] = []
        try:
            for _ in range(count):
                handle = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                handle.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
                handle.bind(("127.0.0.1", 0))
                handle.listen(1)
                handles.append(handle)
            return cls(handles)
        except Exception:
            for handle in handles:
                handle.close()
            raise

    def release(self, index: int) -> None:
        handle = self._sockets[index]
        if handle.fileno() >= 0:
            handle.close()

    def close(self) -> None:
        for index in range(len(self._sockets)):
            self.release(index)

    def __enter__(self) -> "LoopbackPortReservations":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def validate_local_filesystem_type(filesystem_type: str) -> str:
    normalized = filesystem_type.strip().lower()
    if not normalized:
        raise ValueError("runtime filesystem type must be recorded")
    if normalized in NETWORK_FILESYSTEM_TYPES:
        raise ValueError(f"network filesystem is forbidden for runtime state: {normalized}")
    if normalized not in LOCAL_FILESYSTEM_TYPES:
        raise ValueError(f"runtime filesystem type is not allowlisted: {normalized}")
    return normalized


def inspect_java_runtime(
    java_command: str,
    *,
    required_major: int = 17,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> JavaEvidence:
    command = java_command.strip()
    if not command:
        raise ValueError("java command must not be empty")
    completed = runner(
        [command, "-version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    output = "\n".join(
        item.strip() for item in (completed.stdout, completed.stderr) if item.strip()
    )
    if completed.returncode != 0:
        raise ValueError(f"java version command failed with exit {completed.returncode}")
    major = parse_java_major(output)
    if major != required_major:
        raise ValueError(
            f"M15 native services require exact Java {required_major}, observed {major}"
        )
    return JavaEvidence(command=command, major=major, version_output=output)


def _validate_port(port: int, name: str) -> None:
    if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
        raise ValueError(f"{name} must be an unprivileged TCP port")


def _load_staging_manifest(path: Path, runtime_root: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read staging manifest: {exc}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != STAGING_SCHEMA_VERSION
        or payload.get("status") != "success"
    ):
        raise ValueError("staging manifest does not record success")
    try:
        recorded_root = Path(str(payload["runtime_root"])).resolve()
    except (KeyError, OSError) as exc:
        raise ValueError("staging manifest has no valid runtime_root") from exc
    if recorded_root != runtime_root:
        raise ValueError("staging manifest runtime_root does not match")
    staged = payload.get("staged_artifacts")
    if not isinstance(staged, list) or len(staged) != 2:
        raise ValueError("staging manifest must contain exactly two artifacts")
    products = {item.get("product") for item in staged if isinstance(item, dict)}
    if products != {"neo4j", "fuseki"}:
        raise ValueError("staging manifest must contain Neo4j and Fuseki")
    return payload


NEO4J_RESOURCE_PROFILES: dict[str, dict[str, str]] = {
    "development": {
        "profile_id": "development",
        "heap_initial_size": "256m",
        "heap_max_size": "512m",
        "pagecache_size": "256m",
    },
    "finbench_sf0_1": {
        "profile_id": "finbench_sf0_1",
        "heap_initial_size": "1g",
        "heap_max_size": "2g",
        "pagecache_size": "1g",
    },
}


def _neo4j_configuration(
    *,
    neo4j_root: Path,
    state_root: Path,
    http_port: int,
    bolt_port: int,
    resource_profile: Mapping[str, str],
) -> str:
    neo_state = state_root / "neo4j"
    values = {
        "server.directories.data": neo_state / "data",
        "server.directories.transaction.logs.root": neo_state / "transactions",
        "server.directories.logs": neo_state / "logs",
        "server.directories.run": neo_state / "run",
        "server.directories.import": neo_state / "import",
        "server.directories.plugins": neo_state / "plugins",
        "server.directories.lib": neo4j_root / "lib",
        "server.directories.licenses": neo4j_root / "licenses",
    }
    lines = [
        "# Generated for one job-owned XGAP M15 allocation.",
        *(f"{key}={value}" for key, value in values.items()),
        "dbms.security.auth_enabled=false",
        (
            "server.memory.heap.initial_size="
            f"{resource_profile['heap_initial_size']}"
        ),
        f"server.memory.heap.max_size={resource_profile['heap_max_size']}",
        f"server.memory.pagecache.size={resource_profile['pagecache_size']}",
        "server.default_listen_address=127.0.0.1",
        "server.default_advertised_address=127.0.0.1",
        "server.bolt.enabled=true",
        f"server.bolt.listen_address=127.0.0.1:{bolt_port}",
        f"server.bolt.advertised_address=127.0.0.1:{bolt_port}",
        "server.http.enabled=true",
        f"server.http.listen_address=127.0.0.1:{http_port}",
        f"server.http.advertised_address=127.0.0.1:{http_port}",
        "server.https.enabled=false",
    ]
    return "\n".join(str(item) for item in lines) + "\n"


def build_native_service_plan(
    *,
    runtime_root: str | Path,
    staging_manifest: str | Path,
    evidence_root: str | Path,
    filesystem_type: str,
    allocation_id: str,
    java: JavaEvidence,
    neo4j_http_port: int,
    neo4j_bolt_port: int,
    fuseki_port: int,
    lock_path: str | Path = DEFAULT_LOCK_PATH,
    neo4j_resource_profile_id: str = "development",
) -> NativeServicePlan:
    runtime = Path(runtime_root).resolve()
    evidence = Path(evidence_root).resolve()
    allocation = allocation_id.strip()
    if not allocation or allocation.lower() in {"manual", "none", "unavailable"}:
        raise ValueError("a real allocation ID is required")
    if not runtime.is_dir() or runtime.is_symlink():
        raise ValueError("runtime_root must be a real directory")
    if runtime.stat().st_uid != os.getuid():
        raise ValueError("runtime_root must be owned by the current user")
    normalized_fs = validate_local_filesystem_type(filesystem_type)
    if neo4j_resource_profile_id not in NEO4J_RESOURCE_PROFILES:
        raise ValueError("unsupported Neo4j resource profile")
    resource_profile = dict(NEO4J_RESOURCE_PROFILES[neo4j_resource_profile_id])
    staging = _load_staging_manifest(Path(staging_manifest).resolve(), runtime)
    if evidence == runtime or runtime in evidence.parents:
        raise ValueError("durable evidence must be outside runtime_root")
    evidence.mkdir(parents=True, exist_ok=True)

    for port, name in (
        (neo4j_http_port, "neo4j_http_port"),
        (neo4j_bolt_port, "neo4j_bolt_port"),
        (fuseki_port, "fuseki_port"),
    ):
        _validate_port(port, name)
    if len({neo4j_http_port, neo4j_bolt_port, fuseki_port}) != 3:
        raise ValueError("service ports must be distinct")

    lock = load_native_runtime_lock(lock_path)
    lock_file = Path(lock_path).resolve()
    if staging.get("lock_sha256") != _sha256_file(lock_file):
        raise ValueError("staging manifest does not match the active runtime lock")
    if java.major != lock.java_minimum_major or java.major != 17:
        raise ValueError("service plan requires the frozen Java 17 runtime")
    artifacts = {artifact.product: artifact for artifact in lock.artifacts}
    if set(artifacts) != {"neo4j", "fuseki"}:
        raise ValueError("runtime lock must contain exactly Neo4j and Fuseki")
    neo4j_root = runtime / artifacts["neo4j"].extract_root
    fuseki_root = runtime / artifacts["fuseki"].extract_root
    staged_paths = {
        str(item.get("product")): Path(str(item.get("runtime_path"))).resolve()
        for item in staging["staged_artifacts"]
        if isinstance(item, dict)
    }
    if staged_paths != {"neo4j": neo4j_root, "fuseki": fuseki_root}:
        raise ValueError("staging manifest product paths do not match the runtime lock")
    neo4j_executable = neo4j_root / "bin" / "neo4j"
    fuseki_executable = fuseki_root / "fuseki-server"
    for executable in (neo4j_executable, fuseki_executable):
        if not executable.is_file() or executable.is_symlink():
            raise ValueError(f"staged service executable is missing: {executable}")
        if not os.access(executable, os.X_OK):
            raise ValueError(f"staged service executable is not executable: {executable}")

    state_root = runtime / "xgap-service-state"
    state_root.mkdir(mode=0o700, exist_ok=False)
    neo4j_state = state_root / "neo4j"
    for name in ("data", "transactions", "logs", "run", "import", "plugins"):
        (neo4j_state / name).mkdir(parents=True, mode=0o700, exist_ok=False)
    source_neo4j_conf = neo4j_root / "conf"
    if not source_neo4j_conf.is_dir() or source_neo4j_conf.is_symlink():
        raise ValueError("staged Neo4j configuration directory is missing")
    neo4j_conf = state_root / "neo4j-conf"
    shutil.copytree(source_neo4j_conf, neo4j_conf, symlinks=False)
    neo4j_conf.chmod(0o700)
    neo4j_configuration = _neo4j_configuration(
        neo4j_root=neo4j_root,
        state_root=state_root,
        http_port=neo4j_http_port,
        bolt_port=neo4j_bolt_port,
        resource_profile=resource_profile,
    )
    (neo4j_conf / "neo4j.conf").write_text(neo4j_configuration, encoding="utf-8")
    (evidence / "neo4j.conf").write_text(neo4j_configuration, encoding="utf-8")
    fuseki_base = state_root / "fuseki-base"
    fuseki_base.mkdir(mode=0o700)
    local_logs = state_root / "service-logs"
    local_logs.mkdir(mode=0o700)

    neo4j_url = f"http://127.0.0.1:{neo4j_http_port}"
    fuseki_url = f"http://127.0.0.1:{fuseki_port}"
    services = (
        ServiceSpec(
            service_id="neo4j",
            product="neo4j",
            version=artifacts["neo4j"].version,
            command=(str(neo4j_executable), "console"),
            working_directory=neo4j_root,
            environment={
                "JAVACMD": java.command,
                "NEO4J_CONF": str(neo4j_conf),
                "NEO4J_HOME": str(neo4j_root),
            },
            health_url=f"{neo4j_url}/db/neo4j/tx/commit",
            log_path=local_logs / "neo4j.log",
        ),
        ServiceSpec(
            service_id="fuseki",
            product="fuseki",
            version=artifacts["fuseki"].version,
            command=(
                str(fuseki_executable),
                "--localhost",
                "--ping",
                "--port",
                str(fuseki_port),
                "--update",
                "--mem",
                "/xgap",
            ),
            working_directory=fuseki_root,
            environment={
                "FUSEKI_BASE": str(fuseki_base),
                "FUSEKI_HOME": str(fuseki_root),
                "JAVA": java.command,
                "JVM_ARGS": "-Xms128m -Xmx512m",
            },
            health_url=f"{fuseki_url}/$/ping",
            log_path=local_logs / "fuseki.log",
        ),
    )
    plan = NativeServicePlan(
        allocation_id=allocation,
        runtime_root=runtime,
        filesystem_type=normalized_fs,
        java=java,
        runtime_lock_sha256=_sha256_file(lock_file),
        staging_manifest_sha256=_sha256_file(Path(staging_manifest).resolve()),
        neo4j_resource_profile=resource_profile,
        neo4j_http_url=neo4j_url,
        fuseki_url=fuseki_url,
        fuseki_dataset="xgap",
        services=services,
        plan_path=evidence / "service_plan.json",
    )
    _write_json(plan.plan_path, plan.to_dict())
    return plan


def _health_request(spec: ServiceSpec, timeout_seconds: float) -> int:
    if spec.service_id == "neo4j":
        payload = b'{"statements":[{"statement":"RETURN 1 AS ok"}]}'
        request = urllib.request.Request(
            spec.health_url,
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
    else:
        request = urllib.request.Request(spec.health_url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        status = int(response.status)
        body = response.read()
    if not 200 <= status < 300:
        raise ValueError(f"health endpoint returned HTTP {status}")
    if spec.service_id == "neo4j":
        parsed = json.loads(body.decode("utf-8"))
        if parsed.get("errors"):
            raise ValueError("Neo4j health query returned an error")
    return status


def wait_for_service_health(
    service: RunningService,
    *,
    timeout_seconds: float = 120.0,
    interval_seconds: float = 0.5,
    probe: Callable[[ServiceSpec, float], int] = _health_request,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> HealthObservation:
    if timeout_seconds <= 0 or interval_seconds <= 0:
        raise ValueError("health timeout and interval must be positive")
    started = monotonic()
    attempts = 0
    last_error: str | None = None
    last_status: int | None = None
    while True:
        exit_code = service.process.poll()
        if exit_code is not None:
            return HealthObservation(
                service.spec.service_id,
                False,
                attempts,
                (monotonic() - started) * 1000,
                last_status,
                exit_code,
                last_error or "service process exited before readiness",
            )
        attempts += 1
        try:
            last_status = probe(service.spec, min(3.0, timeout_seconds))
            return HealthObservation(
                service.spec.service_id,
                True,
                attempts,
                (monotonic() - started) * 1000,
                last_status,
            )
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            last_error = str(exc)
        elapsed = monotonic() - started
        if elapsed >= timeout_seconds:
            return HealthObservation(
                service.spec.service_id,
                False,
                attempts,
                elapsed * 1000,
                last_status,
                service.process.poll(),
                last_error or "health deadline expired",
            )
        sleeper(min(interval_seconds, max(0.0, timeout_seconds - elapsed)))


def start_service(
    spec: ServiceSpec,
    *,
    popen: Callable[..., ProcessHandle] = subprocess.Popen,
) -> RunningService:
    spec.log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = spec.log_path.open("xb")
    environment = os.environ.copy()
    environment.update(spec.environment)
    try:
        process = popen(
            list(spec.command),
            cwd=spec.working_directory,
            env=environment,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except Exception:
        log_handle.close()
        raise
    return RunningService(spec=spec, process=process, log_handle=log_handle)


def stop_service(
    service: RunningService,
    *,
    timeout_seconds: float = 15.0,
    kill_group: Callable[[int, int], None] = os.killpg,
) -> ShutdownObservation:
    initial = service.process.poll()
    signal_sent: str | None = None
    escalated = False
    error: str | None = None
    final = initial
    try:
        if initial is None:
            signal_sent = "SIGTERM"
            kill_group(service.process.pid, signal.SIGTERM)
            try:
                final = service.process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                escalated = True
                signal_sent = "SIGKILL"
                kill_group(service.process.pid, signal.SIGKILL)
                final = service.process.wait(timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        error = str(exc)
        final = service.process.poll()
    finally:
        service.log_handle.close()
    return ShutdownObservation(
        service_id=service.spec.service_id,
        pid=service.process.pid,
        initial_exit_code=initial,
        final_exit_code=final,
        signal_sent=signal_sent,
        escalated_to_kill=escalated,
        success=initial is None and final is not None and error is None,
        error=error,
    )


@contextmanager
def _service_environment(plan: NativeServicePlan) -> Iterator[None]:
    updates = {
        "NEO4J_HTTP_URL": plan.neo4j_http_url,
        "NEO4J_DATABASE": "neo4j",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "unused-loopback-auth-disabled",
        "FUSEKI_URL": plan.fuseki_url,
        "FUSEKI_DATASET_NAME": plan.fuseki_dataset,
        "FUSEKI_ADMIN_USER": "admin",
        "FUSEKI_ADMIN_PASSWORD": "unused-loopback-auth-disabled",
    }
    previous = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _run_fixture_and_query(
    plan: NativeServicePlan,
    run_root: Path,
    repo_root: Path,
    workload_mode: str,
    workload_bundle: M15WorkloadBundle | None = None,
    campaign_config: str | Path | None = None,
    campaign_session_id: str | None = None,
    expected_campaign_spec_sha256: str | None = None,
    expected_schedule_sha256: str | None = None,
    query_bound_registry: str | Path | None = None,
    query_bound_session_id: str | None = None,
    expected_registry_spec_sha256: str | None = None,
    expected_query_bound_schedule_sha256: str | None = None,
    parameterized_workload_bundle: M15ParameterizedWorkloadBundle | None = None,
    semantic_overlay: M15SemanticOverlayBundle | None = None,
    semantic_base_bundle: M15ParameterizedWorkloadBundle | None = None,
    semantic_catalog: M15SemanticRelaxationCatalog | str | Path | None = None,
    predicate_overlay: M15PredicateOverlayBundle | None = None,
    predicate_mapping: M15PredicateMappingSpec | str | Path | None = None,
    direct_frontier_estimates: str | Path | None = None,
    prepared_direct_frontier: M15PreparedDirectSemanticFrontier | None = None,
    direct_semantic_workload: M15DirectSemanticWorkloadBundle | None = None,
    direct_family_pilot_protocol: Mapping[str, Any] | str | Path | None = None,
    direct_family_predictor_policy: Mapping[str, Any] | str | Path | None = None,
    paired_physical_protocol: Mapping[str, Any] | str | Path | None = None,
    current_query_profile_protocol: Mapping[str, Any] | str | Path | None = None,
    *,
    finbench_workload: str | Path | None = None,
    finbench_partition: str | Path | None = None,
    finbench_query_ids: Sequence[str] | None = None,
    resolution_run: str | Path | None = None,
    resolution_bridge_spec: str | Path | None = None,
    prepared_resolution_bridge: M15PreparedResolutionExecutionBridge | None = None,
    prepared_selected_session: M15PreparedSelectedInterpretationSession | None = None,
) -> None:
    descriptors = repo_root / "descriptors" / "backends"
    with _service_environment(plan):
        neo4j_descriptor = BackendDescriptor.from_yaml(descriptors / "neo4j.yaml")
        fuseki_descriptor = BackendDescriptor.from_yaml(descriptors / "fuseki.yaml")
        clients = {
            "neo4j": Neo4jClient(neo4j_descriptor),
            "fuseki": FusekiClient(fuseki_descriptor),
        }
        loaders = {
            "neo4j": Neo4jCypherFixtureLoader(clients["neo4j"]),
            "fuseki": FusekiGraphStoreFixtureLoader(fuseki_descriptor),
        }
        if workload_mode == "finbench_correctness":
            assert finbench_workload is not None
            assert finbench_partition is not None
            partition_manifest = load_finbench_source_partition(finbench_partition)
            if (
                partition_manifest.get("schema_version")
                == FINBENCH_PARTITION_SCHEMA_VERSION
            ):
                loaders["neo4j"] = Neo4jParameterizedFixtureLoader(
                    clients["neo4j"]
                )
            for client in clients.values():
                client.timeout_seconds = 60.0
            correctness = run_m15_live_finbench_correctness(
                workload_root=finbench_workload,
                partition_root=finbench_partition,
                clients=clients,
                loaders=loaders,
                output_root=run_root,
                run_id="finbench-correctness-run",
                repo_root=repo_root,
                query_ids=finbench_query_ids,
            )
            if not correctness.success:
                raise RuntimeError(
                    f"live FinBench correctness gate failed: {correctness.error}"
                )
            return
        if workload_mode in {
            "resolution_execution_bridge",
            "selected_interpretation_session",
        }:
            assert resolution_run is not None
            assert resolution_bridge_spec is not None
            selected_prepared_bridge = (
                prepared_resolution_bridge
                if workload_mode == "resolution_execution_bridge"
                else prepared_selected_session.resolution_bridge
                if prepared_selected_session is not None
                else None
            )
            assert selected_prepared_bridge is not None
            for client in clients.values():
                client.timeout_seconds = 60.0

            expected_root = (
                selected_prepared_bridge.workload.workload_bundle.root.resolve()
            )

            def reload_resolution_bridge_fixture_bundle(
                bundle_root: Path,
            ) -> M15ParameterizedWorkloadBundle:
                if bundle_root.resolve() != expected_root:
                    raise ValueError(
                        "resolution bridge fixture loader received a different "
                        "parameterized workload root"
                    )
                reloaded = selected_prepared_bridge.reload_workload()
                if reloaded.workload_bundle.root.resolve() != expected_root:
                    raise ValueError(
                        "reloaded resolution bridge workload changed its nested root"
                    )
                return reloaded.workload_bundle

            fixture = load_m15_parameterized_fixture(
                workload_bundle=selected_prepared_bridge.workload.workload_bundle,
                clients=clients,
                loaders=loaders,
                output_root=run_root,
                run_id="resolution-execution-fixture-load",
                repo_root=repo_root,
                bundle_loader=reload_resolution_bridge_fixture_bundle,
            )
            if not fixture.success:
                raise RuntimeError(
                    f"resolution bridge fixture load failed: {fixture.error}"
                )
            if workload_mode == "resolution_execution_bridge":
                assert prepared_resolution_bridge is not None
                bridge = run_m15_live_resolution_execution_bridge(
                    resolution_run_path=resolution_run,
                    bridge_spec_path=resolution_bridge_spec,
                    prepared=prepared_resolution_bridge,
                    clients=clients,
                    output_root=run_root,
                    run_id="resolution-execution-bridge-run",
                    repo_root=repo_root,
                )
                if not bridge.success:
                    raise RuntimeError(
                        "live resolution-execution bridge failed: "
                        f"{bridge.error}"
                    )
            else:
                assert prepared_selected_session is not None
                selected = run_m15_live_selected_interpretation_session(
                    prepared=prepared_selected_session,
                    clients=clients,
                    output_root=run_root,
                    run_id="selected-interpretation-session-run",
                    repo_root=repo_root,
                )
                if not selected.success:
                    raise RuntimeError(
                        "live selected-interpretation session failed: "
                        f"{selected.error}"
                    )
            return
        if workload_mode == "paired_physical_comparison":
            assert direct_semantic_workload is not None
            assert semantic_base_bundle is not None
            assert semantic_catalog is not None
            assert predicate_mapping is not None
            assert paired_physical_protocol is not None
            assert direct_family_pilot_protocol is not None
            assert direct_family_predictor_policy is not None
            assert current_query_profile_protocol is not None
            for client in clients.values():
                client.timeout_seconds = 60.0

            def reload_paired_fixture_bundle(
                bundle_root: Path,
            ) -> M15ParameterizedWorkloadBundle:
                expected_root = direct_semantic_workload.workload_bundle.root.resolve()
                if bundle_root.resolve() != expected_root:
                    raise ValueError(
                        "paired physical fixture loader received a different "
                        "parameterized workload root"
                    )
                reloaded = load_m15_direct_semantic_workload_bundle(
                    direct_semantic_workload.root,
                    base_bundle=semantic_base_bundle,
                    catalog=semantic_catalog,
                    mapping=predicate_mapping,
                )
                if reloaded.workload_bundle.root.resolve() != expected_root:
                    raise ValueError(
                        "reloaded paired physical workload changed its nested root"
                    )
                return reloaded.workload_bundle

            fixture = load_m15_parameterized_fixture(
                workload_bundle=direct_semantic_workload.workload_bundle,
                clients=clients,
                loaders=loaders,
                output_root=run_root,
                run_id="paired-physical-fixture-load",
                repo_root=repo_root,
                bundle_loader=reload_paired_fixture_bundle,
            )
            if not fixture.success:
                raise RuntimeError(
                    f"paired physical fixture load failed: {fixture.error}"
                )
            runtime_compatibility = build_m15_family_runtime_compatibility(plan)
            _write_json(
                run_root / "family_runtime_compatibility.json",
                runtime_compatibility,
            )
            paired = run_m15_live_paired_physical_comparison(
                direct_workload=direct_semantic_workload,
                base_bundle=semantic_base_bundle,
                catalog=semantic_catalog,
                mapping=predicate_mapping,
                protocol=paired_physical_protocol,
                family_protocol=direct_family_pilot_protocol,
                predictor_policy=direct_family_predictor_policy,
                profile_protocol=current_query_profile_protocol,
                clients=clients,
                runtime_compatibility_sha256=runtime_compatibility[
                    "runtime_compatibility_sha256"
                ],
                output_root=run_root,
                run_id="paired-physical-comparison-run",
                repo_root=repo_root,
            )
            if not paired.success:
                raise RuntimeError(
                    f"live paired physical comparison failed: {paired.error}"
                )
            return
        if workload_mode == "current_query_profile_baseline":
            assert direct_semantic_workload is not None
            assert semantic_base_bundle is not None
            assert semantic_catalog is not None
            assert predicate_mapping is not None
            assert current_query_profile_protocol is not None
            for client in clients.values():
                client.timeout_seconds = 60.0

            def reload_current_profile_fixture_bundle(
                bundle_root: Path,
            ) -> M15ParameterizedWorkloadBundle:
                expected_root = direct_semantic_workload.workload_bundle.root.resolve()
                if bundle_root.resolve() != expected_root:
                    raise ValueError(
                        "current-query profile fixture loader received a "
                        "different parameterized workload root"
                    )
                reloaded = load_m15_direct_semantic_workload_bundle(
                    direct_semantic_workload.root,
                    base_bundle=semantic_base_bundle,
                    catalog=semantic_catalog,
                    mapping=predicate_mapping,
                )
                if reloaded.workload_bundle.root.resolve() != expected_root:
                    raise ValueError(
                        "reloaded current-query profile workload changed its "
                        "nested root"
                    )
                return reloaded.workload_bundle

            fixture = load_m15_parameterized_fixture(
                workload_bundle=direct_semantic_workload.workload_bundle,
                clients=clients,
                loaders=loaders,
                output_root=run_root,
                run_id="current-query-profile-fixture-load",
                repo_root=repo_root,
                bundle_loader=reload_current_profile_fixture_bundle,
            )
            if not fixture.success:
                raise RuntimeError(
                    f"current-query profile fixture load failed: {fixture.error}"
                )
            profile = run_m15_live_current_query_profile_baseline(
                direct_workload=direct_semantic_workload,
                base_bundle=semantic_base_bundle,
                catalog=semantic_catalog,
                mapping=predicate_mapping,
                protocol=current_query_profile_protocol,
                clients=clients,
                output_root=run_root,
                run_id="current-query-profile-baseline-run",
                repo_root=repo_root,
            )
            if not profile.success:
                raise RuntimeError(
                    f"live current-query profile baseline failed: {profile.error}"
                )
            return
        if workload_mode == "direct_family_pilot":
            assert direct_semantic_workload is not None
            assert semantic_base_bundle is not None
            assert semantic_catalog is not None
            assert predicate_mapping is not None
            assert direct_family_pilot_protocol is not None
            assert direct_family_predictor_policy is not None
            for client in clients.values():
                client.timeout_seconds = 60.0

            def reload_direct_family_fixture_bundle(
                bundle_root: Path,
            ) -> M15ParameterizedWorkloadBundle:
                """Revalidate the enclosing direct workload at fixture time.

                The nested workload is a predicate-extended parameterized
                bundle, so the base parameterized loader cannot validate it.
                Reconstructing the enclosing direct workload preserves its
                catalog, mapping, split, and file-hash checks immediately
                before the first fixture mutation.
                """

                expected_root = direct_semantic_workload.workload_bundle.root.resolve()
                if bundle_root.resolve() != expected_root:
                    raise ValueError(
                        "direct family fixture loader received a different "
                        "parameterized workload root"
                    )
                reloaded = load_m15_direct_semantic_workload_bundle(
                    direct_semantic_workload.root,
                    base_bundle=semantic_base_bundle,
                    catalog=semantic_catalog,
                    mapping=predicate_mapping,
                )
                if reloaded.workload_bundle.root.resolve() != expected_root:
                    raise ValueError(
                        "reloaded direct family workload changed its nested root"
                    )
                return reloaded.workload_bundle

            fixture = load_m15_parameterized_fixture(
                workload_bundle=direct_semantic_workload.workload_bundle,
                clients=clients,
                loaders=loaders,
                output_root=run_root,
                run_id="direct-family-fixture-load",
                repo_root=repo_root,
                bundle_loader=reload_direct_family_fixture_bundle,
            )
            if not fixture.success:
                raise RuntimeError(
                    f"direct family pilot fixture load failed: {fixture.error}"
                )
            runtime_compatibility = build_m15_family_runtime_compatibility(plan)
            _write_json(
                run_root / "family_runtime_compatibility.json",
                runtime_compatibility,
            )
            pilot = run_m15_live_direct_family_pilot(
                direct_workload=direct_semantic_workload,
                base_bundle=semantic_base_bundle,
                catalog=semantic_catalog,
                mapping=predicate_mapping,
                protocol=direct_family_pilot_protocol,
                predictor_policy=direct_family_predictor_policy,
                clients=clients,
                runtime_compatibility_sha256=runtime_compatibility[
                    "runtime_compatibility_sha256"
                ],
                output_root=run_root,
                run_id="direct-family-pilot-run",
                repo_root=repo_root,
            )
            if not pilot.success:
                raise RuntimeError(f"live direct family pilot failed: {pilot.error}")
            return
        if workload_mode in {
            "parameterized_stream",
            "parameterized_family_transfer",
        }:
            assert parameterized_workload_bundle is not None
            fixture = load_m15_parameterized_fixture(
                workload_bundle=parameterized_workload_bundle,
                clients=clients,
                loaders=loaders,
                output_root=run_root,
                run_id="parameterized-fixture-load",
                repo_root=repo_root,
            )
            if not fixture.success:
                raise RuntimeError(
                    f"parameterized fixture load failed: {fixture.error}"
                )
            if workload_mode == "parameterized_stream":
                stream = run_m15_live_parameterized_stream(
                    workload_bundle=parameterized_workload_bundle,
                    clients=clients,
                    output_root=run_root,
                    run_id="parameterized-stream-run",
                    repo_root=repo_root,
                )
                if not stream.success:
                    raise RuntimeError(
                        f"live parameterized stream failed: {stream.error}"
                    )
            else:
                runtime_compatibility = build_m15_family_runtime_compatibility(plan)
                _write_json(
                    run_root / "family_runtime_compatibility.json",
                    runtime_compatibility,
                )
                transfer = run_m15_live_family_transfer(
                    workload_bundle=parameterized_workload_bundle,
                    clients=clients,
                    runtime_compatibility_sha256=runtime_compatibility[
                        "runtime_compatibility_sha256"
                    ],
                    output_root=run_root,
                    run_id="family-transfer-run",
                    repo_root=repo_root,
                )
                if not transfer.success:
                    raise RuntimeError(
                        f"live family transfer failed: {transfer.error}"
                    )
            return
        if workload_mode == "semantic_risk_relaxation":
            assert semantic_overlay is not None
            assert semantic_base_bundle is not None
            assert semantic_catalog is not None
            fixture = load_m15_parameterized_fixture(
                workload_bundle=semantic_overlay.workload_bundle,
                clients=clients,
                loaders=loaders,
                output_root=run_root,
                run_id="semantic-fixture-load",
                repo_root=repo_root,
            )
            if not fixture.success:
                raise RuntimeError(
                    f"semantic overlay fixture load failed: {fixture.error}"
                )
            semantic = run_m15_live_semantic_risk_relaxation(
                semantic_overlay=semantic_overlay,
                base_bundle=semantic_base_bundle,
                catalog=semantic_catalog,
                clients=clients,
                output_root=run_root,
                run_id="semantic-risk-relaxation-run",
                repo_root=repo_root,
            )
            if not semantic.success:
                raise RuntimeError(
                    f"live semantic risk relaxation failed: {semantic.error}"
                )
            return
        if workload_mode == "semantic_predicate_relaxation":
            assert predicate_overlay is not None
            assert semantic_base_bundle is not None
            assert semantic_catalog is not None
            assert predicate_mapping is not None
            fixture = load_m15_parameterized_fixture(
                workload_bundle=predicate_overlay.workload_bundle,
                clients=clients,
                loaders=loaders,
                output_root=run_root,
                run_id="predicate-fixture-load",
                repo_root=repo_root,
                bundle_loader=partial(
                    load_m15_predicate_overlay_workload_bundle,
                    overlay_root=predicate_overlay.root,
                    base_bundle=semantic_base_bundle,
                    catalog=semantic_catalog,
                    mapping=predicate_mapping,
                ),
            )
            if not fixture.success:
                raise RuntimeError(
                    f"predicate overlay fixture load failed: {fixture.error}"
                )
            predicate = run_m15_live_semantic_predicate_relaxation(
                predicate_overlay=predicate_overlay,
                base_bundle=semantic_base_bundle,
                catalog=semantic_catalog,
                mapping=predicate_mapping,
                clients=clients,
                output_root=run_root,
                run_id="semantic-predicate-relaxation-run",
                repo_root=repo_root,
            )
            if not predicate.success:
                raise RuntimeError(
                    "live semantic predicate relaxation failed: "
                    f"{predicate.error}"
                )
            return
        if workload_mode == "semantic_direct_frontier":
            assert predicate_overlay is not None
            assert semantic_base_bundle is not None
            assert semantic_catalog is not None
            assert predicate_mapping is not None
            assert direct_frontier_estimates is not None
            assert prepared_direct_frontier is not None
            fixture = load_m15_parameterized_fixture(
                workload_bundle=predicate_overlay.workload_bundle,
                clients=clients,
                loaders=loaders,
                output_root=run_root,
                run_id="frontier-fixture-load",
                repo_root=repo_root,
                bundle_loader=partial(
                    load_m15_predicate_overlay_workload_bundle,
                    overlay_root=predicate_overlay.root,
                    base_bundle=semantic_base_bundle,
                    catalog=semantic_catalog,
                    mapping=predicate_mapping,
                ),
            )
            if not fixture.success:
                raise RuntimeError(
                    f"direct frontier fixture load failed: {fixture.error}"
                )
            frontier = run_m15_live_direct_semantic_frontier(
                predicate_overlay=predicate_overlay,
                base_bundle=semantic_base_bundle,
                catalog=semantic_catalog,
                mapping=predicate_mapping,
                estimate_source=direct_frontier_estimates,
                clients=clients,
                output_root=run_root,
                run_id="direct-semantic-frontier-run",
                repo_root=repo_root,
                prepared_frontier=prepared_direct_frontier,
            )
            if not frontier.success:
                raise RuntimeError(
                    f"live direct semantic frontier failed: {frontier.error}"
                )
            return
        fixture = load_m15_split_fixture(
            output_root=run_root,
            run_id="fixture-load",
            repo_root=repo_root,
            clients=clients,
            loaders=loaders,
            workload_bundle=workload_bundle,
        )
        if not fixture.success:
            raise RuntimeError(f"fixture load failed: {fixture.error}")
        if workload_mode == "vertical_slice":
            live = run_m15_live_federated(
                output_root=run_root,
                run_id="federated-run",
                repo_root=repo_root,
                clients=clients,
            )
            if not live.success:
                raise RuntimeError(f"live federated run failed: {live.error}")
        elif workload_mode in {"adaptive", "scaled_adaptive"}:
            adaptive = run_m15_live_adaptive(
                output_root=run_root,
                run_id="adaptive-run",
                repo_root=repo_root,
                clients=clients,
                workload_bundle=workload_bundle,
            )
            if not adaptive.success:
                raise RuntimeError(f"live adaptive run failed: {adaptive.error}")
        elif workload_mode == "scaled_method_matrix":
            assert workload_bundle is not None
            matrix = run_m15_live_method_matrix(
                output_root=run_root,
                run_id="method-matrix-run",
                repo_root=repo_root,
                clients=clients,
                workload_bundle=workload_bundle,
            )
            if not matrix.success:
                raise RuntimeError(f"live method matrix failed: {matrix.error}")
        elif workload_mode == "scaled_campaign_session":
            assert workload_bundle is not None
            assert campaign_config is not None
            assert campaign_session_id is not None
            assert expected_campaign_spec_sha256 is not None
            assert expected_schedule_sha256 is not None
            campaign = run_m15_live_campaign_session(
                campaign_config=campaign_config,
                session_id=campaign_session_id,
                expected_campaign_spec_sha256=expected_campaign_spec_sha256,
                expected_schedule_sha256=expected_schedule_sha256,
                workload_bundle=workload_bundle,
                output_root=run_root,
                run_id="campaign-session-run",
                repo_root=repo_root,
                clients=clients,
            )
            if not campaign.success:
                raise RuntimeError(
                    f"live campaign session failed: {campaign.error}"
                )
        elif workload_mode == "scaled_query_bound_session":
            assert workload_bundle is not None
            assert query_bound_registry is not None
            assert query_bound_session_id is not None
            assert expected_registry_spec_sha256 is not None
            assert expected_query_bound_schedule_sha256 is not None
            query_bound = run_m15_live_query_bound_session(
                query_bound_registry=query_bound_registry,
                session_id=query_bound_session_id,
                expected_registry_spec_sha256=expected_registry_spec_sha256,
                expected_query_bound_schedule_sha256=(
                    expected_query_bound_schedule_sha256
                ),
                workload_bundle=workload_bundle,
                output_root=run_root,
                run_id="query-bound-session-run",
                repo_root=repo_root,
                clients=clients,
            )
            if not query_bound.success:
                raise RuntimeError(
                    f"live query-bound session failed: {query_bound.error}"
                )
        else:
            raise ValueError(f"unsupported M15 workload mode '{workload_mode}'")


def run_m15_native_services(
    *,
    runtime_root: str | Path,
    staging_manifest: str | Path,
    output_root: str | Path,
    run_id: str,
    filesystem_type: str,
    allocation_id: str,
    java_command: str,
    repo_root: str | Path | None = None,
    required_java_major: int = 17,
    neo4j_resource_profile_id: str = "development",
    workload_mode: str = "vertical_slice",
    workload_bundle: M15WorkloadBundle | str | Path | None = None,
    campaign_config: str | Path | None = None,
    campaign_session_id: str | None = None,
    expected_campaign_spec_sha256: str | None = None,
    expected_schedule_sha256: str | None = None,
    query_bound_registry: str | Path | None = None,
    query_bound_session_id: str | None = None,
    expected_registry_spec_sha256: str | None = None,
    expected_query_bound_schedule_sha256: str | None = None,
    parameterized_workload_bundle: (
        M15ParameterizedWorkloadBundle | str | Path | None
    ) = None,
    semantic_overlay: M15SemanticOverlayBundle | str | Path | None = None,
    semantic_base_bundle: (
        M15ParameterizedWorkloadBundle | str | Path | None
    ) = None,
    semantic_catalog: M15SemanticRelaxationCatalog | str | Path | None = None,
    predicate_overlay: M15PredicateOverlayBundle | str | Path | None = None,
    predicate_mapping: M15PredicateMappingSpec | str | Path | None = None,
    direct_frontier_estimates: str | Path | None = None,
    direct_semantic_workload: (
        M15DirectSemanticWorkloadBundle | str | Path | None
    ) = None,
    direct_family_pilot_protocol: Mapping[str, Any] | str | Path | None = None,
    direct_family_predictor_policy: Mapping[str, Any] | str | Path | None = None,
    paired_physical_protocol: Mapping[str, Any] | str | Path | None = None,
    current_query_profile_protocol: Mapping[str, Any] | str | Path | None = None,
    resolution_run: str | Path | None = None,
    resolution_bridge_spec: str | Path | None = None,
    selected_session_training_memory: str | Path | None = None,
    selected_session_expected_memory_sha256: str | None = None,
    selected_session_predictor_policy: str | Path | None = None,
    selected_session_interpretation_policy: str | Path | None = None,
    selected_session_ontology: str | Path | None = None,
    selected_session_relaxation_policy: str | Path | None = None,
    selected_session_transport_policy: str | Path | None = None,
    selected_session_live_policy: str | Path | None = None,
    selected_session_id: str | None = None,
    selected_session_structural_candidate_id: str | None = None,
    selected_session_predicate_candidate_id: str | None = None,
    selected_session_authority_source_id: str | None = None,
    finbench_workload: str | Path | None = None,
    finbench_partition: str | Path | None = None,
    finbench_query_ids: Sequence[str] | None = None,
) -> NativeServiceRunRecord:
    root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else Path(__file__).resolve().parents[3]
    )
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("run_id contains unsupported characters")
    if workload_mode not in WORKLOAD_MODES:
        raise ValueError(f"unsupported M15 workload mode '{workload_mode}'")
    finbench_values = (finbench_workload, finbench_partition)
    if workload_mode == "finbench_correctness":
        if any(value is None for value in finbench_values):
            raise ValueError(
                "finbench_correctness requires a verified workload and partition"
            )
    elif any(value is not None for value in finbench_values) or finbench_query_ids is not None:
        raise ValueError(
            "FinBench inputs are accepted only in finbench_correctness mode"
        )
    selected_bundle = (
        load_m15_workload_bundle(
            workload_bundle.root
            if isinstance(workload_bundle, M15WorkloadBundle)
            else workload_bundle
        )
        if workload_bundle is not None
        else None
    )
    selected_parameterized_bundle = (
        load_m15_parameterized_workload_bundle(
            parameterized_workload_bundle.root
            if isinstance(
                parameterized_workload_bundle,
                M15ParameterizedWorkloadBundle,
            )
            else parameterized_workload_bundle
        )
        if parameterized_workload_bundle is not None
        else None
    )
    if selected_bundle is not None and selected_parameterized_bundle is not None:
        raise ValueError("workload bundle inputs are mutually exclusive")
    selected_semantic_base = (
        semantic_base_bundle
        if isinstance(semantic_base_bundle, M15ParameterizedWorkloadBundle)
        else load_m15_parameterized_workload_bundle(semantic_base_bundle)
        if semantic_base_bundle is not None
        else None
    )
    selected_semantic_catalog = (
        semantic_catalog
        if isinstance(semantic_catalog, M15SemanticRelaxationCatalog)
        else load_m15_semantic_relaxation_catalog(semantic_catalog)
        if semantic_catalog is not None
        else None
    )
    selected_semantic_overlay = (
        load_m15_semantic_overlay_bundle(
            semantic_overlay.root
            if isinstance(semantic_overlay, M15SemanticOverlayBundle)
            else semantic_overlay,
            base_bundle=selected_semantic_base,
            catalog=selected_semantic_catalog,
        )
        if semantic_overlay is not None
        and selected_semantic_base is not None
        and selected_semantic_catalog is not None
        else None
    )
    selected_predicate_mapping = (
        predicate_mapping
        if isinstance(predicate_mapping, M15PredicateMappingSpec)
        else M15PredicateMappingSpec.from_json(predicate_mapping)
        if predicate_mapping is not None
        else None
    )
    selected_predicate_overlay = (
        load_m15_predicate_overlay_bundle(
            predicate_overlay.root
            if isinstance(predicate_overlay, M15PredicateOverlayBundle)
            else predicate_overlay,
            base_bundle=selected_semantic_base,
            catalog=selected_semantic_catalog,
            mapping=selected_predicate_mapping,
        )
        if predicate_overlay is not None
        and selected_semantic_base is not None
        and selected_semantic_catalog is not None
        and selected_predicate_mapping is not None
        else None
    )
    selected_direct_semantic_workload = (
        direct_semantic_workload
        if isinstance(direct_semantic_workload, M15DirectSemanticWorkloadBundle)
        else load_m15_direct_semantic_workload_bundle(
            direct_semantic_workload,
            base_bundle=selected_semantic_base,
            catalog=selected_semantic_catalog,
            mapping=selected_predicate_mapping,
        )
        if direct_semantic_workload is not None
        and selected_semantic_base is not None
        and selected_semantic_catalog is not None
        and selected_predicate_mapping is not None
        else None
    )
    selected_direct_frontier_estimates: M15DirectEstimateSource | None = (
        load_m15_direct_estimate_source(direct_frontier_estimates)
        if direct_frontier_estimates is not None
        else None
    )
    prepared_direct_frontier: M15PreparedDirectSemanticFrontier | None = None
    prepared_direct_family_schedule: M15DirectFamilyPilotSchedule | None = None
    prepared_current_query_profile_schedule: (
        M15CurrentQueryProfileBaselineSchedule | None
    ) = None
    prepared_paired_physical_schedule: (
        M15PairedPhysicalComparisonSchedule | None
    ) = None
    prepared_resolution_bridge: M15PreparedResolutionExecutionBridge | None = None
    prepared_selected_session: M15PreparedSelectedInterpretationSession | None = None
    direct_family_values = (
        direct_family_pilot_protocol,
        direct_family_predictor_policy,
    )
    if workload_mode not in {
        "direct_family_pilot",
        "paired_physical_comparison",
    } and any(
        value is not None for value in direct_family_values
    ):
        raise ValueError(
            "direct family inputs are accepted only in direct-family modes"
        )
    if (
        workload_mode not in {
            "current_query_profile_baseline",
            "paired_physical_comparison",
        }
        and current_query_profile_protocol is not None
    ):
        raise ValueError(
            "current-query profile protocol is accepted only in profile modes"
        )
    if workload_mode != "paired_physical_comparison" and (
        paired_physical_protocol is not None
    ):
        raise ValueError(
            "paired physical protocol is accepted only in "
            "paired_physical_comparison"
        )
    resolution_bridge_values = (resolution_run, resolution_bridge_spec)
    resolution_modes = {
        "resolution_execution_bridge",
        "selected_interpretation_session",
    }
    if workload_mode not in resolution_modes and any(
        value is not None for value in resolution_bridge_values
    ):
        raise ValueError(
            "resolution bridge inputs are accepted only in a resolution mode"
        )
    selected_session_values = (
        selected_session_training_memory,
        selected_session_expected_memory_sha256,
        selected_session_predictor_policy,
        selected_session_interpretation_policy,
        selected_session_ontology,
        selected_session_relaxation_policy,
        selected_session_transport_policy,
        selected_session_live_policy,
        selected_session_id,
        selected_session_structural_candidate_id,
        selected_session_predicate_candidate_id,
        selected_session_authority_source_id,
    )
    if workload_mode != "selected_interpretation_session" and any(
        value is not None for value in selected_session_values
    ):
        raise ValueError(
            "selected-session inputs are accepted only in "
            "selected_interpretation_session"
        )
    if (
        workload_mode not in {
            "direct_family_pilot",
            "current_query_profile_baseline",
            "paired_physical_comparison",
        }
        and direct_semantic_workload is not None
    ):
        raise ValueError(
            "direct semantic workload is accepted only in a direct-family "
            "or profile comparison mode"
        )
    scaled_mode = workload_mode in {
        "scaled_adaptive",
        "scaled_method_matrix",
        "scaled_campaign_session",
        "scaled_query_bound_session",
    }
    if scaled_mode and selected_bundle is None:
        raise ValueError(f"{workload_mode} workload mode requires a verified bundle")
    if not scaled_mode and selected_bundle is not None:
        raise ValueError("a workload bundle is accepted only in a scaled mode")
    parameterized_modes = {
        "parameterized_stream",
        "parameterized_family_transfer",
    }
    if workload_mode in parameterized_modes:
        if selected_parameterized_bundle is None:
            raise ValueError(
                f"{workload_mode} workload mode requires a verified "
                "parameterized bundle"
            )
    elif selected_parameterized_bundle is not None:
        raise ValueError(
            "a parameterized workload bundle is accepted only in "
            "a parameterized workload mode"
        )
    if workload_mode in resolution_modes:
        if any(value is None for value in resolution_bridge_values):
            raise ValueError(
                f"{workload_mode} requires a resolution run and bridge "
                "specification"
            )
        if any(
            value is not None
            for value in (
                workload_bundle,
                parameterized_workload_bundle,
                semantic_overlay,
                semantic_base_bundle,
                semantic_catalog,
                predicate_overlay,
                predicate_mapping,
                direct_frontier_estimates,
                direct_semantic_workload,
                direct_family_pilot_protocol,
                direct_family_predictor_policy,
                current_query_profile_protocol,
                paired_physical_protocol,
            )
        ):
            raise ValueError(
                f"{workload_mode} does not accept another workload, "
                "semantic, predictor, profile, or paired input"
            )
        if workload_mode == "selected_interpretation_session" and any(
            value is None for value in selected_session_values
        ):
            raise ValueError(
                "selected_interpretation_session requires historical memory, "
                "its expected hash, all E5 policy inputs, a session ID, both "
                "explicit candidate IDs, and an authority source ID"
            )
    elif workload_mode == "paired_physical_comparison":
        required_paired_values = (
            paired_physical_protocol,
            direct_family_pilot_protocol,
            direct_family_predictor_policy,
            current_query_profile_protocol,
            direct_semantic_workload,
            semantic_base_bundle,
            semantic_catalog,
            predicate_mapping,
        )
        if any(value is None for value in required_paired_values):
            raise ValueError(
                "paired_physical_comparison requires a direct workload, base "
                "bundle, semantic catalog, predicate mapping, paired protocol, "
                "family protocol, predictor policy, and profile protocol"
            )
        if selected_direct_semantic_workload is None:
            raise ValueError("paired physical workload inputs could not be verified")
        if any(
            value is not None
            for value in (
                semantic_overlay,
                predicate_overlay,
                direct_frontier_estimates,
                selected_bundle,
                selected_parameterized_bundle,
            )
        ):
            raise ValueError(
                "paired_physical_comparison does not accept overlays, frontier "
                "estimates, or another workload bundle"
            )
        assert paired_physical_protocol is not None
        assert direct_family_pilot_protocol is not None
        assert direct_family_predictor_policy is not None
        assert current_query_profile_protocol is not None
        prepared_paired_physical_schedule = (
            compile_m15_paired_physical_comparison_schedule(
                workload=selected_direct_semantic_workload,
                protocol=paired_physical_protocol,
                family_protocol=direct_family_pilot_protocol,
                predictor_policy=direct_family_predictor_policy,
                profile_protocol=current_query_profile_protocol,
            )
        )
    elif workload_mode == "current_query_profile_baseline":
        if current_query_profile_protocol is None or any(
            value is None
            for value in (
                direct_semantic_workload,
                semantic_base_bundle,
                semantic_catalog,
                predicate_mapping,
            )
        ):
            raise ValueError(
                "current_query_profile_baseline requires a direct workload, "
                "base bundle, semantic catalog, predicate mapping, and "
                "profile protocol"
            )
        if selected_direct_semantic_workload is None:
            raise ValueError(
                "current-query profile workload inputs could not be verified"
            )
        if any(
            value is not None
            for value in (
                semantic_overlay,
                predicate_overlay,
                direct_frontier_estimates,
                selected_bundle,
                selected_parameterized_bundle,
                direct_family_pilot_protocol,
                direct_family_predictor_policy,
            )
        ):
            raise ValueError(
                "current_query_profile_baseline does not accept overlays, "
                "frontier estimates, predictor inputs, or another workload "
                "bundle"
            )
        prepared_current_query_profile_schedule = (
            compile_m15_current_query_profile_baseline_schedule(
                workload=selected_direct_semantic_workload,
                protocol=current_query_profile_protocol,
            )
        )
    elif workload_mode == "direct_family_pilot":
        if any(value is None for value in direct_family_values) or any(
            value is None
            for value in (
                semantic_base_bundle,
                semantic_catalog,
                predicate_mapping,
            )
        ):
            raise ValueError(
                "direct_family_pilot requires a direct workload, base bundle, "
                "semantic catalog, predicate mapping, pilot protocol, and "
                "predictor policy"
            )
        if selected_direct_semantic_workload is None:
            raise ValueError("direct family workload inputs could not be verified")
        if any(
            value is not None
            for value in (
                semantic_overlay,
                predicate_overlay,
                direct_frontier_estimates,
                selected_bundle,
                selected_parameterized_bundle,
            )
        ):
            raise ValueError(
                "direct_family_pilot does not accept overlays, frontier "
                "estimates, or another workload bundle"
            )
        assert selected_direct_semantic_workload is not None
        assert direct_family_pilot_protocol is not None
        assert direct_family_predictor_policy is not None
        prepared_direct_family_schedule = compile_m15_direct_family_pilot_schedule(
            workload=selected_direct_semantic_workload,
            protocol=direct_family_pilot_protocol,
            predictor_policy=direct_family_predictor_policy,
        )
    elif workload_mode == "semantic_risk_relaxation":
        if any(
            value is None
            for value in (
                semantic_overlay,
                semantic_base_bundle,
                semantic_catalog,
            )
        ):
            raise ValueError(
                "semantic_risk_relaxation requires an overlay, base bundle, "
                "and semantic catalog"
            )
        if (
            predicate_overlay is not None
            or predicate_mapping is not None
            or direct_frontier_estimates is not None
        ):
            raise ValueError(
                "semantic_risk_relaxation does not accept predicate inputs"
            )
        if selected_semantic_overlay is None:
            raise ValueError("semantic overlay inputs could not be verified")
        if selected_bundle is not None or selected_parameterized_bundle is not None:
            raise ValueError(
                "semantic_risk_relaxation does not accept another workload bundle"
            )
    elif workload_mode == "semantic_predicate_relaxation":
        if any(
            value is None
            for value in (
                predicate_overlay,
                semantic_base_bundle,
                semantic_catalog,
                predicate_mapping,
            )
        ):
            raise ValueError(
                "semantic_predicate_relaxation requires a predicate overlay, "
                "base bundle, semantic catalog, and predicate mapping"
            )
        if semantic_overlay is not None:
            raise ValueError(
                "semantic_predicate_relaxation does not accept a risk overlay"
            )
        if selected_predicate_overlay is None:
            raise ValueError("predicate overlay inputs could not be verified")
        if selected_bundle is not None or selected_parameterized_bundle is not None:
            raise ValueError(
                "semantic_predicate_relaxation does not accept another "
                "workload bundle"
            )
        if direct_frontier_estimates is not None:
            raise ValueError(
                "semantic_predicate_relaxation does not accept frontier estimates"
            )
    elif workload_mode == "semantic_direct_frontier":
        if any(
            value is None
            for value in (
                predicate_overlay,
                semantic_base_bundle,
                semantic_catalog,
                predicate_mapping,
                direct_frontier_estimates,
            )
        ):
            raise ValueError(
                "semantic_direct_frontier requires a predicate overlay, base "
                "bundle, semantic catalog, predicate mapping, and estimates"
            )
        if semantic_overlay is not None:
            raise ValueError(
                "semantic_direct_frontier does not accept a risk overlay"
            )
        if selected_predicate_overlay is None:
            raise ValueError("direct frontier predicate inputs could not be verified")
        if selected_direct_frontier_estimates is None:
            raise ValueError("direct frontier estimates could not be verified")
        if selected_bundle is not None or selected_parameterized_bundle is not None:
            raise ValueError(
                "semantic_direct_frontier does not accept another workload bundle"
            )
        assert selected_semantic_base is not None
        assert selected_semantic_catalog is not None
        assert selected_predicate_mapping is not None
        prepared_direct_frontier = prepare_m15_direct_semantic_frontier(
            predicate_overlay=selected_predicate_overlay,
            base_bundle=selected_semantic_base,
            catalog=selected_semantic_catalog,
            mapping=selected_predicate_mapping,
            estimate_source=direct_frontier_estimates,
        )
    elif any(
        value is not None
        for value in (
            semantic_overlay,
            semantic_base_bundle,
            semantic_catalog,
            predicate_overlay,
            predicate_mapping,
            direct_frontier_estimates,
        )
    ):
        raise ValueError(
            "semantic inputs are accepted only in a semantic relaxation mode"
        )
    campaign_values = (
        campaign_config,
        campaign_session_id,
        expected_campaign_spec_sha256,
        expected_schedule_sha256,
    )
    if workload_mode == "scaled_campaign_session":
        if any(value is None for value in campaign_values):
            raise ValueError(
                "scaled_campaign_session requires config, session, spec hash, "
                "and schedule hash"
            )
        assert selected_bundle is not None
        prepare_m15_live_campaign_session(
            campaign_config=campaign_config,
            session_id=str(campaign_session_id),
            expected_campaign_spec_sha256=str(expected_campaign_spec_sha256),
            expected_schedule_sha256=str(expected_schedule_sha256),
            workload_bundle=selected_bundle,
            repo_root=root,
        )
    elif any(value is not None for value in campaign_values):
        raise ValueError(
            "campaign session inputs are accepted only in scaled_campaign_session"
        )
    query_bound_values = (
        query_bound_registry,
        query_bound_session_id,
        expected_registry_spec_sha256,
        expected_query_bound_schedule_sha256,
    )
    if workload_mode == "scaled_query_bound_session":
        if any(value is None for value in query_bound_values):
            raise ValueError(
                "scaled_query_bound_session requires registry, session, registry "
                "hash, and query-bound schedule hash"
            )
        assert selected_bundle is not None
        prepare_m15_live_query_bound_session(
            query_bound_registry=query_bound_registry,
            session_id=str(query_bound_session_id),
            expected_registry_spec_sha256=str(expected_registry_spec_sha256),
            expected_query_bound_schedule_sha256=str(
                expected_query_bound_schedule_sha256
            ),
            workload_bundle=selected_bundle,
            repo_root=root,
        )
    elif any(value is not None for value in query_bound_values):
        raise ValueError(
            "query-bound session inputs are accepted only in "
            "scaled_query_bound_session"
        )
    run_schema = {
        "vertical_slice": SERVICE_RUN_SCHEMA_VERSION,
        "adaptive": ADAPTIVE_SERVICE_RUN_SCHEMA_VERSION,
        "scaled_adaptive": SCALED_ADAPTIVE_SERVICE_RUN_SCHEMA_VERSION,
        "scaled_method_matrix": METHOD_MATRIX_SERVICE_RUN_SCHEMA_VERSION,
        "scaled_campaign_session": CAMPAIGN_SESSION_SERVICE_RUN_SCHEMA_VERSION,
        "scaled_query_bound_session": (
            QUERY_BOUND_SESSION_SERVICE_RUN_SCHEMA_VERSION
        ),
        "parameterized_stream": PARAMETERIZED_STREAM_SERVICE_RUN_SCHEMA_VERSION,
        "parameterized_family_transfer": (
            FAMILY_TRANSFER_SERVICE_RUN_SCHEMA_VERSION
        ),
        "semantic_risk_relaxation": (
            SEMANTIC_RELAXATION_SERVICE_RUN_SCHEMA_VERSION
        ),
        "semantic_predicate_relaxation": (
            PREDICATE_RELAXATION_SERVICE_RUN_SCHEMA_VERSION
        ),
        "semantic_direct_frontier": (
            DIRECT_SEMANTIC_FRONTIER_SERVICE_RUN_SCHEMA_VERSION
        ),
        "direct_family_pilot": DIRECT_FAMILY_PILOT_SERVICE_RUN_SCHEMA_VERSION,
        "current_query_profile_baseline": (
            CURRENT_QUERY_PROFILE_SERVICE_RUN_SCHEMA_VERSION
        ),
        "paired_physical_comparison": PAIRED_PHYSICAL_SERVICE_RUN_SCHEMA_VERSION,
        "resolution_execution_bridge": (
            RESOLUTION_EXECUTION_BRIDGE_SERVICE_RUN_SCHEMA_VERSION
        ),
        "selected_interpretation_session": (
            SELECTED_INTERPRETATION_SESSION_SERVICE_RUN_SCHEMA_VERSION
        ),
        "finbench_correctness": FINBENCH_CORRECTNESS_SERVICE_RUN_SCHEMA_VERSION,
    }[workload_mode]
    output = Path(output_root).resolve()
    run_root = output / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    status_path = run_root / "run_status.json"
    manifest_path = run_root / "run_manifest.json"
    started_at = _now()
    _write_json(status_path, {"status": "running", "started_at": started_at})

    direct_frontier_preflight: dict[str, Any] | None = None
    if prepared_direct_frontier is not None:
        preflight_root = run_root / "direct-frontier-preflight"
        preflight_root.mkdir()
        preflight_artifacts = prepared_direct_frontier.artifacts()
        for filename, payload in preflight_artifacts.items():
            _write_json(preflight_root / filename, payload)
        candidate_payload = preflight_artifacts["candidate_set.json"]
        estimate_payload = preflight_artifacts["estimate_source.json"]
        snapshot_payload = preflight_artifacts["estimate_snapshot.json"]
        frontier_payload = preflight_artifacts["semantic_frontier.json"]
        direct_frontier_preflight = {
            "schema_version": DIRECT_SEMANTIC_FRONTIER_PREFLIGHT_SCHEMA_VERSION,
            "sealed_before_service_start": True,
            "answer_oracle_fields": snapshot_payload["answer_oracle_fields"],
            "post_execution_measurements_used": snapshot_payload[
                "post_execution_measurements_used"
            ],
            "estimate_source_sha256": estimate_payload[
                "estimate_source_sha256"
            ],
            "candidate_set_sha256": candidate_payload["candidate_set_sha256"],
            "estimate_snapshot_sha256": snapshot_payload[
                "estimate_snapshot_sha256"
            ],
            "frontier_sha256": frontier_payload["frontier_sha256"],
            "backend_calls_before_seal": 0,
            "automatic_retries": 0,
            "paper_result": False,
        }
        _write_json(
            preflight_root / "preflight_manifest.json",
            direct_frontier_preflight,
        )

    direct_family_preflight: dict[str, Any] | None = None
    if prepared_direct_family_schedule is not None:
        preflight_root = run_root / "direct-family-pilot-preflight"
        preflight_root.mkdir()
        schedule_payload = prepared_direct_family_schedule.to_dict()
        _write_json(preflight_root / "pilot_schedule.json", schedule_payload)
        direct_family_preflight = {
            "schema_version": DIRECT_FAMILY_PILOT_PREFLIGHT_SCHEMA_VERSION,
            "sealed_before_service_start": True,
            "schedule_sha256": prepared_direct_family_schedule.schedule_hash,
            "online_cardinality": schedule_payload["selection_boundary"][
                "online_cardinality"
            ],
            "expected_counts": schedule_payload["counts"],
            "backend_calls_before_seal": 0,
            "automatic_retries": 0,
            "paper_result": False,
        }
        _write_json(
            preflight_root / "preflight_manifest.json",
            direct_family_preflight,
        )

    current_query_profile_preflight: dict[str, Any] | None = None
    if prepared_current_query_profile_schedule is not None:
        preflight_root = run_root / "current-query-profile-preflight"
        preflight_root.mkdir()
        schedule_payload = prepared_current_query_profile_schedule.to_dict()
        _write_json(preflight_root / "profile_schedule.json", schedule_payload)
        current_query_profile_preflight = {
            "schema_version": CURRENT_QUERY_PROFILE_PREFLIGHT_SCHEMA_VERSION,
            "sealed_before_service_start": True,
            "schedule_sha256": (
                prepared_current_query_profile_schedule.schedule_hash
            ),
            "expected_counts": schedule_payload["counts"],
            "backend_calls_before_seal": 0,
            "answer_oracle_opened_before_seal": False,
            "automatic_retries": 0,
            "paper_result": False,
        }
        _write_json(
            preflight_root / "preflight_manifest.json",
            current_query_profile_preflight,
        )

    paired_physical_preflight: dict[str, Any] | None = None
    if prepared_paired_physical_schedule is not None:
        preflight_root = run_root / "paired-physical-preflight"
        preflight_root.mkdir()
        schedule_payload = prepared_paired_physical_schedule.to_dict()
        _write_json(preflight_root / "paired_schedule.json", schedule_payload)
        paired_physical_preflight = {
            "schema_version": PAIRED_PHYSICAL_PREFLIGHT_SCHEMA_VERSION,
            "sealed_before_service_start": True,
            "schedule_sha256": prepared_paired_physical_schedule.schedule_hash,
            "expected_counts": schedule_payload["counts"],
            "backend_calls_before_seal": 0,
            "answer_oracle_opened_before_seal": False,
            "automatic_retries": 0,
            "paper_result": False,
        }
        _write_json(
            preflight_root / "preflight_manifest.json",
            paired_physical_preflight,
        )

    resolution_bridge_preflight: dict[str, Any] | None = None
    if workload_mode == "resolution_execution_bridge":
        assert resolution_run is not None
        assert resolution_bridge_spec is not None
        preflight_root = run_root / "resolution-execution-bridge-preflight"
        preflight_root.mkdir()
        prepared_resolution_bridge = prepare_m15_resolution_execution_bridge(
            resolution_run_path=resolution_run,
            bridge_spec_path=resolution_bridge_spec,
            workload_destination=preflight_root / "workload",
            repo_root=root,
        )
        bridge_payload = prepared_resolution_bridge.bridge.to_dict()
        _write_json(preflight_root / "bridge_plan.json", bridge_payload)
        resolution_bridge_preflight = {
            "schema_version": (
                RESOLUTION_EXECUTION_BRIDGE_PREFLIGHT_SCHEMA_VERSION
            ),
            "sealed_before_service_start": True,
            "bridge_sealed_before_workload_generation": True,
            "bridge_plan_sha256": bridge_payload["bridge_plan_sha256"],
            "resolution_run_sha256": _sha256_file(Path(resolution_run)),
            "bridge_spec_sha256": _sha256_file(Path(resolution_bridge_spec)),
            "workload_manifest_sha256": _sha256_file(
                prepared_resolution_bridge.workload.root / "manifest.json"
            ),
            "expected_counts": bridge_payload["counts"],
            "backend_calls_before_seal": 0,
            "answer_oracle_opened_before_seal": False,
            "automatic_retries": 0,
            "paper_result": False,
        }
        resolution_bridge_preflight["preflight_sha256"] = content_hash(
            resolution_bridge_preflight
        )
        _write_json(
            preflight_root / "preflight_manifest.json",
            resolution_bridge_preflight,
        )

    selected_session_preflight: dict[str, Any] | None = None
    if workload_mode == "selected_interpretation_session":
        assert resolution_run is not None
        assert resolution_bridge_spec is not None
        assert selected_session_training_memory is not None
        assert selected_session_expected_memory_sha256 is not None
        assert selected_session_predictor_policy is not None
        assert selected_session_interpretation_policy is not None
        assert selected_session_ontology is not None
        assert selected_session_relaxation_policy is not None
        assert selected_session_transport_policy is not None
        assert selected_session_live_policy is not None
        assert selected_session_id is not None
        assert selected_session_structural_candidate_id is not None
        assert selected_session_predicate_candidate_id is not None
        assert selected_session_authority_source_id is not None
        preflight_root = run_root / "selected-interpretation-session-preflight"
        preflight_root.mkdir()
        prepared_selected_session = prepare_m15_selected_interpretation_session(
            resolution_run_path=resolution_run,
            bridge_spec_path=resolution_bridge_spec,
            workload_destination=preflight_root / "workload",
            training_memory_path=selected_session_training_memory,
            expected_training_memory_sha256=(
                selected_session_expected_memory_sha256
            ),
            predictor_policy_path=selected_session_predictor_policy,
            interpretation_policy_path=selected_session_interpretation_policy,
            ontology_path=selected_session_ontology,
            relaxation_policy_path=selected_session_relaxation_policy,
            transport_policy_path=selected_session_transport_policy,
            live_policy_path=selected_session_live_policy,
            session_id=selected_session_id,
            structural_candidate_id=selected_session_structural_candidate_id,
            predicate_candidate_id=selected_session_predicate_candidate_id,
            authority_source_id=selected_session_authority_source_id,
            repo_root=root,
        )
        selected_session_preflight = build_m15_selected_session_preflight(
            prepared_selected_session
        )
        session_payload = prepared_selected_session.clarification_session.to_dict()
        _write_json(preflight_root / "clarification_session.json", session_payload)
        _write_json(
            preflight_root / "authority_events.json",
            session_payload["authority_events"],
        )
        _write_json(
            preflight_root / "execution_handoff.json",
            session_payload["execution_handoff"],
        )
        _write_json(
            preflight_root / "preflight_manifest.json",
            selected_session_preflight,
        )

    plan: NativeServicePlan | None = None
    health: list[HealthObservation] = []
    shutdown: list[ShutdownObservation] = []
    running: list[RunningService] = []
    error: str | None = None
    try:
        java = inspect_java_runtime(
            java_command,
            required_major=required_java_major,
        )
        with LoopbackPortReservations.acquire(3) as ports:
            plan = build_native_service_plan(
                runtime_root=runtime_root,
                staging_manifest=staging_manifest,
                evidence_root=run_root,
                filesystem_type=filesystem_type,
                allocation_id=allocation_id,
                java=java,
                neo4j_http_port=ports.ports[0],
                neo4j_bolt_port=ports.ports[1],
                fuseki_port=ports.ports[2],
                neo4j_resource_profile_id=neo4j_resource_profile_id,
            )
            ports.release(0)
            ports.release(1)
            neo4j = start_service(plan.services[0])
            running.append(neo4j)
            observation = wait_for_service_health(neo4j)
            health.append(observation)
            if not observation.success:
                raise RuntimeError(f"Neo4j readiness failed: {observation.last_error}")

            ports.release(2)
            fuseki = start_service(plan.services[1])
            running.append(fuseki)
            observation = wait_for_service_health(fuseki)
            health.append(observation)
            if not observation.success:
                raise RuntimeError(f"Fuseki readiness failed: {observation.last_error}")

            fixture_args = (
                plan,
                run_root,
                root,
                workload_mode,
                selected_bundle,
                campaign_config,
                campaign_session_id,
                expected_campaign_spec_sha256,
                expected_schedule_sha256,
                query_bound_registry,
                query_bound_session_id,
                expected_registry_spec_sha256,
                expected_query_bound_schedule_sha256,
                selected_parameterized_bundle,
                selected_semantic_overlay,
                selected_semantic_base,
                selected_semantic_catalog,
                selected_predicate_overlay,
                selected_predicate_mapping,
                direct_frontier_estimates,
                prepared_direct_frontier,
                selected_direct_semantic_workload,
                direct_family_pilot_protocol,
                direct_family_predictor_policy,
                paired_physical_protocol,
                current_query_profile_protocol,
            )
            if workload_mode == "finbench_correctness":
                _run_fixture_and_query(
                    *fixture_args,
                    finbench_workload=finbench_workload,
                    finbench_partition=finbench_partition,
                    finbench_query_ids=finbench_query_ids,
                )
            elif workload_mode in {
                "resolution_execution_bridge",
                "selected_interpretation_session",
            }:
                _run_fixture_and_query(
                    *fixture_args,
                    resolution_run=resolution_run,
                    resolution_bridge_spec=resolution_bridge_spec,
                    prepared_resolution_bridge=prepared_resolution_bridge,
                    prepared_selected_session=prepared_selected_session,
                )
            else:
                _run_fixture_and_query(*fixture_args)
    except Exception as exc:  # Persist the first lifecycle failure; never restart.
        error = str(exc)
    finally:
        for service in reversed(running):
            shutdown.append(stop_service(service))
        logs = run_root / "service_logs"
        logs.mkdir(exist_ok=True)
        if plan is not None:
            for service in plan.services:
                if service.log_path.is_file():
                    shutil.copyfile(service.log_path, logs / service.log_path.name)

    if any(not item.success for item in shutdown):
        shutdown_error = "one or more job-owned service processes did not stop cleanly"
        error = error or shutdown_error
    ended_at = _now()
    success = error is None
    _write_json(
        status_path,
        {
            "schema_version": run_schema,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    _write_json(
        run_root / "service_health.json",
        [item.to_dict() for item in health],
    )
    _write_json(
        run_root / "service_shutdown.json",
        [item.to_dict() for item in shutdown],
    )
    _write_json(
        manifest_path,
        {
            "schema_version": run_schema,
            "run_id": run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
            "allocation_id": allocation_id,
            "runtime_root": str(Path(runtime_root).resolve()),
            "runtime_cleanup_owner": "slurm_job_wrapper",
            "workload_mode": workload_mode,
            "workload_bundle": (
                dict(selected_bundle.manifest) if selected_bundle is not None else None
            ),
            "parameterized_workload_bundle": (
                dict(selected_parameterized_bundle.manifest)
                if selected_parameterized_bundle is not None
                else None
            ),
            "semantic_base_workload_bundle": (
                dict(selected_semantic_base.manifest)
                if selected_semantic_base is not None
                else None
            ),
            "semantic_overlay": (
                dict(selected_semantic_overlay.manifest)
                if selected_semantic_overlay is not None
                else None
            ),
            "predicate_overlay": (
                dict(selected_predicate_overlay.manifest)
                if selected_predicate_overlay is not None
                else None
            ),
            "predicate_mapping": (
                selected_predicate_mapping.to_dict()
                if selected_predicate_mapping is not None
                else None
            ),
            "direct_frontier_estimates": (
                selected_direct_frontier_estimates.to_dict()
                if selected_direct_frontier_estimates is not None
                else None
            ),
            "direct_frontier_preflight": direct_frontier_preflight,
            "direct_semantic_workload": (
                dict(selected_direct_semantic_workload.manifest)
                if selected_direct_semantic_workload is not None
                else None
            ),
            "direct_family_pilot": (
                {
                    "protocol": str(direct_family_pilot_protocol),
                    "predictor_policy": str(direct_family_predictor_policy),
                }
                if workload_mode == "direct_family_pilot"
                else None
            ),
            "direct_family_pilot_preflight": direct_family_preflight,
            "current_query_profile_baseline": (
                {"protocol": str(current_query_profile_protocol)}
                if workload_mode == "current_query_profile_baseline"
                else None
            ),
            "current_query_profile_preflight": (
                current_query_profile_preflight
            ),
            "paired_physical_comparison": (
                {
                    "protocol": str(paired_physical_protocol),
                    "family_protocol": str(direct_family_pilot_protocol),
                    "predictor_policy": str(direct_family_predictor_policy),
                    "profile_protocol": str(current_query_profile_protocol),
                }
                if workload_mode == "paired_physical_comparison"
                else None
            ),
            "paired_physical_preflight": paired_physical_preflight,
            "resolution_execution_bridge": (
                {
                    "resolution_run": str(resolution_run),
                    "bridge_spec": str(resolution_bridge_spec),
                }
                if workload_mode == "resolution_execution_bridge"
                else None
            ),
            "resolution_execution_bridge_preflight": (
                resolution_bridge_preflight
            ),
            "selected_interpretation_session": (
                {
                    "resolution_run": str(resolution_run),
                    "bridge_spec": str(resolution_bridge_spec),
                    "training_memory": str(selected_session_training_memory),
                    "expected_training_memory_sha256": (
                        selected_session_expected_memory_sha256
                    ),
                    "predictor_policy": str(selected_session_predictor_policy),
                    "interpretation_policy": str(
                        selected_session_interpretation_policy
                    ),
                    "ontology": str(selected_session_ontology),
                    "relaxation_policy": str(selected_session_relaxation_policy),
                    "transport_policy": str(selected_session_transport_policy),
                    "live_policy": str(selected_session_live_policy),
                    "session_id": selected_session_id,
                    "structural_candidate_id": (
                        selected_session_structural_candidate_id
                    ),
                    "predicate_candidate_id": (
                        selected_session_predicate_candidate_id
                    ),
                    "authority_source_id": selected_session_authority_source_id,
                }
                if workload_mode == "selected_interpretation_session"
                else None
            ),
            "selected_interpretation_session_preflight": (
                selected_session_preflight
            ),
            "finbench_correctness": (
                {
                    "workload": str(finbench_workload),
                    "partition": str(finbench_partition),
                    "query_ids": list(finbench_query_ids)
                    if finbench_query_ids is not None
                    else None,
                }
                if workload_mode == "finbench_correctness"
                else None
            ),
            "campaign_session": (
                {
                    "campaign_config": str(campaign_config),
                    "session_id": campaign_session_id,
                    "expected_campaign_spec_sha256": expected_campaign_spec_sha256,
                    "expected_schedule_sha256": expected_schedule_sha256,
                }
                if workload_mode == "scaled_campaign_session"
                else None
            ),
            "query_bound_session": (
                {
                    "query_bound_registry": str(query_bound_registry),
                    "session_id": query_bound_session_id,
                    "expected_registry_spec_sha256": (
                        expected_registry_spec_sha256
                    ),
                    "expected_query_bound_schedule_sha256": (
                        expected_query_bound_schedule_sha256
                    ),
                }
                if workload_mode == "scaled_query_bound_session"
                else None
            ),
            "service_plan": plan.to_dict() if plan is not None else None,
            "health": [item.to_dict() for item in health],
            "shutdown": [item.to_dict() for item in shutdown],
            "automatic_retries": 0,
            "service_restarts": 0,
            "public_ports": False,
            "credentials_persisted": False,
            "artifacts": sorted(path.name for path in run_root.iterdir()),
        },
    )
    return NativeServiceRunRecord(
        run_id=run_id,
        run_root=run_root,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        error=error,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--staging-manifest", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-id", default="native-service-run")
    parser.add_argument("--filesystem-type", required=True)
    parser.add_argument("--allocation-id", required=True)
    parser.add_argument("--java-command", default="java")
    parser.add_argument(
        "--neo4j-resource-profile",
        choices=sorted(NEO4J_RESOURCE_PROFILES),
        default="development",
    )
    parser.add_argument("--repo-root")
    parser.add_argument(
        "--workload-mode",
        choices=sorted(WORKLOAD_MODES),
        default="vertical_slice",
    )
    parser.add_argument("--workload-bundle")
    parser.add_argument("--parameterized-workload-bundle")
    parser.add_argument("--semantic-overlay")
    parser.add_argument("--semantic-base-bundle")
    parser.add_argument("--semantic-catalog")
    parser.add_argument("--predicate-overlay")
    parser.add_argument("--predicate-mapping")
    parser.add_argument("--direct-frontier-estimates")
    parser.add_argument("--direct-semantic-workload")
    parser.add_argument("--direct-family-pilot-protocol")
    parser.add_argument("--direct-family-predictor-policy")
    parser.add_argument("--current-query-profile-protocol")
    parser.add_argument("--paired-physical-protocol")
    parser.add_argument("--resolution-run")
    parser.add_argument("--resolution-bridge-spec")
    parser.add_argument("--selected-session-training-memory")
    parser.add_argument("--selected-session-expected-memory-sha256")
    parser.add_argument("--selected-session-predictor-policy")
    parser.add_argument("--selected-session-interpretation-policy")
    parser.add_argument("--selected-session-ontology")
    parser.add_argument("--selected-session-relaxation-policy")
    parser.add_argument("--selected-session-transport-policy")
    parser.add_argument("--selected-session-live-policy")
    parser.add_argument("--selected-session-id")
    parser.add_argument("--selected-session-structural-candidate-id")
    parser.add_argument("--selected-session-predicate-candidate-id")
    parser.add_argument("--selected-session-authority-source-id")
    parser.add_argument("--finbench-workload")
    parser.add_argument("--finbench-partition")
    parser.add_argument("--finbench-query-id", action="append", dest="finbench_query_ids")
    parser.add_argument("--campaign-config")
    parser.add_argument("--campaign-session-id")
    parser.add_argument("--expected-campaign-spec-sha256")
    parser.add_argument("--expected-schedule-sha256")
    parser.add_argument("--query-bound-registry")
    parser.add_argument("--query-bound-session-id")
    parser.add_argument("--expected-registry-spec-sha256")
    parser.add_argument("--expected-query-bound-schedule-sha256")
    args = parser.parse_args(argv)
    if os.environ.get("XGAP_RUN_M15_NATIVE_SERVICES") != "1":
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "error": (
                        "set XGAP_RUN_M15_NATIVE_SERVICES=1 inside the dedicated "
                        "M15 Slurm allocation"
                    ),
                },
                sort_keys=True,
            )
        )
        return 3
    try:
        record = run_m15_native_services(
            runtime_root=args.runtime_root,
            staging_manifest=args.staging_manifest,
            output_root=args.output_root,
            run_id=args.run_id,
            filesystem_type=args.filesystem_type,
            allocation_id=args.allocation_id,
            java_command=args.java_command,
            neo4j_resource_profile_id=args.neo4j_resource_profile,
            repo_root=args.repo_root,
            workload_mode=args.workload_mode,
            workload_bundle=args.workload_bundle,
            parameterized_workload_bundle=args.parameterized_workload_bundle,
            semantic_overlay=args.semantic_overlay,
            semantic_base_bundle=args.semantic_base_bundle,
            semantic_catalog=args.semantic_catalog,
            predicate_overlay=args.predicate_overlay,
            predicate_mapping=args.predicate_mapping,
            direct_frontier_estimates=args.direct_frontier_estimates,
            direct_semantic_workload=args.direct_semantic_workload,
            direct_family_pilot_protocol=args.direct_family_pilot_protocol,
            direct_family_predictor_policy=(
                args.direct_family_predictor_policy
            ),
            current_query_profile_protocol=(
                args.current_query_profile_protocol
            ),
            paired_physical_protocol=args.paired_physical_protocol,
            resolution_run=args.resolution_run,
            resolution_bridge_spec=args.resolution_bridge_spec,
            selected_session_training_memory=(
                args.selected_session_training_memory
            ),
            selected_session_expected_memory_sha256=(
                args.selected_session_expected_memory_sha256
            ),
            selected_session_predictor_policy=(
                args.selected_session_predictor_policy
            ),
            selected_session_interpretation_policy=(
                args.selected_session_interpretation_policy
            ),
            selected_session_ontology=args.selected_session_ontology,
            selected_session_relaxation_policy=(
                args.selected_session_relaxation_policy
            ),
            selected_session_transport_policy=(
                args.selected_session_transport_policy
            ),
            selected_session_live_policy=args.selected_session_live_policy,
            selected_session_id=args.selected_session_id,
            selected_session_structural_candidate_id=(
                args.selected_session_structural_candidate_id
            ),
            selected_session_predicate_candidate_id=(
                args.selected_session_predicate_candidate_id
            ),
            selected_session_authority_source_id=(
                args.selected_session_authority_source_id
            ),
            finbench_workload=args.finbench_workload,
            finbench_partition=args.finbench_partition,
            finbench_query_ids=args.finbench_query_ids,
            campaign_config=args.campaign_config,
            campaign_session_id=args.campaign_session_id,
            expected_campaign_spec_sha256=args.expected_campaign_spec_sha256,
            expected_schedule_sha256=args.expected_schedule_sha256,
            query_bound_registry=args.query_bound_registry,
            query_bound_session_id=args.query_bound_session_id,
            expected_registry_spec_sha256=args.expected_registry_spec_sha256,
            expected_query_bound_schedule_sha256=(
                args.expected_query_bound_schedule_sha256
            ),
        )
    except (FileExistsError, ValueError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps(record.to_dict(), indent=2, sort_keys=True))
    return 0 if record.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
