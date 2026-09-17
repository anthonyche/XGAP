"""One ordinary NL request, either XGAP mode or the shared external frontend."""
import json
from pathlib import Path
import time

from xgap.agent.shared_external_frontend import prepare_external_query
from xgap.experiments.external_federation import query_once
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned
from xgap.experiments.one_shot_records import run_record, write_once, read_record_outcome
from xgap.experiments.one_shot_toy import _DurableRecordingProvider
from xgap.experiments.practical_methods import PRACTICAL_METHODS, FIXED_INFORMATION_METHODS
from xgap.agent.nl_strong_question import NL_STRONG_METHODS, NL_USER_METHODS, NL_FAMILY_METHODS

SCHEMA='xgap-nl-method-worker-v1'
METHODS=('xgap-precision','xgap-performance','fedx','fedup',*PRACTICAL_METHODS,*NL_STRONG_METHODS,*NL_USER_METHODS,*NL_FAMILY_METHODS)


def run_nl(*,request_path,request_sha256,profile_path,profile_sha256,method,output,endpoint=None,seconds=180,
           oracle_path=None,oracle_sha256=None,user_max_calls=9,intent_family_path=None,intent_family_sha256=None):
    if method not in NL_FAMILY_METHODS and (intent_family_path is not None or intent_family_sha256 is not None):
        raise ValueError('Public intent contract is only allowed on the declared finite-family method')
    if method not in (*NL_USER_METHODS,*NL_FAMILY_METHODS) and (oracle_path is not None or oracle_sha256 is not None):
        raise ValueError('Private oracle is only allowed on the declared user-interaction method')
    if method in (*NL_STRONG_METHODS,*NL_USER_METHODS,*NL_FAMILY_METHODS):
        from xgap.experiments.nl_strong_worker import run_nl_strong
        return run_nl_strong(request_path=request_path,request_sha256=request_sha256,profile_path=profile_path,
            profile_sha256=profile_sha256,method=method,output=output,
            oracle_path=oracle_path,oracle_sha256=oracle_sha256,user_max_calls=user_max_calls,
            intent_family_path=intent_family_path,intent_family_sha256=intent_family_sha256)
    if method in FIXED_INFORMATION_METHODS:
        from xgap.experiments.fixed_information_worker import run_fixed_information
        return run_fixed_information(request_path=request_path,request_sha256=request_sha256,profile_path=profile_path,
            profile_sha256=profile_sha256,method=method,output=output,endpoint=endpoint,seconds=seconds)
    if method in PRACTICAL_METHODS:
        from xgap.experiments.practical_method_worker import run_practical
        return run_practical(request_path=request_path,request_sha256=request_sha256,profile_path=profile_path,
            profile_sha256=profile_sha256,method=method,output=output,endpoint=endpoint,seconds=seconds)
    root=Path(output);root.mkdir(parents=True,exist_ok=False);started=time.perf_counter()
    r={'schema_version':SCHEMA,'method':method,'track':'natural_language','success':False,'status':'preparing',
        'request_sha256':request_sha256,'profile_sha256':profile_sha256,'result':None,
        'model_calls':0,'input_tokens':0,'output_tokens':0,'fit_calls':0,'probe_calls':0,
        'automatic_retries':0,'top_level_attempts':0,'alternative_executions':0}
    active=False
    try:
        if method not in METHODS:raise ValueError('Unknown NL method')
        request_raw=json.loads(read_pinned(request_path,request_sha256))
        r.update({k:request_raw[k] for k in ('question_id','population','exposure')})
        if method.startswith('xgap-'):
            active=True
            child=run_record(profile_path=profile_path,profile_sha256=profile_sha256,request_path=request_path,
                request_sha256=request_sha256,mode=method.removeprefix('xgap-'),output=root/'core',operation='execute')
            active=False
            # Usage is already observed even if the subsequent answer handoff fails.
            r.update(dataset=child.get('dataset'),success=child['success'],status=child['status'],
                model_calls=child['model_network_calls'],input_tokens=child['input_tokens'],output_tokens=child['output_tokens'],
                top_level_attempts=child['final_plan_executions'],backend_calls=child['backend_network_calls'],
                planning_ms=child.get('planning_ms'),execution_ms=child.get('execution_ms'))
            core=read_record_outcome(child) or {}
            r.update(planning_ms=core.get('planning_ms',r['planning_ms']),execution_ms=core.get('execution_ms',r['execution_ms']),
                interpretation_ms=core.get('interpretation_ms',(core.get('interpretation') or {}).get('elapsed_ms')),
                grounding_ms=core.get('grounding_ms'))
            answer={'answer_format':'json_rows','answer':core.get('answer_rows') if child['success'] else None}
            scope={k:core[k] for k in ('answer_semantics','approximation') if k in core}
            answer.update(scope)
            r.update(scope)
        else:
            profile=FrozenOneShotProfile.load(profile_path,expected_sha256=profile_sha256)
            materialized=profile.materialize();doc,_,_,sources,_,specs,modes=materialized
            if any(s['engine']!='fuseki' for s in specs.values()):raise ValueError('External common NL needs the shared RDF profile')
            request=profile.request(request_raw,'precision',materialized);r['dataset']=doc['dataset']
            policy,provider=modes['precision']
            budget=provider.token_guard.check(provider.build_request_payload(request),call_kind='generation')
            write_once(root/'preflight.json',{'profile_sha256':profile_sha256,'request_sha256':request_sha256,
                'provider':provider.config.safe_dict(),'budget':budget,'policy':policy.to_dict()})
            if not budget['passed']:raise ValueError('Shared NL request exceeds frozen model budget')
            representation=doc['offline']['rdf_representation']
            metadata=json.loads(read_pinned(representation['path'],representation['sha256']))
            mapping=json.loads(read_pinned(metadata['mapping']['path'],metadata['mapping']['sha256']))
            recorder=_DurableRecordingProvider(provider,root/'interpretation.json');active=True
            information_profile=doc['offline'].get('nl_strong_frontend',{}).get('profile_id','precision-k3-v1')
            front=prepare_external_query(request,recorder,policy=policy,catalog_root=doc['catalog']['path'],
                catalog_hash=doc['catalog']['bundle_hash'],sources=sources,mapping=mapping,
                information_profile=information_profile)
            active=False;write_once(root/'frontend.json',front)
            r.update(model_calls=front['model_calls'],input_tokens=front['input_tokens'],output_tokens=front['output_tokens'],
                status=front['status'],frontend_ms=front['frontend_ms'],compilation_ms=front['compilation_ms'],
                grounding_ms=front['grounding_ms'],interpretation_ms=(front['interpretation'] or {}).get('elapsed_ms'),
                planning_ms=None,backend_calls=None,usage_complete=front['usage_complete'])
            answer={'answer_format':'sparql_json','answer':None}
            if front['success']:
                remaining=seconds-(time.perf_counter()-started)
                if remaining<=0:raise TimeoutError('NL budget exhausted before final external query')
                write_once(root/'execution_intent.json',{'maximum_final_queries':1,'artifact':front['artifact']})
                r['top_level_attempts']=1
                raw=query_once(endpoint,front['artifact']['text'],seconds=min(120,remaining),output=root/'response.json')
                r.update(execution_ms=raw['client_wall_ms'],success=raw['status']=='returned' and raw.get('http_status')==200,
                    status='returned' if raw['status']=='returned' and raw.get('http_status')==200 else 'external_failed')
                if r['success']:answer['answer']=json.loads(raw['body_utf8'])
        r['result']=write_once(root/'answer.json',answer)
    except Exception as error:
        r.update(success=False,status='worker_failed',error_type=type(error).__name__,error=str(error))
        if active:r.update(model_calls=None,input_tokens=None,output_tokens=None,usage_complete=False)
    finally:
        r['worker_ms_before_receipt']=(time.perf_counter()-started)*1000;write_once(root/'receipt.json',r)
    return r
