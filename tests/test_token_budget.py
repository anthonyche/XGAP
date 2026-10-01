from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from xgap.experiments.hashing import content_hash
from xgap.llm import token_budget as module
from xgap.llm.token_budget import ChatTokenBudgetGuard, LocalPinnedChatTokenizer, TokenizerUnavailable


REVISION = "a" * 40
REAL_LOADER = module._load_local_tokenizer


def payload():
    return {
        "model": "Qwen/Qwen3-32B", "max_tokens": 4096,
        "messages": [
            {"role": "system", "content": "Synthetic system"},
            {"role": "user", "content": json.dumps({"schema": {"type": "object"}})},
        ],
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_schema", "json_schema": {"type": "object"}},
    }


class Counter:
    def __init__(self, count=100):
        self.count = count
        self.identity = {"snapshot_revision": REVISION, "synthetic_test_only": True}
        self.seen = []

    def count_payload_tokens(self, request):
        self.seen.append(copy.deepcopy(request))
        return self.count


def guard(counter):
    return ChatTokenBudgetGuard(
        counter, input_limit=8192, output_limit=4096, context_limit=12288,
        expected_model="Qwen/Qwen3-32B",
    )


@pytest.mark.parametrize("kind", ["generation", "repair"])
@pytest.mark.parametrize("count,passed", [(1, True), (8192, True), (8193, False)])
def test_exact_input_boundary_and_payload_identity(kind, count, passed):
    counter = Counter(count)
    request = payload()
    original = copy.deepcopy(request)
    receipt = guard(counter).check(request, call_kind=kind)
    assert receipt["passed"] is passed
    assert receipt["input_tokens"] == count
    assert receipt["requested_output_tokens"] == 4096
    assert receipt["payload_sha256"] == content_hash(original)
    assert receipt["call_kind"] == kind
    assert counter.seen == [original]
    assert request == original
    assert receipt["reason"] == ("within_budget" if passed else "input_budget_exceeded")
    json.dumps(receipt, allow_nan=False)


@pytest.mark.parametrize("output", [4095, 4097, True, 4096.0, None, "4096"])
def test_cannot_shrink_or_expand_frozen_output_reservation(output):
    counter = Counter()
    request = payload()
    request["max_tokens"] = output
    receipt = guard(counter).check(request, call_kind="generation")
    assert receipt["reason"] == "output_reservation_mismatch"
    assert receipt["input_tokens"] is None
    assert not counter.seen


@pytest.mark.parametrize("count", [0, -1, True, 1.5, "100", None, [1]])
def test_invalid_counts_are_never_accepted(count):
    receipt = guard(Counter(count)).check(payload(), call_kind="generation")
    assert not receipt["passed"]
    assert receipt["reason"] == "invalid_token_count"


def test_model_and_counter_identity_are_bound():
    counter = Counter()
    checker = guard(counter)
    changed = payload()
    changed["model"] = "different-model"
    assert checker.check(changed, call_kind="generation")["reason"] == "model_mismatch"
    counter.identity["snapshot_revision"] = "b" * 40
    assert checker.check(payload(), call_kind="generation")["reason"] == "tokenization_unavailable"
    assert not counter.seen


def test_counting_failure_is_explicit_and_does_not_leak_exception(monkeypatch):
    counter = Counter()

    def fail(request):
        raise RuntimeError("sensitive request contents")

    monkeypatch.setattr(counter, "count_payload_tokens", fail)
    receipt = guard(counter).check(payload(), call_kind="generation")
    assert receipt["reason"] == "tokenization_unavailable"
    assert receipt["input_tokens"] is None
    assert "sensitive" not in json.dumps(receipt)


def test_counter_cannot_mutate_payload_or_identity(monkeypatch):
    counter = Counter()
    request = payload()
    original = copy.deepcopy(request)

    def mutate(checked):
        checked["messages"].clear()
        return 10

    monkeypatch.setattr(counter, "count_payload_tokens", mutate)
    assert guard(counter).check(request, call_kind="generation")["reason"] == "counter_mutated_payload"
    assert request == original

    def change_identity(checked):
        counter.identity["changed"] = True
        return 10

    monkeypatch.setattr(counter, "count_payload_tokens", change_identity)
    assert guard(counter).check(request, call_kind="repair")["reason"] == "tokenization_unavailable"


