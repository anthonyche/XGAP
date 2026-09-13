#!/usr/bin/env python3
"""Offline business-ID bounds from pinned same-facts RDF source files.

Consumes only the existing FinBench serializer's finite line grammar, not
arbitrary RDF. All entities/IDs are scanned; no workload or answer is read.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import time

from xgap.experiments.equality_key_bounds import freeze_equality_key_bounds, derive_equality_profile
from xgap.experiments.m15_finbench_partition import ENTITY_PLACEMENTS
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned
from xgap.experiments.one_shot_records import write_once


def extract_ids(lines, *, term_mappings, namespace, expected_counts):
    classes={term_mappings[label]['representation']:label for label in expected_counts}
    id_property=term_mappings['id']['representation']
    prefixes={}; records={}
    def expand(term):
        if term.startswith('<') and term.endswith('>'):return term[1:-1]
        prefix,local=term.split(':',1)
        if prefix not in prefixes:raise ValueError('Undeclared source serializer prefix')
        return prefixes[prefix]+local
    def add_type(subject,term):
        label=classes.get(expand(term))
        if label is None:return False
        if not subject.startswith('<'+namespace) or not subject.endswith('>') or subject in records:
            raise ValueError('Duplicate/mismatched source entity identity')
        records[subject]={'label':label,'properties':{}};return True
    def add_id(subject,tail):
        if subject not in records or records[subject]['properties'] or not tail.endswith(' .'):
            raise ValueError('ID must occur once after its declared entity type')
        value=json.loads(tail[:-2])
        if type(value) is not str:raise ValueError('Source ID must be an exact string')
        records[subject]['properties']['id']=value
    for raw in lines:
        line=raw.decode().strip() if isinstance(raw,bytes) else raw.strip()
        if not line:continue
        if line.startswith('@prefix '):
            match=re.fullmatch(r'@prefix ([A-Za-z_][\w-]*): <([^>]+)> \.',line)
            if not match or match[1] in prefixes:raise ValueError('Changed source prefix grammar')
            prefixes[match[1]]=match[2];continue
        subject,predicate,tail=line.split(' ',2)
        if predicate=='a':
            term,remainder=tail.split(' ; ',1)
            if add_type(subject,term):
                prop,value=remainder.split(' ',1)
                if expand(prop)!=id_property:raise ValueError('Entity header lacks mapped source ID')
                add_id(subject,value)
        elif expand(predicate)=='http://www.w3.org/1999/02/22-rdf-syntax-ns#type':
            if not tail.endswith(' .'):raise ValueError('Changed source type grammar')
            add_type(subject,tail[:-2])
        elif expand(predicate)==id_property:
            add_id(subject,tail)
    if (dict(Counter(row['label'] for row in records.values()))!={k:v for k,v in expected_counts.items() if v}
            or any(set(row['properties'])!={'id'} for row in records.values())):
        raise ValueError('Complete source entity/ID counts differ from frozen summary')
    return list(records.values())


def prepare(*, parent_path, parent_sha256, output):
    at=time.perf_counter();profile=FrozenOneShotProfile.load(parent_path,expected_sha256=parent_sha256)
    doc,_,_,sources,backends,clients,_=profile.materialize()
    if (set(sources)!={'graph','control'} or any(len(s.replica_backend_ids)!=1 for s in sources.values())
            or any(spec['engine']!='fuseki' for spec in clients.values()) or 'rdf_loads' not in doc['offline']):
        raise ValueError('Expected frozen independent RDF instances with explicit source file pins')
    summary_pin=doc['offline']['source_summary']
    summary=json.loads(read_pinned(summary_pin['path'],summary_pin['sha256']))
    counts={e.neo4j_label:summary['table_rows'].get(e.table_id,0) for e in ENTITY_PLACEMENTS}
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    statistics={};exports={}
    for source in ('graph','control'):
        declared=sources[source];backend=backends[declared.replica_backend_ids[0]]
        pin=doc['offline']['rdf_loads'][source]
        if pin['sha256']!=declared.snapshot_version:raise ValueError('Source file and snapshot differ')
        digest=hashlib.sha256();size=0
        def verified_lines():
            nonlocal size
            with Path(pin['path']).open('rb') as stream:
                for line in stream:
                    digest.update(line);size+=len(line);yield line
            if digest.hexdigest()!=pin['sha256'] or size!=pin['size_bytes']:
                raise ValueError('Complete source file hash/size mismatch')
        properties={label:['id'] for label in doc['source_schema'][source]['nodes']}
        rows=extract_ids(verified_lines(),term_mappings=backend.backend_mapping['term_mappings'][backend.backend_id],
            namespace=backend.resource_namespace,expected_counts={k:counts[k] for k in properties})
        path=root/(source+'-id-records.jsonl');out_digest=hashlib.sha256();out_size=0
        with path.open('xb') as stream:
            for row in rows:
                data=(json.dumps(row,sort_keys=True,allow_nan=False)+'\n').encode()
                stream.write(data);out_digest.update(data);out_size+=len(data)
        exports[source]={'path':str(path),'sha256':out_digest.hexdigest(),'bytes':out_size,'records':len(rows)}
        statistics[source]=freeze_equality_key_bounds(records_path=path,records_sha256=out_digest.hexdigest(),
            source_id=source,snapshot_version=declared.snapshot_version,resource_namespace=backend.resource_namespace,
            expected_records=sum(counts[k] for k in properties),properties=properties,output=root/(source+'-statistics.json'))
        del rows
    child=derive_equality_profile(parent_path=parent_path,parent_sha256=parent_sha256,statistics=statistics,output=root/'profile.json')
    return write_once(root/'receipt.json',{'schema_version':'xgap-finbench-id-bounds-v1','success':True,
        'parent':{'path':str(Path(parent_path).resolve()),'sha256':parent_sha256},'profile':child,
        'source_summary':summary_pin,'source_files':doc['offline']['rdf_loads'],'exports':exports,'statistics':statistics,
        'one_time_ms_before_receipt':(time.perf_counter()-at)*1000,
        'scope':'complete per-label business-ID multiplicities only; other properties retain policy limits',
        'query_reads':0,'answer_reads':0,'backend_calls':0,'model_calls':0,'fit_calls':0,'data_loads':0,
        'catalog_builds':0,'baseline_calls':0,'old_profiles_preserved':True})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('parent-path','parent-sha256','output'):parser.add_argument('--'+name,required=True)
    print(json.dumps(prepare(**vars(parser.parse_args()))))
