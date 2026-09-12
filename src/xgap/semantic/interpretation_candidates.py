"""Bounded alternative meanings, admitted independently without execution.

The v1 single-program parser remains authoritative for each candidate. A quality
proxy is a model preference, never a calibrated probability or an answer-quality
bound. ``None`` means unknown and must not be interpreted as zero actual quality.
Candidate admission does not resolve entity identity or rank physical plans.
"""

from collections import Counter
from dataclasses import replace
import json
import math
import time

from xgap.semantic.interpretation import (
    InterpretationFailure, InterpretationResponse, SCHEMA as SINGLE_SCHEMA,
    json_copy, parse_interpretation,
)


SCHEMA = "xgap-semantic-interpretation-candidates-v2"
MAX_CANDIDATES = 8


def validate_candidate_cap(candidate_cap):
    if type(candidate_cap) is not int or not 1 <= candidate_cap <= MAX_CANDIDATES:
        raise ValueError("Interpretation candidate_cap must be an integer from one to eight")
    return candidate_cap


def parse_interpretation_candidates(payload, request, *, candidate_cap):
    """Return every candidate's admission record, preserving response order.

    A malformed/over-budget envelope fails as a whole. An invalid candidate does
    not remove valid siblings. Duplicate IDs invalidate all occurrences of that
    ID because downstream selection must be unambiguous. There is no truncation,
    semantic repair, entity-authority promotion, cost-based ranking or dispatch.
    """
    validate_candidate_cap(candidate_cap)
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "candidates"}:
        raise ValueError("Candidate Interpretation requires exactly schema_version and candidates")
    if payload["schema_version"] != SCHEMA:
        raise ValueError("Unsupported candidate Interpretation schema")
    candidates = payload["candidates"]
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= candidate_cap:
        raise ValueError("Interpretation response exceeds its nonempty bounded candidate pool")
    # Byte admission precedes per-candidate parsing. Python's non-finite values
    # can only arise from a permissive/injected provider; retain their candidate
    # rejection independently rather than allowing them to erase valid siblings.
    encoded = json.dumps(payload, allow_nan=True).encode()
    if len(encoded) > request.max_response_bytes:
        raise ValueError("Candidate Interpretation exceeds the request byte bound")
    ids = Counter(item.get("candidate_id") for item in candidates
                  if isinstance(item, dict) and isinstance(item.get("candidate_id"), str))
    records = []
    for index, raw in enumerate(candidates):
        record = {"candidate_index": index, "candidate_id": None, "status": "invalid",
                  "quality_proxy": None, "quality_proxy_calibrated": False}
        try:
            item = json_copy(raw)
            record["raw_candidate"] = item
            if not isinstance(item, dict) or set(item) != {
                    "candidate_id", "quality_proxy", "program", "operator_sources"}:
                raise ValueError("Each candidate must declare its ID, quality proxy, program and sources")
            identifier = item["candidate_id"]
            if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 256:
                raise ValueError("Candidate ID must be a nonblank string of at most 256 characters")
            record["candidate_id"] = identifier
            if ids[identifier] != 1:
                raise ValueError("Duplicate candidate ID")
            quality = item["quality_proxy"]
            if quality is not None and (type(quality) not in (int, float)
                    or not math.isfinite(quality) or not 0 <= quality <= 1):
                raise ValueError("Quality proxy must be finite in [0,1] or null; it is not calibrated")
            program, sources = parse_interpretation({"schema_version": SINGLE_SCHEMA,
                "program": item["program"], "operator_sources": item["operator_sources"]}, request)
            record.update(status="admitted", quality_proxy=quality,
                          program=program.to_dict(), operator_sources=sources)
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
            record["error"] = str(error)
            if "raw_candidate" not in record:
                # Keep an inert textual observation when the injected payload
                # cannot be represented by strict JSON (for example NaN).
                record["raw_candidate_text"] = json.dumps(raw, allow_nan=True)
        records.append(record)
    return records


def interpret_candidate_question(request, provider, *, candidate_cap):
    """Request one candidate pool and charge that provider action exactly once.

    ``success`` means at least one structurally admitted candidate, not a correct
    interpretation or answer. Unknown usage keeps the existing v1 usage counts
    and explicit ``usage_unavailable`` marker; callers must not price it as free.
    """
    validate_candidate_cap(candidate_cap)
    started = time.perf_counter()
    report = {"schema_version": SCHEMA, "provider_id": provider.provider_id,
              "request": request.to_dict(), "candidate_cap": candidate_cap,
              "success": False, "external_calls": 0, "input_tokens": 0,
              "output_tokens": 0, "candidates": [], "admitted_count": 0,
              "external_call_count_complete": True,
              "quality_proxy_calibrated": False, "automatic_retries": 0}
    try:
        response = provider.interpret(replace(request))
    except InterpretationFailure as error:
        report.update(status="provider_failure", failure_category=error.category,
                      error=str(error), **error.usage)
        if error.provenance:
            report["provenance"] = json_copy(error.provenance)
        if hasattr(error, "recorded_usage"):
            report["provenance"] = {**error.provenance, "kind": "replay",
                                    "recorded_usage": error.recorded_usage}
    except Exception as error:
        report.update(status="provider_failure", failure_category=type(error).__name__,
                      error="Candidate Interpretation provider raised an exception", usage_unavailable=True,
                      external_call_count_complete=False)
    else:
        try:
            if not isinstance(response, InterpretationResponse):
                raise ValueError("Provider must return InterpretationResponse")
            report.update(**response.usage, provenance=json_copy(dict(response.provenance)))
            # Candidate-local non-JSON values are preserved in safe textual
            # records. A normal live provider always supplies strict JSON.
            try:
                report["raw_response"] = json_copy(response.payload)
            except ValueError:
                report["raw_response_text"] = json.dumps(response.payload, allow_nan=True)
            candidates = parse_interpretation_candidates(response.payload, request,
                                                         candidate_cap=candidate_cap)
            admitted = sum(item["status"] == "admitted" for item in candidates)
            report.update(candidates=candidates, admitted_count=admitted,
                          success=bool(admitted), status="interpreted" if admitted else "no_admissible_interpretation")
            if not admitted:
                report["error"] = "No candidate passed independent structural admission"
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
            report.update(status="interpretation_invalid", error=str(error))
    if report.get("provenance", {}).get("usage_reported") is False:
        report["usage_unavailable"] = True
    if report.get("provenance", {}).get("external_call_count_complete") is False:
        report["external_call_count_complete"] = False
    report["token_usage_complete"] = not report.get("usage_unavailable", False)
    report["elapsed_ms"] = (time.perf_counter() - started) * 1000
    return report
