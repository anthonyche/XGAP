"""OpenAI-compatible structured candidate provider for the bounded M12-B path."""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Protocol, Sequence

from xgap.experiments.hashing import content_hash
from xgap.llm.parser import PlannerSchemaError, parse_planner_response
from xgap.llm.schemas import PlannerRequest


class LiveFailureCategory(str, Enum):
    PROVIDER_ERROR = "provider_error"
    TIMEOUT = "timeout"
    STRUCTURED_OUTPUT_ERROR = "structured_output_error"
    REPAIR_FAILED = "repair_failed"
    INVALID_CANDIDATE = "invalid_candidate"
    HALLUCINATED_ONTOLOGY_ID = "hallucinated_ontology_id"
    UNRESOLVED_QUERY_ANCHOR = "unresolved_query_anchor"
    INCOMPLETE_SLOT_COVERAGE = "incomplete_slot_coverage"
    MISSING_BACKEND_MAPPING = "missing_backend_mapping"
    SEMANTIC_INADMISSIBLE = "semantic_inadmissible"
    REPRESENTATION_UNSUPPORTED = "representation_unsupported"
    COMPILER_UNSUPPORTED = "compiler_unsupported"


@dataclass(frozen=True)
class OpenAICompatibleProviderConfig:
    provider_id: str
    base_url: str
    api_key_env: str
    model: str
    temperature: float
    top_p: float
    max_tokens: int
    candidate_cap: int
    timeout_seconds: float
    structured_output_mode: str
    structured_schema: Mapping[str, Any]
    prompt_hash: str
    seed: int | None = None
    seed_supported: bool = False
    max_repair_calls: int = 1
    extra_parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not all((self.provider_id, self.base_url, self.api_key_env, self.model)):
            raise ValueError("OpenAI-compatible provider identifiers and endpoint are required.")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("OpenAI-compatible base_url must use HTTP or HTTPS.")
        if self.temperature < 0 or not 0 <= self.top_p <= 1:
            raise ValueError("Provider sampling parameters are invalid.")
        if self.max_tokens <= 0 or self.candidate_cap <= 0 or self.timeout_seconds <= 0:
            raise ValueError("Provider token, candidate, and timeout bounds must be positive.")
        if self.structured_output_mode not in {"json_schema", "json_object"}:
            raise ValueError("Structured output mode must be json_schema or json_object.")
        if self.seed is not None and not self.seed_supported:
            raise ValueError("Provider seed is configured but not supported.")
        if self.max_repair_calls not in {0, 1}:
            raise ValueError("The bounded protocol permits at most one repair call.")
        protected = {
            "model",
            "messages",
            "temperature",
            "top_p",
            "max_tokens",
            "response_format",
            "seed",
        }
        overlap = protected.intersection(self.extra_parameters)
        if overlap:
            raise ValueError(f"Provider extras cannot override bounded fields: {sorted(overlap)}")
        object.__setattr__(self, "structured_schema", dict(self.structured_schema))
        object.__setattr__(self, "extra_parameters", dict(self.extra_parameters))

    @property
    def chat_completions_url(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"

    def safe_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "model": self.model,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "candidate_cap": self.candidate_cap,
            "timeout_seconds": self.timeout_seconds,
            "structured_output_mode": self.structured_output_mode,
            "structured_schema_hash": content_hash(self.structured_schema),
            "prompt_hash": self.prompt_hash,
            "seed": self.seed,
            "seed_supported": self.seed_supported,
            "max_repair_calls": self.max_repair_calls,
            "extra_parameters": redact_secrets(self.extra_parameters),
        }


