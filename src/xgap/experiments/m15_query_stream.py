"""Compile explicit, auditable task streams from an M15 query-bound campaign.

The F2 campaign originally represented measured work as the Cartesian product
of ``query_ids`` and ``measured_run_ids``.  That is sufficient for counting,
but it is not a safe execution or memory protocol: a task has no unique
identity and the history visible before that task is undefined.  This module
expands one selected session into ordered tasks and freezes those boundaries.

Compilation is side-effect free.  It makes no backend, LLM, or ontology call
and deliberately does not claim that a cross-task transfer model exists.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_method_policy import (
    M15_METHOD_POLICIES,
    M15Method,
)
from xgap.experiments.m15_query_bound_campaign import (
    QUERY_BOUND_CAMPAIGN_PLAN_SCHEMA_VERSION,
    compile_m15_query_bound_campaign_file,
)


QUERY_STREAM_PLAN_SCHEMA_VERSION = "m15-f2c-query-stream-plan-v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class M15QueryStreamError(ValueError):
    """Raised before output when a query stream contract is invalid."""


@dataclass(frozen=True)
class M15QueryStreamPlan:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)

    @property
    def stream_hash(self) -> str:
        return str(self.payload["query_stream_sha256"])


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15QueryStreamError(f"{name} must be a safe identifier")
    return value


def _sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise M15QueryStreamError(f"{name} must be a SHA-256 digest")
    return value


def _list(value: object, *, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise M15QueryStreamError(f"{name} must be a list")
    return value


def _object(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise M15QueryStreamError(f"{name} must be an object")
    return dict(value)


def _query_ref(value: object, *, name: str) -> dict[str, str]:
    raw = _object(value, name=name)
    fields = {
        "query_id",
        "expected_query_spec_sha256",
        "expected_query_contract_sha256",
    }
    if set(raw) != fields:
        raise M15QueryStreamError(
            f"{name} fields do not match the query contract reference"
        )
    return {
        "query_id": _safe_id(raw["query_id"], name=f"{name}.query_id"),
        "expected_query_spec_sha256": _sha256(
            raw["expected_query_spec_sha256"],
            name=f"{name}.expected_query_spec_sha256",
        ),
        "expected_query_contract_sha256": _sha256(
            raw["expected_query_contract_sha256"],
            name=f"{name}.expected_query_contract_sha256",
        ),
    }


def _task_id(*, logical_run_id: str, query_index: int, query_id: str) -> str:
    suffix = content_hash(
        {
            "logical_run_id": logical_run_id,
            "query_index": query_index,
            "query_id": query_id,
        }
    )[:12]
    return f"{logical_run_id}.q{query_index:03d}-{suffix}"


def compile_m15_query_stream(
    query_bound_plan: Mapping[str, Any],
    *,
    session_id: str,
    expected_registry_spec_sha256: str,
    expected_query_bound_schedule_sha256: str,
) -> M15QueryStreamPlan:
    """Expand one hash-bound session into explicit method-local task streams."""

    plan = _object(query_bound_plan, name="query-bound campaign plan")
    if plan.get("schema_version") != QUERY_BOUND_CAMPAIGN_PLAN_SCHEMA_VERSION:
        raise M15QueryStreamError("query-bound campaign schema_version is unsupported")
    selected_session_id = _safe_id(session_id, name="session_id")
    registry_hash = _sha256(
        expected_registry_spec_sha256,
        name="expected_registry_spec_sha256",
    )
    schedule_hash = _sha256(
        expected_query_bound_schedule_sha256,
        name="expected_query_bound_schedule_sha256",
    )
    if plan.get("registry_spec_sha256") != registry_hash:
        raise M15QueryStreamError("query-bound registry spec hash drifted")
    if plan.get("query_bound_schedule_sha256") != schedule_hash:
        raise M15QueryStreamError("query-bound schedule hash drifted")
    if plan.get("automatic_retries") != 0 or plan.get("paper_result") is not False:
        raise M15QueryStreamError(
            "query-bound campaign must disable retry and remain paper_result=false"
        )

    query_bindings = [
        _object(item, name="query binding")
        for item in _list(plan.get("query_bindings"), name="query_bindings")
    ]
    portable_bindings = [
        {
            key: value
            for key, value in item.items()
            if key not in {"query_spec_path", "query_contract_verification"}
        }
        for item in query_bindings
    ]
    observed_binding_hash = content_hash(portable_bindings)
    if plan.get("query_binding_sha256") != observed_binding_hash:
        raise M15QueryStreamError("query binding payload hash drifted")
    base_campaign = _object(plan.get("base_campaign"), name="base_campaign")
    base_schedule_hash = _sha256(
        base_campaign.get("schedule_sha256"),
        name="base_campaign.schedule_sha256",
    )
    all_sessions = _list(plan.get("sessions"), name="sessions")
    observed_schedule_hash = content_hash(
        {
            "registry_id": plan.get("registry_id"),
            "base_schedule_sha256": base_schedule_hash,
            "query_binding_sha256": observed_binding_hash,
            "sessions": all_sessions,
        }
    )
    if observed_schedule_hash != schedule_hash:
        raise M15QueryStreamError("query-bound session payload hash drifted")

    matches = [
        _object(item, name="session")
        for item in all_sessions
        if isinstance(item, Mapping) and item.get("session_id") == selected_session_id
    ]
    if len(matches) != 1:
        raise M15QueryStreamError("session_id must select exactly one session")
    session = matches[0]
    if session.get("automatic_retries") != 0:
        raise M15QueryStreamError("selected session must disable automatic retries")

    query_refs = [
        _query_ref(item, name=f"session.query_contract_refs[{index}]")
        for index, item in enumerate(
            _list(session.get("query_contract_refs"), name="query_contract_refs")
        )
    ]
    if not query_refs:
        raise M15QueryStreamError("selected session requires query contract references")
    query_ids = [item["query_id"] for item in query_refs]
    if len(query_ids) != len(set(query_ids)):
        raise M15QueryStreamError("session query contract IDs must be unique")
    workload_label = _safe_id(
        session.get("workload_label"), name="workload_label"
    )
    bound_refs: dict[str, dict[str, str]] = {}
    for index, binding in enumerate(query_bindings):
        if binding.get("workload_label") != workload_label:
            continue
        ref = _query_ref(
            {
                key: binding.get(key)
                for key in (
                    "query_id",
                    "expected_query_spec_sha256",
                    "expected_query_contract_sha256",
                )
            },
            name=f"query_bindings[{index}]",
        )
        if ref["query_id"] in bound_refs:
            raise M15QueryStreamError(
                "query bindings contain duplicate workload/query keys"
            )
        bound_refs[ref["query_id"]] = ref
    if bound_refs != {item["query_id"]: item for item in query_refs}:
        raise M15QueryStreamError(
            "selected session query contracts disagree with query bindings"
        )

    method_order = [
        _safe_id(item, name="method_order[]")
        for item in _list(session.get("method_order"), name="method_order")
    ]
    raw_streams = _list(session.get("method_streams"), name="method_streams")
    if len(raw_streams) != len(method_order):
        raise M15QueryStreamError("method stream count disagrees with method order")

    compiled_streams: list[dict[str, Any]] = []
    all_tasks: list[dict[str, Any]] = []
    task_ids: set[str] = set()
    measured_tasks_per_stream: list[int] = []
    global_task_index = 0
    for method_index, raw_stream in enumerate(raw_streams, start=1):
        stream = _object(raw_stream, name="method stream")
        method_name = _safe_id(stream.get("method"), name="method")
        if method_name != method_order[method_index - 1]:
            raise M15QueryStreamError("method stream order disagrees with method_order")
        try:
            method = M15Method(method_name)
        except ValueError as exc:
            raise M15QueryStreamError(f"unsupported method: {method_name}") from exc
        if stream.get("position") != method_index:
            raise M15QueryStreamError("method stream position is not canonical")
        namespace = _safe_id(
            stream.get("memory_namespace"),
            name="memory_namespace",
        )
        stream_query_ids = [
            _safe_id(item, name="method_stream.query_ids[]")
            for item in _list(stream.get("query_ids"), name="method_stream.query_ids")
        ]
        stream_refs = [
            _query_ref(item, name="method_stream.query_contract_refs[]")
            for item in _list(
                stream.get("query_contract_refs"),
                name="method_stream.query_contract_refs",
            )
        ]
        if stream_query_ids != query_ids or stream_refs != query_refs:
            raise M15QueryStreamError(
                "method stream query contracts disagree with the selected session"
            )

        policy = M15_METHOD_POLICIES[method]
        policy_record = policy.to_dict()
        prior_tasks: list[str] = []
        stream_tasks: list[dict[str, Any]] = []
        phase_counts: dict[str, int] = {}
        for phase, run_field in (
            ("warmup", "warmup_run_ids"),
            ("measured", "measured_run_ids"),
        ):
            run_ids = [
                _safe_id(item, name=f"method_stream.{run_field}[]")
                for item in _list(stream.get(run_field), name=run_field)
            ]
            if len(run_ids) != len(set(run_ids)):
                raise M15QueryStreamError(f"{run_field} must contain unique IDs")
            phase_counts[phase] = len(run_ids) * len(query_refs)
            for repetition_index, run_id in enumerate(run_ids, start=1):
                for query_index, ref in enumerate(query_refs, start=1):
                    global_task_index += 1
                    task_id = _task_id(
                        logical_run_id=run_id,
                        query_index=query_index,
                        query_id=ref["query_id"],
                    )
                    if task_id in task_ids:
                        raise M15QueryStreamError("expanded task IDs must be unique")
                    task_ids.add(task_id)
                    eligible = list(prior_tasks) if policy.read_memory else []
                    task = {
                        "task_id": task_id,
                        "task_index": global_task_index,
                        "stream_task_index": len(stream_tasks) + 1,
                        "logical_run_id": run_id,
                        "phase": phase,
                        "repetition_index": repetition_index,
                        "method": method.value,
                        "method_position": method_index,
                        "query_index": query_index,
                        **ref,
                        "memory": {
                            "namespace": namespace,
                            "read_enabled": policy.read_memory,
                            "write_enabled": policy.write_memory,
                            "pre_task_snapshot": "frozen_before_task_start",
                            "eligible_predecessor_task_ids": eligible,
                            "read_filter": (
                                "successful_exact_commits_only"
                                if policy.read_memory
                                else "disabled"
                            ),
                            "post_task_commit": (
                                "only_after_success_and_exact_answer"
                                if policy.write_memory
                                else "disabled"
                            ),
                            "within_task_updates_visible": False,
                        },
                    }
                    stream_tasks.append(task)
                    all_tasks.append(task)
                    if policy.write_memory:
                        prior_tasks.append(task_id)
        measured_tasks_per_stream.append(phase_counts["measured"])
        compiled_streams.append(
            {
                "method": method.value,
                "position": method_index,
                "memory_namespace": namespace,
                "method_policy": policy_record,
                "query_contract_refs": query_refs,
                "task_order": "phase_then_repetition_then_query",
                "expected_counts": phase_counts,
                "tasks": stream_tasks,
            }
        )

    namespaces = [item["memory_namespace"] for item in compiled_streams]
    if len(namespaces) != len(set(namespaces)):
        raise M15QueryStreamError("memory namespaces must be isolated by method stream")

    blockers = ["cross_task_transfer_model_not_bound"]
    if len(query_refs) < 2:
        blockers.extend(
            [
                "fewer_than_two_distinct_query_contracts_in_session",
                "query_instances_are_not_yet_parameterized",
            ]
        )
    if any(count < 2 for count in measured_tasks_per_stream):
        blockers.append("fewer_than_two_measured_tasks_per_method_stream")

    expected_counts = {
        "query_contracts": len(query_refs),
        "method_streams": len(compiled_streams),
        "warmup_tasks": sum(
            item["expected_counts"]["warmup"] for item in compiled_streams
        ),
        "measured_tasks": sum(measured_tasks_per_stream),
        "total_tasks": len(all_tasks),
    }
    design_validation = {
        "explicit_task_identity": True,
        "unique_task_ids": len(task_ids) == len(all_tasks),
        "method_memory_namespaces_isolated": True,
        "pre_task_history_frozen": True,
        "post_task_commit_success_and_exact_gated": True,
        "multi_task_memory_ready": not blockers,
        "blocking_conditions": blockers,
    }
    stream_body = {
        "source_binding": {
            "registry_id": _safe_id(plan.get("registry_id"), name="registry_id"),
            "registry_spec_sha256": registry_hash,
            "query_binding_sha256": _sha256(
                plan.get("query_binding_sha256"),
                name="query_binding_sha256",
            ),
            "query_bound_schedule_sha256": schedule_hash,
            "session_id": selected_session_id,
            "workload_label": workload_label,
            "workload_id": _safe_id(
                session.get("workload_id"), name="workload_id"
            ),
        },
        "execution_protocol": {
            "task_order": "method_then_phase_then_repetition_then_query",
            "memory_isolation": "one_namespace_per_method_session",
            "pre_task_snapshot": "frozen_before_task_start",
            "post_task_commit": "only_after_success_and_exact_answer",
            "within_task_memory_write": "prohibited",
            "failure_policy": session.get("failure_policy"),
            "automatic_retries": 0,
        },
        "query_contract_refs": query_refs,
        "method_streams": compiled_streams,
        "expected_counts": expected_counts,
        "design_validation": design_validation,
    }
    return M15QueryStreamPlan(
        {
            "schema_version": QUERY_STREAM_PLAN_SCHEMA_VERSION,
            **stream_body,
            "query_stream_sha256": content_hash(stream_body),
            "claim_boundary": {
                "artifact_class": "unexecuted_query_stream_plan",
                "backend_calls_made": 0,
                "llm_calls_made": 0,
                "ontology_calls_made": 0,
                "contains_measurements": False,
                "cross_task_memory_benefit_measured": False,
                "paper_comparison_ready": False,
                "paper_result": False,
            },
            "automatic_retries": 0,
            "paper_result": False,
        }
    )


def compile_m15_query_stream_file(
    registry_path: str | Path,
    *,
    session_id: str,
    expected_registry_spec_sha256: str,
    expected_query_bound_schedule_sha256: str,
    repo_root: str | Path | None = None,
) -> M15QueryStreamPlan:
    bound = compile_m15_query_bound_campaign_file(
        registry_path,
        repo_root=repo_root,
    )
    return compile_m15_query_stream(
        bound.to_dict(),
        session_id=session_id,
        expected_registry_spec_sha256=expected_registry_spec_sha256,
        expected_query_bound_schedule_sha256=(
            expected_query_bound_schedule_sha256
        ),
    )


def write_m15_query_stream_plan(
    plan: M15QueryStreamPlan,
    output: str | Path,
) -> Path:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"query stream plan exists: {destination}")
    destination.write_text(
        json.dumps(
            plan.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return destination


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--expected-registry-spec-sha256", required=True)
    parser.add_argument("--expected-query-bound-schedule-sha256", required=True)
    parser.add_argument("--repo-root")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        plan = compile_m15_query_stream_file(
            args.registry,
            session_id=args.session_id,
            expected_registry_spec_sha256=(
                args.expected_registry_spec_sha256
            ),
            expected_query_bound_schedule_sha256=(
                args.expected_query_bound_schedule_sha256
            ),
            repo_root=args.repo_root,
        )
        if args.output:
            write_m15_query_stream_plan(plan, args.output)
    except (FileExistsError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
