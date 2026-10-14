"""Reproducible local execution comparison; no backend servers or model calls.

Run each mode in a fresh process. Measure latency without --trace-memory; use
separate traced runs for Python allocation peaks. RSS includes the interpreter,
SQLite and imports. Output is JSON on stdout; no result artifacts enter the repo.
"""
import argparse
import gc
import json
import resource
import sys
import time
import tracemalloc
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from xgap.runtime.contracts import RuntimeNode as N,RuntimeNodeKind as K,FederatedExecutionPlan
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.stream_scheduler import StreamingScheduler
from xgap.tools.backends import BackendInvokeTool,BackendPluginRegistry,NativeBackendPlugin
from xgap.infrastructure.runtime import ExecutionReport


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scheduler',choices=('materialized','stream'),default='stream')
    parser.add_argument('--rows',type=int,default=16000)
    parser.add_argument('--keep',type=int)
    parser.add_argument('--copies',type=int,default=1,help='Exact repetitions of each left row, exercising DISTINCT')
    parser.add_argument('--payload-bytes',type=int,default=1024)
    parser.add_argument('--trace-memory',action='store_true')
    parser.add_argument('--transport',choices=('rows','neo4j-json'),default='rows',help='Native JSON parser with file-backed local transport double; never opens a network connection')
    args=parser.parse_args();keep=args.rows if args.keep is None else args.keep
    if args.rows<1 or args.copies<1 or not 0<=keep<=args.rows or args.payload_bytes<0:parser.error('Invalid row/payload bounds')
    class Client:
        calls=0
        def rows(self,a):
            if a.artifact_id=='left':
                for i in range(args.rows):
                    for _ in range(args.copies):yield {'key':i%32,'value':i,'payload':str(i)+'x'*args.payload_bytes}
            else:
                for i in range(32):yield {'key':i,'group':i%4}
        def execute(self,a):
            self.calls+=1
            return ExecutionReport('local',a.artifact_id,a.language,True,rows=list(self.rows(a)))
        def execute_stream(self,a,emit,control,workspace):
            self.calls+=1
            for row in self.rows(a):emit(row)
    client=Client();counter=client;stack=ExitStack()
    if args.transport=='neo4j-json':
        from xgap.backends.neo4j_client import Neo4jClient
        from xgap.infrastructure.descriptors import BackendDescriptor
        from types import SimpleNamespace
        folder=Path(stack.enter_context(TemporaryDirectory(prefix='xgap-native-benchmark-')))
        for name,columns in [('left',['key','value','payload']),('right',['key','group'])]:
            with (folder/name).open('w') as output:
                output.write('{"results":[{"columns":'+json.dumps(columns)+',"data":[')
                for i,row in enumerate(client.rows(SimpleNamespace(artifact_id=name))):
                    if i:output.write(',')
                    json.dump({'row':[row[k] for k in columns]},output)
                output.write(']}],"errors":[]}')
        def opened(request,timeout):
            name=json.loads(request.data)['statements'][0]['statement']
            assert name in ('left','right')
            counter.calls+=1
            return (folder/name).open('rb')
        def lifecycle(control,url,method,payload,headers,timeout):
            with control.lock:control.lifecycle_calls+=1
            return {'errors':[],**({'commit':url+'/123/commit'} if url.endswith('/tx') else {})}
        stack.enter_context(patch('urllib.request.urlopen',opened))
        stack.enter_context(patch('xgap.backends.confirmed_cancel.lifecycle',lifecycle))
        client=Neo4jClient(BackendDescriptor.from_yaml(Path(__file__).resolve().parents[1]/'descriptors/backends/neo4j.yaml'))
    registry=BackendPluginRegistry();registry.register(NativeBackendPlugin('local',client))
    tool=BackendInvokeTool(registry)
    def remote(name):return N(name,K.REMOTE_QUERY,parameters={'backend_id':'local','artifact':{'artifact_id':name,'language':'cypher' if args.transport=='neo4j-json' else 'sparql','text':name}})
    plan=FederatedExecutionPlan('local-adaptive-comparison',(remote('left'),remote('right'),
        N('filter',K.COORDINATOR_FILTER,('left',),{'condition':{'op':'lt','field':'value','value':keep}}),
        N('join',K.COORDINATOR_JOIN,('filter','right'),{'left_on':'key','right_on':'key'}),
        N('sum',K.COORDINATOR_GROUP_AGGREGATE,('join',),{'group_by':['group'],'aggregations':{'n':{'op':'count'},'sum':{'op':'sum','field':'value'}}}),
        N('sort',K.COORDINATOR_SORT_LIMIT,('sum',),{'order_by':[{'field':'group'}],'limit':None})),
        roots=('sort',),max_remote_calls=2,max_parallelism=1)
    scheduler=StreamingScheduler(tool,clients={'local':client}) if args.scheduler=='stream' else FederatedScheduler(tool,retention='roots')
    gc.collect()
    if args.trace_memory:tracemalloc.start()
    began=time.perf_counter();result=scheduler.execute(plan);elapsed=time.perf_counter()-began
    peak=tracemalloc.get_traced_memory()[1] if args.trace_memory else None
    if args.trace_memory:tracemalloc.stop()
    expected=[dict(group=g,n=len(range(g,keep,4)),sum=sum(range(g,keep,4))) for g in range(min(4,keep))]
    assert result.success and list(result.final_rows)==expected,result
    assert counter.calls==result.total_remote_calls==2
    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
    print(json.dumps(dict(scheduler=args.scheduler,transport=args.transport,rows=args.rows,copies=args.copies,kept_rows=keep,payload_bytes=args.payload_bytes,
        trace_memory=args.trace_memory,elapsed_s=elapsed,python_peak_bytes=peak,process_peak_rss_bytes=rss,
        backend_calls=counter.calls,answers=list(result.final_rows),peak_spill_bytes=result.retention.get('peak_spill_bytes'),
        peak_intermediate_accounted_bytes=result.retention.get('peak_intermediate_accounted_bytes'),
        output_bytes={n.node_id:n.output_bytes for n in result.node_results},
        intermediate_memory_bytes=result.retention.get('intermediate_memory_bytes'),
        row_counts={n.node_id:n.row_count for n in result.node_results})))
    stack.close()


if __name__=='__main__':main()
