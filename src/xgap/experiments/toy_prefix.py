"""A2 native mechanism gate: fixed synthetic history, raw prefix observations.

The unchanged tiny graph has one Alice. Joining that entity with all people
must return Alice under either replica placement. No speedup is claimed.
"""

from copy import deepcopy
import hashlib
import json
import time

from xgap.backends.rdf_terms import RDF_TERMS_V1
from xgap.experiments.toy_backbone import load_fixture
from xgap.experiments.toy_binding import reference_rows
from xgap.experiments.toy_semantic import toy_backends
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.adaptive import ReplanPolicy
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.runtime.planning import PlanObservationSnapshot, RemoteEstimate
from xgap.runtime.semantic_adaptive import SemanticPrefixPolicy
from xgap.runtime.semantic_placement import prepare_semantic_placements
from xgap.runtime.semantic_planning import LogicalSource, run_semantic_plans
from xgap.semantic.program import (SemanticGraphProgram, SemanticOperator,
    SemanticOperatorKind as S, SemanticValueKind as V)
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, CatalogBackendPlugin, ToolStatus


BACKEND_ORDER = ("neo4j", "fuseki")
EXPECTED_ROWS = [{"person": "https://xgap.test/toy/a"}]
HISTORICAL_VALUES = {("s0", "neo4j"): (1000, 100), ("s0", "fuseki"): (2000, 100),
    ("s1", "neo4j"): (100, 1), ("s1", "fuseki"): (1, 10)}


def _fixture(mapping):
    graph, _, _ = load_fixture()
    version = hashlib.sha256(json.dumps(graph, sort_keys=True).encode()).hexdigest()
    sources = {"toy": LogicalSource("toy", version, BACKEND_ORDER)}
    alice = SemanticOperator("s0", S.MATCH, (), (), V.BINDING_SET,
        {"node": {"label": "Person", "properties": {"name": "Alice"}}, "entity_field": "person"})
    people = SemanticOperator("s1", S.MATCH, (), (), V.BINDING_SET,
        {"node": {"label": "Person"}, "entity_field": "person"})
    join = SemanticOperator("join", S.JOIN, ("s0", "s1"), (V.BINDING_SET, V.BINDING_SET),
        V.BINDING_SET, {"left_on": "person", "right_on": "person"})
    program = SemanticGraphProgram("A2-native-prefix", (alice, people, join), ("join",))
    space = prepare_semantic_placements(program, operator_sources={"s0": "toy", "s1": "toy"},
        sources=sources, backends=toy_backends(mapping), max_local_options=4,
        max_observation_calls=4, max_remote_calls=2)
    owners = {node.parameters["observation_key"]: (operator, backend)
        for (operator, backend), nodes in space.local_nodes.items()
        for node in nodes if node.kind is R.REMOTE_QUERY}
    history = PlanObservationSnapshot("A2-native-synthetic-history", "v1", tuple(
        RemoteEstimate(request.observation_key, request.backend_id,
            *HISTORICAL_VALUES[owners[request.observation_key]], 40,
            "A2 synthetic historical cost-table intervention", "v1")
        for request in space.observation_requests), 1000, 0, 0.1)
    return space, history, version


class _RecordedTool:
    def __init__(self, delegate, calls, on_update):
        self.delegate, self.calls, self.on_update = delegate, calls, on_update

    @property
    def spec(self):
        return self.delegate.spec

    def invoke(self, arguments, context):
        event = {"arguments": deepcopy(arguments), "goal_id": context.goal_id,
            "call_id": context.call_id, "status": "started"}
        self.calls.append(event)
        self.on_update()
        started = time.perf_counter()
        try:
            result = self.delegate.invoke(arguments, context)
            event.update(result=result.to_dict(), status=result.status.value)
            return result
        except Exception as error:
            event.update(status="error", error=f"{type(error).__name__}: {error}")
            raise
        finally:
            event["elapsed_ms"] = (time.perf_counter() - started) * 1000
            self.on_update()


def _references():
    # Independently authored targets, never generated from the selected plan.
    return {
        "neo4j": QueryArtifact("A2-reference-neo4j", "cypher",
            "MATCH (p:Person {name: 'Alice'}) "
            "RETURN 'https://xgap.test/toy/' + p.id AS person ORDER BY person", kind="native"),
        "fuseki": QueryArtifact("A2-reference-fuseki", "sparql",
            'PREFIX t: <https://xgap.test/toy/>\n'
            'SELECT ?person WHERE { ?person a t:Person ; t:name "Alice" . } ORDER BY ?person',
            kind="native", parameters={"rdf_result_encoding": RDF_TERMS_V1}),
    }