@pytest.mark.parametrize("extra", [
    {"tools": []}, {"truncate_prompt_tokens": 8192}, {"add_generation_prompt": False},
    {"chat_template_kwargs": {"truncation": True}},
    {"chat_template_kwargs": {"enable_thinking": "false"}},
    {"messages": [{"role": "user", "content": [{"type": "image_url"}]}]},
    {"messages": [{"role": "tool", "content": "test"}]},
    {"messages": []},
])
def test_unsupported_template_inputs_fail_closed(extra):
    request = {**payload(), **extra}
    assert guard(Counter()).check(request, call_kind="generation")["reason"] == "unsupported_chat_payload"


@pytest.mark.parametrize("limits", [
    (0, 1, 1), (True, 1, 2), (1.0, 1, 2), (2, 2, 3), (1, -1, 2),
])
def test_invalid_budget_contract(limits):
    with pytest.raises(ValueError):
        ChatTokenBudgetGuard(Counter(), input_limit=limits[0], output_limit=limits[1],
                             context_limit=limits[2], expected_model="test")


class FakeTokenizer:
    template = "synthetic-template-v1"
    is_fast = True
    vocab_files_names = {"tokenizer_file": "tokenizer.json"}

    def __init__(self):
        self.calls = []

    def get_chat_template(self):
        return self.template

    def apply_chat_template(self, messages, **kwargs):
        self.calls.append((copy.deepcopy(messages), kwargs))
        return [1, 2, 3, 4]


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    path = tmp_path / "models--Synthetic--test" / "snapshots" / REVISION
    path.mkdir(parents=True)
    (path / "tokenizer.json").write_text("{}")
    (path / "tokenizer_config.json").write_text("{}")
    tokenizer = FakeTokenizer()
    seen = []

    def loader(local_path):
        seen.append(local_path)
        return tokenizer

    monkeypatch.setattr(module, "_versions", lambda: {"transformers": "test", "tokenizers": "test"})
    monkeypatch.setattr(module, "_load_local_tokenizer", loader)
    return path, tokenizer, seen


@pytest.mark.parametrize("method,expected", [
    ("count_payload_tokens", 4), ("payload_token_ids", (1, 2, 3, 4)),
])
@pytest.mark.parametrize("repair", [False, True])
def test_local_template_receives_exact_messages_once_and_no_truncation(snapshot, method, expected, repair):
    path, tokenizer, loaded = snapshot
    counter = LocalPinnedChatTokenizer(path, REVISION)
    request = payload()
    if repair:
        request["messages"].extend([
            {"role": "assistant", "content": '{"synthetic": "invalid"}'},
            {"role": "user", "content": "Repair the synthetic response."},
        ])
    original = copy.deepcopy(request)
    assert getattr(counter, method)(request) == expected
    assert loaded == [path]
    assert tokenizer.calls == [(original["messages"], {
        "tokenize": True, "add_generation_prompt": True, "truncation": False,
        "padding": False, "enable_thinking": False,
    })]
    assert request == original
    identity = counter.identity
    assert identity["snapshot_revision"] == REVISION
    assert identity["remote_serving_parity_verified"] is False
    assert set(identity["tokenizer_files"]) == {"tokenizer.json", "tokenizer_config.json"}
    expected_hash = identity.pop("identity_sha256")
    assert content_hash(identity) == expected_hash
    identity["library_versions"].clear()
    assert counter.identity["library_versions"]


