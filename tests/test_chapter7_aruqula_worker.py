"""Protocol wrapper fidelity without running a model or replacing author logic."""
import hashlib
import json
from types import SimpleNamespace
from urllib.parse import parse_qs

import run_chapter7_aruqula_worker as worker


def arguments(tmp_path, question):
    source = tmp_path / 'author'
    source.mkdir()
    (source / 'llm_config.yaml').write_text(json.dumps(dict(prompt_dirs=['prompts'],
        prompt_logging={'log_file': 'prompt_logs.jsonl'}, litellm_set_verbose=False,
        llm_endpoints=[])))
    request = tmp_path / 'request.json'
    request.write_text(json.dumps(question))
    return SimpleNamespace(output=str(tmp_path / 'result'), author_source=str(source),
        request_path=str(request), request_sha256=hashlib.sha256(request.read_bytes()).hexdigest(),
        model_endpoint='http://127.0.0.1:1234/v1', model_id='test-model',
        federation_endpoint='http://127.0.0.1:1235/sparql', lookup_endpoint='http://127.0.0.1:1236/api/search',
        query_seconds=20, response_bytes=1024)


def test_wrapper_keeps_original_api_options_and_submits_its_query_unchanged(tmp_path, monkeypatch):
    args = arguments(tmp_path, dict(question_id='q', question='Public question'))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('XGAP_EXTERNAL_LLM_API_KEY', 'test-credential-not-real')
    monkeypatch.setattr(worker.subprocess, 'check_output',
        lambda command, **kw: worker.AUTHOR_COMMIT if 'rev-parse' in command else b'')
    monkeypatch.setenv('OPENAI_API_KEY','previous-value')
    monkeypatch.setenv('NO_PROXY','existing.example')
    monkeypatch.setenv('no_proxy','existing.example')
    args.method_id='aruqula-fedx'
    seen = {}
    query = 'SELECT ?x WHERE { ?x <https://p> "literal" }'

    class Parser:
        @classmethod
        def initialize(cls, **kwargs):
            seen['initialize'] = kwargs
            assert worker.os.environ['OPENAI_API_KEY']=='test-credential-not-real'
            assert worker.os.environ['OPENAI_BASE_URL']==args.model_endpoint
            from urllib.request import proxy_bypass_environment
            assert proxy_bypass_environment('127.0.0.1')
            assert proxy_bypass_environment('existing.example')

        @classmethod
        def run_batch(cls, questions, **kwargs):
            seen['questions'], seen['batch'] = questions, kwargs
            return [dict(question=questions[0]['question'])]

    async def post_process(dataset, results, **kwargs):
        seen['postprocessing'] = kwargs
        results[0]['predicted_sparql'] = query
        return results

    def endpoint(request, timeout):
        seen['query'] = parse_qs(request.data.decode())['query'][0]
        seen['endpoint'] = request.full_url
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, maximum):
                return b'{"head":{"vars":["x"]},"results":{"bindings":[]}}'
        return Response()

    author_parser = SimpleNamespace(PartToWholeParser=Parser)
    modules = {'yaml': SimpleNamespace(safe_load=json.loads),
        'chainlite': SimpleNamespace(write_prompt_logs_to_file=lambda: None),
        'spinach_agent': SimpleNamespace(part_to_whole_parser=author_parser),
        'spinach_agent.part_to_whole_parser': author_parser,
        'spinach_agent.evaluate_parser': SimpleNamespace(post_processing=post_process),
        'spinach_agent.parser_state': SimpleNamespace(state_to_string=json.dumps)}
    for name, value in modules.items():
        monkeypatch.setitem(worker.sys.modules, name, value)
    monkeypatch.setattr(worker, 'urlopen', endpoint)
    assert worker.run(args) == 0
    assert worker.os.environ['OPENAI_API_KEY']=='previous-value'
    assert worker.os.environ['NO_PROXY']==worker.os.environ['no_proxy']=='existing.example'
    assert seen['questions'] == [dict(question='Public question', questionId='q', conversation_history=[])]
    assert seen['postprocessing'] == dict(regex_use_select_distinct_and_id_not_label=True,
                                          llm_extract_prediction_if_null=True)
    assert seen['query'] == query and seen['endpoint'] == args.federation_endpoint
    config = (tmp_path / 'result/llm_config.yaml').read_text()
    assert 'test-credential-not-real' not in config
    receipt = json.loads((tmp_path / 'result/receipt.json').read_text())
    assert receipt['success'] and receipt['final_query_submissions'] == 1
    assert receipt['method']=='aruqula-fedx' and receipt['loopback_proxy_bypass']
    assert receipt['model_calls'] is None  # Only the parent observer can report this.


def test_private_fields_are_rejected_before_author_import_or_network(tmp_path, monkeypatch):
    args = arguments(tmp_path, dict(question_id='q', question='Public', gold_sparql='secret'))
    monkeypatch.setattr(worker.subprocess, 'check_output',
        lambda command, **kw: worker.AUTHOR_COMMIT if 'rev-parse' in command else b'')
    def forbidden(*args, **kwargs):
        raise AssertionError('No network request is permitted for invalid input')
    monkeypatch.setattr(worker, 'urlopen', forbidden)
    assert worker.run(args) == 1
    receipt = json.loads((tmp_path / 'result/receipt.json').read_text())
    assert receipt['status'] == 'setup_error' and receipt['final_query_submissions'] == 0


