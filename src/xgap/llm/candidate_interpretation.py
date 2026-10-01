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
from xgap.llm.openai_compatible import OpenAICompatibleProviderConfig
from xgap.semantic.interpretation_candidates import SCHEMA, validate_candidate_cap
from xgap.semantic.parameter_contract import PARAMETER_CONTRACT, typed_operator_schema


WIRE_PROFILES = {
    "json-schema-v1": ("json_schema", "typed-v1"),
    "json-object-v1": ("json_object", "typed-v1"),
    "envelope-schema-v1": ("json_schema", "envelope-v1"),
}


def candidate_output_mode(wire_profile):
    """Choose the wire format before dispatch; this is never an error fallback."""
    if wire_profile not in WIRE_PROFILES:
        raise ValueError("Unsupported candidate wire profile")
    return WIRE_PROFILES[wire_profile][0]


def candidate_wire_profile(structured_output_mode, schema_profile="typed-v1"):
    for profile, configuration in WIRE_PROFILES.items():
        if configuration == (structured_output_mode, schema_profile):
            return profile
    raise ValueError("Unsupported candidate output mode/schema profile combination")


def candidate_interpretation_schema(candidate_cap, *, schema_profile="typed-v1"):
    """Build the response schema for one explicitly bounded candidate pool."""
    validate_candidate_cap(candidate_cap)
    single = INTERPRETATION_SCHEMA["properties"]
    fields = {"candidate_id": {"type": "string", "minLength": 1, "maxLength": 256},
              "quality_proxy": {"anyOf": [
                  {"type": "number", "minimum": 0, "maximum": 1}, {"type": "null"}]},
              "program": deepcopy(single["program"]),
              "operator_sources": deepcopy(single["operator_sources"])}
    schema = {"type": "object",
        "required": ["schema_version", "candidates"],
        "additionalProperties": False, "properties": {
            "schema_version": {"type": "string", "const": SCHEMA},
            "candidates": {"type": "array", "minItems": 1, "maxItems": candidate_cap,
                "items": {"type": "object", "required": list(fields),
                          "additionalProperties": False, "properties": fields}}}}
    if schema_profile == "typed-v1":
        operators = fields["program"]["properties"]["operators"]
        operators["items"], definitions = typed_operator_schema(operators["items"])
        schema.update(title=PARAMETER_CONTRACT, **{"$defs": definitions})
    elif schema_profile != "envelope-v1":
        raise ValueError("Unsupported candidate schema profile")
    return schema


@dataclass(frozen=True)
class CandidateInterpretationProviderConfig(OpenAICompatibleProviderConfig):
    """V2-only explicit wire/local distinction, without changing legacy config."""

    schema_profile: str = "typed-v1"

    def __post_init__(self):
        super().__post_init__()
        candidate_wire_profile(self.structured_output_mode, self.schema_profile)
        expected = candidate_interpretation_schema(self.candidate_cap, schema_profile=self.schema_profile)
        if content_hash(self.structured_schema) != content_hash(expected):
            raise ValueError("Candidate schema profile differs from the pinned wire schema")

    def safe_dict(self):
        return {**super().safe_dict(), "schema_profile": self.schema_profile,
            "wire_profile": candidate_wire_profile(self.structured_output_mode, self.schema_profile),
            "wire_schema_hash": content_hash(self.structured_schema),
            "local_admission_schema_hash": content_hash(candidate_interpretation_schema(self.candidate_cap)),
            "parameter_contract_version": PARAMETER_CONTRACT}


@dataclass
class OpenAICompatibleCandidateInterpretationProvider(OpenAICompatibleInterpretationProvider):
    """Existing InterpretationRequest/Response interface; v2 pool on the wire."""

    def __post_init__(self):
        validate_candidate_cap(self.config.candidate_cap)
        if not self.system_prompt.strip() or self.config.prompt_hash != content_hash(self.system_prompt):
            raise ValueError("Candidate Interpretation prompt must match its pinned hash")
        schema_profile = getattr(self.config, "schema_profile", "typed-v1")
        candidate_wire_profile(self.config.structured_output_mode, schema_profile)
        if self.config.max_repair_calls != 0:
            raise ValueError("Candidate Interpretation requires zero repairs")
        expected = candidate_interpretation_schema(self.config.candidate_cap, schema_profile=schema_profile)
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