class OpenAICompatibleTransport(Protocol):
    def post_json(
        self,
        *,
        url: str,
        api_key: str,
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class UrllibOpenAICompatibleTransport:
    user_agent: str = "xgap-m12b/1"

    def post_json(
        self,
        *,
        url: str,
        api_key: str,
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        body = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": self.user_agent,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            safe_body = error.read().decode("utf-8", errors="replace")[:1000]
            guidance = ""
            if error.code == 401 and "dashscope" in url.lower():
                guidance = (
                    " Verify that the API key belongs to the same DashScope region, "
                    "workspace, and billing plan as the configured base URL."
                )
            raise ProviderTransportError(
                LiveFailureCategory.PROVIDER_ERROR,
                f"OpenAI-compatible endpoint returned HTTP {error.code}: "
                f"{safe_body}.{guidance}",
            ) from error
        except (TimeoutError, socket.timeout) as error:
            raise ProviderTransportError(LiveFailureCategory.TIMEOUT, "Provider request timed out.") from error
        except urllib.error.URLError as error:
            category = (
                LiveFailureCategory.TIMEOUT
                if isinstance(error.reason, (TimeoutError, socket.timeout))
                else LiveFailureCategory.PROVIDER_ERROR
            )
            raise ProviderTransportError(category, f"Provider request failed: {error.reason}") from error
        if not isinstance(data, Mapping):
            raise ProviderTransportError(
                LiveFailureCategory.PROVIDER_ERROR,
                "OpenAI-compatible response root must be an object.",
            )
        return dict(data)


@dataclass(frozen=True)
class ProviderTransportError(RuntimeError):
    category: LiveFailureCategory
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class LiveInvocationArtifact:
    provider: str
    model: str
    task_id: str
    prompt_hash: str
    prompt_schema_view_hash: str
    generation_parameters: Mapping[str, Any]
    generation_calls: int
    repair_calls: int
    raw_responses: tuple[Mapping[str, Any], ...]
    structured_response: Mapping[str, Any] | None
    parse_status: str
    validation_status: str
    failure_category: LiveFailureCategory | None
    error_message: str | None
    latency_seconds: float
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    provider_request_ids: tuple[str, ...]
    request_url: str
    request_timeout_seconds: float
    assembled_requests: tuple[Mapping[str, Any], ...]
    schema_version: str = "m12-live-invocation-v2"

    def to_dict(self) -> dict[str, Any]:
        return redact_secrets(
            {
                "schema_version": self.schema_version,
                "provider": self.provider,
                "model": self.model,
                "task_id": self.task_id,
                "prompt_hash": self.prompt_hash,
                "prompt_schema_view_hash": self.prompt_schema_view_hash,
                "generation_parameters": dict(self.generation_parameters),
                "generation_calls": self.generation_calls,
                "repair_calls": self.repair_calls,
                "raw_responses": [dict(item) for item in self.raw_responses],
                "structured_response": (
                    dict(self.structured_response)
                    if self.structured_response is not None
                    else None
                ),
                "parse_status": self.parse_status,
                "validation_status": self.validation_status,
                "failure_category": (
                    self.failure_category.value if self.failure_category is not None else None
                ),
                "error_message": self.error_message,
                "latency_seconds": self.latency_seconds,
                "usage": {
                    "input_tokens": self.input_tokens,
                    "output_tokens": self.output_tokens,
                    "total_tokens": self.total_tokens,
                },
                "provider_request_ids": list(self.provider_request_ids),
                "assembled_request_hashes": [
                    content_hash(item) for item in self.assembled_requests
                ],
            }
        )

    def request_records(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            redact_secrets(
                {
                    "schema_version": "m12-llm-request-v1",
                    "provider": self.provider,
                    "model": self.model,
                    "task_id": self.task_id,
                    "call_index": index,
                    "call_kind": "generation" if index == 1 else "repair",
                    "url": self.request_url,
                    "timeout_seconds": self.request_timeout_seconds,
                    "payload_hash": content_hash(payload),
                    "payload": dict(payload),
                }
            )
            for index, payload in enumerate(self.assembled_requests, start=1)
        )


class LiveProviderError(RuntimeError):
    def __init__(self, category: LiveFailureCategory, message: str, artifact: LiveInvocationArtifact):
        super().__init__(message)
        self.category = category
        self.artifact = artifact


@dataclass
class OpenAICompatibleStructuredCandidateProvider:
    config: OpenAICompatibleProviderConfig
    system_prompt: str
    transport: OpenAICompatibleTransport = field(
        default_factory=UrllibOpenAICompatibleTransport
    )
    response_validator: Callable[[Mapping[str, Any], PlannerRequest], None] | None = None
    last_invocation: LiveInvocationArtifact | None = field(default=None, init=False)

    @property
    def provider_id(self) -> str:
        return self.config.provider_id

    def build_request_payload(self, request: PlannerRequest) -> dict[str, Any]:
        if request.max_candidates > self.config.candidate_cap:
            raise ValueError("PlannerRequest exceeds the configured candidate cap M.")
        schema_view = request.metadata.get("prompt_schema_view")
        if not isinstance(schema_view, Mapping):
            raise ValueError("Live provider requires a bounded prompt_schema_view.")
        _validate_prompt_schema_view(schema_view)
        grounding_contracts = request.metadata.get("grounding_contracts", ())
        if not isinstance(grounding_contracts, Sequence) or isinstance(
            grounding_contracts, (str, bytes)
        ):
            raise ValueError("grounding_contracts must be a sequence of objects.")
        normalized_contracts = []
        for contract in grounding_contracts:
            if not isinstance(contract, Mapping):
                raise ValueError("Every grounding contract must be an object.")
            normalized_contracts.append(dict(contract))
        user_payload = {
            "task_id": str(request.metadata.get("task_id", "")),
            "question": request.question,
            "max_candidates": request.max_candidates,
            "schema_hints": list(request.schema_hints),
            "prompt_schema_view": dict(schema_view),
            "structured_output_schema": dict(self.config.structured_schema),
            "requirements": {
                "choose_query_anchors_from_visible_candidate_ids": True,
                "ground_every_candidate_slot": True,
                "native_query_text_forbidden": True,
                "apply_supplied_grounding_contracts": bool(normalized_contracts),
            },
        }
        if normalized_contracts:
            user_payload["grounding_contracts"] = normalized_contracts
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, sort_keys=True, ensure_ascii=True),
                },
            ],
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "max_tokens": self.config.max_tokens,
            "response_format": self._response_format(),
            **dict(self.config.extra_parameters),
        }
        if self.config.seed is not None:
            payload["seed"] = self.config.seed
        return payload

    def generate_candidates(self, request: PlannerRequest) -> Mapping[str, Any]:
        payload = self.build_request_payload(request)
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            artifact = self._artifact(
                request=request,
                raw_responses=(),
                structured_response=None,
                parse_status="not_started",
                validation_status="failed",
                category=LiveFailureCategory.PROVIDER_ERROR,
                error=f"Required API key environment variable '{self.config.api_key_env}' is unset.",
                latency=0.0,
                generation_calls=0,
                repair_calls=0,
                assembled_requests=(),
            )
            self.last_invocation = artifact
            raise LiveProviderError(
                LiveFailureCategory.PROVIDER_ERROR,
                artifact.error_message or "Missing API key.",
                artifact,
            )
        raw_responses: list[Mapping[str, Any]] = []
        assembled_requests: list[Mapping[str, Any]] = []
        request_ids: list[str] = []
        usages: list[dict[str, int | None]] = []
        started = time.perf_counter()
        generation_calls = 0
        repair_calls = 0
        current_payload = payload
        last_error = ""
        while True:
            if repair_calls == 0:
                generation_calls = 1
            assembled_requests.append(redact_secrets(current_payload))
            try:
                raw_response = self.transport.post_json(
                    url=self.config.chat_completions_url,
                    api_key=api_key,
                    payload=current_payload,
                    timeout_seconds=self.config.timeout_seconds,
                )
            except ProviderTransportError as error:
                safe_error = str(error).replace(api_key, "[REDACTED]")
                artifact = self._artifact(
                    request=request,
                    raw_responses=tuple(raw_responses),
                    structured_response=None,
                    parse_status="failed",
                    validation_status="failed",
                    category=error.category,
                    error=safe_error,
                    latency=time.perf_counter() - started,
                    generation_calls=generation_calls,
                    repair_calls=repair_calls,
                    provider_request_ids=tuple(request_ids),
                    usages=usages,
                    assembled_requests=tuple(assembled_requests),
                )
                self.last_invocation = artifact
                raise LiveProviderError(error.category, safe_error, artifact) from error
            raw_response = dict(raw_response)
            raw_responses.append(redact_secrets(raw_response))
            request_id = raw_response.get("id")
            if request_id is not None:
                request_ids.append(str(request_id))
            usages.append(_usage(raw_response.get("usage")))
            try:
                structured = _structured_content(raw_response)
                parse_planner_response(structured, request)
                _validate_grounded_shape(structured)
                if self.response_validator is not None:
                    self.response_validator(structured, request)
            except (ValueError, KeyError, TypeError, PlannerSchemaError) as error:
                last_error = str(error)
                if repair_calls >= self.config.max_repair_calls:
                    category = (
                        LiveFailureCategory.REPAIR_FAILED
                        if repair_calls
                        else LiveFailureCategory.STRUCTURED_OUTPUT_ERROR
                    )
                    artifact = self._artifact(
                        request=request,
                        raw_responses=tuple(raw_responses),
                        structured_response=None,
                        parse_status="failed",
                        validation_status="failed",
                        category=category,
                        error=last_error,
                        latency=time.perf_counter() - started,
                        generation_calls=generation_calls,
                        repair_calls=repair_calls,
                        provider_request_ids=tuple(request_ids),
                        usages=usages,
                        assembled_requests=tuple(assembled_requests),
                    )
                    self.last_invocation = artifact
                    raise LiveProviderError(category, last_error, artifact) from error
                repair_calls += 1
                current_payload = self._repair_payload(payload, raw_response, last_error)
                continue

            artifact = self._artifact(
                request=request,
                raw_responses=tuple(raw_responses),
                structured_response=structured,
                parse_status="parsed",
                validation_status="schema_valid",
                category=None,
                error=None,
                latency=time.perf_counter() - started,
                generation_calls=generation_calls,
                repair_calls=repair_calls,
                provider_request_ids=tuple(request_ids),
                usages=usages,
                assembled_requests=tuple(assembled_requests),
            )
            self.last_invocation = artifact
            return structured

    def _response_format(self) -> dict[str, Any]:
        if self.config.structured_output_mode == "json_schema":
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": "xgap_grounded_path_candidates",
                    "strict": True,
                    "schema": dict(self.config.structured_schema),
                },
            }
        return {"type": "json_object"}

    @staticmethod
    def _repair_payload(
        original: Mapping[str, Any],
        raw_response: Mapping[str, Any],
        error: str,
    ) -> dict[str, Any]:
        repaired = dict(original)
        messages = [dict(item) for item in original["messages"]]
        try:
            invalid_content = raw_response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            invalid_content = json.dumps(redact_secrets(raw_response), sort_keys=True)
        messages.extend(
            [
                {"role": "assistant", "content": str(invalid_content)},
                {
                    "role": "user",
                    "content": (
                        "Repair the response once. Return only schema-conforming JSON. "
                        f"Validation error: {error}"
                    ),
                },
            ]
        )
        repaired["messages"] = messages
        return repaired

    def _artifact(
        self,
        *,
        request: PlannerRequest,
        raw_responses: tuple[Mapping[str, Any], ...],
        structured_response: Mapping[str, Any] | None,
        parse_status: str,
        validation_status: str,
        category: LiveFailureCategory | None,
        error: str | None,
        latency: float,
        generation_calls: int,
        repair_calls: int,
        provider_request_ids: tuple[str, ...] = (),
        usages: list[dict[str, int | None]] | None = None,
        assembled_requests: tuple[Mapping[str, Any], ...] = (),
    ) -> LiveInvocationArtifact:
        schema_view = request.metadata.get("prompt_schema_view", {})
        usage_values = usages or []
        return LiveInvocationArtifact(
            provider=self.config.provider_id,
            model=self.config.model,
            task_id=str(request.metadata.get("task_id", "")),
            prompt_hash=self.config.prompt_hash,
            prompt_schema_view_hash=content_hash(schema_view),
            generation_parameters=self.config.safe_dict(),
            generation_calls=generation_calls,
            repair_calls=repair_calls,
            raw_responses=raw_responses,
            structured_response=structured_response,
            parse_status=parse_status,
            validation_status=validation_status,
            failure_category=category,
            error_message=error,
            latency_seconds=float(latency),
            input_tokens=_sum_usage(usage_values, "input_tokens"),
            output_tokens=_sum_usage(usage_values, "output_tokens"),
            total_tokens=_sum_usage(usage_values, "total_tokens"),
            provider_request_ids=provider_request_ids,
            request_url=self.config.chat_completions_url,
            request_timeout_seconds=self.config.timeout_seconds,
            assembled_requests=assembled_requests,
        )


