"""Offline M15-E1 demo: identity clarification plus bounded semantics."""

from __future__ import annotations

import json
from dataclasses import dataclass

from xgap.agent import (
    GoalLoop,
    SelectiveResolutionConfig,
    SelectiveSemanticResolutionPolicy,
    build_selective_resolution_goal,
    selective_resolution_environment,
)
from xgap.semantic import (
    ConstraintPolicy,
    SemanticConstraint,
    SemanticGraphProgram,
    SemanticHole,
    SemanticHoleKind,
    SemanticOperator,
    SemanticOperatorKind,
    SemanticValueKind,
)
from xgap.tools import (
    ResolutionCandidateRequest,
    ResolutionCandidateResponse,
    ResolutionCandidateTool,
    ToolContext,
    ToolEffect,
    ToolRegistry,
    USER_CLARIFY_TOOL,
)


@dataclass(frozen=True)
class DemoClarifier:
    def resolve(
        self,
        request: ResolutionCandidateRequest,
        context: ToolContext,
    ) -> ResolutionCandidateResponse:
        del context
        return ResolutionCandidateResponse(
            hole_id=request.hole_id,
            candidate_ids=("person:alice-smith",),
            source_id="demo-user-confirmation",
            authoritative=True,
            external_calls=1,
        )


def main() -> None:
    match = SemanticOperator(
        operator_id="recent-transfers",
        kind=SemanticOperatorKind.MATCH,
        input_ids=(),
        input_kinds=(),
        output_kind=SemanticValueKind.BINDING_SET,
        constraints=(
            SemanticConstraint(
                "one-month",
                "occurred_on >= 2026-08-01",
                ConstraintPolicy.HARD,
            ),
        ),
    )
    program = SemanticGraphProgram(
        "m15-e1-demo",
        (match,),
        ("recent-transfers",),
        holes=(
            SemanticHole(
                "person",
                SemanticHoleKind.ENTITY,
                "Alice",
                candidates=("person:alice-smith", "person:alice-jones"),
            ),
            SemanticHole(
                "risk",
                SemanticHoleKind.PREDICATE,
                "high risk",
                candidates=("risk:HIGH", "risk:MEDIUM"),
            ),
        ),
    )
    registry = ToolRegistry()
    registry.register(
        ResolutionCandidateTool(
            name=USER_CLARIFY_TOOL,
            description="Ask the user to select one bounded entity identity",
            provider=DemoClarifier(),
            may_introduce_candidates=False,
            effect=ToolEffect.EXTERNAL,
            maximum_external_calls=1,
        )
    )
    config = SelectiveResolutionConfig(
        use_catalog=False,
        use_ontology=False,
        use_llm=False,
    )
    state = GoalLoop().run(
        build_selective_resolution_goal(program, config),
        SelectiveSemanticResolutionPolicy(
            program,
            "Find recent transfers from Alice to high-risk companies.",
            config,
        ),
        selective_resolution_environment(registry),
    )
    print(json.dumps(state.to_dict(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

