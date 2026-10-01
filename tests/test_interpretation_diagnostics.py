"""Keep original NL failure evidence without repairing a query or issuing calls."""
from copy import deepcopy

from xgap.experiments.interpretation_diagnostics import summarize_interpretation, batch_cell_summary
from xgap.experiments.compact_profile import load_compact_graph_provider
from xgap.semantic.compact_query import SCHEMA_V2
from xgap.semantic.interpretation import InterpretationRequest
from xgap.semantic.interpretation_candidates import interpret_candidate_question


def test_actual_lowering_rejection_survives_generic_null_program_admission(monkeypatch):
    import json
    schema = {'identity_property': 'xgap_id', 'graph': {
        'nodes': {'Person': {'properties': ['id', 'age']}}, 'edges': []}}
    query = {'nodes': [{'var': 'p', 'type': 'Person', 'entity': None}],
        'edges': [], 'path': None, 'where': [],
        'select': {'id': {'var': 'p', 'property': 'unregistered_property'}},
        'contribution_by': None, 'order_by': [], 'limit': None}
    raw = {'schema_version': SCHEMA_V2, 'candidates': [{
        'candidate_id': 'candidate', 'quality_proxy': None, 'query': query}]}
    class Transport:
        calls = 0
        def post_json(self, **kwargs):
            self.calls += 1
            return {'model': kwargs['payload']['model'], 'choices': [
                {'finish_reason': 'stop', 'message': {'content': json.dumps(raw)}}],
                'usage': {'prompt_tokens': 13, 'completion_tokens': 7, 'total_tokens': 20}}
    monkeypatch.setenv('XGAP_EXTERNAL_LLM_API_KEY', 'fixture-never-sent')
    provider = load_compact_graph_provider(language_version='v2', prompt_version='v2')
    provider.transport = transport = Transport()
    report = interpret_candidate_question(InterpretationRequest('Return each person id.',
        {'source_schema': schema}), provider, candidate_cap=1)
    assert report['status'] == 'no_admissible_interpretation'
    before = deepcopy(report)
    diagnostics = summarize_interpretation({'interpretation': report})
    detail = diagnostics['candidates'][0]
    assert detail['failure_stage'] == 'compact_lowering'
    assert detail['error'] == 'No declared source for node property unregistered_property'
    assert detail['error'] != report['candidates'][0]['error']
    assert diagnostics['admitted_count'] == 0
    assert report == before and transport.calls == 1
    assert report['external_calls'] == 1 and report['input_tokens'] == 13
    assert report['output_tokens'] == 7 and diagnostics['token_usage_complete'] is True
    assert 'fixture-never-sent' not in json.dumps(diagnostics)
    assert 'raw_compact_response' not in diagnostics


def test_duplicate_ids_use_indices_and_scope_failure_remains_distinct():
    report = {'status': 'interpreted', 'admitted_count': 1, 'candidates': [
        {'candidate_index': 0, 'candidate_id': 'same', 'status': 'invalid', 'error': 'invalid program'},
        {'candidate_index': 1, 'candidate_id': 'same', 'status': 'invalid', 'error': 'Duplicate candidate ID'},
        {'candidate_index': 2, 'candidate_id': 'other', 'status': 'admitted'}],
        'provenance': {'compact_lowering': {'candidates': [
            {'candidate_index': 0, 'status': 'invalid', 'error': 'Unknown node type'},
            {'candidate_index': 1, 'status': 'lowered'},
            {'candidate_index': 2, 'status': 'lowered'}]}}}
    core = {'interpretation': report, 'status': 'intent_outside_proposed_scope',
        'scope_confirmation': {'status': 'success', 'value': {'covered': False,
            'private_query': 'never copy this'}}}
    result = summarize_interpretation(core)
    assert [c['failure_stage'] for c in result['candidates']] == [
        'compact_lowering', 'structural_admission', None]
    assert result['scope_covered'] is False and result['scope_confirmation_status'] == 'success'
    assert 'private_query' not in str(result)
    assert summarize_interpretation({'status': 'controlled'}) is None


def test_long_error_and_candidate_count_are_bounded_without_changing_original():
    report = {'candidates': [{'candidate_index': i, 'status': 'invalid', 'error': 'a' * 3000}
                             for i in range(10)]}
    result = summarize_interpretation({'interpretation': report})
    assert result['candidate_count'] == 10 and result['candidates_truncated']
    assert len(result['candidates']) == 8
    assert all(len(c['error']) == 2048 and c['error_truncated'] for c in result['candidates'])
    assert len(report['candidates'][0]['error']) == 3000


def test_batch_log_exposes_actual_rejection_and_budget_without_raw_payloads():
    import json
    outcome = dict(status='proposal_failed', proposal_failure_category='no_admissible_interpretation',
        model_calls=1, final_plan_executions=0, interpretation_diagnostics=dict(
            admitted_count=0, scope_covered=None, candidates=[dict(candidate_index=0,
                failure_stage='compact_lowering', error='Unknown node type: RELATION')]),
        raw_query='private-payload-must-not-appear', private_query='also-not-a-log-field')
    before = deepcopy(outcome)
    summary = batch_cell_summary('cell', outcome, 0.0)
    assert summary['interpretation']['candidate_failures'][0]['error'] == 'Unknown node type: RELATION'
    assert summary['final_plan_executions'] == 0 and outcome == before
    assert 'private' not in json.dumps(summary)
    outcome = dict(status='harness_budget_censored', failure_scope='study_budget_censoring_not_method_incorrectness',
        observations={'source': dict(requests=276, forwarded_requests=256,
            failure_categories={'harness_call_budget': 20}, request_body='not-copied')},
        harness_failures={'source': {'harness_call_budget': 20}})
    summary = batch_cell_summary('ts', outcome, None)
    assert summary['answer_em'] is None and summary['source_forwarded'] == 256
    assert summary['observation_failures'] == {'source': {'harness_call_budget': 20}}
    assert 'not-copied' not in json.dumps(summary)


def test_batch_scope_rejection_stays_separate_from_planning_or_model_failure():
    outcome = dict(status='intent_outside_proposed_scope', model_calls=1, final_plan_executions=0,
        interpretation_diagnostics=dict(admitted_count=1, scope_confirmation_status='success', scope_covered=False,
            candidates=[dict(candidate_index=0, status='admitted', failure_stage=None)]))
    summary = batch_cell_summary('scope', outcome, 0.0)
    assert summary['interpretation'] == dict(admitted_count=1, scope_confirmation_status='success', scope_covered=False)
    assert 'candidate_failures' not in summary['interpretation']
