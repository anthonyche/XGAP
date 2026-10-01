"""Actual scoped oracle calls and NL -> federated SPARQL -> independent answers."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from test_compact_lowering import inputs, financial_intents, EXPECTED, RESOURCE
from xgap.agent.nl_strong_question import run_nl_strong_question
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.simulated_user import SimulatedUserTool, SimulatedUserPolicy, identity, intent_state
from xgap.backends.fuseki_client import FusekiClient
from xgap.compilers.rdf_encoding import RdfEdgeEncoding
from xgap.compilers.features import default_profile
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.runtime.semantic_compiler import SemanticBackend
from xgap.runtime.semantic_planning import LogicalSource
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.interpretation import InterpretationRequest, InterpretationResponse
from xgap.semantic.interpretation_candidates import SCHEMA


QUESTION = 'Show Alice transfer totals for blocked accounts owned by companies in the stated time window.'


def oracle_file(tmp_path, query, bindings, question=QUESTION):
    path = tmp_path/'private-user.json'
    path.write_text(json.dumps(intent_state(question, query, bindings,
        source_id='annotated-intent', version='toy-v1')))
    return SimulatedUserTool(path, hashlib.sha256(path.read_bytes()).hexdigest())


def invoke(oracle, scope, *, query_hash=None, proposal=None, candidates=()):
    return oracle.invoke(dict(question_sha256=identity(QUESTION), scope=scope,
        query_sha256=query_hash, proposal=proposal, candidates=list(candidates)), None)


def test_scoped_replies_wrong_candidates_and_stale_evidence(tmp_path):
    q = financial_intents()[0]; oracle = oracle_file(tmp_path, q, {'person':'person_1'})
    assert oracle.preflight(QUESTION)['ready']
    user = invoke(oracle, 'query_intent', proposal=q).value
    assert user['outcome'] == 'confirmed' and 'entity_bindings' not in user
    wrong = invoke(oracle, 'entity:person', query_hash=identity(q), candidates=['wrong-person'])
    assert wrong.value['outcome'] == 'none_of_these' and wrong.value['answer'] == 'person_1'
    assert 'query' not in wrong.value and 'answer_rows' not in json.dumps(wrong.to_dict())
    changed = deepcopy(q); changed['where'][0]['right']['value'] = False
    assert invoke(oracle, 'query_intent', proposal=changed).value['outcome'] == 'corrected'
    section = invoke(oracle, 'where', query_hash=identity(q), proposal=q['where'])
    assert section.value['answer'] == q['where'] and section.value['outcome'] == 'confirmed'
    assert invoke(oracle, 'entity:person', query_hash='stale').status.value == 'error'
    assert invoke(oracle, 'physical_plan', query_hash=identity(q)).status.value == 'error'
    # Failed calls still count; preflight discloses no semantic state.
    assert invoke(oracle, 'unknown').metrics['clarification_calls'] == 1
    assert 'person_1' not in json.dumps(oracle.preflight(QUESTION))


def run(inputs, tmp_path, *, mode='exact', max_calls=9, malformed_model=False, two_entities=False):
    schema, catalog, bindings, mapping, graphs = inputs
    q = financial_intents()[0]
    entity = next(b['value'] for k, b in bindings.items() if k.startswith('entity:') and
        any(e['candidate_id']==k and e['canonical_label']=='Alice' for e in catalog['entries']))
    private = {'person': entity}
    if two_entities:
        q['nodes'][1]['entity'] = 'account 1'
        private['sender'] = next(bindings[e['candidate_id']]['value'] for e in catalog['entries']
            if e['kind']=='entity' and e['canonical_label']=='account 1')
    oracle = oracle_file(tmp_path, q, private)
    proposal = deepcopy(q); proposal['where'][0]['right']['value'] = False
    program, assignment = lower_compact_query(proposal, schema)
    calls = []; observations = []

    class Provider:
        provider_id = 'controlled-compact-proposal'
        calls = 0
        def interpret(self, request):
            self.calls += 1
            wire = json.dumps(request.to_dict())
            assert 'private-user' not in wire and 'entity_bindings' not in wire
            assert all(value not in wire for value in private.values())
            payload = {'schema_version': SCHEMA, 'candidates': [{'candidate_id': 'wrong-filter',
                'quality_proxy': .99, 'program': program.to_dict(), 'operator_sources': assignment}]}
            return InterpretationResponse({} if malformed_model else payload,
                provenance={'raw_compact_response': {'candidates':[{'query':proposal}]}, 'usage_reported':True},
                external_calls=1, input_tokens=11, output_tokens=17)

    class LocalSource(FusekiClient):
        def _post_query(self, text):
            calls.append(self.backend_id)
            return json.loads(graphs[self.backend_id].query(text).serialize(format='json'))

    sources = {name:LogicalSource(name, 'tiny-v1', (name,)) for name in graphs}
    backend_mapping = deepcopy(mapping['backend_mapping'])
    backend_mapping['backends'] = {name:backend_mapping['backends']['fuseki'] for name in graphs}
    backend_mapping['term_mappings'] = {name:backend_mapping['term_mappings']['fuseki'] for name in graphs}
    backends = {name:SemanticBackend(name, RESOURCE, 'xgap_id', backend_mapping=backend_mapping,
        profile=replace(default_profile('fuseki'), backend_id=name),
        rdf_edge_encoding=RdfEdgeEncoding(**mapping['rdf_edge_encoding']),
        rdf_node_classes=tuple(mapping['rdf_node_classes'])) for name in graphs}
    clients = {name:LocalSource(BackendDescriptor(name, 'fuseki', 'sparql', 'rdf')) for name in graphs}
    provider = Provider()
    # Bundle identity is public context only. Oracle binding does not depend on
    # the current catalog containing the correct candidate.
    class EmptyBundle:
        identity = 'intentionally-empty-catalog'
    result = run_nl_strong_question(InterpretationRequest(QUESTION, {'source_schema':schema}), provider,
        mode=mode, policy=replace(OneShotPolicy.for_mode('performance'), max_parallelism=1), bundle=EmptyBundle(), sources=sources,
        backends=backends, backend_clients=clients, user_oracle=oracle,
        user_policy=SimulatedUserPolicy(max_calls=max_calls, declared_user_wait_ms_per_call=100),
        on_user_observation=observations.append)
    return result, calls, provider, observations


@pytest.mark.parametrize('mode,malformed,two', [('exact',False,False), ('performance',False,False),
    ('exact',True,False), ('exact',False,True)])
def test_nl_queries_user_corrects_intent_and_executes_once(inputs, tmp_path, mode, malformed, two):
    result, calls, provider, observations = run(inputs, tmp_path, mode=mode,
        malformed_model=malformed, two_entities=two)
    assert result['success'], (result.get('error'), result.get('practical'))
    assert result['answer_rows'] == EXPECTED[0]
    assert provider.calls == result['model_calls'] == result['final_plan_executions'] == 1
    assert result['clarification_calls'] == len(observations) == (3 if two else 2)
    assert result['user_intent_verified'] and result['strong_plan']
    assert result['oracle_outcome'] == 'corrected'
    assert result['backend_remote_calls'] == len(calls) > 0
    assert result['practical']['search']['external_calls_during_search'] == 0
    assert result['unvalidated_bindings'] == []
    assert result['declared_user_wait_ms'] == 100*result['clarification_calls']
    assert result['oracle_processing_ms'] >= 0  # no sleep added to E2E
    assert result['answer_quality_verified'] is False  # independent scorer owns this


def test_budget_exhaustion_retains_paid_observation_and_never_executes(inputs, tmp_path):
    r, calls, provider, observed = run(inputs, tmp_path, max_calls=1)
    assert not r['success'] and not calls and r['final_plan_executions'] == 0
    assert r['model_calls'] == provider.calls == r['clarification_calls'] == len(observed) == 1
    assert 'budget exhausted' in r['error'] and not r['user_intent_verified']


def test_private_configuration_preflight_and_content_pin(tmp_path):
    q = financial_intents()[0]
    with pytest.raises(ValueError, match='every named entity'):
        oracle_file(tmp_path, q, {})
    oracle = oracle_file(tmp_path, q, {'person':'person_1'})
    with pytest.raises(ValueError, match='different question'):
        oracle.preflight('Another question')
    raw = json.loads(oracle.response_path.read_text()); raw['answer_rows'] = []
    oracle.response_path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match='hash mismatch'):
        oracle.preflight(QUESTION)


def test_incomplete_oracle_is_configuration_error_before_model_or_backend(inputs,tmp_path):
    q=financial_intents()[0];oracle=oracle_file(tmp_path,q,{'person':'person_1'})
    raw=json.loads(oracle.response_path.read_text());raw['entity_bindings']={}
    oracle.response_path.write_text(json.dumps(raw))
    oracle=SimulatedUserTool(oracle.response_path,hashlib.sha256(oracle.response_path.read_bytes()).hexdigest())
    class NoCalls:
        def interpret(self,request):pytest.fail('Incomplete oracle reached the model')
    result=run_nl_strong_question(InterpretationRequest(QUESTION,{'source_schema':inputs[0]}),NoCalls(),
        mode='exact',policy=OneShotPolicy.for_mode('performance'),bundle=None,sources={},backends={},
        backend_clients={},user_oracle=oracle)
    assert result['status']=='oracle_configuration_error' and not result['user_intent_verified']
    assert result['model_calls']==result['clarification_calls']==result['final_plan_executions']==0
