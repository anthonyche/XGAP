#!/usr/bin/env python3
"""Bind a verified transfer to Linux paths and check tiny RDF services, no LLM.

This is a portability admission, not a baseline quality experiment. The optional
service check executes one predetermined cross-source query against tiny data.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
from zipfile import ZipFile

from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.evidence_store import file_pin
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.experiments.one_shot_records import write_once

REPO=Path(__file__).resolve().parents[1]


def rebase_profile(profile, inputs):
    """Change live file locations only; never rewrite historical provenance."""
    profile=deepcopy(profile);inputs=Path(inputs).resolve()
    def bind(path):
        path=(inputs/path).resolve()
        if not path.is_relative_to(inputs):raise ValueError('Live input escapes verified package')
        if not path.exists():raise ValueError('Live input missing')
        return str(path)
    for key in ('catalog','estimator'):profile[key]['path']=bind(profile[key]['path'])
    for item in profile['offline']['rdf_loads'].values():item['path']=bind(item['path'])
    for mode in profile['modes'].values():
        prompt=mode['provider']['prompt'];prompt['path']=bind(prompt['path'])
    metadata=profile['offline']['shared_public_metadata'];metadata['path']=bind(metadata['path'])
    return profile


def publish(bootstrap,output,*,service_check=False):
    if not os.environ.get('SLURM_JOB_ID'):raise ValueError('CPU scheduler allocation required')
    if os.environ.get('SLURM_JOB_GPUS') or os.environ.get('SLURM_GPUS_ON_NODE') not in (None,'','0'):
        raise ValueError('No GPU allocation allowed')
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    state=json.loads(Path(bootstrap).read_text());host=Path(bootstrap).resolve().parent
    if not state['success']:raise ValueError('Successful Linux bootstrap required')
    inputs=host/'inputs';manifest=json.loads((inputs/'manifest.json').read_text())
    result=dict(schema_version='xgap-ch6-linux-runtime-admission-v1',success=False,
        bootstrap=file_pin(bootstrap),source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        job_id=os.environ['SLURM_JOB_ID'],model_calls=0,formal_campaign_ready=False,
        deployment='rdf',baseline_quality_evaluated=False)
    source=external=None
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=REPO):raise ValueError('Commit publisher before use')
        for name,expected in manifest['files'].items():
            actual=file_pin(inputs/name)
            if any(actual[k]!=expected[k] for k in ('sha256','bytes')):raise ValueError('Transfer file changed: '+name)
        for name in ('java','python','python_environment','redis','classpath','packages'):
            if file_pin(state[name]['path'])!=state[name]:raise ValueError('Linux installation changed: '+name)
        with ZipFile(inputs/'fedx-original.jar') as before,ZipFile(inputs/'fedx-protocol.jar') as after:
            names={n for n in before.namelist() if not n.startswith('org/xgap/')}
            if (names!={n for n in after.namelist() if not n.startswith('org/xgap/')}
                    or any(before.read(n)!=after.read(n) for n in names)):
                raise ValueError('External FedX engine entries changed')
        build=write_once(root/'fedx-build.json',dict(success=True,base=file_pin(inputs/'fedx-original.jar'),
            jar=file_pin(inputs/'fedx-protocol.jar'),external_entries_byte_identical=True,
            external_algorithm_changes=0,transport_parent=manifest['source_fedx_build']))
        doc=rebase_profile(json.loads((inputs/'portable-profile.json').read_text()),inputs)
        doc['offline']['linux_transfer']=dict(manifest=file_pin(inputs/'manifest.json'),bootstrap=file_pin(bootstrap),
            source_profile=manifest['source_profile'],live_paths_rebound=True,logical_facts_changed=False)
        profile=write_once(root/'profile.json',doc)
        FrozenOneShotProfile.load(profile['path'],expected_sha256=profile['sha256'])
        import yaml
        cfg={}
        lookup=Path(state['lookup_source']['path'])
        for name,relative in [('lookup_config','examples/config.yml'),('index_config','examples/indexing/ontology-file-indexer.yml')]:
            cfg[name]=write_once(root/(name+'.json'),yaml.safe_load((lookup/relative).read_text()))
        cfg.update(schema_version='xgap-ch6-external-runtime-v1',compatibility='https-iris-action-schema-fedx-v2',
            **{k:state[k] for k in ('java','python','python_command','python_environment','redis','classpath','author_source','lookup_source')},
            lookup_jar=file_pin(lookup/'lookup/target/lookup-1.0.jar'),metadata=doc['offline']['shared_public_metadata'],
            fedx_build=build,model_endpoint='http://112.95.75.67:9018/v1',model_id='qwen3.8-27b',query_seconds=20,
            model_budget=asdict(SourceObservationBudget(max_calls=64,response_bytes=8*1024**2,phase_response_bytes=64*1024**2,
                timeout_seconds=70,capture_compression='gzip')),
            auxiliary_budget=asdict(SourceObservationBudget(max_calls=256,response_bytes=8*1024**2,phase_response_bytes=64*1024**2,
                timeout_seconds=20,capture_compression='gzip')))
        from ch6_external_session import ExternalSession,verify_config
        verify_config(cfg,doc);runtime=write_once(root/'external-runtime.json',cfg)
        result.update(profile=profile,external_runtime=runtime,services_admitted=False)
        if service_check:
            from prepare_rdf_tdb import prepare
            from rdf_tdb_session import RdfTdbSession
            from xgap.experiments.external_federation import query_once,score_sparql
            from rdflib import Graph
            if prepare(profile=profile['path'],profile_sha256=profile['sha256'],output=root/'stores',
                       java=cfg['java']['path'],fuseki_jar=inputs/'fuseki-server.jar',max_store_bytes=1024**3):
                raise ValueError('Tiny store preparation failed')
            prepared=file_pin(root/'stores/receipt.json');result['prepared_stores']=prepared
            source=RdfTdbSession(root=root/'source-session',prepared_path=prepared['path'],prepared_sha256=prepared['sha256'],
                budget=SourceObservationBudget(max_calls=128,response_bytes=4*1024**2,phase_response_bytes=16*1024**2,
                                              timeout_seconds=20,capture_compression='gzip')).start()
            external=ExternalSession(root=root/'external-session',config_pin=runtime,source_session=source).start()
            # Control holds isBlocked; graph holds nickname. The fixed query must
            # join both stores. No model/candidate/gold is involved in this check.
            query=('PREFIX s: <https://xgap.dev/benchmark/finbench/v0.1.0/schema/> '
                   'SELECT DISTINCT ?s WHERE {?s s:isBlocked ?blocked; s:nickname ?nickname} ORDER BY ?s')
            union=Graph()
            for load in doc['offline']['rdf_loads'].values():union.parse(load['path'],format='turtle')
            expected=json.loads(union.query(query).serialize(format='json'))
            if not expected['results']['bindings']:raise ValueError('Gate requires a nonempty cross-source reference')
            reference=write_once(root/'transport-reference.json',expected)
            source.observer.set_phase('linux-portability-cross-source')
            actual=query_once(external.observers['federation'].base_url+'/sparql',query,seconds=25,output=root/'transport-query.json')
            if actual.get('http_status')!=200:raise ValueError('FedX cross-source transport failed')
            score=score_sparql(json.loads(actual['body_utf8']),expected,ordered=True)
            result.update(transport_score=score,transport_reference=reference,
                source_observations=source.observer.snapshot('linux-portability-cross-source'))
            if not score['exact']:raise ValueError('Cross-source transport result differs')
            result['services_admitted']=True
        result['success']=True
    except Exception as error:result.update(error_type=type(error).__name__,error=str(error))
    finally:
        if external:result['external_closed']=external.close()
        if source:result['source_closed']=source.close()
        for name in ('external_closed','source_closed'):
            if name in result and not all(result[name].get(k) for k in ('owned_processes_terminal','owned_groups_drained','observer_stopped')):
                result['success']=False
        write_once(root/'receipt.json',result)
    print(json.dumps(dict(success=result['success'],receipt=str(root/'receipt.json'),error=result.get('error'))))
    return 0 if result['success'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('bootstrap','output'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--service-check',action='store_true')
    raise SystemExit(publish(**vars(parser.parse_args())))
