#!/usr/bin/env python3
"""Freeze distinct-binding-key estimates without reading queries or answers."""
import argparse
from dataclasses import replace
import json
from pathlib import Path

from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.experiments.one_shot_records import write_once
from xgap.planning.relative_source_work import FrozenSourceWorkRanker


def revise(prepared_pin,output):
    prepared=load_pin(prepared_pin);parent=prepared['profile']
    profile=FrozenOneShotProfile.load(parent['path'],expected_sha256=parent['sha256'])
    doc,old,*_=profile.materialize();seal=load_pin(prepared['input_seal'])
    if not prepared.get('success') or seal['profile']!=parent:
        raise ValueError('Successful frozen stores and matching profile seal required')
    if not isinstance(old,FrozenSourceWorkRanker) or old.distinct_binding_keys:
        raise ValueError('An unrevised frozen source-work model is required')
    model=replace(old,distinct_binding_keys=True)
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    model_pin=write_once(root/'relative-work-v3.json',model.to_dict())
    old_model=dict(doc['estimator']);old_model['path']=str((profile.root/old_model['path']).resolve())
    doc['catalog']['path']=str((profile.root/doc['catalog']['path']).resolve())
    for mode in doc['modes'].values():
        prompt=mode['provider']['prompt'];prompt['path']=str((profile.root/prompt['path']).resolve())
    doc['estimator']={k:model_pin[k] for k in ('path','sha256')};doc['profile_id']+=':binding-ndv-v3'
    doc['offline']['binding_key_revision']=dict(parent=parent,old_estimator=old_model,
        query_reads=0,answer_reads=0,model_calls=0,backend_calls=0,fit_calls=0,
        scope='Column NDV proxies through typed lineage; estimates, not resource certificates; source statistics and weights unchanged')
    pp=write_once(root/'profile.json',doc);FrozenOneShotProfile.load(pp['path'],expected_sha256=pp['sha256'])
    seal['profile']=pp;seal['store_reuse']=dict(parent=prepared_pin,reason='only estimator identity changes; stores and snapshots unchanged')
    sp=write_once(root/'input-seal.json',seal)
    return write_once(root/'receipt.json',{**prepared,'profile':pp,'input_seal':sp,'store_reuse':seal['store_reuse']})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('prepared-path','prepared-sha256','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();print(json.dumps(revise(dict(path=a.prepared_path,sha256=a.prepared_sha256),a.output)))