def _structured_content(response: Mapping[str, Any]) -> dict[str, Any]:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("Provider response has no choices[0].message.content.") from error
    if isinstance(content, Mapping):
        return dict(content)
    if not isinstance(content, str):
        raise ValueError("Structured response content must be a JSON string or object.")
    value = json.loads(content)
    if not isinstance(value, Mapping):
        raise ValueError("Structured response JSON root must be an object.")
    return dict(value)


def _validate_grounded_shape(data: Mapping[str, Any]) -> None:
    forbidden_native_fields = {"native_query", "cypher", "sparql", "gql", "query_text"}
    present = forbidden_native_fields.intersection(data)
    if present:
        raise ValueError(
            "Live XGAP responses cannot contain native query fields: "
            f"{sorted(present)}."
        )
    slots = data.get("query_slots")
    candidates = data.get("candidates")
    if not isinstance(slots, list) or not slots:
        raise ValueError("Grounded response requires a non-empty query_slots list.")
    if not isinstance(candidates, list):
        raise ValueError("Grounded response requires a candidates list.")
    for index, slot in enumerate(slots):
        if not isinstance(slot, Mapping) or not slot.get("slot_id") or not slot.get("query_anchor_id"):
            raise ValueError(f"query_slots[{index}] requires slot_id and query_anchor_id.")
    candidate_ids: list[str] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            raise ValueError(f"candidates[{index}] must be an object.")
        candidate_id = str(candidate.get("candidate_id", ""))
        if not candidate_id:
            raise ValueError(f"candidates[{index}] requires candidate_id.")
        candidate_ids.append(candidate_id)
        grounding = candidate.get("grounding")
        if not isinstance(grounding, Mapping) or not isinstance(
            grounding.get("slot_realizations"), list
        ):
            raise ValueError(f"candidates[{index}] requires grounding.slot_realizations.")
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("Grounded response candidate_id values must be unique.")


