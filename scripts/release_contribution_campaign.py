#!/usr/bin/env python3
"""Freeze the existing contribution-v2 frontend and inherit every prior NL intent.

Offline association only. Original stores, summary, schedule order, model/policy,
and results are unchanged. This never reads golds or invokes a method/model.
"""
import argparse
from copy import deepcopy
import fcntl
import json
from pathlib import Path
import subprocess

from prepare_rdf_tdb import REPO, stream_pin
from xgap.experiments.compact_profile import derive_compact_contribution_profile
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned
from xgap.experiments.one_shot_records import write_once

PARENT=Path('/Users/anthonyche/xgap-data/finbench-compact-roles-v2-20260913')
RELEASE_SHA='8d48ce4e4a87087050d8c3b5d142fba3168e23b3f919b60677e14a5939f0d2ec'
ASSOCIATION_SHA='699a62f25ca630101cf0d486aa5e5f176a878a4d8372e5b06b7ec725061c4c4f'
OLD_CAMPAIGN=Path('/Users/anthonyche/xgap-data/finbench-rdf-nl-campaign-20260913-prompt-v2')


def ident(pin):
    return {k:pin[k] for k in ('path','sha256')}


def load(pin):
    return json.loads(read_pinned(pin['path'],pin['sha256']))


def validate_revision(parent,child):
    a,b=load(parent),load(child)
    for key in ('schema_version','dataset','source_schema','sources','backends'):
        if a[key]!=b[key]:raise ValueError('Frontend revision changed '+key)
    for key in ('catalog','estimator'):
        old=deepcopy(a[key]);old['path']=str((Path(parent['path']).parent/old['path']).resolve())
        if old!=b[key]:raise ValueError('Frontend revision changed '+key)
    if {k:v for k,v in a['offline'].items() if k!='interpretation_revision'}!={k:v for k,v in b['offline'].items() if k!='interpretation_revision'}:
        raise ValueError('Frontend revision changed offline source/model provenance')
    if b['offline']['interpretation_revision']['parent']!=ident(parent):raise ValueError('Revision parent mismatch')
    changed={'provider_id','wire_profile','prompt'}
    if set(a['modes'])!=set(b['modes']):raise ValueError('Changed modes')
    for mode in a['modes']:
        x,y=a['modes'][mode],b['modes'][mode]
        if {k:v for k,v in x.items() if k!='provider'}!={k:v for k,v in y.items() if k!='provider'}:
            raise ValueError('Changed mode policy')
        if {k:v for k,v in x['provider'].items() if k not in changed}!={k:v for k,v in y['provider'].items() if k not in changed}:
            raise ValueError('Changed model/transport configuration')
        if (x['provider']['wire_profile'],y['provider']['wire_profile'])!=('compact-graph-schema-v1','compact-graph-schema-v2'):
            raise ValueError('Unexpected language revision')
    FrozenOneShotProfile.load(child['path'],expected_sha256=child['sha256'])


def inherit_results(*,old_root,old_schedule,new_schedule,new_root,expected_count):
    """Copy references to a complete prefix, never copy/repair an answer."""
    old,new=load(old_schedule),load(new_schedule)
    if old['cells']!=new['cells']:raise ValueError('Cannot change query cells or order')
    allowed={'profile','interpretation_revision'}
    if {k:v for k,v in old.items() if k not in allowed}!={k:v for k,v in new.items() if k not in allowed}:
        raise ValueError('Cannot change dataset, methods or budgets')
    if load(stream_pin(old_root/'cells/schedule.json'))!=ident(old_schedule):raise ValueError('Prior journal schedule mismatch')
    existing={p.name for p in (old_root/'cells').iterdir() if p.is_dir()}
    prefix=new['cells'][:expected_count]
    if existing!={c['cell_id'] for c in prefix}:raise ValueError('Prior intents are not the complete expected prefix')
    rows=[]
    for cell in prefix:
        path=old_root/'cells'/cell['cell_id'];terminal=stream_pin(path/'terminal.json');t=load(terminal)
        if t['status'] not in ('outcome_sealed','inherited_prior_outcome') or t['cell_id']!=cell['cell_id']:
            raise ValueError('Prior terminal is not a resolved outcome')
        outcome=load(t['outcome'])
        if any(outcome[k]!=cell[k] for k in ('question_id','method','track')):raise ValueError('Prior outcome identity mismatch')
        rows.append({'cell_id':cell['cell_id'],'status':'inherited_prior_outcome','executed_in_this_campaign':False,
            'outcome':t['outcome'],'prior_terminal':terminal,
            'prior_intent':stream_pin(path/'intent.json') if (path/'intent.json').exists() else t['prior_intent'],
            'language_version_at_execution':'v1','prompt_revision_at_execution':t.get('prompt_revision_at_execution','v2')})
    ledger=new_root/'cells';ledger.mkdir(parents=True,exist_ok=False)
    write_once(ledger/'schedule.json',ident(new_schedule))
    pins=[]
    for row in rows:
        path=ledger/row['cell_id'];path.mkdir()
        pins.append(write_once(path/'terminal.json',row))
    return write_once(new_root/'inherited-outcomes.json',{'schema_version':'xgap-contribution-campaign-lineage-v2',
        'old_campaign':stream_pin(old_root/'campaign.json'),'old_schedule':old_schedule,'new_schedule':new_schedule,
        'inherited_outcomes':pins,'inherited_count':len(rows),'next_group_index':new['cells'][expected_count]['group_index'],
        'methods_rerun':0,'original_failures_and_exposures_preserved':True,'mixed_version_overall_claim':False})


