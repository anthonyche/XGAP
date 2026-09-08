"""Evidence-bound admission for the GrailQA semantic paper execution.

This module keeps three materially different decisions separate:

* an independent auditor verifies the 150-query catalog and the 18-query
  preflight;
* an author explicitly reviews the exact preflight audit without tuning the
  frozen scientific choices from its outcomes;
* a deterministic admission record binds those artifacts to the already
  explicit five-choice author selection.

Admission is deliberately non-authorizing.  A separate execution authority is
still required before the 150-query model run can start.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from xgap.experiments.grailqa_catalog_v2 import GrailQAInferenceCatalogV2
from xgap.experiments.grailqa_local_catalog import validate_local_catalog
from xgap.experiments.grailqa_semantic_paper_protocol import (
    DEFAULT_PROTOCOL_PATH,
    compile_grailqa_semantic_paper_readiness,
)
from xgap.experiments.hashing import content_hash


PREFLIGHT_REVIEW_SCHEMA_VERSION = (
    "m13e4-grailqa-semantic-preflight-author-review-v1"
)
PREEXECUTION_ADMISSION_SCHEMA_VERSION = (
    "m13e4-grailqa-semantic-preexecution-admission-v1"
)
CATALOG_AUDIT_SCHEMA_VERSION = (
    "m13e4-grailqa-local-catalog-evidence-audit-v1"
)
PREFLIGHT_AUDIT_SCHEMA_VERSION = (
    "m13e3b5-grailqa-preflight-evidence-audit-v1"
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_DECISIONS = {
    "primary_reporting_population": {
        "all_150_plus_joint_reachability_stratum",
        "jointly_reachable_only",
        "defer_semantic_track",
    },
    "primary_epsilon": {"0.0", "0.1", "0.25"},
    "primary_comparator": {
        "model_confidence_top1_same_candidate_set",
        "first_valid_grounded_candidate",
    },
    "inference_failure_estimand": {
        "all_queries_failures_count_incorrect",
        "available_case_primary_with_all_query_sensitivity",
    },
    "interactive_clarification_role": {
        "oracle_upper_bound_only",
        "exclude_from_grailqa",
    },
}


class GrailQASemanticPaperAdmissionError(ValueError):
    """Raised when the admission evidence chain is incomplete or changed."""


def _regular_file(path: str | Path, *, name: str) -> Path:
    value = Path(path)
    if value.is_symlink() or not value.is_file():
        raise GrailQASemanticPaperAdmissionError(
            f"{name} must be a regular non-symbolic-link file"
        )
    return value.resolve()


def _regular_directory(path: str | Path, *, name: str) -> Path:
    value = Path(path)
    if value.is_symlink() or not value.is_dir():
        raise GrailQASemanticPaperAdmissionError(
            f"{name} must be a non-symbolic-link directory"
        )
    return value.resolve()


def _load_json(path: str | Path, *, name: str) -> dict[str, Any]:
    source = _regular_file(path, name=name)
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise GrailQASemanticPaperAdmissionError(f"{name} must contain an object")
    return dict(value)


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"output already exists: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            dict(value),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _validate_self_hash(
    value: Mapping[str, Any], *, field: str, name: str
) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    claimed = result.get(field)
    body = {key: item for key, item in result.items() if key != field}
    if (
        not isinstance(claimed, str)
        or _SHA256.fullmatch(claimed) is None
        or content_hash(body) != claimed
    ):
        raise GrailQASemanticPaperAdmissionError(f"{name} self-hash is invalid")
    return result


def validate_grailqa_catalog_audit(value: Mapping[str, Any]) -> dict[str, Any]:
    audit = _validate_self_hash(
        value, field="audit_sha256", name="catalog audit"
    )
    boundary = audit.get("claim_boundary")
    calls = audit.get("external_call_counts")
    source = audit.get("source_verification_boundary")
    if (
        audit.get("schema_version") != CATALOG_AUDIT_SCHEMA_VERSION
        or audit.get("success") is not True
        or audit.get("failed_check_ids") != []
        or audit.get("run_tree_mutated") is not False
        or audit.get("question_count") != 150
        or audit.get("paper_result") is not False
        or _COMMIT.fullmatch(str(audit.get("expected_builder_commit", "")))
        is None
        or _SHA256.fullmatch(str(audit.get("catalog_hash", ""))) is None
        or _SHA256.fullmatch(
            str(audit.get("reachability_audit_hash", ""))
        )
        is None
        or not isinstance(audit.get("check_count"), int)
        or int(audit["check_count"]) <= 0
        or not isinstance(boundary, Mapping)
        or boundary.get("independent_catalog_reconstruction") is not True
        or boundary.get("catalog_construction_gold_blind") is not True
        or boundary.get("reachability_uses_gold_for_evaluation_only") is not True
        or boundary.get("authorizes_model_execution") is not False
        or boundary.get("paper_result") is not False
        or calls
        != {
            "llm_calls": 0,
            "backend_calls": 0,
            "ontology_service_calls": 0,
        }
        or not isinstance(source, Mapping)
        or source.get("source_inventory_bound") is not True
        or source.get("freebase_bytes_rescanned_by_auditor") != 0
    ):
        raise GrailQASemanticPaperAdmissionError(
            "catalog audit does not admit the frozen pilot150 catalog"
        )
    return audit


def validate_grailqa_preflight_audit(value: Mapping[str, Any]) -> dict[str, Any]:
    audit = _validate_self_hash(
        value, field="audit_sha256", name="preflight audit"
    )
    boundary = audit.get("claim_boundary")
    if (
        audit.get("schema_version") != PREFLIGHT_AUDIT_SCHEMA_VERSION
        or audit.get("success") is not True
        or audit.get("failed_check_ids") != []
        or audit.get("run_tree_mutated") is not False
        or _COMMIT.fullmatch(str(audit.get("expected_commit", ""))) is None
        or not isinstance(audit.get("check_count"), int)
        or int(audit["check_count"]) <= 0
        or not isinstance(boundary, Mapping)
        or boundary.get("development_preflight_only") is not True
        or boundary.get("paper_result") is not False
        or boundary.get("full_150_run_authorized") is not False
        or boundary.get("backend_execution") is not False
    ):
        raise GrailQASemanticPaperAdmissionError(
            "preflight audit is not a successful non-authorizing audit"
        )
    return audit


def build_grailqa_preflight_author_review(
    *,
    preflight_audit: Mapping[str, Any],
    authority_source_id: str,
    decision: str,
) -> dict[str, Any]:
    """Bind an explicit author review to one exact successful audit."""

    audit = validate_grailqa_preflight_audit(preflight_audit)
    if _SAFE_ID.fullmatch(authority_source_id) is None:
        raise GrailQASemanticPaperAdmissionError("authority_source_id is not safe")
    if decision != "accept_exact_preflight_without_parameter_tuning":
        raise GrailQASemanticPaperAdmissionError(
            "decision does not accept the exact preflight under the frozen policy"
        )
    body: dict[str, Any] = {
        "schema_version": PREFLIGHT_REVIEW_SCHEMA_VERSION,
        "preflight_audit_sha256": audit["audit_sha256"],
        "preflight_runner_commit": audit["expected_commit"],
        "authority_source_id": authority_source_id,
        "decision": decision,
        "reviewed_exact_audit": True,
        "parameter_tuning_from_preflight_forbidden": True,
        "full_150_execution_authorized": False,
        "paper_result": False,
    }
    return {**body, "preflight_review_sha256": content_hash(body)}


def validate_grailqa_preflight_author_review(
    *,
    preflight_audit: Mapping[str, Any],
    author_review: Mapping[str, Any],
) -> dict[str, Any]:
    audit = validate_grailqa_preflight_audit(preflight_audit)
    review = _validate_self_hash(
        author_review,
        field="preflight_review_sha256",
        name="preflight author review",
    )
    if (
        review.get("schema_version") != PREFLIGHT_REVIEW_SCHEMA_VERSION
        or review.get("preflight_audit_sha256") != audit["audit_sha256"]
        or review.get("preflight_runner_commit") != audit["expected_commit"]
        or _SAFE_ID.fullmatch(str(review.get("authority_source_id", ""))) is None
        or review.get("decision")
        != "accept_exact_preflight_without_parameter_tuning"
        or review.get("reviewed_exact_audit") is not True
        or review.get("parameter_tuning_from_preflight_forbidden") is not True
        or review.get("full_150_execution_authorized") is not False
        or review.get("paper_result") is not False
    ):
        raise GrailQASemanticPaperAdmissionError(
            "author review does not bind the exact preflight audit"
        )
    return review


def _selected_decisions(readiness: Mapping[str, Any]) -> dict[str, str]:
    selected = {
        str(item["decision_id"]): item.get("selected_value")
        for item in readiness["author_decisions"]
    }
    if any(value is None for value in selected.values()):
        raise GrailQASemanticPaperAdmissionError(
            "all five author decisions must be selected"
        )
    return {key: str(value) for key, value in selected.items()}


def build_grailqa_semantic_preexecution_admission(
    *,
    protocol_path: str | Path,
    author_selection_path: str | Path,
    repo_root: str | Path,
    catalog_root: str | Path,
    reachability_summary_path: str | Path,
    catalog_audit: Mapping[str, Any],
    preflight_audit: Mapping[str, Any],
    author_review: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind all non-authorizing prerequisites for one exact paper protocol."""

    repo = _regular_directory(repo_root, name="repo_root")
    protocol = _regular_file(protocol_path, name="semantic protocol")
    selection = _regular_file(author_selection_path, name="author selection")
    readiness = compile_grailqa_semantic_paper_readiness(
        protocol,
        repo_root=repo,
        author_selection=selection,
    ).to_dict()
    if (
        readiness["gates"]["author_approved"] is not True
        or readiness["gates"]["paper_runner_and_analysis_ready"] is not True
    ):
        raise GrailQASemanticPaperAdmissionError(
            "protocol, author selection, runner, or analysis is not ready"
        )
    selected = _selected_decisions(readiness)
    catalog_path = _regular_directory(catalog_root, name="pilot150 catalog")
    catalog = GrailQAInferenceCatalogV2.load(catalog_path)
    validate_local_catalog(catalog_path)
    manifest = catalog.manifest
    if (
        manifest.get("local_catalog_schema_version")
        != "m13e3b-grailqa-local-catalog-v1"
        or manifest.get("requires_query_entity_filter") is not True
        or manifest.get("gold_used_for_construction") is not False
        or len(tuple(manifest.get("question_ids", ()))) != 150
    ):
        raise GrailQASemanticPaperAdmissionError(
            "admission requires the gold-blind pilot150 query-local catalog"
        )
    reachability = _load_json(
        reachability_summary_path, name="reachability summary"
    )
    if (
        reachability.get("catalog_hash") != catalog.catalog_hash
        or reachability.get("question_count") != 150
        or reachability.get("live_preflight_allowed") is not True
        or _SHA256.fullmatch(str(reachability.get("audit_hash", ""))) is None
    ):
        raise GrailQASemanticPaperAdmissionError(
            "reachability summary does not admit this pilot150 catalog"
        )
    catalog_evidence = validate_grailqa_catalog_audit(catalog_audit)
    preflight_evidence = validate_grailqa_preflight_audit(preflight_audit)
    review = validate_grailqa_preflight_author_review(
        preflight_audit=preflight_evidence,
        author_review=author_review,
    )
    if (
        catalog_evidence["catalog_hash"] != catalog.catalog_hash
        or catalog_evidence["reachability_audit_hash"]
        != reachability["audit_hash"]
        or Path(str(catalog_evidence.get("catalog_root", ""))).resolve()
        != catalog_path
    ):
        raise GrailQASemanticPaperAdmissionError(
            "catalog audit does not bind the current catalog and reachability"
        )
    body: dict[str, Any] = {
        "schema_version": PREEXECUTION_ADMISSION_SCHEMA_VERSION,
        "protocol_sha256": readiness["protocol_sha256"],
        "author_selection_sha256": readiness["author_selection_sha256"],
        "selected_decisions": selected,
        "catalog_hash": catalog.catalog_hash,
        "reachability_audit_hash": reachability["audit_hash"],
        "catalog_audit": catalog_evidence,
        "preflight_audit": preflight_evidence,
        "author_preflight_review": review,
        "gates": {
            "catalog_independently_audited": True,
            "preflight_independently_audited": True,
            "preflight_explicitly_reviewed_by_author": True,
            "parameter_tuning_from_preflight_forbidden": True,
            "all_five_scientific_decisions_explicit": True,
        },
        "external_call_counts": {
            "llm_calls": 0,
            "backend_calls": 0,
            "ontology_service_calls": 0,
        },
        "full_150_execution_authorized": False,
        "paper_result": False,
    }
    return {**body, "preexecution_admission_sha256": content_hash(body)}


