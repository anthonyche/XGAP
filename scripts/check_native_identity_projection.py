#!/usr/bin/env python3
"""Four tiny projection primitives and one affected, estimated final native slice."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import subprocess

from native_store_session import NativeStoreSession
from prepare_rdf_tdb import REPO, stream_pin
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.common_method_trial import run_fixed_trial
from xgap.experiments.common_row_score import score_trial
from xgap.experiments.external_federation import deadline
from xgap.experiments.finbench_rdf import local_identity, RESOURCE
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, native_clients, read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.physical_strategies import _bound_match_artifact
from xgap.runtime.row_operations import normalize_node_bindings
from xgap.runtime.semantic_compiler import compile_semantic_source
from xgap.semantic.program import SemanticGraphProgram

PARENT=Path('/Users/anthonyche/xgap-data/native-campaign-boundary-20260913-v2')
PREPARED_SHA='8f3c88515f52f8526faa4f9963a381ad1df1af7bf419f9bbdce0ec5e11648051'
REQUEST_SHA='77d2edcc63a3e965926f1122340b9ead926c56895dc0a3fed62aa6450f193660'
REFERENCE_SHA='ef5cd2566327035938554fad5853b428669c8c5dfe8e3a318c85135f9895876d'


def fragment(backend,edge=False):
    params=({'edge':{'label':'TRANSFERRED_TO','properties':{}},'entity_field':'edge_id',
             'source_field':'source_id','target_field':'target_id',
             'properties':{'amount':'amount','timestamp':'createTime','absent':'personName'}} if edge else
            {'node':{'label':'XGAPFinBenchAccount','properties':{}},'entity_field':'node_id',
             'properties':{'business_id':'id','absent':'personName'}})
    op=SemanticGraphProgram.from_dict({'program_id':'projection-primitive','operators':[
        {'operator_id':'m','kind':'match','input_ids':[],'input_kinds':[],'output_kind':'binding_set','parameters':params}],
        'roots':['m']}).operators[0]
    f=compile_semantic_source(op,backend)
    return QueryArtifact.from_dict(f.nodes[0].parameters['artifact']),f.nodes[1].parameters


def canonical(rows):
    return sorted(json.dumps(row,sort_keys=True,allow_nan=False) for row in rows)


def main(output):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    receipt={'schema_version':'xgap-native-identity-projection-gate-v1','success':False,'model_calls':0,
        'data_load_calls':0,'fit_calls':0,'catalog_builds':0,'automatic_retries':0,
        'primitive_checks':[],'maximum_primitive_queries':4,'maximum_final_plans':1,
        'primitive_outcomes_used_for_planning':False,'paper_result':False}
    session=None
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):raise ValueError('Commit before native gate')
        receipt['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
        prepared=json.loads(read_pinned(PARENT/'prepared.json',PREPARED_SHA))
        build=json.loads(read_pinned(prepared['input_seal']['path'],prepared['input_seal']['sha256']))
        source=build['sources']['load_neo4j_batches.jsonl']
        if stream_pin(source['path'])!=source:raise ValueError('Frozen tiny facts changed')
        # Expected primitive fields come directly from the frozen fixture facts,
        # independently of generated native query results.
        edge_rows=[]
        for line in Path(source['path']).read_text().splitlines():
            b=json.loads(line)
            if b.get('source_table')!='account_transfer_account':continue
            for row in b.get('parameters',{}).get('rows',[]):
                edge_rows.append({'edge_id':RESOURCE+row['props']['xgap_id'],
                    'source_id':RESOURCE+local_identity('account',row['fromId']),
                    'target_id':RESOURCE+local_identity('account',row['toId']),
                    'amount':row['props']['amount'],'timestamp':row['props']['createTime'],'absent':None})
        if len(edge_rows)!=8:raise ValueError('Expected the frozen eight-edge transfer fixture')
        session=NativeStoreSession(root=root/'session',prepared_path=PARENT/'prepared.json',prepared_sha256=PREPARED_SHA,
            budget=SourceObservationBudget(max_calls=16,request_bytes=1024**2,phase_request_bytes=2*1024**2,
                response_bytes=1024**2,phase_response_bytes=4*1024**2,timeout_seconds=15),discard_serving_copies=True)
        with deadline(120):session.start()
        receipt['ready']=session.ready_pin
        _,_,_,_,backends,specs,_=FrozenOneShotProfile.load(session.profile['path'],expected_sha256=session.profile['sha256']).materialize()
        client=native_clients(specs)['neo4j'];backend=backends['neo4j']
        node,np=fragment(backend);edge,ep=fragment(backend,True)
        bound,key=_bound_match_artifact(edge,backend,max_bindings=16,max_binding_bytes=4096,identity_column='source')
        bound=replace(bound,parameters={**bound.parameters,key:[RESOURCE+local_identity('account','1')]})
        invalid,ip=fragment(replace(backend,identity_property='missing_identity'))
        expected_nodes=[{'node_id':RESOURCE+local_identity('account',str(i)),'business_id':str(i),'absent':None} for i in range(1,5)]
        cases=[('node',node,np,expected_nodes),('edge',edge,ep,edge_rows),
               ('bound-source',bound,ep,[r for r in edge_rows if r['source_id']==RESOURCE+local_identity('account','1')]),
               ('missing-identity',invalid,ip,None)]
        for name,artifact,parameters,expected in cases:
            case=root/name;case.mkdir();session.observer.set_phase('projection:'+name)
            write_once(case/'intent.json',{'artifact':artifact.to_dict(),'normalization':parameters,
                'expected_normalization_failure':expected is None,'attempts':1})
            raw=client.execute(artifact);write_once(case/'native.json',raw.to_dict())
            error=None;normalized=None
            if not raw.success:raise RuntimeError('Primitive native execution failed: '+str(raw.error))
            try:normalized=normalize_node_bindings(raw.rows,parameters)
            except (KeyError,ValueError) as e:error=type(e).__name__+': '+str(e)
            projection=all(set(row[col])=={parameters['identity_property']}
                for row in raw.rows for col in parameters.get('identity_fields',{'entity':'unused'}))
            success=projection and (error is not None if expected is None else error is None and canonical(normalized)==canonical(expected))
            observed=session.observer.seal_phase(session.observer.phase)
            record={'name':name,'success':success,'raw_rows':len(raw.rows),'normalized':normalized,
                    'normalization_error':error,'identity_only_maps':projection,'source_observations':observed}
            pin=write_once(case/'receipt.json',record);session.observer.release_phase(session.observer.phase,pin)
            receipt['primitive_checks'].append({'name':name,'success':success,'receipt':pin,
                'rows':len(raw.rows),'response_bytes':observed['response_body_bytes']})
            if not success:raise ValueError('Primitive projection equivalence failed: '+name)
        # Independent affected full slice: no primitive result/cost enters it.
        run=run_fixed_trial(request_path=PARENT/'request.json',request_sha256=REQUEST_SHA,method='xgap-native',
            output=root/'execution',owned_services=session.owned,observer=session.observer,
            profile_path=session.profile['path'],profile_sha256=session.profile['sha256'])
        score=score_trial(run['receipt']['path'],receipt_sha256=run['receipt']['sha256'],reference_path=PARENT/'reference.json',
            reference_sha256=REFERENCE_SHA,output=root/'score.json')
        receipt.update(run=run['receipt'],score=score,success=run['success'] and score['answer_em']==1,
            final_source_calls=run['source_observations']['requests'],final_response_bytes=run['source_observations']['response_body_bytes'],
            final_online_ms=run['timing']['total_online_ms'])
    except Exception as error:receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        if session:
            receipt['closure']=session.close()
            receipt['success'] &= receipt['closure']['owned_groups_drained'] and receipt['closure']['observer_stopped']
        original=json.loads(read_pinned(PARENT/'prepared.json',PREPARED_SHA));unchanged=True
        for store in original['stores'].values():
            seal=json.loads(read_pinned(store['seal']['path'],store['seal']['sha256']))
            unchanged &= all(stream_pin(p['path'])==p for p in seal['files'])
        receipt['frozen_stores_unchanged']=unchanged;receipt['success'] &= unchanged
        pin=write_once(root/'receipt.json',receipt)
    print(json.dumps({'success':receipt['success'],'receipt':pin,'error':receipt.get('error'),
        'final_response_bytes':receipt.get('final_response_bytes'),'final_online_ms':receipt.get('final_online_ms')}))
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
    raise SystemExit(main(**vars(p.parse_args())))
