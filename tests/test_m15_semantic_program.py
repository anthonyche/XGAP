from __future__ import annotations

import pytest

from xgap.semantic import (
    ConstraintPolicy,
    SemanticConstraint,
    SemanticGraphProgram,
    SemanticHole,
    SemanticHoleKind,
    SemanticOperator,
    SemanticOperatorKind,
    SemanticProgramError,
    SemanticValueKind,
)


def _match(operator_id: str) -> SemanticOperator:
    return SemanticOperator(
        operator_id=operator_id,
        kind=SemanticOperatorKind.MATCH,
        input_ids=(),
        input_kinds=(),
        output_kind=SemanticValueKind.BINDING_SET,
    )


def test_semantic_program_validates_typed_dag_and_required_holes() -> None:
    left = _match("left")
    right = _match("right")
    join = SemanticOperator(
        operator_id="join",
        kind=SemanticOperatorKind.JOIN,
        input_ids=("left", "right"),
        input_kinds=(SemanticValueKind.BINDING_SET, SemanticValueKind.BINDING_SET),
        output_kind=SemanticValueKind.BINDING_SET,
        constraints=(
            SemanticConstraint(
                constraint_id="last-month",
                expression="event_time >= now - P1M",
                policy=ConstraintPolicy.HARD,
            ),
        ),
        required_capabilities=("equality_join",),
    )
    program = SemanticGraphProgram(
        program_id="fund-transfer-risk",
        operators=(left, right, join),
        roots=("join",),
        holes=(
            SemanticHole(
                hole_id="alice",
                kind=SemanticHoleKind.ENTITY,
                mention="Alice",
                candidates=("person:1", "person:2"),
            ),
            SemanticHole(
                hole_id="risk",
                kind=SemanticHoleKind.PREDICATE,
                mention="high risk",
                candidates=("risk:high",),
            ),
        ),
    )

    assert [hole.hole_id for hole in program.unresolved_required_holes] == ["alice"]
    assert program.to_dict()["operators"][-1]["constraints"][0]["policy"] == "hard"


def test_semantic_program_rejects_type_mismatch() -> None:
    source = SemanticOperator(
        operator_id="path",
        kind=SemanticOperatorKind.TRAVERSE,
        input_ids=(),
        input_kinds=(),
        output_kind=SemanticValueKind.PATH_SET,
    )
    project = SemanticOperator(
        operator_id="project",
        kind=SemanticOperatorKind.PROJECT,
        input_ids=("path",),
        input_kinds=(SemanticValueKind.BINDING_SET,),
        output_kind=SemanticValueKind.BINDING_SET,
    )
    with pytest.raises(SemanticProgramError, match="expects 'path'"):
        SemanticGraphProgram("bad-types", (source, project), ("project",))


def test_semantic_program_rejects_cycles() -> None:
    left = SemanticOperator(
        operator_id="left",
        kind=SemanticOperatorKind.FILTER,
        input_ids=("right",),
        input_kinds=(SemanticValueKind.BINDING_SET,),
        output_kind=SemanticValueKind.BINDING_SET,
    )
    right = SemanticOperator(
        operator_id="right",
        kind=SemanticOperatorKind.PROJECT,
        input_ids=("left",),
        input_kinds=(SemanticValueKind.BINDING_SET,),
        output_kind=SemanticValueKind.BINDING_SET,
    )
    with pytest.raises(SemanticProgramError, match="acyclic"):
        SemanticGraphProgram("cycle", (left, right), ("right",))


def test_operator_arity_is_checked() -> None:
    with pytest.raises(SemanticProgramError, match="expects 2 inputs"):
        SemanticOperator(
            operator_id="join",
            kind=SemanticOperatorKind.JOIN,
            input_ids=("only-one",),
            input_kinds=(SemanticValueKind.BINDING_SET,),
            output_kind=SemanticValueKind.BINDING_SET,
        )
