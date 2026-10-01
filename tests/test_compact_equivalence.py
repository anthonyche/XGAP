"""Observed rejection replay and counterexamples for two exact surface rules."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from xgap.experiments.compact_profile import load_compact_graph_provider
from xgap.llm.compact_interpretation import WIRE_PROFILE_EQUIVALENCE
from xgap.semantic.compact_equivalence import PROFILE, canonicalize_compact_surface
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.interpretation import InterpretationRequest
from xgap.semantic.interpretation_candidates import interpret_candidate_question


FIXTURE = Path(__file__).parent / 'fixtures/compact_identity_equality_failure_3885860.json'


def observed():
    return json.loads(FIXTURE.read_text())


def test_frozen_actual_response_passes_exact_alias_lowering_without_mutating_history():
    data = observed(); query = data['raw_compact_response']['candidates'][0]['query']
    before = deepcopy(query)
    with pytest.raises(ValueError, match='Use variable identity'):
        lower_compact_query(query, data['source_schema'], version='v2')
    canonical, trace = canonicalize_compact_surface(query, data['source_schema'])
    assert len(trace) == 2
    program, sources = lower_compact_query(canonical, data['source_schema'], version='v2')
    assert program and sources and query == before
    for old, new in zip(query['where'], canonical['where']):
        if old['op'] == 'ne':
            assert old['left']['property'] == old['right']['property'] == 'xgap_id'
            assert new['left']['property'] is new['right']['property'] is None
        else:
            assert old == new
    assert canonical['select'] == query['select'] and canonical['edges'] == query['edges']


@pytest.mark.parametrize('variation', ['literal', 'business_id', 'ordered', 'cross_type', 'mixed_identity'])
def test_alias_rule_declines_unproven_variants(variation):
    data = observed(); q = deepcopy(data['raw_compact_response']['candidates'][0]['query'])
    q['where'] = [q['where'][1]]
    p = q['where'][0]
    if variation == 'literal': p['right'] = {'value': 'person:1'}
    elif variation == 'business_id': p['left']['property'] = p['right']['property'] = 'id'
    elif variation == 'ordered': p['op'] = 'lt'
    elif variation == 'cross_type': q['nodes'][0]['type'] = 'DifferentType'
    elif variation == 'mixed_identity': p['right']['property'] = None
    canonical, trace = canonicalize_compact_surface(q, data['source_schema'])
    assert canonical == q and not trace


def test_nonaggregate_contribution_normalization_never_touches_aggregate_grain():
    data = observed(); q = deepcopy(data['raw_compact_response']['candidates'][0]['query'])
    q['where'] = []; q['contribution_by'] = ['e1']
    canonical, trace = canonicalize_compact_surface(q, data['source_schema'])
    assert canonical['contribution_by'] is None
    assert trace == [{'rule': 'nonaggregate_set_projection'}]
    q['select']['total'] = {'aggregate': 'count', 'distinct': True, 'field': {'var': 'e1', 'property': 'id'}}
    canonical, trace = canonicalize_compact_surface(q, data['source_schema'])
    assert canonical == q and not trace


def test_missing_identity_contract_and_ambiguous_declarations_still_fail():
    data = observed(); q = deepcopy(data['raw_compact_response']['candidates'][0]['query'])
    schema = deepcopy(data['source_schema']); schema.pop('shared_identity_namespace')
    with pytest.raises(ValueError, match='shared canonical namespace'):
        canonicalize_compact_surface(q, schema)
    q['nodes'].append({'var': 'e1', 'type': 'KNOWS', 'entity': None})
    with pytest.raises(ValueError, match='unique identifiers'):
        canonicalize_compact_surface(q, data['source_schema'])


def test_opt_in_provider_retains_raw_response_and_compiles_canonical_copy(monkeypatch):
    data = observed(); raw = data['raw_compact_response']
    class Transport:
        calls = 0
        def post_json(self, **kwargs):
            self.calls += 1
            return {'model': kwargs['payload']['model'], 'choices': [
                {'finish_reason': 'stop', 'message': {'content': json.dumps(raw)}}],
                'usage': {'prompt_tokens': 11, 'completion_tokens': 7, 'total_tokens': 18}}
    monkeypatch.setenv('XGAP_EXTERNAL_LLM_API_KEY', 'fixture-never-sent')
    provider = load_compact_graph_provider(language_version='v2', prompt_version='v2')
    provider.config = replace(provider.config, normalization_profile=PROFILE)
    provider.transport = transport = Transport()
    report = interpret_candidate_question(InterpretationRequest('Frozen response compiler replay.',
        {'source_schema': data['source_schema']}), provider, candidate_cap=1)
    assert report['success'] and report['admitted_count'] == 1
    provenance = report['provenance']
    assert provenance['raw_compact_response'] == raw
    assert provenance['canonical_compact_response'] != raw
    assert provenance['config']['wire_profile'] == WIRE_PROFILE_EQUIVALENCE
    assert transport.calls == 1 and report['external_calls'] == 1
    assert report['input_tokens'] == 11 and report['output_tokens'] == 7


def test_profile_revision_freezes_same_prompt_data_and_mapping_without_calls(tmp_path, monkeypatch):
    import hashlib
    import socket
    from test_one_shot_records import prepare_profile
    from xgap.experiments.compact_equivalence_profile import derive_compact_equivalence_profile
    from xgap.experiments.one_shot_profile import FrozenOneShotProfile
    from xgap.experiments.one_shot_records import write_once
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('No network during profile revision'))
    _, doc = prepare_profile(tmp_path / 'original')
    for name, mode in doc['modes'].items():
        provider = load_compact_graph_provider(mode=name, language_version='v2', prompt_version='v2')
        path = tmp_path / ('prompt-' + name + '.txt')
        path.write_text(provider.system_prompt)
        mode['provider']['wire_profile'] = 'compact-graph-schema-v2'
        mode['provider']['prompt'] = dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    parent = write_once(tmp_path / 'parent.json', doc)
    before = Path(parent['path']).read_bytes()
    doc = json.loads(before)
    derived = derive_compact_equivalence_profile(parent_path=parent['path'], parent_sha256=parent['sha256'],
                                                 output=tmp_path / 'equivalent')
    child = FrozenOneShotProfile.load(derived['path'], expected_sha256=derived['sha256'])
    after, _, _, _, _, _, modes = child.materialize()
    for field in ('dataset', 'sources', 'source_schema', 'backends', 'catalog', 'estimator'):
        assert after[field] == doc[field]
    for name, (_, provider) in modes.items():
        assert provider.config.normalization_profile == PROFILE
        assert after['modes'][name]['provider']['prompt'] == doc['modes'][name]['provider']['prompt']
    assert Path(parent['path']).read_bytes() == before
    doc['source_schema']['shared_identity_namespace'] = 'https://incorrect.test/'
    bad = write_once(tmp_path / 'bad-parent.json', doc)
    with pytest.raises(ValueError, match='backend identity mapping'):
        derive_compact_equivalence_profile(parent_path=bad['path'], parent_sha256=bad['sha256'], output=tmp_path / 'bad')
    assert not (tmp_path / 'bad').exists()


def test_nl_entry_passes_equivalent_copy_to_authority_without_free_validation(monkeypatch):
    from xgap.api import answer
    from xgap.agent.one_shot_policy import OneShotPolicy
    from xgap.semantic.intent_scope import ScopePolicy
    from xgap.tools.contracts import ToolResult, ToolStatus
    data = observed(); raw = data['raw_compact_response']
    class Transport:
        def post_json(self, **kwargs):
            return {'model': kwargs['payload']['model'], 'choices': [
                {'finish_reason': 'stop', 'message': {'content': json.dumps(raw)}}],
                'usage': {'prompt_tokens': 11, 'completion_tokens': 7, 'total_tokens': 18}}
    class Authority:
        calls = 0
        def confirm_scope(self, question, family):
            self.calls += 1
            query = json.loads(family.candidates[0].query_json)
            assert all(p['left']['property'] is p['right']['property'] is None
                       for p in query['where'] if p['op'] == 'ne')
            return ToolResult('user.confirm_scope', ToolStatus.SUCCESS, {'covered': False})
        def bind(self, *args):
            pytest.fail('A compiled interpretation does not attest intent')
    monkeypatch.setenv('XGAP_EXTERNAL_LLM_API_KEY', 'fixture-never-sent')
    provider = load_compact_graph_provider(language_version='v2', prompt_version='v2')
    provider.config = replace(provider.config, normalization_profile=PROFILE)
    provider.transport = Transport()
    authority = Authority()
    result = answer(InterpretationRequest('Frozen compiler boundary.', {'source_schema': data['source_schema']}),
        provider, mode='exact', scope_policy=ScopePolicy('test', (), language_version='v2'),
        authority=authority, physical_profile=OneShotPolicy.for_mode('performance'),
        sources={}, backends={}, backend_clients={})
    assert result['status'] == 'intent_outside_proposed_scope'
    assert authority.calls == result['scope_confirmation_calls'] == result['total_user_calls'] == 1
    assert result['model_calls'] == 1 and result['final_plan_executions'] == 0
    assert result['interpretation']['provenance']['raw_compact_response'] == raw


def test_provider_adapter_retains_frozen_payload_and_does_not_mutate_original():
    from types import SimpleNamespace
    from xgap.experiments.compact_equivalence_profile import adapt_compact_provider, PROVIDER
    data = observed(); schema = data['source_schema']
    provider = load_compact_graph_provider(language_version='v2', prompt_version='v2')
    request = InterpretationRequest('A bounded new request.', {'source_schema': schema})
    before = provider.config.safe_dict()
    mapped = SimpleNamespace(identity_property=schema['identity_property'],
                             resource_namespace=schema['shared_identity_namespace'])
    adapted, receipt = adapt_compact_provider(provider, schema, {'graph': mapped})
    assert adapted.build_request_payload(request) == provider.build_request_payload(request)
    assert adapted.transport is provider.transport and adapted.token_guard is provider.token_guard
    assert adapted.system_prompt == provider.system_prompt
    assert provider.config.safe_dict() == before
    assert receipt['provider'] == PROVIDER and receipt['historical_profile_pin_unchanged']
    assert receipt['scope_authority_required'] and adapted.config.normalization_profile == PROFILE
    with pytest.raises(ValueError, match='original compact v2'):
        adapt_compact_provider(adapted, schema, {'graph': mapped})
