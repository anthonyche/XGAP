"""Compile the result-blind FinBench paper-protocol promotion gate.

This module deliberately does not execute an experiment or decide scientific
choices for the author.  It verifies the frozen protocol sources, exposes every
unresolved author decision, independently replays development audits when
bindings are supplied, and refuses to authorize a confirmatory run until all
scientific, implementation, evidence, and authority gates are satisfied.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_correctness_evidence import (
    FINBENCH_CORRECTNESS_AUDIT_SCHEMA_VERSION,
    audit_m15_finbench_correctness,
)
from xgap.experiments.m15_finbench_family_campaign_evidence import (
    FINBENCH_FAMILY_CAMPAIGN_AUDIT_SCHEMA_VERSION,
    audit_m15_finbench_family_campaign,
)


FINBENCH_PAPER_PROTOCOL_SCHEMA_VERSION = (
    "m15-finbench-paper-protocol-draft-v1"
)
FINBENCH_PAPER_READINESS_SCHEMA_VERSION = (
    "m15-finbench-paper-protocol-readiness-v1"
)
FINBENCH_PAPER_EVIDENCE_BINDINGS_SCHEMA_VERSION = (
    "m15-finbench-paper-evidence-bindings-v1"
)
DEFAULT_PROTOCOL_PATH = Path(
    "experiments/configs/m15_finbench_paper_protocol_draft_v1.json"
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_PRIMARY_FAMILIES = (
    "f1_direct_transfer_control",
    "f2_temporal_path_control",
    "f3_aggregate_risk_ranking",
)
_DECISION_IDS = (
    "confirmatory_population",
    "primary_scale",
    "robustness_scale",
    "selected_serving_repetitions",
    "shadow_repetitions_per_plan",
    "infrastructure_replacement_limit",
    "semantic_track",
    "external_validation",
)
_PHYSICAL_DECISION_IDS = frozenset(_DECISION_IDS[:6])
_SOURCE_ARTIFACT_IDS = (
    "finbench-v010-sf0_1-source-lock",
    "finbench-sf0_1-primary-population",
    "finbench-development-campaign",
    "finbench-family-memory-policy",
)
_IMPLEMENTATION_SCOPES = (
    ("answer_independent_confirmatory_population_compiler", "physical_confirmatory"),
    ("out_of_sample_family_memory_runner", "physical_confirmatory"),
    ("confirmatory_statistics_analyzer", "physical_confirmatory"),
    ("confirmatory_evidence_auditor", "physical_confirmatory"),
    ("grailqa_semantic_protocol", "paper_complete"),
    ("fedshop_external_validation_protocol", "paper_complete"),
)


class FinBenchPaperProtocolError(ValueError):
    """Raised when the paper-protocol draft or its evidence is invalid."""


@dataclass(frozen=True)
class FinBenchPaperProtocolReadiness:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))


def _strict_object(
    value: object, *, name: str, fields: set[str]
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FinBenchPaperProtocolError(f"{name} must be an object")
    result = dict(value)
    missing = fields - set(result)
    unknown = set(result) - fields
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(sorted(missing)))
        if unknown:
            details.append("unknown=" + ",".join(sorted(unknown)))
        raise FinBenchPaperProtocolError(
            f"{name} fields changed ({'; '.join(details)})"
        )
    return result


def _array(value: object, *, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise FinBenchPaperProtocolError(f"{name} must be an array")
    return value


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise FinBenchPaperProtocolError(f"{name} must be a safe identifier")
    return value


def _sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise FinBenchPaperProtocolError(f"{name} must be a lowercase SHA-256")
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json_object(path: Path, *, name: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise FinBenchPaperProtocolError(
            f"{name} must be a regular non-symbolic-link file"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinBenchPaperProtocolError(f"{name} is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise FinBenchPaperProtocolError(f"{name} must contain an object")
    return dict(value)


def _repo_file(root: Path, relative: object, *, name: str) -> Path:
    if not isinstance(relative, str):
        raise FinBenchPaperProtocolError(f"{name} path must be a string")
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or candidate == Path(".")
        or ".." in candidate.parts
    ):
        raise FinBenchPaperProtocolError(
            f"{name} path must be normalized and repository-relative"
        )
    path = root / candidate
    if path.is_symlink() or not path.is_file():
        raise FinBenchPaperProtocolError(
            f"{name} path must resolve to a regular non-symbolic-link file"
        )
    try:
        path.resolve().relative_to(root)
    except ValueError as exc:
        raise FinBenchPaperProtocolError(f"{name} escapes repo_root") from exc
    return path


def _validate_protocol_sources(
    protocol: Mapping[str, Any], *, repo_root: Path
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(
        _array(protocol["source_artifacts"], name="source_artifacts")
    ):
        raw = _strict_object(
            item,
            name=f"source_artifacts[{index}]",
            fields={"artifact_id", "path", "sha256"},
        )
        artifact_id = _safe_id(
            raw["artifact_id"], name=f"source_artifacts[{index}].artifact_id"
        )
        if artifact_id in seen:
            raise FinBenchPaperProtocolError("source artifact IDs must be unique")
        seen.add(artifact_id)
        path = _repo_file(repo_root, raw["path"], name=artifact_id)
        expected = _sha256(raw["sha256"], name=f"{artifact_id}.sha256")
        observed = _file_sha256(path)
        if observed != expected:
            raise FinBenchPaperProtocolError(
                f"source artifact changed: {artifact_id}"
            )
        records.append(
            {
                "artifact_id": artifact_id,
                "path": str(raw["path"]),
                "sha256": observed,
                "verified": True,
            }
        )
    if tuple(item["artifact_id"] for item in records) != _SOURCE_ARTIFACT_IDS:
        raise FinBenchPaperProtocolError("paper protocol source registry changed")
    return records


def _validate_scientific_contract(protocol: Mapping[str, Any]) -> None:
    scope = _strict_object(
        protocol["scope"],
        name="scope",
        fields={
            "venue",
            "submission_deadline_aoe",
            "study_kind",
            "primary_artifact",
            "benchmark_conformance_claim",
            "primary_family_ids",
            "semantic_track",
            "external_validation",
        },
    )
    if (
        scope["venue"] != "ACM_SIGMOD_2027_research_round_4"
        or scope["submission_deadline_aoe"]
        != "2026-10-17T23:59:00-12:00"
        or scope["study_kind"]
        != "confirmatory_physical_optimizer_evaluation"
        or scope["benchmark_conformance_claim"] is not False
        or tuple(scope["primary_family_ids"]) != _PRIMARY_FAMILIES
        or scope["semantic_track"] != "separate_GrailQA_protocol"
        or scope["external_validation"]
        != "separate_cutoff_bounded_FedShop_protocol"
    ):
        raise FinBenchPaperProtocolError("paper scope changed")

    questions = _array(protocol["research_questions"], name="research_questions")
    question_ids: list[str] = []
    primary = 0
    for index, item in enumerate(questions):
        raw = _strict_object(
            item,
            name=f"research_questions[{index}]",
            fields={
                "rq_id",
                "role",
                "population",
                "treatment",
                "comparator",
                "estimand",
                "metric",
                "cost_boundary",
                "directional_expectation",
                "inferential_test",
            },
        )
        question_ids.append(_safe_id(raw["rq_id"], name="rq_id"))
        primary += raw["role"] == "primary"
    if len(question_ids) != len(set(question_ids)) or primary != 1:
        raise FinBenchPaperProtocolError(
            "research questions require unique IDs and exactly one primary"
        )
    by_question = {
        str(item["rq_id"]): dict(item)
        for item in questions
        if isinstance(item, Mapping)
    }
    if set(by_question) != {"RQ-P1", "RQ-P2", "RQ-P3"}:
        raise FinBenchPaperProtocolError("research question registry changed")
    primary_question = by_question["RQ-P1"]
    if (
        primary_question["role"] != "primary"
        or primary_question["population"]
        != "heldout_instances_from_seen_F1_F2_families"
        or primary_question["treatment"] != "family_memory_zero_profile"
        or primary_question["comparator"] != "current_query_dual_profile"
        or primary_question["estimand"]
        != "geometric_mean_within_query_end_to_end_latency_ratio"
        or primary_question["metric"]
        != "selection_plus_serving_elapsed_ms"
        or primary_question["cost_boundary"]
        != "include_current_query_acquisition_exclude_offline_training_report_training_separately"
        or primary_question["directional_expectation"] != "ratio_below_one"
        or primary_question["inferential_test"]
        != "two_sided_paired_sign_flip_randomization_on_query_log_ratios"
    ):
        raise FinBenchPaperProtocolError("primary research question changed")
    if (
        by_question["RQ-P2"]["role"] != "secondary"
        or by_question["RQ-P3"]["role"] != "descriptive_cold_start"
        or by_question["RQ-P3"]["inferential_test"]
        != "none_separate_stratum"
    ):
        raise FinBenchPaperProtocolError("secondary research boundary changed")
    if (
        by_question["RQ-P2"]["cost_boundary"]
        != "serving_only_and_selection_plus_serving_both_reported"
        or by_question["RQ-P3"]["cost_boundary"]
        != "never_relabel_cold_start_as_family_memory_prediction"
    ):
        raise FinBenchPaperProtocolError("research cost boundary changed")

    methods = _strict_object(
        protocol["methods"],
        name="methods",
        fields={
            "online_methods",
            "analysis_controls",
            "oracle_role",
            "current_query_profile_calls_for_family_memory",
        },
    )
    if (
        methods["current_query_profile_calls_for_family_memory"] != 0
        or methods["oracle_role"] != "postexecution_regret_only"
        or set(methods["online_methods"])
        != {
            "family_memory_zero_profile",
            "predeclared_family_fallback",
            "current_query_dual_profile",
        }
        or set(methods["analysis_controls"])
        != {
            "family_global_no_instance_features",
            "fixed_route_a",
            "fixed_route_b",
            "observed_oracle_upper_bound",
        }
    ):
        raise FinBenchPaperProtocolError("method boundary changed")

    population = _strict_object(
        protocol["population_design"],
        name="population_design",
        fields={
            "sampling_must_be_answer_independent",
            "sampling_must_be_cost_independent",
            "query_instance_is_inferential_unit",
            "repetitions_are_not_independent_units",
            "training_queries_excluded_from_confirmatory_effect_estimates",
            "seen_family_predictions_must_be_out_of_sample",
            "cold_family_reported_separately",
        },
    )
    if not all(value is True for value in population.values()):
        raise FinBenchPaperProtocolError(
            "confirmatory population protections must all be enabled"
        )

    execution = _strict_object(
        protocol["execution_design"],
        name="execution_design",
        fields={
            "backend_boundary",
            "backends",
            "remote_calls_per_complete_plan",
            "method_order",
            "service_lifecycle",
            "cache_policy",
            "selection_sealed_before_serving",
            "shadow_starts_after_all_selection_seals",
            "oracle_opened_after_all_plan_runs",
            "backend_timeout_seconds",
            "automatic_retries",
        },
    )
    if (
        execution["backend_boundary"] != "black_box_public_interfaces_only"
        or execution["backends"] != ["neo4j", "fuseki"]
        or execution["remote_calls_per_complete_plan"] != 2
        or execution["method_order"]
        != "deterministic_counterbalanced_within_query_and_block"
        or execution["service_lifecycle"]
        != "fresh_job_owned_services_per_measurement_block"
        or execution["cache_policy"]
        != "all_completed_measurements_retained_and_cache_state_reported"
        or execution["backend_timeout_seconds"] != 60
        or execution["automatic_retries"] != 0
        or execution["selection_sealed_before_serving"] is not True
        or execution["shadow_starts_after_all_selection_seals"] is not True
        or execution["oracle_opened_after_all_plan_runs"] is not True
    ):
        raise FinBenchPaperProtocolError("execution integrity boundary changed")

    analysis = _strict_object(
        protocol["analysis_design"],
        name="analysis_design",
        fields={
            "primary_alpha",
            "confidence_level",
            "query_level_repetition_aggregation",
            "primary_effects",
            "confidence_interval",
            "confidence_interval_seed",
            "primary_test",
            "primary_test_seed",
            "primary_hypothesis_count",
            "secondary_multiplicity",
            "missing_measurements",
            "report_effect_size_and_interval_regardless_of_p_value",
            "report_per_query_values",
            "report_all_attempts",
            "report_training_cost_and_amortization_separately",
        },
    )
    if (
        analysis["primary_alpha"] != 0.05
        or analysis["confidence_level"] != 0.95
        or analysis["query_level_repetition_aggregation"] != "median"
        or analysis["primary_effects"]
        != ["geometric_mean_ratio", "paired_median_difference_ms"]
        or analysis["confidence_interval"]
        != "query_cluster_bootstrap_10000_resamples"
        or analysis["primary_test"]
        != "paired_sign_flip_randomization_100000_draws_or_exact_if_smaller"
        or analysis["primary_hypothesis_count"] != 1
        or analysis["secondary_multiplicity"]
        != "holm_familywise_alpha_0.05"
        or analysis["missing_measurements"] != "no_imputation"
        or not all(
            analysis[field] is True
            for field in (
                "report_effect_size_and_interval_regardless_of_p_value",
                "report_per_query_values",
                "report_all_attempts",
                "report_training_cost_and_amortization_separately",
            )
        )
    ):
        raise FinBenchPaperProtocolError("analysis integrity boundary changed")

    failure = _strict_object(
        protocol["failure_policy"],
        name="failure_policy",
        fields={
            "query_timeout_is_method_outcome",
            "query_timeout_is_not_replacement_eligible",
            "infrastructure_failure_requires_no_valid_measurement_in_block",
            "replacement_reuses_frozen_schedule",
            "failed_attempts_remain_reported",
            "automatic_retries",
        },
    )
    if failure["automatic_retries"] != 0 or not all(
        failure[field] is True
        for field in failure
        if field != "automatic_retries"
    ):
        raise FinBenchPaperProtocolError("failure policy weakened")


def _decisions(
    protocol: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    records: list[dict[str, Any]] = []
    physical_blockers: list[str] = []
    paper_blockers: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(
        _array(protocol["author_decisions"], name="author_decisions")
    ):
        raw = _strict_object(
            item,
            name=f"author_decisions[{index}]",
            fields={
                "decision_id",
                "allowed_values",
                "recommended_value",
                "selected_value",
            },
        )
        decision_id = _safe_id(raw["decision_id"], name="decision_id")
        if decision_id in seen:
            raise FinBenchPaperProtocolError("author decision IDs must be unique")
        seen.add(decision_id)
        allowed = _array(
            raw["allowed_values"], name=f"{decision_id}.allowed_values"
        )
        if not allowed or any(
            not isinstance(value, str) or not value for value in allowed
        ):
            raise FinBenchPaperProtocolError(
                f"{decision_id}.allowed_values must be nonempty strings"
            )
        if len(allowed) != len(set(allowed)):
            raise FinBenchPaperProtocolError(
                f"{decision_id}.allowed_values must be unique"
            )
        if raw["recommended_value"] not in allowed:
            raise FinBenchPaperProtocolError(
                f"{decision_id}.recommended_value is not allowed"
            )
        selected = raw["selected_value"]
        if selected is not None and selected not in allowed:
            raise FinBenchPaperProtocolError(
                f"{decision_id}.selected_value is not allowed"
            )
        if selected is None:
            blocker = f"author_decision.{decision_id}.unselected"
            paper_blockers.append(blocker)
            if decision_id in _PHYSICAL_DECISION_IDS:
                physical_blockers.append(blocker)
        records.append(copy.deepcopy(raw))
    if tuple(item["decision_id"] for item in records) != _DECISION_IDS:
        raise FinBenchPaperProtocolError("author decision registry changed")
    return records, physical_blockers, paper_blockers


def _implementation_requirements(
    protocol: Mapping[str, Any], *, repo_root: Path
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    records: list[dict[str, Any]] = []
    physical_blockers: list[str] = []
    paper_blockers: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(
        _array(
            protocol["implementation_requirements"],
            name="implementation_requirements",
        )
    ):
        raw = _strict_object(
            item,
            name=f"implementation_requirements[{index}]",
            fields={"requirement_id", "scope", "status", "evidence"},
        )
        requirement_id = _safe_id(raw["requirement_id"], name="requirement_id")
        if requirement_id in seen:
            raise FinBenchPaperProtocolError(
                "implementation requirement IDs must be unique"
            )
        seen.add(requirement_id)
        if raw["scope"] not in {"physical_confirmatory", "paper_complete"}:
            raise FinBenchPaperProtocolError(
                f"{requirement_id}.scope is invalid"
            )
        if raw["status"] not in {"missing", "ready"}:
            raise FinBenchPaperProtocolError(
                f"{requirement_id}.status is invalid"
            )
        evidence = raw["evidence"]
        if raw["status"] == "ready":
            evidence_raw = _strict_object(
                evidence,
                name=f"{requirement_id}.evidence",
                fields={"path", "sha256"},
            )
            path = _repo_file(repo_root, evidence_raw["path"], name=requirement_id)
            expected = _sha256(
                evidence_raw["sha256"], name=f"{requirement_id}.evidence.sha256"
            )
            if _file_sha256(path) != expected:
                raise FinBenchPaperProtocolError(
                    f"implementation evidence changed: {requirement_id}"
                )
        elif evidence is not None:
            raise FinBenchPaperProtocolError(
                f"missing requirement {requirement_id} cannot carry evidence"
            )
        if raw["status"] != "ready":
            blocker = f"implementation.{requirement_id}.missing"
            paper_blockers.append(blocker)
            if raw["scope"] == "physical_confirmatory":
                physical_blockers.append(blocker)
        records.append(copy.deepcopy(raw))
    if tuple(
        (item["requirement_id"], item["scope"]) for item in records
    ) != _IMPLEMENTATION_SCOPES:
        raise FinBenchPaperProtocolError(
            "implementation requirement registry changed"
        )
    return records, physical_blockers, paper_blockers


def _absolute_regular(path_value: object, *, name: str, directory: bool) -> Path:
    if not isinstance(path_value, str) or not Path(path_value).is_absolute():
        raise FinBenchPaperProtocolError(f"{name} must be an absolute path")
    supplied = Path(path_value)
    if supplied.is_symlink():
        raise FinBenchPaperProtocolError(f"{name} must not be a symbolic link")
    if directory and not supplied.is_dir():
        raise FinBenchPaperProtocolError(f"{name} must be a directory")
    if not directory and not supplied.is_file():
        raise FinBenchPaperProtocolError(f"{name} must be a regular file")
    return supplied.resolve()


def _verify_development_evidence(
    bindings_path: str | Path | None,
    *,
    repo_root: Path,
) -> tuple[list[dict[str, Any]], list[str], str | None]:
    if bindings_path is None:
        return (
            [],
            [
                "development_evidence.sf0_1_correctness_audit.unbound",
                "development_evidence.sf0_1_family_campaign_audit.unbound",
            ],
            None,
        )
    supplied = Path(bindings_path)
    bindings = _load_json_object(supplied, name="development evidence bindings")
    raw = _strict_object(
        bindings,
        name="development evidence bindings",
        fields={"schema_version", "bindings"},
    )
    if raw["schema_version"] != FINBENCH_PAPER_EVIDENCE_BINDINGS_SCHEMA_VERSION:
        raise FinBenchPaperProtocolError(
            "development evidence bindings schema changed"
        )
    by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(_array(raw["bindings"], name="bindings")):
        entry = _strict_object(
            item,
            name=f"bindings[{index}]",
            fields={"evidence_id", "run_root", "audit_path", "expected_commit"},
        )
        evidence_id = _safe_id(entry["evidence_id"], name="evidence_id")
        if evidence_id in by_id:
            raise FinBenchPaperProtocolError("evidence IDs must be unique")
        by_id[evidence_id] = entry
    if set(by_id) != {
        "sf0_1_correctness_audit",
        "sf0_1_family_campaign_audit",
    }:
        raise FinBenchPaperProtocolError("development evidence set changed")

    receipts: list[dict[str, Any]] = []
    correctness = by_id["sf0_1_correctness_audit"]
    correctness_commit = correctness["expected_commit"]
    if (
        not isinstance(correctness_commit, str)
        or _COMMIT.fullmatch(correctness_commit) is None
    ):
        raise FinBenchPaperProtocolError("correctness expected_commit is invalid")
    correctness_root = _absolute_regular(
        correctness["run_root"], name="correctness run_root", directory=True
    )
    correctness_audit_path = _absolute_regular(
        correctness["audit_path"], name="correctness audit_path", directory=False
    )
    correctness_saved = _load_json_object(
        correctness_audit_path, name="correctness audit"
    )
    correctness_rebuilt = audit_m15_finbench_correctness(
        run_root=correctness_root,
        expected_commit=correctness_commit,
    ).to_dict()
    if correctness_saved != correctness_rebuilt or (
        correctness_saved.get("schema_version")
        != FINBENCH_CORRECTNESS_AUDIT_SCHEMA_VERSION
        or correctness_saved.get("success") is not True
        or correctness_saved.get("failed_check_ids") != []
        or correctness_saved.get("run_tree_mutated") is not False
    ):
        raise FinBenchPaperProtocolError(
            "correctness evidence failed independent reconstruction"
        )
    receipts.append(
        {
            "evidence_id": "sf0_1_correctness_audit",
            "producer_commit": correctness_commit,
            "run_id": correctness_root.name,
            "audit_sha256": _file_sha256(correctness_audit_path),
            "audit_content_sha256": content_hash(correctness_saved),
            "audit_check_count": correctness_saved["check_count"],
            "independently_reconstructed": True,
        }
    )

    campaign = by_id["sf0_1_family_campaign_audit"]
    campaign_commit = campaign["expected_commit"]
    if (
        not isinstance(campaign_commit, str)
        or _COMMIT.fullmatch(campaign_commit) is None
    ):
        raise FinBenchPaperProtocolError("campaign expected_commit is invalid")
    campaign_root = _absolute_regular(
        campaign["run_root"], name="campaign run_root", directory=True
    )
    campaign_audit_path = _absolute_regular(
        campaign["audit_path"], name="campaign audit_path", directory=False
    )
    campaign_saved = _load_json_object(campaign_audit_path, name="campaign audit")
    campaign_rebuilt = audit_m15_finbench_family_campaign(
        run_root=campaign_root,
        expected_commit=campaign_commit,
        protocol=repo_root
        / "experiments/configs/m15_finbench_family_campaign_dev_v1.json",
        family_memory_policy=repo_root
        / "experiments/configs/m15_finbench_family_memory_policy_v1.json",
    ).to_dict()
    if campaign_saved != campaign_rebuilt or (
        campaign_saved.get("schema_version")
        != FINBENCH_FAMILY_CAMPAIGN_AUDIT_SCHEMA_VERSION
        or campaign_saved.get("success") is not True
        or campaign_saved.get("failed_check_ids") != []
        or campaign_saved.get("run_tree_mutated") is not False
    ):
        raise FinBenchPaperProtocolError(
            "campaign evidence failed independent reconstruction"
        )
    receipts.append(
        {
            "evidence_id": "sf0_1_family_campaign_audit",
            "producer_commit": campaign_commit,
            "run_id": campaign_root.name,
            "audit_sha256": _file_sha256(campaign_audit_path),
            "audit_content_sha256": content_hash(campaign_saved),
            "audit_check_count": campaign_saved["check_count"],
            "independently_reconstructed": True,
        }
    )
    receipts.sort(key=lambda item: item["evidence_id"])
    return receipts, [], content_hash(raw)


def _approval_subject(protocol: Mapping[str, Any]) -> dict[str, Any]:
    implementation_identity = [
        {
            "requirement_id": item["requirement_id"],
            "scope": item["scope"],
        }
        for item in protocol["implementation_requirements"]
    ]
    return {
        key: copy.deepcopy(protocol[key])
        for key in (
            "schema_version",
            "protocol_id",
            "source_artifacts",
            "scope",
            "research_questions",
            "methods",
            "population_design",
            "execution_design",
            "analysis_design",
            "failure_policy",
            "author_decisions",
            "required_development_evidence",
            "automatic_retries",
        )
    } | {"implementation_requirement_identity": implementation_identity}


def compile_finbench_paper_protocol_readiness(
    protocol: Mapping[str, Any] | str | Path = DEFAULT_PROTOCOL_PATH,
    *,
    repo_root: str | Path,
    evidence_bindings: str | Path | None = None,
) -> FinBenchPaperProtocolReadiness:
    """Compile a deterministic, zero-experiment-call promotion decision."""

    supplied_root = Path(repo_root)
    if supplied_root.is_symlink() or not supplied_root.is_dir():
        raise FinBenchPaperProtocolError("repo_root must be a real directory")
    root = supplied_root.resolve()
    selected = (
        copy.deepcopy(dict(protocol))
        if isinstance(protocol, Mapping)
        else _load_json_object(Path(protocol), name="paper protocol")
    )
    raw = _strict_object(
        selected,
        name="paper protocol",
        fields={
            "schema_version",
            "protocol_id",
            "source_artifacts",
            "scope",
            "research_questions",
            "methods",
            "population_design",
            "execution_design",
            "analysis_design",
            "failure_policy",
            "author_decisions",
            "implementation_requirements",
            "required_development_evidence",
            "approval",
            "claim_boundary",
            "automatic_retries",
            "paper_result",
        },
    )
    if raw["schema_version"] != FINBENCH_PAPER_PROTOCOL_SCHEMA_VERSION:
        raise FinBenchPaperProtocolError("paper protocol schema changed")
    _safe_id(raw["protocol_id"], name="protocol_id")
    if raw["automatic_retries"] != 0 or raw["paper_result"] is not False:
        raise FinBenchPaperProtocolError(
            "paper protocol draft must disable retries and remain paper_result=false"
        )
    claim = _strict_object(
        raw["claim_boundary"],
        name="claim_boundary",
        fields={
            "artifact_class",
            "contains_measurements",
            "author_approved",
            "confirmatory_run_authorized",
            "paper_result",
        },
    )
    if claim != {
        "artifact_class": "result_blind_confirmatory_protocol_draft",
        "contains_measurements": False,
        "author_approved": False,
        "confirmatory_run_authorized": False,
        "paper_result": False,
    }:
        raise FinBenchPaperProtocolError("draft claim boundary changed")
    if tuple(raw["required_development_evidence"]) != (
        "sf0_1_correctness_audit",
        "sf0_1_family_campaign_audit",
    ):
        raise FinBenchPaperProtocolError("required development evidence changed")

    sources = _validate_protocol_sources(raw, repo_root=root)
    _validate_scientific_contract(raw)
    decisions, physical_decision_blockers, paper_decision_blockers = _decisions(
        raw
    )
    implementation, physical_impl_blockers, paper_impl_blockers = (
        _implementation_requirements(raw, repo_root=root)
    )
    evidence, evidence_blockers, evidence_bindings_sha256 = (
        _verify_development_evidence(evidence_bindings, repo_root=root)
    )

    subject = _approval_subject(raw)
    subject_sha256 = content_hash(subject)
    approval = _strict_object(
        raw["approval"],
        name="approval",
        fields={
            "status",
            "authority_source_id",
            "approved_subject_sha256",
        },
    )
    approval_blockers: list[str] = []
    if approval["status"] == "pending_author_decision":
        if (
            approval["authority_source_id"] is not None
            or approval["approved_subject_sha256"] is not None
        ):
            raise FinBenchPaperProtocolError(
                "pending approval cannot contain an authority receipt"
            )
        approval_blockers.append("author_approval.pending")
        approved = False
    elif approval["status"] == "approved":
        if physical_decision_blockers:
            raise FinBenchPaperProtocolError(
                "author approval cannot precede all physical author decisions"
            )
        _safe_id(approval["authority_source_id"], name="authority_source_id")
        if approval["approved_subject_sha256"] != subject_sha256:
            raise FinBenchPaperProtocolError(
                "author approval does not bind the current protocol subject"
            )
        approved = True
    else:
        raise FinBenchPaperProtocolError("approval.status is invalid")

    physical_blockers = sorted(
        {
            *physical_decision_blockers,
            *physical_impl_blockers,
            *evidence_blockers,
            *approval_blockers,
        }
    )
    paper_blockers = sorted(
        {
            *physical_blockers,
            *paper_decision_blockers,
            *paper_impl_blockers,
        }
    )
    body: dict[str, Any] = {
        "schema_version": FINBENCH_PAPER_READINESS_SCHEMA_VERSION,
        "protocol_id": raw["protocol_id"],
        "protocol_draft_sha256": content_hash(raw),
        "approval_subject_sha256": subject_sha256,
        "source_artifacts": sources,
        "author_decisions": decisions,
        "implementation_requirements": implementation,
        "development_evidence_receipts": evidence,
        "evidence_bindings_sha256": evidence_bindings_sha256,
        "gates": {
            "result_blind_protocol_structurally_valid": True,
            "all_author_decisions_selected": not paper_decision_blockers,
            "author_approved": approved,
            "development_evidence_verified": not evidence_blockers,
            "physical_implementation_ready": not physical_impl_blockers,
            "physical_confirmatory_run_authorized": not physical_blockers,
            "paper_experiment_stack_ready": not paper_blockers,
        },
        "physical_confirmatory_blockers": physical_blockers,
        "paper_experiment_blockers": paper_blockers,
        "next_author_decisions": [
            {
                "decision_id": item["decision_id"],
                "allowed_values": item["allowed_values"],
                "recommended_value": item["recommended_value"],
            }
            for item in decisions
            if item["selected_value"] is None
        ],
        "claim_boundary": {
            "artifact_class": "result_blind_paper_protocol_readiness",
            "contains_measurements": False,
            "backend_calls_made": 0,
            "llm_calls_made": 0,
            "ontology_service_calls_made": 0,
            "author_decision_inferred": False,
            "paper_result": False,
        },
        "automatic_retries": 0,
        "paper_result": False,
    }
    body["readiness_sha256"] = content_hash(body)
    return FinBenchPaperProtocolReadiness(body)


def write_finbench_paper_protocol_readiness(
    readiness: FinBenchPaperProtocolReadiness, output: str | Path
) -> Path:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"paper readiness output exists: {destination}")
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            readiness.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)
    return destination


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL_PATH))
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--evidence-bindings")
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    try:
        readiness = compile_finbench_paper_protocol_readiness(
            arguments.protocol,
            repo_root=arguments.repo_root,
            evidence_bindings=arguments.evidence_bindings,
        )
        write_finbench_paper_protocol_readiness(readiness, arguments.output)
    except (
        FileExistsError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(
        json.dumps(
            {"status": "success", **readiness.to_dict()},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
