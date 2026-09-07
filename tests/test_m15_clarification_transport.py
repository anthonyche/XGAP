from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_clarification_transport import (
    CLARIFICATION_AUTHORITY_EVENT_SCHEMA_VERSION,
    CLARIFICATION_TRANSPORT_SESSION_SCHEMA_VERSION,
    SELECTED_EXECUTION_HANDOFF_SCHEMA_VERSION,
    M15ClarificationTransportError,
    advance_m15_clarification_transport_session,
    build_m15_clarification_authority_event,
    compile_m15_clarification_transport_session,
)
from xgap.experiments.m15_clarification_transport_evidence import (
    CLARIFICATION_TRANSPORT_AUDIT_SCHEMA_VERSION,
    CLARIFICATION_TRANSPORT_COMPACT_EVIDENCE_SCHEMA_VERSION,
    audit_m15_clarification_transport_session,
    build_m15_clarification_transport_compact_evidence,
)
from xgap.experiments.m15_direct_family_prediction import (
    build_m15_controlled_training_observations,
    build_m15_direct_training_memory_view,
)
from xgap.experiments.m15_direct_semantic_workload import (
    generate_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_parameterized_federation import (
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_resolution_execution_bridge import (
    compile_m15_resolution_execution_bridge,
)
from xgap.experiments.m15_semantic_intake import run_semantic_intake
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact
from xgap.runtime import FEDERATED_EXECUTION_TOOL, FederatedExecutionPlan
from xgap.runtime import FederatedExecutionTool, FederatedScheduler
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin
from xgap.tools.contracts import ToolContext, ToolStatus


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKLOAD_SPEC = REPO_ROOT / "experiments/configs/m15_f2c_parameterized_workload_dev.json"
QUERY_TEMPLATE = REPO_ROOT / "experiments/configs/m15_f2c_parameterized_financial_risk_v2.json"
BACKEND_TEMPLATES = REPO_ROOT / "experiments/templates/m15_f2c_financial_risk"
SEMANTIC_CATALOG = REPO_ROOT / "experiments/configs/m15_f2c6_semantic_relaxation_dev.json"
PREDICATE_MAPPING = REPO_ROOT / "experiments/configs/m15_f2c8_predicate_mapping_dev.json"
CARDINALITY_POLICY = REPO_ROOT / "experiments/configs/m15_f2c10_direct_semantic_workload_dev.json"
PREDICTOR_POLICY = REPO_ROOT / "experiments/configs/m15_f2c10_family_memory_predictor_dev.json"
INTERPRETATION_POLICY = REPO_ROOT / "experiments/configs/m15_e5_hierarchical_interpretation_policy_dev.json"
RELAXATION_POLICY = REPO_ROOT / "experiments/configs/m15_e5b_anchored_predicate_relaxation_dev.json"
TRANSPORT_POLICY = REPO_ROOT / "experiments/configs/m15_e5c_clarification_transport_dev.json"
RESOLUTION_ONTOLOGY = REPO_ROOT / "experiments/specs/m15_e3_financial_risk_ontology_dev.json"
BRIDGE_SPEC = REPO_ROOT / "experiments/configs/m15_e4_resolution_execution_bridge_dev.json"
COMPACT_EVIDENCE = REPO_ROOT / "experiments/artifacts/m15_e5c_local_clarification_transport_20260907.json"
RUNTIME_HASH = content_hash(
    {
        "runtime": "e5c-local-controlled-runtime",
        "neo4j": "controlled",
        "fuseki": "controlled",
    }
)


@pytest.fixture(scope="module")
def e5c_context(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("m15-e5c")
    base = generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=root / "base",
    )
    workload = generate_m15_direct_semantic_workload_bundle(
        base_bundle=base,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
        policy=CARDINALITY_POLICY,
        destination=root / "direct",
    )
    controlled = build_m15_controlled_training_observations(workload)
    memory = build_m15_direct_training_memory_view(
        workload=workload,
        raw_observations=controlled["observations"],
        runtime_compatibility_sha256=RUNTIME_HASH,
        policy=PREDICTOR_POLICY,
        measurement_source_kind="controlled_local_nonmeasurement_fixture",
    )
    resolution = run_semantic_intake(
        question="查找过去一个月与 Alice 有密切资金往来的高风险公司。",
        intake_path=REPO_ROOT
        / "experiments/configs/m15_e3_financial_risk_intake_dev.json",
        catalog_path=REPO_ROOT
        / "experiments/specs/m15_e3_financial_risk_catalog_dev.json",
        ontology_path=RESOLUTION_ONTOLOGY,
        user_selections={"person-identity": "person:alice-smith"},
        user_source_id="explicit-e5c-test-entity-selection",
    )
    spec = json.loads(BRIDGE_SPEC.read_text(encoding="utf-8"))
    bridge = compile_m15_resolution_execution_bridge(
        resolution,
        spec,
        repo_root=REPO_ROOT,
        bridge_spec_sha256=hashlib.sha256(BRIDGE_SPEC.read_bytes()).hexdigest(),
    )
    return workload, memory, bridge


def _arguments(e5c_context) -> dict[str, object]:
    workload, memory, bridge = e5c_context
    return {
        "session_id": "m15-e5c-test-session",
        "bridge": bridge,
        "workload": workload,
        "memory": memory,
        "predictor_policy": PREDICTOR_POLICY,
        "interpretation_policy": INTERPRETATION_POLICY,
        "ontology_path": RESOLUTION_ONTOLOGY,
        "relaxation_policy": RELAXATION_POLICY,
        "transport_policy": TRANSPORT_POLICY,
    }


def _start(e5c_context, **overrides):
    arguments = _arguments(e5c_context)
    arguments.update(overrides)
    return compile_m15_clarification_transport_session(**arguments)


def _advance(e5c_context, session, event):
    arguments = _arguments(e5c_context)
    arguments.pop("session_id")
    return advance_m15_clarification_transport_session(
        session=session,
        authority_event=event,
        **arguments,
    )


def _structurally_bound(e5c_context, *, candidate_id=None):
    initial = _start(e5c_context)
    event = build_m15_clarification_authority_event(
        session=initial,
        event_id="e5c-structural-event",
        candidate_id=(
            candidate_id
            or "constraint:single-transfer-at-least-50000"
        ),
        authority_source_id="explicit-e5c-structural-user-input",
    )
    return _advance(e5c_context, initial, event)


def _ready(e5c_context, *, predicate="predicate:transferred_to"):
    structural = _structurally_bound(e5c_context)
    event = build_m15_clarification_authority_event(
        session=structural,
        event_id="e5c-predicate-anchor-event",
        candidate_id=predicate,
        authority_source_id="explicit-e5c-predicate-user-input",
    )
    return _advance(e5c_context, structural, event)


def test_e5c_starts_with_one_hash_bound_r1_question(e5c_context) -> None:
    session = _start(e5c_context)
    payload = session.to_dict()

    assert payload["schema_version"] == CLARIFICATION_TRANSPORT_SESSION_SCHEMA_VERSION
    assert payload["status"] == "awaiting_structural_clarification"
    assert payload["execution_eligible"] is False
    assert payload["terminal"] is False
    assert payload["authority_events"] == []
    assert payload["execution_handoff"] is None
    question = payload["pending_question"]
    assert question["sequence"] == 1
    assert question["hole_id"] == "relationship-strength"
    assert [item["candidate_id"] for item in question["options"]] == [
        "constraint:single-transfer-at-least-50000",
        "constraint:amount-at-least-50000",
        "constraint:frequency-at-least-3",
    ]
    assert question["conversation_text_is_authoritative"] is False
    assert content_hash(
        {key: value for key, value in question.items() if key != "question_sha256"}
    ) == question["question_sha256"]
    assert content_hash(
        {key: value for key, value in payload.items() if key != "session_sha256"}
    ) == payload["session_sha256"]


def test_e5c_separates_structural_authority_from_predicate_anchor(
    e5c_context,
) -> None:
    session = _structurally_bound(e5c_context)
    payload = session.to_dict()

    assert payload["status"] == "awaiting_predicate_base_authority"
    assert payload["hierarchical_state"]["execution_eligible"] is True
    assert payload["execution_eligible"] is False
    assert payload["execution_handoff"] is None
    assert len(payload["authority_events"]) == 1
    question = payload["pending_question"]
    assert question["sequence"] == 2
    assert question["hole_id"] == "transfer-predicate"
    assert {item["candidate_id"] for item in question["options"]} == {
        "predicate:transferred_to",
        "predicate:paid_to",
    }
    assert question["varying_structural_dimensions"] == []
    assert question["reason_codes"] == [
        "anchored_relaxation_requires_authoritative_base"
    ]


def test_e5c_ready_session_attaches_all_and_only_anchored_returned_plans(
    e5c_context,
) -> None:
    session = _ready(e5c_context)
    payload = session.to_dict()
    handoff = session.execution_handoff

    assert payload["status"] == "ready_for_execution_handoff"
    assert payload["execution_eligible"] is True
    assert payload["terminal"] is True
    assert payload["pending_question"] is None
    assert len(payload["authority_events"]) == 2
    assert session.anchored_frontier is not None
    assert handoff is not None
    handoff_payload = handoff.to_dict()
    assert handoff_payload["schema_version"] == SELECTED_EXECUTION_HANDOFF_SCHEMA_VERSION
    assert handoff_payload["session_state_sha256"] == payload[
        "session_state_sha256"
    ]
    assert handoff_payload["authority_event_chain_sha256"] == payload[
        "authority_event_chain_sha256"
    ]
    returned = payload["anchored_state"]["returned_interpretation_plans"]
    expected_ids = [item["plan_id"] for item in returned]
    assert handoff_payload["selected_plan_ids"] == expected_ids
    assert list(handoff.plans) == expected_ids
    assert handoff_payload["execution_contract"] == {
        "allowed_tools": [FEDERATED_EXECUTION_TOOL],
        "plan_source": "anchored_frontier.returned_interpretation_plans",
        "all_and_only_returned_plans_attached": True,
        "execution_order": "selection_rank",
        "automatic_retries": 0,
    }
    assert content_hash(
        {
            key: value
            for key, value in handoff_payload.items()
            if key != "execution_handoff_sha256"
        }
    ) == handoff_payload["execution_handoff_sha256"]
    assert all(
        descriptor["runtime_plan_sha256"]
        == content_hash(handoff.plans[descriptor["plan_id"]].to_dict())
        for descriptor in handoff_payload["selected_plans"]
    )
    serialized = json.dumps(payload, sort_keys=True)
    assert " MATCH " not in serialized
    assert "SELECT " not in serialized


def test_e5c_session_reconstructs_exactly_from_authority_event_log(
    e5c_context,
) -> None:
    ready = _ready(e5c_context)
    reconstructed = _start(
        e5c_context,
        authority_events=ready.to_dict()["authority_events"],
    )

    assert reconstructed.to_dict() == ready.to_dict()
    assert reconstructed.execution_handoff is not None
    assert reconstructed.execution_handoff.to_dict() == (
        ready.execution_handoff.to_dict()
    )


@pytest.mark.parametrize(
    "candidate_id",
    [
        "constraint:amount-at-least-50000",
        "constraint:frequency-at-least-3",
    ],
)
def test_e5c_unavailable_structural_choice_is_terminal_without_handoff(
    e5c_context,
    candidate_id: str,
) -> None:
    session = _structurally_bound(e5c_context, candidate_id=candidate_id)
    payload = session.to_dict()

    assert payload["status"] == "selected_structure_unavailable"
    assert payload["execution_eligible"] is False
    assert payload["terminal"] is True
    assert payload["pending_question"] is None
    assert payload["execution_handoff"] is None
    assert session.anchored_frontier is None
    assert session.execution_handoff is None
    assert payload["hierarchical_state"]["status"] == (
        "authoritatively_selected_structure_unavailable"
    )


def test_e5c_rejects_out_of_set_tampered_and_replayed_events(e5c_context) -> None:
    initial = _start(e5c_context)
    with pytest.raises(
        M15ClarificationTransportError,
        match="outside the pending bounded set",
    ):
        build_m15_clarification_authority_event(
            session=initial,
            event_id="e5c-invalid-event",
            candidate_id="constraint:not-in-set",
            authority_source_id="explicit-e5c-user-input",
        )

    event = build_m15_clarification_authority_event(
        session=initial,
        event_id="e5c-valid-event",
        candidate_id="constraint:single-transfer-at-least-50000",
        authority_source_id="explicit-e5c-user-input",
    )
    assert event["schema_version"] == CLARIFICATION_AUTHORITY_EVENT_SCHEMA_VERSION
    tampered = copy.deepcopy(event)
    tampered["candidate_id"] = "constraint:amount-at-least-50000"
    with pytest.raises(M15ClarificationTransportError, match="hash mismatch"):
        _start(e5c_context, authority_events=[tampered])

    other = _start(e5c_context, session_id="m15-e5c-other-session")
    with pytest.raises(
        M15ClarificationTransportError,
        match="not bound to the pending question",
    ):
        _start(
            e5c_context,
            session_id=other.to_dict()["session_id"],
            authority_events=[event],
        )


def test_e5c_refuses_conversation_text_as_an_authority_event(e5c_context) -> None:
    initial = _start(e5c_context)
    event = build_m15_clarification_authority_event(
        session=initial,
        event_id="e5c-text-event",
        candidate_id="constraint:single-transfer-at-least-50000",
        authority_source_id="explicit-e5c-user-input",
    )
    event["conversation_text"] = "我想选单笔金额"
    body = {
        key: value for key, value in event.items() if key != "authority_event_sha256"
    }
    event["authority_event_sha256"] = content_hash(body)

    with pytest.raises(
        M15ClarificationTransportError,
        match="fields do not match",
    ):
        _start(e5c_context, authority_events=[event])


def test_e5c_paid_anchor_returns_only_its_dominating_exact_plan(e5c_context) -> None:
    session = _ready(e5c_context, predicate="predicate:paid_to")
    payload = session.to_dict()
    returned = payload["anchored_state"]["returned_interpretation_plans"]

    assert len(returned) == 1
    assert returned[0]["interpretation_status"] == "authoritatively_bound"
    assert returned[0]["selected_candidate_ids"]["transfer-predicate"] == (
        "predicate:paid_to"
    )
    assert payload["execution_handoff"]["selected_plan_ids"] == [
        returned[0]["plan_id"]
    ]


@dataclass
class _ControlledClient:
    backend_id: str
    rows_by_artifact: dict[str, list[dict[str, object]]]
    calls: int = 0

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "controlled fixture ready")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        self.calls += 1
        rows = [dict(item) for item in self.rows_by_artifact[artifact.artifact_id]]
        upper = artifact.parameters.get("occurred_on_lt")
        if self.backend_id == "neo4j" and isinstance(upper, str):
            rows = [item for item in rows if str(item["occurred_on"]) < upper]
        company_ids = artifact.parameters.get("company_ids")
        if self.backend_id == "neo4j" and isinstance(company_ids, list):
            allowed = set(company_ids)
            rows = [
                item
                for item in rows
                if str(item["company_id"]).rsplit(":", 1)[-1] in allowed
            ]
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=rows,
            elapsed_ms=1.0,
        )


