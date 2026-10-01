#!/usr/bin/env python3
"""Two declared NL/family/strong-policy trials on frozen eight-node native stores."""
import argparse
from dataclasses import asdict
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys

from native_store_session import NativeStoreSession, NativeSources
from prepare_rdf_tdb import REPO, stream_pin
sys.path.insert(0,str(REPO/'tests'))
from test_compact_lowering import EXPECTED
from test_intent_strong import clustered_family, QUESTION
from xgap.agent.intent_certificate import fingerprint
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.intent_strong import FamilyInformationPolicy
from xgap.agent.intent_user import private_family_intent
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.common_method_trial import run_nl_trial
from xgap.experiments.common_row_score import score_trial
from xgap.experiments.compact_profile import derive_compact_prompt_profile
from xgap.experiments.external_federation import deadline
from xgap.experiments.nl_strong_release import freeze_common_profile
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.row_normalization import normalize_rows

PREPARED=Path('/Users/anthonyche/xgap-data/native-campaign-boundary-20260913-v2/prepared.json')
PREPARED_SHA='8f3c88515f52f8526faa4f9963a381ad1df1af7bf419f9bbdce0ec5e11648051'


def main(output,read_key=False):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    previous=os.environ.get('XGAP_EXTERNAL_LLM_API_KEY');session=None
    receipt=dict(schema_version='xgap-family-strong-native-gate-v1',success=False,
        scope='one known tiny NL question plus public finite family; not open-domain or paper evaluation',
        maximum_model_calls=2,maximum_final_plans=2,automatic_retries=0,data_loads=0,
        catalog_builds=0,fit_calls=0,baseline_calls=0,cases=[],closures=[])
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):
            raise ValueError('Commit before live gate')
        receipt['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
        key=getpass.getpass('LLM credential (not recorded): ') if read_key else previous
        if not key:raise ValueError('Missing configured model credential')
        os.environ['XGAP_EXTERNAL_LLM_API_KEY']=key;key=None
        write_once(root/'intent.json',dict(methods=['xgap-nl-family-exact','xgap-nl-family-performance'],
            performance_epsilon='1/2',private_intent='central',maximum_model_calls=2,maximum_final_plans=2,
            expected_answer_rows=[4,3],expected_clarification_calls=[1,0],
            full_intent_available_in_both_modes=True,automatic_retries=0,
            timing_scope='single fixed order; no statistical or overall speedup claim',
            expected_difference='one missing row at relaxed intent; not a passed exact-answer gate'))
        request=write_once(root/'request.json',dict(schema_version='xgap-one-shot-evaluation-request-v1',
            question_id='STRONG-INTENT-01',question=QUESTION,population='authored eight-node mechanism',
            exposure='known development case; finite family supplied separately'))
        spec=dict(schema_version='xgap-row-normalization-v1',fields=dict(
            other_id='text',account_distance='integer',medium_id='text',medium_type='text'))
        reference=write_once(root/'reference.json',dict(schema_version='xgap-normalized-row-reference-v1',
            question_id='STRONG-INTENT-01',dataset=dict(dataset_id='financial-binding-tiny',version='financial-tiny-v1'),
            ordered=True,normalization=spec,rows=normalize_rows(EXPECTED[1],spec),
            derivation='pre-existing independent eight-node hand-derived rows; not supplied to worker'))
        session=NativeStoreSession(root=root/'session',prepared_path=PREPARED,prepared_sha256=PREPARED_SHA,
            discard_serving_copies=True,budget=SourceObservationBudget(max_calls=64,request_bytes=1024**2,
                phase_request_bytes=4*1024**2,response_bytes=2*1024**2,phase_response_bytes=8*1024**2,timeout_seconds=20))
        with deadline(120):session.start()
        pin=derive_compact_prompt_profile(parent_path=session.profile['path'],parent_sha256=session.profile['sha256'],
            output=session.root/'compact-prompt')
        pin=freeze_common_profile(pin,session.root/'nl-strong-profile.json')
        profile=FrozenOneShotProfile.load(pin['path'],expected_sha256=pin['sha256'])
        materialized=profile.materialize();doc,estimator,bundle,sources,backends,specs,modes=materialized
        context=profile.request(json.loads(Path(request['path']).read_text()),'performance',materialized).context
        family=clustered_family(snapshot_identity(sources,backends,context['source_schema']))
        family_pin=write_once(root/'public-family-profile.json',dict(schema_version='xgap-family-strong-profile-v1',
            question_sha256=fingerprint(QUESTION),family=family.to_dict(),
            information_policy=asdict(FamilyInformationPolicy()),search_limits=asdict(StrongSearchLimits()),
            performance_epsilon='1/2',propose_with_model=True))
        oracle=write_once(root/'private-user.json',private_family_intent(family,QUESTION,'central'))
        receipt.update(profile=pin,public_family=family_pin,private_user=oracle,
            prepared=dict(path=str(PREPARED),sha256=PREPARED_SHA))
        for method in ('xgap-nl-family-exact','xgap-nl-family-performance'):
            directory=root/method;directory.mkdir()
            outcome=run_nl_trial(request_path=request['path'],request_sha256=request['sha256'],method=method,
                output=directory/'execution',owned_services=NativeSources(session).owned_for(method),observer=session.observer,
                profile_path=pin['path'],profile_sha256=pin['sha256'],oracle_path=oracle['path'],oracle_sha256=oracle['sha256'],
                intent_family_path=family_pin['path'],intent_family_sha256=family_pin['sha256'])
            score=score_trial(outcome['receipt']['path'],receipt_sha256=outcome['receipt']['sha256'],
                reference_path=reference['path'],reference_sha256=reference['sha256'],output=directory/'score.json')
            core_path=directory/'execution/worker/core.json'
            core=json.loads(core_path.read_text()) if core_path.exists() else {}
            cert=core.get('terminal_certificate');index=next((i for i,c in enumerate(family.candidates)
                if cert and c.candidate_id==cert['candidate_id']),None)
            case=dict(method=method,success=outcome['success'],status=outcome['status'],receipt=outcome['receipt'],
                score=stream_pin(directory/'score.json'),answer_em=score['answer_em'],
                returned_rows=len(core.get('answer_rows') or []),
                actual_intent_discrepancy=float(family.distances[index][0]) if index is not None else None,
                source_calls=(outcome.get('source_observations') or {}).get('requests'),
                source_observations=outcome.get('source_observations'),online_ms=outcome['timing']['total_online_ms'])
            case.update({k:core.get(k) for k in ('model_calls','input_tokens','output_tokens','clarification_calls',
                'disclosed_coordinates','oracle_reply_bytes','certificate_ms','planning_ms','planning_cpu_ms',
                'execution_ms','physical_prepare_attempts','final_plan_executions','strong_plan','terminal_certificate')})
            case['expanded_states']=core.get('search',{}).get('expanded_states')
            case['interpretation_success']=core.get('interpretation',{}).get('success')
            receipt['cases'].append(case)
            if not outcome['can_continue_session']:raise ValueError('Trial did not leave a reusable serving session; no retry')
        cases=receipt['cases']
        receipt['success']=(len(cases)==2 and all(c['success'] and c['strong_plan'] and c['model_calls']==1
            and c['final_plan_executions']==1 for c in cases) and
            [c['clarification_calls'] for c in cases]==[1,0] and [c['returned_rows'] for c in cases]==[4,3]
            and [c['answer_em'] for c in cases]==[1,0])
    except Exception as error:receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        if session:receipt['closures'].append(session.close())
        if previous is None:os.environ.pop('XGAP_EXTERNAL_LLM_API_KEY',None)
        else:os.environ['XGAP_EXTERNAL_LLM_API_KEY']=previous
        key=None
        receipt['success'] &= bool(receipt['closures']) and all(c['owned_groups_drained'] and c['owned_processes_terminal']
            and c['observer_stopped'] for c in receipt['closures'])
        receipt_pin=write_once(root/'receipt.json',receipt)
    print(json.dumps(dict(success=receipt['success'],receipt=receipt_pin,error=receipt.get('error'))))
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--read-key',action='store_true')
    with deadline(600):raise SystemExit(main(**vars(p.parse_args())))
