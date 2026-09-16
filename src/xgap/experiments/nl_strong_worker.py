"""Durable NL-only conditional strong method; scoring stays in the supervisor."""
import json
import os
from pathlib import Path
import threading
import time

from xgap.agent.nl_strong_question import NL_STRONG_METHODS, run_nl_strong_question
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned, native_clients
from xgap.experiments.one_shot_records import CapturingClient, write_once
from xgap.experiments.one_shot_toy import _DurableRecordingProvider


def run_nl_strong(*, request_path, request_sha256, profile_path, profile_sha256, method, output, **unused):
    root = Path(output); root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter(); active = False; captures = []
    r = dict(schema_version='xgap-nl-method-worker-v1', method=method, track='natural_language',
        success=False, status='preparing', request_sha256=request_sha256, profile_sha256=profile_sha256,
        model_calls=0, input_tokens=0, output_tokens=0, fit_calls=0, probe_calls=0,
        automatic_retries=0, top_level_attempts=0, alternative_executions=0, result=None,
        input_scope='NL and generic frozen schema only; model structure is not intent authority')
    try:
        if method not in NL_STRONG_METHODS:
            raise ValueError('Unknown NL strong method')
        profile = FrozenOneShotProfile.load(profile_path, expected_sha256=profile_sha256)
        materialized = profile.materialize()
        doc, estimator, bundle, sources, backends, specs, modes = materialized
        raw = json.loads(read_pinned(request_path, request_sha256))
        if set(raw) != {'schema_version', 'question_id', 'question', 'population', 'exposure'}:
            raise ValueError('NL strong evaluation excludes per-question structure, placement and gold fields')
        r.update({k: raw[k] for k in ('question_id', 'population', 'exposure')}); r['dataset'] = doc['dataset']
        # Both modes use the SAME frozen K=1 interpretation and grounding policy.
        request = profile.request(raw, 'performance', materialized)
        policy, provider = modes['performance']
        if policy.candidate_cap != 1:
            raise ValueError('NL strong worker requires frozen K=1')
        budget = provider.token_guard.check(provider.build_request_payload(request), call_kind='generation')
        write_once(root/'preflight.json', dict(request=request.to_dict(), budget=budget,
            provider=provider.config.safe_dict(), policy=policy.to_dict(), profile_sha256=profile_sha256))
        if not budget['passed']:
            raise ValueError('Frozen NL request exceeds provider budget')
        if not os.environ.get(provider.config.api_key_env):
            raise ValueError('Configured model credential is unavailable')
        recorder = _DurableRecordingProvider(provider, root/'interpretation.json'); recorder.config = provider.config
        lock = threading.Lock()
        clients = {b: CapturingClient(c, root, captures, lock, retain_payloads=False) for b, c in native_clients(specs).items()}
        write_once(root/'intent.json', dict(maximum_model_calls=1, maximum_final_executions=1,
            automatic_retries=0, reference_available_to_worker=False))
        active = True
        core = run_nl_strong_question(request, recorder, mode=method.removeprefix('xgap-nl-strong-'),
            policy=policy, bundle=bundle, sources=sources, backends=backends, backend_clients=clients, estimator=estimator)
        active = False
        r.update({k: core.get(k) for k in ('success', 'status', 'model_calls', 'input_tokens', 'output_tokens',
            'planning_ms', 'planning_cpu_ms', 'execution_ms', 'interpretation_ms', 'grounding_ms', 'strong_plan', 'strong_scope',
            'semantic_validation', 'unvalidated_bindings', 'structure_validation', 'user_intent_verified',
            'semantic_discrepancy_upper_bound', 'discrepancy_status', 'usage_complete')})
        r.update(top_level_attempts=core['final_plan_executions'], backend_calls=len(captures),
            backend_capture_profile='pinned-responses-v1', core_end_to_end_ms=core['end_to_end_ms'])
        r['core_result'] = write_once(root/'core.json', core)
        r['result'] = write_once(root/'answer.json', {'answer_format': 'json_rows',
            'answer': core['answer_rows'] if core['success'] else None})
        write_once(root/'backend_ledger.json', captures)
    except Exception as error:
        r.update(success=False, status='worker_failed', error_type=type(error).__name__, error=str(error))
        if active:
            r.update(model_calls=None, input_tokens=None, output_tokens=None, top_level_attempts=None, usage_complete=False)
    finally:
        r['worker_ms_before_receipt'] = (time.perf_counter() - started) * 1000
        write_once(root/'receipt.json', r)
    return r
