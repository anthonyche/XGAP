from __future__ import annotations

from dataclasses import dataclass, field

from xgap.agent import (
    GoalLoop,
    GoalStatus,
    SelectiveResolutionConfig,
    SelectiveSemanticResolutionPolicy,
    build_selective_resolution_goal,
    hard_constraints_sha256,
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
    FunctionTool,
    ResolutionCandidateRequest,
    ResolutionCandidateResponse,
    ResolutionCandidateTool,
    SEMANTIC_CATALOG_LOOKUP_TOOL,
    SEMANTIC_LLM_PROPOSE_TOOL,
    SEMANTIC_ONTOLOGY_LOOKUP_TOOL,
    ToolContext,
    ToolEffect,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    USER_CLARIFY_TOOL,
)


def _program(*holes: SemanticHole) -> SemanticGraphProgram:
    match = SemanticOperator(
        operator_id="match",
        kind=SemanticOperatorKind.MATCH,
        input_ids=(),
        input_kinds=(),
        output_kind=SemanticValueKind.BINDING_SET,
        constraints=(
            SemanticConstraint(
                constraint_id="last-month",
                expression="occurred_on >= 2026-08-01",
                policy=ConstraintPolicy.HARD,
            ),
        ),
    )
    return SemanticGraphProgram(
        program_id="selective-resolution-test",
        operators=(match,),
        roots=("match",),
        holes=holes,
    )


@dataclass
class _Provider:
    candidate_ids: tuple[str, ...]
    source_id: str
    authoritative: bool = False
    external_calls: int = 0
    calls: list[ResolutionCandidateRequest] = field(default_factory=list)

    def resolve(
        self,
        request: ResolutionCandidateRequest,
        context: ToolContext,
    ) -> ResolutionCandidateResponse:
        del context
        self.calls.append(request)
        return ResolutionCandidateResponse(
            hole_id=request.hole_id,
            candidate_ids=self.candidate_ids,
            source_id=self.source_id,
            authoritative=self.authoritative,
            external_calls=self.external_calls,
            latency_ms=7.5 if self.external_calls else 0.0,
            input_tokens=12 if self.external_calls else 0,
            output_tokens=3 if self.external_calls else 0,
        )


def _tool(
    name: str,
    provider: _Provider,
    *,
    may_introduce: bool,
    maximum_external_calls: int = 0,
) -> ResolutionCandidateTool:
    return ResolutionCandidateTool(
        name=name,
        description=f"test provider for {name}",
        provider=provider,
        may_introduce_candidates=may_introduce,
        effect=(ToolEffect.EXTERNAL if maximum_external_calls else ToolEffect.READ_ONLY),
        remote=bool(maximum_external_calls),
        maximum_external_calls=maximum_external_calls,
    )


def _run(
    program: SemanticGraphProgram,
    registry: ToolRegistry | None = None,
    config: SelectiveResolutionConfig = SelectiveResolutionConfig(),
):
    selected_registry = registry or ToolRegistry()
    policy = SelectiveSemanticResolutionPolicy(
        program,
        "Find recent transfers to risky companies.",
        config,
    )
    return GoalLoop().run(
        build_selective_resolution_goal(program, config),
        policy,
        selective_resolution_environment(selected_registry),
    )


def test_fully_bound_program_uses_zero_tools_and_zero_llm_calls() -> None:
    program = _program(
        SemanticHole(
            "person",
            SemanticHoleKind.ENTITY,
            "Alice Smith",
            candidates=("person:alice-smith",),
        ),
        SemanticHole(
            "risk",
            SemanticHoleKind.PREDICATE,
            "high risk",
            candidates=("risk:HIGH",),
        ),
    )

    state = _run(
        program,
        config=SelectiveResolutionConfig(use_llm=True),
    )

    assert state.status is GoalStatus.SUCCEEDED
    assert state.tool_calls == 0
    assert state.output["resolution_status"] == "resolved"
    assert state.output["llm_calls"] == 0
    assert state.output["hard_constraints_sha256"] == hard_constraints_sha256(
        program
    )


