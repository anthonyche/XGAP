from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from xgap.experiments.m15_parameterized_query import (
    PARAMETERIZED_QUERY_CONTRACT_SCHEMA_VERSION,
    M15ParameterizedQueryError,
    compile_m15_parameterized_query,
    compile_m15_parameterized_query_file,
    main,
    write_m15_parameterized_query_contract,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = (
    REPO_ROOT
    / "experiments/configs/m15_f2c_parameterized_financial_risk_v2.json"
)


def _payload() -> dict[str, object]:
    return json.loads(SPEC.read_text(encoding="utf-8"))


def _constraints(contract) -> list[dict[str, object]]:
    return [
        constraint
        for operator in contract.to_dict()["typed_program"]["operators"]
        for constraint in operator["constraints"]
    ]


def test_selected_v2_policy_materializes_typed_dag_and_separates_constraints() -> None:
    contract = compile_m15_parameterized_query_file(SPEC)
    payload = contract.to_dict()

    assert payload["schema_version"] == PARAMETERIZED_QUERY_CONTRACT_SCHEMA_VERSION
    assert len(payload["family_compatibility_sha256"]) == 64
    assert len(payload["query_instance_sha256"]) == 64
    assert len(payload["typed_program_sha256"]) == 64
    assert contract.typed_program.roots == ("answer-projection",)
    assert contract.typed_program.unresolved_required_holes == ()
    constraints = _constraints(contract)
    assert [item["policy"] for item in constraints].count("hard") == 3
    assert [item["policy"] for item in constraints].count("relaxable") == 3
    assert {
        item["constraint_id"] for item in constraints if item["policy"] == "hard"
    } == {
        "resolved-person-identity",
        "time-lower-bound",
        "amount-lower-bound",
    }
    assert {
        item["constraint_id"]
        for item in constraints
        if item["policy"] == "relaxable"
    } == {"risk-level", "transfer-predicate", "path-shape"}
    assert all(
        item["policy"] == "hard"
        for item in constraints
        if item["constraint_id"] in {
            "resolved-person-identity",
            "time-lower-bound",
            "amount-lower-bound",
        }
    )
    by_id = {
        item["operator_id"]: item
        for item in payload["typed_program"]["operators"]
    }
    assert by_id["resolved-person"]["parameters"]["entity_id"] == (
        "person-alice-smith"
    )
    assert by_id["recent-large-transfers"]["parameters"] == {
        "path_shape": "direct",
        "predicate": "transfer_to_company",
    }
    assert by_id["risk-matched-companies"]["parameters"]["risk"] == "HIGH"
    assert payload["claim_boundary"] == {
        "artifact_class": "unexecuted_parameterized_query_contract",
        "backend_query_templates_bound": False,
        "workload_bundle_bound": False,
        "oracles_bound": False,
        "backend_calls_made": 0,
        "llm_calls_made": 0,
        "ontology_calls_made": 0,
        "contains_measurements": False,
        "paper_result": False,
    }
    assert payload["paper_result"] is False


def test_binding_changes_preserve_family_and_change_instance() -> None:
    first = compile_m15_parameterized_query(_payload())
    changed = _payload()
    changed["query_id"] = "financial-risk-bob-medium-risk-v2"
    changed["resolved_intent"] = "The same typed family with different bindings."
    values = {item["slot_id"]: item for item in changed["binding_slots"]}
    values["person-identity"]["value"] = "person-bob-jones"
    values["time-lower-bound"]["value"] = "2026-07-01"
    values["amount-lower-bound"]["value"] = 75000
    values["risk-level"]["value"] = "MEDIUM"
    second = compile_m15_parameterized_query(changed)

    assert first.family_hash == second.family_hash
    assert first.to_dict()["binding_sha256"] != second.to_dict()["binding_sha256"]
    assert first.to_dict()["typed_program_sha256"] != second.to_dict()[
        "typed_program_sha256"
    ]
    assert first.instance_hash != second.instance_hash


def test_query_label_and_intent_are_provenance_not_instance_identity() -> None:
    first = compile_m15_parameterized_query(_payload())
    renamed = _payload()
    renamed["query_id"] = "renamed-query-label"
    renamed["resolved_intent"] = "Equivalent semantics with revised prose."
    second = compile_m15_parameterized_query(renamed)

    assert first.family_hash == second.family_hash
    assert first.to_dict()["binding_sha256"] == second.to_dict()["binding_sha256"]
    assert first.to_dict()["typed_program_sha256"] == second.to_dict()[
        "typed_program_sha256"
    ]
    assert first.instance_hash == second.instance_hash


def test_nonsemantic_order_and_template_label_do_not_change_hashes() -> None:
    first = compile_m15_parameterized_query(_payload())
    reordered = _payload()
    reordered["semantic_template"]["template_id"] = "renamed-template-label"
    reordered["binding_slots"].reverse()
    reordered["artifact_interfaces"].reverse()
    reordered["candidate_strategy_ids"].reverse()
    reordered["semantic_template"]["operators"].reverse()
    for operator in reordered["semantic_template"]["operators"]:
        operator["constraints"].reverse()
        operator["required_capabilities"].reverse()
    second = compile_m15_parameterized_query(reordered)

    assert first.family_hash == second.family_hash
    assert first.to_dict()["binding_sha256"] == second.to_dict()["binding_sha256"]
    assert first.to_dict()["typed_program_sha256"] == second.to_dict()[
        "typed_program_sha256"
    ]
    assert first.instance_hash == second.instance_hash


def test_constraint_policy_is_part_of_family_identity() -> None:
    selected = compile_m15_parameterized_query(_payload())
    hard_risk = _payload()
    risk = next(
        constraint
        for operator in hard_risk["semantic_template"]["operators"]
        for constraint in operator["constraints"]
        if constraint["constraint_id"] == "risk-level"
    )
    risk["policy"] = "hard"
    risk["relaxation"] = None
    alternative = compile_m15_parameterized_query(hard_risk)

    assert selected.family_hash != alternative.family_hash
    assert next(
        item
        for item in _constraints(alternative)
        if item["constraint_id"] == "risk-level"
    )["policy"] == "hard"


@pytest.mark.parametrize(
    ("constraint_id", "policy", "relaxation", "message"),
    [
        (
            "resolved-person-identity",
            "hard",
            {
                "transformations": ["ontology_sibling"],
                "max_steps": 1,
                "deviation_metric": "semantic_deviation",
            },
            "hard constraint cannot declare relaxation",
        ),
        ("risk-level", "relaxable", None, "requires a relaxation contract"),
    ],
)
def test_constraint_policy_and_relaxation_must_agree(
    constraint_id: str,
    policy: str,
    relaxation: object,
    message: str,
) -> None:
    payload = _payload()
    selected = next(
        constraint
        for operator in payload["semantic_template"]["operators"]
        for constraint in operator["constraints"]
        if constraint["constraint_id"] == constraint_id
    )
    selected["policy"] = policy
    selected["relaxation"] = relaxation

    with pytest.raises(M15ParameterizedQueryError, match=message):
        compile_m15_parameterized_query(payload)


def test_semantic_binding_and_artifact_binding_require_exact_coverage() -> None:
    semantic = _payload()
    semantic["semantic_template"]["operators"][3]["parameters"]["risk"] = "HIGH"
    risk_constraint = semantic["semantic_template"]["operators"][3]["constraints"][0]
    risk_constraint["expression_template"] = "risk is preferred"
    risk_constraint["binding_slot_ids"] = []
    with pytest.raises(
        M15ParameterizedQueryError, match="semantic.*coverage mismatch"
    ):
        compile_m15_parameterized_query(semantic)

    artifact = _payload()
    artifact["artifact_interfaces"][2]["binding_parameters"] = {}
    artifact["artifact_interfaces"][2]["parameter_schema"]["risk_level"][
        "required"
    ] = False
    with pytest.raises(
        M15ParameterizedQueryError, match="artifact.*coverage mismatch"
    ):
        compile_m15_parameterized_query(artifact)


def test_artifact_binding_parameter_requires_declared_schema() -> None:
    payload = _payload()
    payload["artifact_interfaces"][2]["binding_parameters"] = {
        "undeclared_parameter": "risk-level"
    }

    with pytest.raises(M15ParameterizedQueryError, match="has no schema"):
        compile_m15_parameterized_query(payload)


def test_artifact_binding_stage_is_enforced() -> None:
    payload = _payload()
    full = payload["artifact_interfaces"][0]
    full["parameter_schema"]["person_id"]["binding_stage"] = (
        "runtime_intermediate"
    )

    with pytest.raises(
        M15ParameterizedQueryError, match="cannot use runtime_intermediate"
    ):
        compile_m15_parameterized_query(payload)


def test_artifact_binding_type_must_match_slot_kind() -> None:
    payload = _payload()
    full = payload["artifact_interfaces"][0]
    full["parameter_schema"]["amount_gte"]["type"] = "string"

    with pytest.raises(
        M15ParameterizedQueryError, match="incompatible with binding slot"
    ):
        compile_m15_parameterized_query(payload)


def test_required_nonintermediate_artifact_parameters_must_be_bound() -> None:
    payload = _payload()
    full = payload["artifact_interfaces"][0]
    del full["binding_parameters"]["amount_gte"]

    with pytest.raises(
        M15ParameterizedQueryError, match="required binding parameters"
    ):
        compile_m15_parameterized_query(payload)


def test_typed_dag_and_root_projection_are_validated() -> None:
    typed = _payload()
    typed["semantic_template"]["operators"][5]["input_kinds"][0] = "scalar"
    with pytest.raises(
        M15ParameterizedQueryError, match="expects 'align-transfer-company'"
    ):
        compile_m15_parameterized_query(typed)

    projection = _payload()
    projection["semantic_template"]["operators"][-1]["parameters"]["fields"] = [
        "person"
    ]
    with pytest.raises(
        M15ParameterizedQueryError, match="disagree with output_fields"
    ):
        compile_m15_parameterized_query(projection)


def test_binding_types_are_enforced() -> None:
    payload = _payload()
    date_slot = next(
        item
        for item in payload["binding_slots"]
        if item["slot_id"] == "time-lower-bound"
    )
    date_slot["value"] = "2026-02-30"

    with pytest.raises(M15ParameterizedQueryError, match="ISO-8601"):
        compile_m15_parameterized_query(payload)


def test_unknown_placeholder_fails_before_program_materialization() -> None:
    payload = _payload()
    payload["semantic_template"]["operators"][0]["parameters"]["entity_id"] = {
        "$binding": "unknown-person"
    }

    with pytest.raises(M15ParameterizedQueryError, match="unknown binding slot"):
        compile_m15_parameterized_query(payload)


def test_file_write_cli_and_symlink_boundaries(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    contract = compile_m15_parameterized_query_file(SPEC)
    output = tmp_path / "contract.json"
    write_m15_parameterized_query_contract(contract, output)
    assert json.loads(output.read_text(encoding="utf-8")) == contract.to_dict()
    with pytest.raises(FileExistsError, match="exists"):
        write_m15_parameterized_query_contract(contract, output)

    assert main(["--spec", str(SPEC)]) == 0
    assert json.loads(capsys.readouterr().out) == contract.to_dict()

    linked = tmp_path / "linked.json"
    linked.symlink_to(SPEC)
    with pytest.raises(M15ParameterizedQueryError, match="non-symbolic-link"):
        compile_m15_parameterized_query_file(linked)
