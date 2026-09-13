"""Offline v2 RDF representation: canonical facts and local metadata do not overlap."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import time

from xgap.experiments.finbench_rdf import SCHEMA, _pin
from xgap.experiments.finbench_serving_profile import verify_asset
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.planning.runtime_estimator import FrozenSourceStatistics
from xgap.planning.runtime_instance_work import FrozenInstanceWorkDeployment

AUX='https://xgap.dev/benchmark/finbench/v0.1.0/aux/control/'
VERSION='xgap-finbench-disjoint-rdf-metadata-v2'


def rewrite_control_line(line, classes):
    """Rewrite tokens in the pinned v1 serializer; keep literal payload bytes."""
    if not line.strip() or line.startswith('@prefix '):
        if line.startswith('@prefix xgapaux:'):raise ValueError('Auxiliary prefix already exists')
        return line,None
    match=re.fullmatch(r'(<[^>]+>) (.+)\n?',line.rstrip('\n'))
    if not match:raise ValueError('Unexpected control serialization')
    subject,tail=match.groups()
    if tail.startswith('rdf:type '):
        kind=re.fullmatch(r'rdf:type xgapfb:([A-Za-z0-9]+) \.',tail)
        if not kind or kind[1] not in classes:raise ValueError('Unknown control class serialization')
        return subject+' rdf:type xgapaux:'+kind[1]+' .\n','type'
    if tail.startswith('xgapfb:sourceId '):
        if not tail.endswith(' .'):raise ValueError('Unexpected sourceId serialization')
        return subject+' xgapaux:sourceId '+tail[len('xgapfb:sourceId '):]+'\n','sourceId'
    if tail.startswith('<'+SCHEMA+'xgap_id> '):
        if not tail.endswith(' .'):raise ValueError('Unexpected xgap_id serialization')
        return subject+' <'+AUX+'xgap_id> '+tail[len('<'+SCHEMA+'xgap_id> '):]+'\n','xgap_id'
    if not tail.startswith('xgapfb:') or not tail.endswith(' .'):
        raise ValueError('Unexpected control predicate serialization')
    return line,None


def publish_disjoint_profile(*, base_profile,base_sha256,output,endpoints=None):
    started=time.perf_counter();base=Path(base_profile).resolve();out=Path(output).resolve()
    original=FrozenOneShotProfile.load(base,expected_sha256=base_sha256)
    doc,model,_,_,_,_,_=original.materialize()
    if (not isinstance(model,FrozenInstanceWorkDeployment) or set(doc['backends'])!={'rdf_graph','rdf_control'}
            or 'rdf_representation' in doc['offline']):
        raise ValueError('Expected the frozen two-instance v1 RDF profile')
    if endpoints is not None and set(endpoints)!=set(doc['backends']):
        raise ValueError('Declare both independent RDF instances')
    source=Path(doc['offline']['materialization_root'])
    manifest=json.loads(read_pinned(source/'manifest.json',doc['offline']['manifest_sha256']))
    mapping=json.loads(read_pinned(source/'mapping.json',manifest['output_files']['mapping.json']['sha256']))
    for name in ('graph.ttl','control.ttl'):verify_asset(source/name,manifest['output_files'][name])
    classes={uri.removeprefix(SCHEMA) for uri in mapping['rdf_node_classes']}
    if any(SCHEMA+name not in mapping['rdf_node_classes'] for name in classes):raise ValueError('Unexpected global class vocabulary')
    out.mkdir(parents=True,exist_ok=False);counts=dict.fromkeys(('type','sourceId','xgap_id'),0)
    try:
        with (source/'control.ttl').open(encoding='utf-8') as reader,(out/'control.ttl').open('x',encoding='utf-8') as writer:
            writer.write('@prefix xgapaux: <'+AUX+'> .\n')
            for line in reader:
                rewritten,category=rewrite_control_line(line,classes);writer.write(rewritten)
                if category:counts[category]+=1
        if set(counts.values())!={manifest['control_identity_entities']}:
            raise ValueError('Control metadata counts differ from the frozen entity manifest')
        local=deepcopy(mapping)
        local['backend_mapping']['mapping_id']='finbench-disjoint-local-metadata-v2'
        local['backend_mapping']['version']='2'
        terms=local['backend_mapping']['term_mappings']['rdf_control']
        for term in terms.values():
            if term['kind']=='class':term['representation']=AUX+term['representation'].removeprefix(SCHEMA)
        for field in ('id','xgap_id'):
            terms[field]['representation']=AUX+('sourceId' if field=='id' else 'xgap_id')
        mapping_pin=write_once(out/'mapping.json',local)
        loads={name:{**_pin(path),'path':str(path.resolve())} for name,path in
            (('graph',source/'graph.ttl'),('control',out/'control.ttl'))}
        derivative=write_once(out/'representation.json',{'schema_version':VERSION,'success':True,
            'parent_profile':{'path':str(base),'sha256':base_sha256},'original_materialization_sha256':doc['offline']['manifest_sha256'],
            'loads':loads,'mapping':mapping_pin,'metadata_rewritten':counts,'auxiliary_namespace':AUX,
            'canonical_global_mapping_unchanged':True,'canonical_graph_bytes_unchanged':True,
            'financial_literal_bytes_unchanged':True,'baseline_query_changes':0,'fit_calls':0,
            'entity_count':manifest['entity_count'],'relationship_count':manifest['relationship_count'],
            'equivalence_scope':'canonical projection of disjoint union equals v1 set union; auxiliary aliases explicitly declared'})
        entries=tuple(replace(s,snapshot_version=loads[s.source_id]['sha256'],
            mean_row_bytes=loads['control']['size_bytes']/s.total_rows if s.source_id=='control' else s.mean_row_bytes,
            provenance_ref=derivative['sha256']) for s in model.statistics.entries)
        stats=FrozenSourceStatistics('finbench-disjoint-rdf-statistics-v2',derivative['sha256'],entries)
        deployment=FrozenInstanceWorkDeployment('finbench-disjoint-rdf-transfer-v2',model.trained_model,stats,
            model.reference_backends,'offline-disjoint-metadata:'+derivative['sha256'])
        deployment.save(out/'estimator.json')
        for name,spec in doc['backends'].items():
            spec['semantic']['backend_mapping']=local['backend_mapping']
            spec['semantic']['rdf_node_classes']=[AUX+c for c in sorted(classes)] if name=='rdf_control' else mapping['rdf_node_classes']
            if endpoints is not None:spec['client']['url']=endpoints[name]
        doc['sources']={s.source_id:{'version':s.snapshot_version,'replicas':[s.backend_id]} for s in stats.entries}
        doc['catalog']['path']=str((base.parent/doc['catalog']['path']).resolve())
        for mode in doc['modes'].values():
            mode['provider']['prompt']['path']=str((base.parent/mode['provider']['prompt']['path']).resolve())
        doc['profile_id']+=':disjoint-metadata-v2'
        doc['estimator']={'path':'estimator.json','sha256':hashlib.sha256((out/'estimator.json').read_bytes()).hexdigest()}
        doc['offline']={**doc['offline'],'rdf_representation':derivative,
            'rdf_loads':loads,'source_representation':'disjoint canonical RDF facts plus visible local metadata aliases',
            'parent_v1_profile':{'path':str(base),'sha256':base_sha256},
            'scope':'offline metadata derivative only; no data queries, model, refit or catalog rebuild',
            'auxiliary_metadata_shared_with_all_methods':True,'formal_campaign_ready':False}
        pin=write_once(out/'profile.json',doc)
        FrozenOneShotProfile.load(pin['path'],expected_sha256=pin['sha256'])
        write_once(out/'publication.json',{'success':True,'profile':pin,'representation':derivative,
            'offline_ms':(time.perf_counter()-started)*1000,'model_calls':0,'backend_calls':0,'query_reads':0,
            'reference_reads':0,'fit_calls':0,'catalog_builds':0,'graph_copies':0,'formal_campaign_ready':False})
        return pin
    except Exception as error:
        write_once(out/'failure.json',{'success':False,'error_type':type(error).__name__,'error':str(error)})
        raise
