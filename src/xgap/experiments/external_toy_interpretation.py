"""Explicit external-model development binding; no exact-tokenizer claim."""

from dataclasses import dataclass
import json
from pathlib import Path
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

from xgap.experiments.hashing import content_hash
from xgap.experiments.toy_live_interpretation import (
    PROMPT_PATH, run_toy_model_requests, toy_model_requests,
)
from xgap.llm.interpretation import INTERPRETATION_SCHEMA, OpenAICompatibleInterpretationProvider
from xgap.llm.openai_compatible import (
    LiveFailureCategory, OpenAICompatibleProviderConfig, ProviderTransportError,
)
from xgap.llm.token_budget import _text_chat_inputs


PROFILE = "xgap-external-toy-development-v1"
REQUEST_BYTES = 65_536
RESPONSE_BYTES = 1_048_576
OUTPUT_TOKENS = 4096
TIMEOUT_SECONDS = 120


def _endpoint(base_url):
    if not isinstance(base_url, str) or base_url != base_url.strip():
        raise ValueError("An explicit external base URL is required")
    parsed = urllib.parse.urlsplit(base_url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or any(c.isspace() for c in base_url)
            or parsed.path.rstrip("/") != "/v1"):
        raise ValueError("External URL must name /v1 without credentials, query or fragment")
    # Validate malformed port strings before any model action.
    _ = parsed.port
    return base_url.rstrip("/")


@dataclass(frozen=True)
class ExternalChatRequestGuard:
    """A full-request byte cap and output reservation, never a token estimate."""

    expected_model: str
    request_byte_limit: int = REQUEST_BYTES
    output_limit: int = OUTPUT_TOKENS

    def __post_init__(self):
        if not isinstance(self.expected_model, str) or not self.expected_model.strip():
            raise ValueError("An exact served model alias is required")
        for actual, maximum in ((self.request_byte_limit, REQUEST_BYTES), (self.output_limit, OUTPUT_TOKENS)):
            if type(actual) is not int or not 0 < actual <= maximum:
                raise ValueError("External development budget exceeds the fixed profile")

    def check(self, payload, *, call_kind):
        record = {"schema_version": "xgap-external-chat-request-budget-v1",
                  "call_kind": call_kind, "payload_sha256": content_hash(payload),
                  "passed": False, "reason": None, "input_tokens": None,
                  "exact_input_tokens_verified": False, "context_fit_verified": False,
                  "requested_output_tokens": payload.get("max_tokens"),
                  "request_bytes": len(json.dumps(payload, ensure_ascii=True, allow_nan=False).encode("utf-8")),
                  "budgets": {"request_bytes": self.request_byte_limit, "output_tokens": self.output_limit}}
        if call_kind != "generation":
            record["reason"] = "repair_not_permitted"
        elif payload.get("model") != self.expected_model:
            record["reason"] = "model_mismatch"
        elif type(payload.get("max_tokens")) is not int or payload["max_tokens"] != self.output_limit:
            record["reason"] = "output_reservation_mismatch"
        else:
            try:
                _text_chat_inputs(payload)
            except ValueError:
                record["reason"] = "unsupported_chat_payload"
            if record["reason"] is None and record["request_bytes"] > self.request_byte_limit:
                record["reason"] = "request_byte_budget_exceeded"
        if record["reason"] is None:
            record.update(passed=True, reason="development_byte_budget_passed")
        return record


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class BoundedExternalChatTransport:
    """Same chat protocol with no redirect/retry and a bounded response read."""

    def post_json(self, *, url, api_key, payload, timeout_seconds):
        body = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode("utf-8")
        if len(body) > REQUEST_BYTES or not 0 < timeout_seconds <= TIMEOUT_SECONDS:
            raise ValueError("External request exceeds the development profile")
        request = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": "Bearer " + api_key, "Content-Type": "application/json",
            "User-Agent": "xgap-external-toy/1"})
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout_seconds) as response:
                raw = response.read(RESPONSE_BYTES + 1)
            if len(raw) > RESPONSE_BYTES:
                raise ProviderTransportError(LiveFailureCategory.PROVIDER_ERROR, "External response exceeds 1 MiB")
            try:
                result = json.loads(raw)
            except (ValueError, UnicodeDecodeError) as error:
                raise ProviderTransportError(LiveFailureCategory.PROVIDER_ERROR,
                    "External response is not JSON: " + raw[:1000].decode(errors="replace").replace(api_key, "[REDACTED]")) from error
        except urllib.error.HTTPError as error:
            detail = error.read(1000).decode(errors="replace").replace(api_key, "[REDACTED]")
            raise ProviderTransportError(LiveFailureCategory.PROVIDER_ERROR,
                f"External endpoint returned HTTP {error.code}: {detail}") from error
        except (TimeoutError, socket.timeout) as error:
            raise ProviderTransportError(LiveFailureCategory.TIMEOUT, "External provider request timed out") from error
        except urllib.error.URLError as error:
            category = LiveFailureCategory.TIMEOUT if isinstance(error.reason, (TimeoutError, socket.timeout)) else LiveFailureCategory.PROVIDER_ERROR
            raise ProviderTransportError(category, "External provider connection failed: " + str(error.reason).replace(api_key, "[REDACTED]")) from error
        if not isinstance(result, dict):
            raise ProviderTransportError(LiveFailureCategory.PROVIDER_ERROR, "External response is not an object")
        return result