def main(output,rdf_campaign_output):
    root=Path(output).resolve();campaign=Path(rdf_campaign_output).resolve()
    if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):raise ValueError('Commit before release')
    if root.exists() or campaign.exists():raise ValueError('Release destinations must be new')
    release=load({'path':str(PARENT/'receipt.json'),'sha256':RELEASE_SHA})
    old_assoc=load({'path':str(PARENT/'associations/receipt.json'),'sha256':ASSOCIATION_SHA})
    with (OLD_CAMPAIGN/'active.lock').open('r') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        root.mkdir(parents=True);associations=root/'associations';associations.mkdir()
        profiles={};prepared={};schedules={}
        for kind in ('native','rdf'):
            parent=release['profiles'][kind]
            child=derive_compact_contribution_profile(parent_path=parent['path'],parent_sha256=parent['sha256'],output=root/kind)
            validate_revision(parent,child);profiles[kind]=child
            old_pin=old_assoc['prepared'][kind];old=load(old_pin);build=load(old['input_seal'])
            if old['profile']!=ident(parent) or build['profile']!=ident(parent):raise ValueError('Original profile/store association mismatch')
            association={'language_version':'v2','parent_preparation':old_pin,'parent_input_seal':old['input_seal'],
                'profile_revision':ident(child),'new_loads':0,'offline_times_and_load_counts_inherited':True,'stores_changed':False}
            build.pop('prompt_only_association',None);build.update(profile=ident(child),interpretation_association=association)
            source_pin=write_once(associations/(kind+'-input-seal.json'),build)
            old.pop('prompt_only_association',None);old.update(profile=ident(child),input_seal=source_pin,interpretation_association=association)
            prepared[kind]=write_once(associations/(kind+'-prepared.json'),old)
            schedule=load(old_assoc['schedules'][kind])
            if schedule['profile']!=ident(parent):raise ValueError('Parent schedule mismatch')
            schedule.update(profile=ident(child),interpretation_revision={'parent_schedule':old_assoc['schedules'][kind],
                'language_version':'v2','population_order_budgets_unchanged':True})
            schedules[kind]=write_once(associations/(kind+'-nl-schedule.json'),schedule)
        summary=load(old_assoc['prepared']['summary'])
        if summary['profile']!=ident(release['profiles']['rdf']):raise ValueError('Parent summary association mismatch')
        summary.pop('prompt_only_association',None)
        summary.update(profile=ident(profiles['rdf']),interpretation_association={'parent_summary':old_assoc['prepared']['summary'],
            'language_version':'v2','new_summary_builds':0,'seals_facts_and_offline_costs_inherited':True})
        prepared['summary']=write_once(associations/'rdf-summary.json',summary)
        lineage=inherit_results(old_root=OLD_CAMPAIGN,old_schedule=old_assoc['schedules']['rdf'],new_schedule=schedules['rdf'],
            new_root=campaign,expected_count=12)
        receipt={'schema_version':'xgap-contribution-full-release-v2','source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
            'profiles':profiles,'prepared':prepared,'schedules':schedules,'rdf_lineage':lineage,
            'parent_release':stream_pin(PARENT/'receipt.json'),'parent_associations':stream_pin(PARENT/'associations/receipt.json'),
            'model_calls':0,'backend_calls':0,'load_calls':0,'summary_builds':0,'catalog_builds':0,'fit_calls':0,'reference_reads':0,
            'native_nl_unstarted':True,'baseline_algorithms_unchanged':True,'mixed_version_overall_claim':False,
            'next_gate':'First new scheduled request verifies original store/engine/summary seals; failed NL outcomes remain valid effectiveness observations.'}
        pin=write_once(root/'receipt.json',receipt)
    print(json.dumps({'receipt':pin,'rdf_campaign':str(campaign),'inherited_cells':12,'next_group':3}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True);parser.add_argument('--rdf-campaign-output',required=True)
    main(**vars(parser.parse_args()))