def _validate_prompt_schema_view(schema_view: Mapping[str, Any]) -> None:
    terms = schema_view.get("terms")
    slots = schema_view.get("query_slots")
    ontology = schema_view.get("ontology")
    if not isinstance(ontology, Mapping) or not all(
        str(ontology.get(field, "")).strip() for field in ("id", "version", "hash")
    ):
        raise ValueError("Live provider requires identified ontology context.")
    if not isinstance(terms, list) or not terms:
        raise ValueError("Live provider requires non-empty prompt-visible ontology terms.")
    visible_term_ids = {
        str(item.get("term_id", ""))
        for item in terms
        if isinstance(item, Mapping) and str(item.get("term_id", ""))
    }
    if len(visible_term_ids) != len(terms):
        raise ValueError("Prompt-visible ontology terms require unique non-empty term_id values.")
    if not isinstance(slots, list) or not slots:
        raise ValueError("Live provider requires non-empty prompt query slots.")
    for index, slot in enumerate(slots):
        if not isinstance(slot, Mapping):
            raise ValueError(f"prompt_schema_view.query_slots[{index}] must be an object.")
        slot_id = str(slot.get("slot_id", ""))
        candidates = slot.get("candidate_anchor_ids")
        if not slot_id or not isinstance(candidates, list) or not candidates:
            raise ValueError(
                f"prompt_schema_view.query_slots[{index}] requires an ID and anchor candidates."
            )
        unknown = {str(item) for item in candidates} - visible_term_ids
        if unknown:
            raise ValueError(
                f"Prompt query slot '{slot_id}' references hidden ontology IDs: {sorted(unknown)}."
            )


def _usage(value: object) -> dict[str, int | None]:
    if not isinstance(value, Mapping):
        return {"input_tokens": None, "output_tokens": None, "total_tokens": None}
    return {
        "input_tokens": _optional_int(value.get("prompt_tokens", value.get("input_tokens"))),
        "output_tokens": _optional_int(value.get("completion_tokens", value.get("output_tokens"))),
        "total_tokens": _optional_int(value.get("total_tokens")),
    }


def _optional_int(value: object) -> int | None:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _sum_usage(values: list[dict[str, int | None]], name: str) -> int | None:
    present = [item[name] for item in values if item[name] is not None]
    return sum(present) if present else None


_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "authorization_header",
    "secret",
    "password",
    "access_token",
    "headers",
}


def redact_secrets(value: object) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): ("[REDACTED]" if str(key).lower() in _SENSITIVE_KEYS else redact_secrets(item))
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact_secrets(item) for item in value]
    return value
