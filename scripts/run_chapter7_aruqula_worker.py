#!/usr/bin/env python3
"""Unmodified author text-to-SPARQL API, followed by one final endpoint request.

Run in the author's isolated Python environment under the common process guard.
The parent owns Redis, lookup, source/model observers and FedUP; this worker must
never receive a private intent, reference answer or gold SPARQL. Its only input is
a pinned public question. Observer records are the authoritative call accounting.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

AUTHOR_COMMIT = '9a3982baca03d62f7250572e300b1e4ba47727cc'
DATASET_ID = 'https://text2sparql.aksw.org/2025/corporate/'


def pinned_json(path, expected):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('Pinned input changed')
    return json.loads(raw)


def write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
        stream.write('\n')


def local_endpoint(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('Use a loopback observer endpoint without credentials')
    return value


def run(args):
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    receipt = dict(schema_version='xgap-ch7-aruqula-worker-v1', success=False,
        status='setup_error', method='aruqula-fedup', author_commit=AUTHOR_COMMIT,
        request_sha256=args.request_sha256, model_calls=None, input_tokens=None,
        output_tokens=None, backend_calls=None, final_query_submissions=0,
        parent_observers_required=True, gold_reads=0, wrapper_retries=0,
        author_algorithm_changes=0, answer=None)
    prompt_writer = None
    try:
        source = Path(args.author_source).resolve()
        current = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
        dirty = subprocess.check_output(['git', 'diff', 'HEAD', '--'], cwd=source)
        if current != AUTHOR_COMMIT or dirty:
            raise ValueError('Author tracked source must remain at its frozen commit')
        question = pinned_json(args.request_path, args.request_sha256)
        if set(question) != {'question_id', 'question'} or not all(
                isinstance(value, str) and value for value in question.values()):
            raise ValueError('Only a question ID and natural-language question are admitted')
        receipt['question_id'] = question['question_id']
        model = local_endpoint(args.model_endpoint)
        endpoint = local_endpoint(args.federation_endpoint)
        lookup = local_endpoint(args.lookup_endpoint)
        if not os.environ.get('XGAP_EXTERNAL_LLM_API_KEY'):
            raise ValueError('Model credential missing from process environment')
        # The same primary and auxiliary model mapping is configured before any
        # author imports. Original prompt contents and decoding remain unchanged.
        import yaml
        original_config = source / 'llm_config.yaml'
        config = yaml.safe_load(original_config.read_text())
        config['prompt_dirs'] = [str((source / p).resolve()) for p in config['prompt_dirs']]
        config['prompt_logging']['log_file'] = str(root / 'prompt_logs.jsonl')
        config['llm_endpoints'] = [dict(api_base=model, api_key='XGAP_EXTERNAL_LLM_API_KEY',
            engine_map={'xgap-qwen': 'openai/' + args.model_id,
                        'gpt-4o': 'openai/' + args.model_id})]
        # JSON is valid YAML. The value contains an environment variable name,
        # never the credential, and records all author configuration fields.
        write(root / 'llm_config.yaml', config)
        receipt.update(original_model_config_sha256=hashlib.sha256(original_config.read_bytes()).hexdigest(),
            configured_model=args.model_id, author_dataset_alias=DATASET_ID,
            dataset_alias_is_interface_configuration=True,
            postprocessing=dict(regex_use_select_distinct_and_id_not_label=True,
                                llm_extract_prediction_if_null=True))
        write(root / 'intent.json', receipt)
        os.environ['ORG_SPARQL_SERVICE_URL'] = endpoint
        os.environ['ORG_LOOKUP_SERVICE_URL'] = lookup
        os.chdir(root)
        sys.path.insert(0, str(source))
        from chainlite import write_prompt_logs_to_file
        prompt_writer = write_prompt_logs_to_file
        from spinach_agent.part_to_whole_parser import PartToWholeParser
        from spinach_agent.evaluate_parser import post_processing
        from spinach_agent.parser_state import state_to_string
        receipt['status'] = 'running'
        PartToWholeParser.initialize(engine='xgap-qwen', dataset_id=DATASET_ID)
        # Same public path as deploy/app/app.py:t2s, including both original
        # postprocessing options. Do not call evaluate_parser's gold-reading CLI.
        results = asyncio.run(post_processing(DATASET_ID,
            PartToWholeParser.run_batch([dict(question=question['question'],
                questionId=question['question_id'], conversation_history=[])], batch_size=1),
            regex_use_select_distinct_and_id_not_label=True,
            llm_extract_prediction_if_null=True))
        write(root / 'author-output.json', [json.loads(state_to_string(value)) for value in results])
        query = results[0].get('predicted_sparql')
        if not isinstance(query, str) or not query.strip():
            receipt['status'] = 'non_answer'
        else:
            (root / 'predicted.sparql').write_text(query)
            write(root / 'final-query-intent.json', dict(query=query, endpoint=endpoint))
            receipt['final_query_submissions'] = 1
            # No normalization/repair here: submit exactly what the original
            # post_processing function selected. Keep JSON bindings and bag order.
            request = Request(endpoint, data=urlencode({'query': query}).encode(),
                headers={'Accept': 'application/sparql-results+json',
                         'Content-Type': 'application/x-www-form-urlencoded'})
            with urlopen(request, timeout=args.query_seconds) as response:
                body = response.read(args.response_bytes + 1)
                receipt['final_http_status'] = response.status
            if len(body) > args.response_bytes:
                raise ValueError('Final result exceeded the declared response limit')
            raw = json.loads(body)
            if not isinstance(raw, dict) or not ('results' in raw or 'boolean' in raw):
                raise ValueError('Final response is not SPARQL result JSON')
            (root / 'answer.json').write_bytes(body)
            receipt.update(success=True, status='answered', answer=dict(
                path=str(root / 'answer.json'), sha256=hashlib.sha256(body).hexdigest()))
    except Exception as error:
        # Some third-party exceptions embed request headers. Avoid serializing
        # the exception object or traceback into the public evidence package.
        receipt.update(status='setup_error' if receipt['status']=='setup_error' else 'method_error',
                       error_type=type(error).__name__)
    finally:
        if prompt_writer:
            try:
                prompt_writer()
            except Exception as error:
                receipt['prompt_log_error_type'] = type(error).__name__
        receipt['worker_ms'] = (time.perf_counter() - started) * 1000
        write(root / 'receipt.json', receipt)
    print(json.dumps(dict(success=receipt['success'], status=receipt['status'],
                          receipt=str(root / 'receipt.json'))))
    return 0 if receipt['success'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('author-source', 'request-path', 'request-sha256', 'model-endpoint',
                 'model-id', 'federation-endpoint', 'lookup-endpoint', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--query-seconds', type=int, default=20)
    parser.add_argument('--response-bytes', type=int, default=64 * 1024**2)
    raise SystemExit(run(parser.parse_args()))
