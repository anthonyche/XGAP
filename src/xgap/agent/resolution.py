"""Cost-bounded routing for selective M15 semantic resolution.

The policy distinguishes identity clarification from semantic candidate
generation.  Entity ambiguity is never delegated to an ontology or LLM.  For
predicate/type/source holes, optional tools may narrow a bounded candidate set;
their output remains a proposal for deterministic downstream validation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from xgap.agent.contracts import (
    AgentDecision,
    AgentPolicy,
    GoalSpec,
    GoalState,
    PlannedToolCall,
)
from xgap.agent.environment import AgentEnvironment
from xgap.agent.memory import MemoryStore
from xgap.semantic import ConstraintPolicy, SemanticGraphProgram, SemanticHole
from xgap.tools import ToolRegistry, ToolStatus
from xgap.tools.resolution import (
    SEMANTIC_CATALOG_LOOKUP_TOOL,
    SEMANTIC_LLM_PROPOSE_TOOL,
    SEMANTIC_ONTOLOGY_LOOKUP_TOOL,
    USER_CLARIFY_TOOL,
)


@dataclass(frozen=True)
class SelectiveResolutionConfig:
    """Finite routing policy for one semantic-program attempt."""

    use_catalog: bool = True
    use_ontology: bool = True
    use_llm: bool = False
    max_llm_calls: int = 1
    max_candidates_per_hole: int = 8

    def __post_init__(self) -> None:
        for name in ("use_catalog", "use_ontology", "use_llm"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        if (
            isinstance(self.max_llm_calls, bool)
            or not isinstance(self.max_llm_calls, int)
            or self.max_llm_calls < 0
        ):
            raise ValueError("max_llm_calls must be a nonnegative integer")
        if self.use_llm and self.max_llm_calls == 0:
            raise ValueError("use_llm requires a positive max_llm_calls")
        if (
            isinstance(self.max_candidates_per_hole, bool)
            or not isinstance(self.max_candidates_per_hole, int)
            or self.max_candidates_per_hole <= 0
        ):
            raise ValueError("max_candidates_per_hole must be positive")


@dataclass(frozen=True)
class _HoleState:
    hole: SemanticHole
    candidate_ids: tuple[str, ...]
    authoritative: bool
    sources: tuple[str, ...]


def hard_constraints_sha256(program: SemanticGraphProgram) -> str:
    """Hash only immutable semantic constraints and their operator owners."""

    payload = [
        {
            "operator_id": operator.operator_id,
            "constraint": constraint.to_dict(),
        }
        for operator in program.operators
        for constraint in operator.constraints
        if constraint.policy is ConstraintPolicy.HARD
    ]
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SelectiveSemanticResolutionPolicy(AgentPolicy):
    program: SemanticGraphProgram
    question: str
    config: SelectiveResolutionConfig = SelectiveResolutionConfig()

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("resolution question must be nonempty")
        for hole in self.program.holes:
            if len(hole.candidates) > self.config.max_candidates_per_hole:
                raise ValueError(
                    f"hole '{hole.hole_id}' exceeds max_candidates_per_hole"
                )

    def decide(
        self,
        state: GoalState,
        environment: AgentEnvironment,
    ) -> AgentDecision:
        failure = self._terminal_error(state)
        if failure is not None:
            return failure

        holes = self._hole_states(state)
        available = {spec.name for spec in environment.tools.specs()}
        allowed = set(state.goal.allowed_tools)

        for index, hole_state in enumerate(holes):
            hole = hole_state.hole
            candidates = hole_state.candidate_ids

            if hole.kind.value == "entity":
                if not candidates:
                    action = self._optional_call(
                        state,
                        available,
                        allowed,
                        stage="catalog",
                        index=index,
                        hole_state=hole_state,
                        tool_name=SEMANTIC_CATALOG_LOOKUP_TOOL,
                        enabled=self.config.use_catalog,
                    )
                    if action is not None:
                        return action
                    return AgentDecision.block(
                        f"entity hole '{hole.hole_id}' has no bounded candidates; "
                        "catalog lookup or user-provided candidates are required"
                    )
                if len(candidates) == 1 and hole_state.authoritative:
                    continue
                action = self._optional_call(
                    state,
                    available,
                    allowed,
                    stage="clarify",
                    index=index,
                    hole_state=hole_state,
                    tool_name=USER_CLARIFY_TOOL,
                    enabled=True,
                )
                if action is not None:
                    return action
                if self._called(state, "clarify", index, hole):
                    return AgentDecision.fail(
                        f"clarification for entity hole '{hole.hole_id}' did not "
                        "produce one authoritative candidate"
                    )
                return AgentDecision.block(
                    f"entity hole '{hole.hole_id}' requires user clarification"
                )

            if not candidates:
                action = self._optional_call(
                    state,
                    available,
                    allowed,
                    stage="catalog",
                    index=index,
                    hole_state=hole_state,
                    tool_name=SEMANTIC_CATALOG_LOOKUP_TOOL,
                    enabled=self.config.use_catalog,
                )
                if action is not None:
                    return action
                if hole.kind.value in {"predicate", "type"}:
                    action = self._optional_call(
                        state,
                        available,
                        allowed,
                        stage="ontology",
                        index=index,
                        hole_state=hole_state,
                        tool_name=SEMANTIC_ONTOLOGY_LOOKUP_TOOL,
                        enabled=self.config.use_ontology,
                    )
                    if action is not None:
                        return action
                return AgentDecision.block(
                    f"semantic hole '{hole.hole_id}' has no bounded candidates"
                )

            if len(candidates) > 1 and hole.kind.value in {"predicate", "type"}:
                action = self._optional_call(
                    state,
                    available,
                    allowed,
                    stage="ontology",
                    index=index,
                    hole_state=hole_state,
                    tool_name=SEMANTIC_ONTOLOGY_LOOKUP_TOOL,
                    enabled=self.config.use_ontology,
                )
                if action is not None:
                    return action

            if len(candidates) > 1 and self._llm_calls(state) < self.config.max_llm_calls:
                action = self._optional_call(
                    state,
                    available,
                    allowed,
                    stage="llm",
                    index=index,
                    hole_state=hole_state,
                    tool_name=SEMANTIC_LLM_PROPOSE_TOOL,
                    enabled=self.config.use_llm,
                )
                if action is not None:
                    return action

        return AgentDecision.succeed(
            "identity bindings are authoritative and semantic candidates are bounded",
            output=self._output(state, holes),
        )

    def _optional_call(
        self,
        state: GoalState,
        available: set[str],
        allowed: set[str],
        *,
        stage: str,
        index: int,
        hole_state: _HoleState,
        tool_name: str,
        enabled: bool,
    ) -> AgentDecision | None:
        if (
            not enabled
            or tool_name not in available
            or tool_name not in allowed
            or self._called(state, stage, index, hole_state.hole)
        ):
            return None
        return AgentDecision.call(
            PlannedToolCall(
                call_id=self._call_id(stage, index, hole_state.hole),
                tool_name=tool_name,
                arguments={
                    "program_id": self.program.program_id,
                    "hole_id": hole_state.hole.hole_id,
                    "hole_kind": hole_state.hole.kind.value,
                    "mention": hole_state.hole.mention,
                    "candidate_ids": list(hole_state.candidate_ids),
                    "question": self.question,
                    "hard_constraints_sha256": hard_constraints_sha256(self.program),
                    "max_candidates": self.config.max_candidates_per_hole,
                },
            ),
            f"{stage} candidates for semantic hole '{hole_state.hole.hole_id}'",
        )

    def _hole_states(self, state: GoalState) -> tuple[_HoleState, ...]:
        values: dict[str, _HoleState] = {
            hole.hole_id: _HoleState(
                hole=hole,
                candidate_ids=tuple(hole.candidates),
                authoritative=len(hole.candidates) == 1,
                sources=("semantic_program",),
            )
            for hole in self.program.holes
        }
        for observation in state.observations:
            if observation.kind != "tool_result":
                continue
            if observation.payload.get("status") != ToolStatus.SUCCESS.value:
                continue
            value = observation.payload.get("value")
            if not isinstance(value, Mapping):
                continue
            hole_id = value.get("hole_id")
            candidate_ids = value.get("candidate_ids")
            source_id = value.get("source_id")
            authoritative = value.get("authoritative")
            if (
                not isinstance(hole_id, str)
                or hole_id not in values
                or not isinstance(candidate_ids, list)
                or not all(isinstance(item, str) for item in candidate_ids)
                or not isinstance(source_id, str)
                or not isinstance(authoritative, bool)
            ):
                continue
            previous = values[hole_id]
            values[hole_id] = _HoleState(
                hole=previous.hole,
                candidate_ids=tuple(candidate_ids),
                authoritative=authoritative,
                sources=previous.sources + (source_id,),
            )
        return tuple(values[hole.hole_id] for hole in self.program.holes if hole.required)

    def _terminal_error(self, state: GoalState) -> AgentDecision | None:
        tool_observations = [
            observation
            for observation in state.observations
            if observation.kind == "tool_result"
        ]
        if not tool_observations:
            return None
        latest = tool_observations[-1]
        status = latest.payload.get("status")
        if status == ToolStatus.ERROR.value:
            return AgentDecision.fail(
                f"semantic-resolution tool failed without retry: "
                f"{latest.payload.get('error')}"
            )
        if status == ToolStatus.UNAVAILABLE.value:
            tool_name = latest.source
            if tool_name in {
                SEMANTIC_ONTOLOGY_LOOKUP_TOOL,
                SEMANTIC_LLM_PROPOSE_TOOL,
            }:
                return None
            return AgentDecision.block(
                f"required semantic-resolution tool is unavailable: "
                f"{latest.payload.get('error')}"
            )
        return None

    def _called(
        self,
        state: GoalState,
        stage: str,
        index: int,
        hole: SemanticHole,
    ) -> bool:
        call_id = self._call_id(stage, index, hole)
        return any(entry.call_id == call_id for entry in state.trace)

    @staticmethod
    def _call_id(stage: str, index: int, hole: SemanticHole) -> str:
        suffix = hashlib.sha256(hole.hole_id.encode("utf-8")).hexdigest()[:10]
        return f"m15-e1-{stage}-{index + 1:03d}-{suffix}"

    @staticmethod
    def _llm_calls(state: GoalState) -> int:
        return sum(
            entry.tool_name == SEMANTIC_LLM_PROPOSE_TOOL for entry in state.trace
        )

    def _output(
        self,
        state: GoalState,
        holes: tuple[_HoleState, ...],
    ) -> dict[str, Any]:
        tool_observations = [
            observation
            for observation in state.observations
            if observation.kind == "tool_result"
        ]
        all_authoritative = all(
            len(item.candidate_ids) == 1 and item.authoritative for item in holes
        )
        candidate_sets = [
            {
                "hole_id": item.hole.hole_id,
                "hole_kind": item.hole.kind.value,
                "mention": item.hole.mention,
                "candidate_ids": list(item.candidate_ids),
                "authoritative": item.authoritative,
                "sources": list(item.sources),
            }
            for item in holes
        ]
        resolved_entity_bindings = {
            item.hole.hole_id: item.candidate_ids[0]
            for item in holes
            if item.hole.kind.value == "entity"
            and len(item.candidate_ids) == 1
            and item.authoritative
        }
        hard_sha256 = hard_constraints_sha256(self.program)
        resolution_commit_sha256 = hashlib.sha256(
            json.dumps(
                {
                    "schema_version": "m15-e3-resolution-commit-v1",
                    "program_id": self.program.program_id,
                    "hard_constraints_sha256": hard_sha256,
                    "resolved_entity_bindings": resolved_entity_bindings,
                    "candidate_sets": candidate_sets,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        return {
            "schema_version": "m15-e1-selective-resolution-result-v1",
            "program_id": self.program.program_id,
            "resolution_status": (
                "resolved" if all_authoritative else "candidate_set_ready"
            ),
            "hard_constraints_sha256": hard_sha256,
            "hard_constraints_preserved": True,
            "candidate_sets": candidate_sets,
            "resolved_entity_bindings": resolved_entity_bindings,
            "resolved_entity_bindings_hard": True,
            "resolution_commit_schema_version": "m15-e3-resolution-commit-v1",
            "resolution_commit_sha256": resolution_commit_sha256,
            "semantic_alternative_hole_ids": [
                item.hole.hole_id
                for item in holes
                if item.hole.kind.value != "entity"
                and (len(item.candidate_ids) > 1 or not item.authoritative)
            ],
            "requires_deterministic_enumeration": not all_authoritative,
            "tool_calls": len(tool_observations),
            "llm_calls": self._llm_calls(state),
            "ontology_calls": sum(
                entry.tool_name == SEMANTIC_ONTOLOGY_LOOKUP_TOOL
                for entry in state.trace
            ),
            "catalog_calls": sum(
                entry.tool_name == SEMANTIC_CATALOG_LOOKUP_TOOL
                for entry in state.trace
            ),
            "clarification_calls": sum(
                entry.tool_name == USER_CLARIFY_TOOL for entry in state.trace
            ),
            "unavailable_optional_tools": [
                observation.source
                for observation in tool_observations
                if observation.payload.get("status") == ToolStatus.UNAVAILABLE.value
                and observation.source
                in {SEMANTIC_ONTOLOGY_LOOKUP_TOOL, SEMANTIC_LLM_PROPOSE_TOOL}
            ],
            "native_query_text_emitted": False,
        }


def build_selective_resolution_goal(
    program: SemanticGraphProgram,
    config: SelectiveResolutionConfig = SelectiveResolutionConfig(),
) -> GoalSpec:
    """Build a finite goal whose allowance matches the selected policy."""

    allowed: list[str] = [USER_CLARIFY_TOOL]
    if config.use_catalog:
        allowed.append(SEMANTIC_CATALOG_LOOKUP_TOOL)
    if config.use_ontology:
        allowed.append(SEMANTIC_ONTOLOGY_LOOKUP_TOOL)
    if config.use_llm:
        allowed.append(SEMANTIC_LLM_PROPOSE_TOOL)
    required_holes = len(program.unresolved_required_holes)
    max_tool_calls = max(1, required_holes * 3 + config.max_llm_calls)
    return GoalSpec(
        goal_id=f"semantic-resolution:{program.program_id}",
        objective="produce bounded semantic candidates without changing hard constraints",
        success_criteria=(
            "every required entity hole has one authoritative user/catalog binding",
            "every other required hole has a bounded candidate set",
            "hard semantic constraints are unchanged",
        ),
        allowed_tools=tuple(allowed),
        max_steps=max_tool_calls + 1,
        max_tool_calls=max_tool_calls,
        metadata={
            "resolution_policy": "m15-e1-selective-resolution-v1",
            "hard_constraints_sha256": hard_constraints_sha256(program),
            "llm_optional": True,
            "maximum_llm_calls": config.max_llm_calls if config.use_llm else 0,
        },
    )


def selective_resolution_environment(
    tools: ToolRegistry,
    *,
    memory: MemoryStore | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AgentEnvironment:
    arguments: dict[str, Any] = {}
    if memory is not None:
        arguments["memory"] = memory
    return AgentEnvironment(
        environment_id="m15-selective-semantic-resolution",
        tools=tools,
        metadata={
            "backend_execution_allowed": False,
            "native_query_generation_allowed": False,
            "hard_constraint_relaxation_allowed": False,
            **dict(metadata or {}),
        },
        **arguments,
    )
