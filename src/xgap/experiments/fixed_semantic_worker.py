"""One fixed-semantics method invocation; no reference or NL/model shortcut."""
import json
from pathlib import Path
from collections.abc import Mapping
import threading
import time

from xgap.experiments.external_federation import query_kind, query_once
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, native_clients, read_pinned
from xgap.experiments.one_shot_records import write_once, CapturingClient
from xgap.experiments.schema_source_routing import source_assignments
from xgap.runtime.one_shot_planning import prepare_one_shot_domain
from xgap.runtime.scheduler import FederatedScheduler
from xgap.semantic.program import SemanticGraphProgram
from xgap.semantic.parameter_contract import validate_program_parameters
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin

REQUEST_SCHEMA='xgap-fixed-semantics-request-v1'


def run_fixed(*, request_path,request_sha256,method,output,profile_path=None,profile_sha256=None,endpoint=None,seconds=120):
    root=Path(output);root.mkdir(parents=True,exist_ok=False);started=time.perf_counter()
    receipt={'schema_version':'xgap-fixed-semantics-worker-v1','success':False,'status':'preparing',
        'method':method,'track':'fixed_semantics','request_sha256':request_sha256,'result':None,
        'model_calls':0,'fit_calls':0,'probe_calls':0,'top_level_attempts':0,'alternative_executions':0}
    try:
        q=json.loads(read_pinned(request_path,request_sha256))
        if set(q)!={'schema_version','question_id','dataset','population','exposure','program','sparql'} or q['schema_version']!=REQUEST_SCHEMA:
            raise ValueError('Fixed input contains unexpected fields or source assignments')
        receipt.update({k:q[k] for k in ('question_id','dataset','population','exposure')})
        if method=='xgap-rdf':
            profile=FrozenOneShotProfile.load(profile_path,expected_sha256=profile_sha256)
            doc,model,_,sources,backends,specs,modes=profile.materialize()
            if doc['dataset']!=q['dataset'] or any(s['engine']!='fuseki' for s in specs.values()):
                raise ValueError('Fixed RDF method requires the same declared RDF dataset')
            validate_program_parameters(q['program']);program=SemanticGraphProgram.from_dict(q['program'])
            at=time.perf_counter();slots,routing=source_assignments(program,doc['source_schema'],sources)
            candidates,domain=prepare_one_shot_domain(program,operator_sources=slots,sources=sources,backends=backends,policy=modes['performance'][0])
            predictions=[(c,model.predict(c.plan)) for c in candidates]
            available=[(c,p) for c,p in predictions if p.estimated_ms is not None]
            if not available:raise ValueError('No available frozen estimate')
            selected,prediction=min(available,key=lambda v:(v[1].estimated_ms,v[0].strategy_id))
            receipt['planning_ms']=(time.perf_counter()-at)*1000
            write_once(root/'selection.json',{'routing':routing,'domain':domain,'selected_strategy':selected.strategy_id,
                'selected_plan':selected.plan.to_dict(),'predictions':[{'strategy':c.strategy_id,'prediction':p.to_dict()} for c,p in predictions]})
            records=[];lock=threading.Lock();registry=BackendPluginRegistry()
            for name,client in native_clients(specs).items():
                registry.register(NativeBackendPlugin(name,CapturingClient(client,root,records,lock)))
            write_once(root/'execution_intent.json',{'plan_id':selected.plan.plan_id,'maximum_final_executions':1})
            receipt['top_level_attempts']=1;at=time.perf_counter()
            result=FederatedScheduler(BackendInvokeTool(registry)).execute(selected.plan)
            receipt.update(execution_ms=(time.perf_counter()-at)*1000,backend_calls=result.total_remote_calls,
                success=result.success,status='returned' if result.success else 'execution_failed')
            write_once(root/'execution.json',result.to_dict())
            answer={'answer_format':'json_rows','answer':list(result.final_rows) if result.success else None}
        elif method in ('fedup','fedx'):
            if not isinstance(q['sparql'],str) or query_kind(q['sparql'])!='SELECT':raise ValueError('Expected unresolved read-only SELECT')
            from rdflib.plugins.sparql.parser import parseQuery
            from pyparsing import ParseResults
            pending=[parseQuery(q['sparql'])]
            while pending:
                part=pending.pop()
                if isinstance(part,(list,tuple,ParseResults)):
                    pending.extend(part)
                elif isinstance(part,Mapping):
                    if getattr(part,'name',None)=='ServiceGraphPattern':
                        raise ValueError('Fixed global input must leave source selection unresolved')
                    pending.extend(part.values())
            receipt['top_level_attempts']=1
            raw=query_once(endpoint,q['sparql'],seconds=seconds,output=root/'response.json')
            receipt.update(success=raw['status']=='returned' and raw.get('http_status')==200,
                status='returned' if raw['status']=='returned' and raw.get('http_status')==200 else 'external_failed',
                external_client_ms=raw['client_wall_ms'],backend_calls=None,planning_ms=None)
            answer={'answer_format':'sparql_json','answer':json.loads(raw['body_utf8']) if receipt['success'] else None}
        else:raise ValueError('Unknown fixed-semantics method')
        receipt['result']=write_once(root/'answer.json',answer)
    except Exception as error:
        receipt.update(success=False,status='worker_failed',error_type=type(error).__name__,error=str(error))
    finally:
        receipt['worker_ms_before_receipt']=(time.perf_counter()-started)*1000
        write_once(root/'receipt.json',receipt)
    return receipt