def validate_grailqa_semantic_preexecution_admission(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    admission = _validate_self_hash(
        value,
        field="preexecution_admission_sha256",
        name="preexecution admission",
    )
    catalog = validate_grailqa_catalog_audit(
        dict(admission.get("catalog_audit", {}))
    )
    preflight = validate_grailqa_preflight_audit(
        dict(admission.get("preflight_audit", {}))
    )
    review = validate_grailqa_preflight_author_review(
        preflight_audit=preflight,
        author_review=dict(admission.get("author_preflight_review", {})),
    )
    gates = admission.get("gates")
    selected = admission.get("selected_decisions")
    if (
        admission.get("schema_version") != PREEXECUTION_ADMISSION_SCHEMA_VERSION
        or _SHA256.fullmatch(str(admission.get("protocol_sha256", ""))) is None
        or _SHA256.fullmatch(
            str(admission.get("author_selection_sha256", ""))
        )
        is None
        or not isinstance(selected, Mapping)
        or set(selected) != set(_ALLOWED_DECISIONS)
        or any(
            str(selected[key]) not in allowed
            for key, allowed in _ALLOWED_DECISIONS.items()
        )
        or admission.get("catalog_hash") != catalog["catalog_hash"]
        or admission.get("reachability_audit_hash")
        != catalog["reachability_audit_hash"]
        or review["preflight_audit_sha256"] != preflight["audit_sha256"]
        or gates
        != {
            "catalog_independently_audited": True,
            "preflight_independently_audited": True,
            "preflight_explicitly_reviewed_by_author": True,
            "parameter_tuning_from_preflight_forbidden": True,
            "all_five_scientific_decisions_explicit": True,
        }
        or admission.get("external_call_counts")
        != {
            "llm_calls": 0,
            "backend_calls": 0,
            "ontology_service_calls": 0,
        }
        or admission.get("full_150_execution_authorized") is not False
        or admission.get("paper_result") is not False
    ):
        raise GrailQASemanticPaperAdmissionError(
            "preexecution admission is invalid"
        )
    return admission


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    review = commands.add_parser("review")
    review.add_argument("--preflight-audit", required=True)
    review.add_argument("--authority-source-id", required=True)
    review.add_argument(
        "--decision",
        required=True,
        choices=("accept_exact_preflight_without_parameter_tuning",),
    )
    review.add_argument("--output", required=True)
    admit = commands.add_parser("admit")
    admit.add_argument("--protocol", default=str(DEFAULT_PROTOCOL_PATH))
    admit.add_argument("--author-selection", required=True)
    admit.add_argument("--repo-root", default=".")
    admit.add_argument("--catalog-root", required=True)
    admit.add_argument("--reachability-summary", required=True)
    admit.add_argument("--catalog-audit", required=True)
    admit.add_argument("--preflight-audit", required=True)
    admit.add_argument("--preflight-review", required=True)
    admit.add_argument("--output", required=True)
    check = commands.add_parser("check")
    check.add_argument("--admission", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "review":
            result = build_grailqa_preflight_author_review(
                preflight_audit=_load_json(
                    args.preflight_audit, name="preflight audit"
                ),
                authority_source_id=args.authority_source_id,
                decision=args.decision,
            )
            _write_json_exclusive(Path(args.output), result)
        elif args.command == "admit":
            result = build_grailqa_semantic_preexecution_admission(
                protocol_path=args.protocol,
                author_selection_path=args.author_selection,
                repo_root=args.repo_root,
                catalog_root=args.catalog_root,
                reachability_summary_path=args.reachability_summary,
                catalog_audit=_load_json(args.catalog_audit, name="catalog audit"),
                preflight_audit=_load_json(
                    args.preflight_audit, name="preflight audit"
                ),
                author_review=_load_json(
                    args.preflight_review, name="preflight author review"
                ),
            )
            _write_json_exclusive(Path(args.output), result)
        else:
            result = validate_grailqa_semantic_preexecution_admission(
                _load_json(args.admission, name="preexecution admission")
            )
    except (
        FileExistsError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps({"status": "success", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
