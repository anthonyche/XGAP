"""Resumable authority transport from E5 clarification to E4 execution.

The transport is intentionally a control-plane contract.  It records only
explicit, bounded authority events, reconstructs the deterministic E5/E5B
selectors after every event, and hands the existing E4 runtime only the plans
returned by the anchored frontier.  Conversation text and backend-native query
text are never semantic authority in this layer.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_anchored_interpretation_frontier import (
    M15AnchoredInterpretationFrontier,
    select_m15_anchored_interpretation_frontier,
)
from xgap.experiments.m15_direct_family_prediction import (
    M15DirectTrainingMemoryView,
)
from xgap.experiments.m15_direct_semantic_workload import (
    M15DirectSemanticWorkloadBundle,
)
from xgap.experiments.m15_hierarchical_interpretation_frontier import (
    M15HierarchicalInterpretationFrontier,
    select_m15_hierarchical_interpretation_frontier,
)
from xgap.experiments.m15_resolution_execution_bridge import (
    M15ResolutionExecutionBridgePlan,
)
from xgap.runtime import FederatedExecutionPlan, RuntimeNodeKind
from xgap.runtime.tool import FEDERATED_EXECUTION_TOOL


CLARIFICATION_TRANSPORT_POLICY_SCHEMA_VERSION = (
    "m15-e5c-clarification-transport-policy-v1"
)
CLARIFICATION_AUTHORITY_EVENT_SCHEMA_VERSION = (
    "m15-e5c-clarification-authority-event-v1"
)
CLARIFICATION_TRANSPORT_SESSION_SCHEMA_VERSION = (
    "m15-e5c-clarification-transport-session-v1"
)
SELECTED_EXECUTION_HANDOFF_SCHEMA_VERSION = (
    "m15-e5c-selected-execution-handoff-v1"
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_AUTHORITY_EVENT_FIELDS = {
    "schema_version",
    "event_id",
    "session_id",
    "sequence",
    "question_sha256",
    "hole_id",
    "candidate_id",
    "authority_source_id",
    "source_kind",
    "authoritative",
    "authority_event_sha256",
}


class M15ClarificationTransportError(ValueError):
    """Raised before execution when a session or authority event drifts."""


@dataclass(frozen=True)
class M15SelectedExecutionHandoff:
    payload: Mapping[str, Any]
    plans: Mapping[str, FederatedExecutionPlan]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))

    @property
    def handoff_hash(self) -> str:
        return str(self.payload["execution_handoff_sha256"])


@dataclass(frozen=True)
class M15ClarificationTransportSession:
    payload: Mapping[str, Any]
    hierarchical_frontier: M15HierarchicalInterpretationFrontier
    anchored_frontier: M15AnchoredInterpretationFrontier | None = None
    execution_handoff: M15SelectedExecutionHandoff | None = None

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))

    @property
    def session_hash(self) -> str:
        return str(self.payload["session_sha256"])


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15ClarificationTransportError(f"{name} is not a safe identifier")
    return value


def _sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise M15ClarificationTransportError(f"{name} is not a SHA-256 digest")
    return value


def _object(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise M15ClarificationTransportError(f"{name} must be an object")
    return copy.deepcopy(dict(value))


def _json_object(
    value: Mapping[str, Any] | str | Path,
    *,
    name: str,
) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise M15ClarificationTransportError(
            f"{name} must be a regular non-symbolic-link file"
        )
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise M15ClarificationTransportError(f"{name} is not valid JSON") from exc
    return _object(parsed, name=name)


def _file_sha256(value: str | Path, *, name: str) -> str:
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise M15ClarificationTransportError(
            f"{name} must be a regular non-symbolic-link file"
        )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _policy(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    raw = _json_object(value, name="clarification transport policy")
    expected_fields = {
        "schema_version",
        "policy_id",
        "purpose",
        "authority_event",
        "stages",
        "predicate_anchor_question",
        "terminal_behavior",
        "execution_handoff",
        "current_query_profile_calls",
        "backend_calls_made",
        "llm_calls_made",
        "ontology_service_calls_made",
        "automatic_retries",
        "paper_result",
    }
    if set(raw) != expected_fields:
        raise M15ClarificationTransportError(
            "clarification transport policy fields do not match the contract"
        )
    if (
        raw["schema_version"] != CLARIFICATION_TRANSPORT_POLICY_SCHEMA_VERSION
        or raw["policy_id"]
        != "m15-e5c-option-a-resumable-authority-transport-v1"
        or raw["purpose"] != "anchored_relaxation_execution"
    ):
        raise M15ClarificationTransportError(
            "clarification transport policy identity changed"
        )
    authority = _object(raw["authority_event"], name="authority event policy")
    if authority != {
        "source_kind": "explicit_user_input",
        "candidate_must_be_in_pending_question": True,
        "conversation_text_is_authoritative": False,
        "replay_binding": "session_sequence_question_sha256",
    }:
        raise M15ClarificationTransportError("authority event policy changed")
    if raw["stages"] != [
        {
            "sequence": 1,
            "hole_id": "relationship-strength",
            "role": "structural_r1_clarification",
        },
        {
            "sequence": 2,
            "hole_id": "transfer-predicate",
            "role": "predicate_base_authority_for_anchored_relaxation",
        },
    ]:
        raise M15ClarificationTransportError("clarification stages changed")
    predicate_question = _object(
        raw["predicate_anchor_question"], name="predicate anchor question"
    )
    if (
        set(predicate_question) != {"question", "options"}
        or not isinstance(predicate_question["question"], str)
        or not predicate_question["question"]
        or predicate_question["options"]
        != [
            {
                "candidate_id": "predicate:transferred_to",
                "label": "transferred_to",
            },
            {"candidate_id": "predicate:paid_to", "label": "paid_to"},
        ]
    ):
        raise M15ClarificationTransportError(
            "predicate anchor question changed"
        )
    if raw["terminal_behavior"] != {
        "selected_structure_unavailable": "stop_without_execution",
        "ready": "build_hash_bound_selected_execution_handoff",
    }:
        raise M15ClarificationTransportError("terminal behavior changed")
    if raw["execution_handoff"] != {
        "allowed_tools": [FEDERATED_EXECUTION_TOOL],
        "plan_source": "anchored_frontier.returned_interpretation_plans",
        "maximum_returned_plans": 4,
        "native_query_text_emitted": False,
    }:
        raise M15ClarificationTransportError("execution handoff policy changed")
    if (
        raw["current_query_profile_calls"] != 0
        or raw["backend_calls_made"] != 0
        or raw["llm_calls_made"] != 0
        or raw["ontology_service_calls_made"] != 0
        or raw["automatic_retries"] != 0
        or raw["paper_result"] is not False
    ):
        raise M15ClarificationTransportError(
            "clarification transport call or claim boundary changed"
        )
    return raw


def _question(
    *,
    session_id: str,
    sequence: int,
    hole_id: str,
    role: str,
    question: str,
    options: Sequence[Mapping[str, Any]],
    reason_codes: Sequence[str],
    varying_structural_dimensions: Sequence[str],
) -> dict[str, Any]:
    normalized_options: list[dict[str, str]] = []
    candidate_ids: list[str] = []
    for raw in options:
        option = _object(raw, name="clarification option")
        if set(option) != {"candidate_id", "label"}:
            raise M15ClarificationTransportError(
                "clarification option fields changed"
            )
        candidate_id = _safe_id(option["candidate_id"], name="candidate_id")
        label = option["label"]
        if not isinstance(label, str) or not label:
            raise M15ClarificationTransportError(
                "clarification option label is invalid"
            )
        candidate_ids.append(candidate_id)
        normalized_options.append({"candidate_id": candidate_id, "label": label})
    if not normalized_options or len(candidate_ids) != len(set(candidate_ids)):
        raise M15ClarificationTransportError(
            "clarification options must be nonempty and unique"
        )
    body = {
        "schema_version": "m15-e5c-bounded-question-v1",
        "question_id": f"{session_id}:q{sequence}:{hole_id}",
        "session_id": session_id,
        "sequence": sequence,
        "hole_id": hole_id,
        "role": role,
        "question": question,
        "options": normalized_options,
        "reason_codes": list(reason_codes),
        "varying_structural_dimensions": list(varying_structural_dimensions),
        "authoritative_response_required": True,
        "conversation_text_is_authoritative": False,
    }
    return {**body, "question_sha256": content_hash(body)}


def _verified_event(
    raw_value: Mapping[str, Any],
    *,
    question: Mapping[str, Any],
    session_id: str,
    expected_sequence: int,
    source_kind: str,
) -> dict[str, Any]:
    raw = _object(raw_value, name="authority event")
    if set(raw) != _AUTHORITY_EVENT_FIELDS:
        raise M15ClarificationTransportError(
            "authority event fields do not match the contract"
        )
    if raw["schema_version"] != CLARIFICATION_AUTHORITY_EVENT_SCHEMA_VERSION:
        raise M15ClarificationTransportError(
            "authority event schema is unsupported"
        )
    observed_hash = _sha256(
        raw["authority_event_sha256"], name="authority event hash"
    )
    if content_hash(
        {key: value for key, value in raw.items() if key != "authority_event_sha256"}
    ) != observed_hash:
        raise M15ClarificationTransportError("authority event hash mismatch")
    if (
        raw["session_id"] != session_id
        or raw["sequence"] != expected_sequence
        or raw["question_sha256"] != question["question_sha256"]
        or raw["hole_id"] != question["hole_id"]
    ):
        raise M15ClarificationTransportError(
            "authority event is not bound to the pending question"
        )
    _safe_id(raw["event_id"], name="event_id")
    _safe_id(raw["authority_source_id"], name="authority_source_id")
    candidate_id = _safe_id(raw["candidate_id"], name="candidate_id")
    allowed = {item["candidate_id"] for item in question["options"]}
    if candidate_id not in allowed:
        raise M15ClarificationTransportError(
            "authority event candidate is outside the pending bounded set"
        )
    if raw["source_kind"] != source_kind or raw["authoritative"] is not True:
        raise M15ClarificationTransportError(
            "authority event is not explicit authoritative user input"
        )
    return raw


def _session_source_contract(
    *,
    bridge: M15ResolutionExecutionBridgePlan,
    workload: M15DirectSemanticWorkloadBundle,
    memory: M15DirectTrainingMemoryView,
    predictor_policy: Mapping[str, Any] | str | Path,
    interpretation_policy: Mapping[str, Any] | str | Path,
    ontology_path: str | Path,
    relaxation_policy: Mapping[str, Any] | str | Path,
    transport_policy: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "bridge_plan_sha256": bridge.plan_hash,
        "workload_manifest_sha256": content_hash(workload.to_dict()),
        "training_memory_view_sha256": memory.memory_view_hash,
        "predictor_policy_sha256": content_hash(
            _json_object(predictor_policy, name="predictor policy")
        ),
        "interpretation_policy_sha256": content_hash(
            _json_object(interpretation_policy, name="interpretation policy")
        ),
        "ontology_sha256": _file_sha256(
            ontology_path, name="resolution ontology"
        ),
        "relaxation_policy_sha256": content_hash(
            _json_object(relaxation_policy, name="relaxation policy")
        ),
        "transport_policy_sha256": content_hash(transport_policy),
    }


def _hierarchical_summary(
    frontier: M15HierarchicalInterpretationFrontier,
) -> dict[str, Any]:
    payload = frontier.to_dict()
    return {
        "hierarchical_frontier_sha256": frontier.frontier_hash,
        "status": payload["status"],
        "clarification_required": payload["clarification_required"],
        "execution_eligible": payload["execution_eligible"],
        "authoritative_structural_selections": copy.deepcopy(
            payload["authoritative_structural_selections"]
        ),
        "authority_source_id": payload["authority_source_id"],
        "active_interpretation_class_ids": list(
            payload["active_interpretation_class_ids"]
        ),
        "returned_interpretation_plans": copy.deepcopy(
            payload["returned_interpretation_plans"]
        ),
        "counts": copy.deepcopy(payload["counts"]),
    }


def _anchored_summary(frontier: M15AnchoredInterpretationFrontier) -> dict[str, Any]:
    payload = frontier.to_dict()
    return {
        "anchored_frontier_sha256": frontier.frontier_hash,
        "status": payload["status"],
        "authoritative_base": copy.deepcopy(payload["authoritative_base"]),
        "returned_interpretation_plans": copy.deepcopy(
            payload["returned_interpretation_plans"]
        ),
        "counts": copy.deepcopy(payload["counts"]),
    }


def _selected_execution_handoff(
    *,
    session_id: str,
    session_state_sha256: str,
    authority_event_chain_sha256: str,
    anchored: M15AnchoredInterpretationFrontier,
    bridge: M15ResolutionExecutionBridgePlan,
    maximum_returned_plans: int,
) -> M15SelectedExecutionHandoff:
    anchored_payload = anchored.to_dict()
    if content_hash(
        {
            key: value
            for key, value in anchored_payload.items()
            if key != "anchored_frontier_sha256"
        }
    ) != anchored.frontier_hash:
        raise M15ClarificationTransportError("anchored frontier hash mismatch")
    if anchored_payload["bridge_plan_sha256"] != bridge.plan_hash:
        raise M15ClarificationTransportError(
            "anchored frontier and runtime bridge identity differ"
        )
    returned = anchored_payload["returned_interpretation_plans"]
    if (
        not isinstance(returned, list)
        or not returned
        or len(returned) > maximum_returned_plans
    ):
        raise M15ClarificationTransportError(
            "anchored frontier returned-plan cardinality is invalid"
        )
    bridge_payload = bridge.to_dict()
    candidates = {
        item["plan_id"]: item for item in bridge_payload["physical_candidates"]
    }
    selected_plans: dict[str, FederatedExecutionPlan] = {}
    descriptors: list[dict[str, Any]] = []
    for expected_rank, item in enumerate(returned, 1):
        plan_id = _safe_id(item.get("plan_id"), name="returned plan_id")
        if item.get("selection_rank") != expected_rank:
            raise M15ClarificationTransportError(
                "returned interpretation plan ranks are not contiguous"
            )
        if plan_id in selected_plans or plan_id not in bridge.plans:
            raise M15ClarificationTransportError(
                "returned interpretation references an unknown or duplicate plan"
            )
        candidate = candidates.get(plan_id)
        if (
            candidate is None
            or candidate["semantic_class_id"] != item["interpretation_class_id"]
            or candidate["physical_strategy"] != item["physical_strategy"]
        ):
            raise M15ClarificationTransportError(
                "returned interpretation and E4 physical candidate differ"
            )
        runtime_plan = bridge.plans[plan_id]
        remote_calls = sum(
            node.kind
            in {RuntimeNodeKind.REMOTE_QUERY, RuntimeNodeKind.REMOTE_BIND_QUERY}
            for node in runtime_plan.nodes
        )
        selected_plans[plan_id] = runtime_plan
        descriptors.append(
            {
                "selection_rank": expected_rank,
                "interpretation_class_id": item["interpretation_class_id"],
                "interpretation_status": item["interpretation_status"],
                "semantic_deviation": item["semantic_deviation"],
                "selected_candidate_ids": copy.deepcopy(
                    item["selected_candidate_ids"]
                ),
                "plan_id": plan_id,
                "query_id": candidate["query_id"],
                "physical_strategy": candidate["physical_strategy"],
                "runtime_plan_sha256": content_hash(runtime_plan.to_dict()),
                "remote_call_budget": runtime_plan.max_remote_calls,
                "expected_remote_calls": remote_calls,
            }
        )
    body = {
        "schema_version": SELECTED_EXECUTION_HANDOFF_SCHEMA_VERSION,
        "session_id": session_id,
        "session_state_sha256": session_state_sha256,
        "authority_event_chain_sha256": authority_event_chain_sha256,
        "bridge_plan_sha256": bridge.plan_hash,
        "anchored_frontier_sha256": anchored.frontier_hash,
        "resolution_commit_sha256": anchored_payload["resolution_commit_sha256"],
        "hard_constraints_sha256": anchored_payload["hard_constraints_sha256"],
        "returned_interpretation_plans_sha256": content_hash(returned),
        "selected_plans": descriptors,
        "selected_plan_ids": [item["plan_id"] for item in descriptors],
        "counts": {
            "selected_interpretation_plans": len(descriptors),
            "selected_runtime_plans": len(selected_plans),
            "expected_remote_calls": sum(
                item["expected_remote_calls"] for item in descriptors
            ),
            "current_query_profile_calls": 0,
        },
        "execution_contract": {
            "allowed_tools": [FEDERATED_EXECUTION_TOOL],
            "plan_source": "anchored_frontier.returned_interpretation_plans",
            "all_and_only_returned_plans_attached": True,
            "execution_order": "selection_rank",
            "automatic_retries": 0,
        },
        "claim_boundary": {
            "artifact_class": "offline_selected_execution_handoff",
            "development_artifacts_only": True,
            "hard_constraints_preserved": True,
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
        },
        "paper_result": False,
    }
    return M15SelectedExecutionHandoff(
        payload={**body, "execution_handoff_sha256": content_hash(body)},
        plans=selected_plans,
    )


def compile_m15_clarification_transport_session(
    *,
    session_id: str,
    bridge: M15ResolutionExecutionBridgePlan,
    workload: M15DirectSemanticWorkloadBundle,
    memory: M15DirectTrainingMemoryView,
    predictor_policy: Mapping[str, Any] | str | Path,
    interpretation_policy: Mapping[str, Any] | str | Path,
    ontology_path: str | Path,
    relaxation_policy: Mapping[str, Any] | str | Path,
    transport_policy: Mapping[str, Any] | str | Path,
    authority_events: Sequence[Mapping[str, Any]] = (),
) -> M15ClarificationTransportSession:
    """Reconstruct one E5C session from its sealed inputs and event log."""

    normalized_session_id = _safe_id(session_id, name="session_id")
    selected_policy = _policy(transport_policy)
    events = list(authority_events)
    if len(events) > 2:
        raise M15ClarificationTransportError(
            "clarification transport accepts at most two authority events"
        )
    unresolved = select_m15_hierarchical_interpretation_frontier(
        bridge=bridge,
        workload=workload,
        memory=memory,
        predictor_policy=predictor_policy,
        interpretation_policy=interpretation_policy,
    )
    unresolved_payload = unresolved.to_dict()
    requests = unresolved_payload["clarification_requests"]
    if (
        unresolved_payload["status"] != "clarification_required"
        or len(requests) != 1
        or requests[0]["hole_id"] != "relationship-strength"
    ):
        raise M15ClarificationTransportError(
            "E5C requires exactly one unresolved R1 structural question"
        )
    request = requests[0]
    structural_question = _question(
        session_id=normalized_session_id,
        sequence=1,
        hole_id=request["hole_id"],
        role="structural_r1_clarification",
        question=request["question"],
        options=request["options"],
        reason_codes=request["reason_codes"],
        varying_structural_dimensions=request[
            "varying_structural_dimensions"
        ],
    )
    source_kind = selected_policy["authority_event"]["source_kind"]
    verified_events: list[dict[str, Any]] = []
    hierarchical = unresolved
    anchored: M15AnchoredInterpretationFrontier | None = None
    pending_question: dict[str, Any] | None = structural_question
    status = "awaiting_structural_clarification"

    if events:
        structural_event = _verified_event(
            events[0],
            question=structural_question,
            session_id=normalized_session_id,
            expected_sequence=1,
            source_kind=source_kind,
        )
        verified_events.append(structural_event)
        hierarchical = select_m15_hierarchical_interpretation_frontier(
            bridge=bridge,
            workload=workload,
            memory=memory,
            predictor_policy=predictor_policy,
            interpretation_policy=interpretation_policy,
            authoritative_selections={
                structural_event["hole_id"]: structural_event["candidate_id"]
            },
            authority_source_id=structural_event["authority_source_id"],
        )
        hierarchical_payload = hierarchical.to_dict()
        if (
            hierarchical_payload["status"]
            == "authoritatively_selected_structure_unavailable"
        ):
            status = "selected_structure_unavailable"
            pending_question = None
            if len(events) != 1:
                raise M15ClarificationTransportError(
                    "an unavailable structural selection is terminal"
                )
        elif hierarchical_payload["status"] == "ready_with_bounded_representatives":
            active_predicates = sorted(
                {
                    item["selected_candidate_ids"]["transfer-predicate"]
                    for item in hierarchical_payload[
                        "returned_interpretation_plans"
                    ]
                }
            )
            configured = selected_policy["predicate_anchor_question"]
            option_ids = sorted(
                item["candidate_id"] for item in configured["options"]
            )
            if active_predicates != option_ids:
                raise M15ClarificationTransportError(
                    "predicate anchor options differ from the active E5 set"
                )
            predicate_question = _question(
                session_id=normalized_session_id,
                sequence=2,
                hole_id="transfer-predicate",
                role="predicate_base_authority_for_anchored_relaxation",
                question=configured["question"],
                options=configured["options"],
                reason_codes=["anchored_relaxation_requires_authoritative_base"],
                varying_structural_dimensions=[],
            )
            status = "awaiting_predicate_base_authority"
            pending_question = predicate_question
            if len(events) == 2:
                predicate_event = _verified_event(
                    events[1],
                    question=predicate_question,
                    session_id=normalized_session_id,
                    expected_sequence=2,
                    source_kind=source_kind,
                )
                if predicate_event["event_id"] == structural_event["event_id"]:
                    raise M15ClarificationTransportError(
                        "authority event IDs must be unique"
                    )
                verified_events.append(predicate_event)
                anchored = select_m15_anchored_interpretation_frontier(
                    hierarchical_frontier=hierarchical,
                    bridge=bridge,
                    ontology_path=ontology_path,
                    relaxation_policy=relaxation_policy,
                    authoritative_base_candidate_id=predicate_event[
                        "candidate_id"
                    ],
                    authority_source_id=predicate_event[
                        "authority_source_id"
                    ],
                )
                status = "ready_for_execution_handoff"
                pending_question = None
        else:
            raise M15ClarificationTransportError(
                "authoritative structural selection produced an unknown state"
            )

    source_contract = _session_source_contract(
        bridge=bridge,
        workload=workload,
        memory=memory,
        predictor_policy=predictor_policy,
        interpretation_policy=interpretation_policy,
        ontology_path=ontology_path,
        relaxation_policy=relaxation_policy,
        transport_policy=selected_policy,
    )
    event_chain_sha256 = content_hash(verified_events)
    state_body = {
        "schema_version": CLARIFICATION_TRANSPORT_SESSION_SCHEMA_VERSION,
        "session_id": normalized_session_id,
        "purpose": selected_policy["purpose"],
        "status": status,
        "source_contract": source_contract,
        "authority_events": verified_events,
        "authority_event_chain_sha256": event_chain_sha256,
        "pending_question": pending_question,
        "hierarchical_state": _hierarchical_summary(hierarchical),
        "anchored_state": (
            _anchored_summary(anchored) if anchored is not None else None
        ),
        "execution_eligible": anchored is not None,
        "terminal": status
        in {"selected_structure_unavailable", "ready_for_execution_handoff"},
        "claim_boundary": {
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
        },
        "paper_result": False,
    }
    state_sha256 = content_hash(state_body)
    handoff = None
    if anchored is not None:
        handoff = _selected_execution_handoff(
            session_id=normalized_session_id,
            session_state_sha256=state_sha256,
            authority_event_chain_sha256=event_chain_sha256,
            anchored=anchored,
            bridge=bridge,
            maximum_returned_plans=selected_policy["execution_handoff"][
                "maximum_returned_plans"
            ],
        )
    body = {
        **state_body,
        "session_state_sha256": state_sha256,
        "execution_handoff": handoff.to_dict() if handoff is not None else None,
    }
    return M15ClarificationTransportSession(
        payload={**body, "session_sha256": content_hash(body)},
        hierarchical_frontier=hierarchical,
        anchored_frontier=anchored,
        execution_handoff=handoff,
    )


def build_m15_clarification_authority_event(
    *,
    session: M15ClarificationTransportSession,
    event_id: str,
    candidate_id: str,
    authority_source_id: str,
) -> dict[str, Any]:
    """Create one explicit event bound to the session's pending question."""

    payload = session.to_dict()
    _verify_session(payload)
    question = payload.get("pending_question")
    if not isinstance(question, Mapping):
        raise M15ClarificationTransportError(
            "session has no pending clarification question"
        )
    selected = _safe_id(candidate_id, name="candidate_id")
    allowed = {item["candidate_id"] for item in question["options"]}
    if selected not in allowed:
        raise M15ClarificationTransportError(
            "authority event candidate is outside the pending bounded set"
        )
    body = {
        "schema_version": CLARIFICATION_AUTHORITY_EVENT_SCHEMA_VERSION,
        "event_id": _safe_id(event_id, name="event_id"),
        "session_id": payload["session_id"],
        "sequence": question["sequence"],
        "question_sha256": question["question_sha256"],
        "hole_id": question["hole_id"],
        "candidate_id": selected,
        "authority_source_id": _safe_id(
            authority_source_id, name="authority_source_id"
        ),
        "source_kind": "explicit_user_input",
        "authoritative": True,
    }
    return {**body, "authority_event_sha256": content_hash(body)}


