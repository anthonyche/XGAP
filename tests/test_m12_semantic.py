from __future__ import annotations

import math

from xgap.experiments.bundles import DatasetBundle
from xgap.experiments.semantic import (
    DEFAULT_EPSILON_VALUES,
    DirectionalOntologyDeviation,
    SemanticDeviationConfig,
    SlotAlignmentEvidence,
)


def _bundle() -> DatasetBundle:
    return DatasetBundle.load("datasets/financial_risk_dev")


def _config() -> SemanticDeviationConfig:
    return SemanticDeviationConfig(max_relaxation_hops=4)


def _measure(*slots: SlotAlignmentEvidence):
    return DirectionalOntologyDeviation(_bundle().ontology, _config()).evaluate(slots)


def test_semantic_config_defaults_and_round_trip() -> None:
    config = _config()
    parsed = SemanticDeviationConfig.from_dict(config.to_dict())

    assert parsed == config
    assert parsed.epsilon_values == DEFAULT_EPSILON_VALUES
    assert parsed.to_dict()["unrelated_policy"] == "infinity"
    assert parsed.config_hash == config.config_hash


def test_exact_specialization_generalization_and_sibling_penalties() -> None:
    exact = _measure(SlotAlignmentEvidence("s", "Company", "Company"))
    specialization = _measure(
        SlotAlignmentEvidence("s", "Company", "HighRiskCompany")
    )
    generalization = _measure(
        SlotAlignmentEvidence("s", "HighRiskCompany", "Company")
    )
    sibling = _measure(
        SlotAlignmentEvidence("s", "HighRiskCompany", "LowRiskCompany")
    )

    assert exact.finite_value == 0
    assert math.isclose(specialization.finite_value or -1, 1 / 12)
    assert math.isclose(generalization.finite_value or -1, 1 / 6)
    assert math.isclose(sibling.finite_value or -1, 1 / 2)
    assert specialization.finite_value < generalization.finite_value < sibling.finite_value


def test_unrelated_missing_mapping_and_incomplete_slots_are_infinite() -> None:
    unrelated = _measure(SlotAlignmentEvidence("s", "Currency", "Transfer"))
    missing = _measure(
        SlotAlignmentEvidence("s", "Company", None, mapping_available=False)
    )
    incomplete = _measure(
        SlotAlignmentEvidence("s", "Company", "Company", covered=False)
    )

    assert unrelated.is_infinite and unrelated.reason == "unrelated_terms"
    assert missing.is_infinite and missing.reason == "missing_source_mapping"
    assert incomplete.is_infinite and incomplete.reason == "incomplete_slot_coverage"
    assert unrelated.to_dict()["value"] == "infinity"


def test_uniform_slot_aggregation_is_bounded() -> None:
    result = _measure(
        SlotAlignmentEvidence("exact", "Person", "Person"),
        SlotAlignmentEvidence("general", "HighRiskCompany", "Company"),
    )

    assert result.admissible
    assert math.isclose(result.finite_value or -1, 1 / 12)
    assert 0 <= (result.finite_value or -1) <= 1


def test_empty_slot_set_is_not_treated_as_exact() -> None:
    result = DirectionalOntologyDeviation(_bundle().ontology, _config()).evaluate(())

    assert result.is_infinite
    assert result.reason == "no_ontology_slots"

