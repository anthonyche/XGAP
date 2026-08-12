"""Configuration-driven controlled M11 physical-planning experiment."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from xgap.backends import registry
from xgap.llm.parser import parse_planner_response
from xgap.llm.schemas import PlannerRequest
from xgap.planning import (
    ArtifactOntologyAlignmentProvider,
    DeterministicStateFeatureExtractor,
    ExchangeCatalog,
    ExchangeStrategy,
    ExecutionObservationStore,
    ExistingCompilerAdapter,
    FixedBudgetPolicy,
    GaussianProcessConfig,
    GaussianProcessCostEstimator,
    MainPlannerResult,
    PlanningConfig,
    PolynomialBudgetPolicy,
    ProvidedSemanticDeviationScorer,
    QueryPlanningContext,
    XGAPPhysicalPlanner,
    write_search_trace,
)


@dataclass(frozen=True)
class PlannerRunArtifacts:
    run_root: Path
    result: MainPlannerResult
    paths: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {
            "run_root": str(self.run_root),
            "status": self.result.status,
            "reason": self.result.reason,
            "paths": dict(self.paths),
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Planner config field '{field_name}' must be a mapping.")
    return dict(value)


def _resolve(path: str | Path, repo_root: Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else repo_root / candidate


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"JSON artifact '{path}' must contain an object.")
    return dict(data)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _exchange_catalog(data: Mapping[str, Any]) -> ExchangeCatalog:
    strategies_data = data.get("strategies", [])
    if not isinstance(strategies_data, list):
        raise ValueError("exchange_catalog.strategies must be a list.")
    strategies = tuple(
        ExchangeStrategy(
            strategy_id=str(item["strategy_id"]),
            source_backend_id=str(item["source_backend_id"]),
            target_backend_id=str(item["target_backend_id"]),
            result_kind=str(item["result_kind"]),
            executable=bool(item.get("executable", True)),
            metadata=dict(item.get("metadata", {})),
        )
        for item in strategies_data
        if isinstance(item, Mapping)
    )
    if len(strategies) != len(strategies_data):
        raise ValueError("Every exchange strategy must be an object.")
    return ExchangeCatalog(
        strategies=strategies,
        catalog_id=str(data.get("catalog_id", "configured-exchange-catalog")),
        version=str(data.get("version", "1")),
    )


def _budget_policy(data: Mapping[str, Any]):
    kind = str(data.get("type", "fixed"))
    if kind == "fixed":
        return FixedBudgetPolicy(int(data["value"]))
    if kind == "polynomial_capped":
        return PolynomialBudgetPolicy(
            base=int(data.get("base", 1)),
            operator_factor=int(data.get("operator_factor", 2)),
            backend_factor=int(data.get("backend_factor", 1)),
            maximum=int(data.get("maximum", 1000)),
        )
    raise ValueError(f"Unsupported budget policy type '{kind}'.")


def run_physical_planner(
    config_path: str | Path,
    *,
    runs_dir_override: str | Path | None = None,
) -> PlannerRunArtifacts:
    repo_root = _repo_root()
    config_file = _resolve(config_path, repo_root)
    raw_config = _read_json(config_file)
    query_data = _mapping(raw_config.get("query"), "query")
    planning_data = _mapping(raw_config.get("planning"), "planning")
    run_id = str(raw_config["run_id"])
    query_context = QueryPlanningContext(
        query_id=str(query_data["query_id"]),
        task_id=str(query_data["task_id"]),
        question=str(query_data["question"]),
        metadata=dict(query_data.get("metadata", {})),
    )

    candidate_path = _resolve(str(raw_config["candidate_artifact"]), repo_root)
    candidate_data = _read_json(candidate_path)
    max_candidates = int(raw_config.get("max_candidates", len(candidate_data.get("candidates", [])) or 1))
    response = parse_planner_response(
        candidate_data,
        PlannerRequest(query_context.question, max_candidates=max_candidates),
    )

    descriptor_dir = _resolve(str(raw_config.get("descriptor_dir", "descriptors/backends")), repo_root)
    registry.load_descriptors(descriptor_dir)
    backend_ids = tuple(str(item) for item in raw_config.get("backend_ids", ()))
    if not backend_ids:
        raise ValueError("Planner config backend_ids must be non-empty.")
    profiles = tuple(registry.get_capability_profile(item) for item in backend_ids)

    alignment_path = _resolve(str(raw_config["alignment_artifact"]), repo_root)
    alignment_provider = ArtifactOntologyAlignmentProvider.from_json(alignment_path)
    exchange_catalog = _exchange_catalog(
        _mapping(raw_config.get("exchange_catalog", {"strategies": []}), "exchange_catalog")
    )
    feature_data = _mapping(raw_config.get("features", {}), "features")
    optional_statistics = _mapping(
        feature_data.get("optional_statistics", {}),
        "features.optional_statistics",
    )
    extractor = DeterministicStateFeatureExtractor(
        backend_ids,
        optional_stat_names=tuple(str(item) for item in feature_data.get("optional_stat_names", ())),
        optional_statistics={name: float(value) for name, value in optional_statistics.items()},
    )
    cost_data = _mapping(raw_config.get("cost_model"), "cost_model")
    if str(cost_data.get("type", "gaussian_process")) != "gaussian_process":
        raise ValueError("The M11 experiment runner supports gaussian_process cost_model only.")
    gp_config = GaussianProcessConfig.from_dict(
        _mapping(cost_data.get("config", {}), "cost_model.config")
    )
    observation_path_value = cost_data.get("observation_store")
    observations = ()
    if observation_path_value is not None:
        observation_path = _resolve(str(observation_path_value), repo_root)
        observations = ExecutionObservationStore(observation_path).snapshot()
    estimator = GaussianProcessCostEstimator(
        config=gp_config,
        feature_extractor=extractor,
        observations=observations,
    )
    planning_config = PlanningConfig(
        run_id=run_id,
        semantic_threshold=float(planning_data["epsilon"]),
        execution_threshold=float(planning_data["t_max"]),
        top_k=int(planning_data["top_k"]),
        global_delta=float(planning_data["global_delta"]),
        task_index=int(planning_data.get("task_index", 1)),
        deterministic_seed=int(planning_data.get("deterministic_seed", 0)),
        metadata={"config_path": str(config_file)},
    )
    planner = XGAPPhysicalPlanner(
        alignment_provider=alignment_provider,
        semantic_scorer=ProvidedSemanticDeviationScorer(),
        backend_profiles=profiles,
        exchange_catalog=exchange_catalog,
        budget_policy=_budget_policy(_mapping(raw_config.get("budget"), "budget")),
        cost_estimator=estimator,
        physical_compiler=ExistingCompilerAdapter(),
    )
    result = planner.plan(
        query_context=query_context,
        candidates=response.candidates,
        config=planning_config,
    )

    runs_dir_value = runs_dir_override or raw_config.get("runs_dir", "runs")
    run_root = _resolve(str(runs_dir_value), repo_root) / run_id
    paths = {
        "config": str(run_root / "planner_config.json"),
        "input": str(run_root / "input_candidates.json"),
        "alignment": str(run_root / "alignment_results.json"),
        "semantic": str(run_root / "semantic_deviation_results.json"),
        "trace": str(run_root / "search_trace.jsonl"),
        "complete": str(run_root / "complete_plans.json"),
        "selected": str(run_root / "selected_plans.json"),
        "summary": str(run_root / "summary.json"),
        "model": str(run_root / "cost_model_snapshot.json"),
    }
    _write_json(Path(paths["config"]), raw_config)
    _write_json(
        Path(paths["input"]),
        {
            "query": query_context.to_dict(),
            "provider_id": response.provider_id,
            "model": response.model,
            "candidates": response.to_dict()["candidates"],
            "candidate_artifact": str(candidate_path),
        },
    )
    _write_json(
        Path(paths["alignment"]),
        {
            "alignment_artifact": str(alignment_path),
            "results": [item.alignment.to_dict() for item in result.candidate_records],
        },
    )
    _write_json(
        Path(paths["semantic"]),
        [
            item.semantic_deviation.to_dict()
            for item in result.candidate_records
            if item.semantic_deviation is not None
        ],
    )
    write_search_trace(paths["trace"], result.traces)
    _write_json(
        Path(paths["complete"]),
        [
            plan.to_dict()
            for record in result.candidate_records
            if record.search is not None
            for plan in record.search.discovered_complete_plans
        ],
    )
    _write_json(Path(paths["selected"]), [item.to_dict() for item in result.selected_plans])
    _write_json(Path(paths["model"]), estimator.to_dict())
    compiled_dir = run_root / "compiled"
    compiled_records = []
    for selected in result.selected_plans:
        compilation = selected.physical_plan.realization.compilation
        if compilation.artifacts:
            for artifact in compilation.artifacts:
                extension = {
                    "cypher": "cypher",
                    "sparql": "rq",
                    "xgap_logical": "xgap",
                }.get(artifact.language.lower(), "txt")
                artifact_path = compiled_dir / f"{selected.candidate_id}.{extension}"
                artifact_path.parent.mkdir(parents=True, exist_ok=True)
                artifact_path.write_text(artifact.text + "\n", encoding="utf-8")
                artifact_json_path = compiled_dir / f"{selected.candidate_id}.artifact.json"
                _write_json(artifact_json_path, artifact.to_dict())
                compiled_records.append(
                    {
                        "candidate_id": selected.candidate_id,
                        "artifact": artifact.to_dict(),
                        "text_path": str(artifact_path),
                        "metadata_path": str(artifact_json_path),
                    }
                )
        else:
            unsupported_path = compiled_dir / f"{selected.candidate_id}.unsupported.json"
            _write_json(unsupported_path, compilation.to_dict())
            compiled_records.append(
                {
                    "candidate_id": selected.candidate_id,
                    "unsupported": compilation.to_dict(),
                    "path": str(unsupported_path),
                }
            )
    processed = sum(
        item.search.processed_count
        for item in result.candidate_records
        if item.search is not None
    )
    generated = sum(
        item.search.generated_count
        for item in result.candidate_records
        if item.search is not None
    )
    pruned = sum(
        item.search.pruned_count
        for item in result.candidate_records
        if item.search is not None
    )
    summary = {
        "run_id": run_id,
        "status": result.status,
        "reason": result.reason,
        "candidate_count": len(response.candidates),
        "selected_count": len(result.selected_plans),
        "candidate_statuses": {
            item.candidate_id: item.status for item in result.candidate_records
        },
        "processed_states": processed,
        "generated_states": generated,
        "pruned_states": pruned,
        "pruning_ratio": pruned / max(1, generated),
        "compiled_or_unsupported": compiled_records,
        "ontology_alignment_provider": alignment_provider.provider_id,
        "semantic_deviation_scorer": "provided-semantic-deviation",
        "cost_model": estimator.to_dict(),
        "feature_schema": extractor.to_dict(),
        "unsupported_boundaries": [
            "no live LLM provider",
            "no ontology induction or OWL/DL reasoning",
            "no logical rewrite enumeration",
            "no distributed cross-backend runtime",
            "no M9 compiler coverage expansion",
            "no KGQA evaluation",
        ],
    }
    _write_json(Path(paths["summary"]), summary)
    return PlannerRunArtifacts(run_root=run_root, result=result, paths=paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run controlled XGAP M11 physical planning")
    parser.add_argument("--config", required=True)
    parser.add_argument("--runs-dir")
    args = parser.parse_args(argv)
    artifacts = run_physical_planner(args.config, runs_dir_override=args.runs_dir)
    print(f"Planner status: {artifacts.result.status}")
    print(f"Selected plans: {len(artifacts.result.selected_plans)}")
    print(f"Run artifacts: {artifacts.run_root}")
    return 0 if artifacts.result.status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
