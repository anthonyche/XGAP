"""Only new compact wire/recording/estimator integration risks; no network calls."""

from copy import deepcopy
import json

import pytest

from test_compact_lowering import financial_intents
from xgap.agent.one_shot_grounding import ground_interpretation
from xgap.experiments.compact_profile import load_compact_graph_provider
from xgap.experiments.financial_nl_profile import publish_profile, schema_and_catalog, verified_inputs
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.experiments.one_shot_toy import _DurableRecordingProvider
from xgap.runtime.one_shot_planning import prepare_one_shot_domain
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.compact_query import SCHEMA
from xgap.semantic.interpretation import InterpretationRequest
from xgap.semantic.interpretation_candidates import interpret_candidate_question
from xgap.semantic.interpretation_replay import ReplayInterpretationProvider


def request(**kwargs):
    return InterpretationRequest('Find transfers from accounts owned by Alice.',
        {'source_schema': schema_and_catalog(*verified_inputs())[0]}, **kwargs)


class ResponseTransport:
    """Injected model boundary only; never claims actual model correctness/cost."""
    def __init__(self, payload):
        self.payload, self.calls = payload, []

    def post_json(self, **kwargs):
        self.calls.append(kwargs['payload'])
        return {'model': kwargs['payload']['model'], 'choices': [{'finish_reason': 'stop',
            'message': {'content': json.dumps(self.payload)}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30}}


def pool(*intents):
    return {'schema_version': SCHEMA, 'candidates': [{'candidate_id': 'c'+str(i),
        'quality_proxy': None, 'query': q} for i, q in enumerate(intents)]}


def test_independent_lowering_and_durable_raw_response_replay(monkeypatch, tmp_path):
    monkeypatch.setenv('XGAP_EXTERNAL_LLM_API_KEY', 'fixture-key-never-sent')
    good = financial_intents()[0]
    bad = deepcopy(good); bad['select']['bad'] = {'var': 'missing', 'property': 'amount'}
    response = pool(good, bad, good); response['candidates'][2]['quality_proxy'] = 2.0
    provider = load_compact_graph_provider(mode='precision')
    transport = ResponseTransport(response); provider.transport = transport
    recorder = _DurableRecordingProvider(provider, tmp_path/'record.json')
    req = request()
    actual = interpret_candidate_question(req, recorder, candidate_cap=3)
    assert actual['success'] and actual['admitted_count'] == 1
    assert [c['status'] for c in actual['candidates']] == ['admitted', 'invalid', 'invalid']
    assert len(transport.calls) == 1 and actual['external_calls'] == 1
    provenance = actual['provenance']
    assert provenance['raw_compact_response'] == response
    assert provenance['compact_lowering']['elapsed_ms'] >= 0
    assert 'Unknown graph variable' in provenance['compact_lowering']['candidates'][1]['error']
    recorded = json.loads((tmp_path/'record.json').read_text())
    assert 'fixture-key-never-sent' not in json.dumps(recorded)
    replay = ReplayInterpretationProvider.from_path(tmp_path/'record.json')
    replayed = interpret_candidate_question(req, replay, candidate_cap=3)
    replay.assert_consumed()
    assert replayed['candidates'] == actual['candidates'] and replayed['external_calls'] == 0
    assert len(transport.calls) == 1


def test_compact_budget_and_unmappable_constraints_do_not_trigger_fallback(monkeypatch):
    monkeypatch.setenv('XGAP_EXTERNAL_LLM_API_KEY', 'fixture-key-never-sent')
    provider = load_compact_graph_provider()
    transport = ResponseTransport(pool(*financial_intents()[:2])); provider.transport = transport
    result = interpret_candidate_question(request(), provider, candidate_cap=1)
    assert result['failure_category'] == 'compact_envelope_invalid' and result['external_calls'] == 1
    hard = ({'operator_id': 'old-operator', 'constraint': {'policy': 'hard', 'expression': 'keep'}},)
    denied = interpret_candidate_question(request(required_constraints=hard), provider, candidate_cap=1)
    assert denied['failure_category'] == 'preflight_error' and denied['external_calls'] == 0
    assert len(transport.calls) == 1


@pytest.fixture(scope='module')
def profile(tmp_path_factory):
    root = tmp_path_factory.mktemp('compact-provider')/'profile'
    pin = publish_profile(root, endpoints={'neo4j': 'http://localhost:1', 'fuseki': 'http://localhost:2'},
        interpretation_profile='compact-graph-v1')
    return FrozenOneShotProfile.load(root/'profile.json', expected_sha256=pin['sha256'])


def test_frozen_mode_profiles_reconstruct_exact_provider_contract(profile):
    raw, _, _, _, _, _, modes = profile.materialize()
    assert raw['offline']['query_reads'] == raw['offline']['answer_reads'] == 0
    for mode, (policy, reconstructed) in modes.items():
        expected = load_compact_graph_provider(mode=mode)
        assert reconstructed.config.safe_dict() == expected.config.safe_dict()
        assert policy.candidate_cap == (3 if mode == 'precision' else 1)
        req = profile.request({'schema_version': 'xgap-one-shot-evaluation-request-v1',
            'question_id': 'independent-new-wire', 'question': 'Find transfers from Alice.',
            'population': 'development', 'exposure': 'fixture'}, mode)
        payload = reconstructed.build_request_payload(req)
        assert reconstructed.token_guard.check(payload, call_kind='generation')['passed']
        assert json.loads(payload['messages'][1]['content'])['candidate_cap'] == policy.candidate_cap
        assert 'program' not in payload['response_format']['json_schema']['schema']['properties']


@pytest.mark.parametrize('index', [0, 1, 2], ids=['direct', 'path', 'dedup'])
def test_lowered_financial_domain_uses_existing_frozen_estimator_without_execution(profile, index, monkeypatch):
    from xgap.planning import runtime_work_estimator
    monkeypatch.setattr(runtime_work_estimator, 'fit_work_estimator', lambda *a, **kw: pytest.fail('online fit'))
    raw, estimator, bundle, sources, backends, _, modes = profile.materialize()
    program, assignments = lower_compact_query(financial_intents()[index], raw['source_schema'])
    policy = modes['performance'][0]
    bound, _ = ground_interpretation(program, assignments, bundle, 'Alice and account 1',
        max_candidates_per_hole=policy.max_candidates_per_hole, use_ontology=policy.use_ontology)
    candidates, domain = prepare_one_shot_domain(bound.program,
        operator_sources=bound.operator_sources, sources=sources, backends=backends, policy=policy)
    predictions = [estimator.predict(c.plan) for c in candidates]
    assert predictions and all(p.status == 'estimated' for p in predictions), [p.to_dict() for p in predictions]
    assert domain['candidate_count'] <= domain['construction_bound']
    assert all(not b['authoritative'] for b in bound.bindings.values())