def _controlled_clients(e5c_context, handoff):
    workload, _, bridge = e5c_context
    candidate_by_plan = {
        item["plan_id"]: item for item in bridge.to_dict()["physical_candidates"]
    }
    rows: dict[str, dict[str, list[dict[str, object]]]] = {
        "neo4j": {},
        "fuseki": {},
    }
    for plan_id, plan in handoff.plans.items():
        instance = load_m15_parameterized_instance(
            workload.workload_bundle,
            candidate_by_plan[plan_id]["query_id"],
        )
        source = instance["source_oracles"]
        for node in plan.nodes:
            backend_id = node.parameters.get("backend_id")
            if backend_id not in rows:
                continue
            artifact = QueryArtifact.from_dict(node.parameters["artifact"])
            if backend_id == "fuseki":
                role = "fuseki_risk"
            elif "company_ids" in artifact.parameters:
                role = "neo4j_bound"
            else:
                role = "neo4j_full"
            rows[backend_id][artifact.artifact_id] = source[role]
    return {
        backend_id: _ControlledClient(backend_id, values)
        for backend_id, values in rows.items()
    }


def test_e5c_handoff_runs_through_existing_allowlisted_runtime_tool_only(
    e5c_context,
) -> None:
    ready = _ready(e5c_context)
    handoff = ready.execution_handoff
    assert handoff is not None
    clients = _controlled_clients(e5c_context, handoff)
    plugins = BackendPluginRegistry()
    for backend_id, client in clients.items():
        plugins.register(NativeBackendPlugin(backend_id, client))
    tool = FederatedExecutionTool(
        FederatedScheduler(BackendInvokeTool(plugins))
    )

    executed = []
    for index, plan_id in enumerate(handoff.to_dict()["selected_plan_ids"], 1):
        plan = handoff.plans[plan_id]
        assert FederatedExecutionPlan.from_dict(plan.to_dict()) == plan
        result = tool.invoke(
            {"plan": plan.to_dict()},
            ToolContext(
                goal_id="m15-e5c-controlled-execution",
                step=index,
                call_id=f"execute-selected-{index}",
            ),
        )
        assert result.status is ToolStatus.SUCCESS
        assert result.value["success"] is True
        assert result.value["total_remote_calls"] == 2
        executed.append(plan_id)

    assert executed == handoff.to_dict()["selected_plan_ids"]
    assert sum(client.calls for client in clients.values()) == 2 * len(executed)
    assert len(executed) < len(e5c_context[2].plans)


