"""Inspect calibration query text, latency, and result cardinality."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash


def inspect_calibration(
    run_root: str | Path,
    *,
    config_path: str | Path,
) -> dict[str, Any]:
    root = Path(run_root)
    config = _load_json(Path(config_path))
    expected = set(
        _mapping(config.get("diagnostics", {}), "diagnostics").get(
            "expected_nonempty_case_ids", ()
        )
    )
    records: list[dict[str, Any]] = []
    for backend_root in sorted((root / "calibration").iterdir()):
        if not backend_root.is_dir():
            continue
        plans = _load_jsonl(backend_root / "calibration_plans.jsonl")
        measurements = _load_jsonl(backend_root / "execution_measurements.jsonl")
        by_plan: dict[str, list[dict[str, Any]]] = {}
        for measurement in measurements:
            by_plan.setdefault(str(measurement.get("physical_plan_id")), []).append(
                measurement
            )
        for plan in plans:
            plan_id = str(plan.get("physical_plan_id"))
            plan_measurements = by_plan.get(plan_id, [])
            if not plan_measurements:
                continue
            artifact = plan.get("query_artifact")
            artifact = artifact if isinstance(artifact, Mapping) else {}
            measured = [item for item in plan_measurements if item.get("phase") == "measured"]
            row_counts = [
                int(item["row_count"])
                for item in measured
                if item.get("row_count") is not None
            ]
            successful = [item for item in measured if item.get("status") == "success"]
            case_id = str(plan.get("case_id"))
            suspicious = bool(
                case_id in expected
                and successful
                and len(row_counts) == len(successful)
                and not any(row_counts)
            )
            records.append(
                {
                    "case_id": case_id,
                    "backend_id": backend_root.name,
                    "physical_plan_id": plan_id,
                    "query_text": artifact.get("text"),
                    "query_hash": content_hash({"text": artifact.get("text")}),
                    "execution_success": bool(successful),
                    "row_counts": row_counts,
                    "latencies_ms": [
                        item.get("raw_latency_ms") for item in successful
                    ],
                    "suspicious_empty_calibration_query": suspicious,
                    "cardinality_status": (
                        "available" if len(row_counts) == len(successful) else "not_available"
                    ),
                }
            )
    suspicious_records = [
        item for item in records if item["suspicious_empty_calibration_query"]
    ]
    return {
        "schema_version": "m12d-calibration-sanity-v1",
        "status": "warning" if suspicious_records else "ok",
        "records": records,
        "suspicious_empty_calibration_queries": suspicious_records,
        "namespace_rewrite_performed": False,
        "fuseki_namespace_caveat": (
            "The toy data uses the financial-risk namespace while current M9 SPARQL "
            "mapping assumptions may use the graph namespace. Empty success is recorded, "
            "not rewritten or treated as backend failure."
        ),
    }


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"{path} must contain a JSON object.")
    return dict(data)


def _load_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        data = json.loads(line)
        if not isinstance(data, Mapping):
            raise ValueError(f"{path}:{line_number} must contain a JSON object.")
        records.append(dict(data))
    return tuple(records)


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object.")
    return dict(value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect M12-C calibration cardinality.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    report = inspect_calibration(args.run_root, config_path=args.config)
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
