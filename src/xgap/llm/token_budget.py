"""Offline, exact chat-template token counting with explicit local provenance.

This measures the assembled text request, not a reservation or a character
estimate. Matching a remote serving template is a separate admission check.
No model weights, credentials, remote code, or downloads are used here.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import json
import re
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol

from xgap.experiments.hashing import content_hash


class TokenizerUnavailable(ValueError):
    """An exact, stable local tokenizer cannot be established."""


class PayloadTokenCounter(Protocol):
    @property
    def identity(self) -> Mapping[str, Any]: ...

    def count_payload_tokens(self, payload: Mapping[str, Any]) -> int: ...


def _versions() -> dict[str, str]:
    return {
        name: importlib.metadata.version(name)
        for name in ("transformers", "tokenizers", "jinja2")
    }


def _load_local_tokenizer(path: Path) -> Any:
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(
        str(path), local_files_only=True, trust_remote_code=False
    )


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class LocalPinnedChatTokenizer:
    """Load only an explicitly named, existing Hugging Face cache snapshot.

    This profile supports tokenizer.json-backed text tokenizers, including the
    frozen Qwen deployment. Snapshot-file symlinks within the same model cache
    (including HF's blob store) are permitted. Symlinks outside that cache,
    moving refs, missing templates, and changed files fail closed. Local
    identity is NOT proof of remote template parity.
    """

    _FILES = (
        "config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
        "added_tokens.json", "vocab.json", "merges.txt", "tokenizer.model", "chat_template.jinja",
    )

    def __init__(self, snapshot_path: Path, revision: str) -> None:
        path = Path(snapshot_path).absolute()
        if (
            not re.fullmatch(r"[0-9a-f]{40}", revision)
            or path.name != revision
            or path.parent.name != "snapshots"
            or path.is_symlink()
            or not path.is_dir()
        ):
            raise TokenizerUnavailable("An existing exact snapshot revision is required.")
        self._path = path.resolve(strict=True)
        self._cache_root = self._path.parent.parent
        self._revision = revision
        try:
            files = self._snapshot_files()
            versions = _versions()
            self._tokenizer = _load_local_tokenizer(self._path)
            vocab_files = getattr(self._tokenizer, "vocab_files_names", None)
            if (
                getattr(self._tokenizer, "is_fast", False) is not True
                or not isinstance(vocab_files, dict)
                or "tokenizer.json" not in vocab_files.values()
                or any(name not in self._FILES for name in vocab_files.values())
            ):
                raise TokenizerUnavailable("Unsupported tokenizer loading footprint.")
            template = self._effective_template()
            if self._snapshot_files() != files or _versions() != versions:
                raise TokenizerUnavailable("Tokenizer identity changed during loading.")
        except TokenizerUnavailable:
            raise
        except Exception as error:
            raise TokenizerUnavailable("Pinned local tokenizer could not be loaded.") from error
        self._files = files
        self._library_versions = versions
        self._template = template
        self._identity = {
            "schema_version": "xgap-local-chat-tokenizer-identity-v1",
            "snapshot_path": str(self._path),
            "snapshot_revision": revision,
            "tokenizer_class": type(self._tokenizer).__name__,
            "library_versions": versions,
            "tokenizer_files": files,
            "chat_template_sha256": hashlib.sha256(template.encode("utf-8")).hexdigest(),
            "counting_method": "apply_chat_template_tokenize_add_generation_prompt",
            "remote_serving_parity_verified": False,
        }
        self._identity["identity_sha256"] = content_hash(self._identity)

    def _snapshot_files(self) -> dict[str, str]:
        if not self._path.is_dir() or self._path.is_symlink():
            raise TokenizerUnavailable("Tokenizer snapshot changed.")
        result = {}
        paths = [self._path / name for name in self._FILES]
        templates = self._path / "chat_templates"
        if templates.exists() or templates.is_symlink():
            if templates.is_symlink() or not templates.is_dir():
                raise TokenizerUnavailable("Unsafe chat template directory.")
            paths.extend(sorted(templates.glob("*.jinja")))
        for path in paths:
            if not path.exists() and not path.is_symlink():
                continue
            target = path.resolve(strict=True)
            if not target.is_relative_to(self._cache_root) or not target.is_file():
                raise TokenizerUnavailable("Tokenizer artifact escapes its model cache.")
            result[path.relative_to(self._path).as_posix()] = _file_hash(target)
        if not {"tokenizer.json", "tokenizer_config.json"}.issubset(result):
            raise TokenizerUnavailable("Required tokenizer artifacts are missing.")
        return result

    def _effective_template(self) -> str:
        template = self._tokenizer.get_chat_template()
        if not isinstance(template, str) or not template.strip():
            raise TokenizerUnavailable("An explicit chat template is required.")
        return template

    def _verify_identity(self) -> None:
        if (
            self._snapshot_files() != self._files
            or _versions() != self._library_versions
            or self._effective_template() != self._template
        ):
            raise TokenizerUnavailable("Pinned tokenizer identity changed.")

    @property
    def identity(self) -> dict[str, Any]:
        return copy.deepcopy(self._identity)

    def count_payload_tokens(self, payload: Mapping[str, Any]) -> int:
        self._verify_identity()
        messages, template_kwargs = _text_chat_inputs(payload)
        # Schema text already present in messages is counted exactly once.
        # response_format constrains decoding; it is not appended to messages.
        tokens = self._tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True,
            truncation=False, padding=False, **template_kwargs,
        )
        self._verify_identity()
        if not isinstance(tokens, list) or not tokens or any(
            type(token) is not int or token < 0 for token in tokens
        ):
            raise TokenizerUnavailable("Tokenizer did not return a flat token ID sequence.")
        return len(tokens)


def _text_chat_inputs(payload: Mapping[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    supported = {
        "model", "messages", "temperature", "top_p", "max_tokens", "seed",
        "response_format", "chat_template_kwargs",
    }
    if set(payload) - supported:
        raise ValueError("Unsupported request fields may change template rendering.")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("A nonempty text message sequence is required.")
    for message in messages:
        if (
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or not isinstance(message["role"], str)
            or message["role"] not in {"system", "user", "assistant"}
            or not isinstance(message["content"], str)
        ):
            raise ValueError("Only explicit text-only chat messages are supported.")
    kwargs = payload.get("chat_template_kwargs", {})
    if not isinstance(kwargs, dict) or set(kwargs) - {"enable_thinking"}:
        raise ValueError("Unsupported chat template overrides.")
    if "enable_thinking" in kwargs and type(kwargs["enable_thinking"]) is not bool:
        raise ValueError("enable_thinking must be boolean.")
    return copy.deepcopy(messages), copy.deepcopy(kwargs)


class ChatTokenBudgetGuard:
    """Check a complete generation or repair payload without changing it."""

    def __init__(
        self, counter: PayloadTokenCounter, *, input_limit: int, output_limit: int,
        context_limit: int, expected_model: str,
    ) -> None:
        if any(type(n) is not int or n <= 0 for n in (input_limit, output_limit, context_limit)):
            raise ValueError("Token limits must be positive integers.")
        if input_limit + output_limit > context_limit:
            raise ValueError("Input and output reservations exceed context capacity.")
        if not isinstance(expected_model, str) or not expected_model.strip():
            raise ValueError("An exact served-model identifier is required.")
        self._counter = counter
        self._model = expected_model
        self._budgets = {"input": input_limit, "output": output_limit, "context": context_limit}
        self._identity = json.loads(json.dumps(dict(counter.identity), allow_nan=False))
        if not self._identity:
            raise ValueError("Tokenizer provenance is required.")

    def check(
        self, payload: Mapping[str, Any], *, call_kind: Literal["generation", "repair"]
    ) -> dict[str, Any]:
        if call_kind not in {"generation", "repair"}:
            raise ValueError("Unknown model call kind.")
        # Invalid/non-JSON inputs are programmer errors, not measurable requests.
        checked = json.loads(json.dumps(dict(payload), allow_nan=False))
        request_hash = content_hash(checked)
        output = checked.get("max_tokens")
        record = {
            "schema_version": "xgap-chat-token-budget-check-v1",
            "call_kind": call_kind,
            "payload_sha256": request_hash,
            "passed": False,
            "reason": None,
            "input_tokens": None,
            "requested_output_tokens": output,
            "budgets": dict(self._budgets),
            "tokenizer_identity": copy.deepcopy(self._identity),
        }
        if checked.get("model") != self._model:
            record["reason"] = "model_mismatch"
            return record
        if type(output) is not int or output != self._budgets["output"]:
            record["reason"] = "output_reservation_mismatch"
            return record
        try:
            _text_chat_inputs(checked)
        except ValueError:
            record["reason"] = "unsupported_chat_payload"
            return record
        try:
            if dict(self._counter.identity) != self._identity:
                raise TokenizerUnavailable("Tokenizer identity changed.")
            count = self._counter.count_payload_tokens(checked)
            if content_hash(checked) != request_hash:
                record["reason"] = "counter_mutated_payload"
                return record
            if dict(self._counter.identity) != self._identity:
                raise TokenizerUnavailable("Tokenizer identity changed.")
            if type(count) is not int or count <= 0:
                record["reason"] = "invalid_token_count"
                return record
        except Exception:
            # Exceptions can contain request text or paths. Keep the public
            # receipt bounded; never substitute a character-count estimate.
            record["reason"] = "tokenization_unavailable"
            return record
        record["input_tokens"] = count
        if count > self._budgets["input"]:
            record["reason"] = "input_budget_exceeded"
        elif count + output > self._budgets["context"]:
            record["reason"] = "context_budget_exceeded"
        else:
            record.update(passed=True, reason="within_budget")
        return record
