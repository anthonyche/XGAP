#!/usr/bin/env python3
"""CPU-only offline core profiles/stores, with one-attempt immutable receipts."""
import argparse
import json
import os
from pathlib import Path

from xgap.experiments.ch6_fact_index import pin,write
from xgap.experiments.ch6_core_profile import publish
from xgap.experiments.m15_native_artifacts import load_native_runtime_lock,fetch_native_artifact
from xgap.experiments.m15_native_runtime import stage_native_artifact
from prepare_rdf_tdb import prepare as prepare_rdf
from prepare_native_stores import prepare as prepare_native


def prepare(materialization,runtime_admission,bootstrap,output,cache,*,deployment='both',large=False):
    if not os.environ.get('SLURM_JOB_ID'):raise ValueError('Explicit CPU allocation required')
    if os.environ.get('SLURM_JOB_GPUS'):raise ValueError('No GPU allocation required or accepted')
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    admission=json.loads(Path(runtime_admission).read_text());runtime=json.loads(Path(bootstrap).read_text())
    if not admission['success'] or not runtime['success']:raise ValueError('Linux prerequisites not admitted')
    parent=admission['profile'];java=runtime['java']['path']
    jar=Path(bootstrap).parent/'inputs/fuseki-server.jar'
    result=dict(success=False,model_calls=0,benchmark_query_calls=0,automatic_retries=0,
                materialization=pin(materialization),job_id=os.environ['SLURM_JOB_ID'],deployments={},formal_campaign_started=False)
    try:
        for kind in (('rdf','native') if deployment=='both' else (deployment,)):
            d=root/kind;d.mkdir()
            profile=publish(materialization,parent['path'],parent['sha256'],d/'profile',deployment=kind)
            args=dict(profile=profile['path'],profile_sha256=profile['sha256'],output=d/'stores',java=java,fuseki_jar=jar,
                      max_store_bytes=(128 if large else 10)*1024**3,load_seconds=3600 if large else 900)
            if kind=='rdf':
                config=json.loads(Path(admission['external_runtime']['path']).read_text())
                doc=json.loads(Path(profile['path']).read_text());config['metadata']=doc['offline']['shared_public_metadata']
                from ch6_external_session import verify_config
                verify_config(config,doc);write(d/'external-runtime.json',config)
                code=prepare_rdf(**args,heap_mib=4096 if large else 2048)
            else:
                artifact=load_native_runtime_lock(Path(__file__).resolve().parents[1]/'services/m15-native-runtime.lock.json').artifact('neo4j-community')
                fetched=fetch_native_artifact(artifact,cache,timeout_seconds=120)
                write(d/'neo4j-fetch.json',fetched.to_dict())
                if not fetched.success:raise ValueError('Pinned Neo4j fetch failed')
                engine=d/'runtime';engine.mkdir()
                staged=stage_native_artifact(fetched.destination,artifact,engine)
                write(d/'neo4j-staging.json',staged.to_dict())
                code=prepare_native(**args,neo4j_root=staged.runtime_path,bulk_import=True)
            result['deployments'][kind]=dict(success=code==0,profile=profile,prepared=pin(d/'stores/receipt.json'))
            if code:raise ValueError(kind+' offline loading failed; retained without retries')
        result['success']=True
    except Exception as error:result.update(error_type=type(error).__name__,error=str(error))
    write(root/'receipt.json',result);print(json.dumps(result))
    return 0 if result['success'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('materialization','runtime-admission','bootstrap','output','cache'):p.add_argument('--'+name,required=True)
    p.add_argument('--deployment',choices=['both','rdf','native'],default='both');p.add_argument('--large',action='store_true')
    raise SystemExit(prepare(**vars(p.parse_args())))
