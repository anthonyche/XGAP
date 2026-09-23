#!/usr/bin/env python3
"""Freeze original TS dependencies and a common public-label RDF overlay offline.

All five methods subsequently load this same profile. Original facts/old runs
remain untouched. No baseline prompt, search or final query is changed here.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import subprocess

from check_chapter7_aruqula_fedup import AUTHOR,PYTHON,LOOKUP,CLASSPATH,REDIS,JAVA
from prepare_chapter7_public_metadata import prepare as prepare_metadata
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.ch6_formal_protocol import load_pin,pin_file
from xgap.experiments.nl_strong_release import freeze_common_profile
from xgap.experiments.one_shot_records import write_once


def prepare(*,profile_path,profile_sha256,fedx_build,output):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    parent=dict(path=profile_path,sha256=profile_sha256)
    pin=freeze_common_profile(parent,root/'base-profile.json');profile=load_pin(pin)
    if any(b['client']['engine']!='fuseki' for b in profile['backends'].values()):
        raise ValueError('Matched RDF profile required; native is not an external TS deployment')
    prepare_metadata(profile_path=pin['path'],profile_sha256=pin['sha256'],output=root/'public-metadata')
    metadata=pin_file(root/'public-metadata/metadata.nt')
    graph=profile['offline']['rdf_loads']['graph'];old=pin_file(graph['path'])
    if old['sha256']!=graph['sha256']:raise ValueError('Frozen source changed')
    # Append, do not parse an entire evaluation graph into coordinator memory.
    with (root/'graph-public.ttl').open('xb') as target:
        for source in (graph['path'],metadata['path']):
            with Path(source).open('rb') as stream:shutil.copyfileobj(stream,target,1024**2)
            target.write(b'\n')
    overlay=pin_file(root/'graph-public.ttl')
    profile['offline']['rdf_loads']['graph']={**graph,'path':overlay['path'],'sha256':overlay['sha256'],'size_bytes':overlay['bytes']}
    profile['offline'].update(shared_public_metadata=metadata,public_overlay_parent=parent,
        public_overlay_scope='English labels/schema from frozen public catalog, shared by all methods; logical business facts unchanged')
    profile['profile_id']+=':shared-labels-v1'
    published=write_once(root/'profile.json',profile)
    code='import json,sys,yaml; print(json.dumps(yaml.safe_load(open(sys.argv[1]))))'
    config={}
    for name,path in [('lookup_config',LOOKUP/'examples/config.yml'),('index_config',LOOKUP/'examples/indexing/ontology-file-indexer.yml')]:
        original=json.loads(subprocess.check_output([str(PYTHON),'-c',code,str(path)],text=True,timeout=10))
        config[name]=write_once(root/(name+'.json'),original)
    config.update(schema_version='xgap-ch6-external-runtime-v1',compatibility='https-iris-action-schema-fedx-v2',
        java=pin_file(JAVA),python=pin_file(PYTHON),redis=pin_file(REDIS),classpath=pin_file(CLASSPATH),
        lookup_jar=pin_file(LOOKUP/'lookup/target/lookup-1.0.jar'),metadata=metadata,fedx_build=pin_file(fedx_build),
        author_source=dict(path=str(AUTHOR),commit='9a3982baca03d62f7250572e300b1e4ba47727cc'),
        lookup_source=dict(path=str(LOOKUP),commit='939b3f36fefafca444cc6dff6c568c5b559f58e0'),
        model_endpoint='http://112.95.75.67:9018/v1',model_id='qwen3.8-27b',query_seconds=20,
        model_budget=asdict(SourceObservationBudget(max_calls=64,response_bytes=8*1024**2,phase_response_bytes=64*1024**2,
            timeout_seconds=70,capture_compression='gzip')),
        auxiliary_budget=asdict(SourceObservationBudget(max_calls=256,response_bytes=8*1024**2,phase_response_bytes=64*1024**2,
            timeout_seconds=20,capture_compression='gzip')))
    from ch6_external_session import verify_config
    verify_config(config,profile)
    runtime=write_once(root/'external-runtime.json',config)
    result=dict(schema_version='xgap-ch6-common-rdf-runtime-v1',profile=published,external_runtime=runtime,
        parent=parent,model_calls=0,backend_calls=0,stores_prepared=False,formal_campaign_ready=False)
    write_once(root/'receipt.json',result);print(json.dumps(result))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('profile-path','profile-sha256','fedx-build','output'):p.add_argument('--'+n,required=True)
    prepare(**vars(p.parse_args()))