def _profile_prompt(request_profile):
    if request_profile == "legacy-v2":
        return PROMPT_PATH.read_text(encoding="utf-8")
    if request_profile == "explicit-output-v1":
        return PROMPT_PATH.with_name("semantic_program_v3.txt").read_text(encoding="utf-8")
    raise ValueError("Unsupported toy request profile")


def load_external_toy_provider(*, base_url, model, api_key_env="XGAP_EXTERNAL_LLM_API_KEY", disable_thinking=False,
                              request_profile="legacy-v2"):
    """Explicitly select the development byte-budget profile, with no downloads."""
    if (not isinstance(model, str) or model != model.strip() or not model or len(model) > 256
            or any(ord(c) < 32 for c in model)):
        raise ValueError("An explicit served model identifier is required")
    if not isinstance(api_key_env, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", api_key_env):
        raise ValueError("A credential environment-variable name is required")
    if type(disable_thinking) is not bool:
        raise ValueError("Thinking override must be explicit boolean")
    prompt = _profile_prompt(request_profile)
    identity = PROFILE + (":explicit-output-v1" if request_profile == "explicit-output-v1" else "")
    config = OpenAICompatibleProviderConfig(
        provider_id=identity + ":" + model, base_url=_endpoint(base_url), api_key_env=api_key_env,
        model=model, temperature=0, top_p=1, max_tokens=OUTPUT_TOKENS, candidate_cap=1,
        timeout_seconds=TIMEOUT_SECONDS, structured_output_mode="json_schema",
        structured_schema=INTERPRETATION_SCHEMA, prompt_hash=content_hash(prompt), max_repair_calls=0,
        extra_parameters={"chat_template_kwargs": {"enable_thinking": False}} if disable_thinking else {})
    return OpenAICompatibleInterpretationProvider(config, prompt, ExternalChatRequestGuard(model), BoundedExternalChatTransport())


def external_toy_preflight(provider, *, request_profile="legacy-v2"):
    if provider.config.prompt_hash != content_hash(_profile_prompt(request_profile)):
        raise ValueError("Toy request profile does not match the configured prompt")
    checks = [{"query_id": qid, "request_budget": provider.token_guard.check(
        provider.build_request_payload(request), call_kind="generation")}
        for qid, request in toy_model_requests(request_profile=request_profile)]
    return {"schema_version": PROFILE, "paper_result": False, "external_calls": 0,
            "success": all(c["request_budget"]["passed"] for c in checks),
            "config": provider.config.safe_dict(), "checks": checks,
            "request_profile": request_profile,
            "live_endpoint_verified": False, "checkpoint_identity_verified": False,
            "exact_input_tokens_verified": False, "context_fit_verified": False,
            "response_byte_limit": RESPONSE_BYTES, "timeout_semantics": "urllib socket timeout, not a wall-clock deadline"}


def run_external_toy_requests(provider, output, *, max_requests=1, start_index=0, request_profile="legacy-v2"):
    preflight = external_toy_preflight(provider, request_profile=request_profile)
    # The shared runner persists this intent before any call; its guard refuses
    # an oversized actual payload and stops the batch without dispatching it.
    return run_toy_model_requests(provider, output, max_requests=max_requests, start_index=start_index,
                                  run_metadata=preflight, request_profile=request_profile)


def main(argv=None):
    import argparse
    import os

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", default="XGAP_EXTERNAL_LLM_API_KEY")
    parser.add_argument("--output", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-requests", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--start-index", type=int, choices=range(5), default=0,
                        help="Zero-based first question; permits continuing with an unattempted suffix")
    parser.add_argument("--disable-thinking", action="store_true", help="Explicitly request the optional chat-template override")
    parser.add_argument("--request-profile", choices=("legacy-v2", "explicit-output-v1"), default="legacy-v2")
    args = parser.parse_args(argv)
    provider = load_external_toy_provider(base_url=args.base_url, model=args.model,
        api_key_env=args.api_key_env, disable_thinking=args.disable_thinking, request_profile=args.request_profile)
    if args.execute:
        if not os.environ.get(args.api_key_env):
            parser.error("The named API-key environment variable is unset")
        report = run_external_toy_requests(provider, args.output, max_requests=args.max_requests,
            start_index=args.start_index, request_profile=args.request_profile)
        success = report["requested_window_success"] and report["requested_window_replay_size_admitted"]
    else:
        report = external_toy_preflight(provider, request_profile=args.request_profile)
        with Path(args.output).open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write("\n")
        success = report["success"]
    print(json.dumps({"success": success, "external_calls": report["external_calls"],
        "output": args.output, "scope": "external toy development; no exact token/context verification"}))
    return 0 if success else 1
