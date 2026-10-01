"""Question orchestration includes the actual guarded provider and RDF engine."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from xgap.backends.rdf_terms import RdfTerm
from xgap.experiments.bundles import ModelBundle
from xgap.experiments.freebase_candidate_compiler import ExecutionRequirements, FreebaseExecutionMapping, NS
from xgap.experiments.freebase_candidate_execution import execute_candidate, prepare_candidate_batch
from xgap.experiments.freebase_question import QuestionBudget, answer_question, run_grounded_question
from xgap.experiments.grailqa_candidate_feedback import TYPED_GROUNDING_ONCE
from xgap.experiments.grailqa_candidate_grounding import SEMANTIC_GROUNDING_POLICY
from xgap.experiments.grailqa_guarded_provider import GuardedSemanticPilotProvider, QueryEventJournal
from xgap.experiments.grailqa_semantic_pilot import GenerationResult
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.experiments.live_run import build_openai_compatible_provider
from xgap.llm.token_budget import ChatTokenBudgetGuard

ROOT = Path(__file__).resolve().parents[1]
CASE = runpy.run_path(str(ROOT/'examples/grounded_candidate_execution_demo.py'))['controlled_recording_case']
NATIVE = runpy.run_path(str(ROOT/'tests/test_freebase_candidate_execution.py'))
MAPPING = FreebaseExecutionMapping('question-fixture', 'a'*64, {'music.release_track.track_number':'string'})


def inputs():
    return CASE('m.recording', filter_value=None)


def wire(raw):
    raw = deepcopy(raw)
    for candidate in raw['candidates']:
        candidate.update(confidence=1.0, rationale=None)
        def annotate(value):
            if isinstance(value, dict):
                if 'label' in value and 'properties' in value:
                    value['label_slot'] = None
                for child in tuple(value.values()): annotate(child)
        annotate(candidate['pattern_query'])
        for binding in candidate.pop('grounding')['slot_realizations']:
            component = candidate['pattern_query']
            for part in binding['component_ref'].split('.'): component = component[part]
            component['label_slot'] = binding['slot_id']
    return raw


@pytest.fixture
def engines():
    rdf = pytest.importorskip('rdflib')
    graph = rdf.Graph().parse(data=f'''@prefix f: <{NS}> .
        f:m.track f:music.release_track.recording f:m.recording ;
                  f:music.release_track.release f:m.release .''', format='turtle')
    return NATIVE['Paths']([('m.recording','m.track','m.release')]), NATIVE['RdfEngine'](graph)


def provider_for(tmp_path, monkeypatch, raws, *, tokens=100):
    model = ModelBundle.load(ROOT/'models/qwen3_32b_vllm_cwru_grailqa_inline_v1')
    monkeypatch.setenv(model.config.api_key_env, 'synthetic-question-test-key')
    monkeypatch.delenv(model.config.model_env, raising=False)
    monkeypatch.delenv(model.config.base_url_env, raising=False)
    journal = QueryEventJournal(tmp_path/'events.jsonl')
    calls = []
    def send(**kwargs):
        calls.append(deepcopy(kwargs['payload']))
        raw = raws.pop(0)
        if isinstance(raw, Exception): raise raw
        return {'id':'synthetic-response','choices':[{'message':{'content':json.dumps(raw)}}],
                'usage':{'prompt_tokens':100,'completion_tokens':80,'total_tokens':180}}
    base = build_openai_compatible_provider(model, SimpleNamespace(post_json=send),
                                           response_parser=parse_normalized_planner_response)
    counter = SimpleNamespace(identity={'synthetic':True},count_payload_tokens=lambda payload: tokens)
    guard = ChatTokenBudgetGuard(counter, input_limit=8192, output_limit=4096,
                                context_limit=12288, expected_model=model.config.exact_model_snapshot)
    provider = GuardedSemanticPilotProvider(model, guard, journal, 'controlled-recording', base_provider=base,
        candidate_repair_policy=TYPED_GROUNDING_ONCE, grounding_policy=SEMANTIC_GROUNDING_POLICY)
    return provider, calls, journal


def run(provider, engines, *, request=None, view=None, requirements=None, **kwargs):
    _, req, context = inputs()
    return run_grounded_question(request=request or req, view=view or context, mapping=MAPPING,
        requirements=requirements or ExecutionRequirements(True), provider=provider,
        neo4j=engines[0], fuseki=engines[1], **kwargs)


def recorded(raw):
    return SimpleNamespace(generate=Mock(return_value=GenerationResult(raw, (),
        {'generation_calls':1,'repair_calls':0}, 0.1, 0, True)))


def test_actual_inline_provider_to_answer_without_baseline(tmp_path, monkeypatch, engines):
    raw, _, _ = inputs()
    provider, calls, journal = provider_for(tmp_path, monkeypatch, [wire(raw)])
    with journal:
        result = run(provider, engines)
    assert result['status'] == 'answered', result
    assert result['answers'] == [RdfTerm('uri', NS+'m.release').to_binding()]
    assert result['model_calls'] == 1 and result['backend_calls'] == 1
    assert engines[1].calls == []
    assert result['execution']['verification_status'] == 'not_run'
    assert result['generation']['structured_response'] != result['generation']['response_record']['structured_response']
    assert 'execution_goal_v1' in json.dumps(calls[0])
    assert not result['question_correctness_verified'] and not result['global_completeness_verified']


def test_explicit_baseline_has_separate_cost_and_preserves_answer(engines):
    raw, _, _ = inputs()
    result = run(recorded(raw), engines, verify_baseline=True)
    assert result['success'] and result['backend_calls'] == 2
    assert result['execution']['verification_status'] == 'matched'
    assert result['execution']['baseline_remote_calls'] == 1
    assert result['execution']['baseline_wall_seconds'] > 0


def test_actual_provider_repair_then_execute_once(tmp_path, monkeypatch, engines):
    raw, _, _ = inputs()
    good = wire(raw)
    bad = deepcopy(good)
    bad['candidates'][0]['pattern_query']['expr']['left']['edge']['label_slot'] = 'unknown-slot'
    provider, calls, journal = provider_for(tmp_path, monkeypatch, [bad, good])
    with journal: result = run(provider, engines)
    assert result['success'], result
    assert result['model_calls'] == 2 and len(calls) == 2 and len(engines[0].calls) == 1


def test_token_refusal_has_zero_external_calls(tmp_path, monkeypatch, engines):
    provider, calls, journal = provider_for(tmp_path, monkeypatch, [], tokens=100000)
    with journal: result = run(provider, engines)
    assert result['status'] == 'generation_failed' and result['model_calls'] == 0
    assert calls == engines[0].calls == engines[1].calls == []


def test_ambiguous_identity_stops_before_model_and_can_take_confirmed_binding(engines):
    raw, request, view = inputs()
    view = replace(view, entities=(*view.entities, {'entity_id':'m.other'}))
    request = replace(request, metadata={**request.metadata,'prompt_schema_view':view.to_dict()})
    provider = recorded(raw)
    result = run(provider, engines, request=request, view=view)
    assert result['status'] == 'clarification_required' and result['model_calls'] == 0
    provider.generate.assert_not_called()
    result = run(provider, engines, request=request, view=view,
                 requirements=ExecutionRequirements(True, required_bindings=((1,'m.recording'),)))
    assert result['success'], result


@pytest.mark.parametrize('variant', ['distinct','unsupported','same'])
def test_candidate_choice_never_uses_backend_support_or_cost_as_meaning(engines, variant):
    raw, _, _ = inputs()
    second = deepcopy(raw['candidates'][0]); second['candidate_id'] = 'second'
    if variant == 'distinct': second['pattern_query']['restrictor'] = 'WALK'
    if variant == 'unsupported': second['pattern_query']['restrictor'] = 'TRAIL'
    raw['candidates'].append(second)
    result = run(recorded(raw), engines)
    if variant == 'same':
        assert result['success'], result
        assert len(engines[0].calls) == 1
        assert len(result['selection']['equivalent_candidate_ids']) == 2
    else:
        assert result['status'] in {'clarification_required','interpretation_unresolved'}, result
        assert engines[0].calls == engines[1].calls == []


def test_missing_actual_anchor_does_not_dispatch(engines):
    raw, _, _ = inputs()
    raw['candidates'][0]['pattern_query']['source']['properties'] = {}
    result = run(recorded(raw), engines)
    assert result['status'] == 'no_executable_candidate'
    assert engines[0].calls == []


def test_backend_failure_is_not_an_empty_answer(engines):
    raw, _, _ = inputs(); engines[0].fail = True
    result = run(recorded(raw), engines)
    assert result['status'] == 'execution_failed' and 'answers' not in result
    assert result['backend_calls'] == 1 and engines[1].calls == []


def test_successful_empty_is_an_answer_on_snapshot(engines):
    raw, _, _ = inputs(); engines[0].paths = []
    result = run(recorded(raw), engines)
    assert result['success'] and result['answers'] == [] and result['answer_count'] == 0


def test_verification_mismatch_keeps_actual_answers(engines):
    raw, _, _ = inputs(); engines[1].graph.remove((None,None,None))
    result = run(recorded(raw), engines, verify_baseline=True)
    assert result['status'] == 'verification_failed'
    assert result['answers'] and result['execution']['execution_success']
    assert result['execution']['verification_status'] == 'mismatch'


def test_budget_checked_before_backend(engines):
    raw, _, _ = inputs()
    result = run(recorded(raw), engines, verify_baseline=True, budget=QuestionBudget(max_backend_calls=1))
    assert result['status'] == 'budget_exhausted' and engines[0].calls == []


def test_input_context_drift_prevents_model(engines):
    raw, request, _ = inputs(); provider = recorded(raw)
    result = run(provider, engines, request=replace(request,metadata={}))
    assert result['status'] == 'failed'
    provider.generate.assert_not_called()


def test_catalog_front_edge_uses_question_and_not_references(engines):
    raw, request, view = inputs()
    retrieval = SimpleNamespace(to_dict=lambda: {'source':'controlled-catalog'})
    catalog = SimpleNamespace(retrieve=Mock(return_value=retrieval),prompt_view=Mock(return_value=view))
    result = answer_question(question_record={'question_id':view.task_id,'text':request.question},catalog=catalog,
        provider_factory=lambda qid:recorded(raw),mapping=MAPPING,requirements=ExecutionRequirements(True),
        neo4j=engines[0],fuseki=engines[1])
    assert result['success'], result
    catalog.retrieve.assert_called_once_with(view.task_id,request.question,top_k=20)
    assert result['retrieval_wall_seconds'] >= 0
    with pytest.raises(ValueError,match='Evaluation-only'):
        answer_question(question_record={'question_id':view.task_id,'text':request.question,'gold_answers':[]},catalog=catalog,
            provider_factory=lambda qid:recorded(raw),mapping=MAPPING,requirements=ExecutionRequirements(True),
            neo4j=engines[0],fuseki=engines[1])


def test_json_confirmed_bindings_are_immutable_and_enforced(engines):
    raw, _, _ = inputs()
    bindings = [[1,'m.recording']]
    goal = ExecutionRequirements(True, required_bindings=bindings)
    bindings[0][1] = 'm.changed'
    assert run(recorded(raw), engines, requirements=goal)['success']
    assert goal.required_bindings == ((1,'m.recording'),)
    with pytest.raises(ValueError, match='conflicting'):
        ExecutionRequirements(True, required_bindings=[[1,'m.recording'],[1,'m.other']])


def test_baseline_exception_keeps_executed_answer_and_attempt_count(engines):
    raw, _, _ = inputs()
    engines[1].execute = Mock(side_effect=OSError('synthetic transport failure'))
    result = run(recorded(raw), engines, verify_baseline=True)
    assert result['status'] == 'verification_failed' and result['answers']
    assert result['execution']['baseline_remote_calls'] == 1
    assert result['execution']['baseline_error_type'] == 'OSError'


def test_deadline_after_generation_prevents_backend(engines):
    raw, _, _ = inputs(); now = [0.0]
    def generate(*args):
        now[0] = 2.0
        return recorded(raw).generate(*args)
    result = run(SimpleNamespace(generate=generate), engines,
                 budget=QuestionBudget(deadline_seconds=1), clock=lambda:now[0])
    assert result['status'] == 'budget_exhausted' and result['model_calls'] == 1
    assert engines[0].calls == []


def test_retrieval_failure_is_not_an_empty_answer(engines):
    factory = Mock()
    result = answer_question(question_record={'question_id':'missing','text':'a question'},
        catalog=SimpleNamespace(retrieve=Mock(side_effect=ValueError())),provider_factory=factory,
        mapping=MAPPING, requirements=ExecutionRequirements(True),neo4j=engines[0],fuseki=engines[1])
    assert result['status'] == 'retrieval_failed' and 'answers' not in result
    factory.assert_not_called()


def test_provider_transport_error_is_not_retried(tmp_path, monkeypatch, engines):
    from xgap.llm.openai_compatible import ProviderTransportError, LiveFailureCategory
    provider, calls, journal = provider_for(tmp_path, monkeypatch,
        [ProviderTransportError(LiveFailureCategory.PROVIDER_ERROR,'synthetic unavailable')])
    with journal: result = run(provider, engines)
    assert result['status'] == 'generation_failed' and result['model_calls'] == len(calls) == 1
    assert engines[0].calls == []


def test_cli_connects_catalog_guarded_provider_and_answer_file(tmp_path, monkeypatch, engines):
    import xgap.experiments.freebase_question_cli as cli
    raw, request, view = inputs()
    provider, calls, journal = provider_for(tmp_path, monkeypatch, [wire(raw)])
    retrieval = SimpleNamespace(to_dict=lambda:{'source':'cli-fixture'})
    catalog = SimpleNamespace(retrieve=lambda *a,**kw:retrieval,prompt_view=lambda *a,**kw:view)
    monkeypatch.setattr(cli.GrailQAInferenceCatalogV2,'load',lambda path:catalog)
    monkeypatch.setattr(cli,'LocalPinnedChatTokenizer',lambda *a:SimpleNamespace(
        identity={'synthetic':True},count_payload_tokens=lambda p:100))
    monkeypatch.setattr(cli,'GuardedSemanticPilotProvider',lambda *a,**kw:provider)
    load_descriptor = cli.BackendDescriptor.from_yaml
    monkeypatch.setattr(cli.BackendDescriptor,'from_yaml',
        lambda path:path if str(path) in {'neo','rdf'} else load_descriptor(path))
    monkeypatch.setattr(cli,'Neo4jClient',lambda d:engines[0])
    monkeypatch.setattr(cli,'FusekiClient',lambda d:engines[1])
    data={'question':{'question_id':view.task_id,'text':request.question},
          'mapping':{'mapping_id':'cli-fixture','snapshot_sha256':'a'*64},
          'requirements':{'require_entity_anchor':True,'required_bindings':[[1,'m.recording']]}}
    path=tmp_path/'input.json'; path.write_text(json.dumps(data))
    out=tmp_path/'run'
    args=['--request',str(path),'--catalog','fixture','--model-bundle',
          str(ROOT/'models/qwen3_32b_vllm_cwru_grailqa_inline_v1'),'--tokenizer-snapshot','fixture',
          '--tokenizer-revision','a'*40,'--context-limit','12288','--neo4j-descriptor','neo',
          '--fuseki-descriptor','rdf','--output',str(out),'--execute']
    with journal:
        assert cli.main(args)==0
    result=json.loads((out/'result.json').read_text())
    assert result['answers']==[RdfTerm('uri',NS+'m.release').to_binding()]
    assert not result['serving_tokenizer_parity_verified']
    assert len(calls)==1 and len(engines[0].calls)==1 and engines[1].calls==[]
    with pytest.raises(FileExistsError): cli.main(args)
    assert len(calls)==1


def test_cli_requires_explicit_execution_switch(tmp_path):
    from xgap.experiments.freebase_question_cli import main
    args=['--request','fixture','--catalog','fixture','--model-bundle','fixture',
          '--tokenizer-snapshot','fixture','--tokenizer-revision','a'*40,'--context-limit','12288',
          '--neo4j-descriptor','neo','--fuseki-descriptor','rdf','--output',str(tmp_path/'run')]
    with pytest.raises(SystemExit) as error: main(args)
    assert error.value.code==2 and not (tmp_path/'run').exists()