def test_token_ids_preserve_order_duplicates_zero_and_detach_from_owned_list(snapshot, monkeypatch):
    path, tokenizer, _ = snapshot
    tokens = [3, 0, 3, 1]
    monkeypatch.setattr(tokenizer, "apply_chat_template", lambda *args, **kwargs: tokens)
    counter = LocalPinnedChatTokenizer(path, REVISION)
    original_identity = counter.identity
    first = counter.payload_token_ids(payload())
    assert type(first) is tuple
    assert first == (3, 0, 3, 1)
    with pytest.raises(TypeError):
        first[0] = 1
    tokens[:] = [1, 3, 0, 3]
    second = counter.payload_token_ids(payload())
    assert first == (3, 0, 3, 1)
    assert second == (1, 3, 0, 3)
    assert len(first) == len(second) == counter.count_payload_tokens(payload())
    assert first != second
    assert counter.identity == original_identity


def test_count_delegates_once_to_public_token_ids(snapshot, monkeypatch):
    path, tokenizer, _ = snapshot
    counter = LocalPinnedChatTokenizer(path, REVISION)
    request = payload()
    calls = []

    def token_ids(actual):
        calls.append(actual)
        return (7, 0, 7)

    monkeypatch.setattr(counter, "payload_token_ids", token_ids)
    assert counter.count_payload_tokens(request) == 3
    assert calls == [request]
    assert calls[0] is request
    assert not tokenizer.calls


def test_loader_forces_offline_no_remote_code(snapshot, monkeypatch):
    import sys
    from types import SimpleNamespace

    path, tokenizer, _ = snapshot
    calls = []

    def load(*args, **kwargs):
        calls.append((args, kwargs))
        return tokenizer

    # Directly exercise the original loader helper, not the fixture substitute.
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        AutoTokenizer=SimpleNamespace(from_pretrained=load)
    ))
    assert REAL_LOADER(path) is tokenizer
    assert calls == [((str(path),), {"local_files_only": True, "trust_remote_code": False})]


@pytest.mark.parametrize("change", ["file", "template", "version", "new_file", "removed_file", "config"])
@pytest.mark.parametrize("method", ["count_payload_tokens", "payload_token_ids"])
def test_identity_drift_rejected_before_tokenization(snapshot, monkeypatch, change, method):
    path, tokenizer, _ = snapshot
    counter = LocalPinnedChatTokenizer(path, REVISION)
    if change == "file":
        (path / "tokenizer.json").write_text('{"changed": true}')
    elif change == "template":
        tokenizer.template = "other"
    elif change == "version":
        monkeypatch.setattr(module, "_versions", lambda: {"transformers": "other", "tokenizers": "test"})
    elif change == "new_file":
        (path / "added_tokens.json").write_text("{}")
    elif change == "config":
        (path / "config.json").write_text('{"model_type": "other"}')
    else:
        (path / "tokenizer_config.json").unlink()
    with pytest.raises(TokenizerUnavailable):
        getattr(counter, method)(payload())
    assert not tokenizer.calls


@pytest.mark.parametrize("change", ["file", "template", "version"])
@pytest.mark.parametrize("method", ["count_payload_tokens", "payload_token_ids"])
def test_identity_drift_during_tokenization_rejects_rendered_ids(snapshot, monkeypatch, change, method):
    path, tokenizer, _ = snapshot
    counter = LocalPinnedChatTokenizer(path, REVISION)
    render = tokenizer.apply_chat_template

    def change_while_rendering(*args, **kwargs):
        result = render(*args, **kwargs)
        if change == "file":
            (path / "tokenizer.json").write_text('{"changed": true}')
        elif change == "template":
            tokenizer.template = "other"
        else:
            monkeypatch.setattr(module, "_versions", lambda: {"transformers": "other", "tokenizers": "test"})
        return result

    monkeypatch.setattr(tokenizer, "apply_chat_template", change_while_rendering)
    with pytest.raises(TokenizerUnavailable, match="identity changed"):
        getattr(counter, method)(payload())
    assert len(tokenizer.calls) == 1