def execute_prefix_ablation(mapping, *, clients, record, on_update):
    started = time.perf_counter()
    record.update(schema_version="a2-native-prefix-mechanism-v1", success=False,
        paper_result=False, live_llm=False, performance_claim=False, automatic_retries=0,
        track="deterministic_planning", interpretation_exercised=False, goal_loop_exercised=False,
        query_id="A2-prefix", expected_rows=deepcopy(EXPECTED_ROWS), backend_order=list(BACKEND_ORDER),
        intervention={"kind": "synthetic historical cardinality and latency", "row_width_bytes": 40,
            "values": [{"source": source, "backend": backend, "elapsed_ms": values[0], "row_count": values[1]}
                for (source, backend), values in HISTORICAL_VALUES.items()],
            "current_backend_reports_modified": False, "historical_acquisition": None,
            "external_history_preparation_calls": 0},
        timing_boundary="Arm wall time includes trace persistence and excludes shared local preparation; "
            "planning_run end_to_end_ms retains its preparation-time attribution. No performance comparison.",
        arms=[{"mode": mode, "status": "not_attempted", "success": False,
               "contract_passed": False, "calls": []} for mode in ("replan", "no_replan")],
        references=[{"backend": backend, "status": "not_attempted", "success": False}
            for backend in BACKEND_ORDER])
    on_update()
    try:
        space, history, source_version = _fixture(mapping)
        frozen_history = history.to_dict()
        record.update(program=space.program.to_dict(), history=frozen_history,
            source={"source_id": "toy", "snapshot_version": source_version,
                "replica_backend_ids": list(BACKEND_ORDER)},
            shared_preparation_ms=space.enumeration_ms,
            domain={"local_options": space.local_option_count,
                "possible_placement_count": space.possible_placement_count,
                "max_remote_calls": space.max_remote_calls})
        on_update()
        for arm in record["arms"]:
            plugins = BackendPluginRegistry()
            for backend, catalog in space.observation_catalogs.items():
                plugins.register(CatalogBackendPlugin(backend, clients[backend], catalog))
            tool = _RecordedTool(BackendInvokeTool(plugins), arm["calls"], on_update)
            policy = SemanticPrefixPolicy(source_operator="s0",
                replan_policy=ReplanPolicy(max_replans=int(arm["mode"] == "replan")))
            arm.update(status="started", policy=policy.to_dict())
            on_update()
            arm_started = time.perf_counter()
            run = run_semantic_plans(space, tool, snapshot=history, prefix_policy=policy,
                goal_id="A2-native-" + arm["mode"])
            arm.update(planning_run=run, arm_wall_ms=(time.perf_counter() - arm_started) * 1000,
                status="checking_contract", execution_answer_success=False)
            on_update()
            if not run["success"]:
                raise ValueError("A2 native arm failed: " + str(run["error"]))
            detail = run["prefix"]
            actual = run["execution"]["value"]["final_rows"]
            arm.update(actual_rows=actual, execution_answer_success=actual == EXPECTED_ROWS)
            expected = {"s0": "neo4j", "s1": "fuseki" if arm["mode"] == "replan" else "neo4j"}
            probe = {item["node_id"]: item for item in detail["probe_run"]["node_results"]}
            continued = {item["node_id"]: item for item in detail["continuation_run"]["node_results"]}
            initial_id = space.compile({"s0": "neo4j", "s1": "neo4j"}).plan.plan_id
            checks = {"independent_gold_answer": actual == EXPECTED_ROWS,
                "initial_placement": detail["initial_selection"]["selected_plan_id"] == initial_id,
                "expected_unfinished_placement": run["selected_plan"]["metadata"]["source_bindings"] == expected,
                "fixed_source": detail["source_operator"] == "s0" and detail["fixed_source_bindings"] == {"s0": "neo4j"},
                "two_real_calls": run["observation_calls"] == 0 and run["execution_calls"] == run["total_remote_calls"] == len(arm["calls"]) == 2,
                "call_order": [call["arguments"]["backend_id"] for call in arm["calls"]] == ["neo4j", expected["s1"]],
                "execution_only": all(call["arguments"]["operation"] == "execute" and call["status"] == ToolStatus.SUCCESS.value for call in arm["calls"]),
                "prefix_not_counted_twice": detail["prefix_remote_calls"] == detail["continuation_new_remote_calls"] == 1,
                "exact_raw_reuse": set(detail["reused_node_ids"]) == set(probe) and all(continued.get(key) == value for key, value in probe.items()),
                "expected_replan": detail["selection_runs"] == (2 if arm["mode"] == "replan" else 1) and detail["replan_count"] == int(arm["mode"] == "replan"),
                "frozen_history": history.to_dict() == frozen_history == detail["history_snapshot"],
                "no_retry_or_enumeration": run["automatic_retries"] == 0 and run["search_space_materialized"] is False}
            arm["contract_checks"] = checks
            if not all(checks.values()):
                raise ValueError("A2 mechanism contract failed: " + ", ".join(key for key, ok in checks.items() if not ok))
            arm.update(success=True, contract_passed=True, status="completed")
            on_update()
        for reference in record["references"]:
            backend = reference["backend"]
            artifact = _references()[backend]
            reference.update(status="started", artifact=artifact.to_dict())
            on_update()
            result = clients[backend].execute(artifact)
            reference.update(execution=result.to_dict(), status="checking_answer")
            on_update()
            actual = reference_rows(result, backend)
            reference.update(actual_rows=actual, success=result.success and actual == EXPECTED_ROWS)
            if not reference["success"]:
                raise ValueError("A2 independent reference failed: " + backend)
            reference["status"] = "completed"
            on_update()
        record["success"] = True
    except Exception as error:
        record["error"] = f"{type(error).__name__}: {error}"
        for item in (*record["arms"], *record["references"]):
            if item["status"] in {"started", "checking_contract", "checking_answer"}:
                item.update(status="failed", success=False, error=record["error"])
        raise
    finally:
        if not record["success"]:
            for item in (*record["arms"], *record["references"]):
                if item["status"] == "not_attempted":
                    item["status"] = "not_attempted_after_failure"
        record["current_method_remote_calls"] = sum(len(arm["calls"]) for arm in record["arms"])
        record["reference_remote_calls"] = sum(item["status"] not in {"not_attempted", "not_attempted_after_failure"}
            for item in record["references"])
        record["end_to_end_ms"] = (time.perf_counter() - started) * 1000
        on_update()
    return record
