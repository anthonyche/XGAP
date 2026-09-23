#!/usr/bin/env python3
"""Opt-in source-only relative-work profile; reuse stores and preserve old model."""
import argparse
import json
from pathlib import Path

from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.experiments.one_shot_records import write_once
from xgap.planning.relative_source_work import FrozenSourceWorkRanker


def prepare(prepared_pin,output):
    prepared=load_pin(prepared_pin)
    if not prepared.get('success'):raise ValueError('Frozen successful stores required')
    parent=prepared['profile'];profile=FrozenOneShotProfile.load(parent['path'],expected_sha256=parent['sha256'])
    doc,old,_,_,_,_,_=profile.materialize();m=load_pin(doc['offline']['materialization'])
    if not m.get('success') or m.get('schema_version')!='xgap-ch6-core-materialization-v1':
        raise ValueError('Complete authored-core source materialization required')
    if doc['offline'].get('relative_work_revision'):
        raise ValueError('Relative work revision already applied')
    seal=load_pin(prepared['input_seal'])
    if seal['profile']['sha256']!=parent['sha256']:raise ValueError('Prepared input/profile identity mismatch')
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    populations=[]
    for s in old.statistics.entries:
        # The materializer has a unique global string node ID, projects id and
        # xgap_id from it, and writes exactly two edge views per source edge.
        n=m['counts']['nodes'];e=2*m['source_original_edges'].get(s.source_id,0)
        populations.append((s.backend_id,n,e))
    ranker=FrozenSourceWorkRanker(old.statistics,tuple(populations),('id','xgap_id'),
        'source materialization:'+doc['offline']['materialization']['sha256'])
    model=write_once(root/'relative-work.json',ranker.to_dict())
    for name in ('catalog','estimator'):doc[name]['path']=str((profile.root/doc[name]['path']).resolve())
    old_model=dict(doc['estimator'])
    for mode in doc['modes'].values():
        prompt=mode['provider']['prompt'];prompt['path']=str((profile.root/prompt['path']).resolve())
    doc['estimator']={k:model[k] for k in ('path','sha256')}
    doc['profile_id']+=':relative-source-work-v1'
    doc['offline']['relative_work_revision']=dict(parent=parent,old_estimator=old_model,
        model_calls=0,backend_calls=0,fit_calls=0,query_reads=0,answer_reads=0,
        scope='Opt-in analytic source-work ranking; no latency-regression or guaranteed selection-quality claim')
    pp=write_once(root/'profile.json',doc)
    FrozenOneShotProfile.load(pp['path'],expected_sha256=pp['sha256'])
    seal['profile']=pp
    seal['store_reuse']=dict(parent=prepared_pin,reason='only estimator identity changes; source snapshots unchanged')
    sp=write_once(root/'input-seal.json',seal)
    result=write_once(root/'receipt.json',{**prepared,'profile':pp,'input_seal':sp,'store_reuse':seal['store_reuse']})
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('prepared-path','prepared-sha256','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();print(json.dumps(prepare(dict(path=a.prepared_path,sha256=a.prepared_sha256),a.output)))
