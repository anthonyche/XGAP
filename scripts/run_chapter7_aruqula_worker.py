#!/usr/bin/env python3
"""Author text-to-SPARQL API, followed by one final endpoint request.

Run in the author's isolated Python environment under the common process guard.
The parent owns Redis, lookup, source/model observers and FedUP; this worker must
never receive a private intent, reference answer or gold SPARQL. Its only input is
a pinned public question. Observer records are the authoritative call accounting.
Opt-in IRI and action-envelope compatibility are separately recorded; they do
not change author search, prompts, action names/arguments or final query selection.
"""
import argparse
import asyncio
import faulthandler
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
HTTPS_PROPERTY_FIX = ('    if pid.startswith("http:"):\n        pid = f"<{pid}>"',
                     '    if pid.startswith(("http:", "https:")):\n        pid = f"<{pid}>"')
HTTPS_ENTITY_FIX = ('    elif entity.startswith("http:"):\n        entity = f"<{entity}>"',
                   '    elif entity.startswith(("http:", "https:")):\n        entity = f"<{entity}>"')
EMPTY_COALESCE_FIX = ('\n        BIND(if(?p = rdf:type, "is a", COALESCE()) AS ?pLabel)',
                      '\n        BIND(if(?p = rdf:type, "is a", COALESCE(1/0)) AS ?pLabel)')
ENTITY_LABEL_FIX = ('''        BIND(if(?p = rdf:type, "is a", COALESCE()) AS ?pLabel)
        OPTIONAL {{?p rdfs:label ?pLabel FILTER(LANG(?pLabel) = "en") }}''',
    '''        OPTIONAL {{?p rdfs:label ?xgapCompatPLabel FILTER(LANG(?xgapCompatPLabel) = "en" && ?p != rdf:type) }}''')
ENTITY_LABEL_TAIL = ('        BIND(COALESCE(?vLabel_en, ?vLabel_) AS ?vLabel)',
    '''        BIND(COALESCE(?vLabel_en, ?vLabel_) AS ?vLabel)
        BIND(IF(?p = rdf:type, "is a", ?xgapCompatPLabel) AS ?pLabel)''')
COMPATIBILITIES = ('original','https-property-iris-v1','https-property-iris-qwen-key-v1',
                   'https-iris-qwen-key-v2','https-iris-qwen-envelope-v3','https-iris-nonthinking-v1',
                   'https-iris-action-schema-v1','https-iris-action-schema-fedx-v1')

ACTION_SCHEMA = {'type':'object','properties':{k:{'type':'string'}
    for k in ('thought','action_name','action_argument')},
    'required':['thought','action_name','action_argument'],'additionalProperties':False}


def nonthinking_parameters(kwargs, formatter_instruction=None):
    """Match the existing XGAP Qwen serving template, without tuning sampling."""
    result=dict(kwargs);extra=dict(result.get('extra_body') or {})
    template=dict(extra.get('chat_template_kwargs') or {})
    if 'enable_thinking' in template and template['enable_thinking'] is not False:
        raise ValueError('Conflicting model-template configuration')
    template['enable_thinking']=False;extra['chat_template_kwargs']=template;result['extra_body']=extra
    messages=result.get('messages') or []
    if (formatter_instruction and messages and messages[0].get('role')=='system'
            and messages[0].get('content')==formatter_instruction):
        if result.get('response_format')!={'type':'json_object'}:
            raise ValueError('Unexpected original formatter response format')
        result['response_format']={'type':'json_schema','json_schema':dict(
            name='aruqula_action_envelope',strict=True,schema=ACTION_SCHEMA)}
    return result


def install_nonthinking_transport(formatter_instruction=None):
    import litellm
    original_async,original_sync=litellm.acompletion,litellm.completion
    async def async_call(*args,**kwargs):return await original_async(*args,**nonthinking_parameters(kwargs,formatter_instruction))
    def sync_call(*args,**kwargs):return original_sync(*args,**nonthinking_parameters(kwargs,formatter_instruction))
    litellm.acompletion,litellm.completion=async_call,sync_call
    def restore():litellm.acompletion,litellm.completion=original_async,original_sync
    return restore


