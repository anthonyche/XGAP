"""Only the new one-shot lifetime, capture and replay risks; tiny/offline."""
from dataclasses import replace
import json
import threading
import time

import pytest

from test_anchor_reduction import tiny, EXPECTED
from test_anchor_source_bind import space, fanout
from test_m15_federated_runtime import _plan, _runtime_tool, RowsBackendClient
from test_one_shot_question import estimator, PIN, BUNDLE_FIXTURE
from xgap.experiments.one_shot_records import (
    BackendReplay, CapturingClient, replay_from_saved_result, write_once,
)
from xgap.agent.question import run_question
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.runtime.semantic_planning import LogicalSource
from xgap.semantic.interpretation import InterpretationRequest, InterpretationResponse
from xgap.semantic.interpretation_candidates import SCHEMA
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.contracts import (
    FederatedExecutionPlan, RuntimeNode, RuntimeNodeKind as K,
    RuntimeNodeResult, RuntimeNodeStatus as S, RuntimePlanError,
)
from xgap.runtime.scheduler import FederatedScheduler


def stable_metrics(result):
    return [(n.node_id, n.status, n.row_count, n.input_bytes, n.output_bytes,
             n.bytes_moved, n.remote_calls, n.error) for n in result.node_results]


def test_shared_fanout_preserves_exact_answers_metrics_and_releases_payloads():
    p, s, b, _, _, full, _ = tiny()
    plan = fanout(space(p, s, b)).plan
    compact = FederatedScheduler(full._backend_tool, retention="roots")
    a, z = full.execute(plan), compact.execute(plan)
    assert a.success and z.success and a.final_rows == z.final_rows == EXPECTED
    assert stable_metrics(a) == stable_metrics(z)
    assert a.total_remote_calls == z.total_remote_calls
    assert a.total_bytes_moved == z.total_bytes_moved
    assert all(n.rows is not None for n in a.node_results)
    assert all((n.rows is not None) == (n.node_id in plan.roots) for n in z.node_results)
    assert z.retention["final_registered_rows"] == len(EXPECTED)
    assert z.retention["peak_registered_rows"] < sum(n.row_count for n in a.node_results)
    raw = z.to_dict()
    assert all(n["rows"] is None and n["rows_retained"] is False
               for n in raw["node_results"] if n["node_id"] not in plan.roots)
    sizes = [len(json.dumps(r.to_dict(), sort_keys=True).encode()) for r in (a, z)]
    assert sizes[1] < sizes[0]
    print(json.dumps({"gate":"tiny-retention-fanout", "answer_rows":len(EXPECTED),
        "full_trace_bytes":sizes[0], "compact_trace_bytes":sizes[1],
        "full_final_registered_rows":sum(n.row_count for n in a.node_results),
        "compact_retention":dict(z.retention), "source_calls_each":z.total_remote_calls}))


@pytest.mark.parametrize("failure", [False, True])
def test_multiple_roots_survive_consumers_and_errors_keep_counts(failure):
    full = _runtime_tool(fail_fuseki=failure).scheduler
    plan = replace(_plan(), roots=("neo4j-transfers", "exchange-transfers", "join"))
    a = full.execute(plan)
    z = FederatedScheduler(full._backend_tool, retention="roots").execute(plan)
    assert z.root_rows == a.root_rows and z.final_rows == a.final_rows
    assert z.success is (not failure) and stable_metrics(z) == stable_metrics(a)
    assert all(n.rows is not None for n in z.node_results if n.node_id in plan.roots)
    if failure:
        assert any(n.status is S.ERROR and n.error == "backend unavailable" for n in z.node_results)
        assert any(n.status is S.SKIPPED and n.error for n in z.node_results)
        assert z.total_remote_calls == 2


