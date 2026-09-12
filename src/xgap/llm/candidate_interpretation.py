"""One bounded chat response with multiple independently admitted meanings.

Reuses the v1 transport, usage capture, secret redaction and no-repair behavior.
It does not change the historical v1 schema or provider configuration contract.
"""

from copy import deepcopy
from dataclasses import dataclass
import json
import math

from xgap.experiments.hashing import content_hash
from xgap.llm.interpretation import INTERPRETATION_SCHEMA, OpenAICompatibleInterpretationProvider
from xgap.semantic.interpretation_candidates import SCHEMA, validate_candidate_cap
from xgap.semantic.parameter_contract import PARAMETER_CONTRACT, typed_operator_schema


WIRE_PROFILES = {"json-schema-v1": "json_schema", "json-object-v1": "json_object"}


def candidate_output_mode(wire_profile):
    """Choose the wire format before dispatch; this is never an error fallback."""
    if wire_profile not in WIRE_PROFILES:
        raise ValueError("Unsupported candidate wire profile")
    return WIRE_PROFILES[wire_profile]


def candidate_wire_profile(structured_output_mode):
    for profile, mode in WIRE_PROFILES.items():
        if mode == structured_output_mode:
            return profile
    raise ValueError("Unsupported candidate structured output mode")


def candidate_interpretation_schema(candidate_cap):
    """Build the response schema for one explicitly bounded candidate pool."""
    validate_candidate_cap(candidate_cap)
    single = INTERPRETATION_SCHEMA["properties"]
    fields = {"candidate_id": {"type": "string", "minLength": 1, "maxLength": 256},
              "quality_proxy": {"anyOf": [
                  {"type": "number", "minimum": 0, "maximum": 1}, {"type": "null"}]},
              "program": deepcopy(single["program"]),
              "operator_sources": deepcopy(single["operator_sources"])}
    operators = fields["program"]["properties"]["operators"]
    operators["items"], definitions = typed_operator_schema(operators["items"])
    return {"type": "object", "title": PARAMETER_CONTRACT, "$defs": definitions,
        "required": ["schema_version", "candidates"],
        "additionalProperties": False, "properties": {
            "schema_version": {"type": "string", "const": SCHEMA},
            "candidates": {"type": "array", "minItems": 1, "maxItems": candidate_cap,
                "items": {"type": "object", "required": list(fields),
                          "additionalProperties": False, "properties": fields}}}}


@dataclass
class OpenAICompatibleCandidateInterpretationProvider(OpenAICompatibleInterpretationProvider):
    """Existing InterpretationRequest/Response interface; v2 pool on the wire."""

    def __post_init__(self):
        validate_candidate_cap(self.config.candidate_cap)
        if not self.system_prompt.strip() or self.config.prompt_hash != content_hash(self.system_prompt):
            raise ValueError("Candidate Interpretation prompt must match its pinned hash")
        candidate_wire_profile(self.config.structured_output_mode)
        if self.config.max_repair_calls != 0:
            raise ValueError("Candidate Interpretation requires zero repairs")
        expected = candidate_interpretation_schema(self.config.candidate_cap)
        if content_hash(self.config.structured_schema) != content_hash(expected):
            raise ValueError("Candidate Interpretation schema does not match its bounded pool")
        if set(self.config.extra_parameters) - {"chat_template_kwargs"}:
            raise ValueError("Candidate Interpretation permits only explicit chat-template overrides")
        if not all(math.isfinite(n) for n in (
                self.config.timeout_seconds, self.config.temperature, self.config.top_p)):
            raise ValueError("Candidate Interpretation request bounds must be finite")

    def build_request_payload(self, request):
        payload = super().build_request_payload(request)
        wire_request = {**request.to_dict(), "schema_version": SCHEMA,
                        "candidate_cap": self.config.candidate_cap}
        payload["messages"][1]["content"] = json.dumps(wire_request, ensure_ascii=False)
        if self.config.structured_output_mode == "json_object":
            payload["response_format"] = {"type": "json_object"}
        else:
            payload["response_format"]["json_schema"]["name"] = "xgap_semantic_candidates"
        return payload
