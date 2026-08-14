"""Deterministic local/sequential M12-D experiment matrix expansion."""

from __future__ import annotations

import argparse
import itertools
import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.calibrate import run_calibration
from xgap.experiments.contracts import BaselineId, ExperimentSpec
from xgap.experiments.hashing import content_hash
from xgap.experiments.online_run import OnlineRunResult, run_online_experiment


@dataclass(frozen=True)
class MatrixInstance:
    matrix_id: str
    run_id: str
    spec: ExperimentSpec
    dimensions: Mapping[str, Any]
    instance_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "m12d-matrix-instance-v1",
            "matrix_id": self.matrix_id,
            "run_id": self.run_id,
            "instance_hash": self.instance_hash,
            "dimensions": dict(self.dimensions),
            "experiment_spec": self.spec.to_dict(),
        }


@dataclass(frozen=True)
class MatrixRunResult:
    matrix_root: Path
    instances: tuple[MatrixInstance, ...]
    executed: tuple[OnlineRunResult, ...]
    skipped_run_ids: tuple[str, ...]
    failed: tuple[Mapping[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "m12d-matrix-run-summary-v1",
            "matrix_root": str(self.matrix_root),
            "expanded_count": len(self.instances),
            "executed": [item.to_dict() for item in self.executed],
            "skipped_run_ids": list(self.skipped_run_ids),
            "failed": [dict(item) for item in self.failed],
        }


def expand_matrix(config_path: str | Path) -> tuple[dict[str, Any], tuple[MatrixInstance, ...]]:
    repo_root = _repo_root()
    config = _load_json(_resolve(config_path, repo_root))
    matrix_id = str(config.get("matrix_id", ""))
    if not matrix_id:
        raise ValueError("Matrix config requires matrix_id.")
    base_path = _resolve(str(config.get("base_experiment_spec", "")), repo_root)
    base_data = _load_json(base_path)
    dimensions = _mapping(config.get("dimensions"), "dimensions")
    methods = tuple(dimensions.get("method", ()))
    epsilons = tuple(dimensions.get("epsilon", ()))
    budgets = tuple(dimensions.get("budget", ()))
    seeds = tuple(dimensions.get("seed", ()))
    if not all((methods, epsilons, budgets, seeds)):
        raise ValueError("Matrix method, epsilon, budget, and seed dimensions are required.")
    instances: list[MatrixInstance] = []
    for method_value, epsilon, budget, seed in itertools.product(
        methods, epsilons, budgets, seeds
    ):
        method = (
            {"id": str(method_value)}
            if isinstance(method_value, str)
            else _mapping(method_value, "dimensions.method[]")
        )
        concrete = json.loads(json.dumps(base_data))
        method_id = BaselineId(str(method["id"]))
        backend_id = method.get("backend_id")
        concrete["baseline"] = {
            "id": method_id.value,
            "backend_id": backend_id,
            "controlled_scope": method_id is BaselineId.EXHAUSTIVE_ORACLE,
            "model_bundle_ref": concrete["model_bundle"],
        }
        if method_id is BaselineId.DIRECT_TEXT2GRAPHQUERY:
            concrete["baseline"]["model_bundle_ref"] = concrete["model_bundle"]
        if method_id in {BaselineId.SINGLE_BACKEND, BaselineId.DIRECT_TEXT2GRAPHQUERY}:
            if not backend_id:
                raise ValueError(f"Matrix method {method_id.value} requires backend_id.")
            concrete["backend_ids"] = [str(backend_id)]
        concrete["planning"]["epsilon"] = float(epsilon)
        concrete["budget"] = {"type": "fixed", "value": int(budget)}
        concrete["random_seed"] = int(seed)
        update = method_id is not BaselineId.NO_ONLINE_UPDATE
        concrete["gp_protocol"]["evaluation"]["update_posterior_between_tasks"] = update
        orchestration = dict(concrete.get("orchestration", {}))
        orchestration.update(_mapping(config.get("orchestration", {}), "orchestration"))
        orchestration["candidate_mode"] = "generate_once"
        if method_id is BaselineId.SINGLE_BACKEND:
            orchestration["feature_backend_ids"] = list(
                config.get("feature_backend_ids", base_data["backend_ids"])
            )
        concrete["orchestration"] = orchestration
        dimension_record = {
            "dataset": concrete["dataset_bundle"],
            "model": concrete["model_bundle"],
            "method": method_id.value,
            "backend": backend_id,
            "epsilon": float(epsilon),
            "budget": int(budget),
            "seed": int(seed),
        }
        instance_hash = content_hash(
            {
                "matrix_id": matrix_id,
                "base_spec_hash": ExperimentSpec.from_dict(base_data).spec_hash,
                "dimensions": dimension_record,
                "orchestration": orchestration,
            }
        )
        dataset_token = Path(str(concrete["dataset_bundle"])).name
        model_token = Path(str(concrete["model_bundle"])).name
        run_id = (
            f"{matrix_id}-{dataset_token}-{model_token}-{method_id.value}-"
            f"e{_number_token(float(epsilon))}-b{int(budget)}-s{int(seed)}-"
            f"{instance_hash[:10]}"
        )
        concrete["run_id"] = run_id
        concrete["experiment_id"] = f"{matrix_id}-{method_id.value}"
        spec = ExperimentSpec.from_dict(concrete)
        instances.append(
            MatrixInstance(matrix_id, run_id, spec, dimension_record, instance_hash)
        )
    max_runs = int(config.get("max_expanded_runs", 256))
    if len(instances) > max_runs:
        raise ValueError(
            f"Matrix expands to {len(instances)} runs, exceeding limit {max_runs}."
        )
    return config, tuple(instances)


def run_matrix(
    config_path: str | Path,
    *,
    execute: bool = False,
    offline: bool = False,
    resume: bool = False,
    retry_failed: bool = False,
    fail_fast: bool = False,
    filters: Mapping[str, str] | None = None,
    output_root_override: str | Path | None = None,
) -> MatrixRunResult:
    repo_root = _repo_root()
    config, expanded = expand_matrix(config_path)
    selected = tuple(item for item in expanded if _matches(item, filters or {}))
    output_root = (
        Path(output_root_override)
        if output_root_override is not None
        else _resolve(str(config.get("output_root", "runs/matrices")), repo_root)
    )
    matrix_root = output_root / str(config["matrix_id"])
    if not execute:
        return MatrixRunResult(matrix_root, selected, (), (), ())

    (matrix_root / "instances").mkdir(parents=True, exist_ok=True)
    shared_candidates = matrix_root / "candidate_artifacts"
    for instance in selected:
        _write_json(
            matrix_root / "instances" / f"{instance.run_id}.json",
            instance.to_dict(),
        )
    calibration_root: Path
    if offline:
        calibration_config = config.get("calibration_config")
        if not calibration_config:
            raise ValueError("Offline matrix execution requires calibration_config.")
        expected = matrix_root / "calibration" / "m12c-financial-risk-gp-calibration-dev"
        if expected.exists():
            calibration_root = expected
        else:
            calibration_root = run_calibration(
                str(calibration_config),
                output_root_override=matrix_root / "calibration",
                offline=True,
            ).run_root
    else:
        calibration_ref = config.get("calibration_run")
        if not calibration_ref:
            raise ValueError("Real matrix execution requires calibration_run.")
        calibration_root = _resolve(str(calibration_ref), repo_root)

    executed: list[OnlineRunResult] = []
    skipped: list[str] = []
    failed: list[Mapping[str, str]] = []
    for instance in selected:
        run_root = matrix_root / "runs" / instance.run_id
        summary = run_root / "run_summary.json"
        if summary.exists() and _load_json(summary).get("status") == "complete":
            skipped.append(instance.run_id)
            continue
        if run_root.exists() and not (resume or retry_failed):
            failed.append(
                {
                    "run_id": instance.run_id,
                    "category": "resume_state_error",
                    "message": "Incomplete run requires --resume or --retry-failed.",
                }
            )
            if fail_fast:
                break
            continue
        concrete = instance.spec.to_dict()
        concrete.pop("spec_hash", None)
        concrete["orchestration"] = {
            **dict(instance.spec.orchestration),
            "candidate_artifact_dir": str(shared_candidates),
            "calibration_run": str(calibration_root),
        }
        concrete_spec = ExperimentSpec.from_dict(concrete)
        concrete_path = matrix_root / "instances" / f"{instance.run_id}__runtime.json"
        _write_json(concrete_path, concrete_spec.to_dict())
        try:
            result = run_online_experiment(
                concrete_path,
                output_root_override=matrix_root / "runs",
                calibration_root_override=calibration_root,
                offline=offline,
                resume=run_root.exists() and (resume or retry_failed),
            )
            _write_json(result.run_root / "matrix_instance.json", instance.to_dict())
            executed.append(result)
        except Exception as error:  # noqa: BLE001 - matrix persists per-run failure.
            failed.append(
                {
                    "run_id": instance.run_id,
                    "category": "experiment_error",
                    "message": str(error),
                }
            )
            if fail_fast:
                break
    result = MatrixRunResult(
        matrix_root,
        selected,
        tuple(executed),
        tuple(skipped),
        tuple(failed),
    )
    _write_json(matrix_root / "matrix_summary.json", result.to_dict())
    return result


def _matches(instance: MatrixInstance, filters: Mapping[str, str]) -> bool:
    return all(str(instance.dimensions.get(key)) == value for key, value in filters.items())


def _number_token(value: float) -> str:
    return format(value, ".12g").replace("-", "m").replace(".", "p")


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object.")
    return dict(value)


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"{path} must contain a JSON object.")
    return dict(data)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve(path: str | Path, repo_root: Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else repo_root / value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Expand and run an M12-D matrix.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--filter", action="append", default=[])
    parser.add_argument("--output-root")
    args = parser.parse_args(argv)
    filters = dict(item.split("=", 1) for item in args.filter)
    execute = args.execute and not args.dry_run
    result = run_matrix(
        args.config,
        execute=execute,
        offline=args.offline,
        resume=args.resume,
        retry_failed=args.retry_failed,
        fail_fast=args.fail_fast,
        filters=filters,
        output_root_override=args.output_root,
    )
    if args.list or not execute:
        for instance in result.instances:
            print(instance.run_id)
    print(f"Expanded: {len(result.instances)}")
    print(f"Executed: {len(result.executed)}")
    print(f"Skipped: {len(result.skipped_run_ids)}")
    print(f"Failed: {len(result.failed)}")
    print(f"Matrix artifacts: {result.matrix_root}")
    return 0 if not result.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