def test_slow_parallel_consumer_can_read_after_fast_consumer_finishes():
    barrier = threading.Barrier(2)
    class Parallel(FederatedScheduler):
        def _execute_remote(self, node, goal_id, results):
            if node.node_id == "seed":
                rows = ({"id":1}, {"id":2})
            else:
                barrier.wait(timeout=3)
                if node.node_id == "slow":
                    until = time.monotonic() + 3
                    while "fast" not in results and time.monotonic() < until:
                        threading.Event().wait(.001)
                    assert "fast" in results
                # In particular, slow reads AFTER fast has been registered.
                assert results["seed"].rows is not None
                rows = results["seed"].rows
            return RuntimeNodeResult(node.node_id,node.kind,S.SUCCESS,rows=rows,
                                     output_bytes=22,remote_calls=1)
    plan = FederatedExecutionPlan("parallel-retention", (
        RuntimeNode("seed",K.REMOTE_QUERY),
        RuntimeNode("fast",K.REMOTE_BIND_QUERY,inputs=("seed",)),
        RuntimeNode("slow",K.REMOTE_BIND_QUERY,inputs=("seed",)),
    ),roots=("fast","slow"),max_remote_calls=3,max_parallelism=2)
    result = Parallel(None,retention="roots").execute(plan)
    assert result.success and len(result.final_rows) == 4
    assert result.node_results[0].rows is None and result.node_results[0].row_count == 2


def test_full_prefix_still_works_and_released_prefix_is_explicitly_rejected():
    full = _runtime_tool().scheduler
    plan = _plan(); a = full.execute(plan)
    seed = a.node_results[0]
    continued = full.execute(plan,initial_results={seed.node_id:seed})
    assert continued.final_rows == a.final_rows
    compact = FederatedScheduler(full._backend_tool,retention="roots")
    with pytest.raises(RuntimePlanError,match="resumable prefix"):
        compact.execute(plan,initial_results={seed.node_id:seed})
    released = replace(seed,rows=None,released_row_count=seed.row_count)
    with pytest.raises(RuntimePlanError,match="Released payloads"):
        full.execute(plan,initial_results={seed.node_id:released})
    with pytest.raises(RuntimePlanError,match="observed row count"):
        replace(seed,rows=None)
    old_trace = {"selected_plan":plan.to_dict(), "execution":{"value":{
        "node_results":[released.to_dict()]}}}
    with pytest.raises(ValueError,match="original captured backend ledger"):
        replay_from_saved_result({},old_trace)


def capture(tmp_path, *, failure=False):
    artifact = QueryArtifact("q","sparql","SELECT ...")
    client = RowsBackendClient("rdf",{"q":[{"id":i,"payload":"x"*128} for i in range(5)]},fail=failure)
    records = []
    wrapped = CapturingClient(client,tmp_path,records,threading.Lock(),retain_payloads=False)
    return artifact, records, wrapped


@pytest.mark.parametrize("failure", [False, True])
def test_pinned_capture_replays_complete_success_or_native_failure(tmp_path,failure):
    artifact, records, wrapped = capture(tmp_path,failure=failure)
    original = wrapped.execute(artifact)
    assert "execution" not in records[0] and records[0]["status"] == "returned"
    replay = BackendReplay("rdf",records).execute(artifact)
    assert replay.rows == original.rows and replay.success == original.success
    assert replay.error == original.error and replay.metadata["network_calls"] == 0
    assert records[0]["row_count"] == len(original.rows)


@pytest.mark.parametrize("corruption", ["hash", "identity", "size"])
def test_capture_pin_rejects_corruption_before_consuming_record(tmp_path,corruption):
    artifact, records, wrapped = capture(tmp_path)
    wrapped.execute(artifact)
    pin = records[0]["response_record"]
    if corruption == "hash": pin["sha256"] = "0"*64
    elif corruption == "size": pin["bytes"] = 2**40
    else:
        raw = json.loads((tmp_path/"backend-0000-result.json").read_text())
        raw["artifact"]["text"] = "different query"
        records[0]["response_record"] = write_once(tmp_path/"wrong.json",raw)
    replay = BackendReplay("rdf",records)
    with pytest.raises(ValueError,match="capture|Evidence stored size/hash mismatch"):
        replay.execute(artifact)
    assert replay.position == 0