def _verify_session(payload: Mapping[str, Any]) -> None:
    observed = _sha256(payload.get("session_sha256"), name="session hash")
    if content_hash(
        {key: value for key, value in payload.items() if key != "session_sha256"}
    ) != observed:
        raise M15ClarificationTransportError("clarification session hash mismatch")


def advance_m15_clarification_transport_session(
    *,
    session: M15ClarificationTransportSession,
    authority_event: Mapping[str, Any],
    bridge: M15ResolutionExecutionBridgePlan,
    workload: M15DirectSemanticWorkloadBundle,
    memory: M15DirectTrainingMemoryView,
    predictor_policy: Mapping[str, Any] | str | Path,
    interpretation_policy: Mapping[str, Any] | str | Path,
    ontology_path: str | Path,
    relaxation_policy: Mapping[str, Any] | str | Path,
    transport_policy: Mapping[str, Any] | str | Path,
) -> M15ClarificationTransportSession:
    """Rebuild the prior state, then append exactly one bounded event."""

    payload = session.to_dict()
    _verify_session(payload)
    previous = compile_m15_clarification_transport_session(
        session_id=payload["session_id"],
        bridge=bridge,
        workload=workload,
        memory=memory,
        predictor_policy=predictor_policy,
        interpretation_policy=interpretation_policy,
        ontology_path=ontology_path,
        relaxation_policy=relaxation_policy,
        transport_policy=transport_policy,
        authority_events=payload["authority_events"],
    )
    if previous.to_dict() != payload:
        raise M15ClarificationTransportError(
            "persisted clarification session does not reconstruct exactly"
        )
    if payload["terminal"]:
        raise M15ClarificationTransportError(
            "terminal clarification session cannot accept another event"
        )
    return compile_m15_clarification_transport_session(
        session_id=payload["session_id"],
        bridge=bridge,
        workload=workload,
        memory=memory,
        predictor_policy=predictor_policy,
        interpretation_policy=interpretation_policy,
        ontology_path=ontology_path,
        relaxation_policy=relaxation_policy,
        transport_policy=transport_policy,
        authority_events=[*payload["authority_events"], authority_event],
    )
