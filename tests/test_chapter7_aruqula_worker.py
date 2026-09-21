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
    seen = {}
    query = 'SELECT ?x WHERE { ?x <https://p> "literal" }'

    class Parser:
        @classmethod
        def initialize(cls, **kwargs):
            seen['initialize'] = kwargs

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

    modules = {'yaml': SimpleNamespace(safe_load=json.loads),
        'chainlite': SimpleNamespace(write_prompt_logs_to_file=lambda: None),
        'spinach_agent': SimpleNamespace(),
        'spinach_agent.part_to_whole_parser': SimpleNamespace(PartToWholeParser=Parser),
        'spinach_agent.evaluate_parser': SimpleNamespace(post_processing=post_process),
        'spinach_agent.parser_state': SimpleNamespace(state_to_string=json.dumps)}
    for name, value in modules.items():
        monkeypatch.setitem(worker.sys.modules, name, value)
    monkeypatch.setattr(worker, 'urlopen', endpoint)
    assert worker.run(args) == 0
    assert seen['questions'] == [dict(question='Public question', questionId='q', conversation_history=[])]
    assert seen['postprocessing'] == dict(regex_use_select_distinct_and_id_not_label=True,
                                          llm_extract_prediction_if_null=True)
    assert seen['query'] == query and seen['endpoint'] == args.federation_endpoint
    config = (tmp_path / 'result/llm_config.yaml').read_text()
    assert 'test-credential-not-real' not in config
    receipt = json.loads((tmp_path / 'result/receipt.json').read_text())
    assert receipt['success'] and receipt['final_query_submissions'] == 1
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