def test_e5c_call_and_claim_boundaries_are_explicit(e5c_context) -> None:
    payload = _ready(e5c_context).to_dict()

    assert payload["claim_boundary"] == {
        "artifact_class": "resumable_clarification_authority_transport",
        "development_artifacts_only": True,
        "hard_constraints_preserved": True,
        "authority_events_required": True,
        "conversation_text_used_as_authority": False,
        "answer_oracle_used_for_selection": False,
        "post_execution_measurements_used": False,
        "current_query_profile_calls": 0,
        "backend_calls_made": 0,
        "llm_calls_made": 0,
        "ontology_service_calls_made": 0,
        "native_query_text_emitted": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    assert payload["execution_handoff"]["claim_boundary"][
        "backend_calls_made"
    ] == 0
    assert payload["execution_handoff"]["claim_boundary"][
        "native_query_text_emitted"
    ] is False
    assert payload["paper_result"] is False


def test_e5c_independent_audit_reconstructs_ready_session(e5c_context) -> None:
    ready = _ready(e5c_context)
    arguments = _arguments(e5c_context)
    arguments.pop("session_id")

    audit = audit_m15_clarification_transport_session(
        session=ready.to_dict(),
        **arguments,
    ).to_dict()

    assert audit["schema_version"] == CLARIFICATION_TRANSPORT_AUDIT_SCHEMA_VERSION
    assert audit["success"] is True
    assert audit["check_count"] == 13
    assert audit["failed_check_ids"] == []
    assert audit["reconstruction_error"] is None
    assert audit["source_session_mutated"] is False
    assert content_hash(
        {key: value for key, value in audit.items() if key != "audit_sha256"}
    ) == audit["audit_sha256"]


def test_e5c_independent_audit_reports_tampered_portable_session(
    e5c_context,
) -> None:
    tampered = _ready(e5c_context).to_dict()
    tampered["execution_handoff"]["selected_plan_ids"].reverse()
    arguments = _arguments(e5c_context)
    arguments.pop("session_id")

    audit = audit_m15_clarification_transport_session(
        session=tampered,
        **arguments,
    ).to_dict()

    assert audit["success"] is False
    assert "session.hash" in audit["failed_check_ids"]
    assert "session.exact_reconstruction" in audit["failed_check_ids"]
    assert "handoff.all_and_only_returned_plan_ids" in audit["failed_check_ids"]
    assert audit["paper_result"] is False


def test_e5c_compact_evidence_is_hash_bound_and_reproducible(
    e5c_context,
) -> None:
    artifact = json.loads(COMPACT_EVIDENCE.read_text(encoding="utf-8"))
    workload, memory, _ = e5c_context
    resolution = run_semantic_intake(
        question="查找过去一个月与 Alice 有密切资金往来的高风险公司。",
        intake_path=REPO_ROOT
        / "experiments/configs/m15_e3_financial_risk_intake_dev.json",
        catalog_path=REPO_ROOT
        / "experiments/specs/m15_e3_financial_risk_catalog_dev.json",
        ontology_path=RESOLUTION_ONTOLOGY,
        user_selections={"person-identity": "person:alice-smith"},
        user_source_id="explicit-e5c-evidence-entity-selection",
    )
    bridge = compile_m15_resolution_execution_bridge(
        resolution,
        json.loads(BRIDGE_SPEC.read_text(encoding="utf-8")),
        repo_root=REPO_ROOT,
        bridge_spec_sha256=hashlib.sha256(BRIDGE_SPEC.read_bytes()).hexdigest(),
    )
    common = {
        "bridge": bridge,
        "workload": workload,
        "memory": memory,
        "predictor_policy": PREDICTOR_POLICY,
        "interpretation_policy": INTERPRETATION_POLICY,
        "ontology_path": RESOLUTION_ONTOLOGY,
        "relaxation_policy": RELAXATION_POLICY,
        "transport_policy": TRANSPORT_POLICY,
    }
    initial = compile_m15_clarification_transport_session(
        session_id="m15-e5c-controlled-evidence-session",
        **common,
    )
    structural_event = build_m15_clarification_authority_event(
        session=initial,
        event_id="m15-e5c-evidence-structural-event",
        candidate_id="constraint:single-transfer-at-least-50000",
        authority_source_id="explicit-e5c-evidence-structural-user-input",
    )
    structural = advance_m15_clarification_transport_session(
        session=initial,
        authority_event=structural_event,
        **common,
    )
    predicate_event = build_m15_clarification_authority_event(
        session=structural,
        event_id="m15-e5c-evidence-predicate-event",
        candidate_id="predicate:transferred_to",
        authority_source_id="explicit-e5c-evidence-predicate-user-input",
    )
    ready = advance_m15_clarification_transport_session(
        session=structural,
        authority_event=predicate_event,
        **common,
    )
    unavailable = {}
    for candidate_id in (
        "constraint:amount-at-least-50000",
        "constraint:frequency-at-least-3",
    ):
        event = build_m15_clarification_authority_event(
            session=initial,
            event_id="m15-e5c-evidence-" + candidate_id.rsplit(":", 1)[-1],
            candidate_id=candidate_id,
            authority_source_id="explicit-e5c-evidence-unavailable-user-input",
        )
        unavailable[candidate_id] = advance_m15_clarification_transport_session(
            session=initial,
            authority_event=event,
            **common,
        )
    audit = audit_m15_clarification_transport_session(
        session=ready,
        **common,
    )
    actual = build_m15_clarification_transport_compact_evidence(
        git_commit=artifact["git_commit"],
        initial=initial,
        structurally_bound=structural,
        ready=ready,
        unavailable_structures=unavailable,
        audit=audit,
    )

    assert artifact["schema_version"] == (
        CLARIFICATION_TRANSPORT_COMPACT_EVIDENCE_SCHEMA_VERSION
    )
    assert content_hash(
        {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    ) == artifact["artifact_sha256"]
    assert actual == artifact
