"""Read-only replay of recorded GrailQA preflight parsing and grounding."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.experiments.runtime_alignment import (
    PromptQuerySlot,
    PromptSchemaView,
    RetrievalLimits,
    RetrievedOntologyTerm,
    parse_grounded_planner_response,
)
from xgap.llm.schemas import PlannerRequest
from xgap.llm.inline_grounding import (
    SCHEMA_CONTRACT_KEY, materialize_inline_response, validate_response_contract,
)


class PreflightReplaySourceError(ValueError):
    """The recorded source cannot identify an exact request/response pair."""


def _object(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PreflightReplaySourceError(f"{name} must be an object")
    return value


def _task_id(row: Mapping[str, Any]) -> str:
    value = row.get("task_id")
    if not isinstance(value, str) or not value:
        raise PreflightReplaySourceError("Every ledger row requires a task_id")
    return value


def _load_ledger(path: Path) -> tuple[list[Mapping[str, Any]], str]:
    data = path.read_bytes()
    rows = [
        _object(json.loads(line), f"{path.name}:{index}")
        for index, line in enumerate(data.splitlines(), start=1)
        if line.strip()
    ]
    if not rows:
        raise PreflightReplaySourceError(f"{path.name} is empty")
    return rows, hashlib.sha256(data).hexdigest()


def _reconstruct_request(
    request_rows: Sequence[Mapping[str, Any]], response: Mapping[str, Any]
) -> tuple[PlannerRequest, PromptSchemaView]:
    task_id = _task_id(response)
    call_indexes = [row.get("call_index") for row in request_rows]
    if any(type(index) is not int for index in call_indexes):
        raise PreflightReplaySourceError(f"{task_id}: invalid request call_index")
    ordered = sorted(request_rows, key=lambda row: row["call_index"])
    if [row["call_index"] for row in ordered] != list(range(1, len(ordered) + 1)):
        raise PreflightReplaySourceError(f"{task_id}: missing or duplicate request call")
    if not ordered or ordered[0].get("call_kind") != "generation":
        raise PreflightReplaySourceError(f"{task_id}: initial generation request is missing")
    if any(row.get("call_kind") != "repair" for row in ordered[1:]):
        raise PreflightReplaySourceError(f"{task_id}: unexpected subsequent request kind")
    hashes = []
    for row in ordered:
        payload = _object(row.get("payload"), "request payload")
        digest = content_hash(payload)
        if row.get("payload_hash") != digest:
            raise PreflightReplaySourceError(f"{task_id}: request payload hash mismatch")
        hashes.append(digest)
    if response.get("assembled_request_hashes") != hashes:
        raise PreflightReplaySourceError(f"{task_id}: response/request identity mismatch")
    payload = ordered[0]["payload"]
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise PreflightReplaySourceError(f"{task_id}: request messages are missing")
    users = [item for item in messages if isinstance(item, Mapping) and item.get("role") == "user"]
    if len(users) != 1:
        raise PreflightReplaySourceError(f"{task_id}: expected one initial user payload")
    user = _object(json.loads(users[0]["content"]), "recorded user payload")
    contract = validate_response_contract(response.get("generation_parameters", {}).get("response_contract"))
    schema = _object(user.get("structured_output_schema", {}), "recorded response schema")
    if schema.get(SCHEMA_CONTRACT_KEY) != contract:
        raise PreflightReplaySourceError("Recorded wire schema/materialization contract mismatch")
    value = _object(user.get("prompt_schema_view"), "recorded prompt view")
    view = PromptSchemaView(
        task_id=value["task_id"],
        ontology_id=value["ontology"]["id"],
        ontology_version=value["ontology"]["version"],
        ontology_hash=value["ontology"]["hash"],
        schema_snapshot_version=value["schema_snapshot"]["version"],
        schema_snapshot_hash=value["schema_snapshot"]["hash"],
        terms=tuple(RetrievedOntologyTerm(**item) for item in value["terms"]),
        entities=tuple(value["entities"]),
        query_slots=tuple(PromptQuerySlot(**item) for item in value["query_slots"]),
        backend_hints=value["backend_hints"],
        source_schema_items=tuple(value["source_schema_items"]),
        limits=RetrievalLimits(**value["retrieval"]["limits"]),
        retrieval_method=value["retrieval"]["method"],
        schema_version=value["schema_version"],
    )
    if user.get("task_id") != task_id or view.task_id != task_id:
        raise PreflightReplaySourceError(f"{task_id}: recorded task identity mismatch")
    if view.to_dict() != value or view.view_hash != response.get("prompt_schema_view_hash"):
        raise PreflightReplaySourceError(f"{task_id}: recorded prompt-view identity mismatch")
    request = PlannerRequest(
        question=user["question"],
        max_candidates=user["max_candidates"],
        schema_hints=tuple(user["schema_hints"]),
        metadata={"task_id": task_id, "prompt_schema_view": value},
    )
    return request, view


def _replay_response(
    request: PlannerRequest, view: PromptSchemaView, response: Mapping[str, Any]
) -> dict[str, Any]:
    raw = response.get("structured_response")
    candidates = raw.get("candidates") if isinstance(raw, Mapping) else None
    result = {
        "question_id": _task_id(response),
        "provider_validation": response.get("validation_status"),
        "raw_candidate_count": len(candidates) if isinstance(candidates, list) else 0,
    }
    if raw is None:
        if response.get("validation_status") != "failed":
            raise PreflightReplaySourceError("Missing structured response without provider failure")
        return {
            **result,
            "stage": "provider_failed",
            "error_type": response.get("failure_category"),
            "message": response.get("error_message"),
        }
    if response.get("validation_status") != "schema_valid" or not isinstance(raw, Mapping):
        raise PreflightReplaySourceError("Structured response/provider status mismatch")
    contract = validate_response_contract(response.get("generation_parameters", {}).get("response_contract"))
    receipts = response.get("response_materializations", [])
    if contract is not None:
        # Recompute the transformation from preserved model bytes. Never trust
        # a recorded derived body merely because its own hash is consistent.
        if not isinstance(receipts, list) or not receipts:
            raise PreflightReplaySourceError("Inline response lacks its materialization receipt")
        receipt = _object(receipts[-1], "materialization receipt")
        effective = materialize_inline_response(raw, entity_identity_property=contract["entity_identity_property"])
        hashes = response.get("assembled_request_hashes")
        raw_responses = response.get("raw_responses")
        if not isinstance(hashes, list) or not hashes or not isinstance(raw_responses, list) or not raw_responses:
            raise PreflightReplaySourceError("Inline response lacks source call evidence")
        try:
            last_wire = raw_responses[-1]["choices"][0]["message"]["content"]
            last_wire = json.loads(last_wire) if isinstance(last_wire, str) else last_wire
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise PreflightReplaySourceError("Inline source response is malformed") from error
        if (receipt.get("status") != "materialized" or receipt.get("contract") != contract
                or type(receipt.get("call_index")) is not int or receipt["call_index"] != len(hashes)
                or receipt.get("request_payload_sha256") != hashes[-1]
                or receipt.get("source_response_sha256") != content_hash(raw)
                or last_wire != raw
                or receipt.get("materialized_response_sha256") != content_hash(effective)
                or receipt.get("materialized_response") != effective):
            raise PreflightReplaySourceError("Inline materialization does not reproduce its source evidence")
        raw = effective
        result["response_contract"] = contract
        result["materialization_recomputed"] = True
    elif receipts:
        raise PreflightReplaySourceError("Undeclared response materialization")
    stage = "normalized_parser_rejected"
    try:
        parsed = parse_normalized_planner_response(raw, request)
        stage = "grounding_rejected"
        grounded = parse_grounded_planner_response(raw, parsed, view)
    except Exception as error:  # noqa: BLE001 - expose deterministic rejection diagnostics.
        category = getattr(error, "category", None)
        return {
            **result,
            "stage": stage,
            "error_type": type(error).__name__,
            "category": getattr(category, "value", None),
            "message": str(error),
        }
    return {
        **result,
        "stage": "grounding_passed",
        "grounded_candidate_count": len(grounded.grounded_candidates),
    }


def replay_grailqa_preflight(*, run_root: str | Path) -> dict[str, Any]:
    """Replay only retained provider envelopes; never load catalog or gold."""

    root = Path(run_root)
    requests, request_hash = _load_ledger(root / "llm_requests.jsonl")
    responses, response_hash = _load_ledger(root / "llm_responses.jsonl")
    requests_by_task: dict[str, list[Mapping[str, Any]]] = {}
    for row in requests:
        requests_by_task.setdefault(_task_id(row), []).append(row)
    response_ids = [_task_id(row) for row in responses]
    if len(response_ids) != len(set(response_ids)):
        raise PreflightReplaySourceError("Duplicate response task_id")
    if set(response_ids) != set(requests_by_task):
        raise PreflightReplaySourceError("Request and response task sets differ")
    results = []
    for response in responses:
        task_id = _task_id(response)
        try:
            request, view = _reconstruct_request(requests_by_task[task_id], response)
        except (KeyError, TypeError, ValueError) as error:
            raise PreflightReplaySourceError(f"{task_id}: invalid recorded request: {error}") from error
        results.append(_replay_response(request, view, response))
    return {
        "schema_version": "grailqa-preflight-replay-v1",
        "status": "complete",
        "input_sha256": {
            "llm_requests.jsonl": request_hash,
            "llm_responses.jsonl": response_hash,
        },
        "counts": {
            "queries": len(results),
            "raw_candidates": sum(row["raw_candidate_count"] for row in results),
            "by_stage": dict(sorted(Counter(row["stage"] for row in results).items())),
        },
        "queries": results,
        "external_call_counts": {"llm_calls": 0, "backend_calls": 0, "ontology_service_calls": 0},
        "paper_result": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    args = parser.parse_args(argv)
    try:
        result = replay_grailqa_preflight(run_root=args.run_root)
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(json.dumps({"status": "configuration_error", "error": str(error), "paper_result": False}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