def test_https_overlay_only_extends_existing_absolute_iri_serialization(tmp_path):
    source=tmp_path/'author';source.mkdir()
    original=('def get_property_examples(pid):\n'+worker.HTTPS_PROPERTY_FIX[0]+
              '\n    elif not pid.startswith("dbo:"):\n        pid = "dbo:" + pid\n    return pid\n')
    (source/'kg_utils.py').write_text(original)
    output=tmp_path/'output';output.mkdir()
    overlay,receipt=worker.https_property_overlay(source,output)
    assert (source/'kg_utils.py').read_text()==original
    patched=(overlay/'kg_utils.py').read_text()
    assert patched.replace(worker.HTTPS_PROPERTY_FIX[1],worker.HTTPS_PROPERTY_FIX[0])==original
    before,after={},{}
    exec(original,before);exec(patched,after)
    for term in ('http://example.org/p','dbo:p','p'):
        assert before['get_property_examples'](term)==after['get_property_examples'](term)
    iri='https://example.org/p'
    assert before['get_property_examples'](iri)=='dbo:'+iri
    assert after['get_property_examples'](iri)=='<'+iri+'>'
    assert receipt['replacements']==1 and receipt['algorithm_changes']==receipt['output_repairs']==0


def test_action_key_alias_preserves_text_and_action_without_guessing_missing_values():
    raw={'>':'Observed text unchanged\n', 'action_name':'execute_sparql',
         'action_argument':'SELECT ?x WHERE { ?x <https://p> ?y }'}
    original=dict(raw);decoded=worker.action_envelope_alias(raw)
    assert raw==original and decoded==dict(thought=raw['>'],action_name=raw['action_name'],
                                          action_argument=raw['action_argument'])
    for value in ({'action_name':'stop','action_argument':''},
                  {'>':'text','action_name':'stop'},
                  {'>':None,'action_name':'stop','action_argument':''},
                  {'thought':'author value','>':'other','action_name':'stop','action_argument':''},
                  {**raw,'unexpected':'field'}):
        assert worker.action_envelope_alias(value) is value


def test_sole_reasoning_field_contract_does_not_fill_missing_actions_or_conflicts():
    for key in ('>', ', ', 'unexpected_reasoning_key'):
        value={key:'Original trace text', 'action_name':'stop','action_argument':''}
        assert worker.action_envelope_alias(value,sole_reasoning_key=True)==dict(
            thought='Original trace text',action_name='stop',action_argument='')
    for value in ({'thought':'original','>':'other','action_name':'stop'},
                  {'a':'text','b':'text','action_name':'stop'},
                  {'>':'text','action_name':'stop'},
                  {'>':'text','action_name':'stop','action_argument':None},
                  {'>':'text','other':'text','action_name':'stop','action_argument':''}):
        assert worker.action_envelope_alias(value,sole_reasoning_key=True) is value


def test_shared_template_mode_preserves_original_prompts_sampling_and_format():
    import pytest
    original=dict(messages=[{'role':'system','content':'Original author prompt'}],
        temperature=1.,top_p=.9,max_tokens=700,response_format={'type':'json_object'})
    configured=worker.nonthinking_parameters(original)
    assert {k:v for k,v in configured.items() if k!='extra_body'}==original
    assert configured['extra_body']=={'chat_template_kwargs':{'enable_thinking':False}}
    assert 'extra_body' not in original
    with pytest.raises(ValueError,match='Conflicting'):
        worker.nonthinking_parameters(dict(extra_body={'chat_template_kwargs':{'enable_thinking':True}}))


def test_action_schema_applies_only_to_exact_formatter_instruction():
    message={'role':'system','content':'Original format instruction'}
    original=dict(messages=[message,{'role':'user','content':'Unchanged controller action'}],
                  response_format={'type':'json_object'},temperature=0,top_p=.9,max_tokens=700)
    configured=worker.nonthinking_parameters(original,message['content'])
    assert configured['messages']==original['messages']
    assert configured['response_format']['json_schema']['schema']==worker.ACTION_SCHEMA
    assert set(worker.ACTION_SCHEMA['properties'])=={'thought','action_name','action_argument'}
    assert all(v=={'type':'string'} for v in worker.ACTION_SCHEMA['properties'].values())
    for key in ('temperature','top_p','max_tokens'):assert configured[key]==original[key]
    controller=dict(original,messages=[{'role':'system','content':'Controller instruction'}])
    assert worker.nonthinking_parameters(controller,message['content'])['response_format']=={'type':'json_object'}


def test_coalesce_overlay_changes_only_pinned_active_tool_expression(tmp_path):
    source=tmp_path/'source';source.mkdir();output=tmp_path/'output';output.mkdir()
    original=worker.HTTPS_PROPERTY_FIX[0]+'\n'+worker.HTTPS_ENTITY_FIX[0]+worker.EMPTY_COALESCE_FIX[0]
    original+='\n#         BIND(if(?p = rdf:type, "is a", COALESCE()) AS ?pLabel)'
    (source/'kg_utils.py').write_text(original)
    target,receipt=worker.https_property_overlay(source,output,include_entity=True,empty_coalesce=True)
    patched=(target/'kg_utils.py').read_text()
    for before,after in (worker.HTTPS_PROPERTY_FIX,worker.HTTPS_ENTITY_FIX,worker.EMPTY_COALESCE_FIX):
        patched=patched.replace(after,before)
    assert patched==original==(source/'kg_utils.py').read_text()
    assert receipt['replacements']==3 and receipt['empty_coalesce_compatibility']
