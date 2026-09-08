"""Read-only reconstruction audit for one confirmatory block attempt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_confirmatory_execution import (
    validate_finbench_confirmatory_block_execution_envelope,
)
from xgap.experiments.m15_live_finbench_confirmatory_block import (
    FINBENCH_CONFIRMATORY_LIVE_BLOCK_SCHEMA_VERSION,
    FINBENCH_CONFIRMATORY_RAW_MEASUREMENTS_SCHEMA_VERSION,
)


FINBENCH_CONFIRMATORY_BLOCK_AUDIT_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-block-evidence-audit-v1"
)
_CONFIRMATORY_TIMEOUT_POLICY = {
    "method_timeout_seconds": 60.0,
    "transport_timeout_seconds": 65.0,
    "neo4j": {
        "setting": "db.transaction.timeout",
        "value": "60s",
        "monitor_check_interval": "1s",
    },
    "fuseki": {
        "setting": "arq:queryTimeout",
        "value_milliseconds": 60_000,
        "configuration": "FUSEKI_BASE/config.ttl",
    },
    "timeout_is_method_outcome": True,
    "automatic_retries": 0,
}
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class FinBenchConfirmatoryBlockEvidenceCheck:
    check_id: str
    passed: bool
    expected: Any
    observed: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "passed": self.passed,
            "expected": self.expected,
            "observed": self.observed,
        }


@dataclass(frozen=True)
class FinBenchConfirmatoryBlockEvidenceAudit:
    attempt_root: Path
    expected_commit: str
    attempt_id: str
    block_attempt_sha256: str
    execution_context_sha256: str
    raw_measurements_sha256: str
    attempt_status: str
    replacement_eligible: bool
    valid_measurement_count: int
    failure_category: str | None
    checks: tuple[FinBenchConfirmatoryBlockEvidenceCheck, ...]
    run_tree_mutated: bool

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(item.check_id for item in self.checks if not item.passed)

    @property
    def success(self) -> bool:
        return not self.failed_check_ids and not self.run_tree_mutated

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "schema_version": FINBENCH_CONFIRMATORY_BLOCK_AUDIT_SCHEMA_VERSION,
            "success": self.success,
            "attempt_root": str(self.attempt_root),
            "expected_commit": self.expected_commit,
            "attempt_id": self.attempt_id,
            "block_attempt_sha256": self.block_attempt_sha256,
            "execution_context_sha256": self.execution_context_sha256,
            "raw_measurements_sha256": self.raw_measurements_sha256,
            "attempt_status": self.attempt_status,
            "replacement_eligible": self.replacement_eligible,
            "valid_measurement_count": self.valid_measurement_count,
            "failure_category": self.failure_category,
            "check_count": len(self.checks),
            "failed_check_ids": list(self.failed_check_ids),
            "checks": [item.to_dict() for item in self.checks],
            "run_tree_mutated": self.run_tree_mutated,
            "paper_result": False,
        }
        body["audit_sha256"] = content_hash(body)
        return body


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"attempt tree contains a symbolic link: {path}")
        if not path.is_file():
            continue
        relative = str(path.relative_to(root)).encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def _read(path: Path) -> tuple[Any, str]:
    if path.is_symlink() or not path.is_file():
        return None, "missing_or_nonregular"
    try:
        return json.loads(path.read_text(encoding="utf-8")), "ok"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"invalid_json:{exc}"


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _hash_matches(value: object, field: str) -> bool:
    if not isinstance(value, Mapping) or not isinstance(value.get(field), str):
        return False
    body = {key: item for key, item in value.items() if key != field}
    return value[field] == content_hash(body)


def audit_finbench_confirmatory_block(
    *,
    attempt_root: str | Path,
    execution_context: Mapping[str, Any],
    expected_commit: str,
) -> FinBenchConfirmatoryBlockEvidenceAudit:
    """Audit a complete block or zero-measurement infrastructure failure."""

    if _COMMIT.fullmatch(expected_commit) is None:
        raise ValueError("expected_commit must be a full lowercase Git commit")
    selected = Path(attempt_root)
    if selected.is_symlink():
        raise ValueError("attempt_root must not be a symbolic link")
    root = selected.resolve()
    if not root.is_dir():
        raise ValueError("attempt_root must be a real directory")
    context = validate_finbench_confirmatory_block_execution_envelope(
        execution_context
    )
    attempt = context["block_attempt"]
    before = _tree_digest(root)
    paths = {
        "status": root / "run_status.json",
        "manifest": root / "run_manifest.json",
        "preflight": root / "preflight.json",
        "loads": root / "load_reports.json",
        "raw": root / "raw_measurements.json",
        "attempt_record": root / "attempt_record.json",
    }
    loaded: dict[str, Any] = {}
    states: dict[str, str] = {}
    for name, path in paths.items():
        loaded[name], states[name] = _read(path)

    checks: list[FinBenchConfirmatoryBlockEvidenceCheck] = []

    def check(check_id: str, expected: Any, observed: Any) -> None:
        checks.append(
            FinBenchConfirmatoryBlockEvidenceCheck(
                check_id=check_id,
                passed=expected == observed,
                expected=expected,
                observed=observed,
            )
        )

    status = _mapping(loaded.get("status"))
    manifest = _mapping(loaded.get("manifest"))
    preflight = _mapping(loaded.get("preflight"))
    loads = _mapping(loaded.get("loads"))
    raw = _mapping(loaded.get("raw"))
    attempt_record = _mapping(loaded.get("attempt_record"))
    attempt_status = str(attempt_record.get("status", ""))
    completed = attempt_status == "completed"
    infrastructure_failed = attempt_status == "infrastructure_failed"
    accepted_attempt_status = completed or infrastructure_failed
    expected_runtime_status = "success" if completed else "failed"
    expected_replacement_eligible = infrastructure_failed
    expected_error = status.get("error")
    error_shape_valid = (
        expected_error is None
        if completed
        else isinstance(expected_error, str) and bool(expected_error)
    )
    for name, state in states.items():
        if name == "loads" and infrastructure_failed:
            check(
                "artifact.loads",
                True,
                state in {"ok", "missing_or_nonregular"},
            )
        else:
            check(f"artifact.{name}", "ok", state)
    check("attempt.accepted_status", True, accepted_attempt_status)
    expected_measurements = attempt["measurements"]
    expected_identities = [
        str(item["scheduled_identity"]) for item in expected_measurements
    ]
    raw_measurements = raw.get("measurements")
    raw_values = raw_measurements if isinstance(raw_measurements, list) else []
    raw_identities = [
        str(item.get("scheduled_identity"))
        for item in raw_values
        if isinstance(item, Mapping)
    ]

    check("directory.attempt_id", attempt["attempt_id"], root.name)
    check(
        "status.schema",
        FINBENCH_CONFIRMATORY_LIVE_BLOCK_SCHEMA_VERSION,
        status.get("schema_version"),
    )
    check("status.state", expected_runtime_status, status.get("status"))
    check("status.error_shape", True, error_shape_valid)
    check(
        "status.replacement_eligible",
        expected_replacement_eligible,
        status.get("replacement_eligible"),
    )
    check("status.automatic_retries", 0, status.get("automatic_retries"))
    check("preflight.hash", True, _hash_matches(preflight, "preflight_sha256"))
    check("preflight.attempt", attempt, preflight.get("attempt"))
    check(
        "preflight.context",
        context["execution_context_sha256"],
        preflight.get("execution_context_sha256"),
    )
    check(
        "preflight.git.commit",
        expected_commit,
        _mapping(preflight.get("git")).get("commit"),
    )
    check(
        "preflight.git.clean", True, _mapping(preflight.get("git")).get("clean")
    )
    check(
        "preflight.sealed",
        True,
        preflight.get("plan_catalog_sealed_before_fixture_load"),
    )
    check(
        "preflight.calls_before_seal", 0, preflight.get("backend_calls_before_seal")
    )
    check("preflight.oracle", False, preflight.get("oracle_content_parsed"))
    catalog = preflight.get("plan_catalog")
    catalog_values = catalog if isinstance(catalog, list) else []
    # Use JSON-native arrays here.  The audit is persisted and later
    # reconstructed by the campaign auditor; tuples serialize as arrays but
    # do not compare equal to the arrays read back from JSON.
    catalog_projection = [
        [
            item.get("scheduled_identity"),
            item.get("query_id"),
            item.get("family_id"),
            item.get("physical_strategy"),
        ]
        for item in catalog_values
        if isinstance(item, Mapping)
    ]
    expected_projection = [
        [
            item["scheduled_identity"],
            item["query_id"],
            item["family_id"],
            item["physical_strategy"],
        ]
        for item in expected_measurements
    ]
    check("preflight.plan_catalog", expected_projection, catalog_projection)
    check(
        "preflight.query_timeout_policy",
        _CONFIRMATORY_TIMEOUT_POLICY,
        preflight.get("query_timeout_policy"),
    )
    check(
        "preflight.query_timeout_policy_hash",
        content_hash(_CONFIRMATORY_TIMEOUT_POLICY),
        preflight.get("query_timeout_policy_sha256"),
    )
    if completed:
        check("loads.backends", ["fuseki", "neo4j"], sorted(loads))
        check(
            "loads.success",
            True,
            set(loads) == {"neo4j", "fuseki"}
            and all(
                isinstance(item, Mapping) and item.get("success") is True
                for item in loads.values()
            ),
        )
    elif states["loads"] == "ok":
        check("loads.failure_evidence", True, isinstance(loaded["loads"], Mapping))
    check("raw.hash", True, _hash_matches(raw, "raw_measurements_sha256"))
    check(
        "raw.schema",
        FINBENCH_CONFIRMATORY_RAW_MEASUREMENTS_SCHEMA_VERSION,
        raw.get("schema_version"),
    )
    check("raw.attempt", attempt["attempt_id"], raw.get("attempt_id"))
    check(
        "raw.block", attempt["measurement_block_id"], raw.get("measurement_block_id")
    )
    expected_raw_count = len(expected_identities) if completed else 0
    expected_raw_identities = expected_identities if completed else []
    check("raw.count", expected_raw_count, raw.get("measurement_count"))
    check("raw.identity_order", expected_raw_identities, raw_identities)
    check("raw.oracle", False, raw.get("oracle_opened"))
    check("raw.automatic_retries", 0, raw.get("automatic_retries"))
    check("raw.paper_result", False, raw.get("paper_result"))
    valid_measurements = len(raw_values) == expected_raw_count
    timeout_count = 0
    for expected_item, item in zip(expected_measurements, raw_values):
        if not isinstance(item, Mapping):
            valid_measurements = False
            continue
        outcome = item.get("outcome")
        elapsed = item.get("elapsed_ms")
        if outcome == "query_timeout":
            timeout_count += 1
            calls = item.get("total_remote_calls")
            outcome_valid = (
                isinstance(elapsed, (int, float))
                and not isinstance(elapsed, bool)
                and float(elapsed) >= 60_000.0
                and item.get("total_bytes_moved") is None
                and isinstance(calls, int)
                and not isinstance(calls, bool)
                and 0 <= calls <= 2
            )
        else:
            moved = item.get("total_bytes_moved")
            outcome_valid = (
                outcome == "success"
                and isinstance(elapsed, (int, float))
                and not isinstance(elapsed, bool)
                and float(elapsed) >= 0
                and isinstance(moved, int)
                and not isinstance(moved, bool)
                and moved >= 0
                and item.get("total_remote_calls") == 2
            )
        rows = item.get("canonical_rows")
        valid_measurements = valid_measurements and (
            item.get("attempt_id") == attempt["attempt_id"]
            and item.get("query_id") == expected_item["query_id"]
            and item.get("family_id") == expected_item["family_id"]
            and item.get("method_id") == expected_item["method_id"]
            and item.get("physical_strategy") == expected_item["physical_strategy"]
            and item.get("oracle_opened") is False
            and item.get("exact_answer") is None
            and isinstance(rows, list)
            and item.get("canonical_rows_sha256") == content_hash(rows)
            and outcome_valid
        )
    check("raw.measurements", True, valid_measurements)
    check("raw.timeout_count", timeout_count, raw.get("query_timeout_count"))
    expected_attempt_record = {
        "attempt_id": attempt["attempt_id"],
        "measurement_block_id": attempt["measurement_block_id"],
        "attempt_index": attempt["attempt_index"],
        "status": attempt_status,
        "valid_measurement_count": expected_raw_count,
        "replacement_of_attempt_id": attempt["replacement_of_attempt_id"],
        "failure_category": None if completed else "infrastructure_failure",
    }
    check("attempt_record", expected_attempt_record, dict(attempt_record))
    check("manifest.hash", True, _hash_matches(manifest, "manifest_sha256"))
    check(
        "manifest.schema",
        FINBENCH_CONFIRMATORY_LIVE_BLOCK_SCHEMA_VERSION,
        manifest.get("schema_version"),
    )
    check("manifest.status", expected_runtime_status, manifest.get("status"))
    check("manifest.error", expected_error, manifest.get("error"))
    check(
        "manifest.git",
        expected_commit,
        _mapping(manifest.get("git")).get("commit"),
    )
    check("manifest.attempt", attempt["attempt_id"], manifest.get("attempt_id"))
    check(
        "manifest.context",
        context["execution_context_sha256"],
        manifest.get("execution_context_sha256"),
    )
    check(
        "manifest.raw",
        raw.get("raw_measurements_sha256"),
        manifest.get("raw_measurements_sha256"),
    )
    check(
        "manifest.query_timeout_policy",
        content_hash(_CONFIRMATORY_TIMEOUT_POLICY),
        manifest.get("query_timeout_policy_sha256"),
    )
    check(
        "manifest.attempt_record",
        expected_attempt_record,
        manifest.get("attempt_record"),
    )
    check(
        "manifest.expected_count",
        len(expected_identities),
        manifest.get("expected_plan_run_count"),
    )
    check(
        "manifest.observed_count",
        expected_raw_count,
        manifest.get("observed_method_outcome_count"),
    )
    check("manifest.timeout_count", timeout_count, manifest.get("query_timeout_count"))
    check(
        "manifest.replacement_eligible",
        expected_replacement_eligible,
        manifest.get("replacement_eligible"),
    )
    check("manifest.oracle", False, manifest.get("oracle_content_parsed"))
    check("manifest.automatic_retries", 0, manifest.get("automatic_retries"))
    check("manifest.paper_result", False, manifest.get("paper_result"))
    after = _tree_digest(root)
    return FinBenchConfirmatoryBlockEvidenceAudit(
        attempt_root=root,
        expected_commit=expected_commit,
        attempt_id=str(attempt["attempt_id"]),
        block_attempt_sha256=str(attempt["block_attempt_sha256"]),
        execution_context_sha256=str(context["execution_context_sha256"]),
        raw_measurements_sha256=str(raw.get("raw_measurements_sha256", "")),
        attempt_status=attempt_status,
        replacement_eligible=expected_replacement_eligible,
        valid_measurement_count=expected_raw_count,
        failure_category=None if completed else "infrastructure_failure",
        checks=tuple(checks),
        run_tree_mutated=before != after,
    )


def _read_context(path: str | Path) -> dict[str, Any]:
    selected = Path(path)
    if selected.is_symlink() or not selected.is_file():
        raise ValueError("execution context must be a regular file")
    value = json.loads(selected.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("execution context must contain an object")
    return value


def _write(path: str | Path, value: Mapping[str, Any]) -> Path:
    selected = Path(path)
    if selected.exists() or selected.is_symlink():
        raise FileExistsError(f"output exists: {selected}")
    selected.parent.mkdir(parents=True, exist_ok=True)
    temporary = selected.with_name(selected.name + f".partial-{os.getpid()}")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, selected)
    return selected


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt-root", required=True)
    parser.add_argument("--execution-context", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        audit = audit_finbench_confirmatory_block(
            attempt_root=args.attempt_root,
            execution_context=_read_context(args.execution_context),
            expected_commit=args.expected_commit,
        )
        payload = audit.to_dict()
        output = _write(args.output, payload)
    except (FileExistsError, OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if audit.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
