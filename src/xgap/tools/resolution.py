"""Typed candidate-resolution tools for selective semantic interpretation.

These tools return bounded candidate identifiers.  They do not emit native
queries, mutate a semantic program, or decide whether a proposed candidate is
semantically valid.  The agent policy owns routing and deterministic
validation remains downstream.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from xgap.semantic import SemanticHoleKind
from xgap.tools.contracts import (
    ToolContext,
    ToolEffect,
    ToolResult,
    ToolSpec,
    ToolStatus,
)


SEMANTIC_CATALOG_LOOKUP_TOOL = "semantic.catalog.lookup"
SEMANTIC_ONTOLOGY_LOOKUP_TOOL = "semantic.ontology.lookup"
SEMANTIC_LLM_PROPOSE_TOOL = "semantic.llm.propose"
USER_CLARIFY_TOOL = "user.clarify"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CANDIDATE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#?=&%+-]{0,511}$")
_FORBIDDEN_NATIVE_KEYS = frozenset(
    {"cypher", "sparql", "gql", "native_query", "native_query_text", "query_text"}
)


def _candidate_ids(value: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be an array")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not _CANDIDATE_ID.fullmatch(item):
            raise ValueError(f"{name} contains an invalid candidate identifier")
        result.append(item)
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must not contain duplicates")
    return tuple(result)


def _validate_safe_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError("resolution metadata keys must be strings")
                if key.lower() in _FORBIDDEN_NATIVE_KEYS:
                    raise ValueError("resolution metadata must not contain native query text")
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    normalized = dict(value)
    visit(normalized)
    try:
        json.dumps(normalized, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("resolution metadata must be finite JSON") from exc
    return normalized


@dataclass(frozen=True)
class ResolutionCandidateRequest:
    """One bounded request for candidates for a declared semantic hole."""

    program_id: str
    hole_id: str
    hole_kind: SemanticHoleKind
    mention: str
    candidate_ids: tuple[str, ...]
    question: str
    hard_constraints_sha256: str
    max_candidates: int

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.program_id, self.hole_id, self.mention, self.question)
        ):
            raise ValueError("resolution request identifiers and text must be nonempty")
        if not isinstance(self.hole_kind, SemanticHoleKind):
            raise ValueError("resolution request hole_kind is invalid")
        object.__setattr__(
            self,
            "candidate_ids",
            _candidate_ids(self.candidate_ids, name="candidate_ids"),
        )
        if not _SHA256.fullmatch(self.hard_constraints_sha256):
            raise ValueError("hard_constraints_sha256 must be a SHA-256 digest")
        if (
            isinstance(self.max_candidates, bool)
            or not isinstance(self.max_candidates, int)
            or self.max_candidates <= 0
        ):
            raise ValueError("max_candidates must be a positive integer")
        if len(self.candidate_ids) > self.max_candidates:
            raise ValueError("candidate_ids exceed max_candidates")

    @classmethod
    def from_arguments(
        cls,
        arguments: Mapping[str, Any],
    ) -> "ResolutionCandidateRequest":
        required = {
            "program_id",
            "hole_id",
            "hole_kind",
            "mention",
            "candidate_ids",
            "question",
            "hard_constraints_sha256",
            "max_candidates",
        }
        if set(arguments) != required:
            raise ValueError("resolution tool arguments do not match the v1 contract")
        try:
            hole_kind = SemanticHoleKind(arguments["hole_kind"])
        except (TypeError, ValueError) as exc:
            raise ValueError("resolution tool hole_kind is invalid") from exc
        return cls(
            program_id=arguments["program_id"],
            hole_id=arguments["hole_id"],
            hole_kind=hole_kind,
            mention=arguments["mention"],
            candidate_ids=arguments["candidate_ids"],
            question=arguments["question"],
            hard_constraints_sha256=arguments["hard_constraints_sha256"],
            max_candidates=arguments["max_candidates"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_id": self.program_id,
            "hole_id": self.hole_id,
            "hole_kind": self.hole_kind.value,
            "mention": self.mention,
            "candidate_ids": list(self.candidate_ids),
            "question": self.question,
            "hard_constraints_sha256": self.hard_constraints_sha256,
            "max_candidates": self.max_candidates,
        }


@dataclass(frozen=True)
class ResolutionCandidateResponse:
    """Bounded tool output with provenance and explicit external-call cost."""

    hole_id: str
    candidate_ids: tuple[str, ...]
    source_id: str
    authoritative: bool = False
    external_calls: int = 0
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.hole_id, str) or not self.hole_id.strip():
            raise ValueError("resolution response hole_id must be nonempty")
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise ValueError("resolution response source_id must be nonempty")
        object.__setattr__(
            self,
            "candidate_ids",
            _candidate_ids(self.candidate_ids, name="candidate_ids"),
        )
        if not isinstance(self.authoritative, bool):
            raise ValueError("authoritative must be boolean")
        if self.authoritative and len(self.candidate_ids) != 1:
            raise ValueError("an authoritative response must select exactly one candidate")
        for name, value in (
            ("external_calls", self.external_calls),
            ("input_tokens", self.input_tokens),
            ("output_tokens", self.output_tokens),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if (
            isinstance(self.latency_ms, bool)
            or not isinstance(self.latency_ms, (int, float))
            or not math.isfinite(self.latency_ms)
            or self.latency_ms < 0
        ):
            raise ValueError("latency_ms must be finite and nonnegative")
        object.__setattr__(self, "metadata", _validate_safe_metadata(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "hole_id": self.hole_id,
            "candidate_ids": list(self.candidate_ids),
            "source_id": self.source_id,
            "authoritative": self.authoritative,
            "external_calls": self.external_calls,
            "latency_ms": float(self.latency_ms),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "metadata": dict(self.metadata),
        }


class ResolutionCandidateProvider(Protocol):
    def resolve(
        self,
        request: ResolutionCandidateRequest,
        context: ToolContext,
    ) -> ResolutionCandidateResponse:
        """Return bounded candidates for exactly one request."""


class ResolutionProviderFailure(RuntimeError):
    """A provider failure whose spent resources remain observable."""

    def __init__(
        self,
        message: str,
        *,
        source_id: str,
        failure_category: str,
        external_calls: int = 0,
        latency_ms: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if not isinstance(message, str) or not message.strip():
            raise ValueError("resolution provider failure message must be nonempty")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("resolution provider failure source_id must be nonempty")
        if not isinstance(failure_category, str) or not failure_category.strip():
            raise ValueError("resolution provider failure category must be nonempty")
        for name, value in (
            ("external_calls", external_calls),
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if (
            isinstance(latency_ms, bool)
            or not isinstance(latency_ms, (int, float))
            or not math.isfinite(latency_ms)
            or latency_ms < 0
        ):
            raise ValueError("latency_ms must be finite and nonnegative")
        super().__init__(message)
        self.source_id = source_id
        self.failure_category = failure_category
        self.external_calls = external_calls
        self.latency_ms = float(latency_ms)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.metadata = _validate_safe_metadata(metadata or {})

    def to_tool_result(self, tool_name: str) -> ToolResult:
        return ToolResult(
            tool_name=tool_name,
            status=ToolStatus.ERROR,
            error=str(self),
            metrics={
                "latency_ms": self.latency_ms,
                "external_calls": float(self.external_calls),
                "input_tokens": float(self.input_tokens),
                "output_tokens": float(self.output_tokens),
            },
            metadata={
                "source_id": self.source_id,
                "failure_category": self.failure_category,
                "bounded_candidate_ids": True,
                "native_query_text_allowed": False,
                **self.metadata,
            },
        )


@dataclass
class ResolutionCandidateTool:
    """Expose a candidate provider through the common agent-tool boundary."""

    name: str
    description: str
    provider: ResolutionCandidateProvider
    may_introduce_candidates: bool
    effect: ToolEffect = ToolEffect.READ_ONLY
    remote: bool = False
    estimated_cost_units: float = 0.0
    maximum_external_calls: int = 0
    tags: tuple[str, ...] = ("semantic_resolution",)

    def __post_init__(self) -> None:
        if self.name not in {
            SEMANTIC_CATALOG_LOOKUP_TOOL,
            SEMANTIC_ONTOLOGY_LOOKUP_TOOL,
            SEMANTIC_LLM_PROPOSE_TOOL,
            USER_CLARIFY_TOOL,
        }:
            raise ValueError("resolution tool name is not registered")
        if (
            isinstance(self.maximum_external_calls, bool)
            or not isinstance(self.maximum_external_calls, int)
            or self.maximum_external_calls < 0
        ):
            raise ValueError("maximum_external_calls must be a nonnegative integer")

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema={
                "type": "object",
                "required": [
                    "program_id",
                    "hole_id",
                    "hole_kind",
                    "mention",
                    "candidate_ids",
                    "question",
                    "hard_constraints_sha256",
                    "max_candidates",
                ],
                "additionalProperties": False,
            },
            output_kind="semantic_candidate_set",
            effect=self.effect,
            remote=self.remote,
            estimated_cost_units=self.estimated_cost_units,
            tags=self.tags,
        )

    def invoke(
        self,
        arguments: Mapping[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        try:
            request = ResolutionCandidateRequest.from_arguments(arguments)
            response = self.provider.resolve(request, context)
            if not isinstance(response, ResolutionCandidateResponse):
                raise TypeError("resolution provider returned an invalid response type")
            if response.hole_id != request.hole_id:
                raise ValueError("resolution response hole_id does not match the request")
            if len(response.candidate_ids) > request.max_candidates:
                raise ValueError("resolution response exceeds max_candidates")
            if not self.may_introduce_candidates and not set(
                response.candidate_ids
            ).issubset(request.candidate_ids):
                raise ValueError("resolution response introduced an unbounded candidate ID")
            if response.external_calls > self.maximum_external_calls:
                raise ValueError("resolution provider exceeded its external-call budget")
            if self.name == SEMANTIC_LLM_PROPOSE_TOOL and response.authoritative:
                raise ValueError("LLM proposals cannot be authoritative bindings")
        except ResolutionProviderFailure as exc:
            if exc.external_calls > self.maximum_external_calls:
                return ToolResult.error_result(
                    self.name,
                    "resolution provider failure exceeded its external-call budget",
                )
            return exc.to_tool_result(self.name)
        except (TypeError, ValueError) as exc:
            return ToolResult.error_result(self.name, str(exc))
        return ToolResult.success(
            self.name,
            response.to_dict(),
            metrics={
                "latency_ms": float(response.latency_ms),
                "external_calls": float(response.external_calls),
                "input_tokens": float(response.input_tokens),
                "output_tokens": float(response.output_tokens),
            },
            metadata={
                "source_id": response.source_id,
                "authoritative": response.authoritative,
                "bounded_candidate_ids": True,
                "native_query_text_allowed": False,
            },
        )
