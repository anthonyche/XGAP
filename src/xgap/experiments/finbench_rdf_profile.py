"""Derive a two-RDF-instance profile from frozen source-only financial inputs."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time

from xgap.compilers.features import default_profile
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.finbench_serving_profile import verify_asset
from xgap.planning.runtime_estimator import FrozenSourceStatistics
from xgap.planning.runtime_instance_work import FrozenInstanceWorkDeployment
from xgap.planning.runtime_work_deployment import FrozenWorkDeployment
from xgap.planning.runtime_work_estimator import frozen_estimator_from_dict


def publish_rdf_profile(*, base_profile, base_sha256, output, endpoints, datasets=None):
    started=time.perf_counter();base=Path(base_profile).resolve();root=base.parent
    doc=json.loads(read_pinned(base,base_sha256))
    # Full profile reconstruction validates frozen input identities; no service is touched.
    FrozenOneShotProfile.load(base,expected_sha256=base_sha256)
    model=frozen_estimator_from_dict(json.loads(read_pinned(root/doc['estimator']['path'],doc['estimator']['sha256'])))
    if not isinstance(model,FrozenWorkDeployment) or set(doc['sources'])!={'graph','control'}:
        raise ValueError('Expected the source-only native financial deployment')
    materialization=Path(doc['offline']['materialization_root'])
    manifest=json.loads(read_pinned(materialization/'manifest.json',doc['offline']['manifest_sha256']))
    mapping=json.loads(read_pinned(materialization/'mapping.json',manifest['output_files']['mapping.json']['sha256']))
    for name in ('graph.ttl','control.ttl'):
        verify_asset(materialization/name,manifest['output_files'][name])
    if set(endpoints)!={'rdf_graph','rdf_control'}:raise ValueError('Declare both independent RDF instances')
    datasets=datasets or {'rdf_graph':'graph','rdf_control':'control'}
    if set(datasets)!=set(endpoints):raise ValueError('RDF instance dataset names differ')
    stats=FrozenSourceStatistics('finbench-rdf-instance-statistics-v1',doc['offline']['manifest_sha256'],tuple(
        replace(s,backend_id='rdf_'+s.source_id,
            snapshot_version=manifest['output_files'][s.source_id+'.ttl']['sha256'])
        for s in model.statistics.entries))
    deployed=FrozenInstanceWorkDeployment('finbench-rdf-instance-transfer-v1',model.trained_model,stats,
        tuple((s.backend_id,'fuseki') for s in stats.entries),'source-only-rdf-profile:'+base_sha256)
    out=Path(output);out.mkdir(parents=True,exist_ok=False)
    deployed.save(out/'estimator.json')
    cap=default_profile('fuseki')
    doc['backends']={instance:{'semantic':{'resource_namespace':mapping['resource_namespace'],
        'identity_property':'xgap_id',**{k:mapping[k] for k in ('backend_mapping','rdf_edge_encoding','rdf_node_classes')},
        'profile':replace(cap,backend_id=instance).to_dict()},'client':{'engine':'fuseki','url':url,
            'database':datasets[instance],'timeout_seconds':20,'auth':None}} for instance,url in endpoints.items()}
    doc['sources']={s.source_id:{'version':s.snapshot_version,'replicas':[s.backend_id]} for s in stats.entries}
    doc['catalog']['path']=str((root/doc['catalog']['path']).resolve())
    for mode in doc['modes'].values():
        mode['provider']['prompt']['path']=str((root/mode['provider']['prompt']['path']).resolve())
    doc['profile_id']+=':two-rdf-instances-v1'
    doc['estimator']={'path':'estimator.json','sha256':hashlib.sha256((out/'estimator.json').read_bytes()).hexdigest()}
    doc['offline']={**doc['offline'],'derived_from_native_profile':{'path':str(base),'sha256':base_sha256},
        'source_representation':'same-facts RDF graph/control instances; no gold source assignment',
        'feature_projection':'same-engine instance work summed into unchanged Fuseki reference weights',
        'scope':'offline RDF profile derivation; no data rebuild, query, answer, fit or service call',
        'serving_services_started':False,'formal_campaign_ready':False}
    pin=write_once(out/'profile.json',doc)
    FrozenOneShotProfile.load(out/'profile.json',expected_sha256=pin['sha256'])
    write_once(out/'publication.json',{'success':True,'profile':pin,'offline_ms':(time.perf_counter()-started)*1000,
        'model_calls':0,'backend_calls':0,'fit_calls':0,'query_reads':0,'answer_reads':0,'formal_campaign_ready':False})
    return pin