def test_entity_ambiguity_calls_only_user_clarification() -> None:
    program = _program(
        SemanticHole(
            "person",
            SemanticHoleKind.ENTITY,
            "Alice",
            candidates=("person:alice-smith", "person:alice-jones"),
        )
    )
    clarify = _Provider(
        ("person:alice-smith",),
        "user-confirmation",
        authoritative=True,
        external_calls=1,
    )
    ontology = _Provider(("person:alice-smith",), "ontology")
    llm = _Provider(("person:alice-smith",), "llm", external_calls=1)
    registry = ToolRegistry()
    registry.register(
        _tool(
            USER_CLARIFY_TOOL,
            clarify,
            may_introduce=False,
            maximum_external_calls=1,
        )
    )
    registry.register(
        _tool(
            SEMANTIC_ONTOLOGY_LOOKUP_TOOL,
            ontology,
            may_introduce=False,
        )
    )
    registry.register(
        _tool(
            SEMANTIC_LLM_PROPOSE_TOOL,
            llm,
            may_introduce=False,
            maximum_external_calls=1,
        )
    )

    state = _run(
        program,
        registry,
        SelectiveResolutionConfig(use_llm=True),
    )

    assert state.status is GoalStatus.SUCCEEDED
    assert [entry.tool_name for entry in state.trace if entry.tool_name] == [
        USER_CLARIFY_TOOL
    ]
    assert state.output["resolved_entity_bindings"] == {
        "person": "person:alice-smith"
    }
    assert state.output["llm_calls"] == 0
    assert len(ontology.calls) == 0
    assert len(llm.calls) == 0


def test_entity_ambiguity_blocks_when_clarification_is_not_available() -> None:
    program = _program(
        SemanticHole(
            "person",
            SemanticHoleKind.ENTITY,
            "Alice",
            candidates=("person:alice-smith", "person:alice-jones"),
        )
    )

    state = _run(program)

    assert state.status is GoalStatus.BLOCKED
    assert state.tool_calls == 0
    assert "user clarification" in state.message


def test_predicate_resolution_routes_ontology_then_bounded_llm() -> None:
    program = _program(
        SemanticHole(
            "predicate",
            SemanticHoleKind.PREDICATE,
            "funded",
            candidates=("predicate:paid", "predicate:invested"),
        )
    )
    ontology = _Provider(
        ("predicate:paid", "predicate:invested"),
        "ontology-v1",
    )
    llm = _Provider(
        ("predicate:invested",),
        "bounded-llm-v1",
        external_calls=1,
    )
    registry = ToolRegistry()
    registry.register(
        _tool(
            SEMANTIC_ONTOLOGY_LOOKUP_TOOL,
            ontology,
            may_introduce=False,
        )
    )
    registry.register(
        _tool(
            SEMANTIC_LLM_PROPOSE_TOOL,
            llm,
            may_introduce=False,
            maximum_external_calls=1,
        )
    )

    state = _run(
        program,
        registry,
        SelectiveResolutionConfig(use_llm=True),
    )

    assert state.status is GoalStatus.SUCCEEDED
    assert [entry.tool_name for entry in state.trace if entry.tool_name] == [
        SEMANTIC_ONTOLOGY_LOOKUP_TOOL,
        SEMANTIC_LLM_PROPOSE_TOOL,
    ]
    assert state.output["resolution_status"] == "candidate_set_ready"
    assert state.output["candidate_sets"][0]["candidate_ids"] == [
        "predicate:invested"
    ]
    assert state.output["candidate_sets"][0]["authoritative"] is False
    assert state.output["requires_deterministic_enumeration"] is True
    assert state.output["llm_calls"] == 1


def test_empty_nonentity_hole_uses_catalog_without_forcing_llm() -> None:
    program = _program(
        SemanticHole("source", SemanticHoleKind.SOURCE, "company records")
    )
    catalog = _Provider(
        ("source:neo4j", "source:fuseki"),
        "catalog-v1",
    )
    registry = ToolRegistry()
    registry.register(
        _tool(
            SEMANTIC_CATALOG_LOOKUP_TOOL,
            catalog,
            may_introduce=True,
        )
    )

    state = _run(
        program,
        registry,
        SelectiveResolutionConfig(use_ontology=False, use_llm=False),
    )

    assert state.status is GoalStatus.SUCCEEDED
    assert state.output["catalog_calls"] == 1
    assert state.output["llm_calls"] == 0
    assert state.output["semantic_alternative_hole_ids"] == ["source"]


