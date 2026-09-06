from __future__ import annotations

import json
from pathlib import Path

import pytest

from xgap.semantic import SemanticHoleKind
from xgap.tools import (
    ArtifactCatalogProvider,
    ArtifactOntologyProvider,
    ExplicitUserSelectionProvider,
    ResolutionCandidateRequest,
    ToolContext,
    ToolStatus,
    artifact_catalog_tool,
    artifact_ontology_tool,
    explicit_user_clarification_tool,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG = REPO_ROOT / "experiments/specs/m15_e3_financial_risk_catalog_dev.json"
ONTOLOGY = REPO_ROOT / "experiments/specs/m15_e3_financial_risk_ontology_dev.json"
HASH = "0" * 64
CONTEXT = ToolContext(goal_id="test", step=1, call_id="call-1")


def _request(
    kind: SemanticHoleKind,
    mention: str,
    candidates: tuple[str, ...] = (),
    *,
    maximum: int = 8,
) -> ResolutionCandidateRequest:
    return ResolutionCandidateRequest(
        program_id="program",
        hole_id="hole",
        hole_kind=kind,
        mention=mention,
        candidate_ids=candidates,
        question="controlled request",
        hard_constraints_sha256=HASH,
        max_candidates=maximum,
    )


def test_catalog_exposes_ambiguous_alias_without_identity_authority() -> None:
    provider = ArtifactCatalogProvider(CATALOG)

    response = provider.resolve(
        _request(SemanticHoleKind.ENTITY, "Alice"),
        CONTEXT,
    )

    assert response.candidate_ids == (
        "person:alice-smith",
        "person:alice-jones",
    )
    assert response.authoritative is False
    assert response.external_calls == 0
    assert response.metadata["artifact_sha256"] == provider.artifact_sha256
    assert response.metadata["candidate_set_truncated"] is False


def test_catalog_unique_canonical_entity_can_be_authoritative() -> None:
    response = ArtifactCatalogProvider(CATALOG).resolve(
        _request(SemanticHoleKind.ENTITY, "Alice Smith"),
        CONTEXT,
    )

    assert response.candidate_ids == ("person:alice-smith",)
    assert response.authoritative is True


def test_catalog_refuses_silent_identity_truncation() -> None:
    tool = artifact_catalog_tool(ArtifactCatalogProvider(CATALOG))
    request = _request(SemanticHoleKind.ENTITY, "Alice", maximum=1)

    result = tool.invoke(request.to_dict(), CONTEXT)

    assert result.status is ToolStatus.ERROR
    assert result.metrics["external_calls"] == 0.0
    assert result.metadata["failure_category"] == "candidate_cap_exceeded"


def test_ontology_expands_only_one_hop_with_provenance() -> None:
    provider = ArtifactOntologyProvider(ONTOLOGY)

    response = provider.resolve(
        _request(
            SemanticHoleKind.TYPE,
            "高风险公司",
            ("type:HighRiskCompany",),
        ),
        CONTEXT,
    )

    assert response.candidate_ids == (
        "type:HighRiskCompany",
        "type:MediumRiskCompany",
    )
    assert "type:LowRiskCompany" not in response.candidate_ids
    assert response.authoritative is False
    assert response.external_calls == 0
    assert response.metadata["expansions"] == [
        {
            "source_id": "type:HighRiskCompany",
            "target_id": "type:MediumRiskCompany",
            "relation": "adjacent-risk-level",
            "deviation": 1 / 3,
            "provenance": {
                "evidence": "controlled-development-relation",
                "record_id": "relation-risk-001",
            },
        }
    ]


def test_ontology_never_resolves_entity_identity() -> None:
    tool = artifact_ontology_tool(ArtifactOntologyProvider(ONTOLOGY))
    request = _request(
        SemanticHoleKind.ENTITY,
        "Alice",
        ("person:alice-smith", "person:alice-jones"),
    )

    result = tool.invoke(request.to_dict(), CONTEXT)

    assert result.status is ToolStatus.ERROR
    assert result.metrics["external_calls"] == 0.0
    assert result.metadata["failure_category"] == "unsupported_hole_kind"


def test_ontology_can_ground_an_empty_nonentity_request_from_exact_label() -> None:
    response = ArtifactOntologyProvider(ONTOLOGY).resolve(
        _request(SemanticHoleKind.PREDICATE, "密切资金往来"),
        CONTEXT,
    )

    assert response.candidate_ids == (
        "predicate:transferred_to",
        "predicate:paid_to",
    )
    assert response.metadata["mention_match_candidate_ids"] == [
        "predicate:transferred_to",
        "predicate:paid_to",
    ]


def test_explicit_user_selection_is_bounded_and_authoritative() -> None:
    provider = ExplicitUserSelectionProvider(
        {"hole": "person:alice-smith"},
        source_id="explicit-test-user",
    )
    tool = explicit_user_clarification_tool(provider)
    request = _request(
        SemanticHoleKind.ENTITY,
        "Alice",
        ("person:alice-smith", "person:alice-jones"),
    )

    result = tool.invoke(request.to_dict(), CONTEXT)

    assert result.status is ToolStatus.SUCCESS
    assert result.value["candidate_ids"] == ["person:alice-smith"]
    assert result.value["authoritative"] is True
    assert result.metrics["external_calls"] == 1.0


def test_explicit_user_selection_outside_candidate_set_fails_without_retry() -> None:
    provider = ExplicitUserSelectionProvider(
        {"hole": "person:alice-unknown"},
        source_id="explicit-test-user",
    )
    tool = explicit_user_clarification_tool(provider)
    request = _request(
        SemanticHoleKind.ENTITY,
        "Alice",
        ("person:alice-smith", "person:alice-jones"),
    )

    result = tool.invoke(request.to_dict(), CONTEXT)

    assert result.status is ToolStatus.ERROR
    assert result.metrics["external_calls"] == 0.0
    assert result.metadata["failure_category"] == "out_of_set_user_selection"


def test_artifact_provider_rejects_hash_drift_and_native_text(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        ArtifactCatalogProvider(CATALOG, expected_sha256="f" * 64)

    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    payload["entries"][0]["provenance"]["sparql"] = "SELECT * WHERE {}"
    invalid = tmp_path / "catalog.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="native query text"):
        ArtifactCatalogProvider(invalid)
