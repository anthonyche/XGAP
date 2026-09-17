"""Durable NL-only or explicit simulated-user method; independent scoring stays outside."""
import json
import os
from pathlib import Path
import threading
import time

from xgap.agent.nl_strong_question import NL_STRONG_METHODS, NL_USER_METHODS, NL_FAMILY_METHODS, run_nl_strong_question
from xgap.agent.nl_intent_question import family_configuration
from xgap.agent.intent_user import ScopedFamilyUser
from xgap.agent.simulated_user import SimulatedUserTool, SimulatedUserPolicy
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned, native_clients
from xgap.experiments.one_shot_records import CapturingClient, write_once
from xgap.experiments.one_shot_toy import _DurableRecordingProvider


def run_nl_strong(*, request_path, request_sha256, profile_path, profile_sha256, method, output,
                  oracle_path=None, oracle_sha256=None, user_max_calls=9,
                  intent_family_path=None,intent_family_sha256=None, **unused):
    root = Path(output); root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter(); active = False; captures = []
    r = dict(schema_version='xgap-nl-method-worker-v1', method=method, track='natural_language',
        success=False, status='preparing', request_sha256=request_sha256, profile_sha256=profile_sha256,
        model_calls=0, input_tokens=0, output_tokens=0, fit_calls=0, probe_calls=0,
        automatic_retries=0, top_level_attempts=0, alternative_executions=0, result=None,
        input_scope='NL and generic frozen schema only; model structure is not intent authority')
    try:
        if method not in (*NL_STRONG_METHODS, *NL_USER_METHODS, *NL_FAMILY_METHODS):
            raise ValueError('Unknown NL strong method')
        family_mode = method in NL_FAMILY_METHODS
        interaction = method in (*NL_USER_METHODS,*NL_FAMILY_METHODS)
        if family_mode != (intent_family_path is not None and intent_family_sha256 is not None) or (
                not family_mode and (intent_family_path is not None or intent_family_sha256 is not None)):
            raise ValueError('Explicit finite-family method and public family pin are required together')
        if interaction != (oracle_path is not None and oracle_sha256 is not None) or (
                not interaction and (oracle_path is not None or oracle_sha256 is not None)):
            raise ValueError('Explicit user-interaction method and private oracle pin are required together')
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
        family_args={};propose=True;effective_user_max=user_max_calls
        if family_mode:
            family,info,limits,epsilon,propose=family_configuration(
                json.loads(read_pinned(intent_family_path,intent_family_sha256)),request.question)
            oracle=ScopedFamilyUser(family,Path(oracle_path),oracle_sha256)
            effective_user_max=info.max_calls
            family_args=dict(intent_family=family,family_information=info,family_limits=limits,
                family_epsilon='0' if method.endswith('-exact') else epsilon,propose_with_model=propose)
            r.update(intent_family_sha256=intent_family_sha256,family_identity=family.identity)
        else:
            oracle = SimulatedUserTool(Path(oracle_path), oracle_sha256) if interaction else None
        user_policy = SimulatedUserPolicy() if family_mode else SimulatedUserPolicy(max_calls=user_max_calls)
        if interaction:
            r.update(track='natural_language_finite_family' if family_mode else 'natural_language_interaction',
                input_scope='NL plus public finite intent contract; private metered authority' if family_mode
                    else 'NL and generic schema; metered private user replies',
                oracle_sha256=oracle_sha256, user_max_calls=effective_user_max)
            write_once(root/'oracle_preflight.json', oracle.preflight(request.question))
        if policy.candidate_cap != 1:
            raise ValueError('NL strong worker requires frozen K=1')
        budget = (provider.token_guard.check(provider.build_request_payload(request), call_kind='generation')
            if propose else {'passed':True,'scope':'explicit model-disabled family profile'})
        write_once(root/'preflight.json', dict(request=request.to_dict(), budget=budget,
            provider=provider.config.safe_dict(), policy=policy.to_dict(), profile_sha256=profile_sha256))
        if not budget['passed']:
            raise ValueError('Frozen NL request exceeds provider budget')
        if propose and not os.environ.get(provider.config.api_key_env):
            raise ValueError('Configured model credential is unavailable')
        recorder = _DurableRecordingProvider(provider, root/'interpretation.json') if propose else None
        lock = threading.Lock()
        clients = {b: CapturingClient(c, root, captures, lock, retain_payloads=False) for b, c in native_clients(specs).items()}
        write_once(root/'intent.json', dict(maximum_model_calls=int(propose), maximum_final_executions=1,
            automatic_retries=0, reference_available_to_worker=False,
            maximum_user_calls=effective_user_max if interaction else 0,
            user_intent_scope='public family full/scoped coordinates' if family_mode else
                'query statement and entity identities' if interaction else None))
        user_records = []
        def user_observation(record):
            user_records.append(write_once(root/f'user-observation-{len(user_records):02}.json', record))
        active = True
        core = run_nl_strong_question(request, recorder, mode=method.rsplit('-',1)[1],
            policy=policy, bundle=bundle, sources=sources, backends=backends, backend_clients=clients, estimator=estimator,
            user_oracle=oracle, user_policy=user_policy, on_user_observation=user_observation,**family_args)
        active = False
        r.update({k: core.get(k) for k in ('success', 'status', 'model_calls', 'input_tokens', 'output_tokens',
            'planning_ms', 'planning_cpu_ms', 'execution_ms', 'interpretation_ms', 'grounding_ms', 'strong_plan', 'strong_scope',
            'semantic_validation', 'unvalidated_bindings', 'structure_validation', 'user_intent_verified',
            'semantic_discrepancy_upper_bound', 'discrepancy_status', 'usage_complete')})
        if interaction:
            r.update({k:core.get(k) for k in ('clarification_calls','oracle_processing_ms','oracle_lowering_ms',
                'declared_user_wait_ms','acquisition_policy_scope','profile_id')})
            r['user_observations'] = user_records
        if family_mode:
            r.update({k:core.get(k) for k in ('input_scope','disclosed_coordinates','oracle_reply_bytes',
                'certificate_ms','certificate_checks','physical_prepare_attempts','physical_plan_cache_hits',
                'acquisition_ms','terminal_certificate','root_gap','search')})
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
