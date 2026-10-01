"""A separate tiny intake for explicit NL return clauses, without gold access."""

from dataclasses import replace
import re


LEGACY_PROFILE = "legacy-v2"
REQUEST_PROFILE = "explicit-output-v1"


def requested_output_from_question(question):
    """Recognize only the two declared return-clause forms in this dev profile."""
    if not isinstance(question, str) or question.count("返回") != 1:
        raise ValueError("The tiny output profile requires one explicit return clause")
    matched = re.search(r"返回([^，。；;\n]+)", question)
    clause = matched.group(1).strip() if matched else ""
    if clause == "人员和边":
        fields = ["person", "edge"]
    elif clause.endswith("的身份和年龄") and clause[:-len("的身份和年龄")].strip():
        fields = ["person", "age"]
    else:
        raise ValueError("Unsupported explicit return clause in the tiny output profile")
    return {"kind": "binding_set", "fields": fields}


def apply_toy_output_contract(request):
    required = requested_output_from_question(request.question)
    if "requested_output" in request.context and request.context["requested_output"] != required:
        raise ValueError("Explicit question return clause conflicts with the supplied output contract")
    return replace(request, context={**request.context, "requested_output": required})


def apply_request_profile(request, profile):
    if profile == LEGACY_PROFILE:
        return request
    if profile == REQUEST_PROFILE:
        return apply_toy_output_contract(request)
    raise ValueError("Unsupported toy request profile")
