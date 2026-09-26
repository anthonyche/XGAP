"""Portable public request contracts; mocked transport, no model/backend calls."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from xgap.experiments.compact_profile import load_compact_graph_provider
from xgap.experiments.hashing import content_hash
from xgap.llm.public_typed_compact import adapt_public_typed_compact_provider, public_typed_schema, PROFILE
from xgap.semantic.compact_equivalence import PROFILE as EQUIVALENCE
from xgap.semantic.compact_query import SCHEMA_V2
from xgap.semantic.interpretation import InterpretationRequest


def source():
    return {'identity_property': 'cid', 'shared_identity_namespace': 'urn:toy:',
            'graph': {'nodes': {'Person': {'properties': ['id']}, 'Movie': {'properties': ['id']}}, 'edges': [
                {'label': 'RATED', 'source': 'Person', 'target': 'Movie', 'properties': ['value']}]}}


def query(*, node_only=False):
    return dict(nodes=[dict(var='p', type='Person', entity=None)] + ([] if node_only else [
        dict(var='m', type='Movie', entity=None)]), edges=[] if node_only else [
        dict(var='r', type='RATED', source='p', target='m')], path=None,
        where=[], select={'id': {'var': 'p', 'property': 'id'}}, contribution_by=None,
        order_by=[], limit=None)


class Guard:
    def check(self, payload, call_kind):
        assert call_kind == 'generation'
        return {'passed': True}


class Transport:
    def __init__(self, candidate): self.candidate, self.calls = candidate, []
    def post_json(self, **kwargs):
        self.calls.append(kwargs['payload'])
        return {'model': kwargs['payload']['model'], 'choices': [{'finish_reason': 'stop',
            'message': {'content': json.dumps({'schema_version': SCHEMA_V2, 'candidates': [
                {'candidate_id': 'one', 'quality_proxy': None, 'query': self.candidate}]})}}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30}}


def run(monkeypatch, candidate):
    monkeypatch.setenv('XGAP_EXTERNAL_LLM_API_KEY', 'fixture-never-sent')
    original = load_compact_graph_provider(language_version='v2', prompt_version='v2')
    original.config = replace(original.config, normalization_profile=EQUIVALENCE)
    original.token_guard = Guard()
    original.transport = transport = Transport(candidate)
    old_config, old_prompt = original.config.safe_dict(), original.system_prompt
    provider = adapt_public_typed_compact_provider(original)
    response = provider.interpret(InterpretationRequest('Public graph roles.', {'source_schema': source()}))
    assert original.config.safe_dict() == old_config and original.system_prompt == old_prompt
    assert provider.config.normalization_profile == EQUIVALENCE
    assert len(transport.calls) == response.external_calls == 1
    assert response.input_tokens == 10 and response.output_tokens == 20
    assert response.provenance['raw_compact_response']['candidates'][0]['query'] == candidate
    contract = response.provenance['public_type_contract']
    payload = transport.calls[0]
    assert contract['profile'] == PROFILE
    assert contract['actual_structured_schema_sha256'] == content_hash(payload['response_format']['json_schema']['schema'])
    assert contract['actual_prompt_sha256'] == provider.config.prompt_hash
    assert contract['public_source_schema_sha256'] == content_hash(source())
    assert 'strict' not in payload['response_format']['json_schema']
    return response, payload


@pytest.mark.parametrize('node_only', [False, True])
def test_legal_edge_endpoints_and_node_only_queries(monkeypatch, node_only):
    response, payload = run(monkeypatch, query(node_only=node_only))
    assert response.provenance['compact_lowering']['candidates'][0]['status'] == 'lowered'
    q = payload['response_format']['json_schema']['schema']['properties']['candidates']['items']['properties']['query']['properties']
    assert q['nodes']['items']['properties']['type']['enum'] == ['Movie', 'Person']
    assert q['edges']['items']['properties']['type']['enum'] == ['RATED']
    assert q['path']['anyOf'][1]['properties']['type']['enum'] == ['RATED']


@pytest.mark.parametrize('invalid, message', [
    ('duplicate', 'unique identifiers'), ('missing_endpoint', 'endpoints must be declared nodes'),
    ('relation_as_node', 'Unknown node type')])
def test_received_invalid_graph_is_preserved_and_rejected_not_repaired(monkeypatch, invalid, message):
    q = query()
    if invalid == 'duplicate': q['nodes'].append(dict(var='r', type='Person', entity=None))
    elif invalid == 'missing_endpoint': q['nodes'] = q['nodes'][:1]
    else: q['nodes'][0]['type'] = 'RATED'
    response, _ = run(monkeypatch, q)
    record = response.provenance['compact_lowering']['candidates'][0]
    assert record['status'] == 'invalid' and message in record['error']
    assert response.payload['candidates'][0]['program'] is None


def test_empty_relation_domain_and_source_validation_are_public_only():
    schema = source(); schema['graph']['edges'] = []
    before = deepcopy(schema)
    actual = public_typed_schema(schema, 1)
    props = actual['properties']['candidates']['items']['properties']['query']['properties']
    assert props['edges']['maxItems'] == 0 and props['path'] == {'type': 'null'}
    assert schema == before
    malformed = source(); malformed['graph']['edges'][0]['target'] = 'Unknown'
    with pytest.raises(ValueError, match='endpoint type'): public_typed_schema(malformed, 1)
