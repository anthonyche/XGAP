#!/usr/bin/env python3
"""Freeze string-key bounds from the previously loaded eight-entity source files."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from rdflib import Graph, Literal, RDF, URIRef, XSD

from xgap.experiments.equality_key_bounds import freeze_equality_key_bounds, derive_equality_profile
from xgap.experiments.m15_finbench_partition import ENTITY_PLACEMENTS, _canonical_sha256
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned
from xgap.experiments.one_shot_records import write_once


def prepare(*, parent_path, parent_sha256, output):
    at = time.perf_counter()
    parent = FrozenOneShotProfile.load(parent_path, expected_sha256=parent_sha256)
    doc, _, _, sources, backends, clients, _ = parent.materialize()
    if (doc['dataset'] != {'dataset_id':'financial-binding-tiny','version':'financial-tiny-v1'}
            or set(sources) != {'graph','control'} or len(sources['control'].replica_backend_ids) != 1):
        raise ValueError('This exporter is only the frozen eight-entity native development adapter')
    control = backends[sources['control'].replica_backend_ids[0]]
    if clients[control.backend_id]['engine'] != 'fuseki':
        raise ValueError('Expected the declared control RDF encoding')
    # Read only the pinned files actually used for this native snapshot. No source queries.
    materialization = Path(doc['offline']['materialization_root'])
    files = {name:read_pinned(materialization/name, doc['offline']['load_files'][name]['sha256'])
             for name in ('load_neo4j_batches.jsonl','control.ttl')}
    rows = {'graph':[], 'control':[]}; graph_ids = set()
    entities = {e.table_id:e for e in ENTITY_PLACEMENTS}
    for line in files['load_neo4j_batches.jsonl'].splitlines():
        batch = json.loads(line); digest = batch.pop('batch_sha256')
        if digest != _canonical_sha256(batch):
            raise ValueError('Source batch digest mismatch')
        if batch['kind'] == 'nodes':
            label = entities[batch['source_table']].neo4j_label
            for row in batch['parameters']['rows']:
                rows['graph'].append({'label':label,'properties':{'id':row['id'], **row['props']}})
                graph_ids.add(control.resource_namespace+row['props']['xgap_id'])
    if len(rows['graph']) != 8 or len(graph_ids) != 8:
        raise ValueError('Expected complete original eight-entity graph export')
    graph = Graph().parse(data=files['control.ttl'].decode(), format='turtle')
    mappings = control.backend_mapping['term_mappings'][control.backend_id]
    control_ids = set()
    for label, shape in doc['source_schema']['control']['nodes'].items():
        type_iri = URIRef(mappings[label]['representation'])
        for subject in sorted(graph.subjects(RDF.type, type_iri), key=str):
            props = {}
            for prop in shape['properties']:
                values = list(graph.objects(subject, URIRef(mappings[prop]['representation'])))
                if len(values) > 1:
                    raise ValueError('Tiny source adapter requires scalar-valued properties')
                value = values[0] if values else None
                # This source export is complete for exact strings only. Other RDF types
                # cannot equal a Python string under the frozen binding semantics.
                props[prop] = (str(value) if isinstance(value,Literal) and value.language is None
                               and value.datatype in (None,XSD.string) else None)
            rows['control'].append({'label':label,'properties':props}); control_ids.add(str(subject))
    if control_ids != graph_ids or len(rows['control']) != 8:
        raise ValueError('Control/graph complete identity coverage mismatch')
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=False)
    stats, exports = {}, {}
    for source in ('graph','control'):
        payload = b''.join((json.dumps(row,sort_keys=True,allow_nan=False)+'\n').encode() for row in rows[source])
        path = root/(source+'-string-records.jsonl'); path.write_bytes(payload)
        sha = hashlib.sha256(payload).hexdigest(); exports[source] = {'path':str(path),'sha256':sha,'bytes':len(payload)}
        stats[source] = freeze_equality_key_bounds(records_path=path,records_sha256=sha,
            source_id=source,snapshot_version=sources[source].snapshot_version,resource_namespace=control.resource_namespace,
            expected_records=8,properties={k:v['properties'] for k,v in doc['source_schema'][source]['nodes'].items()},
            output=root/(source+'-equality-key-bounds.json'))
    profile = derive_equality_profile(parent_path=parent_path,parent_sha256=parent_sha256,statistics=stats,output=root/'profile.json')
    return write_once(root/'receipt.json',{'schema_version':'xgap-tiny-equality-preparation-v1','success':True,
        'parent':{'path':str(Path(parent_path).resolve()),'sha256':parent_sha256},'exports':exports,'statistics':stats,
        'profile':profile,'input_load_files':doc['offline']['load_files'],'source_records_each':8,
        'source_export_scope':'all original tiny entity labels and schema properties, complete for exact string equality',
        'one_time_ms_before_receipt':(time.perf_counter()-at)*1000,'query_reads':0,'answer_reads':0,
        'backend_calls':0,'model_calls':0,'fit_calls':0,'catalog_builds':0,'data_loads':0})


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('parent-path','parent-sha256','output'): parser.add_argument('--'+name,required=True)
    print(json.dumps(prepare(**vars(parser.parse_args()))))