def test_ordinary_hf_blob_symlink_allowed_but_escape_rejected(snapshot, tmp_path):
    path, _, _ = snapshot
    blob = path.parent.parent / "blobs" / "synthetic"
    blob.parent.mkdir()
    blob.write_text("{}")
    token_file = path / "tokenizer.json"
    token_file.unlink()
    token_file.symlink_to(blob)
    assert LocalPinnedChatTokenizer(path, REVISION).count_payload_tokens(payload()) == 4
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    token_file.unlink()
    token_file.symlink_to(outside)
    with pytest.raises(TokenizerUnavailable):
        LocalPinnedChatTokenizer(path, REVISION)


@pytest.mark.parametrize("revision", ["main", "short", "b" * 40])
def test_moving_or_mismatched_revision_rejected_without_loading(snapshot, revision):
    path, _, loaded = snapshot
    with pytest.raises(TokenizerUnavailable):
        LocalPinnedChatTokenizer(path, revision)
    assert not loaded


def test_missing_artifacts_and_template_fail_closed(snapshot):
    path, tokenizer, _ = snapshot
    tokenizer.template = ""
    with pytest.raises(TokenizerUnavailable):
        LocalPinnedChatTokenizer(path, REVISION)
    tokenizer.template = "synthetic-template-v1"
    (path / "tokenizer.json").unlink()
    with pytest.raises(TokenizerUnavailable):
        LocalPinnedChatTokenizer(path, REVISION)


@pytest.mark.parametrize("attribute,value", [
    ("is_fast", False), ("vocab_files_names", {"vocab_file": "unknown.model"}),
])
def test_unknown_loading_footprint_rejected(snapshot, attribute, value):
    path, tokenizer, _ = snapshot
    setattr(tokenizer, attribute, value)
    with pytest.raises(TokenizerUnavailable):
        LocalPinnedChatTokenizer(path, REVISION)


@pytest.mark.parametrize("tokens", [[], [[1]], [True], [-1], [1.0], [None], "123", (1, 2), None])
@pytest.mark.parametrize("method", ["count_payload_tokens", "payload_token_ids"])
def test_non_tokenizer_sequence_cannot_be_a_measurement(snapshot, monkeypatch, tokens, method):
    path, tokenizer, _ = snapshot
    monkeypatch.setattr(tokenizer, "apply_chat_template", lambda *args, **kwargs: tokens)
    with pytest.raises(TokenizerUnavailable):
        getattr(LocalPinnedChatTokenizer(path, REVISION), method)(payload())


def test_real_optional_tokenizer_local_roundtrip_without_download(tmp_path):
    transformers = pytest.importorskip("transformers")
    tokenizers = pytest.importorskip("tokenizers")
    path = tmp_path / "models--Synthetic--test" / "snapshots" / REVISION
    path.mkdir(parents=True)
    backend = tokenizers.Tokenizer(tokenizers.models.WordLevel(
        {"[UNK]": 0, "system": 1, "user": 2, "assistant": 3, "Hello": 4, "World": 5},
        unk_token="[UNK]",
    ))
    backend.pre_tokenizer = tokenizers.pre_tokenizers.WhitespaceSplit()
    tokenizer = transformers.PreTrainedTokenizerFast(tokenizer_object=backend, unk_token="[UNK]")
    tokenizer.chat_template = (
        "{% for message in messages %}{{ message['role'] + ' ' + message['content'] + ' ' }}{% endfor %}"
        "{% if add_generation_prompt %}assistant{% endif %}"
    )
    tokenizer.save_pretrained(path)
    counter = LocalPinnedChatTokenizer(path, REVISION)
    request = payload()
    request["messages"] = [{"role": "system", "content": "Hello"}, {"role": "user", "content": "World"}]
    # Five known token IDs from the actual local tokenizer, not a fake count.
    identity = counter.identity
    token_ids = counter.payload_token_ids(request)
    assert token_ids == (1, 4, 2, 5, 3)
    assert counter.count_payload_tokens(request) == len(token_ids) == 5
    assert guard(counter).check(request, call_kind="generation")["input_tokens"] == 5
    assert counter.identity["remote_serving_parity_verified"] is False
    assert counter.identity == identity
