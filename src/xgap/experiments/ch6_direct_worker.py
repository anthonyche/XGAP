"""Durable direct-proposal adapter. Deliberately accepts no private-user path."""
import json
import os
from pathlib import Path
import threading
import time

from xgap.experiments.ch6_direct import METHOD, TRACK, answer_direct
from xgap.experiments import unified_contract
from xgap.experiments.bounded_joint_contract import METRICS
from xgap.experiments.evidence_store import write_json_evidence
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned, native_clients
from xgap.experiments.one_shot_records import CapturingClient, write_once
from xgap.experiments.one_shot_toy import _DurableRecordingProvider
from xgap.llm.compact_interpretation import CompactInterpretationProviderConfig


def run(*, profile_path, profile_sha256, request_path, request_sha256,
        joint_config_path, joint_config_sha256, output):
    root = Path(output); root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter(); captures = []; active = False
    receipt = dict(schema_version='xgap-nl-method-worker-v1', method=METHOD, track=TRACK,
        success=False, status='preparing', request_sha256=request_sha256,
        profile_sha256=profile_sha256, joint_config_sha256=joint_config_sha256,
        reference_available_to_worker=False, oracle_available_to_worker=False,
        execution_kind='configured_native', automatic_retries=0, model_calls=0,
        top_level_attempts=0, final_plan_executions=0, fit_calls=0, probe_calls=0,
        clarification_calls=0, total_user_calls=0, scope_confirmation_calls=0,
        user_observations=[], intent_guarantee=False)
    try:
        raw = json.loads(read_pinned(request_path, request_sha256))
        if set(raw) != {'schema_version','question_id','question','population','exposure'}:
            raise ValueError('Unexpected public request fields')
        receipt.update({k: raw[k] for k in ('question_id','population','exposure')})
        config, _, settings, costs = unified_contract.load_configuration(joint_config_path, joint_config_sha256)
        unified_contract.validate_method('xgap-unified-lookahead', settings)
        if config['provider'] != 'frozen_compact_model':
            raise ValueError('Direct experiment requires the frozen one-call model')
        profile = FrozenOneShotProfile.load(profile_path, expected_sha256=profile_sha256)
        materialized = profile.materialize()
        doc, estimator, _, sources, backends, specs, modes = materialized
        receipt['dataset'] = doc['dataset']
        request = profile.request(raw, 'performance', materialized)
        physical, provider = modes['performance']
        if not isinstance(provider.config, CompactInterpretationProviderConfig):
            raise ValueError('Frozen compact provider required')
        language = provider.config.language_version
        preflight = provider.token_guard.check(provider.build_request_payload(request), call_kind='generation')
        if not preflight['passed']: raise ValueError('Frozen token budget exceeded')
        if not os.environ.get(provider.config.api_key_env): raise ValueError('Configured model credential unavailable')
        write_once(root/'intent.json', dict(request=request.to_dict(), settings=config['settings'],
            cost_profile=costs.to_dict(), preflight=preflight, maximum_model_calls=1,
            maximum_final_plan_executions=1, oracle_available_to_worker=False))
        provider = _DurableRecordingProvider(provider, root/'interpretation.json')
        lock = threading.Lock()
        clients = {name: CapturingClient(client, root, captures, lock, retain_payloads=False, compress=True)
                   for name, client in native_clients(specs).items()}
        active = True
        core = answer_direct(request, provider, settings=settings, costs=costs,
            source_schema=doc['source_schema'], sources=sources, backends=backends,
            backend_clients=clients, physical_profile=physical, estimator=estimator, language_version=language)
        active = False
        receipt.update({k: core.get(k) for k in ('success','status','model_calls','input_tokens','output_tokens',
            'final_plan_executions','error','error_type',*METRICS)})
        receipt.update(unified_contract.metric_values(core))
        receipt.update(top_level_attempts=core['final_plan_executions'], total_user_calls=0,
            clarification_calls=0, scope_confirmation_calls=0, disclosed_coordinates=0,
            core=write_json_evidence(root/'core.json.gz', core),
            result=write_json_evidence(root/'answer.json.gz', dict(answer_format='json_rows', answer=core['answer_rows'])),
            interpretation_ms=core.get('interpretation', {}).get('elapsed_ms'),
            proposal_kind='frozen_compact_model', algorithm_profile='single-proposal-shared-physical-v1')
    except Exception as error:
        receipt.update(success=False, status='worker_failed', error_type=type(error).__name__, error=str(error))
        if active: receipt.update(model_calls=None, final_plan_executions=None, top_level_attempts=None)
    finally:
        receipt.update(backend_calls=len(captures), backend_ledger=write_once(root/'backend-ledger.json', captures),
                       worker_ms=(time.perf_counter()-started)*1000)
        write_once(root/'receipt.json', receipt)
    return receipt
