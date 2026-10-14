"""One-shot scheduler using adaptive row stores and fused local pipelines.

Only successful root answers are materialized for the public API. Native clients
stream HTTP row arrays; third-party list-only adapters retain explicit fallback
telemetry. Blocking states adapt between bounded memory and exact disk storage.
"""
from dataclasses import replace
import time
from xgap.backends.request_control import RequestControl
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.scheduler import FederatedScheduler,_encoded_size
from xgap.runtime.contracts import RuntimeNodeKind as K,RuntimeNodeStatus as S,RuntimeNodeResult
from xgap.runtime.spill_rows import SpillWorkspace,DiskRows
from xgap.runtime.spill_operators import operate
from xgap.runtime.retrieval_budget import budget_from_artifact,observe_budget


def stream_executor(client):
    method=getattr(client,'execute_stream',None)
    if not callable(method):return None
    # An adapter that overrides execute may redirect, authorize or normalize its
    # calls. Never silently bypass that contract via an inherited native stream.
    if 'execute' in getattr(client,'__dict__',{}) and 'execute_stream' not in client.__dict__:return None
    mro=type(client).__mro__
    stream_owner=next((i for i,c in enumerate(mro) if 'execute_stream' in c.__dict__),len(mro))
    execute_owner=next((i for i,c in enumerate(mro) if 'execute' in c.__dict__),len(mro))
    return None if execute_owner<stream_owner else method


class StreamingScheduler(FederatedScheduler):
    def __init__(self,backend_tool,*,clients,limits=None,pipeline=True):
        super().__init__(backend_tool,retention='roots',stream_topk=False,limits=limits)
        self.clients=clients;self.pipeline=pipeline

    def execute(self,plan,*,goal_id='federated-query',initial_results=None):
        if initial_results:raise ValueError('Streaming execution does not accept resumable rows')
        started=time.perf_counter();limit=self._limits
        control=RequestControl(None if limit.dispatch_timeout_s is None else started+limit.dispatch_timeout_s,limit.max_response_bytes)
        control.database_cancellation=True
        with SpillWorkspace(control,limit.max_spill_bytes,limit.intermediate_memory_bytes) as workspace:
            runner=_StreamRun(self._backend_tool,clients=self.clients,limits=limit,pipeline=self.pipeline)
            runner.workspace=workspace;runner.control=control
            result=FederatedScheduler.execute(runner,plan,goal_id=goal_id)
            try:roots={k:tuple(v) for k,v in result.root_rows.items()}
            except TimeoutError:
                control.cancel();roots={}
                result=replace(result,success=False,root_rows={},node_results=tuple(
                    replace(n,status=S.ERROR,rows=(),output_bytes=0,error='Final answer materialization exceeded deadline')
                    if n.node_id in result.root_rows else n for n in result.node_results),
                    retention={**result.retention,'execution_stop_reason':'dispatch_timeout'})
            nodes=tuple(replace(n,rows=roots[n.node_id]) if n.node_id in roots else n for n in result.node_results)
            return replace(result,root_rows=roots,node_results=nodes,elapsed_ms=(time.perf_counter()-started)*1000,
                retention={**result.retention,'streaming_profile':'adaptive-row-pipelines-v2',
                    'peak_intermediate_accounted_bytes':workspace.peak_memory_bytes,
                    'intermediate_memory_bytes':limit.intermediate_memory_bytes,'spilled_stores':workspace.spilled_stores,
                    'peak_spill_bytes':workspace.peak_bytes,'max_spill_bytes':limit.max_spill_bytes,
                    'backend_cancellation':control.receipts,'database_control_http_calls':control.lifecycle_calls,
                    'native_http_response_bytes_including_discarded':control.response_bytes,
                    'stream_scope':'adaptive SQLite pages and fused local row pipelines; native envelopes validated before use; root answers materialized; not a process RSS cap'})


class _StreamRun(StreamingScheduler):
    def _make_control(self,deadline,limits):return self.control

    def _execution_pipelines(self,plan):
        from xgap.runtime.row_pipeline import islands
        return islands(plan) if self.pipeline else []

    def _execute_pipeline(self,pipeline,nodes,results):
        from xgap.runtime.row_pipeline import run
        return run(self.workspace,pipeline,nodes,results)


    def _execute_remote(self,node,goal_id,results):
        started=time.perf_counter();backend=node.parameters['backend_id'];client=self.clients[backend]
        execute_stream=stream_executor(client)
        if execute_stream is None:
            result=super()._execute_remote(node,goal_id,results)
            if result.status is not S.SUCCESS:return result
            store=None
            try:
                store=self.workspace.store()
                for row in result.rows:store.append(row)
                return replace(result,rows=store.finish(),metadata={**result.metadata,'stream_transport':'materialized_adapter_fallback'})
            except Exception as error:
                if store is not None:store.close()
                return self._error(node,f'{type(error).__name__}: {error}',started,
                    input_bytes=result.input_bytes,remote_calls=result.remote_calls)
        store=None;calls=0;input_bytes=0;count=None
        try:
            artifact=dict(node.parameters['artifact']);budget=budget_from_artifact(artifact)
            if node.kind is K.REMOTE_BIND_QUERY:
                rows=results[node.inputs[0]].rows;input_bytes=_encoded_size(rows)
                artifact,count=self._bind_artifact(node,artifact,rows)
            store=self.workspace.store();received=0
            def emit(row):
                nonlocal received
                if not isinstance(row,dict):raise ValueError('Backend returned a non-row value')
                received+=1
                if budget and received>budget['fetch_rows']:raise ValueError('Backend exceeded the compiled relationship fetch bound')
                if not budget or received<=budget['rows']:store.append(row)
            if count!=0:
                calls=1
                execute_stream(QueryArtifact.from_dict(artifact),emit,self.control,self.workspace)
            store.finish()
            return RuntimeNodeResult(node_id=node.node_id,kind=node.kind,status=S.SUCCESS,rows=store,
                elapsed_ms=(time.perf_counter()-started)*1000,input_bytes=input_bytes,output_bytes=store.encoded_bytes,remote_calls=calls,
                metadata={'backend_id':backend,'stream_transport':'native-row-spool',
                    'database_cancel_capability':('owned-transaction' if hasattr(client,'_post_statement') else
                        'owned-query-extension' if getattr(getattr(client,'descriptor',None),'runtime',{}).get('confirmed_cancel_protocol')=='xgap-fuseki-v1' else 'adapter-or-timeout-only'),
                    **({'binding_count':count,'empty_binding_short_circuit':count==0} if count is not None else {}),
                    **({'retrieval_budget':observe_budget(budget,received)} if budget else {})})
        except Exception as error:
            if store is not None:store.close()
            return self._error(node,f'{type(error).__name__}: {error}',started,input_bytes=input_bytes,remote_calls=calls)

    def _execute_local(self,node,results):
        started=time.perf_counter();inputs=[results[n].rows for n in node.inputs]
        input_bytes=sum(_encoded_size(rows) for rows in inputs);store=None
        try:
            store=self.workspace.store()
            for row in operate(self.workspace,node,inputs):store.append(row)
            store.finish()
            return RuntimeNodeResult(node_id=node.node_id,kind=node.kind,status=S.SUCCESS,rows=store,
                elapsed_ms=(time.perf_counter()-started)*1000,input_bytes=input_bytes,output_bytes=store.encoded_bytes,
                bytes_moved=store.encoded_bytes if node.kind is K.EXCHANGE else 0,metadata={'stream_operator':True})
        except Exception as error:
            if store is not None:store.close()
            return self._error(node,f'{type(error).__name__}: {error}',started,input_bytes=input_bytes)
