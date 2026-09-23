#!/usr/bin/env python3
"""Freeze source-only endpoint degree moments; never read queries or answers."""
import argparse
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import time

from xgap.experiments.ch6_fact_index import read_index,verify,pin
from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.experiments.one_shot_records import write_once
from xgap.planning.relative_source_work import FrozenSourceWorkRanker


def build(index_pin,output):
    started=time.monotonic();meta=load_pin(index_pin);verify(meta['database'])
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    labels=[meta['core']['relation']+suffix for suffix in ('','_EARLY','_LATE')]
    counts={(label,role):Counter() for label in labels for role in ('source','target')}
    rows=0
    with read_index(meta['database']['path']) as db:
        for source,target,stamp in db.execute('SELECT src,dst,ts FROM edges'):
            for label in (labels[0],labels[1 if stamp<=meta['scope_cut_ms'] else 2]):
                counts[label,'source'][source]+=1;counts[label,'target'][target]+=1
            rows+=1
    entries=[]
    for (label,role),counter in sorted(counts.items()):
        entries.append(dict(label=label,endpoint=role,rows=sum(counter.values()),ndv=len(counter),
                            squared_sum=sum(v*v for v in counter.values()),maximum=max(counter.values(),default=0)))
    return write_once(root/'receipt.json',dict(schema_version='xgap-source-endpoint-degrees-v1',success=True,
        index=index_pin,dataset=meta['dataset'],scope_cut_ms=meta['scope_cut_ms'],original_rows=rows,entries=entries,
        query_reads=0,answer_reads=0,model_calls=0,backend_calls=0,offline_seconds=time.monotonic()-started))


def revise(prepared_pin,degree_pin,output):
    prepared=load_pin(prepared_pin);degrees=load_pin(degree_pin);parent=prepared['profile']
    profile=FrozenOneShotProfile.load(parent['path'],expected_sha256=parent['sha256'])
    doc,old,*_=profile.materialize();material=load_pin(doc['offline']['materialization'])
    if (not prepared.get('success') or not isinstance(old,FrozenSourceWorkRanker) or old.endpoint_degrees
            or not degrees.get('success') or degrees.get('schema_version')!='xgap-source-endpoint-degrees-v1'
            or material['index_receipt']['sha256']!=degrees['index']['sha256']
            or material['scale']!='1' or material['source_count']!=2
            or material['counts']['original_edges']!=degrees['original_rows']):
        raise ValueError('Degree revision requires the same complete base-scale two-source facts')
    entries=[]
    for source in old.statistics.entries:
        if source.source_id=='graph':
            entries.extend((source.backend_id,e['label'],e['endpoint'],e['rows'],e['ndv'],e['squared_sum'],e['maximum']) for e in degrees['entries'])
    if not entries:raise ValueError('No matching complete graph backend')
    model=replace(old,endpoint_degrees=tuple(entries),preparation_ref='endpoint statistics:'+degree_pin['sha256'])
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    model_pin=write_once(root/'relative-work-v2.json',model.to_dict())
    doc['catalog']['path']=str((profile.root/doc['catalog']['path']).resolve())
    for mode in doc['modes'].values():
        prompt=mode['provider']['prompt'];prompt['path']=str((profile.root/prompt['path']).resolve())
    doc['estimator']={k:model_pin[k] for k in ('path','sha256')};doc['profile_id']+=':endpoint-degree-v2'
    doc['offline']['endpoint_degree_revision']=dict(parent=parent,statistics=degree_pin,query_reads=0,answer_reads=0,
        online_probe_calls=0,fit_calls=0,cost_unit='declared work; mean/size-biased degree is an estimate, not a resource certificate')
    pp=write_once(root/'profile.json',doc);FrozenOneShotProfile.load(pp['path'],expected_sha256=pp['sha256'])
    seal=load_pin(prepared['input_seal'])
    if seal['profile']!=parent:raise ValueError('Input seal profile mismatch')
    seal['profile']=pp;seal['store_reuse']=dict(parent=prepared_pin,reason='offline estimator-only degree revision')
    sp=write_once(root/'input-seal.json',seal)
    return write_once(root/'receipt.json',{**prepared,'profile':pp,'input_seal':sp,'store_reuse':seal['store_reuse']})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--index',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();print(json.dumps(build(pin(a.index),a.output)))
