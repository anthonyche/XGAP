"""Deterministic campaign planning for M15 live method comparisons.

Compilation is deliberately side-effect free with respect to experimental
systems: it starts no service and invokes no backend, ontology, or model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_method_policy import M15Method
from xgap.experiments.m15_workload import M15WorkloadSpec


CAMPAIGN_SPEC_SCHEMA_VERSION = "m15-f2-campaign-spec-v1"
CAMPAIGN_PLAN_SCHEMA_VERSION = "m15-f2-campaign-plan-v1"
ORDER_DESIGN_VERSION = "m15-f2-williams-even-v1"

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CANONICAL_METHODS = tuple(M15Method)
_ORDER_DESIGN = "williams_balanced_first_order"
_SERVICE_POLICY = "fresh_neo4j_fuseki_pair_per_sequence"
_CACHE_POLICY = "shared_unflushed_within_sequence_counterbalanced"
_CALIBRATION_POLICY = "common_three_profile_calibration_per_sequence_excluded"
_MEMORY_POLICY = "isolated_per_method_sequence_seeded_from_common_calibration"
_FAILURE_POLICY = "stop_sequence_no_retry"


class M15CampaignError(ValueError):
    """Raised before output when a campaign contract is invalid."""


def _strict_object(
    value: object,
    *,
    name: str,
    fields: set[str],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise M15CampaignError(f"{name} must be an object")
    result = dict(value)
    unknown = set(result) - fields
    missing = fields - set(result)
    if unknown:
        raise M15CampaignError(
            f"unknown {name} fields: {', '.join(sorted(unknown))}"
        )
    if missing:
        raise M15CampaignError(
            f"missing {name} fields: {', '.join(sorted(missing))}"
        )
    return result


def _bounded_int(
    value: object,
    *,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise M15CampaignError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise M15CampaignError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15CampaignError(
            f"{name} must match [A-Za-z0-9][A-Za-z0-9._-]{{0,127}}"
        )
    return value


def _nonempty(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise M15CampaignError(f"{name} must be a nonempty string")
    return value


def _unique_strings(
    value: object,
    *,
    name: str,
    minimum: int,
    maximum: int,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise M15CampaignError(f"{name} must be an array")
    if not minimum <= len(value) <= maximum:
        raise M15CampaignError(
            f"{name} must contain between {minimum} and {maximum} items"
        )
    items = tuple(_nonempty(item, name=f"{name}[]") for item in value)
    if len(items) != len(set(items)):
        raise M15CampaignError(f"{name} must not contain duplicates")
    return items


@dataclass(frozen=True)
class CampaignWorkload:
    label: str
    spec_path: str
    query_ids: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignWorkload":
        raw = _strict_object(
            value,
            name="workload",
            fields={"label", "spec_path", "query_ids"},
        )
        relative = _nonempty(raw["spec_path"], name="workload.spec_path")
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or path == Path("."):
            raise M15CampaignError(
                "workload.spec_path must be a normalized repository-relative path"
            )
        query_ids = tuple(
            _safe_id(item, name="workload.query_ids[]")
            for item in _unique_strings(
                raw["query_ids"],
                name="workload.query_ids",
                minimum=1,
                maximum=256,
            )
        )
        return cls(
            label=_safe_id(raw["label"], name="workload.label"),
            spec_path=relative,
            query_ids=query_ids,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "spec_path": self.spec_path,
            "query_ids": list(self.query_ids),
        }


@dataclass(frozen=True)
class CampaignProtocol:
    order_design: str
    blocks_per_workload: int
    warmup_runs_per_method: int
    measured_runs_per_method_per_sequence: int
    service_lifecycle: str
    cache_policy: str
    calibration_policy: str
    memory_policy: str
    failure_policy: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignProtocol":
        fields = {
            "order_design",
            "blocks_per_workload",
            "warmup_runs_per_method",
            "measured_runs_per_method_per_sequence",
            "service_lifecycle",
            "cache_policy",
            "calibration_policy",
            "memory_policy",
            "failure_policy",
        }
        raw = _strict_object(value, name="protocol", fields=fields)
        exact = {
            "order_design": _ORDER_DESIGN,
            "service_lifecycle": _SERVICE_POLICY,
            "cache_policy": _CACHE_POLICY,
            "calibration_policy": _CALIBRATION_POLICY,
            "memory_policy": _MEMORY_POLICY,
            "failure_policy": _FAILURE_POLICY,
        }
        for key, expected in exact.items():
            if raw[key] != expected:
                raise M15CampaignError(f"protocol.{key} must be {expected}")
        return cls(
            order_design=_ORDER_DESIGN,
            blocks_per_workload=_bounded_int(
                raw["blocks_per_workload"],
                name="protocol.blocks_per_workload",
                minimum=1,
                maximum=50,
            ),
            warmup_runs_per_method=_bounded_int(
                raw["warmup_runs_per_method"],
                name="protocol.warmup_runs_per_method",
                minimum=0,
                maximum=10,
            ),
            measured_runs_per_method_per_sequence=_bounded_int(
                raw["measured_runs_per_method_per_sequence"],
                name="protocol.measured_runs_per_method_per_sequence",
                minimum=1,
                maximum=1,
            ),
            service_lifecycle=_SERVICE_POLICY,
            cache_policy=_CACHE_POLICY,
            calibration_policy=_CALIBRATION_POLICY,
            memory_policy=_MEMORY_POLICY,
            failure_policy=_FAILURE_POLICY,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_design": self.order_design,
            "blocks_per_workload": self.blocks_per_workload,
            "warmup_runs_per_method": self.warmup_runs_per_method,
            "measured_runs_per_method_per_sequence": (
                self.measured_runs_per_method_per_sequence
            ),
            "service_lifecycle": self.service_lifecycle,
            "cache_policy": self.cache_policy,
            "calibration_policy": self.calibration_policy,
            "memory_policy": self.memory_policy,
            "failure_policy": self.failure_policy,
        }


@dataclass(frozen=True)
class CampaignAnalysis:
    primary_metric: str
    secondary_metrics: tuple[str, ...]
    inferential_analysis: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignAnalysis":
        fields = {
            "correctness_gate",
            "primary_metric",
            "secondary_metrics",
            "collection_aggregation",
            "inferential_analysis",
        }
        raw = _strict_object(value, name="analysis", fields=fields)
        if raw["correctness_gate"] != "exact_oracle_match_required":
            raise M15CampaignError(
                "analysis.correctness_gate must be exact_oracle_match_required"
            )
        if raw["collection_aggregation"] != "none_preserve_raw_repetitions":
            raise M15CampaignError(
                "analysis.collection_aggregation must be "
                "none_preserve_raw_repetitions"
            )
        if raw["inferential_analysis"] != "unfrozen_requires_author_approval":
            raise M15CampaignError(
                "analysis.inferential_analysis must be "
                "unfrozen_requires_author_approval in the v1 schema"
            )
        return cls(
            primary_metric=_safe_id(
                raw["primary_metric"], name="analysis.primary_metric"
            ),
            secondary_metrics=tuple(
                _safe_id(item, name="analysis.secondary_metrics[]")
                for item in _unique_strings(
                    raw["secondary_metrics"],
                    name="analysis.secondary_metrics",
                    minimum=1,
                    maximum=32,
                )
            ),
            inferential_analysis=str(raw["inferential_analysis"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "correctness_gate": "exact_oracle_match_required",
            "primary_metric": self.primary_metric,
            "secondary_metrics": list(self.secondary_metrics),
            "collection_aggregation": "none_preserve_raw_repetitions",
            "inferential_analysis": self.inferential_analysis,
        }


@dataclass(frozen=True)
class M15CampaignSpec:
    campaign_id: str
    experiment_mode: str
    design_seed: str
    methods: tuple[M15Method, ...]
    workloads: tuple[CampaignWorkload, ...]
    protocol: CampaignProtocol
    analysis: CampaignAnalysis
    paper_readiness_blockers: tuple[str, ...]
    max_sessions: int

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "M15CampaignSpec":
        fields = {
            "schema_version",
            "campaign_id",
            "experiment_mode",
            "design_seed",
            "methods",
            "workloads",
            "protocol",
            "analysis",
            "paper_readiness_blockers",
            "max_sessions",
            "paper_result",
        }
        raw = _strict_object(value, name="campaign spec", fields=fields)
        if raw["schema_version"] != CAMPAIGN_SPEC_SCHEMA_VERSION:
            raise M15CampaignError(
                f"campaign schema_version must be {CAMPAIGN_SPEC_SCHEMA_VERSION}"
            )
        if raw["experiment_mode"] not in {"development", "pilot", "paper"}:
            raise M15CampaignError(
                "experiment_mode must be development, pilot, or paper"
            )
        seed = _nonempty(raw["design_seed"], name="design_seed")
        if len(seed.encode("utf-8")) > 256:
            raise M15CampaignError("design_seed must be at most 256 UTF-8 bytes")
        try:
            methods = tuple(
                M15Method(item)
                for item in _unique_strings(
                    raw["methods"], name="methods", minimum=1, maximum=32
                )
            )
        except ValueError as exc:
            raise M15CampaignError(f"unknown M15 method: {exc}") from exc
        if (
            len(methods) != len(_CANONICAL_METHODS)
            or set(methods) != set(_CANONICAL_METHODS)
        ):
            raise M15CampaignError(
                "campaign methods must contain each of the six frozen M15 "
                "methods exactly once"
            )
        raw_workloads = raw["workloads"]
        if not isinstance(raw_workloads, list) or not 1 <= len(raw_workloads) <= 64:
            raise M15CampaignError("workloads must contain between 1 and 64 items")
        workloads = tuple(
            CampaignWorkload.from_dict(item) for item in raw_workloads
        )
        if len({item.label for item in workloads}) != len(workloads):
            raise M15CampaignError("workload labels must be unique")
        if len({item.spec_path for item in workloads}) != len(workloads):
            raise M15CampaignError("workload spec paths must be unique")
        if raw["paper_result"] is not False:
            raise M15CampaignError(
                "a campaign specification must set paper_result=false"
            )
        return cls(
            campaign_id=_safe_id(raw["campaign_id"], name="campaign_id"),
            experiment_mode=str(raw["experiment_mode"]),
            design_seed=seed,
            methods=_CANONICAL_METHODS,
            workloads=workloads,
            protocol=CampaignProtocol.from_dict(raw["protocol"]),
            analysis=CampaignAnalysis.from_dict(raw["analysis"]),
            paper_readiness_blockers=_unique_strings(
                raw["paper_readiness_blockers"],
                name="paper_readiness_blockers",
                minimum=1,
                maximum=64,
            ),
            max_sessions=_bounded_int(
                raw["max_sessions"],
                name="max_sessions",
                minimum=1,
                maximum=10_000,
            ),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "M15CampaignSpec":
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise M15CampaignError("campaign spec must be a JSON object")
        return cls.from_dict(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CAMPAIGN_SPEC_SCHEMA_VERSION,
            "campaign_id": self.campaign_id,
            "experiment_mode": self.experiment_mode,
            "design_seed": self.design_seed,
            "methods": [method.value for method in self.methods],
            "workloads": [item.to_dict() for item in self.workloads],
            "protocol": self.protocol.to_dict(),
            "analysis": self.analysis.to_dict(),
            "paper_readiness_blockers": list(self.paper_readiness_blockers),
            "max_sessions": self.max_sessions,
            "paper_result": False,
        }


@dataclass(frozen=True)
class M15CampaignPlan:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)

    @property
    def schedule_hash(self) -> str:
        return str(self.payload["schedule_sha256"])


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _bundle_spec_sha256(spec: M15WorkloadSpec) -> str:
    encoded = (
        json.dumps(
            spec.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _seed_rank(seed: str, *parts: object) -> str:
    text = ":".join((seed, *(str(part) for part in parts)))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _williams_base_indices(count: int) -> tuple[int, ...]:
    if count < 2 or count % 2:
        raise M15CampaignError(
            "the v1 Williams design requires an even number of methods"
        )
    result = [0]
    low = 1
    high = count - 1
    while len(result) < count:
        result.append(low)
        low += 1
        if len(result) < count:
            result.append(high)
            high -= 1
    return tuple(result)


def _balanced_orders(
    methods: tuple[M15Method, ...],
    *,
    seed: str,
    workload_label: str,
    block_index: int,
) -> tuple[tuple[M15Method, ...], ...]:
    labels = tuple(
        sorted(
            methods,
            key=lambda method: (
                _seed_rank(
                    seed,
                    "label",
                    workload_label,
                    block_index,
                    method.value,
                ),
                method.value,
            ),
        )
    )
    base = _williams_base_indices(len(labels))
    return tuple(
        tuple(labels[(index + shift) % len(labels)] for index in base)
        for shift in range(len(labels))
    )


def _resolve_workload(
    workload: CampaignWorkload,
    *,
    repo_root: Path,
) -> tuple[M15WorkloadSpec, dict[str, Any]]:
    candidate = repo_root / workload.spec_path
    if candidate.is_symlink():
        raise M15CampaignError(
            f"workload spec must not be a symlink: {workload.spec_path}"
        )
    path = candidate.resolve()
    try:
        path.relative_to(repo_root)
    except ValueError as exc:
        raise M15CampaignError("workload spec escapes the repository root") from exc
    if path.is_symlink() or not path.is_file():
        raise M15CampaignError(
            f"workload spec must be a regular file: {workload.spec_path}"
        )
    try:
        spec = M15WorkloadSpec.from_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise M15CampaignError(
            f"invalid workload spec {workload.spec_path}: {exc}"
        ) from exc
    return spec, {
        "label": workload.label,
        "workload_id": spec.workload_id,
        "spec_path": workload.spec_path,
        "spec_sha256": _sha256_file(path),
        "bundle_spec_sha256": _bundle_spec_sha256(spec),
        "query_ids": list(workload.query_ids),
        "query_count": len(workload.query_ids),
        "workload_counts": {
            "companies": spec.company_count,
            "transfers": spec.transfer_count,
            "high_risk_companies": spec.high_risk_company_count,
        },
    }


def _session(
    *,
    spec: M15CampaignSpec,
    workload: CampaignWorkload,
    workload_id: str,
    block_index: int,
    sequence_index: int,
    order: tuple[M15Method, ...],
) -> dict[str, Any]:
    session_id = (
        f"{spec.campaign_id}.{workload.label}.b{block_index:02d}."
        f"s{sequence_index:02d}"
    )
    streams = []
    for position, method in enumerate(order, start=1):
        warmup_ids = [
            f"{session_id}.{method.value}.warmup{index:02d}"
            for index in range(1, spec.protocol.warmup_runs_per_method + 1)
        ]
        measured_ids = [
            f"{session_id}.{method.value}.measured01"
        ]
        streams.append(
            {
                "method": method.value,
                "position": position,
                "memory_namespace": f"{session_id}.{method.value}",
                "query_ids": list(workload.query_ids),
                "warmup_run_ids": warmup_ids,
                "measured_run_ids": measured_ids,
                "warmup_included_in_metrics": False,
            }
        )
    return {
        "session_id": session_id,
        "dispatch_index": None,
        "workload_label": workload.label,
        "workload_id": workload_id,
        "block_index": block_index,
        "sequence_index": sequence_index,
        "method_order": [method.value for method in order],
        "service_lifecycle": spec.protocol.service_lifecycle,
        "cache_policy": spec.protocol.cache_policy,
        "calibration": {
            "policy": spec.protocol.calibration_policy,
            "expected_profile_calls": 3,
            "included_in_method_metrics": False,
        },
        "method_streams": streams,
        "failure_policy": spec.protocol.failure_policy,
        "automatic_retries": 0,
    }


def _balance_report(
    sessions: Sequence[Mapping[str, Any]],
    *,
    methods: tuple[M15Method, ...],
    workloads: tuple[CampaignWorkload, ...],
    blocks: int,
) -> dict[str, Any]:
    values = tuple(method.value for method in methods)
    expected_pairs = {
        f"{left}->{right}"
        for left in values
        for right in values
        if left != right
    }
    strata = []
    all_passed = True
    for workload in workloads:
        for block_index in range(1, blocks + 1):
            selected = [
                item
                for item in sessions
                if item["workload_label"] == workload.label
                and item["block_index"] == block_index
            ]
            positions = {method: [0] * len(values) for method in values}
            pairs = {pair: 0 for pair in sorted(expected_pairs)}
            for item in selected:
                order = list(item["method_order"])
                for position, method in enumerate(order):
                    positions[method][position] += 1
                for left, right in zip(order, order[1:]):
                    pairs[f"{left}->{right}"] += 1
            position_passed = (
                len(selected) == len(values)
                and all(counts == [1] * len(values) for counts in positions.values())
            )
            carryover_passed = (
                set(pairs) == expected_pairs and all(count == 1 for count in pairs.values())
            )
            passed = position_passed and carryover_passed
            all_passed = all_passed and passed
            strata.append(
                {
                    "workload_label": workload.label,
                    "block_index": block_index,
                    "sequence_count": len(selected),
                    "position_counts": positions,
                    "ordered_carryover_counts": pairs,
                    "position_balance_passed": position_passed,
                    "first_order_carryover_balance_passed": carryover_passed,
                    "passed": passed,
                }
            )
    return {
        "schema_version": ORDER_DESIGN_VERSION,
        "proof_scope": "within_each_workload_and_block",
        "passed": all_passed,
        "strata": strata,
    }


def compile_m15_campaign(
    spec: M15CampaignSpec,
    *,
    repo_root: str | Path | None = None,
) -> M15CampaignPlan:
    """Compile and validate a schedule without making an external call."""

    root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else Path(__file__).resolve().parents[3]
    )
    if not root.is_dir():
        raise M15CampaignError(f"repository root does not exist: {root}")

    workload_inputs = []
    workload_ids: dict[str, str] = {}
    for workload in spec.workloads:
        workload_spec, record = _resolve_workload(workload, repo_root=root)
        if workload_spec.workload_id in workload_ids.values():
            raise M15CampaignError("workload_id values must be unique")
        workload_ids[workload.label] = workload_spec.workload_id
        workload_inputs.append(record)

    count = (
        len(spec.workloads)
        * spec.protocol.blocks_per_workload
        * len(spec.methods)
    )
    if count > spec.max_sessions:
        raise M15CampaignError(
            f"campaign expands to {count} sessions, exceeding max_sessions "
            f"{spec.max_sessions}"
        )

    sessions = []
    for workload in spec.workloads:
        for block_index in range(1, spec.protocol.blocks_per_workload + 1):
            orders = _balanced_orders(
                spec.methods,
                seed=spec.design_seed,
                workload_label=workload.label,
                block_index=block_index,
            )
            for sequence_index, order in enumerate(orders, start=1):
                sessions.append(
                    _session(
                        spec=spec,
                        workload=workload,
                        workload_id=workload_ids[workload.label],
                        block_index=block_index,
                        sequence_index=sequence_index,
                        order=order,
                    )
                )
    sessions.sort(
        key=lambda item: (
            _seed_rank(spec.design_seed, "dispatch", item["session_id"]),
            item["session_id"],
        )
    )
    for index, session in enumerate(sessions, start=1):
        session["dispatch_index"] = index

    validation = _balance_report(
        sessions,
        methods=spec.methods,
        workloads=spec.workloads,
        blocks=spec.protocol.blocks_per_workload,
    )
    if not validation["passed"]:
        raise M15CampaignError("internal campaign balance validation failed")

    measured_attempts = sum(
        len(stream["query_ids"]) * len(stream["measured_run_ids"])
        for session in sessions
        for stream in session["method_streams"]
    )
    warmup_attempts = sum(
        len(stream["query_ids"]) * len(stream["warmup_run_ids"])
        for session in sessions
        for stream in session["method_streams"]
    )
    schedule_body = {
        "campaign_id": spec.campaign_id,
        "design_seed": spec.design_seed,
        "order_design_version": ORDER_DESIGN_VERSION,
        "method_policy_schema_version": "m15-f1-method-policy-v1",
        "methods": [method.value for method in spec.methods],
        "workload_inputs": workload_inputs,
        "protocol": spec.protocol.to_dict(),
        "sessions": sessions,
    }
    query_context_count = sum(len(item.query_ids) for item in spec.workloads)
    automatic_blockers = [
        "compiled_schedule_contains_no_execution_results",
        "query_ids_are_not_yet_bound_to_hash_verified_query_artifacts",
    ]
    if query_context_count < 30:
        automatic_blockers.append(
            "fewer_than_30_distinct_workload_query_contexts"
        )
    if any(len(item.query_ids) < 2 for item in spec.workloads):
        automatic_blockers.append(
            "at_least_one_workload_has_no_multi_task_memory_stream"
        )
    automatic_blockers.append("inferential_analysis_not_preregistered")
    blockers = (*automatic_blockers, *spec.paper_readiness_blockers)
    return M15CampaignPlan(
        {
            "schema_version": CAMPAIGN_PLAN_SCHEMA_VERSION,
            "campaign_id": spec.campaign_id,
            "experiment_mode": spec.experiment_mode,
            "campaign_spec_sha256": content_hash(spec.to_dict()),
            "schedule_sha256": content_hash(schedule_body),
            "method_policy_schema_version": "m15-f1-method-policy-v1",
            "methods": [method.value for method in spec.methods],
            "workload_inputs": workload_inputs,
            "protocol": spec.protocol.to_dict(),
            "analysis": spec.analysis.to_dict(),
            "sessions": sessions,
            "expected_counts": {
                "workloads": len(spec.workloads),
                "workload_query_contexts": query_context_count,
                "blocks_per_workload": spec.protocol.blocks_per_workload,
                "sessions": len(sessions),
                "method_streams": len(sessions) * len(spec.methods),
                "common_calibration_profile_calls": len(sessions) * 3,
                "warmup_query_attempts": warmup_attempts,
                "measured_query_attempts": measured_attempts,
            },
            "design_validation": validation,
            "claim_boundary": {
                "artifact_class": "unexecuted_deterministic_campaign_plan",
                "backend_calls_made": 0,
                "llm_calls_made": 0,
                "ontology_calls_made": 0,
                "contains_measurements": False,
                "paper_comparison_ready": False,
                "paper_result": False,
                "blocking_conditions": list(blockers),
            },
            "automatic_retries": 0,
            "paper_result": False,
        }
    )


def compile_m15_campaign_file(
    config_path: str | Path,
    *,
    repo_root: str | Path | None = None,
) -> M15CampaignPlan:
    return compile_m15_campaign(
        M15CampaignSpec.from_json(config_path),
        repo_root=repo_root,
    )


def write_m15_campaign_plan(plan: M15CampaignPlan, output: str | Path) -> Path:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"campaign plan already exists: {destination}")
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
    parser.add_argument("--config", required=True)
    parser.add_argument("--repo-root")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        plan = compile_m15_campaign_file(
            args.config,
            repo_root=args.repo_root,
        )
        if args.output:
            write_m15_campaign_plan(plan, args.output)
    except (
        FileExistsError,
        M15CampaignError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
