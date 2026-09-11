#!/usr/bin/env python3
"""Collect existing frozen FinBench inputs; never download, rebuild, or submit.

Run with Python 3.10+ on Pioneer. Only the two known run directories are read.
The sealed oracle is copied and hashed as bytes, never parsed or used to select
instances. The output is a fresh directory containing a tar.gz and a receipt;
input failures leave a diagnostic receipt without a completed archive.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tarfile
import time


DEFAULT_REPO_ROOT = "/home/hxc859/XGAP-m15-465e2e2"
FREEZE = "runs/cwru-m15-finbench-confirmatory-freeze-3793747"
POPULATION = "runs/cwru-m15-finbench-confirmatory-population-3793727"
WORKLOAD = FREEZE + "/confirmatory-workload"
WORKLOAD_SHA256 = "63a8ef36bc7576033db93caa2aa486409bc90ecfc699385b61e7d02be4320a5f"
SCHEDULE_SHA256 = "27b7c1391fb507ec83bd84fcf559e40f0572100190205052f0f26243cdac2298"
MAX_BYTES = 64 * 1024 * 1024
OUTPUTS = {"public_instances.json", "sealed_oracles.json", "family_contracts.json"}
TEMPLATES = {f"f{family}_{name}" for family in (1, 2, 3) for name in (
    "neo4j_full.cypher.tmpl", "neo4j_bound.cypher.tmpl", "fuseki_control.rq.tmpl")}
FREEZE_FILES = ("run_manifest.json", "run_status.json", "population_approval.json",
                "author_selection_snapshot.json", "measurement_schedule.json")
POPULATION_FILES = ("population_registry.json", "run_manifest.json", "run_status.json")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value, *, ascii_only: bool) -> str:
    return _sha(json.dumps(value, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=ascii_only, allow_nan=False).encode("utf-8"))


def _object(data: bytes, name: str) -> dict:
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {name}")
    return value


def _sealed(value: dict, field: str, *, ascii_only: bool, expected: str | None = None) -> str:
    claimed = value.get(field)
    actual = _canonical({k: v for k, v in value.items() if k != field}, ascii_only=ascii_only)
    if claimed != actual or (expected is not None and actual != expected):
        raise ValueError(f"Frozen {field} mismatch: expected={expected}, claimed={claimed}, actual={actual}")
    return actual


class Inputs:
    """A bounded cache of verified original bytes; tar never reopens the source."""

    def __init__(self, root: Path):
        if root.is_symlink() or not root.is_dir():
            raise ValueError(f"Repository root is missing or symbolic: {root}")
        self.root = root.resolve(strict=True)
        self.files: dict[str, bytes] = {}
        self.total = 0

    def read(self, relative: str) -> bytes:
        if relative in self.files:
            return self.files[relative]
        name = PurePosixPath(relative)
        if name.is_absolute() or ".." in name.parts or not name.parts:
            raise ValueError(f"Unsafe input path: {relative}")
        path = self.root
        for part in name.parts:
            path = path / part
            if path.is_symlink():
                raise ValueError(f"Symbolic input path is forbidden: {path}")
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"Input must be a regular file: {path}")
        if before.st_size > MAX_BYTES - self.total:
            raise ValueError(f"Input exceeds the aggregate 64 MiB budget: {relative}")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if (not stat.S_ISREG(opened.st_mode)
                    or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)):
                raise ValueError(f"Input changed before reading: {relative}")
            data = handle.read(MAX_BYTES - self.total + 1)
            after = os.fstat(handle.fileno())
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if (signature(before) != signature(after) or len(data) != before.st_size
                or len(data) > MAX_BYTES - self.total
                or not path.resolve(strict=True).is_relative_to(self.root)):
            raise ValueError(f"Input changed or exceeded its boundary while reading: {relative}")
        self.files[relative] = data
        self.total += len(data)
        return data

    def object(self, relative: str) -> dict:
        return _object(self.read(relative), relative)

    def verify(self, relative: str, record: dict) -> None:
        data = self.read(relative)
        if (not isinstance(record, dict) or type(record.get("size_bytes")) is not int
                or record["size_bytes"] != len(data) or record.get("sha256") != _sha(data)):
            raise ValueError(f"Frozen file size/hash mismatch: {relative}")


def _validated_inputs(inputs: Inputs) -> dict:
    manifest = inputs.object(WORKLOAD + "/workload_manifest.json")
    _sealed(manifest, "workload_sha256", ascii_only=False, expected=WORKLOAD_SHA256)
    if manifest.get("paper_result") is not False or manifest.get("instance_count") != 48:
        raise ValueError("Expected the frozen 48-instance workpack boundary")
    outputs, templates = manifest.get("output_files"), manifest.get("template_files")
    if not isinstance(outputs, dict) or set(outputs) != OUTPUTS:
        raise ValueError("Workload output inventory differs from the original public loader")
    if not isinstance(templates, dict) or set(templates) != TEMPLATES:
        raise ValueError("Workload must contain exactly the original nine templates")
    for name, record in outputs.items():
        inputs.verify(WORKLOAD + "/" + name, record)
    for name, record in templates.items():
        inputs.verify(WORKLOAD + "/templates/" + name, record)
    for name in FREEZE_FILES:
        inputs.read(FREEZE + "/" + name)
    for name in POPULATION_FILES:
        inputs.read(POPULATION + "/" + name)

    registry = inputs.object(POPULATION + "/population_registry.json")
    registry_hash = _sealed(registry, "registry_sha256", ascii_only=True,
                            expected=manifest["population_registry_sha256"])
    schedule = inputs.object(FREEZE + "/measurement_schedule.json")
    _sealed(schedule, "schedule_sha256", ascii_only=True, expected=SCHEDULE_SHA256)
    if schedule.get("workload_sha256") != WORKLOAD_SHA256:
        raise ValueError("Schedule names a different workload")
    freeze = inputs.object(FREEZE + "/run_manifest.json")
    _sealed(freeze, "manifest_sha256", ascii_only=True)
    if (freeze.get("status") != "success" or freeze.get("slurm_job_id") != "3793747"
            or freeze.get("workload_sha256") != WORKLOAD_SHA256
            or freeze.get("schedule_sha256") != SCHEDULE_SHA256
            or freeze.get("population_source", {}).get("registry_sha256") != registry_hash):
        raise ValueError("Freeze run identity disagrees with the accepted workload")
    inventory = freeze.get("artifact_files")
    if not isinstance(inventory, dict):
        raise ValueError("Freeze artifact inventory is missing")
    for name in inputs.files:
        if name.startswith(FREEZE + "/") and name not in {
                FREEZE + "/run_manifest.json", FREEZE + "/run_status.json"}:
            relative = name[len(FREEZE) + 1:]
            inputs.verify(name, inventory.get(relative))
    producer = inputs.object(POPULATION + "/run_manifest.json")
    _sealed(producer, "manifest_sha256", ascii_only=True)
    registry_bytes = inputs.files[POPULATION + "/population_registry.json"]
    if (producer.get("status") != "success" or producer.get("slurm_job_id") != "3793727"
            or producer.get("output", {}).get("registry_sha256") != registry_hash
            or producer.get("output", {}).get("registry_file_sha256") != _sha(registry_bytes)):
        raise ValueError("Population run identity disagrees with the frozen registry")
    for run, job in ((FREEZE, "3793747"), (POPULATION, "3793727")):
        status = inputs.object(run + "/run_status.json")
        if status.get("status") != "success" or status.get("slurm_job_id") != job:
            raise ValueError(f"Successful original run status is missing: {run}")
    public = inputs.object(WORKLOAD + "/public_instances.json")
    rows = public.get("instances")
    if not isinstance(rows, list) or len(rows) != 48:
        raise ValueError("The full frozen 48-instance list is required")
    ids = [item["query_id"] for item in rows]
    if (any(not isinstance(qid, str) for qid in ids) or len(set(ids)) != 48
            or set(schedule.get("query_ids", [])) != set(ids)
            or len(schedule.get("seen_family_query_ids", [])) != 32
            or len(schedule.get("cold_family_query_ids", [])) != 16):
        raise ValueError("Frozen IDs or 32-seen/16-cold denominators disagree")
    return {"workload_sha256": WORKLOAD_SHA256, "schedule_sha256": SCHEDULE_SHA256,
            "registry_sha256": registry_hash, "query_ids": ids,
            "seen_query_count": 32, "cold_query_count": 16}


def _job_status() -> list[dict]:
    commands = (("squeue", "--jobs=3804011", "--noheader", "--format=%i|%T|%M|%R"),
                ("sacct", "--jobs=3804011", "--noheader", "--parsable2",
                 "--format=JobID,State,ExitCode,Elapsed,NodeList"))
    records = []
    for command in commands:
        started = time.monotonic()
        record = {"command": list(command), "timeout_seconds": 10, "attempts": 1}
        try:
            result = subprocess.run(command, capture_output=True, timeout=10, check=False)
            record.update(success=result.returncode == 0, returncode=result.returncode)
            stdout, stderr = result.stdout, result.stderr
        except (OSError, subprocess.TimeoutExpired) as error:
            record.update(success=False, error_type=type(error).__name__, error=str(error))
            stdout, stderr = getattr(error, "stdout", None) or b"", getattr(error, "stderr", None) or b""
        record.update(stdout=stdout[:65536].decode("utf-8", errors="replace"),
                      stderr=stderr[:65536].decode("utf-8", errors="replace"),
                      output_truncated=len(stdout) > 65536 or len(stderr) > 65536,
                      elapsed_ms=(time.monotonic() - started) * 1000)
        records.append(record)
    return records


def collect(repo_root: str | Path, output_root: str | Path, *, job_status: bool = False) -> dict:
    repo = Path(repo_root).expanduser().absolute()
    output = Path(output_root).expanduser().absolute()
    if output.is_symlink() or output.exists():
        raise ValueError(f"Output must be a fresh directory: {output}")
    for source in (repo / FREEZE, repo / POPULATION):
        if output.resolve().is_relative_to(source.resolve()):
            raise ValueError("Output must be outside the original run directories")
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"schema_version": "xgap-int-workpack-collection-v1", "success": False,
        "started_at": datetime.now(timezone.utc).isoformat(), "repo_root": str(repo),
        "known_source_roots": [str(repo / FREEZE), str(repo / POPULATION)],
        "expected_workload_sha256": WORKLOAD_SHA256, "expected_schedule_sha256": SCHEDULE_SHA256,
        "maximum_bytes": MAX_BYTES, "source_mutations": 0, "automatic_retries": 0,
        "recursive_data_search": False, "oracle_content_parsed": False,
        "instances_regenerated": False, "job_status_requested": job_status,
        "files": [], "archive": None, "paper_result": False}
    inputs = None
    temporary = output / "workpack.partial.tar.gz"
    try:
        inputs = Inputs(repo)
        receipt["validated"] = _validated_inputs(inputs)
        with tarfile.open(temporary, mode="x:gz") as archive:
            for name, data in sorted(inputs.files.items()):
                member = tarfile.TarInfo(name)
                member.size, member.mode = len(data), 0o600
                archive.addfile(member, io.BytesIO(data))
        packed = temporary.read_bytes()
        if len(packed) > MAX_BYTES:
            raise ValueError("Compressed workpack exceeds the 64 MiB budget")
        destination = output / "finbench-int-workpack.tar.gz"
        temporary.rename(destination)
        receipt.update(success=True, archive={"path": destination.name,
                       "size_bytes": len(packed), "sha256": _sha(packed)})
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as error:
        receipt["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        temporary.unlink(missing_ok=True)
    if inputs is not None:
        receipt["files"] = [{"path": name, "size_bytes": len(data), "sha256": _sha(data)}
                            for name, data in sorted(inputs.files.items())]
        receipt["source_bytes"] = inputs.total
    receipt["job_status"] = _job_status() if job_status else []
    receipt["completed_at"] = datetime.now(timezone.utc).isoformat()
    with (output / "collection_receipt.json").open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=DEFAULT_REPO_ROOT,
                        help="Explicit checkout override; no automatic path search")
    parser.add_argument("--output-root", required=True, help="New destination outside original run directories")
    parser.add_argument("--job-status-3804011", action="store_true",
                        help="Also save read-only squeue/sacct output, 10 seconds each, no retries")
    args = parser.parse_args(argv)
    try:
        result = collect(args.repo_root, args.output_root, job_status=args.job_status_3804011)
    except (OSError, ValueError) as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 2
    print(json.dumps({"success": result["success"],
        "receipt": str(Path(args.output_root).expanduser().absolute() / "collection_receipt.json"),
        "archive": result["archive"],
        "job_status_success": all(item["success"] for item in result["job_status"])
            if result["job_status_requested"] else None}))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
