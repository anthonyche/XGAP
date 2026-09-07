from __future__ import annotations

import copy
import hashlib
import http.client
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
import xgap.ui.local_app as local_app

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_clarification_transport import (
    CLARIFICATION_AUTHORITY_EVENT_SCHEMA_VERSION,
    CLARIFICATION_TRANSPORT_SESSION_SCHEMA_VERSION,
    SELECTED_EXECUTION_HANDOFF_SCHEMA_VERSION,
    M15ClarificationTransportError,
    M15ClarificationTransportSession,
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
from xgap.ui import (
    CLARIFICATION_VIEW_SCHEMA_VERSION,
    LOCAL_UI_STATE_SCHEMA_VERSION,
    LOCAL_UI_SUBMISSION_RESULT_SCHEMA_VERSION,
    LOCAL_UI_HTTP_SCHEMA_VERSION,
    SELECTED_SESSION_SUBMISSION_PREVIEW_SCHEMA_VERSION,
    M15ClarificationUiError,
    M15LocalClarificationController,
    M15LocalControlError,
    M15LocalHttpConfig,
    build_m15_local_http_server,
    build_m15_clarification_selection_event,
    build_m15_clarification_view,
    build_m15_selected_session_submission_preview,
)


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
REMOTE_MEMORY_PATH = (
    "/home/hxc859/XGAP-m15-465e2e2/runs/"
    "cwru-m15-native-direct-family-pilot-3791600/native-service-run/"
    "direct-family-pilot-run/training/training_memory_view.json"
)
DISPLAY_QUERY = "查找过去一个月与 Alice 有密切资金往来的高风险公司。"


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


def _ready_with_shared_authority(e5c_context):
    authority_source_id = "author:anthonyche:e6b-ui-test"
    initial = _start(e5c_context)
    structural_event = build_m15_clarification_authority_event(
        session=initial,
        event_id="e6b-ui-structural-event",
        candidate_id="constraint:single-transfer-at-least-50000",
        authority_source_id=authority_source_id,
    )
    structural = _advance(e5c_context, initial, structural_event)
    predicate_event = build_m15_clarification_authority_event(
        session=structural,
        event_id="e6b-ui-predicate-event",
        candidate_id="predicate:transferred_to",
        authority_source_id=authority_source_id,
    )
    return _advance(e5c_context, structural, predicate_event)


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


def test_e6b_projects_pending_question_without_execution_details(
    e5c_context,
) -> None:
    view = build_m15_clarification_view(_start(e5c_context))

    assert view["schema_version"] == CLARIFICATION_VIEW_SCHEMA_VERSION
    assert view["status"] == "awaiting_structural_clarification"
    assert view["execution_eligible"] is False
    assert view["execution_handoff"] is None
    assert view["question"]["hole_id"] == "relationship-strength"
    assert view["question"]["response_contract"] == (
        "explicit_candidate_id_only"
    )
    assert [item["candidate_id"] for item in view["question"]["options"]] == [
        "constraint:single-transfer-at-least-50000",
        "constraint:amount-at-least-50000",
        "constraint:frequency-at-least-3",
    ]
    serialized = json.dumps(view, sort_keys=True)
    assert "runtime_plan" not in serialized
    assert " MATCH " not in serialized
    assert "SELECT " not in serialized
    assert content_hash(
        {key: value for key, value in view.items() if key != "view_sha256"}
    ) == view["view_sha256"]


def test_e6b_selection_is_by_candidate_id_not_display_order(e5c_context) -> None:
    initial = _start(e5c_context)
    payload = initial.to_dict()
    question = payload["pending_question"]
    question["options"] = list(reversed(question["options"]))
    question["question_sha256"] = content_hash(
        {
            key: value
            for key, value in question.items()
            if key != "question_sha256"
        }
    )
    payload["session_sha256"] = content_hash(
        {
            key: value
            for key, value in payload.items()
            if key != "session_sha256"
        }
    )
    reordered = M15ClarificationTransportSession(
        payload=payload,
        hierarchical_frontier=initial.hierarchical_frontier,
    )

    event = build_m15_clarification_selection_event(
        session=reordered,
        event_id="e6b-reordered-choice",
        candidate_id="constraint:single-transfer-at-least-50000",
        authority_source_id="author:anthonyche:e6b-reordered",
    )

    assert event["candidate_id"] == (
        "constraint:single-transfer-at-least-50000"
    )
    assert event["question_sha256"] == question["question_sha256"]


def test_e6b_refuses_out_of_set_or_terminal_selection(e5c_context) -> None:
    with pytest.raises(M15ClarificationUiError, match="outside the pending"):
        build_m15_clarification_selection_event(
            session=_start(e5c_context),
            event_id="e6b-out-of-set",
            candidate_id="constraint:invented",
            authority_source_id="author:anthonyche:e6b-test",
        )

    with pytest.raises(M15ClarificationUiError, match="no pending"):
        build_m15_clarification_selection_event(
            session=_ready_with_shared_authority(e5c_context),
            event_id="e6b-after-terminal",
            candidate_id="predicate:transferred_to",
            authority_source_id="author:anthonyche:e6b-test",
        )


def test_e6b_builds_exact_script_scoped_selected_session_preview(
    e5c_context,
) -> None:
    ready = _ready_with_shared_authority(e5c_context)
    memory_hash = ready.to_dict()["source_contract"][
        "training_memory_view_sha256"
    ]

    preview = build_m15_selected_session_submission_preview(
        session=ready,
        remote_training_memory_path=REMOTE_MEMORY_PATH,
        expected_training_memory_sha256=memory_hash,
    )

    assert preview["schema_version"] == (
        SELECTED_SESSION_SUBMISSION_PREVIEW_SCHEMA_VERSION
    )
    assert preview["remote_operation"] == "submit_job"
    assert preview["remote_payload"]["script"] == (
        "scripts/slurm/run_m15_native_selected_interpretation_session.sbatch"
    )
    environment = preview["remote_payload"]["environment"]
    assert set(environment) == {
        "XGAP_M15_SELECTED_TRAINING_MEMORY",
        "XGAP_M15_SELECTED_MEMORY_SHA256",
        "XGAP_M15_SELECTED_SESSION_ID",
        "XGAP_M15_SELECTED_STRUCTURAL_CANDIDATE",
        "XGAP_M15_SELECTED_PREDICATE_CANDIDATE",
        "XGAP_M15_SELECTED_AUTHORITY_SOURCE_ID",
    }
    assert environment["XGAP_M15_SELECTED_TRAINING_MEMORY"] == (
        REMOTE_MEMORY_PATH
    )
    assert environment["XGAP_M15_SELECTED_MEMORY_SHA256"] == memory_hash
    assert environment["XGAP_M15_SELECTED_STRUCTURAL_CANDIDATE"] == (
        "constraint:single-transfer-at-least-50000"
    )
    assert environment["XGAP_M15_SELECTED_PREDICATE_CANDIDATE"] == (
        "predicate:transferred_to"
    )
    serialized = json.dumps(preview, sort_keys=True)
    assert "password" not in serialized.lower()
    assert "token" not in serialized.lower()
    assert " MATCH " not in serialized
    assert "SELECT " not in serialized
    assert content_hash(
        {
            key: value
            for key, value in preview.items()
            if key != "submission_preview_sha256"
        }
    ) == preview["submission_preview_sha256"]


def test_e6b_refuses_nonready_memory_drift_and_unsafe_remote_path(
    e5c_context,
) -> None:
    initial = _start(e5c_context)
    with pytest.raises(M15ClarificationUiError, match="only a ready"):
        build_m15_selected_session_submission_preview(
            session=initial,
            remote_training_memory_path=REMOTE_MEMORY_PATH,
            expected_training_memory_sha256=initial.to_dict()[
                "source_contract"
            ]["training_memory_view_sha256"],
        )

    ready = _ready_with_shared_authority(e5c_context)
    memory_hash = ready.to_dict()["source_contract"][
        "training_memory_view_sha256"
    ]
    with pytest.raises(M15ClarificationUiError, match="differs"):
        build_m15_selected_session_submission_preview(
            session=ready,
            remote_training_memory_path=REMOTE_MEMORY_PATH,
            expected_training_memory_sha256="0" * 64,
        )
    with pytest.raises(M15ClarificationUiError, match="unsafe"):
        build_m15_selected_session_submission_preview(
            session=ready,
            remote_training_memory_path="/home/hxc859/memory.json,OTHER=value",
            expected_training_memory_sha256=memory_hash,
        )


def test_e6b_refuses_two_different_authority_sources(e5c_context) -> None:
    ready = _ready(e5c_context)
    with pytest.raises(M15ClarificationUiError, match="one shared"):
        build_m15_selected_session_submission_preview(
            session=ready,
            remote_training_memory_path=REMOTE_MEMORY_PATH,
            expected_training_memory_sha256=ready.to_dict()[
                "source_contract"
            ]["training_memory_view_sha256"],
        )


def _local_controller(e5c_context, *, session=None, **overrides):
    current = session or _start(e5c_context)
    arguments = {
        "session": current,
        "advance_session": lambda value, event: _advance(
            e5c_context, value, event
        ),
        "remote_training_memory_path": REMOTE_MEMORY_PATH,
        "expected_training_memory_sha256": current.to_dict()[
            "source_contract"
        ]["training_memory_view_sha256"],
        "authority_source_id": "author:anthonyche:e6c-loopback-test",
        "display_query": DISPLAY_QUERY,
    }
    arguments.update(overrides)
    return M15LocalClarificationController(**arguments)


def _select_current(controller, candidate_id):
    state = controller.snapshot()
    question = state["clarification"]["question"]
    return controller.select_candidate(
        expected_session_sha256=state["clarification"]["session_sha256"],
        expected_question_sha256=question["question_sha256"],
        candidate_id=candidate_id,
    )


def _ready_local_controller(e5c_context, **overrides):
    controller = _local_controller(e5c_context, **overrides)
    _select_current(
        controller, "constraint:single-transfer-at-least-50000"
    )
    _select_current(controller, "predicate:transferred_to")
    return controller


def _successful_remote_submission(payload):
    return {
        "tool_name": "remote.executor",
        "status": "success",
        "value": {
            "executor_id": "cwru-pioneer",
            "operation": "submit_job",
            "state": "submitted",
            "job_id": "3793365",
            "script": payload["script"],
            "job_environment_keys": sorted(payload["environment"]),
        },
        "error": None,
        "metrics": {"control_calls": 1.0},
        "metadata": {},
    }


def test_e6c_initial_snapshot_is_browser_safe(e5c_context) -> None:
    state = _local_controller(e5c_context).snapshot()
    serialized = json.dumps(state, sort_keys=True)

    assert state["schema_version"] == LOCAL_UI_STATE_SCHEMA_VERSION
    assert state["connected"] is True
    assert state["request"] == {
        "text": DISPLAY_QUERY,
        "sha256": hashlib.sha256(DISPLAY_QUERY.encode("utf-8")).hexdigest(),
    }
    assert state["submission_preview"] is None
    assert state["submission_enabled"] is False
    assert state["submission_attempted"] is False
    assert "authority_source_id" not in serialized
    assert REMOTE_MEMORY_PATH not in serialized
    assert "XGAP_M15_SELECTED" not in serialized
    assert content_hash(
        {key: value for key, value in state.items() if key != "state_sha256"}
    ) == state["state_sha256"]


def test_e6c_commits_hash_bound_choices_and_persists(e5c_context) -> None:
    persisted = []
    controller = _local_controller(
        e5c_context,
        persist_session=lambda session: persisted.append(session.to_dict()),
    )
    initial = controller.snapshot()
    question = initial["clarification"]["question"]

    after = controller.select_candidate(
        expected_session_sha256=initial["clarification"]["session_sha256"],
        expected_question_sha256=question["question_sha256"],
        candidate_id="constraint:single-transfer-at-least-50000",
    )

    assert len(persisted) == 1
    assert after["clarification"]["authority_event_count"] == 1
    assert after["clarification"]["question"]["hole_id"] == (
        "transfer-predicate"
    )
    assert persisted[0]["session_sha256"] == after["clarification"][
        "session_sha256"
    ]


def test_e6c_rejects_stale_hashes_without_mutation(e5c_context) -> None:
    persisted = []
    controller = _local_controller(
        e5c_context,
        persist_session=lambda session: persisted.append(session.to_dict()),
    )
    initial = controller.snapshot()
    question = initial["clarification"]["question"]

    with pytest.raises(M15LocalControlError, match="session changed"):
        controller.select_candidate(
            expected_session_sha256="0" * 64,
            expected_question_sha256=question["question_sha256"],
            candidate_id="constraint:single-transfer-at-least-50000",
        )
    with pytest.raises(M15LocalControlError, match="question changed"):
        controller.select_candidate(
            expected_session_sha256=initial["clarification"]["session_sha256"],
            expected_question_sha256="0" * 64,
            candidate_id="constraint:single-transfer-at-least-50000",
        )

    assert persisted == []
    assert controller.snapshot()["state_sha256"] == initial["state_sha256"]


def test_e6c_ready_preview_hides_server_owned_submission_values(
    e5c_context,
) -> None:
    controller = _ready_local_controller(e5c_context)
    state = controller.snapshot()
    serialized = json.dumps(state, sort_keys=True)

    assert state["clarification"]["status"] == (
        "ready_for_execution_handoff"
    )
    assert state["submission_preview"]["confirmation_required"] is True
    assert "remote_payload" not in state["submission_preview"]
    assert "authority_source_id" not in serialized
    assert REMOTE_MEMORY_PATH not in serialized
    assert "XGAP_M15_SELECTED" not in serialized


def test_e6c_submission_requires_enablement_confirmation_and_fresh_preview(
    e5c_context,
) -> None:
    disabled = _ready_local_controller(e5c_context)
    preview_hash = disabled.snapshot()["submission_preview"][
        "submission_preview_sha256"
    ]
    with pytest.raises(M15LocalControlError, match="disabled"):
        disabled.submit_selected_session(
            expected_submission_preview_sha256=preview_hash,
            confirmed=True,
        )

    controller = _ready_local_controller(
        e5c_context, submit_job=_successful_remote_submission
    )
    preview_hash = controller.snapshot()["submission_preview"][
        "submission_preview_sha256"
    ]
    with pytest.raises(M15LocalControlError, match="explicit confirmation"):
        controller.submit_selected_session(
            expected_submission_preview_sha256=preview_hash,
            confirmed=False,
        )
    with pytest.raises(M15LocalControlError, match="preview changed"):
        controller.submit_selected_session(
            expected_submission_preview_sha256="0" * 64,
            confirmed=True,
        )
    assert controller.snapshot()["submission_attempted"] is False


def test_e6c_publishes_only_normalized_submission_result_once(
    e5c_context,
) -> None:
    payloads = []

    def submit(payload):
        payloads.append(copy.deepcopy(payload))
        return _successful_remote_submission(payload)

    controller = _ready_local_controller(e5c_context, submit_job=submit)
    preview_hash = controller.snapshot()["submission_preview"][
        "submission_preview_sha256"
    ]
    state = controller.submit_selected_session(
        expected_submission_preview_sha256=preview_hash,
        confirmed=True,
    )

    assert len(payloads) == 1
    assert set(payloads[0]) == {"script", "environment"}
    assert state["submission_enabled"] is False
    assert state["submission_attempted"] is True
    assert state["submission_result"] == {
        "schema_version": LOCAL_UI_SUBMISSION_RESULT_SCHEMA_VERSION,
        "status": "success",
        "executor_id": "cwru-pioneer",
        "job_id": "3793365",
        "state": "submitted",
        "script": payloads[0]["script"],
    }
    with pytest.raises(M15LocalControlError, match="already submitted"):
        controller.submit_selected_session(
            expected_submission_preview_sha256=preview_hash,
            confirmed=True,
        )
    assert len(payloads) == 1


def test_e6c_unsafe_or_uncertain_submitter_never_retries(e5c_context) -> None:
    calls = []

    def unsafe(payload):
        calls.append(payload)
        return {
            **_successful_remote_submission(payload),
            "secret": "do-not-expose",
        }

    controller = _ready_local_controller(e5c_context, submit_job=unsafe)
    preview_hash = controller.snapshot()["submission_preview"][
        "submission_preview_sha256"
    ]
    with pytest.raises(M15LocalControlError, match="invalid observation"):
        controller.submit_selected_session(
            expected_submission_preview_sha256=preview_hash,
            confirmed=True,
        )
    state = controller.snapshot()
    assert state["submission_result"]["status"] == "unknown"
    assert "secret" not in json.dumps(state, sort_keys=True)
    with pytest.raises(M15LocalControlError, match="already submitted"):
        controller.submit_selected_session(
            expected_submission_preview_sha256=preview_hash,
            confirmed=True,
        )
    assert len(calls) == 1


def _http_json(connection, method, path, *, origin=None, body=None):
    headers = {}
    encoded = None
    if origin is not None:
        headers["Origin"] = origin
    if body is not None:
        encoded = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    connection.request(method, path, body=encoded, headers=headers)
    response = connection.getresponse()
    payload = json.loads(response.read().decode("utf-8"))
    return response, payload


def _run_local_server(controller):
    config = M15LocalHttpConfig(port=0)
    server = build_m15_local_http_server(controller, config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_e6c_http_server_refuses_nonloopback_configuration() -> None:
    with pytest.raises(ValueError, match="127.0.0.1"):
        M15LocalHttpConfig(bind_address="0.0.0.0")
    with pytest.raises(ValueError, match="loopback"):
        M15LocalHttpConfig(allowed_origins=("https://example.com",))


def test_e6c_http_server_projects_state_and_enforces_origin(e5c_context) -> None:
    controller = _local_controller(e5c_context)
    server, thread = _run_local_server(controller)
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=5
    )
    try:
        response, health = _http_json(connection, "GET", "/health")
        assert response.status == 200
        assert health == {
            "schema_version": LOCAL_UI_HTTP_SCHEMA_VERSION,
            "status": "ready",
            "bind_address": "127.0.0.1",
            "paper_result": False,
        }

        response, state = _http_json(
            connection,
            "GET",
            "/api/session",
            origin="http://localhost:3000",
        )
        assert response.status == 200
        assert response.getheader("Access-Control-Allow-Origin") == (
            "http://localhost:3000"
        )
        assert state["state_sha256"] == controller.snapshot()["state_sha256"]

        response, failure = _http_json(
            connection,
            "POST",
            "/api/clarification",
            origin="https://example.com",
            body={
                "session_sha256": "0" * 64,
                "question_sha256": "0" * 64,
                "candidate_id": "constraint:single-transfer-at-least-50000",
                "confirmed": True,
            },
        )
        assert response.status == 403
        assert failure == {"error": "request origin is not allowed"}
        assert controller.snapshot()["clarification"][
            "authority_event_count"
        ] == 0
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_e6c_http_server_commits_confirmed_choices(e5c_context) -> None:
    controller = _local_controller(e5c_context)
    server, thread = _run_local_server(controller)
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=5
    )
    origin = "http://127.0.0.1:3000"
    try:
        initial = controller.snapshot()
        question = initial["clarification"]["question"]
        request = {
            "session_sha256": initial["clarification"]["session_sha256"],
            "question_sha256": question["question_sha256"],
            "candidate_id": "constraint:single-transfer-at-least-50000",
            "confirmed": False,
        }
        response, failure = _http_json(
            connection,
            "POST",
            "/api/clarification",
            origin=origin,
            body=request,
        )
        assert response.status == 409
        assert "explicit confirmation" in failure["error"]
        assert failure["state"]["clarification"][
            "authority_event_count"
        ] == 0

        request["confirmed"] = True
        response, after = _http_json(
            connection,
            "POST",
            "/api/clarification",
            origin=origin,
            body=request,
        )
        assert response.status == 200
        assert after["clarification"]["authority_event_count"] == 1
        assert after["clarification"]["question"]["sequence"] == 2
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_e6c_http_server_submits_only_fixed_confirmed_preview(
    e5c_context,
) -> None:
    controller = _ready_local_controller(
        e5c_context, submit_job=_successful_remote_submission
    )
    server, thread = _run_local_server(controller)
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=5
    )
    origin = "http://localhost:3000"
    try:
        state = controller.snapshot()
        response, submitted = _http_json(
            connection,
            "POST",
            "/api/submit",
            origin=origin,
            body={
                "submission_preview_sha256": state["submission_preview"][
                    "submission_preview_sha256"
                ],
                "confirmed": True,
            },
        )
        assert response.status == 200
        assert submitted["submission_result"]["job_id"] == "3793365"
        assert submitted["submission_enabled"] is False

        response, repeated = _http_json(
            connection,
            "POST",
            "/api/submit",
            origin=origin,
            body={
                "submission_preview_sha256": state["submission_preview"][
                    "submission_preview_sha256"
                ],
                "confirmed": True,
            },
        )
        assert response.status == 409
        assert "already submitted" in repeated["error"]
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_e6c_session_store_round_trips_only_reconstruction_key(
    e5c_context,
    tmp_path,
) -> None:
    session = _structurally_bound(e5c_context)
    store_path = tmp_path / "ui-state.json"

    local_app.persist_m15_local_ui_session(store_path, session)
    stored = local_app.load_m15_local_ui_session_store(store_path)

    assert stored is not None
    assert stored["schema_version"] == (
        local_app.LOCAL_UI_SESSION_STORE_SCHEMA_VERSION
    )
    assert stored["session_id"] == session.to_dict()["session_id"]
    assert stored["authority_events"] == session.to_dict()["authority_events"]
    assert stored["session_sha256"] == session.session_hash
    assert set(stored) == {
        "schema_version",
        "session_id",
        "authority_events",
        "session_sha256",
        "paper_result",
        "store_sha256",
    }
    serialized = store_path.read_text(encoding="utf-8")
    assert "native_query" not in serialized
    assert REMOTE_MEMORY_PATH not in serialized


