"""Versioned DatasetBundle and ModelBundle loaders for M12 experiments."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from xgap.backends.mapping import normalize_backend_mapping_artifact
from xgap.experiments.hashing import content_hash
from xgap.experiments.semantic import OntologyGraph
from xgap.infrastructure.descriptors import load_yaml_mapping


class FragmentSupport(str, Enum):
    XGAP_SUPPORTED = "xgap_supported"
    COMPILER_UNSUPPORTED = "compiler_unsupported"
    REPRESENTATION_UNSUPPORTED = "representation_unsupported"
    DATASET_MAPPING_FAILURE = "dataset_mapping_failure"


class ArtifactAvailability(str, Enum):
    AVAILABLE = "available"
    NOT_AVAILABLE = "not_available"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class QuestionRecord:
    question_id: str
    text: str
    split: str
    source_benchmark_id: str
    fragment_support: FragmentSupport
    gold_answers: tuple[Any, ...] | None = None
    gold_logical_form: Any | None = None
    ontology_slots: tuple[str, ...] | None = None
    unavailable_fields: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "m12-question-v1"

    def __post_init__(self) -> None:
        if not self.question_id or not self.text.strip() or not self.split:
            raise ValueError("Question ID, text, and split must be non-empty.")
        if not self.source_benchmark_id:
            raise ValueError("Question source_benchmark_id must be non-empty.")
        if self.gold_answers is not None:
            object.__setattr__(self, "gold_answers", tuple(self.gold_answers))
        if self.ontology_slots is not None:
            object.__setattr__(self, "ontology_slots", tuple(self.ontology_slots))
        unavailable = tuple(sorted(set(self.unavailable_fields)))
        if self.gold_answers is None and "gold_answers" not in unavailable:
            unavailable = (*unavailable, "gold_answers")
        if self.gold_logical_form is None and "gold_logical_form" not in unavailable:
            unavailable = (*unavailable, "gold_logical_form")
        object.__setattr__(self, "unavailable_fields", tuple(sorted(unavailable)))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QuestionRecord":
        answers = data.get("gold_answers")
        if answers is not None and not isinstance(answers, list):
            raise ValueError("Question gold_answers must be a list or null.")
        slots = data.get("ontology_slots")
        if slots is not None and not isinstance(slots, list):
            raise ValueError("Question ontology_slots must be a list or null.")
        return cls(
            schema_version=str(data.get("schema_version", "m12-question-v1")),
            question_id=str(data.get("question_id", "")),
            text=str(data.get("text", "")),
            split=str(data.get("split", "")),
            source_benchmark_id=str(data.get("source_benchmark_id", "")),
            fragment_support=FragmentSupport(str(data.get("fragment_support", ""))),
            gold_answers=tuple(answers) if answers is not None else None,
            gold_logical_form=data.get("gold_logical_form"),
            ontology_slots=tuple(str(item) for item in slots) if slots is not None else None,
            unavailable_fields=tuple(str(item) for item in data.get("unavailable_fields", ())),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "question_id": self.question_id,
            "text": self.text,
            "split": self.split,
            "source_benchmark_id": self.source_benchmark_id,
            "fragment_support": self.fragment_support.value,
            "gold_answers": list(self.gold_answers) if self.gold_answers is not None else None,
            "gold_logical_form": self.gold_logical_form,
            "ontology_slots": list(self.ontology_slots) if self.ontology_slots is not None else None,
            "unavailable_fields": list(self.unavailable_fields),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EntityCatalogRecord:
    entity_id: str
    canonical_label: str
    aliases: tuple[str, ...]
    types: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EntityCatalogRecord":
        return cls(
            entity_id=str(data["entity_id"]),
            canonical_label=str(data["canonical_label"]),
            aliases=tuple(str(item) for item in data.get("aliases", ())),
            types=tuple(str(item) for item in data.get("types", ())),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "canonical_label": self.canonical_label,
            "aliases": list(self.aliases),
            "types": list(self.types),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class GoldAlignmentRecord:
    question_id: str
    candidate_id: str
    alignment_id: str
    mapping_status: str
    required_terms: tuple[str, ...]
    mapped_terms: tuple[str, ...]
    evidence: tuple[str, ...]
    slot_alignments: tuple[dict[str, Any], ...]
    controlled: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GoldAlignmentRecord":
        slots = data.get("slot_alignments", [])
        if not isinstance(slots, list) or not all(isinstance(item, Mapping) for item in slots):
            raise ValueError("Gold alignment slot_alignments must be a list of objects.")
        return cls(
            question_id=str(data["question_id"]),
            candidate_id=str(data["candidate_id"]),
            alignment_id=str(data["alignment_id"]),
            mapping_status=str(data["mapping_status"]),
            required_terms=tuple(str(item) for item in data.get("required_terms", ())),
            mapped_terms=tuple(str(item) for item in data.get("mapped_terms", ())),
            evidence=tuple(str(item) for item in data.get("evidence", ())),
            slot_alignments=tuple(dict(item) for item in slots),
            controlled=bool(data.get("controlled", False)),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "candidate_id": self.candidate_id,
            "alignment_id": self.alignment_id,
            "mapping_status": self.mapping_status,
            "required_terms": list(self.required_terms),
            "mapped_terms": list(self.mapped_terms),
            "evidence": list(self.evidence),
            "slot_alignments": [dict(item) for item in self.slot_alignments],
            "controlled": self.controlled,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SchemaSnapshot:
    source: str
    version: str
    content: dict[str, Any]
    content_hash: str
    timestamp: str | None = None
    schema_version: str = "m12-schema-snapshot-v1"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SchemaSnapshot":
        content = data.get("content")
        if not isinstance(content, Mapping):
            raise ValueError("Schema snapshot content must be an object.")
        snapshot = cls(
            schema_version=str(data.get("schema_version", "m12-schema-snapshot-v1")),
            source=str(data.get("source", "")),
            version=str(data.get("version", "")),
            timestamp=str(data["timestamp"]) if data.get("timestamp") is not None else None,
            content=dict(content),
            content_hash=str(data.get("content_hash", "")),
        )
        if not snapshot.source or not snapshot.version:
            raise ValueError("Schema snapshot source and version must be non-empty.")
        expected = content_hash(snapshot.content)
        if snapshot.content_hash != expected:
            raise ValueError("Schema snapshot content_hash does not match content.")
        return snapshot

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "version": self.version,
            "timestamp": self.timestamp,
            "content": dict(self.content),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class DatasetBundle:
    root: Path
    dataset_id: str
    version: str
    name: str
    description: str
    provenance: str
    controlled: bool
    questions: tuple[QuestionRecord, ...]
    ontology: OntologyGraph
    aliases: dict[str, Any]
    entity_catalog: tuple[EntityCatalogRecord, ...]
    backend_mapping: dict[str, Any]
    schema_snapshot: SchemaSnapshot
    gold_alignments: tuple[GoldAlignmentRecord, ...] | None
    fragment_support: dict[str, FragmentSupport]
    artifact_refs: dict[str, str | None]
    unavailable_artifacts: tuple[str, ...]
    backend_load: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "m12-dataset-bundle-v1"

    @classmethod
    def load(cls, root: str | Path) -> "DatasetBundle":
        bundle_root = Path(root)
        metadata = load_yaml_mapping(bundle_root / "dataset.yaml")
        artifacts = _mapping(metadata.get("artifacts"), "dataset.artifacts")
        required_names = tuple(str(item) for item in metadata.get("required_artifacts", ()))
        optional_names = tuple(str(item) for item in metadata.get("optional_artifacts", ()))
        refs: dict[str, str | None] = {}
        unavailable: list[str] = []
        for name in (*required_names, *optional_names):
            value = artifacts.get(name)
            refs[name] = str(value) if value is not None else None
            if value is None:
                if name in required_names:
                    raise ValueError(f"Required dataset artifact '{name}' is unavailable.")
                unavailable.append(name)
                continue
            if not (bundle_root / str(value)).exists():
                if name in required_names:
                    raise FileNotFoundError(bundle_root / str(value))
                unavailable.append(name)

        questions = tuple(
            QuestionRecord.from_dict(item)
            for item in _read_jsonl(_required_path(bundle_root, refs, "questions"))
        )
        if not questions or len({item.question_id for item in questions}) != len(questions):
            raise ValueError("Dataset questions must be non-empty with unique IDs.")
        ontology = OntologyGraph.from_dict(
            load_yaml_mapping(_required_path(bundle_root, refs, "ontology"))
        )
        aliases = _normalize_aliases(
            load_yaml_mapping(_required_path(bundle_root, refs, "aliases"))
        )
        entities = tuple(
            EntityCatalogRecord.from_dict(item)
            for item in _read_jsonl(_required_path(bundle_root, refs, "entity_catalog"))
        )
        backend_mapping = normalize_backend_mapping_artifact(
            load_yaml_mapping(_required_path(bundle_root, refs, "backend_mapping"))
        )
        schema_data = json.loads(
            _required_path(bundle_root, refs, "schema_snapshot").read_text(encoding="utf-8")
        )
        if not isinstance(schema_data, Mapping):
            raise ValueError("schema_snapshot.json must contain an object.")
        schema_snapshot = SchemaSnapshot.from_dict(schema_data)
        fragment_records = _read_jsonl(
            _required_path(bundle_root, refs, "fragment_support")
        )
        fragment_support = {
            str(item["question_id"]): FragmentSupport(str(item["fragment_support"]))
            for item in fragment_records
        }
        if set(fragment_support) != {item.question_id for item in questions}:
            raise ValueError("Fragment-support records must cover every question exactly once.")
        for question in questions:
            if fragment_support[question.question_id] is not question.fragment_support:
                raise ValueError(
                    f"Question '{question.question_id}' fragment-support labels disagree."
                )

        gold_alignments: tuple[GoldAlignmentRecord, ...] | None = None
        gold_ref = refs.get("gold_alignments")
        if gold_ref is not None and "gold_alignments" not in unavailable:
            gold_alignments = tuple(
                GoldAlignmentRecord.from_dict(item)
                for item in _read_jsonl(bundle_root / gold_ref)
            )
        bundle = cls(
            root=bundle_root,
            schema_version=str(metadata.get("schema_version", "m12-dataset-bundle-v1")),
            dataset_id=str(metadata.get("dataset_id", "")),
            version=str(metadata.get("version", "")),
            name=str(metadata.get("name", "")),
            description=str(metadata.get("description", "")),
            provenance=str(metadata.get("provenance", "")),
            controlled=bool(metadata.get("controlled", False)),
            questions=questions,
            ontology=ontology,
            aliases=dict(aliases),
            entity_catalog=entities,
            backend_mapping=dict(backend_mapping),
            schema_snapshot=schema_snapshot,
            gold_alignments=gold_alignments,
            fragment_support=fragment_support,
            artifact_refs=refs,
            unavailable_artifacts=tuple(sorted(set(unavailable))),
            backend_load=_optional_mapping(
                metadata.get("backend_load"), "dataset.backend_load"
            ),
            metadata=_optional_mapping(metadata.get("metadata"), "dataset.metadata"),
        )
        bundle.validate()
        return bundle

    def validate(self) -> None:
        if not self.dataset_id or not self.version or not self.name:
            raise ValueError("DatasetBundle ID, version, and name must be non-empty.")
        if self.ontology.max_relaxation_hops <= 0:
            raise ValueError("DatasetBundle ontology must define positive H.")
        known_terms = set(self.ontology.all_terms)
        for entity in self.entity_catalog:
            if any(term not in known_terms for term in entity.types):
                raise ValueError(f"Entity '{entity.entity_id}' references an unknown ontology type.")
        if self.gold_alignments is not None:
            question_ids = {item.question_id for item in self.questions}
            if any(item.question_id not in question_ids for item in self.gold_alignments):
                raise ValueError("Gold alignment references an unknown question.")
        for backend_id, path_value in self.backend_load.items():
            if not isinstance(path_value, str) or not path_value:
                raise ValueError(f"Backend-load artifact for '{backend_id}' must be a path.")
            if not (self.root / path_value).exists():
                raise FileNotFoundError(self.root / path_value)

    def question(self, question_id: str) -> QuestionRecord:
        for question in self.questions:
            if question.question_id == question_id:
                return question
        raise KeyError(question_id)

    def alignments_for(self, question_id: str) -> tuple[GoldAlignmentRecord, ...]:
        if self.gold_alignments is None:
            return ()
        return tuple(item for item in self.gold_alignments if item.question_id == question_id)

    def to_hash_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "provenance": self.provenance,
            "controlled": self.controlled,
            "artifact_refs": dict(sorted(self.artifact_refs.items())),
            "questions": [item.to_dict() for item in self.questions],
            "ontology_hash": self.ontology.ontology_hash,
            "aliases_hash": content_hash(self.aliases),
            "entity_catalog_hash": content_hash([item.to_dict() for item in self.entity_catalog]),
            "backend_mapping_hash": content_hash(self.backend_mapping),
            "schema_snapshot_hash": self.schema_snapshot.content_hash,
            "gold_alignments_hash": (
                content_hash([item.to_dict() for item in self.gold_alignments])
                if self.gold_alignments is not None
                else None
            ),
            "fragment_support": {
                key: value.value for key, value in sorted(self.fragment_support.items())
            },
            "backend_load": dict(self.backend_load),
            "metadata": dict(self.metadata),
        }

    @property
    def bundle_hash(self) -> str:
        return content_hash(self.to_hash_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.to_hash_dict(),
            "bundle_hash": self.bundle_hash,
            "root": str(self.root),
            "unavailable_artifacts": list(self.unavailable_artifacts),
        }


@dataclass(frozen=True)
class PromptArtifact:
    system_prompt: str
    few_shot_examples: tuple[dict[str, Any], ...]
    schema_context_policy: str
    ontology_context_policy: str
    structured_output_schema: dict[str, Any]
    schema_version: str = "m12-prompt-v1"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PromptArtifact":
        examples = data.get("few_shot_examples", [])
        if not isinstance(examples, list) or not all(isinstance(item, Mapping) for item in examples):
            raise ValueError("Prompt few_shot_examples must be a list of objects.")
        output_schema = data.get("structured_output_schema")
        if not isinstance(output_schema, Mapping):
            raise ValueError("Prompt structured_output_schema must be an object.")
        prompt = cls(
            schema_version=str(data.get("schema_version", "m12-prompt-v1")),
            system_prompt=str(data.get("system_prompt", "")),
            few_shot_examples=tuple(dict(item) for item in examples),
            schema_context_policy=str(data.get("schema_context_policy", "")),
            ontology_context_policy=str(data.get("ontology_context_policy", "")),
            structured_output_schema=dict(output_schema),
        )
        if not prompt.system_prompt.strip():
            raise ValueError("Prompt system_prompt must be non-empty.")
        return prompt

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "system_prompt": self.system_prompt,
            "few_shot_examples": [dict(item) for item in self.few_shot_examples],
            "schema_context_policy": self.schema_context_policy,
            "ontology_context_policy": self.ontology_context_policy,
            "structured_output_schema": dict(self.structured_output_schema),
        }

    @property
    def prompt_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class ModelConfig:
    model_id: str
    version: str
    provider: str
    exact_model_snapshot: str
    endpoint_type: str
    temperature: float
    top_p: float
    candidate_count: int
    structured_output_mode: str
    prompt_ref: str
    prompt_hash: str
    token_limits: dict[str, int]
    seed: int | None
    seed_supported: bool
    mock_responses_ref: str | None = None
    base_url: str | None = None
    base_url_env: str | None = None
    model_env: str | None = None
    api_key_env: str | None = None
    timeout_seconds: float = 60.0
    structured_schema_ref: str | None = None
    structured_schema_hash: str | None = None
    max_repair_calls: int = 0
    extra_parameters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "m12-model-config-v1"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelConfig":
        config = cls(
            schema_version=str(data.get("schema_version", "m12-model-config-v1")),
            model_id=str(data.get("model_id", "")),
            version=str(data.get("version", "")),
            provider=str(data.get("provider", "")),
            exact_model_snapshot=str(data.get("exact_model_snapshot", "")),
            endpoint_type=str(data.get("endpoint_type", "")),
            temperature=float(data.get("temperature", 0.0)),
            top_p=float(data.get("top_p", 1.0)),
            candidate_count=int(data.get("candidate_count", 0)),
            structured_output_mode=str(data.get("structured_output_mode", "")),
            prompt_ref=str(data.get("prompt_ref", "")),
            prompt_hash=str(data.get("prompt_hash", "")),
            token_limits={
                str(key): int(value)
                for key, value in _mapping(data.get("token_limits"), "token_limits").items()
            },
            seed=int(data["seed"]) if data.get("seed") is not None else None,
            seed_supported=bool(data.get("seed_supported", False)),
            mock_responses_ref=(
                str(data["mock_responses_ref"])
                if data.get("mock_responses_ref") is not None
                else None
            ),
            base_url=str(data["base_url"]) if data.get("base_url") is not None else None,
            base_url_env=(
                str(data["base_url_env"])
                if data.get("base_url_env") is not None
                else None
            ),
            model_env=(
                str(data["model_env"])
                if data.get("model_env") is not None
                else None
            ),
            api_key_env=(
                str(data["api_key_env"]) if data.get("api_key_env") is not None else None
            ),
            timeout_seconds=float(data.get("timeout_seconds", 60.0)),
            structured_schema_ref=(
                str(data["structured_schema_ref"])
                if data.get("structured_schema_ref") is not None
                else None
            ),
            structured_schema_hash=(
                str(data["structured_schema_hash"])
                if data.get("structured_schema_hash") is not None
                else None
            ),
            max_repair_calls=int(data.get("max_repair_calls", 0)),
            extra_parameters=dict(data.get("extra_parameters", {})),
            metadata=dict(data.get("metadata", {})),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not all((self.model_id, self.version, self.provider, self.exact_model_snapshot)):
            raise ValueError("Model ID, version, provider, and exact snapshot are required.")
        if not 0 <= self.temperature or not 0 <= self.top_p <= 1:
            raise ValueError("Model temperature must be nonnegative and top_p within [0,1].")
        if self.candidate_count <= 0:
            raise ValueError("Model candidate_count must be positive.")
        if self.seed is not None and not self.seed_supported:
            raise ValueError("Model seed cannot be set when seed_supported is false.")
        if self.provider == "mock" and self.mock_responses_ref is None:
            raise ValueError("Mock ModelBundle requires mock_responses_ref.")
        if self.timeout_seconds <= 0:
            raise ValueError("Model timeout_seconds must be positive.")
        if self.max_repair_calls not in {0, 1}:
            raise ValueError("The bounded protocol permits at most one repair call.")
        if self.provider != "mock":
            if self.endpoint_type != "openai_compatible":
                raise ValueError("M12-B live ModelBundles must use an OpenAI-compatible endpoint.")
            if not self.base_url or not self.api_key_env:
                raise ValueError("Live ModelBundles require base_url and api_key_env.")
            if self.base_url_env is not None and not self.base_url_env.strip():
                raise ValueError("Live ModelBundle base_url_env cannot be blank.")
            if self.model_env is not None and not self.model_env.strip():
                raise ValueError("Live ModelBundle model_env cannot be blank.")
            if not self.structured_schema_ref or not self.structured_schema_hash:
                raise ValueError("Live ModelBundles require a hashed structured schema.")

    def to_hash_dict(self) -> dict[str, Any]:
        value = {
            "schema_version": self.schema_version,
            "model_id": self.model_id,
            "version": self.version,
            "provider": self.provider,
            "exact_model_snapshot": self.exact_model_snapshot,
            "endpoint_type": self.endpoint_type,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "candidate_count": self.candidate_count,
            "structured_output_mode": self.structured_output_mode,
            "prompt_ref": self.prompt_ref,
            "prompt_hash": self.prompt_hash,
            "token_limits": dict(sorted(self.token_limits.items())),
            "seed": self.seed,
            "seed_supported": self.seed_supported,
            "mock_responses_ref": self.mock_responses_ref,
            "base_url": self.base_url,
            "base_url_env": self.base_url_env,
            "api_key_env": self.api_key_env,
            "timeout_seconds": self.timeout_seconds,
            "structured_schema_ref": self.structured_schema_ref,
            "structured_schema_hash": self.structured_schema_hash,
            "max_repair_calls": self.max_repair_calls,
            "extra_parameters": dict(sorted(self.extra_parameters.items())),
            "metadata": dict(self.metadata),
        }
        # Keep hashes of pre-M13-E2 frozen bundles byte-for-byte stable.
        if self.model_env is not None:
            value["model_env"] = self.model_env
        return value

    @property
    def config_hash(self) -> str:
        return content_hash(self.to_hash_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_hash_dict(), "config_hash": self.config_hash}


@dataclass(frozen=True)
class ModelBundle:
    root: Path
    config: ModelConfig
    prompt: PromptArtifact
    structured_schema: dict[str, Any] | None = None

    @classmethod
    def load(cls, root: str | Path) -> "ModelBundle":
        bundle_root = Path(root)
        config_data = json.loads((bundle_root / "model_config.json").read_text(encoding="utf-8"))
        prompt_data = json.loads((bundle_root / "prompt.json").read_text(encoding="utf-8"))
        if not isinstance(config_data, Mapping) or not isinstance(prompt_data, Mapping):
            raise ValueError("ModelBundle JSON roots must be objects.")
        config = ModelConfig.from_dict(config_data)
        prompt = PromptArtifact.from_dict(prompt_data)
        if config.prompt_ref != "prompt.json":
            raise ValueError("ModelBundle prompt_ref must be prompt.json.")
        if config.prompt_hash != prompt.prompt_hash:
            raise ValueError("Model configuration prompt_hash does not match prompt.json.")
        if config.mock_responses_ref is not None and not (bundle_root / config.mock_responses_ref).exists():
            raise FileNotFoundError(bundle_root / config.mock_responses_ref)
        structured_schema: dict[str, Any] | None = None
        if config.structured_schema_ref is not None:
            schema_data = json.loads(
                (bundle_root / config.structured_schema_ref).read_text(encoding="utf-8")
            )
            if not isinstance(schema_data, Mapping):
                raise ValueError("ModelBundle structured schema root must be an object.")
            structured_schema = dict(schema_data)
            if content_hash(structured_schema) != config.structured_schema_hash:
                raise ValueError("Model configuration structured_schema_hash does not match.")
        return cls(bundle_root, config, prompt, structured_schema)

    @property
    def bundle_hash(self) -> str:
        return content_hash(
            {
                "config_hash": self.config.config_hash,
                "prompt_hash": self.prompt.prompt_hash,
                "structured_schema_hash": (
                    content_hash(self.structured_schema)
                    if self.structured_schema is not None
                    else None
                ),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "model_config": self.config.to_dict(),
            "prompt": self.prompt.to_dict(),
            "structured_schema": self.structured_schema,
            "bundle_hash": self.bundle_hash,
        }


def load_mock_responses(bundle: ModelBundle) -> dict[str, dict[str, Any]]:
    if bundle.config.provider != "mock" or bundle.config.mock_responses_ref is None:
        raise NotImplementedError("M12-A loads only mock ModelBundle responses.")
    data = json.loads((bundle.root / bundle.config.mock_responses_ref).read_text(encoding="utf-8"))
    if not isinstance(data, Mapping) or not isinstance(data.get("responses"), Mapping):
        raise ValueError("Mock response artifact must contain a responses mapping.")
    return {
        str(question_id): dict(response)
        for question_id, response in data["responses"].items()
        if isinstance(response, Mapping)
    }


def _read_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, Mapping):
            raise ValueError(f"{path}:{line_number} must contain a JSON object.")
        records.append(dict(value))
    return tuple(records)


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping.")
    return dict(value)


def _optional_mapping(value: object, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    return _mapping(value, field_name)


def _normalize_aliases(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(value)
    for field_name in ("ontology_terms", "relations", "entities"):
        normalized[field_name] = _optional_mapping(
            normalized.get(field_name), f"dataset.aliases.{field_name}"
        )
    return normalized


def _required_path(root: Path, refs: Mapping[str, str | None], name: str) -> Path:
    value = refs.get(name)
    if value is None:
        raise ValueError(f"Required artifact '{name}' is unavailable.")
    return root / value
