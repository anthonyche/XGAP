"""M12-B live structured-model experiment path selected by ModelBundle."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.backends.capabilities import BackendCapabilityProfile
from xgap.experiments.artifacts import (
    RunArtifactLayout,
    create_manifest,
    initialize_run_contract_files,
)
from xgap.experiments.bundles import DatasetBundle, FragmentSupport, ModelBundle
from xgap.experiments.contracts import (
    END_TO_END_METRICS,
    INTERPRETATION_METRICS,
    LIVE_GENERATION_METRICS,
    PHYSICAL_PLANNING_METRICS,
    ExperimentMetrics,
    ExperimentSpec,
    MetricValue,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.runtime_alignment import (
    FileBackedRuntimeAlignmentProvider,
    OntologyArtifactLoader,
    OntologyContextRetriever,
    PromptSchemaViewBuilder,
    RetrievalLimits,
    RuntimeAlignmentError,
    assert_no_gold_leakage,
    parse_grounded_planner_response,
)
from xgap.experiments.semantic import DirectionalOntologySemanticDeviationScorer
from xgap.llm.openai_compatible import (
    LiveFailureCategory,
    LiveInvocationArtifact,
    LiveProviderError,
    OpenAICompatibleProviderConfig,
    OpenAICompatibleStructuredCandidateProvider,
    OpenAICompatibleTransport,
)
from xgap.llm.parser import parse_planner_response
from xgap.llm.schemas import PlannerRequest
from xgap.llm.validation import validate_candidate
from xgap.planning import (
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
class LiveRunArtifacts:
    run_root: Path
    question_results: tuple[MainPlannerResult, ...]
    inventory: tuple[str, ...]


@dataclass
class _LiveCounters:
    generation_attempts: int = 0
    generation_successes: int = 0
    parse_successes: int = 0
    generated_candidates: int = 0
    valid_candidates: int = 0
    grounded_candidates: int = 0
    unresolved_anchor_failures: int = 0
    hallucinated_id_failures: int = 0
    mapping_failures: int = 0
    semantic_inadmissible: int = 0
    repair_calls: int = 0
    latency_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    input_tokens_available: bool = False
    output_tokens_available: bool = False
    total_tokens_available: bool = False

    def add_invocation(self, artifact: LiveInvocationArtifact) -> None:
        self.generation_attempts += int(artifact.generation_calls > 0)
        self.generation_successes += int(artifact.validation_status == "schema_valid")
        self.parse_successes += int(artifact.parse_status == "parsed")
        self.repair_calls += artifact.repair_calls
        self.latency_seconds += artifact.latency_seconds
        usage = artifact.to_dict()["usage"]
        for name in ("input_tokens", "output_tokens", "total_tokens"):
            value = usage[name]
            if value is not None:
                setattr(self, name, getattr(self, name) + int(value))
                setattr(self, f"{name}_available", True)


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
    raise ValueError(f"Unsupported M12-B budget policy '{kind}'.")


def _retrieval_limits(data: Mapping[str, Any]) -> RetrievalLimits:
    return RetrievalLimits(
        max_slots=int(data.get("max_slots", 8)),
        max_candidates_per_slot=int(data.get("max_candidates_per_slot", 4)),
        max_entities=int(data.get("max_entities", 4)),
        max_schema_items=int(data.get("max_schema_items", 12)),
    )


def _provider(
    model: ModelBundle,
    transport_override: OpenAICompatibleTransport | None,
) -> OpenAICompatibleStructuredCandidateProvider:
    config = model.config
    if model.structured_schema is None:
        raise ValueError("Live ModelBundle has no structured output schema.")
    base_url = str(config.base_url)
    if config.base_url_env is not None and config.base_url_env in os.environ:
        base_url = os.environ[config.base_url_env].strip()
        if not base_url:
            raise ValueError(
                f"Configured base URL environment variable '{config.base_url_env}' is blank."
            )
    provider_config = OpenAICompatibleProviderConfig(
        provider_id=config.provider,
        base_url=base_url,
        api_key_env=str(config.api_key_env),
        model=config.exact_model_snapshot,
        temperature=config.temperature,
        top_p=config.top_p,
        max_tokens=int(config.token_limits.get("output", 0)),
        candidate_cap=config.candidate_count,
        timeout_seconds=config.timeout_seconds,
        structured_output_mode=config.structured_output_mode,
        structured_schema=model.structured_schema,
        prompt_hash=model.prompt.prompt_hash,
        seed=config.seed,
        seed_supported=config.seed_supported,
        max_repair_calls=config.max_repair_calls,
        extra_parameters=config.extra_parameters,
    )
    kwargs: dict[str, Any] = {
        "config": provider_config,
        "system_prompt": model.prompt.system_prompt,
    }
    if transport_override is not None:
        kwargs["transport"] = transport_override
    return OpenAICompatibleStructuredCandidateProvider(**kwargs)


def run_live_experiment(
    *,
    spec: ExperimentSpec,
    dataset: DatasetBundle,
    model: ModelBundle,
    repo_root: Path,
    output_root: Path,
    profiles: Sequence[BackendCapabilityProfile],
    extractor: DeterministicStateFeatureExtractor,
    estimator: GaussianProcessCostEstimator,
    gp_config: GaussianProcessConfig,
    transport_override: object | None,
) -> LiveRunArtifacts:
    if model.config.provider == "mock":
        raise ValueError("Live runner requires a non-mock ModelBundle.")
    if transport_override is not None and not hasattr(transport_override, "post_json"):
        raise TypeError("transport_override must implement post_json().")
    questions = tuple(dataset.question(question_id) for question_id in spec.question_ids)
    loader = OntologyArtifactLoader.from_dataset(dataset)
    limits = _retrieval_limits(spec.runtime_grounding)
    retriever = OntologyContextRetriever(loader, limits)
    view_builder = PromptSchemaViewBuilder(loader, retriever)
    provider = _provider(model, transport_override)  # type: ignore[arg-type]
    semantic_scorer = DirectionalOntologySemanticDeviationScorer(
        dataset.ontology,
        spec.semantic_deviation,
    )
    layout = RunArtifactLayout.create(output_root, spec.run_id)
    layout.write_json("experiment_spec.json", spec.to_dict())
    runtime_questions = [
        {
            "schema_version": question.schema_version,
            "question_id": question.question_id,
            "text": question.text,
            "split": question.split,
            "source_benchmark_id": question.source_benchmark_id,
            "fragment_support": question.fragment_support.value,
            "metadata": {
                "inference_view": True,
                "controlled": bool(question.metadata.get("controlled", False)),
            },
        }
        for question in questions
    ]
    assert_no_gold_leakage(runtime_questions)
    layout.write_jsonl("questions.jsonl", runtime_questions)

    candidate_rows: list[dict[str, Any]] = []
    validation_rows: list[dict[str, Any]] = []
    prompt_view_rows: list[dict[str, Any]] = []
    llm_request_rows: list[dict[str, Any]] = []
    raw_model_rows: list[dict[str, Any]] = []
    query_slot_rows: list[dict[str, Any]] = []
    grounding_rows: list[dict[str, Any]] = []
    search_rows: list[dict[str, Any]] = []
    planner_results: list[MainPlannerResult] = []
    counters = _LiveCounters()
    semantic_values: list[float] = []
    supported_count = 0
    unsupported_count = 0

    for task_index, question in enumerate(questions, start=1):
        task_id = f"{spec.run_id}-task-{task_index}"
        if question.fragment_support is not FragmentSupport.XGAP_SUPPORTED:
            unsupported_count += 1
            validation_rows.append(
                {
                    "question_id": question.question_id,
                    "candidate_id": None,
                    "ok": False,
                    "stage": "fragment_support",
                    "failure_category": question.fragment_support.value,
                    "message": "Question is retained but not sent to the live provider.",
                }
            )
            continue
        supported_count += 1
        prompt_view = view_builder.build(
            task_id=task_id,
            question=question.text,
            backend_ids=spec.backend_ids,
        )
        prompt_view_row = {
            "question_id": question.question_id,
            "prompt_schema_view_hash": prompt_view.view_hash,
            "view": prompt_view.to_dict(),
        }
        assert_no_gold_leakage(prompt_view_row)
        prompt_view_rows.append(prompt_view_row)
        if not prompt_view.query_slots:
            counters.unresolved_anchor_failures += 1
            validation_rows.append(
                {
                    "question_id": question.question_id,
                    "candidate_id": None,
                    "ok": False,
                    "stage": "query_anchor_retrieval",
                    "failure_category": LiveFailureCategory.UNRESOLVED_QUERY_ANCHOR.value,
                    "message": "Deterministic retrieval found no query-side ontology slots.",
                }
            )
            continue

        request = PlannerRequest(
            question.text,
            max_candidates=min(spec.candidate_cap, model.config.candidate_count),
            schema_hints=prompt_view.source_schema_items,
            metadata={
                "task_id": task_id,
                "prompt_schema_view": prompt_view.to_dict(),
            },
        )
        assert_no_gold_leakage(request.to_dict())
        try:
            raw_response = provider.generate_candidates(request)
        except LiveProviderError as error:
            counters.add_invocation(error.artifact)
            llm_request_rows.extend(
                {"question_id": question.question_id, **record}
                for record in error.artifact.request_records()
            )
            raw_model_rows.append(
                {"question_id": question.question_id, **error.artifact.to_dict()}
            )
            validation_rows.append(
                {
                    "question_id": question.question_id,
                    "candidate_id": None,
                    "ok": False,
                    "stage": "live_generation",
                    "failure_category": error.category.value,
                    "message": str(error),
                }
            )
            continue
        assert provider.last_invocation is not None
        counters.add_invocation(provider.last_invocation)
        llm_request_rows.extend(
            {"question_id": question.question_id, **record}
            for record in provider.last_invocation.request_records()
        )
        raw_model_rows.append(
            {"question_id": question.question_id, **provider.last_invocation.to_dict()}
        )
        validation_rows.append(
            {
                "question_id": question.question_id,
                "candidate_id": None,
                "ok": True,
                "stage": "structured_parse",
                "failure_category": None,
                "message": "Live response passed bounded structured-output parsing.",
            }
        )
        response = parse_planner_response(raw_response, request)
        counters.generated_candidates += len(response.candidates)

        valid_candidates = []
        response_dict = response.to_dict()
        for candidate in response.candidates:
            candidate_row = next(
                item
                for item in response_dict["candidates"]
                if item["candidate_id"] == candidate.candidate_id
            )
            candidate_rows.append(
                {"question_id": question.question_id, **candidate_row}
            )
            report = validate_candidate(candidate)
            validation_rows.append(
                {
                    "question_id": question.question_id,
                    "failure_category": (
                        None if report.ok else LiveFailureCategory.INVALID_CANDIDATE.value
                    ),
                    **report.to_dict(),
                }
            )
            if report.ok:
                valid_candidates.append(candidate)
                counters.valid_candidates += 1
        if not valid_candidates:
            continue

        try:
            grounded_response = parse_grounded_planner_response(
                raw_response,
                response,
                prompt_view,
            )
        except RuntimeAlignmentError as error:
            if error.category is LiveFailureCategory.UNRESOLVED_QUERY_ANCHOR:
                counters.unresolved_anchor_failures += 1
            if error.category is LiveFailureCategory.HALLUCINATED_ONTOLOGY_ID:
                counters.hallucinated_id_failures += 1
            validation_rows.append(
                {
                    "question_id": question.question_id,
                    "candidate_id": None,
                    "ok": False,
                    "stage": "ontology_grounding_validation",
                    "failure_category": error.category.value,
                    "message": str(error),
                }
            )
            continue
        counters.grounded_candidates += len(grounded_response.grounded_candidates)
        validation_rows.extend(
            {
                "question_id": question.question_id,
                "candidate_id": item.candidate.candidate_id,
                "ok": True,
                "stage": "ontology_grounding_validation",
                "failure_category": None,
                "message": (
                    "Prompt-visible ontology IDs and complete candidate slot coverage validated."
                ),
            }
            for item in grounded_response.grounded_candidates
        )
        query_slot_rows.append(
            {
                "question_id": question.question_id,
                "prompt_schema_view_hash": prompt_view.view_hash,
                "query_anchors": [
                    item.to_dict() for item in grounded_response.query_anchors
                ],
            }
        )

        alignment_provider = FileBackedRuntimeAlignmentProvider(
            loader=loader,
            prompt_view=prompt_view,
            grounded_response=grounded_response,
            backend_ids=spec.backend_ids,
        )
        query_context = QueryPlanningContext(
            query_id=question.question_id,
            task_id=task_id,
            question=question.text,
            metadata={"dataset_id": dataset.dataset_id, "split": question.split},
        )
        for candidate in valid_candidates:
            context = alignment_provider.resolve(query_context, candidate)
            grounding_rows.append(
                {
                    "question_id": question.question_id,
                    **alignment_provider.grounding_record(candidate.candidate_id),
                }
            )
            mapping_ok = context.mapping_sufficiency.sufficient
            counters.mapping_failures += int(not mapping_ok)
            validation_rows.append(
                {
                    "question_id": question.question_id,
                    "candidate_id": candidate.candidate_id,
                    "ok": mapping_ok,
                    "stage": "mapping_sufficiency",
                    "failure_category": (
                        None
                        if mapping_ok
                        else LiveFailureCategory.MISSING_BACKEND_MAPPING.value
                    ),
                    "message": (
                        "Runtime source/backend mapping is sufficient."
                        if mapping_ok
                        else context.mapping_sufficiency.reason
                    ),
                }
            )
            semantic = semantic_scorer.score(query_context, candidate, context)
            admissible = semantic.value is not None and semantic.value <= spec.epsilon
            if semantic.value is not None:
                semantic_values.append(semantic.value)
            counters.semantic_inadmissible += int(not admissible)
            validation_rows.append(
                {
                    "question_id": question.question_id,
                    "candidate_id": candidate.candidate_id,
                    "ok": admissible,
                    "stage": "semantic_deviation",
                    "failure_category": (
                        None
                        if admissible
                        else LiveFailureCategory.SEMANTIC_INADMISSIBLE.value
                    ),
                    "message": semantic.reason or "Finite runtime semantic deviation computed.",
                    "semantic_deviation": semantic.to_dict(),
                }
            )

        planner = XGAPPhysicalPlanner(
            alignment_provider=alignment_provider,
            semantic_scorer=semantic_scorer,
            backend_profiles=tuple(profiles),
            exchange_catalog=ExchangeCatalog(strategies=()),
            budget_policy=_budget_policy(spec.budget),
            cost_estimator=estimator,
            physical_compiler=ExistingCompilerAdapter(
                backend_mapping=dataset.backend_mapping
            ),
        )
        result = planner.plan(
            query_context=query_context,
            candidates=valid_candidates,
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
        _write_plan_artifacts(layout, question.question_id, result, search_rows)
        validation_rows.extend(
            {
                "question_id": question.question_id,
                "candidate_id": record.candidate_id,
                "ok": record.status == "eligible",
                "stage": "m11_planning",
                "failure_category": _planning_failure(record.status),
                "message": record.message,
                "planner_status": record.status,
            }
            for record in result.candidate_records
        )

    results = tuple(planner_results)
    metrics = _live_metrics(
        selected_question_count=len(questions),
        supported_count=supported_count,
        unsupported_count=unsupported_count,
        results=results,
        counters=counters,
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
    layout.write_jsonl("prompt_schema_view.jsonl", prompt_view_rows)
    layout.write_jsonl("llm_requests.jsonl", llm_request_rows)
    layout.write_jsonl("raw_model_responses.jsonl", raw_model_rows)
    layout.write_jsonl("query_slots.jsonl", query_slot_rows)
    layout.write_jsonl("grounding.jsonl", grounding_rows)
    layout.write_jsonl(
        "alignment_results.jsonl",
        (
            {
                "question_id": row["question_id"],
                "candidate_id": row["candidate_id"],
                "alignment": row["alignment"],
            }
            for row in grounding_rows
        ),
    )
    layout.write_jsonl("plans/search_trace.jsonl", search_rows)
    layout.write_json("cost_model.json", estimator.to_dict())
    layout.write_json("feature_schema.json", extractor.to_dict())
    layout.write_json("runtime_ontology_manifest.json", loader.runtime_manifest)
    layout.write_json(
        "live_diagnostics.json",
        {
            "schema_version": "m12-live-diagnostics-v1",
            "failure_taxonomy": [item.value for item in LiveFailureCategory],
            "counters": dict(counters.__dict__),
            "semantic_deviation_values": semantic_values,
            "semantic_deviation_distribution_status": (
                "available" if semantic_values else "not_available"
            ),
        },
    )
    no_execution = {
        "schema_version": "m12-result-status-v1",
        "status": "not_available",
        "reason": "M12-B validates live semantic inputs and planning; measured backend execution belongs to later experiment execution phases.",
    }
    layout.write_json("results/raw/status.json", no_execution)
    layout.write_json("results/normalized/status.json", no_execution)
    manifest = create_manifest(
        repo_root=repo_root,
        spec=spec,
        dataset=dataset,
        model=model,
        backend_versions={backend_id: None for backend_id in spec.backend_ids},
        estimator={
            "id": estimator.estimator_id,
            "model_version": estimator.model_version,
            "config_hash": content_hash(gp_config.to_dict()),
            "calibration_status": "not_available",
            "development_prior": True,
        },
        feature_schema={
            "version": extractor.schema_version,
            "hash": extractor.schema_hash,
            "extractor_id": extractor.extractor_id,
        },
    )
    manifest_data = manifest.to_dict()
    manifest_data["runtime_ontology_alignment"] = loader.runtime_manifest
    manifest_data["live_provider"] = provider.config.safe_dict()
    layout.write_json("experiment_manifest.json", manifest_data)
    required_live_files = (
        "prompt_schema_view.jsonl",
        "llm_requests.jsonl",
        "raw_model_responses.jsonl",
        "query_slots.jsonl",
        "grounding.jsonl",
        "alignment_results.jsonl",
        "live_diagnostics.json",
        "runtime_ontology_manifest.json",
    )
    if not all((layout.root / relative).is_file() for relative in required_live_files):
        raise RuntimeError("M12-B live run artifact contract is incomplete.")
    successful = sum(item.status == "ok" for item in results)
    layout.write_json(
        "run_summary.json",
        {
            "schema_version": "m12-development-run-summary-v1",
            "run_id": spec.run_id,
            "status": "ok" if successful == len(questions) else "partial",
            "question_count": len(questions),
            "planned_question_count": len(results),
            "successful_question_count": successful,
            "backend_execution": "not_available",
            "phase_boundary": "M12-B live structured model and runtime alignment",
        },
    )
    return LiveRunArtifacts(layout.root, results, layout.inventory())


def _write_plan_artifacts(
    layout: RunArtifactLayout,
    question_id: str,
    result: MainPlannerResult,
    search_rows: list[dict[str, Any]],
) -> None:
    for record in result.candidate_records:
        if record.formatted_logical_plan is not None:
            layout.write_json(
                f"plans/logical/{question_id}__{record.candidate_id}.json",
                {
                    "schema_version": "m12-logical-plan-artifact-v1",
                    "question_id": question_id,
                    "candidate_id": record.candidate_id,
                    "logical_plan_id": record.logical_plan_id,
                    "formatted_plan": record.formatted_logical_plan,
                },
            )
        if record.search is not None:
            search_rows.extend(
                {"question_id": question_id, **event.to_dict()}
                for event in record.search.trace
            )
    for selected in result.selected_plans:
        stem = f"{question_id}__{selected.candidate_id}"
        layout.write_json(f"plans/physical/{stem}.json", selected.to_dict())
        for index, artifact in enumerate(
            selected.physical_plan.realization.compilation.artifacts,
            start=1,
        ):
            extension = {
                "xgap_logical": "xgap",
                "cypher": "cypher",
                "sparql": "rq",
            }.get(artifact.language.lower(), "txt")
            path = layout.path(f"queries/{stem}__{index}.{extension}")
            path.write_text(artifact.text + "\n", encoding="utf-8")


def _live_metrics(
    *,
    selected_question_count: int,
    supported_count: int,
    unsupported_count: int,
    results: tuple[MainPlannerResult, ...],
    counters: _LiveCounters,
) -> ExperimentMetrics:
    unavailable = "Metric requires later benchmark execution or exhaustive ground truth."
    interpretation = {name: MetricValue.unavailable(unavailable) for name in INTERPRETATION_METRICS}
    physical = {name: MetricValue.unavailable(unavailable) for name in PHYSICAL_PLANNING_METRICS}
    end_to_end = {name: MetricValue.unavailable(unavailable) for name in END_TO_END_METRICS}
    live = {name: MetricValue.unavailable("No live invocation data was available.") for name in LIVE_GENERATION_METRICS}
    interpretation["supported_coverage"] = MetricValue.available(
        supported_count / max(1, selected_question_count)
    )
    interpretation["unsupported_rate"] = MetricValue.available(
        unsupported_count / max(1, selected_question_count)
    )
    records = tuple(record for result in results for record in result.candidate_records)
    mapping_failures = sum(record.status.startswith("mapping_") for record in records)
    interpretation["mapping_failure_rate"] = MetricValue.available(
        mapping_failures / max(1, len(records))
    )
    deviations = [
        record.semantic_deviation.value
        for record in records
        if record.semantic_deviation is not None and record.semantic_deviation.value is not None
    ]
    if deviations:
        interpretation["semantic_deviation"] = MetricValue.available(
            sum(deviations) / len(deviations)
        )
    generated = sum(record.search.generated_count for record in records if record.search is not None)
    processed = sum(record.search.processed_count for record in records if record.search is not None)
    pruned = sum(record.search.pruned_count for record in records if record.search is not None)
    physical["states_generated"] = MetricValue.available(generated)
    physical["states_processed"] = MetricValue.available(processed)
    physical["states_pruned"] = MetricValue.available(pruned)
    physical["pruning_ratio"] = MetricValue.available(pruned / max(1, generated))

    attempts = max(1, counters.generation_attempts)
    candidates = max(1, counters.generated_candidates)
    live["generation_success_rate"] = MetricValue.available(counters.generation_successes / attempts)
    live["structured_parse_success_rate"] = MetricValue.available(counters.parse_successes / attempts)
    live["candidate_validation_success_rate"] = MetricValue.available(counters.valid_candidates / candidates)
    live["candidates_per_question"] = MetricValue.available(
        counters.generated_candidates / max(1, supported_count)
    )
    live["llm_latency_seconds"] = MetricValue.available(
        counters.latency_seconds / attempts
    )
    live["repair_rate"] = MetricValue.available(counters.repair_calls / attempts)
    live["ontology_grounding_success_rate"] = MetricValue.available(
        counters.grounded_candidates / candidates
    )
    live["unresolved_anchor_rate"] = MetricValue.available(
        counters.unresolved_anchor_failures / max(1, supported_count)
    )
    live["hallucinated_ontology_id_rate"] = MetricValue.available(
        counters.hallucinated_id_failures / max(1, supported_count)
    )
    live["mapping_failure_rate"] = MetricValue.available(counters.mapping_failures / candidates)
    live["semantic_inadmissibility_rate"] = MetricValue.available(
        counters.semantic_inadmissible / candidates
    )
    for name in ("input_tokens", "output_tokens", "total_tokens"):
        if getattr(counters, f"{name}_available"):
            live[name] = MetricValue.available(getattr(counters, name))
    return ExperimentMetrics(interpretation, physical, end_to_end, live)


def _planning_failure(status: str) -> str | None:
    if status == "eligible":
        return None
    if status.startswith("mapping_"):
        return LiveFailureCategory.MISSING_BACKEND_MAPPING.value
    if status.startswith("semantic_") or status == "semantic_threshold_exceeded":
        return LiveFailureCategory.SEMANTIC_INADMISSIBLE.value
    if status == "no_feasible_complete_plan":
        return LiveFailureCategory.COMPILER_UNSUPPORTED.value
    return LiveFailureCategory.INVALID_CANDIDATE.value