def test_e6c_session_store_rejects_tampering_and_symlinks(
    e5c_context,
    tmp_path,
) -> None:
    store_path = tmp_path / "ui-state.json"
    local_app.persist_m15_local_ui_session(
        store_path, _start(e5c_context)
    )
    payload = json.loads(store_path.read_text(encoding="utf-8"))
    payload["session_id"] = "tampered-session"
    store_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(local_app.M15LocalAppError, match="hash mismatch"):
        local_app.load_m15_local_ui_session_store(store_path)

    store_path.unlink()
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    store_path.symlink_to(target)
    with pytest.raises(local_app.M15LocalAppError, match="non-symbolic-link"):
        local_app.load_m15_local_ui_session_store(store_path)
    with pytest.raises(local_app.M15LocalAppError, match="non-symbolic-link"):
        local_app.persist_m15_local_ui_session(
            store_path, _start(e5c_context)
        )


def test_e6c_local_app_reconstructs_session_from_persisted_events(
    e5c_context,
    tmp_path,
    monkeypatch,
) -> None:
    workload, memory, bridge = e5c_context
    prepared = SimpleNamespace(bridge=bridge, workload=workload)
    monkeypatch.setattr(
        local_app,
        "prepare_m15_resolution_execution_bridge",
        lambda **kwargs: prepared,
    )
    monkeypatch.setattr(
        local_app,
        "load_m15_direct_training_memory_view",
        lambda *args, **kwargs: memory,
    )
    monkeypatch.setattr(
        local_app,
        "_resolution_question_sha256",
        lambda path: hashlib.sha256(DISPLAY_QUERY.encode("utf-8")).hexdigest(),
    )
    state_path = tmp_path / "session.json"
    arguments = {
        "resolution_run_path": tmp_path / "resolution.json",
        "training_memory_path": tmp_path / "memory.json",
        "remote_training_memory_path": REMOTE_MEMORY_PATH,
        "expected_training_memory_sha256": memory.memory_view_hash,
        "session_id": "m15-e6c-local-app-test",
        "authority_source_id": "author:anthonyche:e6c-local-app-test",
        "display_query": DISPLAY_QUERY,
        "session_store_path": state_path,
        "repo_root": REPO_ROOT,
    }

    initial = local_app.build_m15_local_clarification_controller(
        **arguments,
        workload_destination=tmp_path / "workload-one",
    )
    _select_current(
        initial, "constraint:single-transfer-at-least-50000"
    )
    persisted = local_app.load_m15_local_ui_session_store(state_path)
    assert persisted is not None
    assert len(persisted["authority_events"]) == 1

    resumed = local_app.build_m15_local_clarification_controller(
        **arguments,
        workload_destination=tmp_path / "workload-two",
    )
    snapshot = resumed.snapshot()
    assert snapshot["clarification"]["authority_event_count"] == 1
    assert snapshot["clarification"]["question"]["sequence"] == 2
    assert snapshot["clarification"]["session_sha256"] == persisted[
        "session_sha256"
    ]
