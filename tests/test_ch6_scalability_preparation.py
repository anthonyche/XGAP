import json
import sqlite3
import time

from xgap.experiments.ch6_synthetic import generate
from xgap.experiments.ch6_parallel import execute, variant, ready_width
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
