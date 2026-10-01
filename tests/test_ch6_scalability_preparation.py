import json
import sqlite3
import threading
import time

from xgap.experiments.ch6_synthetic import generate
from xgap.experiments.ch6_parallel import LEVELS, execute, variant, ready_width
from xgap.infrastructure.runtime import ExecutionReport
from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNode, RuntimeNodeKind
from xgap.tools.backends import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


def test_synthetic_fact_generator_is_deterministic_and_structurally_valid(tmp_path):
    receipts=[]
    for name in ('a','b'):
        ref=generate(tmp_path/name,nodes=32,degree=4,seed=7,reserve_bytes=0)
        receipts.append(json.loads(open(ref['path']).read()))
    assert receipts[0]['provenance']['logical_facts_sha256']==receipts[1]['provenance']['logical_facts_sha256']
    assert receipts[0]['counts']['edges']==128
    with sqlite3.connect(receipts[0]['database']['path']) as db:
        assert db.execute('SELECT count(*) FROM edges WHERE src=dst').fetchone()[0]==0
        assert db.execute('SELECT DISTINCT c FROM (SELECT count(*) c FROM edges GROUP BY src)').fetchall()==[(4,)]
        assert db.execute('SELECT DISTINCT c FROM (SELECT count(*) c FROM edges GROUP BY dst)').fetchall()==[(4,)]


def test_parallelism_changes_actual_overlap_without_changing_answers():
    class Client:
        backend_id='source'
        def execute(self,artifact):
            time.sleep(.03)
            return ExecutionReport(backend_id='source',artifact_id=artifact.artifact_id,
                language=artifact.language,success=True,rows=[{'id':artifact.artifact_id}])
    plugins=BackendPluginRegistry();plugins.register(NativeBackendPlugin('source',Client()))
    tool=BackendInvokeTool(plugins)
    nodes=tuple(RuntimeNode(str(i),RuntimeNodeKind.REMOTE_QUERY,parameters=dict(backend_id='source',
        artifact=dict(artifact_id=str(i),language='sparql',text='SELECT ?id WHERE {}'))) for i in range(4))
    plan=FederatedExecutionPlan('overlap',nodes=nodes,roots=tuple(n.node_id for n in nodes),max_remote_calls=4)
    serial,s=execute(plan,tool,parallelism=1)
    parallel,p=execute(plan,tool,parallelism=4)
    assert serial.success and parallel.success and serial.root_rows==parallel.root_rows
    assert s['calls']==p['calls']==4 and s['observed_peak_inflight']==1
    assert p['observed_peak_inflight']>1 and ready_width(plan)==4
    assert variant(plan,8).nodes==plan.nodes


def test_two_sources_execute_sixteen_ready_tasks_with_actual_worker_overlap():
    # Synthetic in-memory clients only: the barrier proves workers overlap,
    # without interpreting noisy fixture wall times as a database speedup.
    state={};lock=threading.Lock()
    class Client:
        def __init__(self,backend_id):self.backend_id=backend_id
        def execute(self,artifact):
            with lock:state['calls'].append((self.backend_id,artifact.artifact_id,threading.get_ident()))
            state['gate'].wait(timeout=3)
            time.sleep(.005)
            return ExecutionReport(backend_id=self.backend_id,artifact_id=artifact.artifact_id,
                language=artifact.language,success=True,rows=[{'id':artifact.artifact_id}])
    plugins=BackendPluginRegistry()
    for source in ('source0','source1'):plugins.register(NativeBackendPlugin(source,Client(source)))
    tool=BackendInvokeTool(plugins)
    nodes=tuple(RuntimeNode(str(i),RuntimeNodeKind.REMOTE_QUERY,parameters=dict(backend_id='source'+str(i%2),
        artifact=dict(artifact_id=str(i),language='sparql',text='SELECT ?id WHERE {}'))) for i in range(16))
    plan=FederatedExecutionPlan('two-sources-wide-plan',nodes=nodes,roots=tuple(n.node_id for n in nodes),max_remote_calls=16)
    frozen=plan.to_dict();answer=None
    assert LEVELS==(1,2,4,8,16) and ready_width(plan)==16
    for parallelism in LEVELS:
        state.update(gate=threading.Barrier(parallelism),calls=[])
        result,observation=execute(plan,tool,parallelism=parallelism)
        assert result.success
        if answer is None:answer=result.root_rows
        assert result.root_rows==answer and plan.to_dict()==frozen
        assert observation['calls']==len(state['calls'])==16
        assert observation['observed_peak_inflight']==parallelism
        assert len({thread_id for _,_,thread_id in state['calls']})==parallelism
        assert {source for source,_,_ in state['calls']}=={'source0','source1'}
        assert observation['model_calls']==0 and observation['planner_reexecuted'] is False
