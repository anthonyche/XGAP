"""Versioned artifact-backed ontology/alignment planning boundary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from xgap.llm.schemas import PlannerCandidate
from xgap.planning.contracts import (
    MappingSufficiencyResult,
    MappingSufficiencyStatus,
    OntologyAlignmentContext,
    QueryPlanningContext,
    SemanticDeviationResult,
    SemanticDeviationStatus,
)


class AlignmentArtifactError(ValueError):
    pass


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise AlignmentArtifactError(f"{field_name} must be a mapping.")
    return dict(value)


@dataclass(frozen=True)
class ArtifactOntologyAlignmentProvider:
    """Controlled artifact adapter; it performs no ontology reasoning."""

    artifact: dict[str, Any]
    provider_id: str = "artifact-ontology-alignment"

    def __post_init__(self) -> None:
        artifact = dict(self.artifact)
        if int(artifact.get("artifact_version", 0)) <= 0:
            raise AlignmentArtifactError("alignment artifact_version must be positive.")
        if not isinstance(artifact.get("interpretations"), Mapping):
            raise AlignmentArtifactError("alignment artifact interpretations must be a mapping.")
        for field_name in ("ontology", "mapping"):
            value = artifact.get(field_name)
            if not isinstance(value, Mapping) or not value.get("id") or not value.get("version"):
                raise AlignmentArtifactError(
                    f"alignment artifact {field_name} must provide id and version."
                )
        object.__setattr__(self, "artifact", artifact)

    @classmethod
    def from_json(cls, path: str | Path) -> "ArtifactOntologyAlignmentProvider":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, Mapping):
            raise AlignmentArtifactError("alignment artifact root must be a mapping.")
        return cls(dict(data))

    def resolve(
        self,
        query_context: QueryPlanningContext,
        interpretation: PlannerCandidate,
    ) -> OntologyAlignmentContext:
        del query_context
        ontology = _mapping(self.artifact.get("ontology"), "ontology")
        mapping = _mapping(self.artifact.get("mapping"), "mapping")
        interpretations = _mapping(self.artifact.get("interpretations"), "interpretations")
        raw = interpretations.get(interpretation.candidate_id)
        if not isinstance(raw, Mapping):
            return OntologyAlignmentContext(
                interpretation_id=interpretation.candidate_id,
                alignment_id=f"missing-{interpretation.candidate_id}",
                ontology_artifact_id=str(ontology.get("id")) if ontology.get("id") else None,
                ontology_version=str(ontology.get("version")) if ontology.get("version") else None,
                mapping_artifact_id=str(mapping.get("id")) if mapping.get("id") else None,
                mapping_version=str(mapping.get("version")) if mapping.get("version") else None,
                mapping_sufficiency=MappingSufficiencyResult(
                    status=MappingSufficiencyStatus.MISSING,
                    reason="No alignment record exists for this interpretation.",
                ),
                metadata={"provider_id": self.provider_id},
            )

        raw_dict = dict(raw)
        try:
            status = MappingSufficiencyStatus(str(raw_dict.get("mapping_status", "missing")))
        except ValueError as error:
            raise AlignmentArtifactError(
                f"Unknown mapping_status for '{interpretation.candidate_id}'."
            ) from error
        sufficiency = MappingSufficiencyResult(
            status=status,
            required_terms=tuple(str(item) for item in raw_dict.get("required_terms", ())),
            mapped_terms=tuple(str(item) for item in raw_dict.get("mapped_terms", ())),
            evidence=tuple(str(item) for item in raw_dict.get("evidence", ())),
            reason=str(raw_dict.get("reason", "")),
        )
        return OntologyAlignmentContext(
            interpretation_id=interpretation.candidate_id,
            alignment_id=str(raw_dict.get("alignment_id", interpretation.candidate_id)),
            ontology_artifact_id=str(ontology.get("id")) if ontology.get("id") else None,
            ontology_version=str(ontology.get("version")) if ontology.get("version") else None,
            mapping_artifact_id=str(mapping.get("id")) if mapping.get("id") else None,
            mapping_version=str(mapping.get("version")) if mapping.get("version") else None,
            mapping_sufficiency=sufficiency,
            aliases=_mapping(raw_dict.get("aliases"), "aliases"),
            semantic_inputs=_mapping(raw_dict.get("semantic_inputs"), "semantic_inputs"),
            metadata={
                "provider_id": self.provider_id,
                "artifact_version": int(self.artifact["artifact_version"]),
                **_mapping(raw_dict.get("metadata"), "metadata"),
            },
        )


@dataclass(frozen=True)
class ProvidedSemanticDeviationScorer:
    """Reads a supplied deviation value; it derives no semantic score."""

    input_field: str = "semantic_deviation"
    scorer_id: str = "provided-semantic-deviation"

    def score(
        self,
        query_context: QueryPlanningContext,
        interpretation: PlannerCandidate,
        semantic_context: OntologyAlignmentContext,
    ) -> SemanticDeviationResult:
        del query_context
        value = semantic_context.semantic_inputs.get(self.input_field)
        if value is None:
            return SemanticDeviationResult(
                interpretation_id=interpretation.candidate_id,
                status=SemanticDeviationStatus.MISSING,
                scorer_id=self.scorer_id,
                reason=f"Semantic input '{self.input_field}' is missing.",
            )
        if isinstance(value, bool) or not isinstance(value, int | float):
            return SemanticDeviationResult(
                interpretation_id=interpretation.candidate_id,
                status=SemanticDeviationStatus.UNSUPPORTED,
                scorer_id=self.scorer_id,
                reason=f"Semantic input '{self.input_field}' must be numeric.",
            )
        return SemanticDeviationResult(
            interpretation_id=interpretation.candidate_id,
            status=SemanticDeviationStatus.AVAILABLE,
            scorer_id=self.scorer_id,
            value=float(value),
            components=_mapping(semantic_context.semantic_inputs.get("components"), "components"),
        )
