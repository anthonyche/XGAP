"""Pull local operators together; only fan-out, remote and root boundaries seal.

The original physical DAG and every node's counts remain visible. No backend is
re-executed and no row is consumed before its native response has been validated.
"""
from collections import Counter
import time
from xgap.runtime.contracts import RuntimeNodeKind as K,RuntimeNodeStatus as S,RuntimeNodeResult
from xgap.runtime.spill_operators import operate
from xgap.runtime.row_size import encoded_row_size

REMOTE={K.REMOTE_QUERY,K.REMOTE_BIND_QUERY}


def islands(plan,preexecuted=frozenset()):
    nodes={n.node_id:n for n in plan.nodes};uses=Counter(i for n in plan.nodes for i in n.inputs)
    roots=set(plan.roots);remote_inputs={i for n in plan.nodes if n.kind in REMOTE for i in n.inputs}
    sinks=[n.node_id for n in plan.nodes if n.node_id not in preexecuted and n.kind not in REMOTE and
        (uses[n.node_id]!=1 or n.node_id in roots or n.node_id in remote_inputs)]
    out=[];queued=set(sinks)
    for sink in sinks:
        members=[];boundaries=set();claimed={sink};stack=[(sink,False)]
        while stack:
            identifier,expanded=stack.pop()
            if expanded:members.append(identifier);continue
            stack.append((identifier,True))
            for parent in reversed(nodes[identifier].inputs):
                local=nodes[parent].kind not in REMOTE and parent not in preexecuted
                if local and uses[parent]==1 and parent not in roots and len(claimed)<64:
                    claimed.add(parent);stack.append((parent,False))
                else:
                    boundaries.add(parent)
                    if local and parent not in queued:sinks.append(parent);queued.add(parent)
        out.append(dict(root=sink,nodes=members,boundaries=boundaries,row_pipeline=True))
    return out


def run(workspace,pipeline,nodes,results):
    started=time.perf_counter();root=pipeline['root'];metrics={};streams={};failed=[];store=None
    consumers={i:nodes[c].kind for c in pipeline['nodes'] for i in nodes[c].inputs}
    def produce(identifier):
        node=nodes[identifier];m=metrics[identifier]
        inputs=[streams[i] if i in streams else results[i].rows for i in node.inputs]
        try:
            for row in operate(workspace,node,inputs,unordered=consumers.get(identifier) in (K.COORDINATOR_GROUP_AGGREGATE,K.COORDINATOR_SORT_LIMIT,K.MERGE)):
                workspace.control.check()
                m['bytes']+=encoded_row_size(row)+int(m['rows']>0);m['rows']+=1
                yield row
            m['complete']=True
        except Exception as error:
            if not failed:failed.append((identifier,error))
            raise
    try:
        for identifier in pipeline['nodes']:
            metrics[identifier]=dict(rows=0,bytes=2,complete=False)
            streams[identifier]=produce(identifier)
        store=workspace.store()
        for row in streams[root]:store.append(row)
        store.finish()
    except Exception as error:
        if not failed:failed.append((root,error))
        if store is not None:store.close();store=None
    finally:
        # Explicitly unwind partially consumed blocking operators on any error.
        for stream in reversed(list(streams.values())):stream.close()
    elapsed=(time.perf_counter()-started)*1000;output=[]
    for identifier in pipeline['nodes']:
        node=nodes[identifier];m=metrics[identifier];terminal=identifier==root
        success=m['complete'] and (not terminal or not failed)
        status=S.SUCCESS if success else S.ERROR if failed and failed[0][0]==identifier else S.SKIPPED
        inputs=sum(metrics[i]['bytes'] if i in metrics else results[i].output_bytes for i in node.inputs)
        output.append(RuntimeNodeResult(identifier,node.kind,status,
            rows=store if terminal and success else None,released_row_count=None if terminal and success else m['rows'],
            input_bytes=inputs,output_bytes=m['bytes'] if success else 0,
            bytes_moved=m['bytes'] if success and node.kind is K.EXCHANGE else 0,
            elapsed_ms=elapsed if terminal else 0,
            error=None if success else f'{type(failed[0][1]).__name__}: {failed[0][1]}',
            metadata=dict(streaming_pipeline=root,stream_operator=True,intermediate_payload_materialized=terminal,
                timing_scope='whole local pipeline at boundary; per-node timing unavailable')))
    return output,dict(root=root,nodes=pipeline['nodes'],streamed_rows={i:m['rows'] for i,m in metrics.items()},
        profile='pull-local-operators-v1',success=not failed)
