"""Current v2 replay and canonical contract guidance only; no external calls."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import socket

import pytest

from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.experiments.finbench_semantic import load_financial_provider
from xgap.llm.candidate_interpretation import candidate_interpretation_schema
from xgap.semantic.interpretation_candidates import parse_interpretation_candidates
from test_financial_nl_failure import request_from_saved


def test_saved_v2_condition_error_remains_rejected(monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('Unexpected network'))
    path = Path(__file__).parent/'fixtures/financial_nl_failure_v2.json'
    saved = json.loads(path.read_text()); payload = json.loads(saved['raw_response'])
    records = parse_interpretation_candidates(payload, request_from_saved(saved), candidate_cap=1)
    assert len(records)==1 and records[0]['status']=='invalid'
    assert "unknown fields ['conditions']" in records[0]['error']
    assert records[0]['raw_candidate']==payload['candidates'][0]


def test_hybrid_guidance_is_exact_local_schema_and_preserves_working_envelope(monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('Unexpected network'))
    path = Path(__file__).parent/'fixtures/financial_nl_failure_v2.json'
    request = request_from_saved(json.loads(path.read_text()))
    old_root = Path('/Users/anthonyche/xgap-data/financial-nl-native-20260912-v2/profile')
    old = json.loads((old_root/'profile.json').read_text())
    for mode in ('precision','performance'):
        v2 = load_financial_provider(mode=mode,disable_thinking=True,syntax_profile='v2')
        assert hashlib.sha256(v2.system_prompt.encode()).hexdigest()==old['modes'][mode]['provider']['prompt']['sha256']
        v3 = load_financial_provider(mode=mode,disable_thinking=True,syntax_profile='v3')
        schema_text = v3.system_prompt.split('BEGIN LOCAL RESPONSE SPECIFICATION\n')[1].split('\nEND LOCAL RESPONSE SPECIFICATION')[0]
        assert json.loads(schema_text)==candidate_interpretation_schema(v3.config.candidate_cap)
        assert v3.config.structured_schema==v2.config.structured_schema
        assert v3.config.max_repair_calls==0 and v3.config.max_tokens==v2.config.max_tokens
        current = replace(request,context={**request.context,'one_shot_profile':OneShotPolicy.for_mode(mode).to_dict()})
        assert v3.token_guard.check(v3.build_request_payload(current),call_kind='generation')['passed']
