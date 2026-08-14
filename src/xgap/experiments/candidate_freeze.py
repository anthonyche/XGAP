"""Immutable candidate and grounding artifacts for fair M12-D comparisons."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from xgap.experiments.bundles import (
    DatasetBundle,
    ModelBundle,
    QuestionRecord,
    load_mock_responses,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.runtime_alignment import (
    FileBackedRuntimeAlignmentProvider,
    OntologyArtifactLoader,
    OntologyContextRetriever,
    PromptSchemaViewBuilder,
    assert_no_gold_leakage,
    parse_grounded_planner_response,
)
from xgap.llm.openai_compatible import OpenAICompatibleTransport
from xgap.llm.parser import parse_planner_response
from xgap.llm.schemas import PlannerRequest, PlannerResponse
from xgap.llm.validation import validate_candidate
from xgap.planning import ArtifactOntologyAlignmentProvider, QueryPlanningContext


@dataclass(frozen=True)
class FrozenCandidateArtifact:
    question_id: str
    question: str
    dataset_id: str
    dataset_version: str
    model_id: str
    model_snapshot: str
    model_config_hash: str
    prompt_hash: str
    max_candidates: int
    structured_response: Mapping[str, Any]
    alignment_artifact: Mapping[str, Any]
    prompt_schema_view: Mapping[str, Any] | None = None
    llm_requests: tuple[Mapping[str, Any], ...] = ()
    raw_model_responses: tuple[Mapping[str, Any], ...] = ()
    seed: int | None = None
    seed_supported: bool = False
    controlled: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = "m12d-frozen-candidates-v1"

    def __post_init__(self) -> None:
        if not all(
            (
                self.question_id,
                self.question.strip(),
                self.dataset_id,
                self.dataset_version,
                self.model_id,
                self.model_snapshot,
                self.prompt_hash,
            )
        ):
            raise ValueError("Frozen candidate identity fields must be non-empty.")
        if self.max_candidates <= 0:
            raise ValueError("Frozen candidate max_candidates must be positive.")
        object.__setattr__(self, "structured_response", dict(self.structured_response))
        object.__setattr__(self, "alignment_artifact", dict(self.alignment_artifact))
        if self.prompt_schema_view is not None:
            object.__setattr__(self, "prompt_schema_view", dict(self.prompt_schema_view))
        object.__setattr__(
            self, "llm_requests", tuple(dict(item) for item in self.llm_requests)
        )
        object.__setattr__(
            self,
            "raw_model_responses",
            tuple(dict(item) for item in self.raw_model_responses),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))
        assert_no_gold_leakage(self.to_hash_dict())

    @property
    def candidate_hash(self) -> str:
        return content_hash(self.structured_response)

    @property
    def grounding_hash(self) -> str:
        return content_hash(self.alignment_artifact)

    @property
    def artifact_hash(self) -> str:
        return content_hash(self.to_hash_dict())

    def to_hash_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "question_id": self.question_id,
            "question": self.question,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "model_id": self.model_id,
            "model_snapshot": self.model_snapshot,
            "model_config_hash": self.model_config_hash,
            "prompt_hash": self.prompt_hash,
            "max_candidates": self.max_candidates,
            "structured_response": dict(self.structured_response),
            "alignment_artifact": dict(self.alignment_artifact),
            "prompt_schema_view": (
                dict(self.prompt_schema_view)
                if self.prompt_schema_view is not None
                else None
            ),
            "llm_requests": [dict(item) for item in self.llm_requests],
            "raw_model_responses": [
                dict(item) for item in self.raw_model_responses
            ],
            "seed": self.seed,
            "seed_supported": self.seed_supported,
            "controlled": self.controlled,
            "metadata": dict(self.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.to_hash_dict(),
            "candidate_hash": self.candidate_hash,
            "grounding_hash": self.grounding_hash,
            "artifact_hash": self.artifact_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FrozenCandidateArtifact":
        artifact = cls(
            schema_version=str(data.get("schema_version", "m12d-frozen-candidates-v1")),
            question_id=str(data["question_id"]),
            question=str(data["question"]),
            dataset_id=str(data["dataset_id"]),
            dataset_version=str(data["dataset_version"]),
            model_id=str(data["model_id"]),
            model_snapshot=str(data["model_snapshot"]),
            model_config_hash=str(data["model_config_hash"]),
            prompt_hash=str(data["prompt_hash"]),
            max_candidates=int(data["max_candidates"]),
            structured_response=_mapping(data.get("structured_response"), "structured_response"),
            alignment_artifact=_mapping(data.get("alignment_artifact"), "alignment_artifact"),
            prompt_schema_view=(
                _mapping(data.get("prompt_schema_view"), "prompt_schema_view")
                if data.get("prompt_schema_view") is not None
                else None
            ),
            llm_requests=tuple(
                _mapping(item, "llm_requests[]")
                for item in data.get("llm_requests", ())
            ),
            raw_model_responses=tuple(
                _mapping(item, "raw_model_responses[]")
                for item in data.get("raw_model_responses", ())
            ),
            seed=int(data["seed"]) if data.get("seed") is not None else None,
            seed_supported=bool(data.get("seed_supported", False)),
            controlled=bool(data.get("controlled", False)),
            metadata=_mapping(data.get("metadata", {}), "metadata"),
        )
        checks = {
            "candidate_hash": artifact.candidate_hash,
            "grounding_hash": artifact.grounding_hash,
            "artifact_hash": artifact.artifact_hash,
        }
        for field_name, expected in checks.items():
            if data.get(field_name) not in {None, expected}:
                raise ValueError(f"Frozen candidate {field_name} does not match content.")
        return artifact

    @classmethod
    def load(cls, path: str | Path) -> "FrozenCandidateArtifact":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, Mapping):
            raise ValueError("Frozen candidate artifact root must be an object.")
        return cls.from_dict(data)

    def write(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
        temporary.write_text(
            json.dumps(
                self.to_dict(),
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
        return target

    def planner_response(self) -> PlannerResponse:
        request = PlannerRequest(self.question, max_candidates=self.max_candidates)
        response = parse_planner_response(self.structured_response, request)
        for candidate in response.candidates:
            validation = validate_candidate(candidate)
            if not validation.ok:
                raise ValueError(
                    f"Frozen candidate '{candidate.candidate_id}' failed "
                    f"{validation.stage}: {validation.message}"
                )
        return response

    def alignment_provider(self) -> ArtifactOntologyAlignmentProvider:
        return ArtifactOntologyAlignmentProvider(dict(self.alignment_artifact))


def generate_frozen_candidate_artifact(
    *,
    dataset: DatasetBundle,
    model: ModelBundle,
    question: QuestionRecord,
    backend_ids: tuple[str, ...],
    max_candidates: int,
    task_id: str,
    runtime_grounding: Mapping[str, Any] | None = None,
    transport_override: OpenAICompatibleTransport | None = None,
) -> FrozenCandidateArtifact:
    """Generate once, validate deterministically, and freeze for replay."""

    if model.config.provider == "mock":
        raw = load_mock_responses(model).get(question.question_id)
        if raw is None:
            raise ValueError(f"No mock response exists for '{question.question_id}'.")
        response = parse_planner_response(
            raw, PlannerRequest(question.text, max_candidates=max_candidates)
        )
        _validate_response(response)
        alignment = _controlled_alignment_artifact(
            dataset, question.question_id, tuple(item.candidate_id for item in response.candidates)
        )
        return FrozenCandidateArtifact(
            question_id=question.question_id,
            question=question.text,
            dataset_id=dataset.dataset_id,
            dataset_version=dataset.version,
            model_id=model.config.model_id,
            model_snapshot=model.config.exact_model_snapshot,
            model_config_hash=model.config.config_hash,
            prompt_hash=model.prompt.prompt_hash,
            max_candidates=max_candidates,
            structured_response=raw,
            alignment_artifact=alignment,
            seed=model.config.seed,
            seed_supported=model.config.seed_supported,
            controlled=True,
            metadata={"generation_mode": "controlled_mock"},
        )

    from xgap.experiments.live_run import _provider, _retrieval_limits

    loader = OntologyArtifactLoader.from_dataset(dataset)
    view = PromptSchemaViewBuilder(
        loader,
        OntologyContextRetriever(loader, _retrieval_limits(runtime_grounding or {})),
    ).build(task_id=task_id, question=question.text, backend_ids=backend_ids)
    provider = _provider(model, transport_override)
    request = PlannerRequest(
        question.text,
        max_candidates=min(max_candidates, model.config.candidate_count),
        schema_hints=view.source_schema_items,
        metadata={"task_id": task_id, "prompt_schema_view": view.to_dict()},
    )
    raw = provider.generate_candidates(request)
    response = parse_planner_response(raw, request)
    _validate_response(response)
    grounded = parse_grounded_planner_response(raw, response, view)
    runtime_provider = FileBackedRuntimeAlignmentProvider(
        loader=loader,
        prompt_view=view,
        grounded_response=grounded,
        backend_ids=backend_ids,
    )
    context = QueryPlanningContext(
        query_id=question.question_id,
        task_id=task_id,
        question=question.text,
    )
    alignment = _runtime_alignment_artifact(
        dataset,
        {
            candidate.candidate_id: runtime_provider.resolve(context, candidate)
            for candidate in response.candidates
        },
    )
    invocation = provider.last_invocation
    assert invocation is not None
    return FrozenCandidateArtifact(
        question_id=question.question_id,
        question=question.text,
        dataset_id=dataset.dataset_id,
        dataset_version=dataset.version,
        model_id=model.config.model_id,
        model_snapshot=model.config.exact_model_snapshot,
        model_config_hash=model.config.config_hash,
        prompt_hash=model.prompt.prompt_hash,
        max_candidates=request.max_candidates,
        structured_response=raw,
        alignment_artifact=alignment,
        prompt_schema_view=view.to_dict(),
        llm_requests=invocation.request_records(),
        raw_model_responses=(invocation.to_dict(),),
        seed=model.config.seed,
        seed_supported=model.config.seed_supported,
        controlled=False,
        metadata={"generation_mode": "live_structured", "task_id": task_id},
    )


def _validate_response(response: PlannerResponse) -> None:
    for candidate in response.candidates:
        report = validate_candidate(candidate)
        if not report.ok:
            raise ValueError(
                f"Candidate '{candidate.candidate_id}' failed {report.stage}: {report.message}"
            )


def _controlled_alignment_artifact(
    dataset: DatasetBundle,
    question_id: str,
    candidate_ids: tuple[str, ...],
) -> dict[str, Any]:
    records = {item.candidate_id: item for item in dataset.alignments_for(question_id)}
    missing = set(candidate_ids) - set(records)
    if missing:
        raise ValueError(f"Controlled alignments are missing candidates: {sorted(missing)}")
    mapping_id, mapping_version = _mapping_identity(dataset)
    return {
        "artifact_version": 1,
        "ontology": {"id": dataset.ontology.ontology_id, "version": dataset.ontology.version},
        "mapping": {"id": mapping_id, "version": mapping_version},
        "interpretations": {
            candidate_id: {
                "alignment_id": records[candidate_id].alignment_id,
                "mapping_status": records[candidate_id].mapping_status,
                "required_terms": list(records[candidate_id].required_terms),
                "mapped_terms": list(records[candidate_id].mapped_terms),
                "evidence": list(records[candidate_id].evidence),
                "semantic_inputs": {
                    "slot_alignments": [
                        dict(item) for item in records[candidate_id].slot_alignments
                    ]
                },
                "metadata": {"controlled": True},
            }
            for candidate_id in candidate_ids
        },
    }


def _runtime_alignment_artifact(
    dataset: DatasetBundle,
    contexts: Mapping[str, Any],
) -> dict[str, Any]:
    mapping_id, mapping_version = _mapping_identity(dataset)
    return {
        "artifact_version": 1,
        "ontology": {"id": dataset.ontology.ontology_id, "version": dataset.ontology.version},
        "mapping": {"id": mapping_id, "version": mapping_version},
        "interpretations": {
            candidate_id: {
                "alignment_id": context.alignment_id,
                "mapping_status": context.mapping_sufficiency.status.value,
                "required_terms": list(context.mapping_sufficiency.required_terms),
                "mapped_terms": list(context.mapping_sufficiency.mapped_terms),
                "evidence": list(context.mapping_sufficiency.evidence),
                "reason": context.mapping_sufficiency.reason,
                "aliases": dict(context.aliases),
                "semantic_inputs": dict(context.semantic_inputs),
                "metadata": dict(context.metadata),
            }
            for candidate_id, context in sorted(contexts.items())
        },
    }


def _mapping_identity(dataset: DatasetBundle) -> tuple[str, str]:
    mapping_id = str(dataset.backend_mapping.get("mapping_id", ""))
    mapping_version = str(dataset.backend_mapping.get("version", ""))
    if not mapping_id or not mapping_version:
        raise ValueError("Dataset backend mapping identity is incomplete.")
    return mapping_id, mapping_version


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object.")
    return dict(value)
