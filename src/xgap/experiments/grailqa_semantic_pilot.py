"""Frozen M13-D GrailQA RQ1 semantic-pilot orchestration."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.grailqa_catalog import (
    GrailQAInferenceCatalog,
    RetrievalResult,
    directory_content_hash,
    sha256_file,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.live_run import build_openai_compatible_provider
from xgap.experiments.runtime_alignment import (
    GroundedPlannerResponse,
    PromptSchemaView,
    RuntimeAlignmentError,
    parse_grounded_planner_response,
)
from xgap.experiments.semantic import (
    DirectionalOntologyDeviation,
    SemanticDeviationConfig,
    SlotAlignmentEvidence,
)
from xgap.llm.openai_compatible import LiveProviderError, redact_secrets
from xgap.llm.parser import (
    parse_path_pattern_query,
    parse_planner_response,
    path_pattern_query_to_dict,
)
from xgap.llm.schemas import PlannerRequest
from xgap.llm.validation import validate_candidate
from xgap.pattern.ast import Alt, Bounded, OptionalExpr, Plus, RegexExpr, Rel, Seq, Star


SPEC_SCHEMA_VERSION = "m13d-grailqa-semantic-pilot-spec-v1"
FAILURE_TAXONOMY = (
    "retrieval_miss",
    "generation_miss",
    "malformed_output",
    "type_check_failure",
    "entity_grounding_failure",
    "relation_grounding_failure",
    "semantic_bound_rejection",
    "ranking_failure",
    "equivalence_failure",
)
OUTPUT_FILES = (
    "run_manifest.json",
    "environment.json",
    "readiness.json",
    "retrieval.jsonl",
    "llm_requests.jsonl",
    "llm_responses.jsonl",
    "validated_candidates.jsonl",
    "semantic_scores.jsonl",
    "rankings.jsonl",
    "failures.jsonl",
    "metrics.json",
    "metrics.csv",
    "result_summary.md",
    "progress.json",
)
STRICT_FORBIDDEN_INFERENCE_KEYS = frozenset(
    {
        "gold_answers",
        "gold_answer",
        "gold_logical_form",
        "gold_alignments",
        "gold_alignment",
        "gold_entity_annotation",
        "gold_relation_annotation",
        "evaluation_labels",
        "reference_interpretation",
        "reference_interpretations",
        "canonical_gold_plan",
        "canonical_logical_plan",
        "ontology_slots",
        "answer_column",
        "answer_path_position",
        "q",
        "a",
        "a_recommended",
    }
)


def strict_inference_leakage_audit(value: object) -> None:
    """Fail closed when evaluation-only information reaches inference."""

    def visit(item: object, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                normalized = str(key).strip().casefold()
                if normalized in STRICT_FORBIDDEN_INFERENCE_KEYS or normalized.startswith("gold_"):
                    raise ValueError(
                        f"Evaluation-only field leaked into M13-D inference: {path}{key}"
                    )
                visit(child, f"{path}{key}.")
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}{index}.")

    visit(value, "")


@dataclass(frozen=True)
class GrailQASemanticPilotSpec:
    root: Path
    data: Mapping[str, Any]

    @classmethod
    def load(cls, path: str | Path) -> "GrailQASemanticPilotSpec":
        spec_path = Path(path).resolve()
        data = json.loads(spec_path.read_text(encoding="utf-8"))
        if not isinstance(data, Mapping) or data.get("schema_version") != SPEC_SCHEMA_VERSION:
            raise ValueError("Unsupported M13-D experiment spec schema.")
        instance = cls(spec_path, dict(data))
        instance.validate_shape()
        return instance

    def validate_shape(self) -> None:
        expected = str(self.data.get("freeze_hash", ""))
        payload = {key: value for key, value in self.data.items() if key != "freeze_hash"}
        if content_hash(payload) != expected:
            raise ValueError("Experiment spec freeze_hash does not match canonical content.")
        ids = tuple(str(item) for item in self.data.get("question_ids", ()))
        if len(ids) != 150 or len(set(ids)) != 150:
            raise ValueError("Frozen GrailQA pilot spec must contain exactly 150 unique IDs.")
        if tuple(float(item) for item in self.data.get("epsilon_values", ())) != (
            0.0,
            0.1,
            0.25,
            0.5,
            0.75,
            1.0,
        ):
            raise ValueError("Frozen epsilon grid was modified.")
        if tuple(int(item) for item in self.data.get("m_values", ())) != (1, 3):
            raise ValueError("M values must reflect the frozen M12 candidate cap {1, 3}.")
        if int(self.data.get("candidate_cap", 0)) != 3:
            raise ValueError("M12-B candidate cap must remain three.")
        if tuple(self.data.get("failure_taxonomy", ())) != FAILURE_TAXONOMY:
            raise ValueError("First-failure taxonomy was modified.")
        if tuple(self.data.get("output_schema", ())) != OUTPUT_FILES:
            raise ValueError("Server output schema was modified.")

    @property
    def question_ids(self) -> tuple[str, ...]:
        return tuple(str(item) for item in self.data["question_ids"])

    @property
    def freeze_hash(self) -> str:
        return str(self.data["freeze_hash"])

    @property
    def file_sha256(self) -> str:
        return sha256_file(self.root)

    def resolve(self, repo_root: Path, field: str) -> Path:
        return (repo_root / str(self.data[field])).resolve()


@dataclass(frozen=True)
class GenerationResult:
    structured_response: Mapping[str, Any] | None
    request_records: tuple[Mapping[str, Any], ...]
    response_record: Mapping[str, Any]
    latency_seconds: float
    repair_calls: int
    api_call_completed: bool
    error: str | None = None


class SemanticPilotProvider(Protocol):
    provider_id: str

    def generate(self, request: PlannerRequest, prompt_view: PromptSchemaView) -> GenerationResult: ...


@dataclass
class LiveSemanticPilotProvider:
    model: ModelBundle

    def __post_init__(self) -> None:
        self._provider = build_openai_compatible_provider(self.model)

    @property
    def provider_id(self) -> str:
        return self._provider.provider_id

    def generate(self, request: PlannerRequest, prompt_view: PromptSchemaView) -> GenerationResult:
        del prompt_view
        try:
            response = self._provider.generate_candidates(request)
            invocation = self._provider.last_invocation
            assert invocation is not None
            return GenerationResult(
                structured_response=dict(response),
                request_records=invocation.request_records(),
                response_record=invocation.to_dict(),
                latency_seconds=invocation.latency_seconds,
                repair_calls=invocation.repair_calls,
                api_call_completed=True,
            )
        except LiveProviderError as error:
            invocation = error.artifact
            return GenerationResult(
                structured_response=None,
                request_records=invocation.request_records(),
                response_record=invocation.to_dict(),
                latency_seconds=invocation.latency_seconds,
                repair_calls=invocation.repair_calls,
                api_call_completed=False,
                error=str(error),
            )


@dataclass(frozen=True)
class FakeSemanticPilotProvider:
    model: ModelBundle
    provider_id: str = "m13d-deterministic-fake"

    def generate(self, request: PlannerRequest, prompt_view: PromptSchemaView) -> GenerationResult:
        started = time.perf_counter()
        response = _fake_response(request, prompt_view, self.model.config.candidate_count)
        payload = {
            "model": "deterministic-fake",
            "question": request.question,
            "max_candidates": request.max_candidates,
            "prompt_schema_view": prompt_view.to_dict(),
        }
        request_record = {
            "schema_version": "m13d-fake-request-v1",
            "provider": self.provider_id,
            "model": "deterministic-fake",
            "task_id": prompt_view.task_id,
            "call_index": 1,
            "call_kind": "generation",
            "payload_hash": content_hash(payload),
            "payload": payload,
        }
        elapsed = time.perf_counter() - started
        return GenerationResult(
            structured_response=response,
            request_records=(request_record,),
            response_record={
                "schema_version": "m13d-fake-response-v1",
                "provider": self.provider_id,
                "model": "deterministic-fake",
                "task_id": prompt_view.task_id,
                "structured_response": response,
                "generation_calls": 1,
                "repair_calls": 0,
                "latency_seconds": elapsed,
                "validation_status": "schema_valid",
            },
            latency_seconds=elapsed,
            repair_calls=0,
            api_call_completed=True,
        )


def _fake_response(
    request: PlannerRequest,
    view: PromptSchemaView,
    candidate_cap: int,
) -> dict[str, Any]:
    slots = {item.slot_id: item for item in view.query_slots}
    type_slot = slots["retrieved-type"]
    relation_slot = slots["retrieved-relation"]
    terms = {item.term_id: item for item in view.terms}
    entity_ids = list(view.visible_entity_ids)
    query_slots = [
        {"slot_id": type_slot.slot_id, "query_anchor_id": type_slot.candidate_anchor_ids[0]},
        {
            "slot_id": relation_slot.slot_id,
            "query_anchor_id": relation_slot.candidate_anchor_ids[0],
        },
    ]
    candidates: list[dict[str, Any]] = []
    count = min(request.max_candidates, candidate_cap)
    for index in range(count):
        type_id = type_slot.candidate_anchor_ids[index % len(type_slot.candidate_anchor_ids)]
        relation_id = relation_slot.candidate_anchor_ids[
            index % len(relation_slot.candidate_anchor_ids)
        ]
        relation = terms[relation_id]
        target_type = relation.range if relation.range in terms else type_id
        target_properties = {"type.object.id": entity_ids[index % len(entity_ids)]} if entity_ids else {}
        grounded_entities = [target_properties["type.object.id"]] if target_properties else []
        candidates.append(
            {
                "candidate_id": f"candidate-{index + 1}",
                "confidence": round(1.0 - index * 0.1, 3),
                "rationale": "Deterministic orchestration fixture; no accuracy claim.",
                "pattern_query": {
                    "path_var": "path",
                    "source": {"var": "answer", "label": type_id, "properties": {}},
                    "expr": {
                        "kind": "rel",
                        "edge": {
                            "var": "edge_1",
                            "label": relation_id,
                            "direction": "OUT",
                            "properties": {},
                        },
                    },
                    "target": {
                        "var": "anchor",
                        "label": target_type,
                        "properties": target_properties,
                    },
                    "selector": {"kind": "ALL", "k": None},
                    "restrictor": "SIMPLE",
                    "condition": {
                        "kind": "node_not_equals",
                        "left": {"kind": "node", "position": 1},
                        "right": {"kind": "node", "position": 2},
                    },
                    "max_depth": None,
                },
                "grounding": {
                    "slot_realizations": [
                        {
                            "slot_id": type_slot.slot_id,
                            "ontology_term_id": type_id,
                            "component_ref": "source",
                        },
                        {
                            "slot_id": relation_slot.slot_id,
                            "ontology_term_id": relation_id,
                            "component_ref": "expr.edge",
                        },
                    ],
                    "entity_ids": grounded_entities,
                },
            }
        )
    return {
        "provider_id": "m13d-deterministic-fake",
        "model": "deterministic-fake",
        "query_slots": query_slots,
        "candidates": candidates,
    }


def build_inference_request(
    question_record: Mapping[str, Any],
    retrieval: RetrievalResult,
    prompt_view: PromptSchemaView,
    candidate_cap: int,
) -> PlannerRequest:
    strict_inference_leakage_audit(question_record)
    metadata = {
        "task_id": str(question_record["question_id"]),
        "prompt_schema_view": prompt_view.to_dict(),
        "retrieval_hash": content_hash(retrieval.to_dict()),
        "inference_only": True,
    }
    request = PlannerRequest(
        question=str(question_record["text"]),
        max_candidates=candidate_cap,
        schema_hints=tuple(prompt_view.source_schema_items),
        metadata=metadata,
    )
    strict_inference_leakage_audit(request.to_dict())
    return request


def validate_frozen_artifacts(
    spec: GrailQASemanticPilotSpec,
    repo_root: Path,
) -> tuple[GrailQAInferenceCatalog, ModelBundle]:
    catalog = GrailQAInferenceCatalog.load(spec.resolve(repo_root, "catalog_root"))
    if catalog.catalog_hash != spec.data["catalog_hash"]:
        raise ValueError("Frozen catalog hash does not match experiment spec.")
    if catalog.ontology.ontology_hash != spec.data["ontology_hash"]:
        raise ValueError("Frozen ontology hash does not match experiment spec.")
    pilot_root = spec.resolve(repo_root, "pilot_bundle_root")
    expected_artifacts = spec.data["pilot_artifact_hashes"]
    for name, expected in expected_artifacts.items():
        if sha256_file(pilot_root / name) != expected:
            raise ValueError(f"Frozen pilot artifact hash mismatch: {name}.")
    ids_data = json.loads((pilot_root / "pilot_ids.json").read_text(encoding="utf-8"))
    if tuple(str(item) for item in ids_data["question_ids"]) != spec.question_ids:
        raise ValueError("Frozen pilot IDs do not match the existing M13-C selection.")
    model = ModelBundle.load(spec.resolve(repo_root, "model_bundle_root"))
    if model.bundle_hash != spec.data["model_bundle_hash"]:
        raise ValueError("Frozen model bundle hash mismatch.")
    if model.prompt.prompt_hash != spec.data["prompt_hash"]:
        raise ValueError("Frozen prompt hash mismatch.")
    if model.config.exact_model_snapshot != spec.data["model"]:
        raise ValueError("Frozen model snapshot mismatch.")
    if model.config.candidate_count != int(spec.data["candidate_cap"]):
        raise ValueError("Frozen generation bound mismatch.")
    return catalog, model


def readiness_report(
    spec: GrailQASemanticPilotSpec,
    repo_root: Path,
    output_root: Path,
    *,
    require_credentials: bool,
    require_clean: bool = True,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, action: Any, *, required: bool = True) -> None:
        try:
            detail = action()
            checks.append({"name": name, "status": "pass", "required": required, "detail": detail})
        except Exception as error:  # noqa: BLE001 - readiness reports all boundaries.
            checks.append(
                {"name": name, "status": "fail", "required": required, "detail": str(error)}
            )

    check(
        "python_version",
        lambda: platform.python_version()
        if sys.version_info >= (3, 10)
        else (_ for _ in ()).throw(RuntimeError("Python 3.10+ is required.")),
    )
    check("frozen_artifacts", lambda: validate_frozen_artifacts(spec, repo_root)[0].catalog_hash)
    check("spec_hash", lambda: spec.freeze_hash)
    check("git_commit", lambda: _git(repo_root, "rev-parse", "HEAD"))
    check(
        "git_clean",
        lambda: "clean"
        if not _git(repo_root, "status", "--porcelain")
        else (_ for _ in ()).throw(RuntimeError("Working tree is not clean.")),
        required=require_clean and os.environ.get("XGAP_ALLOW_DIRTY") != "1",
    )

    def output_writable() -> str:
        output_root.mkdir(parents=True, exist_ok=True)
        probe = output_root / ".m13d-write-probe"
        probe.write_text("ok", encoding="ascii")
        probe.unlink()
        return str(output_root)

    check("output_writable", output_writable)
    model = ModelBundle.load(spec.resolve(repo_root, "model_bundle_root"))

    def credentials() -> str:
        env_name = str(model.config.api_key_env)
        if not os.environ.get(env_name):
            raise RuntimeError(f"Required credential environment variable {env_name} is unset.")
        return f"{env_name} is set (value not inspected or persisted)"

    check("qwen_credential", credentials, required=require_credentials)
    checks.append(
        {
            "name": "provider_reachability",
            "status": "not_run",
            "required": False,
            "detail": "The credential-gated 3-query smoke is the reachability check.",
        }
    )
    ready = all(item["status"] == "pass" for item in checks if item["required"])
    return {
        "schema_version": "m13d-readiness-v1",
        "ready": ready,
        "spec_hash": spec.freeze_hash,
        "checks": checks,
        "secret_values_persisted": False,
    }


def run_semantic_pilot(
    *,
    spec_path: str | Path,
    output_root: str | Path,
    repo_root: str | Path,
    dry_run: bool,
    resume: bool,
    max_queries: int | None = None,
    provider_override: SemanticPilotProvider | None = None,
) -> dict[str, Any]:
    repo = Path(repo_root).resolve()
    output = Path(output_root).resolve()
    spec = GrailQASemanticPilotSpec.load(spec_path)
    catalog, model = validate_frozen_artifacts(spec, repo)
    selected_ids = spec.question_ids[:max_queries] if max_queries is not None else spec.question_ids
    if max_queries is not None and max_queries <= 0:
        raise ValueError("--max-queries must be positive.")
    questions = _load_inference_questions(
        spec.resolve(repo, "pilot_bundle_root") / "inference_questions.jsonl",
        selected_ids,
    )
    strict_inference_leakage_audit(questions)
    output.mkdir(parents=True, exist_ok=True)
    state_root = output / ".query_state"
    state_root.mkdir(exist_ok=True)
    readiness = readiness_report(
        spec,
        repo,
        output,
        require_credentials=not dry_run and provider_override is None,
        require_clean=not dry_run,
    )
    _atomic_json(output / "readiness.json", readiness)
    if not readiness["ready"]:
        raise RuntimeError("Server readiness checks failed; inspect readiness.json.")
    git_commit = _git(repo, "rev-parse", "HEAD")
    run_identity = {
        "schema_version": "m13d-grailqa-run-manifest-v1",
        "run_id": str(spec.data["run_id"]) + ("-dry-run" if dry_run else ""),
        "mode": "deterministic_fake" if dry_run else "live_qwen",
        "git_commit": git_commit,
        "spec_path": str(spec.root.relative_to(repo)),
        "spec_sha256": spec.file_sha256,
        "spec_freeze_hash": spec.freeze_hash,
        "pilot_bundle_hash": spec.data["pilot_bundle_hash"],
        "catalog_hash": catalog.catalog_hash,
        "ontology_hash": catalog.ontology.ontology_hash,
        "prompt_hash": model.prompt.prompt_hash,
        "model": "deterministic-fake" if dry_run else model.config.exact_model_snapshot,
        "requested_query_count": len(selected_ids),
        "full_pilot_query_count": len(spec.question_ids),
        "resume_policy": (
            "Skip successful API calls and deterministic terminal retrieval misses; "
            "retry provider failures only."
        ),
        "candidate_generation_reused_across_epsilon": True,
        "secrets_persisted": False,
    }
    manifest_path = output / "run_manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        identity_fields = (
            "run_id",
            "git_commit",
            "spec_freeze_hash",
            "pilot_bundle_hash",
            "catalog_hash",
            "prompt_hash",
            "model",
        )
        if not resume:
            raise FileExistsError("Output already contains a run; pass --resume.")
        if any(previous.get(key) != run_identity.get(key) for key in identity_fields):
            raise ValueError("Resume identity does not match the existing run.")
        run_identity = previous
    else:
        if resume:
            raise FileNotFoundError("Cannot resume: run_manifest.json does not exist.")
        _atomic_json(manifest_path, run_identity)
    environment = {
        "schema_version": "m13d-environment-v1",
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "git_commit": git_commit,
        "git_clean": not bool(_git(repo, "status", "--porcelain")),
        "credential_environment_name": model.config.api_key_env,
        "credential_present": bool(os.environ.get(str(model.config.api_key_env))),
        "credential_value_persisted": False,
    }
    _atomic_json(output / "environment.json", environment)
    provider = provider_override or (
        FakeSemanticPilotProvider(model) if dry_run else LiveSemanticPilotProvider(model)
    )
    semantic_config = SemanticDeviationConfig(
        max_relaxation_hops=catalog.ontology.max_relaxation_hops,
        epsilon_values=tuple(float(item) for item in spec.data["epsilon_values"]),
    )
    semantic = DirectionalOntologyDeviation(catalog.ontology, semantic_config)
    processed = 0
    skipped = 0
    for question in questions:
        question_id = str(question["question_id"])
        state_path = state_root / f"{question_id}.json"
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if state.get("terminal") or state.get("api_call_completed"):
                skipped += 1
                continue
        state = _infer_one(
            question=question,
            catalog=catalog,
            provider=provider,
            semantic=semantic,
            retrieval_k=int(spec.data["retrieval_k"]),
            candidate_cap=int(spec.data["candidate_cap"]),
        )
        _atomic_json(state_path, state)
        processed += 1
        _atomic_json(
            output / "progress.json",
            {
                "schema_version": "m13d-progress-v1",
                "processed_this_invocation": processed,
                "skipped_on_resume": skipped,
                "state_records": len(list(state_root.glob("*.json"))),
                "target_queries": len(questions),
                "last_question_id": question_id,
            },
        )

    states = [_read_json(state_root / f"{question_id}.json") for question_id in selected_ids]
    if len(states) != len(selected_ids):
        raise RuntimeError("Not every selected pilot query has a state record.")
    evaluated = _evaluate_after_inference(states, spec, repo)
    _write_outputs(output, evaluated, run_identity, spec)
    summary = (output / "result_summary.md").read_text(encoding="utf-8")
    return {
        "output_root": str(output),
        "query_count": len(selected_ids),
        "processed_this_invocation": processed,
        "skipped_on_resume": skipped,
        "metrics": evaluated["metrics"],
        "summary": summary,
    }


def _infer_one(
    *,
    question: Mapping[str, Any],
    catalog: GrailQAInferenceCatalog,
    provider: SemanticPilotProvider,
    semantic: DirectionalOntologyDeviation,
    retrieval_k: int,
    candidate_cap: int,
    response_parser: Callable[[Mapping[str, Any], PlannerRequest], Any] = parse_planner_response,
) -> dict[str, Any]:
    strict_inference_leakage_audit(question)
    started = time.perf_counter()
    retrieval = catalog.retrieve(
        str(question["question_id"]), str(question["text"]), top_k=retrieval_k
    )
    retrieval_latency = time.perf_counter() - started
    retrieval_row = {**retrieval.to_dict(), "latency_seconds": retrieval_latency}
    if not retrieval.types or not retrieval.relations:
        return _failed_state(
            question,
            retrieval_row,
            "retrieval_miss",
            "No bounded type or relation context was available.",
            terminal=True,
        )
    view = catalog.prompt_view(retrieval)
    request = build_inference_request(question, retrieval, view, candidate_cap)
    strict_inference_leakage_audit(request.to_dict())
    generation = provider.generate(request, view)
    if generation.structured_response is None:
        return {
            **_failed_state(
                question,
                retrieval_row,
                "malformed_output",
                generation.error or "Provider request failed.",
                terminal=False,
            ),
            "request_records": [dict(item) for item in generation.request_records],
            "response_record": dict(generation.response_record),
            "llm_latency_seconds": generation.latency_seconds,
            "repair_calls": generation.repair_calls,
            "api_call_completed": False,
        }
    strict_inference_leakage_audit(
        {
            "question": question,
            "request": request.to_dict(),
            "prompt_view": view.to_dict(),
        }
    )
    deterministic_started = time.perf_counter()
    try:
        parsed = response_parser(generation.structured_response, request)
    except Exception as error:  # noqa: BLE001
        return _generation_failed_state(
            question, retrieval_row, generation, "malformed_output", str(error)
        )
    if not parsed.candidates:
        return _generation_failed_state(
            question,
            retrieval_row,
            generation,
            "generation_miss",
            "Structured response contained no candidates.",
        )
    try:
        grounded = parse_grounded_planner_response(
            generation.structured_response, parsed, view
        )
    except RuntimeAlignmentError as error:
        category = (
            "entity_grounding_failure"
            if "Entity" in str(error)
            else "relation_grounding_failure"
        )
        return _generation_failed_state(
            question, retrieval_row, generation, category, str(error)
        )
    candidate_rows: list[dict[str, Any]] = []
    semantic_rows: list[dict[str, Any]] = []
    first_candidate_failure: tuple[str, str] | None = None
    for candidate in parsed.candidates:
        validation = validate_candidate(candidate)
        row = {
            "question_id": question["question_id"],
            "candidate_id": candidate.candidate_id,
            "candidate_index": len(candidate_rows) + 1,
            "pattern_query": path_pattern_query_to_dict(candidate.pattern_query),
            "confidence": candidate.confidence,
            "validation": validation.to_dict(),
            "grounded": False,
            "semantic_admissible": False,
        }
        if not validation.ok:
            if first_candidate_failure is None:
                first_candidate_failure = ("type_check_failure", validation.message)
            candidate_rows.append(row)
            continue
        grounded_candidate = grounded.candidate(candidate.candidate_id)
        entity_error = _entity_grounding_error(candidate.pattern_query, grounded_candidate.entity_ids, view)
        if entity_error:
            if first_candidate_failure is None:
                first_candidate_failure = ("entity_grounding_failure", entity_error)
            row["grounding_error"] = entity_error
            candidate_rows.append(row)
            continue
        relation_error = _relation_grounding_error(candidate.pattern_query, grounded_candidate)
        if relation_error:
            if first_candidate_failure is None:
                first_candidate_failure = ("relation_grounding_failure", relation_error)
            row["grounding_error"] = relation_error
            candidate_rows.append(row)
            continue
        row["grounded"] = True
        anchors = {item.slot_id: item.query_anchor_id for item in grounded.query_anchors}
        measurement = semantic.evaluate(
            tuple(
                SlotAlignmentEvidence(
                    slot_id=item.slot_id,
                    query_term=anchors[item.slot_id],
                    aligned_term=item.ontology_term_id,
                    metadata={"component_ref": item.component_ref},
                )
                for item in grounded_candidate.slot_realizations
            )
        )
        row["semantic_admissible"] = measurement.admissible
        row["semantic_deviation"] = measurement.finite_value
        candidate_rows.append(row)
        semantic_rows.append(
            {
                "question_id": question["question_id"],
                "candidate_id": candidate.candidate_id,
                "measurement": measurement.to_dict(),
            }
        )
    deterministic_latency = time.perf_counter() - deterministic_started
    finite = [item for item in candidate_rows if item.get("semantic_admissible")]
    failure: dict[str, Any] | None = None
    if not finite:
        category, message = first_candidate_failure or (
            "semantic_bound_rejection",
            "No candidate had finite c_sem.",
        )
        failure = _failure(question["question_id"], category, message)
    return {
        "schema_version": "m13d-query-state-v1",
        "question": dict(question),
        "retrieval": retrieval_row,
        "request_records": [dict(item) for item in generation.request_records],
        "response_record": dict(generation.response_record),
        "structured_response": dict(generation.structured_response),
        "prompt_view": view.to_dict(),
        "candidates": candidate_rows,
        "semantic_scores": semantic_rows,
        "failure": failure,
        "retrieval_latency_seconds": retrieval_latency,
        "llm_latency_seconds": generation.latency_seconds,
        "deterministic_latency_seconds": deterministic_latency,
        "repair_calls": generation.repair_calls,
        "provider_id": provider.provider_id,
        "api_call_completed": generation.api_call_completed,
        "terminal": True,
    }


def _failed_state(
    question: Mapping[str, Any],
    retrieval: Mapping[str, Any],
    category: str,
    message: str,
    *,
    terminal: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "m13d-query-state-v1",
        "question": dict(question),
        "retrieval": dict(retrieval),
        "request_records": [],
        "response_record": {},
        "structured_response": None,
        "prompt_view": None,
        "candidates": [],
        "semantic_scores": [],
        "failure": _failure(str(question["question_id"]), category, message),
        "retrieval_latency_seconds": retrieval.get("latency_seconds", 0.0),
        "llm_latency_seconds": 0.0,
        "deterministic_latency_seconds": 0.0,
        "repair_calls": 0,
        "api_call_completed": False,
        "terminal": terminal,
    }


def _generation_failed_state(
    question: Mapping[str, Any],
    retrieval: Mapping[str, Any],
    generation: GenerationResult,
    category: str,
    message: str,
) -> dict[str, Any]:
    return {
        **_failed_state(question, retrieval, category, message, terminal=True),
        "request_records": [dict(item) for item in generation.request_records],
        "response_record": dict(generation.response_record),
        "structured_response": (
            dict(generation.structured_response)
            if generation.structured_response is not None
            else None
        ),
        "llm_latency_seconds": generation.latency_seconds,
        "repair_calls": generation.repair_calls,
        "api_call_completed": generation.api_call_completed,
    }


def _failure(question_id: str, category: str, message: str) -> dict[str, Any]:
    if category not in FAILURE_TAXONOMY:
        raise ValueError(f"Unknown M13-D failure category {category}.")
    return {
        "schema_version": "m13d-first-failure-v1",
        "question_id": question_id,
        "category": category,
        "message": message,
    }


def _entity_grounding_error(query: Any, entity_ids: Sequence[str], view: PromptSchemaView) -> str | None:
    used = {
        str(value)
        for pattern in (query.source, query.target)
        for key, value in pattern.properties.items()
        if key == "type.object.id"
    }
    if not used:
        return None
    visible = set(view.visible_entity_ids)
    declared = set(entity_ids)
    missing = used - visible
    if missing:
        return f"Candidate uses non-retrieved entity IDs: {sorted(missing)}"
    undeclared = used - declared
    if undeclared:
        return f"Candidate omitted grounded entity IDs: {sorted(undeclared)}"
    return None


def _relation_grounding_error(query: Any, grounded: Any) -> str | None:
    component_terms = {
        item.component_ref: item.ontology_term_id for item in grounded.slot_realizations
    }
    for component_ref, label in _regex_relation_components(query.expr, "expr"):
        if component_ref in component_terms and component_terms[component_ref] != label:
            return (
                f"Relation component {component_ref} uses {label}, but grounding declares "
                f"{component_terms[component_ref]}."
            )
    return None


def _regex_relation_components(expr: RegexExpr, path: str) -> tuple[tuple[str, str | None], ...]:
    if isinstance(expr, Rel):
        return ((f"{path}.edge", expr.edge.label),)
    if isinstance(expr, (Seq, Alt)):
        return (
            *_regex_relation_components(expr.left, f"{path}.left"),
            *_regex_relation_components(expr.right, f"{path}.right"),
        )
    if isinstance(expr, (Plus, Star, OptionalExpr, Bounded)):
        return _regex_relation_components(expr.child, f"{path}.child")
    raise TypeError(type(expr).__name__)


def canonical_interpretation(value: Mapping[str, Any]) -> dict[str, Any]:
    """Canonical structural equivalence key; variable spelling is immaterial."""

    def scrub(item: object, key: str | None = None) -> Any:
        if isinstance(item, Mapping):
            return {
                str(child_key): scrub(child, str(child_key))
                for child_key, child in sorted(item.items())
                if str(child_key) not in {"var", "path_var"}
            }
        if isinstance(item, list):
            return [scrub(child) for child in item]
        if key in {"label", "kind", "direction", "restrictor"} and isinstance(item, str):
            return item.strip()
        return item

    return scrub(value)


def reference_supported(
    generated: Mapping[str, Any], reference: Mapping[str, Any]
) -> bool:
    return content_hash(canonical_interpretation(generated)) == content_hash(
        canonical_interpretation(reference)
    )


def _evaluate_after_inference(
    states: list[dict[str, Any]],
    spec: GrailQASemanticPilotSpec,
    repo: Path,
) -> dict[str, Any]:
    """Open evaluation-only files only after every inference state is present."""

    pilot = spec.resolve(repo, "pilot_bundle_root")
    references = {
        item["question_id"]: item for item in _read_jsonl(pilot / "reference_interpretations.jsonl")
    }
    workload = {item["question_id"]: item for item in _read_jsonl(pilot / "workload_stats.jsonl")}
    retrieval_rows: list[dict[str, Any]] = []
    request_rows: list[dict[str, Any]] = []
    response_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    semantic_rows: list[dict[str, Any]] = []
    ranking_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    evaluations: list[dict[str, Any]] = []
    epsilons = tuple(float(item) for item in spec.data["epsilon_values"])
    for state in states:
        question_id = str(state["question"]["question_id"])
        retrieval = dict(state["retrieval"])
        gold_terms = _reference_terms(references[question_id]["pattern_query"])
        retrieval["post_inference_gold_diagnostics"] = _retrieval_diagnostics(
            retrieval, gold_terms
        )
        retrieval_rows.append(retrieval)
        request_rows.extend(state.get("request_records", ()))
        if state.get("response_record"):
            response_rows.append(dict(state["response_record"]))
        reference_pattern = references[question_id]["pattern_query"]
        evaluated_candidates: list[dict[str, Any]] = []
        for candidate in state.get("candidates", ()):
            row = dict(candidate)
            row["reference_supported"] = reference_supported(
                row["pattern_query"], reference_pattern
            )
            evaluated_candidates.append(row)
            candidate_rows.append(row)
        semantic_rows.extend(state.get("semantic_scores", ()))
        ranking_by_epsilon: dict[str, list[dict[str, Any]]] = {}
        ranking_error: str | None = None
        try:
            for epsilon in epsilons:
                admissible = [
                    item
                    for item in evaluated_candidates
                    if item.get("semantic_admissible")
                    and item.get("semantic_deviation") is not None
                    and float(item["semantic_deviation"]) <= epsilon
                ]
                admissible.sort(
                    key=lambda item: (
                        float(item["semantic_deviation"]),
                        -float(item["confidence"] or 0.0),
                        content_hash(item["pattern_query"]),
                        item["candidate_id"],
                    )
                )
                ranking_by_epsilon[str(epsilon)] = [
                    {
                        "rank": index,
                        "candidate_id": item["candidate_id"],
                        "semantic_deviation": item["semantic_deviation"],
                        "reference_supported": item["reference_supported"],
                    }
                    for index, item in enumerate(admissible, 1)
                ]
        except Exception as error:  # noqa: BLE001
            ranking_error = str(error)
        ranking_row = {
            "schema_version": "m13d-ranking-v1",
            "question_id": question_id,
            "candidate_generation_reused": True,
            "rankings_by_epsilon": ranking_by_epsilon,
        }
        ranking_rows.append(ranking_row)
        failure = state.get("failure")
        if ranking_error:
            failure = _failure(question_id, "ranking_failure", ranking_error)
        elif failure is None and not any(
            item.get("reference_supported") for item in evaluated_candidates
        ):
            failure = _failure(
                question_id,
                "equivalence_failure",
                "No generated interpretation matched the frozen structural reference.",
            )
        if failure is not None:
            failures.append(dict(failure))
        evaluations.append(
            {
                "question_id": question_id,
                "Q": int(workload[question_id]["Q"]),
                "A": int(workload[question_id]["A_recommended"]),
                "candidates": evaluated_candidates,
                "rankings_by_epsilon": ranking_by_epsilon,
                "failure": failure,
                "retrieval_diagnostics": retrieval["post_inference_gold_diagnostics"],
                "repair_calls": int(state.get("repair_calls", 0)),
                "provider_id": str(state.get("provider_id", "")),
                "api_call_completed": bool(state.get("api_call_completed")),
                "latencies": {
                    "retrieval": float(state.get("retrieval_latency_seconds", 0.0)),
                    "llm": float(state.get("llm_latency_seconds", 0.0)),
                    "deterministic": float(state.get("deterministic_latency_seconds", 0.0)),
                },
            }
        )
    metrics = aggregate_metrics(evaluations, spec)
    return {
        "retrieval": retrieval_rows,
        "requests": request_rows,
        "responses": response_rows,
        "candidates": candidate_rows,
        "semantic": semantic_rows,
        "rankings": ranking_rows,
        "failures": failures,
        "evaluations": evaluations,
        "metrics": metrics,
    }


def _reference_terms(pattern: Mapping[str, Any]) -> dict[str, set[str]]:
    entities: set[str] = set()
    types = {
        str(item["label"])
        for item in (pattern["source"], pattern["target"])
        if item.get("label") is not None
    }
    for item in (pattern["source"], pattern["target"]):
        value = item.get("properties", {}).get("type.object.id")
        if value is not None:
            entities.add(str(value))

    def relations(expr: Mapping[str, Any]) -> set[str]:
        if expr["kind"] == "rel":
            label = expr["edge"].get("label")
            return {str(label)} if label is not None else set()
        if expr["kind"] in {"seq", "alt"}:
            return relations(expr["left"]) | relations(expr["right"])
        return relations(expr["child"])

    return {"entity": entities, "relation": relations(pattern["expr"]), "type": types}


def _retrieval_diagnostics(
    retrieval: Mapping[str, Any], gold: Mapping[str, set[str]]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for kind, field in (
        ("entity", "entity_candidates"),
        ("relation", "relation_candidates"),
        ("type", "type_candidates"),
    ):
        ranked = [str(item["id"]) for item in retrieval[field]]
        gold_ids = set(gold[kind])
        result[kind] = {
            "gold_count": len(gold_ids),
            "recall": {
                str(k): (len(gold_ids & set(ranked[:k])) / len(gold_ids) if gold_ids else None)
                for k in (1, 5, 10, 20)
            },
        }
    return result


def aggregate_metrics(
    evaluations: Sequence[Mapping[str, Any]], spec: GrailQASemanticPilotSpec
) -> dict[str, Any]:
    count = len(evaluations)
    epsilons = tuple(float(item) for item in spec.data["epsilon_values"])
    m_values = tuple(int(item) for item in spec.data["m_values"])

    def mean(values: Sequence[float]) -> float | None:
        return sum(values) / len(values) if values else None

    retrieval: dict[str, Any] = {}
    for kind in ("entity", "relation", "type"):
        retrieval[kind] = {
            f"recall@{k}": mean(
                [
                    float(value)
                    for item in evaluations
                    if (
                        value := item["retrieval_diagnostics"][kind]["recall"][str(k)]
                    )
                    is not None
                ]
            )
            for k in (1, 5, 10, 20)
        }
    generated = [candidate for item in evaluations for candidate in item["candidates"]]
    completed = sum(bool(item["api_call_completed"]) for item in evaluations)
    repairs = sum(int(item["repair_calls"]) for item in evaluations)
    semantic_metrics: dict[str, Any] = {}
    for epsilon in epsilons:
        rankings = [item["rankings_by_epsilon"].get(str(epsilon), []) for item in evaluations]
        semantic_metrics[str(epsilon)] = {
            "top_1_interpretation_accuracy": (
                sum(bool(rows and rows[0]["reference_supported"]) for rows in rankings) / count
                if count
                else None
            ),
            "feasible_coverage": sum(bool(rows) for rows in rankings) / count if count else None,
            "average_admissible_candidate_count": (
                sum(len(rows) for rows in rankings) / count if count else None
            ),
        }
    m_sensitivity: dict[str, Any] = {}
    for m in m_values:
        slices = [item["candidates"][:m] for item in evaluations]
        m_sensitivity[str(m)] = {
            "candidate_recall": (
                sum(any(candidate["reference_supported"] for candidate in rows) for rows in slices)
                / count
                if count
                else None
            ),
            "valid_rate": (
                sum(candidate["validation"]["ok"] for rows in slices for candidate in rows)
                / sum(len(rows) for rows in slices)
                if sum(len(rows) for rows in slices)
                else None
            ),
            "grounded_rate": (
                sum(candidate["grounded"] for rows in slices for candidate in rows)
                / sum(len(rows) for rows in slices)
                if sum(len(rows) for rows in slices)
                else None
            ),
        }
    q_stratified: dict[str, Any] = {}
    for q in (13, 19, 25):
        group = [item for item in evaluations if item["Q"] == q]
        q_stratified[str(q)] = {
            "count": len(group),
            "candidate_recall": (
                sum(any(c["reference_supported"] for c in item["candidates"]) for item in group)
                / len(group)
                if group
                else None
            ),
            "top_1_accuracy": {
                str(epsilon): (
                    sum(
                        bool(
                            item["rankings_by_epsilon"].get(str(epsilon))
                            and item["rankings_by_epsilon"][str(epsilon)][0][
                                "reference_supported"
                            ]
                        )
                        for item in group
                    )
                    / len(group)
                    if group
                    else None
                )
                for epsilon in epsilons
            },
            "feasible_coverage": {
                str(epsilon): (
                    sum(bool(item["rankings_by_epsilon"].get(str(epsilon))) for item in group)
                    / len(group)
                    if group
                    else None
                )
                for epsilon in epsilons
            },
        }
    failure_counts = Counter(
        item["failure"]["category"] for item in evaluations if item["failure"] is not None
    )
    return {
        "schema_version": "m13d-grailqa-semantic-metrics-v1",
        "measurement_status": (
            "orchestration_only_no_accuracy_claim"
            if evaluations
            and all(item.get("provider_id") == "m13d-deterministic-fake" for item in evaluations)
            else "pilot_measurement"
        ),
        "query_count": count,
        "retrieval": retrieval,
        "generation": {
            "completed_requests": completed,
            "failed_requests": count - completed,
            "repair_count": repairs,
            "structured_valid_rate": completed / count if count else None,
        },
        "candidate": {
            "candidate_recall": (
                sum(any(c["reference_supported"] for c in item["candidates"]) for item in evaluations)
                / count
                if count
                else None
            ),
            "generated_candidate_count": len(generated),
            "grounded_candidate_rate": (
                sum(bool(item["grounded"]) for item in generated) / len(generated)
                if generated
                else None
            ),
            "admissible_candidate_rate": (
                sum(bool(item["semantic_admissible"]) for item in generated) / len(generated)
                if generated
                else None
            ),
        },
        "semantic_by_epsilon": semantic_metrics,
        "m_sensitivity": m_sensitivity,
        "q_stratified": q_stratified,
        "ambiguity": {
            "decision": "exclude",
            "recommendation": "C",
            "reported_metrics": False,
            "reason": "A(u) is an ontology-neighborhood count, not a validated query ambiguity measure.",
        },
        "first_failure_taxonomy": {
            name: failure_counts.get(name, 0) for name in FAILURE_TAXONOMY
        },
        "latency_seconds": {
            kind: {
                "mean": mean([float(item["latencies"][kind]) for item in evaluations]),
                "total": sum(float(item["latencies"][kind]) for item in evaluations),
            }
            for kind in ("retrieval", "llm", "deterministic")
        },
    }


def _write_outputs(
    output: Path,
    evaluated: Mapping[str, Any],
    manifest: Mapping[str, Any],
    spec: GrailQASemanticPilotSpec,
) -> None:
    _atomic_jsonl(output / "retrieval.jsonl", evaluated["retrieval"])
    _atomic_jsonl(output / "llm_requests.jsonl", evaluated["requests"])
    _atomic_jsonl(output / "llm_responses.jsonl", evaluated["responses"])
    _atomic_jsonl(output / "validated_candidates.jsonl", evaluated["candidates"])
    _atomic_jsonl(output / "semantic_scores.jsonl", evaluated["semantic"])
    _atomic_jsonl(output / "rankings.jsonl", evaluated["rankings"])
    _atomic_jsonl(output / "failures.jsonl", evaluated["failures"])
    _atomic_json(output / "metrics.json", evaluated["metrics"])
    _write_metrics_csv(output / "metrics.csv", evaluated["metrics"])
    summary = render_result_summary(manifest, evaluated["metrics"], output, spec)
    _atomic_text(output / "result_summary.md", summary)
    _atomic_json(
        output / "progress.json",
        {
            "schema_version": "m13d-progress-v1",
            "status": "complete",
            "query_count": evaluated["metrics"]["query_count"],
            "accounted_query_count": len(evaluated["evaluations"]),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def render_result_summary(
    manifest: Mapping[str, Any],
    metrics: Mapping[str, Any],
    output: Path,
    spec: GrailQASemanticPilotSpec,
) -> str:
    lines = [
        "# GrailQA Semantic Pilot Result Summary",
        "",
        "## A. Run Identity",
        f"- Git commit: `{manifest['git_commit']}`",
        f"- Spec SHA-256: `{manifest['spec_sha256']}`",
        f"- Spec freeze hash: `{manifest['spec_freeze_hash']}`",
        f"- Catalog hash: `{manifest['catalog_hash']}`",
        f"- Model: `{manifest['model']}`",
        f"- Query count: {metrics['query_count']}",
        "",
        "## B. Retrieval Recall@k",
    ]
    for kind, values in metrics["retrieval"].items():
        lines.append(f"- {kind}: " + ", ".join(f"{key}={_fmt(value)}" for key, value in values.items()))
    generation = metrics["generation"]
    lines.extend(
        [
            "",
            "## C. Model Execution",
            f"- Successes: {generation['completed_requests']}",
            f"- Failures: {generation['failed_requests']}",
            f"- Repairs: {generation['repair_count']}",
            "",
            "## D. Candidate Recall",
            f"- Candidate Recall: {_fmt(metrics['candidate']['candidate_recall'])}",
            f"- Grounded candidate rate: {_fmt(metrics['candidate']['grounded_candidate_rate'])}",
            f"- Admissible candidate rate: {_fmt(metrics['candidate']['admissible_candidate_rate'])}",
            "",
            "## E. Top-1 Accuracy By Epsilon",
        ]
    )
    for epsilon, values in metrics["semantic_by_epsilon"].items():
        lines.append(f"- epsilon={epsilon}: {_fmt(values['top_1_interpretation_accuracy'])}")
    lines.extend(["", "## F. Feasible Coverage By Epsilon"])
    for epsilon, values in metrics["semantic_by_epsilon"].items():
        lines.append(f"- epsilon={epsilon}: {_fmt(values['feasible_coverage'])}")
    lines.extend(["", "## G. M Sensitivity"])
    for m, values in metrics["m_sensitivity"].items():
        lines.append(
            f"- M={m}: recall={_fmt(values['candidate_recall'])}, "
            f"valid={_fmt(values['valid_rate'])}, grounded={_fmt(values['grounded_rate'])}"
        )
    lines.extend(["", "## H. Q-Stratified Results"])
    for q, values in metrics["q_stratified"].items():
        lines.append(
            f"- Q={q}: n={values['count']}, candidate_recall={_fmt(values['candidate_recall'])}"
        )
    lines.extend(["", "## I. First-Failure Taxonomy"])
    for category, value in metrics["first_failure_taxonomy"].items():
        lines.append(f"- {category}: {value}")
    lines.extend(["", "## J. Latency Summary"])
    for kind, values in metrics["latency_seconds"].items():
        lines.append(f"- {kind}: mean={_fmt(values['mean'])}s, total={_fmt(values['total'])}s")
    lines.extend(
        [
            "",
            "## K. Raw Artifacts",
            *[f"- `{output / name}`" for name in spec.data["output_schema"]],
            "",
        ]
    )
    return "\n".join(lines)


def _write_metrics_csv(path: Path, metrics: Mapping[str, Any]) -> None:
    rows: list[tuple[str, str, Any]] = []

    def visit(prefix: str, value: object) -> None:
        if isinstance(value, Mapping):
            for key, child in sorted(value.items()):
                visit(f"{prefix}.{key}" if prefix else str(key), child)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            section, _, metric = prefix.partition(".")
            rows.append((section, metric, value))

    visit("", metrics)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("section", "metric", "value"))
        writer.writerows(rows)
    os.replace(temp, path)


def _load_inference_questions(path: Path, ids: Sequence[str]) -> list[dict[str, Any]]:
    by_id = {str(item["question_id"]): item for item in _read_jsonl(path)}
    missing = set(ids) - set(by_id)
    if missing:
        raise ValueError(f"Inference-only question artifact is missing IDs: {sorted(missing)}")
    rows = [by_id[item] for item in ids]
    strict_inference_leakage_audit(rows)
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"Expected JSON object: {path}")
    return dict(value)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(value, encoding="utf-8")
    os.replace(temp, path)


def _atomic_json(path: Path, value: object) -> None:
    _atomic_text(path, json.dumps(redact_secrets(value), indent=2, sort_keys=True) + "\n")


def _atomic_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> None:
    _atomic_text(
        path,
        "".join(
            json.dumps(redact_secrets(dict(item)), sort_keys=True, ensure_ascii=True) + "\n"
            for item in values
        ),
    )


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", *args), cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _fmt(value: object) -> str:
    if value is None:
        return "not_available"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)
