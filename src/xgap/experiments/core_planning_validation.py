#!/usr/bin/env python3
"""Offline complete-query selection diagnostic: zero execution, no reference rows.

The terminal callback records a proposed plan and deliberately reports that no
execution occurred. Its internal controller report is NOT an admission/result
receipt. Only the diagnostic fields below are published.
"""
import json
from pathlib import Path

from xgap.agent.intent_certificate import IntentCandidate,IntentFamily,fingerprint
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.practical_planning import _baseline
from xgap.agent.scope_authority import ScopedQueryUser
from xgap.agent.unified_family import run_unified_family,UnifiedSettings
from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.experiments.one_shot_records import write_once
from xgap.planning.joint_cost import JointCostProfile
from xgap.runtime.unified_physical import PhysicalMoves
from xgap.semantic.compact_lowering import lower_compact_query


def rebind(bundle_pin,prepared_pin,output):
    """Reuse selected questions/references only when all execution inputs match."""
    bundle=load_pin(bundle_pin);prepared=load_pin(prepared_pin)
    parent=FrozenOneShotProfile.load(bundle['profile']['path'],expected_sha256=bundle['profile']['sha256'])
    child=FrozenOneShotProfile.load(prepared['profile']['path'],expected_sha256=prepared['profile']['sha256'])
    old,*_=parent.materialize();new,*_=child.materialize()
    original_profile=dict(bundle['profile'])
    for doc,profile in ((old,parent),(new,child)):
        doc['catalog']['path']=str((profile.root/doc['catalog']['path']).resolve())
        for mode in doc['modes'].values():
            prompt=mode['provider']['prompt'];prompt['path']=str((profile.root/prompt['path']).resolve())
    for key in ('dataset','source_schema','sources','backends','catalog','modes'):
        if old[key]!=new[key]:raise ValueError('Estimator-only case rebinding changed '+key)
    if not prepared['success']:raise ValueError('Successful prepared stores required')
    bundle['profile']=prepared['profile']
    bundle['estimator_revision']=dict(parent_bundle=bundle_pin,
        original_profile=original_profile,
        query_or_reference_changes=False,reason='Estimator-only revision on identical execution inputs')
    return write_once(Path(output),bundle)


def inspect(bundle_pin,output):
    bundle=load_pin(bundle_pin);pp=bundle['profile']
    profile=FrozenOneShotProfile.load(pp['path'],expected_sha256=pp['sha256'])
    doc,estimator,_,sources,backends,_,modes=profile.materialize()
    if not 1<=len(bundle['cases'])<=1024:raise ValueError('Bounded presampled bundle required')
    snapshot=snapshot_identity(sources,backends,doc['source_schema'])
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False);rows=[]
    for i,case in enumerate(bundle['cases']):
        if case['source_snapshot_sha256']!=snapshot:raise ValueError('Case snapshot differs')
        query=load_pin(case['oracle'])['query'];question=load_pin(case['request'])['question']
        family=IntentFamily('offline-complete-query-diagnostic',
            (IntentCandidate.create(fingerprint(query),query),),(),snapshot,language_version='v2',
            coverage_basis='offline complete-query diagnostic; no NL interpretation claim')
        program,assignment=lower_compact_query(query,doc['source_schema'],version='v2',optimize=True)
        physical=modes['performance'][0];selected=[]
        def record(plan):
            selected.append(plan)
            return dict(success=False,reason='planning diagnostic only; execution deliberately not performed')
        report=run_unified_family(question,family,ScopedQueryUser(family,case['oracle']['path'],case['oracle']['sha256']),
            prepare_seed=lambda *_:_baseline(program,assignment,sources,backends,physical,optimize_reads=False),
            execute=record,costs=JointCostProfile(),settings=UnifiedSettings(),estimator=estimator,
            moves=PhysicalMoves(family,doc['source_schema'],backends,physical,sources))
        if len(selected)!=1 or report['external_calls_during_search'] or report['clarification_calls']:
            raise ValueError('Expected exactly one symbolic terminal and zero external actions')
        plan=selected[0];remote=[n for n in plan.nodes if n.kind.value.startswith('remote_')]
        row=dict(case_id=case['case_id'],query_sha256=fingerprint(query),
            selected_plan=write_once(root/f'plan-{i:04d}.json',plan.to_dict()),
            full_edge_reads=sum(n.kind.value=='remote_query' and n.parameters['artifact']['parameters'].get('compiler')=='semantic_edge_match_v1' for n in remote),
            bound_reads=sum(n.kind.value=='remote_bind_query' for n in remote),
            estimate=estimator.predict(plan).to_dict(),
            expanded_states=report['expanded_states'],physical_actions=report['physical_actions'])
        rows.append(row)
    return write_once(root/'receipt.json',dict(schema_version='xgap-ch6-planning-diagnostic-v1',
        success=True,bundle=bundle_pin,profile=pp,cases=rows,backend_calls=0,model_calls=0,
        actual_plan_executions=0,reference_rows_read=0,backend_admission=False,
        scope='Offline complete-query selection; no performance or answer-quality result'))