def action_envelope_alias(value, *, sole_reasoning_key=False):
    """Recognize one observed serializer key alias; never infer an action/value.

    Thought text is retained verbatim in the author's subsequent history. Any
    other missing/malformed field still reaches the original parser unchanged.
    """
    if isinstance(value,dict) and 'thought' not in value:
        extra=set(value)-{'action_name','action_argument'}
        if (len(value)==3 and len(extra)==1 and (sole_reasoning_key or extra=={'>'})
                and all(isinstance(v,str) for v in value.values())):
            return dict(thought=value[next(iter(extra))],action_name=value['action_name'],
                        action_argument=value['action_argument'])
    return value


def https_property_overlay(source, output, include_entity=False, empty_coalesce=False, entity_label=False):
    """One recorded URI-scheme compatibility fix; no query/output rewriting."""
    path = Path(source)/'kg_utils.py'
    raw = path.read_bytes()
    original, replacement = (s.encode() for s in HTTPS_PROPERTY_FIX)
    if raw.count(original)!=1:
        raise ValueError('Pinned HTTPS compatibility patch does not apply exactly once')
    updated = raw.replace(original,replacement)
    if include_entity:
        before,after=(s.encode() for s in HTTPS_ENTITY_FIX)
        if updated.count(before)!=1:
            raise ValueError('Pinned entity HTTPS patch does not apply exactly once')
        updated=updated.replace(before,after)
    if entity_label:
        if empty_coalesce or b'?xgapCompatPLabel' in raw:
            raise ValueError('Conflicting label compatibility patch')
        for before,after in (ENTITY_LABEL_FIX,ENTITY_LABEL_TAIL):
            before,after=before.encode(),after.encode()
            if updated.count(before)!=1:raise ValueError('Pinned entity-label template changed')
            updated=updated.replace(before,after)
    if empty_coalesce:
        before,after=(s.encode() for s in EMPTY_COALESCE_FIX)
        if updated.count(before)!=1:
            raise ValueError('Pinned empty-COALESCE compatibility patch does not apply exactly once')
        updated=updated.replace(before,after)
    target = Path(output)/'author-compatibility'
    target.mkdir()
    (target/'kg_utils.py').write_bytes(updated)
    return target,dict(kind=('https-iris-entity-label-v1' if entity_label else 'https-iris-empty-coalesce-v1' if empty_coalesce else
                            'https-iris-v2' if include_entity else 'https-property-iris-v1'),changed_module='kg_utils.py',
        changed_function='get_property_examples',original_sha256=hashlib.sha256(raw).hexdigest(),
        changed_functions=['get_property_examples']+(['get_outgoing_edges'] if include_entity else []),
        patched_sha256=hashlib.sha256(updated).hexdigest(),replacements=1+int(include_entity)+int(empty_coalesce)+2*int(entity_label),
        empty_coalesce_compatibility=empty_coalesce,
        entity_label_compatibility=entity_label,
        change=('Recognize absolute HTTPS IRIs; equivalent entity-label OPTIONAL before final projection binding'
                if entity_label else 'Recognize absolute HTTPS IRIs; empty COALESCE becomes COALESCE(1/0), an error in either case'
                if empty_coalesce else 'Recognize https: as an absolute IRI, like existing http: support'),
        original_author_checkout_unchanged=True,algorithm_changes=0,prompt_changes=0,output_repairs=0)


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
        status='setup_error', method=getattr(args,'method_id','aruqula-fedup'), author_commit=AUTHOR_COMMIT,
        request_sha256=args.request_sha256, model_calls=None, input_tokens=None,
        output_tokens=None, backend_calls=None, final_query_submissions=0,
        parent_observers_required=True, gold_reads=0, wrapper_retries=0,
        author_algorithm_changes=0, answer=None)
    compatibility = getattr(args,'compatibility','original')
    if compatibility not in COMPATIBILITIES:
        raise ValueError('Unknown author compatibility configuration')
    receipt['compatibility'] = compatibility
    receipt['author_source_compatibility_patches'] = 0
    receipt['action_envelope_key_aliases'] = 0
    receipt['action_name_or_argument_repairs'] = 0
    prompt_writer = None
    previous_openai={k:os.environ.get(k) for k in ('OPENAI_API_KEY','OPENAI_BASE_URL','NO_PROXY','no_proxy')}
    diagnostic=None
    restore_model_transport=None
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
        # This pinned LangChain/LiteLLM bridge reads the standard OpenAI environment
        # alias even though ChainLite also accepts a named key in its YAML config.
        # Configure credentials in memory only; keep the original client/algorithm.
        os.environ['OPENAI_API_KEY']=os.environ['XGAP_EXTERNAL_LLM_API_KEY']
        os.environ['OPENAI_BASE_URL']=model
        # All author endpoints are owned loopback observers. Keep their traffic
        # direct even when macOS advertises a system-wide HTTP proxy. Only the
        # model observer's remote hop uses that proxy, as configured by parent.
        for name in ('NO_PROXY','no_proxy'):
            prior=os.environ.get(name,os.environ.get(name.swapcase(),''))
            os.environ[name]=','.join(filter(None,(prior,'127.0.0.1','localhost','::1')))
        receipt['loopback_proxy_bypass']=True
        diagnostic=(root/'deadline-stack.txt').open('x')
        faulthandler.dump_traceback_later(270,file=diagnostic)
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
        os.environ['ORG_SPARQL_SERVICE_URL'] = endpoint
        os.environ['ORG_LOOKUP_SERVICE_URL'] = lookup
        os.chdir(root)
        sys.path.insert(0, str(source))
        if compatibility != 'original':
            overlay, patch_receipt = https_property_overlay(source,root,
                include_entity=compatibility in ('https-iris-qwen-key-v2','https-iris-qwen-envelope-v3',
                    'https-iris-nonthinking-v1','https-iris-action-schema-v1','https-iris-action-schema-fedx-v1'),
                entity_label=compatibility=='https-iris-action-schema-fedx-v1')
            receipt['compatibility_patch'] = patch_receipt
            receipt['author_source_compatibility_patches'] = patch_receipt['replacements']
            write(root/'compatibility-patch.json',patch_receipt)
            sys.path.insert(0,str(overlay))
        if compatibility in ('https-iris-nonthinking-v1','https-iris-action-schema-v1','https-iris-action-schema-fedx-v1'):
            instruction=None
            if compatibility in ('https-iris-action-schema-v1','https-iris-action-schema-fedx-v1'):
                prompt=(source/'spinach_agent/prompts/format_actions.prompt').read_text()
                instruction=prompt.split('# instruction\n',1)[1].split('# distillation instruction',1)[0].strip()
                receipt['formatter_transport_schema']=ACTION_SCHEMA
            restore_model_transport=install_nonthinking_transport(instruction)
            receipt['model_template_parameters']={'enable_thinking':False}
            receipt['model_template_matches_xgap']=True
            receipt['action_envelope_adapter_enabled']=False
        write(root / 'intent.json', receipt)
        from chainlite import write_prompt_logs_to_file
        prompt_writer = write_prompt_logs_to_file
        from spinach_agent import part_to_whole_parser
        PartToWholeParser = part_to_whole_parser.PartToWholeParser
        if compatibility in ('https-property-iris-qwen-key-v1','https-iris-qwen-key-v2','https-iris-qwen-envelope-v3'):
            from langchain_core.runnables import RunnableLambda
            def decode_envelope(value):
                decoded = action_envelope_alias(value,
                    sole_reasoning_key=compatibility=='https-iris-qwen-envelope-v3')
                if decoded is not value:
                    receipt['action_envelope_key_aliases'] += 1
                    # No prompt, action argument or query content in this audit.
                    digest=lambda v:hashlib.sha256(json.dumps(v,sort_keys=True).encode()).hexdigest()
                    record=dict(index=receipt['action_envelope_key_aliases'],
                        rule=('sole reasoning string key -> thought; action_name/action_argument unchanged'
                              if compatibility=='https-iris-qwen-envelope-v3'
                              else 'rename > to thought only when it is the sole missing key'),
                        before_sha256=digest(value),after_sha256=digest(decoded))
                    with (root/'action-key-aliases.jsonl').open('a') as stream:
                        stream.write(json.dumps(record)+'\n')
                return decoded
            part_to_whole_parser.json_to_action = (
                RunnableLambda(decode_envelope) | part_to_whole_parser.json_to_action)
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
        if restore_model_transport:restore_model_transport()
        if diagnostic:
            faulthandler.cancel_dump_traceback_later()
            diagnostic.close()
        if prompt_writer:
            try:
                prompt_writer()
            except Exception as error:
                receipt['prompt_log_error_type'] = type(error).__name__
        for key,value in previous_openai.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value
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
    parser.add_argument('--method-id',choices=['aruqula-fedup','aruqula-fedx','aruqula-single-fuseki'],default='aruqula-fedup')
    parser.add_argument('--compatibility',choices=COMPATIBILITIES,default='original')
    raise SystemExit(run(parser.parse_args()))