def test_failed_capture_write_keeps_indeterminate_record_without_retry(tmp_path,monkeypatch):
    import xgap.experiments.one_shot_records as module
    artifact, records, wrapped = capture(tmp_path)
    original = module.write_once
    def failing(path,value):
        if path.name.endswith("-result.json"):raise OSError("disk fixture")
        return original(path,value)
    monkeypatch.setattr(module,"write_once",failing)
    with pytest.raises(OSError,match="disk fixture"):wrapped.execute(artifact)
    assert len(records) == 1 and records[0]["status"] == "indeterminate"
    assert "response_record" not in records[0]


def test_indexed_parallel_order_is_not_a_query_change_and_cannot_duplicate_calls(tmp_path):
    records=[];lock=threading.Lock()
    client=RowsBackendClient('rdf',{'a':[{'id':'a'}],'b':[{'id':'b'}]})
    wrapped=CapturingClient(client,tmp_path,records,lock,retain_payloads=False)
    a,b=(QueryArtifact(k,'sparql',f'SELECT {k}') for k in ('a','b'))
    wrapped.execute(b);wrapped.execute(a)  # Native start order is b,a.
    replay=BackendReplay('rdf',records)
    assert replay.execute(a).rows==[{'id':'a'}]
    with pytest.raises(ValueError,match='artifact differs'):replay.execute(a)
    assert replay.position==1
    assert replay.execute(b).rows==[{'id':'b'}] and replay.position==2
    with pytest.raises(ValueError,match='No backend replay'):replay.execute(b)


def test_new_capture_replays_the_same_current_ordinary_entry(tmp_path,monkeypatch,estimator):
    import socket
    monkeypatch.setattr(socket.socket,"connect",lambda *a,**kw:pytest.fail("Unexpected network"))
    p,placement,backends,graphs,clients,_,calls = tiny()
    union = graphs['rdf_a'] + graphs['rdf_b'];graphs.update(rdf_a=union,rdf_b=union)
    class Provider:
        provider_id = 'authored-tiny-retention'
        def interpret(self,request):
            return InterpretationResponse({'schema_version':SCHEMA,'candidates':[{
                'candidate_id':'tiny','quality_proxy':1.0,'program':p.to_dict(),
                'operator_sources':{o:'toy' for o in placement}}]})
    args = dict(mode='performance',estimator=estimator,catalog_root=BUNDLE_FIXTURE/PIN['root'],
        catalog_hash=PIN['bundle_hash'],sources={'toy':LogicalSource('toy','toy-v1',('rdf_a','rdf_b'))},
        backends=backends,
        # rdflib's in-process parser is not a concurrent server. The separate
        # slow-consumer test above exercises actual overlapping scheduler work.
        one_shot_policy=replace(OneShotPolicy.for_mode('performance'),max_parallelism=1))
    request = InterpretationRequest('Find people reachable from the aged-20 anchor.',context={'query_id':'slice-query'})
    records=[];lock=threading.Lock()
    capture_clients={b:CapturingClient(c,tmp_path,records,lock,retain_payloads=False) for b,c in clients.items()}
    first=run_question(request,Provider(),backend_clients=capture_clients,**args)
    assert first['success'],[(n['node_id'],n['error']) for n in first.get('execution',{}).get('value',{}).get('node_results',[]) if n.get('status')=='error']
    first_calls=len(calls)
    assert tuple(first['answer_rows'])==EXPECTED
    assert records and all('execution' not in r and 'response_record' in r for r in records)
    replay_clients={b:BackendReplay(b,[r for r in records if r['backend_id']==b]) for b in clients}
    second=run_question(request,Provider(),backend_clients=replay_clients,**args)
    assert second['success'],second
    assert second['answer_rows']==first['answer_rows'] and second['selected_plan']==first['selected_plan']
    assert second['final_plan_executions']==first['final_plan_executions']==1
    assert all(c.position==len(c.records) for c in replay_clients.values())
    assert len(calls)==first_calls  # No source calls in replay.
    assert second['execution']['value']['retention']['final_rows_truncated'] is False
