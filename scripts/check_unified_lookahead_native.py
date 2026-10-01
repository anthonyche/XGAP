#!/usr/bin/env python3
"""Two correctness executions and a reserve rejection on frozen tiny native stores."""
import argparse
import json
from pathlib import Path
import subprocess

from native_store_session import NativeStoreSession
from prepare_rdf_tdb import REPO
from xgap.api import answer_unified
from xgap.agent.scope_authority import QueryIntentAuthority, private_query_intent
from xgap.agent.unified_family import UnifiedSettings
from xgap.agent.unified_lookahead import Limits, Resources
from xgap.experiments.bounded_joint_toy import QUESTION, TemplateProposalProvider, load_inputs, toy_scope
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.compact_profile import derive_compact_prompt_profile
from xgap.experiments.evidence_store import write_json_evidence
from xgap.experiments.external_federation import deadline
from xgap.experiments.nl_strong_release import freeze_common_profile
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, native_clients
from xgap.experiments.one_shot_records import write_once


def public_request():
    return dict(schema_version='xgap-one-shot-evaluation-request-v1', question_id='UNIFIED-TINY',
                question=QUESTION, population='authored toy', exposure='development')


def main(output, prepared_path, prepared_sha256):
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    session = None
    receipt = dict(schema_version='xgap-unified-seed-native-gate-v1', success=False,
        scope='eight-node authored development correctness; not model quality or comparative evaluation',
        maximum_model_calls=0, maximum_final_plans=2, automatic_retries=0, cases=[], closures=[])
    try:
        if subprocess.check_output(['git', 'status', '--porcelain'], cwd=REPO, text=True):
            raise ValueError('Commit before native boundary gate')
        receipt['source_commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()
        data, _ = load_inputs()
        request_pin = write_once(root/'request.json', public_request())
        user = write_once(root/'private-user.json', private_query_intent(QUESTION, data['query_template']))
        intent = write_once(root/'intent.json', dict(question=QUESTION, population='authored eight-node toy',
            cases=['strict', 'zero_optional_search', 'no_completion_calls'], expected_final_executions=[1, 1, 0],
            expected_success=[True, True, False], fixed_order=True, repeats=1))
        session = NativeStoreSession(root=root/'session', prepared_path=prepared_path,
            prepared_sha256=prepared_sha256, discard_serving_copies=True,
            budget=SourceObservationBudget(capture_compression='gzip', max_calls=64,
                request_bytes=1024**2, phase_request_bytes=4*1024**2, response_bytes=2*1024**2,
                phase_response_bytes=8*1024**2, timeout_seconds=20))
        with deadline(120):
            session.start()
        pin = derive_compact_prompt_profile(parent_path=session.profile['path'], parent_sha256=session.profile['sha256'],
                                            output=session.root/'compact')
        pin = freeze_common_profile(pin, session.root/'common-profile.json')
        profile = FrozenOneShotProfile.load(pin['path'], expected_sha256=pin['sha256'])
        materialized = profile.materialize()
        _, _, _, sources, backends, specs, modes = materialized
        request = profile.request(public_request(), 'performance', materialized)
        physical, _ = modes['performance']  # Reuse the frozen physical input, not its historical controller.
        receipt['inputs'] = dict(profile=pin, request=request_pin, private_user=user, intent=intent,
                                prepared=dict(path=str(prepared_path), sha256=prepared_sha256))
        cases = [('strict', UnifiedSettings()),
                 ('zero_optional_search', UnifiedSettings(limits=Limits(optional_ms=0))),
                 ('no_completion_calls', UnifiedSettings(limits=Limits(resources=Resources(
                      user_calls=0, remote_calls=32, bytes=None, peak_bytes=None))))]
        for name, settings in cases:
            session.observer.set_phase(name)
            with deadline(90):
                result = answer_unified(request, TemplateProposalProvider(data['query_template']),
                    settings=settings, scope_policy=toy_scope(),
                    authority=QueryIntentAuthority(Path(user['path']), user['sha256']), physical_profile=physical,
                    sources=sources, backends=backends, backend_clients=native_clients(specs))
            core = write_json_evidence(root/(name+'-core.json.gz'), result)
            observations = session.observer.seal_phase(name)
            outcome = write_once(root/(name+'-outcome.json'), dict(core=core, source_observations=observations))
            session.observer.release_phase(name, outcome)
            case = {k: result.get(k) for k in ('success', 'status', 'final_plan_executions', 'clarification_calls',
                                              'scope_confirmation_calls', 'model_calls', 'backend_remote_calls')}
            case.update(name=name, exact_answer_match=result['answer_rows'] == data['expected'],
                        outcome=outcome, source_observations=observations)
            receipt['cases'].append(case)
            expected = name != 'no_completion_calls'
            if (result['success'] != expected or result['final_plan_executions'] != int(expected)
                    or result['model_calls'] != 0 or observations['failed_requests'] != 0
                    or expected and not case['exact_answer_match']
                    or not expected and (observations['requests'] != 0 or result['status'] != 'completion_witness_unavailable')):
                raise ValueError('Unified tiny boundary case failed: '+name)
        receipt['success'] = len(receipt['cases']) == 3
    except Exception as error:
        receipt.update(error_type=type(error).__name__, error=str(error))
    finally:
        if session:
            receipt['closures'].append(session.close())
        receipt['success'] &= bool(receipt['closures']) and all(
            c['owned_groups_drained'] and c['owned_processes_terminal'] and c['observer_stopped']
            for c in receipt['closures'])
        result_pin = write_once(root/'receipt.json', receipt)
    print(json.dumps(dict(success=receipt['success'], receipt=result_pin, error=receipt.get('error'), cases=receipt['cases'])))
    return 0 if receipt['success'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'prepared-path', 'prepared-sha256'):
        parser.add_argument('--'+name, required=True)
    with deadline(420):
        raise SystemExit(main(**vars(parser.parse_args())))
