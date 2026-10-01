#!/usr/bin/env python3
"""Freeze source-derived candidates before domain admission or method outcomes.

Verifies a Git blob against the pinned source tree, then extracts a declared
contiguous source range. Rejections and previously exposed structures remain in
the ledger. This is provenance intake, not an executable evaluation workload.
"""
import argparse,hashlib,json
from collections import Counter
from pathlib import Path

from xgap.experiments.ch6_structures import extract


def root_tree_hash(entries):
    roots=[r for r in entries if '/' not in r['path']]
    ordered=sorted(roots,key=lambda r:(r['path']+('/' if r['type']=='tree' else '')).encode())
    payload=b''.join((format(int(r['mode'],8),'o')+' '+r['path']).encode()+b'\0'+bytes.fromhex(r['sha']) for r in ordered)
    return hashlib.sha1(b'tree '+str(len(payload)).encode()+b'\0'+payload).hexdigest()


def source_bytes(path,tree,commit):
    raw=Path(path).read_bytes();t=json.loads(Path(tree).read_text());c=json.loads(Path(commit).read_text())
    # A stored recursive API response may name the queried commit rather than
    # the resolved root tree. Reconstruct the Git tree bytes instead of trusting
    # that display field as the tree object's identity.
    if t.get('truncated') or root_tree_hash(t['tree'])!=c['tree']:
        raise ValueError('Incomplete or mismatched source tree')
    parents=[r for r in t['tree'] if r['path']=='dataset' and r['type']=='tree']
    subtree=[{**r,'path':r['path'][8:]} for r in t['tree'] if r['path'].startswith('dataset/')]
    if len(parents)!=1 or root_tree_hash(subtree)!=parents[0]['sha']:
        raise ValueError('Benchmark subtree does not match its parent Git tree')
    matches=[r for r in t['tree'] if r['path']=='dataset/test.json' and r['type']=='blob']
    blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    if len(matches)!=1 or matches[0]['sha']!=blob or matches[0]['size']!=len(raw):
        raise ValueError('Raw benchmark bytes do not match the pinned Git tree')
    return raw,dict(commit=c['commit'],sha256=hashlib.sha256(raw).hexdigest(),git_blob=blob,
        repository='https://github.com/AskNowQA/LC-QuAD2.0',source_path='dataset/test.json')


def intake(source,tree,commit,previous_registry,output,*,start=128,count=512):
    if type(start) is not int or start<128 or type(count) is not int or not 1<=count<=512:
        raise ValueError('Explicit bounded, non-development source range required')
    raw,version=source_bytes(source,tree,commit);rows=json.loads(raw)
    if start+count>len(rows):raise ValueError('Source range exceeds the frozen file')
    previous=[json.loads(s) for s in Path(previous_registry).read_text().splitlines()]
    if any(r['source_version']['sha256']!=version['sha256'] or r['source_version']['commit']!=version['commit'] for r in previous):
        raise ValueError('Previous exposure registry is from another source')
    exposed={r['structure_hash'] for r in previous if r.get('structure_hash')}
    root=Path(output);root.mkdir(exist_ok=False,parents=True);counts=Counter();families=set();representatives={}
    with (root/'source-candidates.jsonl').open('x') as target:
        for index in range(start,start+count):
            row=rows[index]
            for field in ('sparql_wikidata','sparql_dbpedia18'):
                if field not in row:continue
                record=extract(row,source_version=version,field=field)
                status='source_rejected' if record['status']=='rejected' else (
                    'previously_exposed_source_structure' if record['structure_hash'] in exposed else 'pending_domain_admission')
                record.update(source_row_index=index,source_intake_status=status,
                    formal_evaluation_ready=False,cross_ir_development_overlap_checked=False,
                    domain_compiler_admission='not_attempted',independent_reference_admission='not_attempted')
                counts[status]+=1
                if status=='pending_domain_admission':
                    families.add(record['structure_hash'])
                    representatives.setdefault(record['structure_hash'],dict(source_row_index=index,uid=record['uid'],
                        source_field=field,raw_query_sha256=record['raw_query_sha256'],categories=record['structure_categories']))
                target.write(json.dumps(record,ensure_ascii=False)+'\n')
    receipt=dict(schema_version='xgap-ch6-benchmark-source-intake-v1',source=version,
        source_range=dict(start=start,count=count),selection='fixed contiguous published source range before method outcomes',
        previous_registry_sha256=hashlib.sha256(Path(previous_registry).read_bytes()).hexdigest(),
        exposed_source_structures=len(exposed),counts=dict(counts),new_source_structures=len(families),
        source_representatives=representatives,domain_queries_generated=0,model_calls=0,backend_calls=0,
        formal_evaluation_ready=False,remaining=['Typed domain lowering with explicit semantic changes',
            'Same compact-IR structure normalization against ALL previously exposed domain families',
            'Independent reference and backend interface admission',
            'Freeze final template split, instance sampling and sample size before method outcomes'])
    (root/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k not in ('source_representatives','remaining')},ensure_ascii=False))
    return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','tree','commit','previous-registry','output'):p.add_argument('--'+name,required=True)
    p.add_argument('--start',type=int,default=128);p.add_argument('--count',type=int,default=512)
    intake(**vars(p.parse_args()))
