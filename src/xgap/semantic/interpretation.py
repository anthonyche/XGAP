"""Independent, provider-neutral question → semantic-program boundary."""

from dataclasses import dataclass, field, replace
import json
import time
from typing import Any, Mapping, Protocol

from xgap.semantic.intake import DeterministicSemanticIntake, _safe_json_mapping
from xgap.semantic.program import ConstraintPolicy, SemanticGraphProgram


SCHEMA = "xgap-semantic-interpretation-v1"


def json_copy(value):
    return json.loads(json.dumps(value, allow_nan=False))


@dataclass(frozen=True)
class InterpretationRequest:
    question: str
    context: Mapping[str, Any] = field(default_factory=dict)
    required_constraints: tuple[Mapping[str, Any], ...] = ()
    max_response_bytes: int = 1_048_576

    def __post_init__(self):
        if not isinstance(self.question, str) or not self.question.strip():
            raise ValueError("Interpretation needs a nonempty question")
        if type(self.max_response_bytes) is not int or not 0 < self.max_response_bytes <= 4_194_304:
            raise ValueError("Interpretation response bound must be positive and at most4MiB")
        if not isinstance(self.context, Mapping):
            raise ValueError("Interpretation context must be an object")
        for item in self.required_constraints:
            if set(item) != {"operator_id", "constraint"} or item["constraint"].get("policy") != "hard":
                raise ValueError("Required constraints must name an operator and an explicit hard constraint")
        object.__setattr__(self, "context", json_copy(dict(self.context)))
        object.__setattr__(self, "required_constraints", tuple(json_copy(self.required_constraints)))

    def to_dict(self):
        return {"schema_version": SCHEMA, "question": self.question,
                "context": json_copy(dict(self.context)),
                "required_constraints": json_copy(self.required_constraints),
                "max_response_bytes": self.max_response_bytes}


@dataclass(frozen=True)
class InterpretationResponse:
    payload: Mapping[str, Any]
    external_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if any(type(v) is not int or v < 0 for v in (self.external_calls, self.input_tokens, self.output_tokens)):
            raise ValueError("Interpretation usage must contain nonnegative integer counts")

    @property
    def usage(self):
        return {"external_calls": self.external_calls, "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens}


class InterpretationFailure(Exception):
    """Safe provider failure; no transport credentials or automatic retry."""

    def __init__(self, category: str, message: str, *, usage=None):
        super().__init__(message)
        self.category = category
        self.usage = InterpretationResponse({}, **(usage or {})).usage


class InterpretationProvider(Protocol):
    provider_id: str

    def interpret(self, request: InterpretationRequest) -> InterpretationResponse: ...


@dataclass
class TemplateInterpretationProvider:
    """One explicitly selected, controlled phrase template; not general NL parsing."""

    intake: DeterministicSemanticIntake
    operator_sources: Mapping[str, Any]

    @property
    def provider_id(self):
        return f"template:{self.intake.template_id}:{self.intake.artifact_sha256}"

    def interpret(self, request):
        result = self.intake.compile(request.question)
        program = result.program.to_dict()
        # Intake ownership is provenance, not an executable operator parameter.
        owners = {op["operator_id"]: op["parameters"].pop("semantic_hole_ids", [])
                  for op in program["operators"]}
        program["metadata"]["intake_hole_owners"] = owners
        return InterpretationResponse(
            {"schema_version": SCHEMA, "program": program,
             "operator_sources": json_copy(dict(self.operator_sources))},
            provenance={"kind": "controlled_template", "template_sha256": self.intake.artifact_sha256,
                        "phrase_matches": [m.to_dict() for m in result.phrase_matches]})


def parse_interpretation(payload, request):
    """Structural admission is independent from NL meaning/answer evaluation."""
    encoded = json.dumps(payload, allow_nan=False).encode()
    if len(encoded) > request.max_response_bytes:
        raise ValueError("Interpretation response exceeds the request byte bound")
    payload = _safe_json_mapping(json.loads(encoded), name="interpretation response")
    if set(payload) != {"schema_version", "program", "operator_sources"} or payload["schema_version"] != SCHEMA:
        raise ValueError("Interpretation response fields or schema are unsupported")
    program = SemanticGraphProgram.from_dict(payload["program"])
    # Reject fields silently discarded by nested legacy dataclass loaders.
    for raw in payload["program"].get("holes", []):
        if set(raw) - {"hole_id", "kind", "mention", "required", "candidates", "is_resolved"}:
            raise ValueError("Unknown semantic hole fields")
        if type(raw.get("required", True)) is not bool or ("is_resolved" in raw and
                raw["is_resolved"] is not (len(raw.get("candidates", [])) == 1)):
            raise ValueError("Semantic hole flags must agree with their typed candidates")
        if raw["kind"] == "entity" and raw.get("candidates"):
            raise ValueError("Interpretation cannot supply authoritative entity candidates; use catalog or clarification")
    for raw in payload["program"]["operators"]:
        for constraint in raw.get("constraints", []):
            if set(constraint) - {"constraint_id", "expression", "policy", "predicate"}:
                raise ValueError("Unknown semantic constraint fields")
    actual = [{"operator_id": op.operator_id, "constraint": c.to_dict()}
              for op in program.operators for c in op.constraints if c.policy is ConstraintPolicy.HARD]
    canonical = lambda item: json.dumps(item, sort_keys=True, allow_nan=False)
    if any(canonical(item) not in {canonical(c) for c in actual} for item in request.required_constraints):
        raise ValueError("Interpretation dropped or changed an explicit hard constraint")
    sources = payload["operator_sources"]
    if not isinstance(sources, dict):
        raise ValueError("Interpretation source assignments must be an object")
    return program, sources


def interpret_question(request: InterpretationRequest, provider: InterpretationProvider):
    """Call once, retain raw output/usage, and admit independently of execution."""
    started = time.perf_counter()
    report = {"schema_version": SCHEMA, "provider_id": provider.provider_id,
              "request": request.to_dict(), "success": False, "external_calls": 0,
              "input_tokens": 0, "output_tokens": 0}
    try:
        response = provider.interpret(replace(request))
    except InterpretationFailure as error:
        report.update(status="provider_failure", failure_category=error.category,
                      error=str(error), **error.usage)
        if hasattr(error, "recorded_usage"):
            report["provenance"] = {"kind": "replay", "recorded_usage": error.recorded_usage}
    except Exception as error:
        # Unexpected provider exceptions are observations, never a repair trigger.
        report.update(status="provider_failure", failure_category=type(error).__name__,
                      error="Interpretation provider raised an exception", usage_unavailable=True)
    else:
        try:
            if not isinstance(response, InterpretationResponse):
                raise ValueError("Provider must return InterpretationResponse")
            report.update(**response.usage, provenance=json_copy(dict(response.provenance)),
                          raw_response=json_copy(response.payload))
            program, sources = parse_interpretation(response.payload, request)
            report.update(success=True, status="interpreted", program=program.to_dict(), operator_sources=sources)
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
            report.update(status="interpretation_invalid", error=str(error))
    report["elapsed_ms"] = (time.perf_counter() - started) * 1000
    return report
