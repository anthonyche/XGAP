"""Versioned controlled estimate source for the F2C9 native mechanism gate."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_semantic_frontier import (
    M15DirectSemanticCandidateSet,
    M15DirectSemanticFrontierError,
    M15PreexecutionEstimateSnapshot,
    build_m15_preexecution_estimate_snapshot,
)


DIRECT_ESTIMATE_SOURCE_SCHEMA_VERSION = "m15-f2c9-direct-estimate-source-v1"
_FIELDS = {
    "schema_version",
    "evidence_kind",
    "evidence_id",
    "records",
    "automatic_retries",
    "paper_result",
}
_RECORD_FIELDS = {
    "changed_slot_ids",
    "physical_strategy",
    "estimated_latency_ms",
    "estimated_resource_cost_units",
}
_DIRECT_CHANGED_SLOT_SETS = {
    (),
    ("risk-level",),
    ("transfer-predicate",),
    ("risk-level", "transfer-predicate"),
}
_PHYSICAL_STRATEGIES = {"parallel_hash_join", "risk_first_bind_join"}


@dataclass(frozen=True)
class M15DirectEstimateSource:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))

    @property
    def source_hash(self) -> str:
        return str(self.payload["estimate_source_sha256"])


def _number(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise M15DirectSemanticFrontierError(f"{name} must be numeric")
    normalized = float(value)
    if normalized < 0 or normalized == float("inf") or normalized != normalized:
        raise M15DirectSemanticFrontierError(
            f"{name} must be finite and nonnegative"
        )
    return normalized


def load_m15_direct_estimate_source(
    path: str | Path,
) -> M15DirectEstimateSource:
    source_path = Path(path)
    if source_path.is_symlink() or not source_path.is_file():
        raise M15DirectSemanticFrontierError(
            "direct estimate source must be a regular non-symbolic-link file"
        )
    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise M15DirectSemanticFrontierError(
            f"direct estimate source is invalid: {exc}"
        ) from exc
    if not isinstance(raw, Mapping) or set(raw) != _FIELDS:
        raise M15DirectSemanticFrontierError(
            "direct estimate source fields do not match the contract"
        )
    if raw.get("schema_version") != DIRECT_ESTIMATE_SOURCE_SCHEMA_VERSION:
        raise M15DirectSemanticFrontierError(
            "direct estimate source schema_version is unsupported"
        )
    if raw.get("evidence_kind") != "controlled_preexecution_fixture":
        raise M15DirectSemanticFrontierError(
            "development estimate source must be a controlled preexecution fixture"
        )
    evidence_id = raw.get("evidence_id")
    if not isinstance(evidence_id, str) or not evidence_id:
        raise M15DirectSemanticFrontierError(
            "direct estimate source evidence_id is invalid"
        )
    records = raw.get("records")
    if not isinstance(records, list) or len(records) != 8:
        raise M15DirectSemanticFrontierError(
            "direct estimate source requires eight records"
        )
    normalized: list[dict[str, Any]] = []
    identities: list[tuple[tuple[str, ...], str]] = []
    for index, record in enumerate(records):
        if not isinstance(record, Mapping) or set(record) != _RECORD_FIELDS:
            raise M15DirectSemanticFrontierError(
                f"direct estimate records[{index}] fields are invalid"
            )
        changed = record.get("changed_slot_ids")
        if not isinstance(changed, list) or not all(
            isinstance(value, str) for value in changed
        ):
            raise M15DirectSemanticFrontierError(
                f"direct estimate records[{index}] changed slots are invalid"
            )
        changed_key = tuple(changed)
        strategy = record.get("physical_strategy")
        if changed_key not in _DIRECT_CHANGED_SLOT_SETS:
            raise M15DirectSemanticFrontierError(
                "direct estimate source references a non-direct semantic class"
            )
        if strategy not in _PHYSICAL_STRATEGIES:
            raise M15DirectSemanticFrontierError(
                "direct estimate source references an unsupported strategy"
            )
        identities.append((changed_key, str(strategy)))
        normalized.append(
            {
                "changed_slot_ids": list(changed_key),
                "physical_strategy": strategy,
                "estimated_latency_ms": _number(
                    record.get("estimated_latency_ms"),
                    name="estimated_latency_ms",
                ),
                "estimated_resource_cost_units": _number(
                    record.get("estimated_resource_cost_units"),
                    name="estimated_resource_cost_units",
                ),
            }
        )
    expected = {
        (changed, strategy)
        for changed in _DIRECT_CHANGED_SLOT_SETS
        for strategy in _PHYSICAL_STRATEGIES
    }
    if len(identities) != len(set(identities)) or set(identities) != expected:
        raise M15DirectSemanticFrontierError(
            "direct estimate source must cover each direct class and strategy once"
        )
    if raw.get("automatic_retries") != 0 or raw.get("paper_result") is not False:
        raise M15DirectSemanticFrontierError(
            "direct estimate source claim boundary is invalid"
        )
    body = {
        "schema_version": DIRECT_ESTIMATE_SOURCE_SCHEMA_VERSION,
        "evidence_kind": raw["evidence_kind"],
        "evidence_id": evidence_id,
        "records": sorted(
            normalized,
            key=lambda item: (
                tuple(item["changed_slot_ids"]),
                item["physical_strategy"],
            ),
        ),
        "automatic_retries": 0,
        "paper_result": False,
    }
    return M15DirectEstimateSource(
        {**body, "estimate_source_sha256": content_hash(body)}
    )


def bind_m15_direct_estimate_snapshot(
    candidate_set: M15DirectSemanticCandidateSet,
    estimate_source: M15DirectEstimateSource,
) -> M15PreexecutionEstimateSnapshot:
    candidates = candidate_set.to_dict()
    source = estimate_source.to_dict()
    by_identity = {
        (tuple(item["changed_slot_ids"]), item["physical_strategy"]): item
        for item in source["records"]
    }
    changed_by_class = {
        item["semantic_class_id"]: tuple(item["changed_slot_ids"])
        for item in candidates["semantic_classes"]
    }
    estimates: list[dict[str, Any]] = []
    for candidate in candidates["physical_candidates"]:
        identity = (
            changed_by_class[candidate["semantic_class_id"]],
            candidate["physical_strategy"],
        )
        source_record = by_identity.get(identity)
        if source_record is None:
            raise M15DirectSemanticFrontierError(
                "direct estimate source does not cover a physical candidate"
            )
        estimates.append(
            {
                "plan_id": candidate["plan_id"],
                "estimated_latency_ms": source_record[
                    "estimated_latency_ms"
                ],
                "estimated_resource_cost_units": source_record[
                    "estimated_resource_cost_units"
                ],
            }
        )
    return build_m15_preexecution_estimate_snapshot(
        candidate_set,
        estimates,
        evidence_kind=source["evidence_kind"],
        evidence_id=source["evidence_id"],
    )
