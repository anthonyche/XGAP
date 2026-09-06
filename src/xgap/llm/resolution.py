"""Single-call OpenAI-compatible provider for M15 semantic candidates.

The older M12 provider emits grounded ``PathPatternQuery`` candidates and may
perform one structured-output repair.  M15-E2 deliberately uses a narrower
contract: select only from the candidate identifiers supplied for one
non-entity semantic hole, perform exactly one HTTP request, and return no
native query or authoritative binding.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping

from xgap.experiments.hashing import content_hash
from xgap.llm.openai_compatible import (
    LiveFailureCategory,
    OpenAICompatibleProviderConfig,
    OpenAICompatibleTransport,
    ProviderTransportError,
    UrllibOpenAICompatibleTransport,
    redact_secrets,
)
from xgap.semantic import SemanticHoleKind
from xgap.tools import ToolContext
from xgap.tools.resolution import (
    ResolutionCandidateRequest,
    ResolutionCandidateResponse,
    ResolutionProviderFailure,
)

if TYPE_CHECKING:
    from xgap.experiments.bundles import ModelBundle


M15_RESOLUTION_PROVIDER_SCHEMA_VERSION = "m15-e2-openai-resolution-provider-v1"
M15_RESOLUTION_INVOCATION_SCHEMA_VERSION = "m15-e2-resolution-invocation-v1"

M15_RESOLUTION_BASE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["hole_id", "candidate_ids"],
    "additionalProperties": False,
    "properties": {
        "hole_id": {"type": "string"},
        "candidate_ids": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "uniqueItems": True,
        },
    },
}


def _validate_base_schema(value: Mapping[str, Any]) -> None:
    if content_hash(value) != content_hash(M15_RESOLUTION_BASE_SCHEMA):
        raise ValueError("M15 resolution ModelBundle uses an unsupported base schema")


def _usage(value: object) -> tuple[int, int, int, bool]:
    if not isinstance(value, Mapping):
        return 0, 0, 0, False
    raw = (
        value.get("prompt_tokens"),
        value.get("completion_tokens"),
        value.get("total_tokens"),
    )
    if not all(isinstance(item, int) and not isinstance(item, bool) and item >= 0 for item in raw):
        return 0, 0, 0, False
    return int(raw[0]), int(raw[1]), int(raw[2]), True


def _structured_content(response: Mapping[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("OpenAI-compatible response has no choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise ValueError("OpenAI-compatible response choice is invalid")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("OpenAI-compatible response message is invalid")
    content = message.get("content")
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("OpenAI-compatible response content is not JSON") from exc
    if not isinstance(content, Mapping):
        raise ValueError("OpenAI-compatible response content must be an object")
    return dict(content)


@dataclass(frozen=True)
class M15ResolutionInvocationArtifact:
    provider_id: str
    model: str
    program_id: str
    hole_id: str
    hard_constraints_sha256: str
    request_payload_sha256: str | None
    dynamic_schema_sha256: str | None
    response_sha256: str | None
    provider_request_id: str | None
    external_calls: int
    latency_ms: float
    input_tokens: int
    output_tokens: int
    total_tokens: int
    usage_reported: bool
    status: str
    failure_category: str | None
    error_message: str | None
    schema_version: str = M15_RESOLUTION_INVOCATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "provider_id": self.provider_id,
            "model": self.model,
            "program_id": self.program_id,
            "hole_id": self.hole_id,
            "hard_constraints_sha256": self.hard_constraints_sha256,
            "request_payload_sha256": self.request_payload_sha256,
            "dynamic_schema_sha256": self.dynamic_schema_sha256,
            "response_sha256": self.response_sha256,
            "provider_request_id": self.provider_request_id,
            "external_calls": self.external_calls,
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "usage_reported": self.usage_reported,
            "status": self.status,
            "failure_category": self.failure_category,
            "error_message": self.error_message,
        }
        return redact_secrets(payload)

    @property
    def invocation_sha256(self) -> str:
        return content_hash(self.to_dict())


@dataclass
class OpenAICompatibleResolutionCandidateProvider:
    """Rank bounded non-entity candidate IDs with one provider request."""

    config: OpenAICompatibleProviderConfig
    system_prompt: str
    transport: OpenAICompatibleTransport = field(
        default_factory=UrllibOpenAICompatibleTransport
    )
    last_invocation: M15ResolutionInvocationArtifact | None = field(
        default=None,
        init=False,
    )

    def __post_init__(self) -> None:
        if not self.system_prompt.strip():
            raise ValueError("M15 resolution system prompt must be nonempty")
        if self.config.structured_output_mode != "json_schema":
            raise ValueError("M15 resolution requires json_schema structured output")
        if self.config.max_repair_calls != 0:
            raise ValueError("M15 resolution forbids provider repair calls")
        _validate_base_schema(self.config.structured_schema)

    @property
    def provider_id(self) -> str:
        return self.config.provider_id

    def dynamic_schema(self, request: ResolutionCandidateRequest) -> dict[str, Any]:
        if not request.candidate_ids:
            raise ValueError("LLM resolution requires bounded candidate IDs")
        maximum = min(
            len(request.candidate_ids),
            request.max_candidates,
            self.config.candidate_cap,
        )
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["hole_id", "candidate_ids"],
            "additionalProperties": False,
            "properties": {
                "hole_id": {"type": "string", "const": request.hole_id},
                "candidate_ids": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": list(request.candidate_ids),
                    },
                    "minItems": 1,
                    "maxItems": maximum,
                    "uniqueItems": True,
                },
            },
        }

    def build_request_payload(
        self,
        request: ResolutionCandidateRequest,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if request.hole_kind is SemanticHoleKind.ENTITY:
            raise ValueError("entity ambiguity requires user clarification, not an LLM")
        if len(request.candidate_ids) > self.config.candidate_cap:
            raise ValueError("resolution request exceeds the provider candidate cap")
        schema = self.dynamic_schema(request)
        user_payload = {
            "program_id": request.program_id,
            "hole_id": request.hole_id,
            "hole_kind": request.hole_kind.value,
            "mention": request.mention,
            "question": request.question,
            "candidate_ids": list(request.candidate_ids),
            "hard_constraints_sha256": request.hard_constraints_sha256,
            "max_candidates": min(
                request.max_candidates,
                self.config.candidate_cap,
            ),
            "requirements": {
                "select_only_supplied_candidate_ids": True,
                "authoritative_binding_forbidden": True,
                "native_query_text_forbidden": True,
                "explanation_forbidden": True,
            },
        }
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        user_payload,
                        sort_keys=True,
                        ensure_ascii=True,
                    ),
                },
            ],
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "max_tokens": self.config.max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "xgap_m15_semantic_candidates",
                    "strict": True,
                    "schema": schema,
                },
            },
            **dict(self.config.extra_parameters),
        }
        if self.config.seed is not None:
            payload["seed"] = self.config.seed
        return payload, schema

    def resolve(
        self,
        request: ResolutionCandidateRequest,
        context: ToolContext,
    ) -> ResolutionCandidateResponse:
        del context
        source_id = f"llm:{self.config.provider_id}:{self.config.model}"
        try:
            payload, schema = self.build_request_payload(request)
        except ValueError as exc:
            self._fail(
                request,
                source_id=source_id,
                message=str(exc),
                category="preflight_error",
                external_calls=0,
            )
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            self._fail(
                request,
                source_id=source_id,
                message=(
                    f"required API key environment variable "
                    f"'{self.config.api_key_env}' is unset"
                ),
                category=LiveFailureCategory.PROVIDER_ERROR.value,
                external_calls=0,
                request_payload_sha256=content_hash(payload),
                dynamic_schema_sha256=content_hash(schema),
            )

        started = time.perf_counter()
        try:
            raw = self.transport.post_json(
                url=self.config.chat_completions_url,
                api_key=api_key,
                payload=payload,
                timeout_seconds=self.config.timeout_seconds,
            )
        except ProviderTransportError as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            safe_message = str(exc).replace(api_key, "[REDACTED]")
            self._fail(
                request,
                source_id=source_id,
                message=safe_message,
                category=exc.category.value,
                external_calls=1,
                latency_ms=latency_ms,
                request_payload_sha256=content_hash(payload),
                dynamic_schema_sha256=content_hash(schema),
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            safe_message = f"{type(exc).__name__}: {exc}".replace(
                api_key,
                "[REDACTED]",
            )
            self._fail(
                request,
                source_id=source_id,
                message=safe_message,
                category=LiveFailureCategory.PROVIDER_ERROR.value,
                external_calls=1,
                latency_ms=latency_ms,
                request_payload_sha256=content_hash(payload),
                dynamic_schema_sha256=content_hash(schema),
            )
        latency_ms = (time.perf_counter() - started) * 1000.0
        try:
            raw = dict(raw)
        except (TypeError, ValueError) as exc:
            self._fail(
                request,
                source_id=source_id,
                message=f"provider response root is invalid: {exc}",
                category=LiveFailureCategory.PROVIDER_ERROR.value,
                external_calls=1,
                latency_ms=latency_ms,
                request_payload_sha256=content_hash(payload),
                dynamic_schema_sha256=content_hash(schema),
            )
        input_tokens, output_tokens, total_tokens, usage_reported = _usage(
            raw.get("usage")
        )
        provider_request_id = (
            str(raw["id"]) if raw.get("id") is not None else None
        )
        response_sha256 = content_hash(redact_secrets(raw))
        try:
            structured = _structured_content(raw)
            if set(structured) != {"hole_id", "candidate_ids"}:
                raise ValueError("resolution response fields do not match the v1 contract")
            if structured["hole_id"] != request.hole_id:
                raise ValueError("resolution response hole_id does not match the request")
            candidate_ids = structured["candidate_ids"]
            if not isinstance(candidate_ids, list) or not candidate_ids:
                raise ValueError("resolution response candidate_ids must be nonempty")
            if not all(isinstance(item, str) for item in candidate_ids):
                raise ValueError("resolution response candidate_ids must be strings")
            if len(candidate_ids) != len(set(candidate_ids)):
                raise ValueError("resolution response candidate_ids must be unique")
            if len(candidate_ids) > schema["properties"]["candidate_ids"]["maxItems"]:
                raise ValueError("resolution response exceeds dynamic maxItems")
            if not set(candidate_ids).issubset(request.candidate_ids):
                raise ValueError("resolution response introduced an unbounded candidate ID")
        except (KeyError, TypeError, ValueError) as exc:
            self._fail(
                request,
                source_id=source_id,
                message=str(exc),
                category=LiveFailureCategory.STRUCTURED_OUTPUT_ERROR.value,
                external_calls=1,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                usage_reported=usage_reported,
                request_payload_sha256=content_hash(payload),
                dynamic_schema_sha256=content_hash(schema),
                response_sha256=response_sha256,
                provider_request_id=provider_request_id,
            )

        artifact = M15ResolutionInvocationArtifact(
            provider_id=self.config.provider_id,
            model=self.config.model,
            program_id=request.program_id,
            hole_id=request.hole_id,
            hard_constraints_sha256=request.hard_constraints_sha256,
            request_payload_sha256=content_hash(payload),
            dynamic_schema_sha256=content_hash(schema),
            response_sha256=response_sha256,
            provider_request_id=provider_request_id,
            external_calls=1,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            usage_reported=usage_reported,
            status="success",
            failure_category=None,
            error_message=None,
        )
        self.last_invocation = artifact
        return ResolutionCandidateResponse(
            hole_id=request.hole_id,
            candidate_ids=tuple(candidate_ids),
            source_id=source_id,
            authoritative=False,
            external_calls=1,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            metadata={
                "provider_id": self.config.provider_id,
                "model": self.config.model,
                "provider_request_id": provider_request_id,
                "prompt_sha256": self.config.prompt_hash,
                "dynamic_schema_sha256": artifact.dynamic_schema_sha256,
                "request_payload_sha256": artifact.request_payload_sha256,
                "response_sha256": artifact.response_sha256,
                "invocation_sha256": artifact.invocation_sha256,
                "usage_reported": usage_reported,
                "provider_repair_calls": 0,
            },
        )

    def _fail(
        self,
        request: ResolutionCandidateRequest,
        *,
        source_id: str,
        message: str,
        category: str,
        external_calls: int,
        latency_ms: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        usage_reported: bool = False,
        request_payload_sha256: str | None = None,
        dynamic_schema_sha256: str | None = None,
        response_sha256: str | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        artifact = M15ResolutionInvocationArtifact(
            provider_id=self.config.provider_id,
            model=self.config.model,
            program_id=request.program_id,
            hole_id=request.hole_id,
            hard_constraints_sha256=request.hard_constraints_sha256,
            request_payload_sha256=request_payload_sha256,
            dynamic_schema_sha256=dynamic_schema_sha256,
            response_sha256=response_sha256,
            provider_request_id=provider_request_id,
            external_calls=external_calls,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            usage_reported=usage_reported,
            status="failed",
            failure_category=category,
            error_message=message,
        )
        self.last_invocation = artifact
        raise ResolutionProviderFailure(
            message,
            source_id=source_id,
            failure_category=category,
            external_calls=external_calls,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            metadata={
                "provider_id": self.config.provider_id,
                "model": self.config.model,
                "invocation_sha256": artifact.invocation_sha256,
                "provider_repair_calls": 0,
            },
        )


def build_openai_compatible_resolution_provider(
    model: "ModelBundle",
    transport_override: OpenAICompatibleTransport | None = None,
) -> OpenAICompatibleResolutionCandidateProvider:
    """Build the M15 one-call provider from a frozen live ModelBundle."""

    config = model.config
    if config.provider == "mock":
        raise ValueError("M15 live resolution requires a non-mock ModelBundle")
    if model.structured_schema is None:
        raise ValueError("M15 resolution ModelBundle has no structured schema")
    if config.max_repair_calls != 0:
        raise ValueError("M15 resolution ModelBundle must disable repair calls")
    prompt_schema = model.prompt.structured_output_schema
    if set(prompt_schema) != {"ref", "hash"}:
        raise ValueError("M15 resolution prompt schema binding is invalid")
    if (
        prompt_schema["ref"] != config.structured_schema_ref
        or prompt_schema["hash"] != config.structured_schema_hash
        or content_hash(model.structured_schema) != prompt_schema["hash"]
    ):
        raise ValueError("M15 resolution prompt and model schema bindings disagree")
    base_url = str(config.base_url)
    if config.base_url_env is not None and config.base_url_env in os.environ:
        base_url = os.environ[config.base_url_env].strip()
        if not base_url:
            raise ValueError("M15 resolution base URL environment value is blank")
    model_name = config.exact_model_snapshot
    if config.model_env is not None and config.model_env in os.environ:
        model_name = os.environ[config.model_env].strip()
        if not model_name:
            raise ValueError("M15 resolution model environment value is blank")
    provider_config = OpenAICompatibleProviderConfig(
        provider_id=config.provider,
        base_url=base_url,
        api_key_env=str(config.api_key_env),
        model=model_name,
        temperature=config.temperature,
        top_p=config.top_p,
        max_tokens=int(config.token_limits.get("output", 0)),
        candidate_cap=config.candidate_count,
        timeout_seconds=config.timeout_seconds,
        structured_output_mode=config.structured_output_mode,
        structured_schema=model.structured_schema,
        prompt_hash=model.prompt.prompt_hash,
        seed=config.seed,
        seed_supported=config.seed_supported,
        max_repair_calls=config.max_repair_calls,
        extra_parameters=config.extra_parameters,
    )
    kwargs: dict[str, Any] = {
        "config": provider_config,
        "system_prompt": model.prompt.system_prompt,
    }
    if transport_override is not None:
        kwargs["transport"] = transport_override
    return OpenAICompatibleResolutionCandidateProvider(**kwargs)
