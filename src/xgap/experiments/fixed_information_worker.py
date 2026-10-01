"""One matched fixed-information frontend and one unchanged author query."""
import json
import math
from pathlib import Path
import time

from xgap.agent.fixed_information_frontend import prepare_fixed_information_query
from xgap.experiments.external_federation import deadline, query_once
from xgap.experiments.one_shot_profile import _file, _url, read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.practical_method_worker import _usage
from xgap.experiments.practical_methods import FIXED_INFORMATION_METHODS
from xgap.experiments.practical_profile import FrozenPracticalProfile, REQUEST_SCHEMA
from xgap.experiments.practical_records import CapturingAcquisition


def run_fixed_information(*, request_path, request_sha256, profile_path, profile_sha256,
        method, output, endpoint=None, seconds=180):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    active = False
    r = {'schema_version': 'xgap-nl-method-worker-v1', 'method': method, 'track': 'trusted_template',
        'success': False, 'status': 'preparing', 'request_sha256': request_sha256,
        'profile_sha256': profile_sha256, 'result': None, 'model_calls': 0, 'input_tokens': 0,
        'output_tokens': 0, 'fit_calls': 0, 'probe_calls': 0, 'automatic_retries': 0,
        'top_level_attempts': 0, 'alternative_executions': 0, 'paper_result': False,
        'strong_plan': None, 'execution_kind': 'configured_external', 'planning_ms': None,
        'backend_calls': None, 'input_scope': 'matched trusted template and mode permissions; explicit fixed-information plus author-method composition'}
    captures = []
    try:
        if method not in FIXED_INFORMATION_METHODS:
            raise ValueError('Explicit composed-method identity required')
        _url(endpoint)
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError('Finite positive worker deadline required')
        mode, engine = FIXED_INFORMATION_METHODS[method]
        r.update(external_engine=engine, information_strategy='fixed_action_order_v1')
        with deadline(seconds):
            request = json.loads(read_pinned(request_path, request_sha256))
            if request.get('schema_version') != REQUEST_SCHEMA:
                raise ValueError('Composition requires a practical trusted-template request')
            r.update({k: request[k] for k in ('question_id', 'population', 'exposure')})
            profile, cfg = FrozenPracticalProfile.load_materialized(profile_path, expected_sha256=profile_sha256)
            doc = cfg[0]
            r['dataset'] = doc['dataset']
            if 'external_frontend' not in doc:
                raise ValueError('An explicit frozen external frontend mapping is required')
            mapping = json.loads(_file(profile.root, doc['external_frontend']['mapping']))
            capture_root = root / 'acquisitions'
            capture_root.mkdir()
            prepared = profile.prepare(request, request_sha256=request_sha256,
                request_root=Path(request_path).resolve().parent, mode=mode, materialized=cfg,
                acquisition_wrapper=lambda tool: CapturingAcquisition(tool, capture_root, captures))
            r['admission_ms'] = (time.perf_counter() - started) * 1000
            write_once(root / 'frontend-intent.json', {'method': method, 'mode': mode,
                'request_sha256': request_sha256, 'profile_sha256': profile_sha256,
                'mapping': doc['external_frontend']['mapping'], 'maximum_final_queries': 1})
            active = True
            opts = prepared.options
            front = prepare_fixed_information_query(prepared.program, initial_state=opts.initial_state,
                mode=opts.mode, actions=opts.actions, predictions=opts.predictions,
                resolution_tools=opts.resolution_tools, limits=opts.limits, physical_profile=opts.physical_profile,
                operator_sources=prepared.provider.operator_sources, binding_values=cfg[2].bindings,
                sources=cfg[4], backends=cfg[5], mapping=mapping)
            active = False
            front['model_invocations'] = {k: p.last_invocation.to_dict() for k, p in prepared.model_providers.items()
                if p.last_invocation is not None}
            front['acquisition_captures'] = captures
            front['source_routing'] = prepared.source_routing
            r.update(model_calls=front['model_calls'], **_usage(front, front['model_calls']))
            r['core_result'] = write_once(root / 'frontend.json', front)
            for key in ('status', 'frontend_ms', 'compilation_ms', 'acquisition_ms', 'clarification_calls',
                        'semantic_validation', 'unvalidated_bindings', 'semantic_discrepancy_upper_bound', 'discrepancy_status'):
                r[key] = front[key]
            r['usage_complete'] = all(r[k] is not None for k in ('model_calls', 'input_tokens', 'output_tokens'))
            answer = {'answer_format': 'sparql_json', 'answer': None}
            if front['success']:
                remaining = seconds - (time.perf_counter() - started)
                if remaining <= 0:
                    raise TimeoutError('Request deadline exhausted before external query')
                write_once(root / 'execution-intent.json', {'maximum_final_queries': 1,
                    'external_engine': engine, 'artifact': front['artifact']})
                r['top_level_attempts'] = 1
                response = query_once(endpoint, front['artifact']['text'], seconds=min(120, remaining), output=root / 'response.json')
                r.update(execution_ms=response['client_wall_ms'],
                    success=response['status'] == 'returned' and response.get('http_status') == 200,
                    status='returned' if response['status'] == 'returned' and response.get('http_status') == 200 else 'external_failed')
                if r['success']:
                    answer['answer'] = json.loads(response['body_utf8'])
            r['result'] = write_once(root / 'answer.json', answer)
    except Exception as error:
        r.update(success=False, status='worker_failed', error_type=type(error).__name__, error=str(error))
        if active:
            r.update(model_calls=None, input_tokens=None, output_tokens=None, usage_complete=False)
    finally:
        r['acquisition_captures'] = captures
        r['worker_ms_before_receipt'] = (time.perf_counter() - started) * 1000
        write_once(root / 'receipt.json', r)
    return r
