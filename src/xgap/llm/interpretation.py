"""One bounded chat request producing the existing semantic-program envelope."""

from dataclasses import dataclass, field
import json
import math
import os
import time

from xgap.experiments.hashing import content_hash
from xgap.llm.openai_compatible import (OpenAICompatibleProviderConfig,
    OpenAICompatibleTransport, ProviderTransportError, UrllibOpenAICompatibleTransport,
    redact_secrets)
from xgap.llm.resolution import _structured_content, _usage
from xgap.llm.token_budget import ChatTokenBudgetGuard
from xgap.semantic.interpretation import InterpretationFailure, InterpretationResponse, SCHEMA
from xgap.semantic.program import SemanticOperatorKind, SemanticValueKind, SemanticHoleKind


def _object(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def _array(items, maximum=64):
    return {"type": "array", "items": items, "maxItems": maximum}


TEXT = {"type": "string", "minLength": 1}
VALUE = {"type": "string", "enum": [k.value for k in SemanticValueKind]}
INTERPRETATION_SCHEMA = _object({
    "schema_version": {"type": "string", "const": SCHEMA},
    "program": _object({
        "program_id": TEXT,
        "operators": {**_array(_object({
            "operator_id": TEXT,
            "kind": {"type": "string", "enum": [k.value for k in SemanticOperatorKind]},
            "input_ids": _array(TEXT, 2), "input_kinds": _array(VALUE, 2),
            "output_kind": VALUE, "parameters": {"type": "object"},
            "constraints": _array({"type": "object"}),
            "required_capabilities": _array(TEXT)})), "minItems": 1},
        "roots": {**_array(TEXT), "minItems": 1},
        "holes": _array(_object({"hole_id": TEXT,
            "kind": {"type": "string", "enum": [k.value for k in SemanticHoleKind]},
            "mention": TEXT, "required": {"type": "boolean", "const": True},
            "candidates": _array(TEXT, 0), "is_resolved": {"type": "boolean", "const": False}})),
        "metadata": {"type": "object"}}),
    "operator_sources": {"type": "object", "additionalProperties": {
        "anyOf": [TEXT, _object({"$hole": TEXT})]}}})


@dataclass
class OpenAICompatibleInterpretationProvider:
    config: OpenAICompatibleProviderConfig
    system_prompt: str
    token_guard: ChatTokenBudgetGuard
    transport: OpenAICompatibleTransport = field(default_factory=UrllibOpenAICompatibleTransport)
    last_invocation: dict | None = field(default=None, init=False)

    def __post_init__(self):
        if not self.system_prompt.strip() or self.config.prompt_hash != content_hash(self.system_prompt):
            raise ValueError("Interpretation prompt must match its pinned hash")
        if (self.config.structured_output_mode != "json_schema" or self.config.max_repair_calls != 0
                or self.config.candidate_cap != 1):
            raise ValueError("Interpretation requires one candidate, JSON schema and zero repairs")
        if content_hash(self.config.structured_schema) != content_hash(INTERPRETATION_SCHEMA):
            raise ValueError("Unsupported Interpretation wire schema")
        if set(self.config.extra_parameters) - {"chat_template_kwargs"}:
            raise ValueError("Interpretation permits only explicit chat-template overrides")
        if not all(math.isfinite(n) for n in (self.config.timeout_seconds, self.config.temperature, self.config.top_p)):
            raise ValueError("Interpretation request bounds must be finite")

    @property
    def provider_id(self):
        return self.config.provider_id

    def build_request_payload(self, request):
        payload = {"model": self.config.model,
            "messages": [{"role": "system", "content": self.system_prompt},
                         {"role": "user", "content": json.dumps(request.to_dict(), ensure_ascii=False)}],
            "temperature": self.config.temperature, "top_p": self.config.top_p,
            "max_tokens": self.config.max_tokens,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "xgap_semantic_program", "schema": self.config.structured_schema}},
            **self.config.extra_parameters}
        if self.config.seed is not None:
            payload["seed"] = self.config.seed
        return payload

    def interpret(self, request):
        started = time.perf_counter()
        usage = {"external_calls": 0, "input_tokens": 0, "output_tokens": 0}
        invocation = {"kind": "live_chat", "config": self.config.safe_dict(), "usage_reported": True}
        api_key = os.environ.get(self.config.api_key_env, "")

        def safe(value):
            value = redact_secrets(value)
            if isinstance(value, dict):
                return {k: safe(v) for k, v in value.items()}
            if isinstance(value, list):
                return [safe(v) for v in value]
            if isinstance(value, str) and api_key:
                return value.replace(api_key, "[REDACTED]")
            return value

        def finish(status):
            invocation.update(status=status, usage=dict(usage),
                              elapsed_ms=(time.perf_counter() - started) * 1000)
            self.last_invocation = safe(invocation)
            return self.last_invocation

        def fail(category, message):
            raise InterpretationFailure(category, safe(message), usage=usage,
                                        provenance=finish(category))

        try:
            payload = self.build_request_payload(request)
            invocation.update(request_payload=safe(payload), request_payload_sha256=content_hash(payload))
            check = self.token_guard.check(payload, call_kind="generation")
            invocation["token_budget"] = check
        except Exception:
            fail("preflight_error", "Cannot construct or count the pinned model request")
        if not check["passed"]:
            fail("token_budget", "Model request rejected: " + check["reason"])
        if not api_key:
            fail("missing_api_key", "Required key environment variable is unset: " + self.config.api_key_env)
        usage["external_calls"] = 1
        invocation["usage_reported"] = False
        try:
            raw = self.transport.post_json(url=self.config.chat_completions_url,
                api_key=api_key, payload=payload, timeout_seconds=self.config.timeout_seconds)
        except ProviderTransportError as error:
            fail(error.category.value, str(error))
        except Exception:
            fail("provider_error", "Model transport failed without a usable response")
        if not isinstance(raw, dict):
            fail("provider_error", "Model response is not an object")
        input_tokens, output_tokens, total_tokens, reported = _usage(raw.get("usage"))
        reported = reported and input_tokens + output_tokens == total_tokens
        invocation["usage_reported"] = reported
        if reported:
            usage.update(input_tokens=input_tokens, output_tokens=output_tokens)
        try:
            encoded = json.dumps(raw, allow_nan=False)
            if len(encoded.encode()) > request.max_response_bytes:
                invocation["response_prefix"] = safe(encoded[:2048])
                fail("response_too_large", "Model response exceeds the request byte bound")
            invocation["raw_provider_response"] = safe(raw)
            invocation["response_sha256"] = content_hash(raw)
            if raw.get("model") != self.config.model:
                raise ValueError("Model response does not identify the configured model")
            choices = raw.get("choices")
            if not isinstance(choices, list) or len(choices) != 1 or choices[0].get("finish_reason") != "stop":
                raise ValueError("Model response must contain one completed choice")
            structured = _structured_content(raw)
            structured = json.loads(json.dumps(safe(structured), allow_nan=False))
        except (ValueError, TypeError, AttributeError) as error:
            fail("structured_output_error", str(error))
        return InterpretationResponse(structured, **usage, provenance=finish("response_received"))
