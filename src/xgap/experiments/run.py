"""Offline configuration-driven M12-A development experiment runner."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from xgap.backends import registry
from xgap.experiments.artifacts import (
    RunArtifactLayout,
    create_manifest,
    initialize_run_contract_files,
)
from xgap.experiments.bundles import (
    DatasetBundle,
    FragmentSupport,
    GoldAlignmentRecord,
    ModelBundle,
    load_mock_responses,
)
from xgap.experiments.contracts import (
    BaselineId,
    ExperimentMetrics,
    ExperimentSpec,
    MetricValue,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.semantic import DirectionalOntologySemanticDeviationScorer
from xgap.llm.parser import parse_planner_response
from xgap.llm.schemas import PlannerRequest
from xgap.llm.validation import validate_candidate
from xgap.planning import (
    ArtifactOntologyAlignmentProvider,
    DeterministicStateFeatureExtractor,
    ExchangeCatalog,
    ExistingCompilerAdapter,
    FixedBudgetPolicy,
    GaussianProcessConfig,
    GaussianProcessCostEstimator,
    MainPlannerResult,
    PlanningConfig,
    PolynomialBudgetPolicy,
    QueryPlanningContext,
    XGAPPhysicalPlanner,
)


@dataclass(frozen=True)
class DevelopmentRunResult:
    run_root: Path
    question_results: tuple[MainPlannerResult, ...]
    inventory: tuple[str, ...]
    attempted_question_count: int | None = None

    @property
    def successful_question_count(self) -> int:
        return sum(item.status == "ok" for item in self.question_results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_root": str(self.run_root),
            "question_count": len(self.question_results),
            "attempted_question_count": (
                self.attempted_question_count
                if self.attempted_question_count is not None
                else len(self.question_results)
            ),
            "successful_question_count": self.successful_question_count,
            "inventory": list(self.inventory),
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve(path: str | Path, repo_root: Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else repo_root / value


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Experiment field '{field_name}' must be a mapping.")
    return dict(value)


def _budget_policy(data: Mapping[str, Any]):
    kind = str(data.get("type", ""))
    if kind == "fixed":
        return FixedBudgetPolicy(int(data.get("value", 0)))
    if kind == "polynomial_capped":
        return PolynomialBudgetPolicy(
            base=int(data.get("base", 1)),
            operator_factor=int(data.get("operator_factor", 2)),
            backend_factor=int(data.get("backend_factor", 1)),
            maximum=int(data.get("maximum", 1000)),
        )
    raise ValueError(f"Unsupported M12-A budget policy '{kind}'.")


def _alignment_artifact(
    dataset: DatasetBundle,
    alignments: tuple[GoldAlignmentRecord, ...],
) -> dict[str, Any]:
    mapping_id = str(dataset.backend_mapping.get("mapping_id", ""))
    mapping_version = str(dataset.backend_mapping.get("version", ""))
    if not mapping_id or not mapping_version:
        raise ValueError("Dataset backend mapping must define mapping_id and version.")
    interpretations: dict[str, Any] = {}
    for alignment in alignments:
        if alignment.candidate_id in interpretations:
            raise ValueError(f"Duplicate alignment for candidate '{alignment.candidate_id}'.")
        interpretations[alignment.candidate_id] = {
            "alignment_id": alignment.alignment_id,
            "mapping_status": alignment.mapping_status,
            "required_terms": list(alignment.required_terms),
            "mapped_terms": list(alignment.mapped_terms),
            "evidence": list(alignment.evidence),
            "semantic_inputs": {
                "slot_alignments": [dict(item) for item in alignment.slot_alignments]
            },
            "metadata": {
                "controlled": alignment.controlled,
                **dict(alignment.metadata),
            },
        }
    return {
        "artifact_version": 1,
        "ontology": {
            "id": dataset.ontology.ontology_id,
            "version": dataset.ontology.version,
        },
        "mapping": {"id": mapping_id, "version": mapping_version},
        "interpretations": interpretations,
    }


def _metrics(
    *,
    selected_question_count: int,
    supported_question_count: int,
    unsupported_question_count: int,
    results: tuple[MainPlannerResult, ...],
) -> ExperimentMetrics:
    metrics = ExperimentMetrics.unavailable(
        "Metric requires later M12 benchmark execution or exhaustive ground truth."
    )
    interpretation = dict(metrics.interpretation)
    physical = dict(metrics.physical_planning)
    end_to_end = dict(metrics.end_to_end)
    interpretation["supported_coverage"] = MetricValue.available(
        supported_question_count / selected_question_count
    )
    interpretation["unsupported_rate"] = MetricValue.available(
        unsupported_question_count / selected_question_count
    )
    candidate_records = tuple(record for result in results for record in result.candidate_records)
    mapping_failures = sum(record.status.startswith("mapping_") for record in candidate_records)
    interpretation["mapping_failure_rate"] = MetricValue.available(
        mapping_failures / max(1, len(candidate_records))
    )
    finite_deviations = [
        record.semantic_deviation.value
        for record in candidate_records
        if record.semantic_deviation is not None and record.semantic_deviation.value is not None
    ]
    if finite_deviations:
        interpretation["semantic_deviation"] = MetricValue.available(
            sum(finite_deviations) / len(finite_deviations)
        )
    generated = sum(
        record.search.generated_count
        for record in candidate_records
        if record.search is not None
    )
    processed = sum(
        record.search.processed_count
        for record in candidate_records
        if record.search is not None
    )
    pruned = sum(
        record.search.pruned_count
        for record in candidate_records
        if record.search is not None
    )
    physical["states_generated"] = MetricValue.available(generated)
    physical["states_processed"] = MetricValue.available(processed)
    physical["states_pruned"] = MetricValue.available(pruned)
    physical["pruning_ratio"] = MetricValue.available(pruned / max(1, generated))
    return ExperimentMetrics(interpretation, physical, end_to_end)


def run_experiment(
    config_path: str | Path,
    *,
    output_root_override: str | Path | None = None,
    run_id_override: str | None = None,
    transport_override: object | None = None,
) -> DevelopmentRunResult:
    repo_root = _repo_root()
    config_file = _resolve(config_path, repo_root)
    spec = ExperimentSpec.load(config_file)
    if run_id_override is not None:
        spec = replace(spec, run_id=run_id_override)
    if spec.baseline.baseline_id is not BaselineId.FULL_XGAP:
        raise NotImplementedError(
            "M12-A freezes baseline contracts but executes full_xgap only."
        )
    if spec.ablations.enabled:
        raise NotImplementedError(
            "M12-A freezes ablation switches but does not execute ablations."
        )

    dataset = DatasetBundle.load(_resolve(spec.dataset_bundle_ref, repo_root))
    model = ModelBundle.load(_resolve(spec.model_bundle_ref, repo_root))
    if dataset.ontology.max_relaxation_hops != spec.semantic_deviation.max_relaxation_hops:
        raise ValueError("Experiment semantic H must match the DatasetBundle ontology H.")
    questions = tuple(dataset.question(question_id) for question_id in spec.question_ids)

    descriptor_dir = _resolve(spec.descriptor_dir, repo_root)
    registry.load_descriptors(descriptor_dir)
    profiles = tuple(registry.get_capability_profile(item) for item in spec.backend_ids)
    extractor = DeterministicStateFeatureExtractor(
        spec.backend_ids,
        optional_stat_names=spec.feature_schema.unavailable_statistics,
    )
    if extractor.extractor_id != spec.feature_schema.extractor_id:
        raise ValueError("Experiment feature extractor ID does not match M11.")
    if extractor.schema_version != spec.feature_schema.version:
        raise ValueError("Experiment feature schema version does not match M11.")
    if extractor.schema_hash != spec.feature_schema.schema_hash:
        raise ValueError("Experiment feature schema hash does not match M11.")
    cost_data = _mapping(spec.cost_estimator, "cost_estimator")
    if str(cost_data.get("type", "")) != "gaussian_process":
        raise ValueError("M12-A reuses the M11 Gaussian-process estimator only.")
    gp_config = GaussianProcessConfig.from_dict(
        _mapping(cost_data.get("config"), "cost_estimator.config")
    )
    estimator = GaussianProcessCostEstimator(
        config=gp_config,
        feature_extractor=extractor,
        observations=(),
    )
    output_root = (
        Path(output_root_override)
        if output_root_override is not None
        else _resolve(spec.output_root, repo_root)
    )
    if model.config.provider != "mock":
        if spec.alignment_provider_id != "file_backed_runtime":
            raise ValueError("Live ModelBundles require file_backed_runtime alignment.")
        from xgap.experiments.live_run import run_live_experiment

        live = run_live_experiment(
            spec=spec,
            dataset=dataset,
            model=model,
            repo_root=repo_root,
            output_root=output_root,
            profiles=profiles,
            extractor=extractor,
            estimator=estimator,
            gp_config=gp_config,
            transport_override=transport_override,
        )
        return DevelopmentRunResult(
            live.run_root,
            live.question_results,
            live.inventory,
            attempted_question_count=len(questions),
        )
    if spec.alignment_provider_id != "controlled_artifact":
        raise ValueError("Mock M12-A ModelBundle requires controlled_artifact alignment.")
    responses = load_mock_responses(model)
    alignment_records = tuple(
        alignment
        for question in questions
        for alignment in dataset.alignments_for(question.question_id)
    )
    alignment_data = _alignment_artifact(dataset, alignment_records)
    alignment_provider = ArtifactOntologyAlignmentProvider(alignment_data)
    planner = XGAPPhysicalPlanner(
        alignment_provider=alignment_provider,
        semantic_scorer=DirectionalOntologySemanticDeviationScorer(
            dataset.ontology,
            spec.semantic_deviation,
        ),
        backend_profiles=profiles,
        exchange_catalog=ExchangeCatalog(strategies=()),
        budget_policy=_budget_policy(spec.budget),
        cost_estimator=estimator,
        physical_compiler=ExistingCompilerAdapter(
            backend_mapping=dataset.backend_mapping
        ),
    )

    layout = RunArtifactLayout.create(output_root, spec.run_id)
    layout.write_json("experiment_spec.json", spec.to_dict())
    layout.write_jsonl("questions.jsonl", (question.to_dict() for question in questions))

    candidate_rows: list[dict[str, Any]] = []
    validation_rows: list[dict[str, Any]] = []
    planner_results: list[MainPlannerResult] = []
    search_rows: list[dict[str, Any]] = []
    supported_count = 0
    unsupported_count = 0
    for task_index, question in enumerate(questions, start=1):
        if question.fragment_support is not FragmentSupport.XGAP_SUPPORTED:
            unsupported_count += 1
            validation_rows.append(
                {
                    "question_id": question.question_id,
                    "ok": False,
                    "stage": "fragment_support",
                    "message": question.fragment_support.value,
                }
            )
            continue
        supported_count += 1
        raw_response = responses.get(question.question_id)
        if raw_response is None:
            raise ValueError(
                f"Mock ModelBundle has no response for supported question '{question.question_id}'."
            )
        response = parse_planner_response(
            raw_response,
            PlannerRequest(question.text, max_candidates=spec.candidate_cap),
        )
        for candidate in response.candidates:
            candidate_row = next(
                item
                for item in response.to_dict()["candidates"]
                if item["candidate_id"] == candidate.candidate_id
            )
            candidate_rows.append(
                {"question_id": question.question_id, **candidate_row}
            )
            report = validate_candidate(candidate)
            validation_rows.append(
                {"question_id": question.question_id, **report.to_dict()}
            )
            if not report.ok:
                raise ValueError(
                    f"Controlled candidate '{candidate.candidate_id}' failed {report.stage}: "
                    f"{report.message}"
                )
        result = planner.plan(
            query_context=QueryPlanningContext(
                query_id=question.question_id,
                task_id=f"{spec.run_id}-task-{task_index}",
                question=question.text,
                metadata={"dataset_id": dataset.dataset_id, "split": question.split},
            ),
            candidates=response.candidates,
            config=PlanningConfig(
                run_id=spec.run_id,
                semantic_threshold=spec.epsilon,
                execution_threshold=spec.execution_threshold,
                top_k=spec.top_k,
                global_delta=spec.global_delta,
                task_index=task_index,
                deterministic_seed=spec.random_seed,
                metadata={"experiment_spec_hash": spec.spec_hash},
            ),
        )
        planner_results.append(result)
        for record in result.candidate_records:
            if record.formatted_logical_plan is not None:
                layout.write_json(
                    f"plans/logical/{question.question_id}__{record.candidate_id}.json",
                    {
                        "schema_version": "m12-logical-plan-artifact-v1",
                        "question_id": question.question_id,
                        "candidate_id": record.candidate_id,
                        "logical_plan_id": record.logical_plan_id,
                        "formatted_plan": record.formatted_logical_plan,
                    },
                )
            if record.search is not None:
                search_rows.extend(
                    {"question_id": question.question_id, **event.to_dict()}
                    for event in record.search.trace
                )
        for selected in result.selected_plans:
            stem = f"{question.question_id}__{selected.candidate_id}"
            layout.write_json(
                f"plans/physical/{stem}.json",
                selected.to_dict(),
            )
            for index, artifact in enumerate(
                selected.physical_plan.realization.compilation.artifacts,
                start=1,
            ):
                extension = {
                    "xgap_logical": "xgap",
                    "cypher": "cypher",
                    "sparql": "rq",
                }.get(artifact.language.lower(), "txt")
                query_path = layout.path(f"queries/{stem}__{index}.{extension}")
                query_path.write_text(artifact.text + "\n", encoding="utf-8")

    results_tuple = tuple(planner_results)
    metrics = _metrics(
        selected_question_count=len(questions),
        supported_question_count=supported_count,
        unsupported_question_count=unsupported_count,
        results=results_tuple,
    )
    initialize_run_contract_files(
        layout,
        spec=spec,
        dataset=dataset,
        model=model,
        metrics=metrics,
    )
    layout.write_jsonl("candidates.jsonl", candidate_rows)
    layout.write_jsonl("validation.jsonl", validation_rows)
    layout.write_jsonl("plans/search_trace.jsonl", search_rows)
    layout.write_json("cost_model.json", estimator.to_dict())
    layout.write_json("feature_schema.json", extractor.to_dict())
    layout.write_jsonl(
        "alignment_results.jsonl",
        (
            {
                "question_id": result.query_id,
                "candidate_id": record.candidate_id,
                "alignment": record.alignment.to_dict(),
                "semantic_deviation": (
                    record.semantic_deviation.to_dict()
                    if record.semantic_deviation is not None
                    else None
                ),
            }
            for result in results_tuple
            for record in result.candidate_records
        ),
    )
    no_execution = {
        "schema_version": "m12-result-status-v1",
        "status": "not_available",
        "reason": "M12-A proves the offline planning artifact path; backend execution belongs to later experiment phases.",
    }
    layout.write_json("results/raw/status.json", no_execution)
    layout.write_json("results/normalized/status.json", no_execution)
    backend_versions = {backend_id: None for backend_id in spec.backend_ids}
    manifest = create_manifest(
        repo_root=repo_root,
        spec=spec,
        dataset=dataset,
        model=model,
        backend_versions=backend_versions,
        estimator={
            "id": estimator.estimator_id,
            "model_version": estimator.model_version,
            "config_hash": content_hash(gp_config.to_dict()),
            "calibration_status": "not_available",
        },
        feature_schema={
            "version": extractor.schema_version,
            "hash": extractor.schema_hash,
            "extractor_id": extractor.extractor_id,
        },
    )
    layout.write_json("experiment_manifest.json", manifest.to_dict())
    layout.write_json(
        "run_summary.json",
        {
            "schema_version": "m12-development-run-summary-v1",
            "run_id": spec.run_id,
            "status": (
                "ok" if all(result.status == "ok" for result in results_tuple) else "partial"
            ),
            "question_count": len(questions),
            "planned_question_count": len(results_tuple),
            "successful_question_count": sum(result.status == "ok" for result in results_tuple),
            "backend_execution": "not_available",
            "phase_boundary": "M12-A controlled development run",
        },
    )
    inventory = layout.inventory()
    if not all((layout.root / relative).exists() for relative in (
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
    )):
        raise RuntimeError("M12 run artifact contract is incomplete.")
    return DevelopmentRunResult(
        layout.root,
        results_tuple,
        inventory,
        attempted_question_count=len(questions),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the offline M12-A XGAP development experiment")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-root")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    result = run_experiment(
        args.config,
        output_root_override=args.output_root,
        run_id_override=args.run_id,
    )
    attempted = result.attempted_question_count or len(result.question_results)
    print(f"M12 development questions: {attempted}")
    print(f"Successful planner questions: {result.successful_question_count}")
    print(f"Run artifacts: {result.run_root}")
    return 0 if result.successful_question_count == attempted else 2


if __name__ == "__main__":
    raise SystemExit(main())