def test_llm_cannot_introduce_an_unbounded_candidate_id_and_is_not_retried() -> None:
    program = _program(
        SemanticHole(
            "predicate",
            SemanticHoleKind.PREDICATE,
            "funded",
            candidates=("predicate:paid", "predicate:invested"),
        )
    )
    llm = _Provider(
        ("predicate:hallucinated",),
        "bounded-llm-v1",
        external_calls=1,
    )
    registry = ToolRegistry()
    registry.register(
        _tool(
            SEMANTIC_LLM_PROPOSE_TOOL,
            llm,
            may_introduce=False,
            maximum_external_calls=1,
        )
    )

    state = _run(
        program,
        registry,
        SelectiveResolutionConfig(use_ontology=False, use_llm=True),
    )

    assert state.status is GoalStatus.FAILED
    assert state.tool_calls == 1
    assert len(llm.calls) == 1
    assert "without retry" in state.message
    assert "unbounded candidate ID" in state.message


def test_optional_unavailable_llm_preserves_bounded_candidates_explicitly() -> None:
    program = _program(
        SemanticHole(
            "predicate",
            SemanticHoleKind.PREDICATE,
            "funded",
            candidates=("predicate:paid", "predicate:invested"),
        )
    )
    registry = ToolRegistry()
    registry.register(
        FunctionTool(
            ToolSpec(
                name=SEMANTIC_LLM_PROPOSE_TOOL,
                description="unavailable test LLM",
                input_schema={"type": "object"},
                output_kind="semantic_candidate_set",
                effect=ToolEffect.EXTERNAL,
                remote=True,
            ),
            lambda arguments, context: ToolResult.unavailable(
                SEMANTIC_LLM_PROPOSE_TOOL,
                "model is offline",
            ),
        )
    )

    state = _run(
        program,
        registry,
        SelectiveResolutionConfig(use_ontology=False, use_llm=True),
    )

    assert state.status is GoalStatus.SUCCEEDED
    assert state.tool_calls == 1
    assert state.output["candidate_sets"][0]["candidate_ids"] == [
        "predicate:paid",
        "predicate:invested",
    ]
    assert state.output["unavailable_optional_tools"] == [
        SEMANTIC_LLM_PROPOSE_TOOL
    ]


def test_provider_external_call_budget_is_enforced() -> None:
    program = _program(
        SemanticHole(
            "predicate",
            SemanticHoleKind.PREDICATE,
            "funded",
            candidates=("predicate:paid", "predicate:invested"),
        )
    )
    hidden_retry = _Provider(
        ("predicate:paid",),
        "llm-with-hidden-repair",
        external_calls=2,
    )
    registry = ToolRegistry()
    registry.register(
        _tool(
            SEMANTIC_LLM_PROPOSE_TOOL,
            hidden_retry,
            may_introduce=False,
            maximum_external_calls=1,
        )
    )

    state = _run(
        program,
        registry,
        SelectiveResolutionConfig(use_ontology=False, use_llm=True),
    )

    assert state.status is GoalStatus.FAILED
    assert state.tool_calls == 1
    assert "external-call budget" in state.message


def test_llm_cannot_claim_an_authoritative_binding() -> None:
    program = _program(
        SemanticHole(
            "predicate",
            SemanticHoleKind.PREDICATE,
            "funded",
            candidates=("predicate:paid", "predicate:invested"),
        )
    )
    llm = _Provider(
        ("predicate:paid",),
        "bounded-llm-v1",
        authoritative=True,
        external_calls=1,
    )
    registry = ToolRegistry()
    registry.register(
        _tool(
            SEMANTIC_LLM_PROPOSE_TOOL,
            llm,
            may_introduce=False,
            maximum_external_calls=1,
        )
    )

    state = _run(
        program,
        registry,
        SelectiveResolutionConfig(use_ontology=False, use_llm=True),
    )

    assert state.status is GoalStatus.FAILED
    assert state.tool_calls == 1
    assert "cannot be authoritative" in state.message


def test_resolution_response_rejects_native_query_metadata() -> None:
    try:
        ResolutionCandidateResponse(
            hole_id="predicate",
            candidate_ids=("predicate:paid",),
            source_id="bad-provider",
            metadata={"cypher": "MATCH (n) RETURN n"},
        )
    except ValueError as exc:
        assert "native query text" in str(exc)
    else:
        raise AssertionError("native query metadata was accepted")
