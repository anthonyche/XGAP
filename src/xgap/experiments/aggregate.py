"""Analysis-ready JSON/CSV aggregation for compatible M12-D runs."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


GROUP_FIELDS = ("dataset", "model", "method", "epsilon", "budget", "seed", "backend")


@dataclass(frozen=True)
class AggregateResult:
    output_json: Path
    output_csv: Path
    run_count: int
    group_count: int


def aggregate_runs(
    run_paths: Iterable[str | Path],
    *,
    output_prefix: str | Path,
) -> AggregateResult:
    records = tuple(_run_record(Path(path)) for path in run_paths)
    if not records:
        raise ValueError("Aggregation requires at least one completed run.")
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for record in records:
        key = tuple(str(record["group"].get(field)) for field in GROUP_FIELDS)
        groups.setdefault(key, []).append(record)
    rows: list[dict[str, Any]] = []
    for key, group_records in sorted(groups.items()):
        metric_names = sorted(
            {
                name
                for record in group_records
                for name in record["metrics"]
            }
        )
        for metric_name in metric_names:
            values = [
                float(record["metrics"][metric_name])
                for record in group_records
                if metric_name in record["metrics"]
            ]
            if not values:
                continue
            summary = _summary(values)
            rows.append(
                {
                    **dict(zip(GROUP_FIELDS, key, strict=True)),
                    "metric": metric_name,
                    **summary,
                }
            )
    prefix = Path(output_prefix)
    json_path = prefix.with_suffix(".json")
    csv_path = prefix.with_suffix(".csv")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "m12d-aggregate-v1",
        "run_count": len(records),
        "group_count": len(groups),
        "confidence_interval": {
            "method": "normal_approximation_95_percent",
            "multiplier": 1.96,
            "small_sample_caveat": True,
        },
        "rows": rows,
    }
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            *GROUP_FIELDS,
            "metric",
            "count",
            "mean",
            "median",
            "stddev",
            "ci95_low",
            "ci95_high",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return AggregateResult(json_path, csv_path, len(records), len(groups))


def _run_record(run_root: Path) -> dict[str, Any]:
    summary = _load_json(run_root / "run_summary.json")
    if summary.get("status") != "complete":
        raise ValueError(f"Aggregation accepts completed runs only: {run_root}")
    spec = _load_json(run_root / "experiment_spec.json")
    metrics = _load_json(run_root / "metrics.json")
    planning = spec.get("planning", {})
    baseline = spec.get("baseline", {})
    budget = spec.get("budget", {})
    backend_ids = spec.get("backend_ids", [])
    return {
        "group": {
            "dataset": spec.get("dataset_bundle"),
            "model": spec.get("model_bundle"),
            "method": baseline.get("id"),
            "epsilon": planning.get("epsilon"),
            "budget": budget.get("value", budget.get("maximum")),
            "seed": spec.get("random_seed"),
            "backend": baseline.get("backend_id") or "+".join(backend_ids),
        },
        "metrics": _flatten_numeric(metrics),
    }


def _flatten_numeric(value: object, prefix: str = "") -> dict[str, float]:
    result: dict[str, float] = {}
    if isinstance(value, Mapping):
        for key, item in sorted(value.items()):
            name = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten_numeric(item, name))
    elif isinstance(value, int | float) and not isinstance(value, bool):
        number = float(value)
        if math.isfinite(number):
            result[prefix] = number
    return result


def _summary(values: Sequence[float]) -> dict[str, float | int]:
    mean = statistics.mean(values)
    median = statistics.median(values)
    stddev = statistics.stdev(values) if len(values) > 1 else 0.0
    margin = 1.96 * stddev / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return {
        "count": len(values),
        "mean": mean,
        "median": median,
        "stddev": stddev,
        "ci95_low": mean - margin,
        "ci95_high": mean + margin,
    }


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"{path} must contain a JSON object.")
    return dict(data)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate completed M12-D runs.")
    parser.add_argument("--runs", nargs="*")
    parser.add_argument("--matrix-root")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    paths = [Path(item) for item in args.runs or []]
    if args.matrix_root:
        paths.extend(
            path
            for path in sorted((Path(args.matrix_root) / "runs").iterdir())
            if path.is_dir()
            and (path / "run_summary.json").exists()
            and _load_json(path / "run_summary.json").get("status") == "complete"
        )
    result = aggregate_runs(paths, output_prefix=args.output)
    print(f"Aggregated runs: {result.run_count}")
    print(f"Groups: {result.group_count}")
    print(f"JSON: {result.output_json}")
    print(f"CSV: {result.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
