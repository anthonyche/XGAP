"""Source-only, small development extracts. No answer/cost-driven sampling."""
import csv
from collections import defaultdict
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def finish(dataset,nodes,edges,*,kind,relation,measure,control,control_values,provenance,sum_meaningful,target_type=None):
    nodes=[{**n,'identity':n['id']} for n in nodes]
    nodeids={n['id'] for n in nodes}
    if len(nodeids)!=len(nodes) or any(e['from'] not in nodeids or e['to'] not in nodeids for e in edges):
        raise ValueError('Duplicate identity or missing endpoint mapping')
    cut=sorted(e['timestamp'] for e in edges)[len(edges)//2]
    early=relation+'_EARLY';late=relation+'_LATE'
    return dict(dataset=dataset,node_type=kind,target_type=target_type or kind,nodes=nodes,relations={relation:edges,
        early:[e for e in edges if e['timestamp']<=cut],late:[e for e in edges if e['timestamp']>cut]},
        scope_relations=[early,late],scope_definitions={early:{'timestamp_le':cut},late:{'timestamp_gt':cut}},
        main_relation=relation,measure=measure,control_property=control,control_values=control_values,
        sum_meaningful=sum_meaningful,provenance=provenance)


def snb(root):
    root=Path(root);receipt=json.loads((root/'receipt.json').read_text())
    for item in receipt['files']:
        if sha(root/item['path'])!=item['sha256']:raise ValueError('SNB frozen hash mismatch')
    base=root/'cypher/test-data/vanilla/dynamic'
    def rows(name):
        with (base/name).open() as f:return list(csv.reader(f,delimiter='|'))
    raw=rows('person_0_0.csv');people={r[0]:dict(zip(raw[0],r)) for r in raw[1:]}
    relation=rows('person_knows_person_0_0.csv');selected=relation[1:65]
    ids={r[i] for r in selected for i in (0,1)}
    nodes=[dict(id=i,type='Person',gender=people[i]['gender'],firstName=people[i]['firstName']) for i in sorted(ids)]
    edges=[dict(id='knows:'+str(i+1),**{'from':r[0],'to':r[1]},timestamp=int(r[2]),value=1) for i,r in enumerate(selected)]
    return finish('D1',nodes,edges,kind='Person',relation='KNOWS',measure='value',control='gender',control_values=['female','male'],
        sum_meaningful=False,provenance=dict(source='official SNB test CSV',commit=receipt['commit'],
            receipt_sha256=sha(root/'receipt.json'),selection='first 64 source rows of knows; all endpoints; same-snapshot gender',
            license='repository Apache-2.0; keep original LICENSE; no claim of current generator release'))


def finbench(archive,lock_path):
    from xgap.experiments.m15_finbench_artifacts import load_finbench_artifact_lock
    from xgap.experiments.m15_finbench_workload import load_finbench_query_data
    lock=load_finbench_artifact_lock(lock_path);data=load_finbench_query_data(archive,lock)
    selected=data.transfers[:64];ids={i for t in selected for i in (t.from_id,t.to_id)}
    nodes=[dict(id=i,type='Account',isBlocked=data.accounts[i]['isBlocked']=='true') for i in sorted(ids)]
    edges=[dict(id='transfer:'+str(j+1),**{'from':t.from_id,'to':t.to_id},amount=float(t.amount),timestamp=t.create_time)
           for j,t in enumerate(selected)]
    return finish('D3',nodes,edges,kind='Account',relation='TRANSFERRED_TO',measure='amount',control='isBlocked',control_values=[False,True],
        sum_meaningful=True,provenance=dict(source='FinBench v0.1.0 SF0.1 archive',archive_sha256=sha(archive),lock_sha256=sha(lock_path),
            selection='first 64 source transfer rows with row identities and all endpoints; same-snapshot account flags',
            license='see pinned artifact lock; no redistribution of input archive',
            query_card_admission='authored patterns only; TSR1/TCR1/TCR4/TCR12 fidelity audit still required'))


def movielens(archive):
    with ZipFile(archive) as z:
        def rows(name):return list(csv.DictReader(io.StringIO(z.read('ml-latest-small/'+name).decode('utf-8'))))
        ratings=rows('ratings.csv');movies={r['movieId']:r for r in rows('movies.csv')};links={r['movieId']:r for r in rows('links.csv')}
        license_text=z.read('ml-latest-small/README.txt')
    users=sorted({int(r['userId']) for r in ratings})[:4];counts=defaultdict(int);selected=[]
    for index,r in enumerate(ratings):
        if int(r['userId']) in users and counts[r['userId']]<16:
            selected.append((index,r));counts[r['userId']]+=1
    ids=sorted({r['movieId'] for _,r in selected})
    nodes=[dict(id='user:'+str(u),type='User') for u in users]
    nodes.extend(dict(id='movie:'+i,type='Movie',title=movies[i]['title'],isDrama='Drama' in movies[i]['genres'].split('|')) for i in ids)
    edges=[dict(id='rating-row:'+str(j+2),**{'from':'user:'+r['userId'],'to':'movie:'+r['movieId']},rating=float(r['rating']),timestamp=int(r['timestamp'])) for j,r in selected]
    result=finish('D2',nodes,edges,kind='User',target_type='Movie',relation='RATED',measure='rating',control='isDrama',control_values=[False,True],
        sum_meaningful=True,provenance=dict(source='MovieLens latest-small development only',archive_sha256=sha(archive),
            license_sha256=hashlib.sha256(license_text).hexdigest(),license='GroupLens research license; attribution required; no commercial use without permission',
            selection='first 16 ratings for each of first 4 integer user IDs; all movie endpoints',
            formal_replacement='stable MovieLens 20M, not this development dataset',
            external_mapping_status='provided IMDb/TMDB IDs retained; Wikidata mapping NOT yet verified',
            full_download_counts=dict(ratings=len(ratings),movies=len(movies),users=len({r['userId'] for r in ratings})),
            measure_semantics='SUM is total rating score, not average rating or monetary amount'))
    result['external_id_candidates']={i:links[i] for i in ids}
    return result


def verified_wikidata_mapping(links,claims):
    """Exact P345 only; never join names or quietly pick an ambiguous entity."""
    index=defaultdict(set)
    for claim in claims:
        if claim.get('property')!='P345' or not claim.get('revision'):raise ValueError('Pinned P345 claim required')
        index[claim['value']].add(claim['qid'])
    accepted=[];rejected=[]
    for movie,row in links.items():
        value='tt'+row['imdbId'].zfill(7);matches=sorted(index[value])
        if len(matches)==1:accepted.append(dict(movie_id=movie,imdb_id=value,qid=matches[0]))
        else:rejected.append(dict(movie_id=movie,reason='missing' if not matches else 'ambiguous',matches=matches))
    return accepted,rejected
