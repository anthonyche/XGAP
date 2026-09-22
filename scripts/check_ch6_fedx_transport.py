"""Tiny GET/form/raw-SPARQL gate for unchanged FedX; zero LLM calls."""
import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request,urlopen

from rdflib import Graph
from check_common_rdf_trial import JAVA,FUSEKI
from check_chapter7_aruqula_fedup import public_source_loads
from prepare_chapter7_public_metadata import prepare
from run_external_federation_tiny import Processes,ready
from xgap.experiments.campaign_source_observer import CampaignSourceObserver,SourceObservationBudget
from xgap.experiments.evidence_store import file_pin
from xgap.experiments.common_row_score import sparql_values
from xgap.experiments.row_normalization import normalize_rows
from xgap.experiments.finbench_one_shot_population import normalization
from xgap.experiments.external_federation import deadline,score_sparql
from xgap.experiments.financial_nl_profile import INPUT_ROOT
from xgap.experiments.finbench_rdf import FAMILIES,fixed_semantics_query
from xgap.experiments.m15_native_services import LoopbackPortReservations
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.process_guard import _group_sample


def check(build,profile_path,profile_sha256,output,query_manifest=None,query_manifest_sha256=None,disable_optional_bind=False):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    processes=Processes(root);ports=None;observer=None
    receipt=dict(success=False,model_calls=0,cases=[],external_algorithm_changes=0)
    try:
        with deadline(180):
            compiled=json.loads(Path(build).read_text());jar=compiled['jar']
            if file_pin(jar['path'])!=jar or not compiled['external_entries_byte_identical']:raise ValueError('Build changed')
            profile=json.loads(read_pinned(profile_path,profile_sha256))
            if Path(profile['offline']['materialization_root'])!=INPUT_ROOT:raise ValueError('Tiny snapshot only')
            old=Path('/Users/anthonyche/xgap-data/unified-external-admission-20260921-v5/federation-observations/0000-intent.json')
            parameters=dict(person_id='1',start_time='2020-01-01 00:00:00.000',end_time='2020-01-04 00:00:00.000')
            queries={'author-values':json.loads(old.read_text())['query'],'cross-source':fixed_semantics_query(FAMILIES[0],parameters)}
            replay_pin=None;originals={}
            if query_manifest:
                replay=json.loads(read_pinned(query_manifest,query_manifest_sha256))
                if replay.get('schema_version')!='xgap-author-query-replay-v1' or not 1<=len(replay['queries'])<=4:
                    raise ValueError('Expected a bounded pinned replay manifest')
                queries={}
                for item in replay['queries']:
                    if not item['name'].isidentifier() or item['name'] in queries:
                        raise ValueError('Invalid replay query name')
                    queries[item['name']]=read_pinned(item['path'],item['sha256']).decode()
                    if item.get('original_path'):
                        originals[item['name']]=read_pinned(item['original_path'],item['original_sha256']).decode()
                if originals and set(originals)!=set(queries):
                    raise ValueError('Equivalence replay needs an original for every query')
                replay_pin=file_pin(query_manifest)
            receipt['inputs']=write_once(root/'input-seal.json',dict(build=file_pin(build),jar=jar,failed_author_query=file_pin(old),
                profile=dict(path=profile_path,sha256=profile_sha256),queries=queries,original_queries=originals,
                replay_manifest=replay_pin,
                model_calls_cap=0,federation_requests_cap=3*len(queries)+1,wall_seconds=180,
                fedx_disable_optional_bind=disable_optional_bind))
            prepare(profile_path=profile_path,profile_sha256=profile_sha256,output=root/'metadata')
            loads=public_source_loads(profile,root/'metadata/metadata.nt',root)
            receipt['public_sources']=[file_pin(p) for p in loads]
            oracle=Graph()
            for load in loads:oracle.parse(load,format='turtle')
            # Captured author tools have no evaluator answer contract. Their
            # replay verifies transport/JSON only; keep answer scoring separate.
            # In particular do not rewrite COALESCE() for RDFLib compatibility.
            expected={} if query_manifest else {
                name:json.loads(oracle.query(query).serialize(format='json')) for name,query in queries.items()}
            ports=LoopbackPortReservations.acquire(4 if originals else 3);routes={}
            for i,load in enumerate(loads):
                port=ports.ports[i];ports.release(i);state=root/f'source-{i}';state.mkdir()
                process=processes.start(f'source-{i}',[str(FUSEKI/'fuseki-server'),'--localhost','--port',str(port),'--file',str(load),'/ds'],
                    cwd=FUSEKI,env={'JAVA':JAVA,'FUSEKI_HOME':str(FUSEKI),'FUSEKI_BASE':str(state),'JVM_ARGS':'-Xms64m -Xmx256m'})
                ready(process,port);routes[f'/{i}/sparql']=f'http://127.0.0.1:{port}/ds/sparql'
            if originals:
                # A separate Jena reference evaluates the untouched author syntax
                # on the union of exactly these fixtures. Never used by the method.
                original_load=root/'reference.ttl';oracle.serialize(original_load,format='turtle')
                state=root/'reference-source';state.mkdir();port=ports.ports[3];ports.release(3)
                process=processes.start('reference',[str(FUSEKI/'fuseki-server'),'--localhost','--port',str(port),
                    '--file',str(original_load),'/ds'],cwd=FUSEKI,env={'JAVA':JAVA,'FUSEKI_HOME':str(FUSEKI),
                    'FUSEKI_BASE':str(state),'JVM_ARGS':'-Xms64m -Xmx256m'})
                ready(process,port)
                for name,query in originals.items():
                    req=Request(f'http://127.0.0.1:{port}/ds/sparql',data=urlencode({'query':query}).encode(),
                        headers={'Content-Type':'application/x-www-form-urlencoded','Accept':'application/sparql-results+json'})
                    with urlopen(req,timeout=15) as response:expected[name]=json.load(response)
                    write_once(root/(name+'-original-answer.json'),expected[name])
                receipt['original_reference_calls']=len(originals)
            observer=CampaignSourceObserver(routes,root/'source-observations',budget=SourceObservationBudget(
                max_calls=128,response_bytes=2**20,phase_response_bytes=8*2**20,timeout_seconds=10,capture_compression='gzip'))
            observer.set_phase('protocol')
            port=ports.ports[2];ports.release(2)
            host=processes.start('fedx',[JAVA,'-Xms64m','-Xmx512m','-Dxgap.fedx.debugErrors=true',
                *(['-Dxgap.fedx.disableOptionalBind=true'] if disable_optional_bind else []),
                '-jar',jar['path'],str(port),'10',*[observer.base_url+p for p in routes]])
            ready(host,port);endpoint=f'http://127.0.0.1:{port}/sparql'
            for name,query in queries.items():
                encoded=urlencode({'query':query,'format':'json'})
                for transport in ('GET','form','raw'):
                    req=(Request(endpoint+'?'+encoded) if transport=='GET' else Request(endpoint,
                        data=(encoded if transport=='form' else query).encode(),headers={'Content-Type':
                        'application/x-www-form-urlencoded' if transport=='form' else 'application/sparql-query'}))
                    with urlopen(req,timeout=15) as response:answer=json.load(response)
                    write_once(root/(name+'-'+transport+'-answer.json'),answer)
                    if originals:
                        same=score_sparql(answer,expected[name],ordered=False)['exact']
                    elif query_manifest:
                        same=(isinstance(answer.get('head',{}).get('vars'),list) and
                              isinstance(answer.get('results',{}).get('bindings'),list))
                    elif name=='cross-source':
                        # Use the pre-existing shared financial answer contract:
                        # decimal 66 and double 66.0 denote the same amount.
                        spec=normalization(FAMILIES[0])
                        same=normalize_rows(sparql_values(answer,spec),spec)==normalize_rows(sparql_values(expected[name],spec),spec)
                    else:same=score_sparql(answer,expected[name],ordered=False)['exact']
                    receipt['cases'].append(dict(query=name,transport=transport,success=same,rows=len(answer['results']['bindings']),
                        validation=('original_Jena_vs_adapted_FedX' if originals else
                                    'transport_and_result_format' if query_manifest else 'independent_reference')))
                    if not same:raise ValueError('Independent RDF terms differ')
            try:
                urlopen(Request(endpoint,data=b'INSERT DATA { <urn:x> <urn:p> <urn:y> }',headers={'Content-Type':'application/sparql-query'}),timeout=15)
                raise ValueError('UPDATE accepted')
            except HTTPError as error:receipt['update_rejected']=error.code==500
            receipt['observations']=observer.seal_phase('protocol')
            receipt['success']=receipt['update_rejected'] and len(receipt['cases'])==3*len(queries)
    except (Exception,KeyboardInterrupt) as error:receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        receipt['processes']=processes.close()
        if observer:observer.close()
        if ports:ports.close()
        receipt['all_owned_closed']=all(p['returncode'] is not None and not _group_sample(p['pid']) for p in receipt['processes']) and (observer is None or not observer.thread.is_alive() and observer.inflight==0)
        receipt['success']=receipt['success'] and receipt['all_owned_closed']
        pin=write_once(root/'receipt.json',receipt)
    print(json.dumps(dict(receipt=pin,success=receipt['success'],cases=receipt['cases'],error=receipt.get('error'))))
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('build','profile-path','profile-sha256','output'):p.add_argument('--'+name,required=True)
    p.add_argument('--query-manifest')
    p.add_argument('--query-manifest-sha256')
    p.add_argument('--disable-optional-bind',action='store_true')
    raise SystemExit(check(**vars(p.parse_args())))
