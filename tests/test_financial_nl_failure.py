"""Preserved real failure and new prompt wire boundary; no model/database run."""

import hashlib
import json
from pathlib import Path
import socket

import pytest

from xgap.experiments.finbench_semantic import load_financial_provider
from xgap.semantic.interpretation import InterpretationRequest
from xgap.semantic.interpretation_candidates import parse_interpretation_candidates


SAVED = Path(__file__).parent/'fixtures/financial_nl_failure_v1.json'


def request_from_saved(saved):
    raw = dict(saved['request']); raw.pop('schema_version')
    return InterpretationRequest(**raw)


def test_original_financial_failure_remains_invalid_without_repair(monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('Unexpected network'))
    saved = json.loads(SAVED.read_text())
    payload = json.loads(saved['raw_response'])
    before = json.dumps(payload, sort_keys=True)
    records = parse_interpretation_candidates(payload, request_from_saved(saved), candidate_cap=1)
    assert len(records)==1 and records[0]['status']=='invalid'
    assert "unknown fields ['func']" in records[0]['error']
    assert json.dumps(payload, sort_keys=True)==before
    assert saved['observed_usage']=={'external_calls':1, 'input_tokens':3212, 'output_tokens':1970}


def test_explicit_v2_prompt_preserves_v1_identity_and_fits_both_existing_budgets(monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('Unexpected network'))
    saved = json.loads(SAVED.read_text()); request = request_from_saved(saved)
    root = Path('/Users/anthonyche/xgap-data/financial-nl-native-20260912-v1/profile')
    raw = json.loads((root/'profile.json').read_text())
    for mode in ('precision','performance'):
        old = load_financial_provider(mode=mode, disable_thinking=True)
        pin = raw['modes'][mode]['provider']['prompt']['sha256']
        assert hashlib.sha256(old.system_prompt.encode()).hexdigest()==pin
        new = load_financial_provider(mode=mode, disable_thinking=True, syntax_profile='v2')
        assert new.config.prompt_hash != old.config.prompt_hash
        assert new.provider_id.endswith(':financial-binding-v2')
        assert new.config.max_tokens == old.config.max_tokens
        # The ordinary provider guard checks the full new wire payload. No answer
        # or mutated saved response is supplied and no external call is made.
        from dataclasses import replace
        from xgap.agent.one_shot_policy import OneShotPolicy
        current = replace(request, context={**request.context, 'one_shot_profile':OneShotPolicy.for_mode(mode).to_dict()})
        assert new.token_guard.check(new.build_request_payload(current), call_kind='generation')['passed']
        assert 'grouped_bindings' in new.system_prompt and 'identity.property' in new.system_prompt
