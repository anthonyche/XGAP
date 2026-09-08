"""Compile the result-blind GrailQA semantic-paper protocol readiness gate.

The protocol is deliberately non-executing and non-authorizing.  It binds the
public dataset, bounded model contract, primary estimand, comparators, failure
policy, and query-level analysis before any 150-query outcome is inspected.
An optional author-selection receipt can approve scientific choices, but this
module never turns that approval into live-run authority.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.hashing import content_hash


PROTOCOL_SCHEMA_VERSION = "m13e4-grailqa-semantic-paper-protocol-draft-v1"
READINESS_SCHEMA_VERSION = "m13e4-grailqa-semantic-paper-readiness-v1"
AUTHOR_SELECTION_SCHEMA_VERSION = (
    "m13e4-grailqa-semantic-paper-author-selection-v1"
)
DEFAULT_PROTOCOL_PATH = Path(
    "experiments/configs/grailqa_semantic_paper_protocol_draft_v1.json"
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_SOURCE_IDS = (
    "grailqa-pilot-artifact-manifest",
    "grailqa-pilot-selection",
    "qwen3-32b-model-config",
    "qwen3-32b-prompt",
    "qwen3-32b-structured-schema",
    "grailqa-preflight18-spec",
    "grailqa-paper-run-spec",
)
_DECISION_IDS = (
    "primary_reporting_population",
    "primary_epsilon",
    "primary_comparator",
    "inference_failure_estimand",
    "interactive_clarification_role",
)
_REQUIREMENT_IDS = (
    "preflight18_independent_audit",
    "pilot150_query_local_catalog",
    "paper_semantic_runner",
    "query_level_statistics_analyzer",
    "independent_semantic_evidence_auditor",
    "independent_semantic_run_evidence_auditor",
)


class GrailQASemanticPaperProtocolError(ValueError):
    """Raised when the frozen semantic protocol boundary is invalid."""


@dataclass(frozen=True)
class GrailQASemanticPaperReadiness:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))


def _strict_object(
    value: object, *, name: str, fields: set[str]
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GrailQASemanticPaperProtocolError(f"{name} must be an object")
    result = dict(value)
    missing = fields - set(result)
    unknown = set(result) - fields
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(sorted(missing)))
        if unknown:
            details.append("unknown=" + ",".join(sorted(unknown)))
        raise GrailQASemanticPaperProtocolError(
            f"{name} fields changed ({'; '.join(details)})"
        )
    return result


def _array(value: object, *, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise GrailQASemanticPaperProtocolError(f"{name} must be an array")
    return value


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise GrailQASemanticPaperProtocolError(f"{name} is not a safe ID")
    return value


def _sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GrailQASemanticPaperProtocolError(
            f"{name} must be a lowercase SHA-256"
        )
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path, *, name: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise GrailQASemanticPaperProtocolError(
            f"{name} must be a regular non-symbolic-link file"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GrailQASemanticPaperProtocolError(
            f"{name} is not valid JSON"
        ) from exc
    if not isinstance(value, Mapping):
        raise GrailQASemanticPaperProtocolError(f"{name} must contain an object")
    return dict(value)


def _repo_file(root: Path, relative: object, *, name: str) -> Path:
    if not isinstance(relative, str):
        raise GrailQASemanticPaperProtocolError(f"{name} path must be a string")
    candidate = Path(relative)
    if candidate.is_absolute() or candidate == Path(".") or ".." in candidate.parts:
        raise GrailQASemanticPaperProtocolError(
            f"{name} path must be normalized and repository-relative"
        )
    path = root / candidate
    if path.is_symlink() or not path.is_file():
        raise GrailQASemanticPaperProtocolError(
            f"{name} path must resolve to a regular non-symbolic-link file"
        )
    try:
        path.resolve().relative_to(root)
    except ValueError as exc:
        raise GrailQASemanticPaperProtocolError(f"{name} escapes repo_root") from exc
    return path


def _load_protocol(value: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    return _load_json(Path(value), name="semantic paper protocol")


def _validate_sources(
    protocol: Mapping[str, Any], *, repo_root: Path
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, item in enumerate(
        _array(protocol["source_artifacts"], name="source_artifacts")
    ):
        raw = _strict_object(
            item,
            name=f"source_artifacts[{index}]",
            fields={"artifact_id", "path", "sha256"},
        )
        artifact_id = _safe_id(raw["artifact_id"], name="artifact_id")
        path = _repo_file(repo_root, raw["path"], name=artifact_id)
        expected = _sha256(raw["sha256"], name=f"{artifact_id}.sha256")
        observed = _file_sha256(path)
        if observed != expected:
            raise GrailQASemanticPaperProtocolError(
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
    if tuple(item["artifact_id"] for item in records) != _SOURCE_IDS:
        raise GrailQASemanticPaperProtocolError("source artifact registry changed")
    return records


def _validate_bound_artifacts(
    protocol: Mapping[str, Any], *, repo_root: Path
) -> dict[str, Any]:
    dataset = _strict_object(
        protocol["dataset_contract"],
        name="dataset_contract",
        fields={
            "dataset_id",
            "license",
            "pilot_question_count",
            "train_question_count",
            "dev_question_count",
            "selection_uses_xgap_outcomes",
            "inference_questions_sha256",
            "reference_interpretations_sha256",
            "ontology_sha256",
            "gold_opened_after_all_inference",
        },
    )
    manifest = _load_json(
        repo_root / "datasets/grailqa_pilot_v1/artifact_manifest.json",
        name="GrailQA artifact manifest",
    )
    pilot_ids = _load_json(
        repo_root / "datasets/grailqa_pilot_v1/pilot_ids.json",
        name="GrailQA pilot IDs",
    )
    artifacts = dict(manifest.get("artifacts", {}))
    if (
        dataset["dataset_id"] != manifest.get("dataset_id")
        or dataset["license"] != "CC_BY_SA_4_0"
        or dataset["pilot_question_count"] != 150
        or dataset["train_question_count"] != 120
        or dataset["dev_question_count"] != 30
        or dataset["selection_uses_xgap_outcomes"] is not False
        or pilot_ids.get("selected_size") != 150
        or pilot_ids.get("selection_uses_xgap_outcomes") is not False
        or len(set(pilot_ids.get("question_ids", ()))) != 150
        or dataset["gold_opened_after_all_inference"] is not True
    ):
        raise GrailQASemanticPaperProtocolError("dataset boundary changed")
    expected_artifact_hashes = {
        "inference_questions.jsonl": dataset["inference_questions_sha256"],
        "reference_interpretations.jsonl": dataset[
            "reference_interpretations_sha256"
        ],
        "ontology.yaml": dataset["ontology_sha256"],
    }
    for filename, expected in expected_artifact_hashes.items():
        _sha256(expected, name=f"dataset_contract.{filename}")
        if dict(artifacts.get(filename, {})).get("sha256") != expected:
            raise GrailQASemanticPaperProtocolError(
                f"dataset artifact hash changed: {filename}"
            )

    inference = _strict_object(
        protocol["inference_contract"],
        name="inference_contract",
        fields={
            "model_bundle_root",
            "model_bundle_hash",
            "model",
            "provider",
            "temperature",
            "top_p",
            "seed",
            "maximum_repair_calls",
            "retrieval_k",
            "prompt_candidates_per_slot",
            "candidate_cap",
            "native_query_generation",
            "backend_execution",
        },
    )
    model = ModelBundle.load(repo_root / str(inference["model_bundle_root"]))
    if (
        model.bundle_hash != inference["model_bundle_hash"]
        or model.config.exact_model_snapshot != inference["model"]
        or model.config.provider != inference["provider"]
        or model.config.temperature != inference["temperature"]
        or model.config.top_p != inference["top_p"]
        or model.config.seed != inference["seed"]
        or model.config.max_repair_calls != inference["maximum_repair_calls"]
        or inference["retrieval_k"] != 20
        or inference["prompt_candidates_per_slot"] != 4
        or inference["candidate_cap"] != 3
        or inference["native_query_generation"] is not False
        or inference["backend_execution"] is not False
    ):
        raise GrailQASemanticPaperProtocolError("inference boundary changed")

    preflight = _load_json(
        repo_root
        / "experiments/specs/grailqa_semantic_preflight_v2_cwru_qwen3_32b.json",
        name="GrailQA preflight spec",
    )
    if (
        preflight.get("full_150_run_permitted") is not False
        or preflight.get("question_ids") is None
        or len(preflight["question_ids"]) != 18
        or preflight.get("model_bundle_hash") != inference["model_bundle_hash"]
        or preflight.get("candidate_cap") != inference["candidate_cap"]
        or preflight.get("backend_execution") is not False
        or preflight.get("gold_exposed_to_inference") is not False
    ):
        raise GrailQASemanticPaperProtocolError("preflight boundary changed")
    return {
        "dataset_id": dataset["dataset_id"],
        "pilot_question_count": 150,
        "model_bundle_hash": model.bundle_hash,
        "preflight_question_count": 18,
        "preflight_full_run_permitted": False,
    }


def _validate_scientific_contract(protocol: Mapping[str, Any]) -> None:
    scope = _strict_object(
        protocol["scope"],
        name="scope",
        fields={
            "venue",
            "submission_deadline_aoe",
            "study_kind",
            "primary_artifact",
            "physical_track_separate",
            "semantic_track_backend_execution",
        },
    )
    if scope != {
        "venue": "ACM_SIGMOD_2027_research_round_4",
        "submission_deadline_aoe": "2026-10-17T23:59:00-12:00",
        "study_kind": "result_blind_semantic_interpretation_evaluation",
        "primary_artifact": "GrailQA_v1_0_frozen_150_query_pilot",
        "physical_track_separate": "LDBC_FinBench_confirmatory",
        "semantic_track_backend_execution": False,
    }:
        raise GrailQASemanticPaperProtocolError("semantic scope changed")

    methods = _strict_object(
        protocol["methods"],
        name="methods",
        fields={
            "treatment",
            "primary_comparator",
            "shared_candidate_generation",
            "shared_grounding_and_validation",
            "ontology_ablation",
            "equivalence_ablation",
            "frontier_pruning_ablation",
            "oracle_upper_bound",
        },
    )
    if methods != {
        "treatment": "ontology_bounded_c_sem_epsilon_frontier",
        "primary_comparator": "model_confidence_top1_same_grounded_candidate_set",
        "shared_candidate_generation": True,
        "shared_grounding_and_validation": True,
        "ontology_ablation": "exact_only_zero_deviation_ranking",
        "equivalence_ablation": "no_semantic_equivalence_merge",
        "frontier_pruning_ablation": "no_epsilon_or_K_pruning",
        "oracle_upper_bound": "postinference_gold_simulated_clarification_only",
    }:
        raise GrailQASemanticPaperProtocolError("method boundary changed")

    outcomes = _strict_object(
        protocol["outcomes"],
        name="outcomes",
        fields={
            "primary",
            "candidate_recall",
            "coverage",
            "hard_constraint_violations",
            "frontier_size",
            "system_cost",
            "reachability_stratum",
        },
    )
    if outcomes != {
        "primary": "exact_canonical_structural_interpretation_match",
        "candidate_recall": "reference_supported_candidate_in_top3",
        "coverage": "nonempty_admissible_return_set",
        "hard_constraint_violations": "count_and_query_rate",
        "frontier_size": "returned_interpretations_after_equivalence_epsilon_K",
        "system_cost": "provider_calls_repairs_tokens_and_latency",
        "reachability_stratum": "jointly_prompt_reachable_queries_reported_separately",
    }:
        raise GrailQASemanticPaperProtocolError("outcome boundary changed")

    analysis = _strict_object(
        protocol["analysis_design"],
        name="analysis_design",
        fields={
            "inferential_unit",
            "repetitions_are_independent_units",
            "primary_test",
            "confidence_interval",
            "bootstrap_resamples",
            "bootstrap_seed",
            "alpha",
            "secondary_multiplicity",
            "report_per_query",
            "report_all_attempts",
            "missing_measurements",
        },
    )
    if analysis != {
        "inferential_unit": "query",
        "repetitions_are_independent_units": False,
        "primary_test": "exact_two_sided_McNemar_on_paired_query_correctness",
        "confidence_interval": "query_paired_bootstrap_percentile",
        "bootstrap_resamples": 10000,
        "bootstrap_seed": "m13e4-grailqa-semantic-ci-v1",
        "alpha": 0.05,
        "secondary_multiplicity": "holm_familywise_alpha_0_05",
        "report_per_query": True,
        "report_all_attempts": True,
        "missing_measurements": "no_imputation_failure_handled_by_selected_estimand",
    }:
        raise GrailQASemanticPaperProtocolError("analysis boundary changed")

    failure = _strict_object(
        protocol["failure_policy"],
        name="failure_policy",
        fields={
            "automatic_retries",
            "provider_failure",
            "malformed_output",
            "grounding_failure",
            "empty_admissible_set",
            "completer_only_analysis",
            "repair_call_limit",
        },
    )
    if failure != {
        "automatic_retries": 0,
        "provider_failure": "retained_as_query_outcome",
        "malformed_output": "retained_as_query_outcome",
        "grounding_failure": "retained_as_query_outcome",
        "empty_admissible_set": "retained_as_query_outcome",
        "completer_only_analysis": "secondary_diagnostic_only",
        "repair_call_limit": 1,
    }:
        raise GrailQASemanticPaperProtocolError("failure policy changed")

    isolation = _strict_object(
        protocol["evaluation_isolation"],
        name="evaluation_isolation",
        fields={
            "gold_forbidden_during_inference",
            "reference_opened_after_all_inference",
            "preflight_outcomes_forbidden_from_parameter_selection",
            "candidate_generation_reused_across_methods",
            "catalog_reachability_is_paper_semantic_baseline",
            "simulated_clarification_is_treatment",
        },
    )
    if isolation != {
        "gold_forbidden_during_inference": True,
        "reference_opened_after_all_inference": True,
        "preflight_outcomes_forbidden_from_parameter_selection": True,
        "candidate_generation_reused_across_methods": True,
        "catalog_reachability_is_paper_semantic_baseline": False,
        "simulated_clarification_is_treatment": False,
    }:
        raise GrailQASemanticPaperProtocolError("evaluation isolation changed")


def _decisions(
    protocol: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    decisions: list[dict[str, Any]] = []
    blockers: list[str] = []
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
        allowed = [str(value) for value in _array(raw["allowed_values"], name="allowed_values")]
        if not allowed or len(set(allowed)) != len(allowed):
            raise GrailQASemanticPaperProtocolError(
                f"{decision_id} allowed values are invalid"
            )
        recommended = str(raw["recommended_value"])
        selected = raw["selected_value"]
        if recommended not in allowed:
            raise GrailQASemanticPaperProtocolError(
                f"{decision_id} recommendation is not allowed"
            )
        if selected is not None and str(selected) not in allowed:
            raise GrailQASemanticPaperProtocolError(
                f"{decision_id} selected value is not allowed"
            )
        normalized = {
            "decision_id": decision_id,
            "allowed_values": allowed,
            "recommended_value": recommended,
            "selected_value": None if selected is None else str(selected),
        }
        decisions.append(normalized)
        if selected is None:
            blockers.append(f"author_decision.{decision_id}.unselected")
    if tuple(item["decision_id"] for item in decisions) != _DECISION_IDS:
        raise GrailQASemanticPaperProtocolError("author decision registry changed")
    return decisions, blockers


def _apply_author_selection(
    protocol: Mapping[str, Any], selection: str | Path | Mapping[str, Any] | None
) -> tuple[dict[str, Any], str | None, bool]:
    working = copy.deepcopy(dict(protocol))
    if selection is None:
        return working, None, False
    raw = (
        copy.deepcopy(dict(selection))
        if isinstance(selection, Mapping)
        else _load_json(Path(selection), name="author selection")
    )
    selected = _strict_object(
        raw,
        name="author_selection",
        fields={
            "schema_version",
            "protocol_sha256",
            "authority_source_id",
            "decisions",
            "selection_sha256",
        },
    )
    if selected["schema_version"] != AUTHOR_SELECTION_SCHEMA_VERSION:
        raise GrailQASemanticPaperProtocolError("author selection schema changed")
    if selected["protocol_sha256"] != content_hash(protocol):
        raise GrailQASemanticPaperProtocolError(
            "author selection does not bind this protocol"
        )
    _safe_id(selected["authority_source_id"], name="authority_source_id")
    decision_map = _strict_object(
        selected["decisions"], name="author_selection.decisions", fields=set(_DECISION_IDS)
    )
    body = {key: value for key, value in selected.items() if key != "selection_sha256"}
    selection_sha256 = _sha256(
        selected["selection_sha256"], name="selection_sha256"
    )
    if content_hash(body) != selection_sha256:
        raise GrailQASemanticPaperProtocolError("author selection hash mismatch")
    for item in working["author_decisions"]:
        item["selected_value"] = str(decision_map[item["decision_id"]])
    _decisions(working)
    return working, selection_sha256, True


def _requirements(
    protocol: Mapping[str, Any], *, repo_root: Path
) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    blockers: list[str] = []
    for index, item in enumerate(
        _array(protocol["implementation_requirements"], name="implementation_requirements")
    ):
        raw = _strict_object(
            item,
            name=f"implementation_requirements[{index}]",
            fields={"requirement_id", "status", "evidence"},
        )
        requirement_id = _safe_id(raw["requirement_id"], name="requirement_id")
        status = str(raw["status"])
        if status not in {"ready", "pending_live_evidence", "missing"}:
            raise GrailQASemanticPaperProtocolError(
                f"{requirement_id} status is invalid"
            )
        evidence = raw["evidence"]
        evidence_record: dict[str, Any] | None = None
        if status == "ready":
            evidence_raw = _strict_object(
                evidence,
                name=f"{requirement_id}.evidence",
                fields={"path", "sha256"},
            )
            path = _repo_file(repo_root, evidence_raw["path"], name=requirement_id)
            expected = _sha256(evidence_raw["sha256"], name=f"{requirement_id}.sha256")
            if _file_sha256(path) != expected:
                raise GrailQASemanticPaperProtocolError(
                    f"implementation evidence changed: {requirement_id}"
                )
            evidence_record = {"path": str(evidence_raw["path"]), "sha256": expected}
        elif evidence is not None:
            raise GrailQASemanticPaperProtocolError(
                f"{requirement_id} cannot claim evidence before it is ready"
            )
        if status != "ready":
            blockers.append(f"implementation.{requirement_id}.{status}")
        records.append(
            {
                "requirement_id": requirement_id,
                "status": status,
                "evidence": evidence_record,
            }
        )
    if tuple(item["requirement_id"] for item in records) != _REQUIREMENT_IDS:
        raise GrailQASemanticPaperProtocolError(
            "implementation requirement registry changed"
        )
    return records, blockers


def compile_grailqa_semantic_paper_readiness(
    protocol: str | Path | Mapping[str, Any] = DEFAULT_PROTOCOL_PATH,
    *,
    repo_root: str | Path = ".",
    author_selection: str | Path | Mapping[str, Any] | None = None,
) -> GrailQASemanticPaperReadiness:
    """Validate the draft and return a deterministic non-authorizing record."""

    root = Path(repo_root).resolve()
    raw = _load_protocol(protocol)
    raw = _strict_object(
        raw,
        name="protocol",
        fields={
            "schema_version",
            "protocol_id",
            "source_artifacts",
            "scope",
            "dataset_contract",
            "inference_contract",
            "methods",
            "outcomes",
            "analysis_design",
            "failure_policy",
            "evaluation_isolation",
            "preflight_gate",
            "author_decisions",
            "implementation_requirements",
            "claim_boundary",
            "automatic_retries",
            "paper_result",
            "freeze_hash",
        },
    )
    if raw["schema_version"] != PROTOCOL_SCHEMA_VERSION:
        raise GrailQASemanticPaperProtocolError("protocol schema changed")
    _safe_id(raw["protocol_id"], name="protocol_id")
    expected_freeze = _sha256(raw["freeze_hash"], name="freeze_hash")
    without_freeze = {key: value for key, value in raw.items() if key != "freeze_hash"}
    if content_hash(without_freeze) != expected_freeze:
        raise GrailQASemanticPaperProtocolError("protocol freeze_hash mismatch")
    if raw["automatic_retries"] != 0 or raw["paper_result"] is not False:
        raise GrailQASemanticPaperProtocolError(
            "protocol must disable retries and remain paper_result=false"
        )
    if raw["claim_boundary"] != {
        "artifact_class": "result_blind_semantic_protocol_draft",
        "contains_measurements": False,
        "author_approved": False,
        "full_150_run_authorized": False,
        "paper_result": False,
    }:
        raise GrailQASemanticPaperProtocolError("claim boundary changed")
    preflight_gate = _strict_object(
        raw["preflight_gate"],
        name="preflight_gate",
        fields={
            "independent_audit_required",
            "author_review_required",
            "parameter_tuning_from_preflight_forbidden",
            "full_150_execution_requires_separate_authority",
        },
    )
    if preflight_gate != {
        "independent_audit_required": True,
        "author_review_required": True,
        "parameter_tuning_from_preflight_forbidden": True,
        "full_150_execution_requires_separate_authority": True,
    }:
        raise GrailQASemanticPaperProtocolError("preflight gate changed")

    sources = _validate_sources(raw, repo_root=root)
    bound = _validate_bound_artifacts(raw, repo_root=root)
    _validate_scientific_contract(raw)
    selected_protocol, author_selection_sha256, author_approved = (
        _apply_author_selection(raw, author_selection)
    )
    decisions, decision_blockers = _decisions(selected_protocol)
    requirements, implementation_blockers = _requirements(raw, repo_root=root)
    blockers = sorted(
        {
            *decision_blockers,
            *implementation_blockers,
            "preflight18.author_review.pending",
            "execution_authority.full_150.missing",
            *(() if author_approved else ("author_approval.pending",)),
        }
    )
    body: dict[str, Any] = {
        "schema_version": READINESS_SCHEMA_VERSION,
        "protocol_id": raw["protocol_id"],
        "protocol_sha256": content_hash(raw),
        "author_selection_sha256": author_selection_sha256,
        "source_artifacts": sources,
        "bound_artifacts": bound,
        "author_decisions": decisions,
        "implementation_requirements": requirements,
        "gates": {
            "result_blind_protocol_structurally_valid": True,
            "all_author_decisions_selected": not decision_blockers,
            "author_approved": author_approved,
            "preflight18_independently_audited_and_reviewed": False,
            "paper_runner_and_analysis_ready": not implementation_blockers,
            "full_150_run_authorized": False,
        },
        "blockers": blockers,
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
            "artifact_class": "result_blind_semantic_protocol_readiness",
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
    return GrailQASemanticPaperReadiness(body)


def write_grailqa_semantic_paper_readiness(
    readiness: GrailQASemanticPaperReadiness, output: str | Path
) -> Path:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"semantic readiness output exists: {destination}")
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
    parser.add_argument("--author-selection")
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    try:
        readiness = compile_grailqa_semantic_paper_readiness(
            arguments.protocol,
            repo_root=arguments.repo_root,
            author_selection=arguments.author_selection,
        )
        write_grailqa_semantic_paper_readiness(readiness, arguments.output)
    except (FileExistsError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps({"status": "success", **readiness.to_dict()}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
