"""Authority-gated, gold-isolated GrailQA 150-query semantic runner.

The runner has three explicit phases:

1. bind an exact result-blind execution request;
2. require a separate author execution authority;
3. run all 150 model calls, seal their inference states, and only then open
   gold-derived reachability/reference artifacts to build the outcome ledger.

The module never executes a graph backend or emits native query text.  It also
does not run the statistical analyzer: the frozen outcome ledger is consumed
later by the producer analyzer and its independent auditor.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Mapping, Sequence

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.cwru_vllm import load_run_environment
from xgap.experiments.grailqa_catalog_v2 import GrailQAInferenceCatalogV2
from xgap.experiments.grailqa_local_catalog import validate_local_catalog
from xgap.experiments.grailqa_semantic_analysis import QUERY_OUTCOME_SCHEMA_VERSION
from xgap.experiments.grailqa_semantic_paper_protocol import (
    DEFAULT_PROTOCOL_PATH,
    compile_grailqa_semantic_paper_readiness,
)
from xgap.experiments.grailqa_semantic_paper_admission import (
    validate_grailqa_semantic_preexecution_admission,
)
from xgap.experiments.grailqa_semantic_pilot import (
    LiveSemanticPilotProvider,
    SemanticPilotProvider,
    _infer_one,
    canonical_interpretation,
    strict_inference_leakage_audit,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.interpretation_contract import (
    component_match_report,
    parse_normalized_planner_response,
)
from xgap.experiments.relation_endpoints import RELATION_ENDPOINT_CONTRACT_VERSION
from xgap.experiments.semantic import (
    DirectionalOntologyDeviation,
    SemanticDeviationConfig,
)


EXECUTION_REQUEST_SCHEMA_VERSION = (
    "m13e4-grailqa-semantic-execution-request-v2"
)
EXECUTION_AUTHORITY_SCHEMA_VERSION = (
    "m13e4-grailqa-semantic-execution-authority-v2"
)
INFERENCE_SEAL_SCHEMA_VERSION = "m13e4-grailqa-semantic-inference-seal-v2"
RUN_MANIFEST_SCHEMA_VERSION = "m13e4-grailqa-semantic-paper-run-v2"
RUN_STATUS_SCHEMA_VERSION = "m13e4-grailqa-semantic-paper-run-status-v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class GrailQASemanticPaperRunError(ValueError):
    """Raised when a semantic paper run violates its frozen boundary."""


def _regular_file(path: str | Path, *, name: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise GrailQASemanticPaperRunError(
            f"{name} must be a regular non-symbolic-link file"
        )
    return candidate.resolve()


def _regular_directory(path: str | Path, *, name: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_dir():
        raise GrailQASemanticPaperRunError(
            f"{name} must be a non-symbolic-link directory"
        )
    return candidate.resolve()


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: str | Path, *, name: str) -> dict[str, Any]:
    source = _regular_file(path, name=name)
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise GrailQASemanticPaperRunError(f"{name} must contain an object")
    return dict(value)


def _load_jsonl(path: str | Path, *, name: str) -> list[dict[str, Any]]:
    source = _regular_file(path, name=name)
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        source.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line:
            continue
        value = json.loads(line)
        if not isinstance(value, Mapping):
            raise GrailQASemanticPaperRunError(
                f"{name} line {line_number} must contain an object"
            )
        rows.append(dict(value))
    return rows


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


def _write_jsonl_exclusive(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"output already exists: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(
            json.dumps(
                dict(row),
                sort_keys=True,
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _exact_ids(
    values: Sequence[object], expected: Sequence[str], *, name: str
) -> tuple[str, ...]:
    ids = tuple(str(item) for item in values)
    target = tuple(str(item) for item in expected)
    if (
        len(ids) != 150
        or len(set(ids)) != 150
        or set(ids) != set(target)
        or any(_SAFE_ID.fullmatch(item) is None for item in ids)
    ):
        raise GrailQASemanticPaperRunError(
            f"{name} must cover the exact frozen 150-query population"
        )
    return ids


def _git_commit(repo_root: Path) -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _selected_decisions(readiness: Mapping[str, Any]) -> dict[str, str]:
    result = {
        str(item["decision_id"]): str(item["selected_value"])
        for item in readiness["author_decisions"]
    }
    if any(value == "None" for value in result.values()):
        raise GrailQASemanticPaperRunError(
            "all five author decisions must be selected before a request is built"
        )
    return result


def _validate_local_150_catalog(
    catalog_root: Path, expected_ids: Sequence[str]
) -> GrailQAInferenceCatalogV2:
    catalog = GrailQAInferenceCatalogV2.load(catalog_root)
    manifest = catalog.manifest
    if (
        manifest.get("local_catalog_schema_version")
        != "m13e3b-grailqa-local-catalog-v1"
        or manifest.get("requires_query_entity_filter") is not True
        or manifest.get("gold_used_for_construction") is not False
    ):
        raise GrailQASemanticPaperRunError(
            "paper execution requires the gold-blind query-local catalog"
        )
    _exact_ids(
        tuple(manifest.get("question_ids", ())),
        expected_ids,
        name="query-local catalog",
    )
    validate_local_catalog(catalog_root)
    return catalog


def _validate_reachability_artifacts(
    *,
    summary_path: Path,
    rows_path: Path,
    catalog_hash: str,
    expected_ids: Sequence[str],
    parse_rows: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    summary = _load_json(summary_path, name="reachability summary")
    if (
        summary.get("schema_version")
        != "m13e3b4-grailqa-local-reachability-v2"
        or int(summary.get("question_count", -1)) != 150
        or int(summary.get("prompt_limit", -1)) != 4
        or summary.get("catalog_hash") != catalog_hash
        or summary.get("gold_used_for_construction") is not False
    ):
        raise GrailQASemanticPaperRunError(
            "pilot150 reachability summary violates the frozen contract"
        )
    endpoint = summary.get("relation_endpoint_grounding")
    if (
        not isinstance(endpoint, Mapping)
        or endpoint.get("contract_version") != RELATION_ENDPOINT_CONTRACT_VERSION
    ):
        raise GrailQASemanticPaperRunError(
            "reachability endpoint-grounding contract changed"
        )
    body = {key: value for key, value in summary.items() if key != "audit_hash"}
    if content_hash(body) != summary.get("audit_hash"):
        raise GrailQASemanticPaperRunError("reachability audit hash mismatch")
    rows_sha256 = _sha256_file(rows_path)
    artifact_hashes = summary.get("artifact_hashes")
    if (
        not isinstance(artifact_hashes, Mapping)
        or artifact_hashes.get("reachability.jsonl") != rows_sha256
    ):
        raise GrailQASemanticPaperRunError("reachability row hash mismatch")
    if not parse_rows:
        return summary, None
    rows = _load_jsonl(rows_path, name="reachability rows")
    _exact_ids(
        [item.get("question_id") for item in rows],
        expected_ids,
        name="reachability rows",
    )
    for row in rows:
        row_endpoint = row.get("relation_endpoint_grounding")
        if (
            not isinstance(row_endpoint, Mapping)
            or row_endpoint.get("contract_version")
            != RELATION_ENDPOINT_CONTRACT_VERSION
        ):
            raise GrailQASemanticPaperRunError(
                "a reachability row changed endpoint-grounding contract"
            )
    return summary, rows


def build_grailqa_semantic_execution_request(
    *,
    protocol_path: str | Path,
    author_selection_path: str | Path,
    repo_root: str | Path,
    catalog_root: str | Path,
    reachability_summary_path: str | Path,
    reachability_rows_path: str | Path,
    preexecution_admission_path: str | Path,
    run_id: str,
    runner_commit: str | None = None,
) -> dict[str, Any]:
    """Bind one exact, still non-authorizing 150-query execution request."""

    if _SAFE_ID.fullmatch(run_id) is None:
        raise GrailQASemanticPaperRunError("run_id is not a safe identifier")
    repo = _regular_directory(repo_root, name="repo_root")
    protocol = _regular_file(protocol_path, name="semantic protocol")
    selection = _regular_file(author_selection_path, name="author selection")
    readiness = compile_grailqa_semantic_paper_readiness(
        protocol,
        repo_root=repo,
        author_selection=selection,
    ).to_dict()
    if readiness["gates"]["author_approved"] is not True:
        raise GrailQASemanticPaperRunError("author selection is not approved")
    decisions = _selected_decisions(readiness)
    admission = validate_grailqa_semantic_preexecution_admission(
        _load_json(
            preexecution_admission_path,
            name="preexecution admission",
        )
    )
    pilot_path = repo / "datasets/grailqa_pilot_v1/pilot_ids.json"
    pilot = _load_json(pilot_path, name="GrailQA pilot selection")
    expected_ids = _exact_ids(
        pilot.get("question_ids", ()),
        pilot.get("question_ids", ()),
        name="GrailQA pilot selection",
    )
    catalog_path = _regular_directory(catalog_root, name="pilot150 catalog")
    catalog = _validate_local_150_catalog(catalog_path, expected_ids)
    summary_path = _regular_file(
        reachability_summary_path, name="reachability summary"
    )
    rows_path = _regular_file(reachability_rows_path, name="reachability rows")
    summary, rows = _validate_reachability_artifacts(
        summary_path=summary_path,
        rows_path=rows_path,
        catalog_hash=catalog.catalog_hash,
        expected_ids=expected_ids,
        parse_rows=True,
    )
    assert rows is not None
    if (
        admission["protocol_sha256"] != readiness["protocol_sha256"]
        or admission["author_selection_sha256"]
        != readiness["author_selection_sha256"]
        or admission["selected_decisions"] != decisions
        or admission["catalog_hash"] != catalog.catalog_hash
        or admission["reachability_audit_hash"] != summary["audit_hash"]
    ):
        raise GrailQASemanticPaperRunError(
            "preexecution admission does not bind the current frozen inputs"
        )
    commit = runner_commit or _git_commit(repo)
    if _COMMIT.fullmatch(commit) is None:
        raise GrailQASemanticPaperRunError("runner_commit must be exact 40-hex")
    inference = readiness["bound_artifacts"]
    body: dict[str, Any] = {
        "schema_version": EXECUTION_REQUEST_SCHEMA_VERSION,
        "run_id": run_id,
        "runner_commit": commit,
        "protocol_sha256": readiness["protocol_sha256"],
        "author_selection_sha256": readiness["author_selection_sha256"],
        "preexecution_admission_sha256": admission[
            "preexecution_admission_sha256"
        ],
        "selected_decisions": decisions,
        "population": {
            "query_count": 150,
            "question_ids_sha256": content_hash(list(expected_ids)),
            "pilot_selection_sha256": _sha256_file(pilot_path),
            "split_distribution": pilot["distribution"]["split"],
            "q_distribution": pilot["distribution"]["Q"],
        },
        "catalog": {
            "catalog_hash": catalog.catalog_hash,
            "manifest_sha256": _sha256_file(catalog_path / "manifest.json"),
            "question_count": 150,
            "query_local": True,
            "gold_used_for_construction": False,
        },
        "reachability": {
            "audit_hash": summary["audit_hash"],
            "summary_sha256": _sha256_file(summary_path),
            "rows_sha256": _sha256_file(rows_path),
            "question_count": len(rows),
            "opened_by_runner_after_inference_seal": True,
        },
        "inference": {
            "model_bundle_hash": inference["model_bundle_hash"],
            "query_count": 150,
            "retrieval_k": 20,
            "prompt_candidates_per_slot": 4,
            "candidate_cap": 3,
            "maximum_repair_calls_per_query": 1,
            "maximum_external_calls_per_query": 2,
            "automatic_retries": 0,
            "native_query_generation": False,
            "backend_execution": False,
        },
        "evaluation_isolation": {
            "gold_forbidden_during_inference": True,
            "all_query_states_sealed_before_gold_open": True,
            "shared_candidate_set_across_methods": True,
            "failures_retained": True,
        },
        "full_150_execution_authorized": False,
        "paper_result": False,
    }
    return {**body, "execution_request_sha256": content_hash(body)}


def build_grailqa_semantic_execution_authority(
    *,
    execution_request: Mapping[str, Any],
    preexecution_admission: Mapping[str, Any],
    authority_source_id: str,
    decision: str,
) -> dict[str, Any]:
    """Create authority only for an explicit exact-run authorization command."""

    request = validate_grailqa_semantic_execution_request(execution_request)
    admission = validate_grailqa_semantic_preexecution_admission(
        preexecution_admission
    )
    if (
        request["preexecution_admission_sha256"]
        != admission["preexecution_admission_sha256"]
    ):
        raise GrailQASemanticPaperRunError(
            "execution request does not bind this preexecution admission"
        )
    if _SAFE_ID.fullmatch(authority_source_id) is None:
        raise GrailQASemanticPaperRunError("authority_source_id is not safe")
    if decision != "authorize_exact_150_query_semantic_execution":
        raise GrailQASemanticPaperRunError(
            "decision does not authorize the exact 150-query semantic run"
        )
    body: dict[str, Any] = {
        "schema_version": EXECUTION_AUTHORITY_SCHEMA_VERSION,
        "execution_request_sha256": request["execution_request_sha256"],
        "preexecution_admission_sha256": admission[
            "preexecution_admission_sha256"
        ],
        "run_id": request["run_id"],
        "runner_commit": request["runner_commit"],
        "authority_source_id": authority_source_id,
        "decision": decision,
        "authorized_scope": {
            "query_count": 150,
            "maximum_external_calls": 300,
            "maximum_repair_calls_per_query": 1,
            "automatic_retries": 0,
            "backend_execution": False,
        },
        "full_150_execution_authorized": True,
        "single_run_only": True,
        "scope_expansion_requires_new_authority": True,
        "paper_result": False,
    }
    return {**body, "execution_authority_sha256": content_hash(body)}


def validate_grailqa_semantic_execution_request(
    value: Mapping[str, Any]
) -> dict[str, Any]:
    request = dict(value)
    expected = request.get("execution_request_sha256")
    body = {
        key: item
        for key, item in request.items()
        if key != "execution_request_sha256"
    }
    if (
        request.get("schema_version") != EXECUTION_REQUEST_SCHEMA_VERSION
        or not isinstance(expected, str)
        or _SHA256.fullmatch(expected) is None
        or content_hash(body) != expected
        or request.get("full_150_execution_authorized") is not False
        or request.get("paper_result") is not False
    ):
        raise GrailQASemanticPaperRunError("execution request is invalid")
    inference = request.get("inference")
    population = request.get("population")
    catalog = request.get("catalog")
    reachability = request.get("reachability")
    isolation = request.get("evaluation_isolation")
    selected = request.get("selected_decisions")
    allowed_decisions = {
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
    if (
        not isinstance(inference, Mapping)
        or not isinstance(population, Mapping)
        or not isinstance(catalog, Mapping)
        or not isinstance(reachability, Mapping)
        or not isinstance(isolation, Mapping)
        or not isinstance(selected, Mapping)
        or set(selected) != set(allowed_decisions)
        or any(
            str(selected[key]) not in allowed
            for key, allowed in allowed_decisions.items()
        )
        or _SAFE_ID.fullmatch(str(request.get("run_id", ""))) is None
        or _COMMIT.fullmatch(str(request.get("runner_commit", ""))) is None
        or _SHA256.fullmatch(str(request.get("protocol_sha256", ""))) is None
        or _SHA256.fullmatch(
            str(request.get("author_selection_sha256", ""))
        )
        is None
        or _SHA256.fullmatch(
            str(request.get("preexecution_admission_sha256", ""))
        )
        is None
        or population.get("query_count") != 150
        or _SHA256.fullmatch(
            str(population.get("question_ids_sha256", ""))
        )
        is None
        or _SHA256.fullmatch(
            str(population.get("pilot_selection_sha256", ""))
        )
        is None
        or catalog.get("question_count") != 150
        or catalog.get("query_local") is not True
        or catalog.get("gold_used_for_construction") is not False
        or _SHA256.fullmatch(str(catalog.get("catalog_hash", ""))) is None
        or _SHA256.fullmatch(str(catalog.get("manifest_sha256", ""))) is None
        or reachability.get("question_count") != 150
        or reachability.get("opened_by_runner_after_inference_seal") is not True
        or _SHA256.fullmatch(str(reachability.get("audit_hash", ""))) is None
        or _SHA256.fullmatch(str(reachability.get("summary_sha256", ""))) is None
        or _SHA256.fullmatch(str(reachability.get("rows_sha256", ""))) is None
        or inference.get("query_count") != 150
        or _SHA256.fullmatch(str(inference.get("model_bundle_hash", ""))) is None
        or inference.get("retrieval_k") != 20
        or inference.get("prompt_candidates_per_slot") != 4
        or inference.get("candidate_cap") != 3
        or inference.get("maximum_repair_calls_per_query") != 1
        or inference.get("maximum_external_calls_per_query") != 2
        or inference.get("automatic_retries") != 0
        or inference.get("native_query_generation") is not False
        or inference.get("backend_execution") is not False
        or isolation.get("gold_forbidden_during_inference") is not True
        or isolation.get("all_query_states_sealed_before_gold_open") is not True
        or isolation.get("shared_candidate_set_across_methods") is not True
        or isolation.get("failures_retained") is not True
    ):
        raise GrailQASemanticPaperRunError("execution request scope changed")
    return request


def validate_grailqa_semantic_execution_authority(
    *,
    execution_request: Mapping[str, Any],
    preexecution_admission: Mapping[str, Any],
    authority: Mapping[str, Any],
) -> dict[str, Any]:
    request = validate_grailqa_semantic_execution_request(execution_request)
    admission = validate_grailqa_semantic_preexecution_admission(
        preexecution_admission
    )
    value = dict(authority)
    expected = value.get("execution_authority_sha256")
    body = {
        key: item
        for key, item in value.items()
        if key != "execution_authority_sha256"
    }
    scope = value.get("authorized_scope")
    if (
        value.get("schema_version") != EXECUTION_AUTHORITY_SCHEMA_VERSION
        or not isinstance(expected, str)
        or _SHA256.fullmatch(expected) is None
        or content_hash(body) != expected
        or value.get("execution_request_sha256")
        != request["execution_request_sha256"]
        or request.get("preexecution_admission_sha256")
        != admission["preexecution_admission_sha256"]
        or value.get("preexecution_admission_sha256")
        != admission["preexecution_admission_sha256"]
        or value.get("run_id") != request["run_id"]
        or value.get("runner_commit") != request["runner_commit"]
        or value.get("decision")
        != "authorize_exact_150_query_semantic_execution"
        or value.get("full_150_execution_authorized") is not True
        or value.get("single_run_only") is not True
        or value.get("scope_expansion_requires_new_authority") is not True
        or value.get("paper_result") is not False
        or not isinstance(scope, Mapping)
        or scope
        != {
            "query_count": 150,
            "maximum_external_calls": 300,
            "maximum_repair_calls_per_query": 1,
            "automatic_retries": 0,
            "backend_execution": False,
        }
    ):
        raise GrailQASemanticPaperRunError("execution authority is invalid")
    return value


def _validate_run_inputs_without_opening_gold(
    *,
    request: Mapping[str, Any],
    admission: Mapping[str, Any],
    authority: Mapping[str, Any],
    repo_root: Path,
    protocol_path: Path,
    author_selection_path: Path,
    catalog_root: Path,
    reachability_summary_path: Path,
    reachability_rows_path: Path,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    tuple[str, ...],
    GrailQAInferenceCatalogV2,
    ModelBundle,
]:
    """Validate identities before inference; hash but do not parse gold artifacts."""

    frozen_request = validate_grailqa_semantic_execution_request(request)
    frozen_admission = validate_grailqa_semantic_preexecution_admission(
        admission
    )
    frozen_authority = validate_grailqa_semantic_execution_authority(
        execution_request=frozen_request,
        preexecution_admission=frozen_admission,
        authority=authority,
    )
    if _git_commit(repo_root) != frozen_request["runner_commit"]:
        raise GrailQASemanticPaperRunError("runner commit differs from authority")
    readiness = compile_grailqa_semantic_paper_readiness(
        protocol_path,
        repo_root=repo_root,
        author_selection=author_selection_path,
    ).to_dict()
    if (
        readiness["protocol_sha256"] != frozen_request["protocol_sha256"]
        or readiness["author_selection_sha256"]
        != frozen_request["author_selection_sha256"]
        or _selected_decisions(readiness) != frozen_request["selected_decisions"]
        or readiness["protocol_sha256"]
        != frozen_admission["protocol_sha256"]
        or readiness["author_selection_sha256"]
        != frozen_admission["author_selection_sha256"]
        or _selected_decisions(readiness)
        != frozen_admission["selected_decisions"]
    ):
        raise GrailQASemanticPaperRunError("protocol or author selection drifted")
    pilot_path = repo_root / "datasets/grailqa_pilot_v1/pilot_ids.json"
    pilot = _load_json(pilot_path, name="GrailQA pilot selection")
    expected_ids = _exact_ids(
        pilot.get("question_ids", ()),
        pilot.get("question_ids", ()),
        name="GrailQA pilot selection",
    )
    if (
        content_hash(list(expected_ids))
        != frozen_request["population"]["question_ids_sha256"]
        or _sha256_file(pilot_path)
        != frozen_request["population"]["pilot_selection_sha256"]
    ):
        raise GrailQASemanticPaperRunError("frozen query population drifted")
    catalog = _validate_local_150_catalog(catalog_root, expected_ids)
    if (
        catalog.catalog_hash != frozen_request["catalog"]["catalog_hash"]
        or catalog.catalog_hash != frozen_admission["catalog_hash"]
        or _sha256_file(catalog_root / "manifest.json")
        != frozen_request["catalog"]["manifest_sha256"]
    ):
        raise GrailQASemanticPaperRunError("pilot150 catalog identity drifted")
    # Gold-derived reachability content is not parsed here.  Only its sealed
    # byte identity is checked before the model is called.
    if (
        _sha256_file(reachability_summary_path)
        != frozen_request["reachability"]["summary_sha256"]
        or _sha256_file(reachability_rows_path)
        != frozen_request["reachability"]["rows_sha256"]
    ):
        raise GrailQASemanticPaperRunError("reachability artifact identity drifted")
    summary = _load_json(
        reachability_summary_path, name="reachability summary"
    )
    if (
        summary.get("audit_hash")
        != frozen_admission["reachability_audit_hash"]
    ):
        raise GrailQASemanticPaperRunError(
            "admission-bound reachability identity drifted"
        )
    model = ModelBundle.load(
        repo_root / "models/qwen3_32b_vllm_cwru_m13e2"
    )
    if model.bundle_hash != frozen_request["inference"]["model_bundle_hash"]:
        raise GrailQASemanticPaperRunError("model bundle identity drifted")
    return (
        frozen_request,
        frozen_admission,
        frozen_authority,
        expected_ids,
        catalog,
        model,
    )


def _state_provider_account(
    state: Mapping[str, Any], failure: str | None
) -> dict[str, Any]:
    response = state.get("response_record")
    response_map = dict(response) if isinstance(response, Mapping) else {}
    usage = response_map.get("usage")
    usage_map = dict(usage) if isinstance(usage, Mapping) else {}
    request_records = state.get("request_records", ())
    external_calls = len(request_records) if isinstance(request_records, Sequence) else 0
    repairs = int(state.get("repair_calls", 0))
    if repairs > 1 or external_calls > 2 or repairs > external_calls:
        raise GrailQASemanticPaperRunError("provider call bound exceeded")
    completed = bool(state.get("api_call_completed"))
    if failure in {"provider_failure", "malformed_output"}:
        completed = False
    return {
        "completed": completed,
        "external_calls": external_calls,
        "repair_calls": repairs,
        "input_tokens": int(usage_map.get("input_tokens") or 0),
        "output_tokens": int(usage_map.get("output_tokens") or 0),
        "latency_ms": float(state.get("llm_latency_seconds", 0.0)) * 1000.0,
    }


def _operational_failure(state: Mapping[str, Any]) -> str | None:
    old = state.get("failure")
    old_category = (
        str(old.get("category")) if isinstance(old, Mapping) and old.get("category") else None
    )
    if old_category == "retrieval_miss":
        return "retrieval_miss"
    if not bool(state.get("api_call_completed")):
        response = state.get("response_record")
        category = (
            str(response.get("failure_category"))
            if isinstance(response, Mapping) and response.get("failure_category")
            else ""
        )
        return (
            "malformed_output"
            if category in {"structured_output_error", "repair_failed"}
            else "provider_failure"
        )
    if old_category == "malformed_output":
        return "malformed_output"
    if old_category in {
        "type_check_failure",
        "entity_grounding_failure",
        "relation_grounding_failure",
        "semantic_bound_rejection",
        "ranking_failure",
    }:
        return old_category
    candidates = state.get("candidates", ())
    if not candidates:
        return "generation_miss"
    return None


def _outcome_rows_after_inference(
    *,
    states: Sequence[Mapping[str, Any]],
    expected_ids: Sequence[str],
    references: Sequence[Mapping[str, Any]],
    workloads: Sequence[Mapping[str, Any]],
    reachability_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    reference_by_id = {str(item["question_id"]): item for item in references}
    workload_by_id = {str(item["question_id"]): item for item in workloads}
    reachability_by_id = {
        str(item["question_id"]): item for item in reachability_rows
    }
    state_by_id = {
        str(dict(item["question"])["question_id"]): item for item in states
    }
    for name, values in (
        ("inference states", state_by_id),
        ("references", reference_by_id),
        ("workloads", workload_by_id),
        ("reachability rows", reachability_by_id),
    ):
        _exact_ids(tuple(values), expected_ids, name=name)
    outcomes: list[dict[str, Any]] = []
    for question_id in expected_ids:
        state = state_by_id[question_id]
        question = dict(state["question"])
        reference = dict(reference_by_id[question_id])["pattern_query"]
        candidates: list[dict[str, Any]] = []
        for position, candidate_value in enumerate(state.get("candidates", ()), start=1):
            candidate = dict(candidate_value)
            validation = candidate.get("validation")
            validation_ok = bool(
                isinstance(validation, Mapping) and validation.get("ok")
            )
            grounded = bool(candidate.get("grounded"))
            admissible = bool(candidate.get("semantic_admissible"))
            deviation = candidate.get("semantic_deviation") if admissible else None
            pattern = dict(candidate["pattern_query"])
            match = component_match_report(pattern, reference)
            candidates.append(
                {
                    "candidate_id": str(candidate["candidate_id"]),
                    "candidate_index": position,
                    "confidence": float(candidate.get("confidence") or 0.0),
                    "validation_ok": validation_ok,
                    "grounded": grounded,
                    "hard_constraints_preserved": validation_ok and grounded,
                    "semantic_admissible": admissible,
                    "semantic_deviation": deviation,
                    "equivalence_key": content_hash(
                        canonical_interpretation(pattern)
                    ),
                    "reference_supported": bool(
                        match["matches"]["full_normalized_interpretation"]
                    ),
                }
            )
        failure = _operational_failure(state)
        if failure is None and candidates and not any(
            item["reference_supported"] for item in candidates
        ):
            failure = "equivalence_failure"
        reachability = reachability_by_id[question_id]
        deployed = reachability.get("deployed_prompt")
        joint = deployed.get("joint") if isinstance(deployed, Mapping) else None
        if not isinstance(joint, Mapping) or not isinstance(
            joint.get("reachable"), bool
        ):
            raise GrailQASemanticPaperRunError(
                f"{question_id} has no boolean joint prompt reachability"
            )
        workload = workload_by_id[question_id]
        outcome = {
            "schema_version": QUERY_OUTCOME_SCHEMA_VERSION,
            "question_id": question_id,
            "split": str(question["split"]),
            "q_bucket": int(workload["Q"]),
            "jointly_prompt_reachable": bool(joint["reachable"]),
            "provider": _state_provider_account(state, failure),
            "failure_category": failure,
            "candidates": candidates,
        }
        outcomes.append(outcome)
    return outcomes


def execute_grailqa_semantic_paper_run(
    *,
    output_root: str | Path,
    request: Mapping[str, Any],
    admission: Mapping[str, Any],
    authority: Mapping[str, Any],
    question_rows: Sequence[Mapping[str, Any]],
    expected_ids: Sequence[str],
    catalog: GrailQAInferenceCatalogV2,
    provider: SemanticPilotProvider,
    references_loader: Callable[[], Sequence[Mapping[str, Any]]],
    workloads_loader: Callable[[], Sequence[Mapping[str, Any]]],
    reachability_loader: Callable[[], Sequence[Mapping[str, Any]]],
    execution_environment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute the state machine with injected gold loaders for audit tests."""

    frozen_request = validate_grailqa_semantic_execution_request(request)
    frozen_admission = validate_grailqa_semantic_preexecution_admission(
        admission
    )
    frozen_authority = validate_grailqa_semantic_execution_authority(
        execution_request=frozen_request,
        preexecution_admission=frozen_admission,
        authority=authority,
    )
    ids = _exact_ids(expected_ids, expected_ids, name="expected IDs")
    question_by_id = {str(item["question_id"]): dict(item) for item in question_rows}
    _exact_ids(tuple(question_by_id), ids, name="inference questions")
    questions = [question_by_id[question_id] for question_id in ids]
    strict_inference_leakage_audit(questions)
    output = Path(output_root)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"semantic run output exists: {output}")
    output.mkdir(parents=True, exist_ok=False)
    _write_json_exclusive(
        output / "control/preexecution_admission.json",
        frozen_admission,
    )
    _write_json_exclusive(output / "control/execution_request.json", frozen_request)
    _write_json_exclusive(
        output / "control/execution_authority.json", frozen_authority
    )
    state_root = output / "inference/query-state"
    state_root.mkdir(parents=True)
    started = datetime.now(timezone.utc).isoformat()
    semantic = DirectionalOntologyDeviation(
        catalog.ontology,
        SemanticDeviationConfig(
            max_relaxation_hops=catalog.ontology.max_relaxation_hops,
            epsilon_values=(0.0, 0.1, 0.25, 0.5, 0.75, 1.0),
        ),
    )
    states: list[dict[str, Any]] = []
    for question in questions:
        state = _infer_one(
            question=question,
            catalog=catalog,  # type: ignore[arg-type] - v2 implements this protocol.
            provider=provider,
            semantic=semantic,
            retrieval_k=20,
            candidate_cap=3,
            prompt_candidates_per_slot=4,
            response_parser=parse_normalized_planner_response,
        )
        strict_inference_leakage_audit(state)
        question_id = str(question["question_id"])
        _write_json_exclusive(state_root / f"{question_id}.json", state)
        states.append(state)
    state_files = [state_root / f"{question_id}.json" for question_id in ids]
    external_calls = sum(
        len(state.get("request_records", ())) for state in states
    )
    repair_calls = sum(int(state.get("repair_calls", 0)) for state in states)
    if external_calls > 300 or repair_calls > 150:
        raise GrailQASemanticPaperRunError("aggregate provider call bound exceeded")
    seal_body: dict[str, Any] = {
        "schema_version": INFERENCE_SEAL_SCHEMA_VERSION,
        "run_id": frozen_request["run_id"],
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "execution_request_sha256": frozen_request["execution_request_sha256"],
        "preexecution_admission_sha256": frozen_admission[
            "preexecution_admission_sha256"
        ],
        "execution_authority_sha256": frozen_authority[
            "execution_authority_sha256"
        ],
        "question_count": len(states),
        "question_ids_sha256": content_hash(list(ids)),
        "query_state_files": [
            {
                "question_id": question_id,
                "path": f"inference/query-state/{question_id}.json",
                "sha256": _sha256_file(path),
            }
            for question_id, path in zip(ids, state_files, strict=True)
        ],
        "provider_external_calls": external_calls,
        "provider_repair_calls": repair_calls,
        "automatic_retries": 0,
        "native_query_text_emitted": False,
        "backend_calls": 0,
        "gold_artifacts_opened": False,
        "all_query_states_present": len(states) == 150,
    }
    seal = {**seal_body, "inference_seal_sha256": content_hash(seal_body)}
    seal_path = output / "inference/inference_seal.json"
    _write_json_exclusive(seal_path, seal)

    # These are the only gold-derived loaders in the run.  Their invocation is
    # structurally after the durable inference seal above.
    gold_opened_at = datetime.now(timezone.utc).isoformat()
    references = list(references_loader())
    workloads = list(workloads_loader())
    reachability = list(reachability_loader())
    outcomes = _outcome_rows_after_inference(
        states=states,
        expected_ids=ids,
        references=references,
        workloads=workloads,
        reachability_rows=reachability,
    )
    outcomes_path = output / "evaluation/query_outcomes.jsonl"
    _write_jsonl_exclusive(outcomes_path, outcomes)
    source_body: dict[str, Any] = {
        "run_id": frozen_request["run_id"],
        "execution_request_sha256": frozen_request["execution_request_sha256"],
        "preexecution_admission_sha256": frozen_admission[
            "preexecution_admission_sha256"
        ],
        "execution_authority_sha256": frozen_authority[
            "execution_authority_sha256"
        ],
        "inference_seal_sha256": seal["inference_seal_sha256"],
        "inference_sealed_at": seal["sealed_at"],
        "gold_opened_at": gold_opened_at,
        "outcome_ledger_sha256": _sha256_file(outcomes_path),
    }
    source_run_sha256 = content_hash(source_body)
    manifest_body: dict[str, Any] = {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "run_id": frozen_request["run_id"],
        "started_at": started,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "status": "success",
        "runner_commit": frozen_request["runner_commit"],
        "protocol_sha256": frozen_request["protocol_sha256"],
        "author_selection_sha256": frozen_request[
            "author_selection_sha256"
        ],
        "execution_request_sha256": frozen_request[
            "execution_request_sha256"
        ],
        "preexecution_admission_sha256": frozen_admission[
            "preexecution_admission_sha256"
        ],
        "execution_authority_sha256": frozen_authority[
            "execution_authority_sha256"
        ],
        "catalog_hash": frozen_request["catalog"]["catalog_hash"],
        "reachability_audit_hash": frozen_request["reachability"]["audit_hash"],
        "inference_seal_sha256": seal["inference_seal_sha256"],
        "inference_sealed_at": seal["sealed_at"],
        "gold_opened_at": gold_opened_at,
        "outcome_ledger_sha256": _sha256_file(outcomes_path),
        "source_run_sha256": source_run_sha256,
        "question_count": len(outcomes),
        "provider_external_calls": external_calls,
        "provider_repair_calls": repair_calls,
        "automatic_retries": 0,
        "backend_calls": 0,
        "native_query_text_emitted": False,
        "selection_uses_gold": False,
        "gold_opened_after_all_inference": True,
        "inference_seal_written_before_gold_open": True,
        "failures_retained": True,
        "execution_environment": (
            dict(execution_environment) if execution_environment is not None else None
        ),
        "paper_result": False,
    }
    manifest = {
        **manifest_body,
        "run_manifest_sha256": content_hash(manifest_body),
    }
    _write_json_exclusive(output / "run_manifest.json", manifest)
    _write_json_exclusive(
        output / "run_status.json",
        {
            "schema_version": RUN_STATUS_SCHEMA_VERSION,
            "status": "success",
            "run_id": frozen_request["run_id"],
            "source_run_sha256": source_run_sha256,
            "paper_result": False,
        },
    )
    return manifest


def run_grailqa_semantic_paper(
    *,
    request_path: str | Path,
    admission_path: str | Path,
    authority_path: str | Path,
    protocol_path: str | Path,
    author_selection_path: str | Path,
    repo_root: str | Path,
    catalog_root: str | Path,
    reachability_summary_path: str | Path,
    reachability_rows_path: str | Path,
    output_root: str | Path,
    provider_override: SemanticPilotProvider | None = None,
) -> dict[str, Any]:
    repo = _regular_directory(repo_root, name="repo_root")
    protocol = _regular_file(protocol_path, name="semantic protocol")
    selection = _regular_file(author_selection_path, name="author selection")
    catalog_path = _regular_directory(catalog_root, name="pilot150 catalog")
    summary_path = _regular_file(
        reachability_summary_path, name="reachability summary"
    )
    rows_path = _regular_file(reachability_rows_path, name="reachability rows")
    request = _load_json(request_path, name="execution request")
    admission = _load_json(admission_path, name="preexecution admission")
    authority = _load_json(authority_path, name="execution authority")
    request, admission, authority, expected_ids, catalog, model = (
        _validate_run_inputs_without_opening_gold(
            request=request,
            admission=admission,
            authority=authority,
            repo_root=repo,
            protocol_path=protocol,
            author_selection_path=selection,
            catalog_root=catalog_path,
            reachability_summary_path=summary_path,
            reachability_rows_path=rows_path,
        )
    )
    output = Path(output_root).resolve()
    if output.name != request["run_id"]:
        raise GrailQASemanticPaperRunError(
            "output directory name must equal the authority-bound run_id"
        )
    pilot_root = repo / "datasets/grailqa_pilot_v1"
    questions = _load_jsonl(
        pilot_root / "inference_questions.jsonl",
        name="inference questions",
    )
    provider = provider_override or LiveSemanticPilotProvider(
        model, response_parser=parse_normalized_planner_response
    )
    environment = None
    environment_path = os.environ.get("XGAP_RUN_ENVIRONMENT_FILE")
    if environment_path:
        environment = load_run_environment(environment_path)

    def load_references() -> Sequence[Mapping[str, Any]]:
        return _load_jsonl(
            pilot_root / "reference_interpretations.jsonl",
            name="reference interpretations",
        )

    def load_workloads() -> Sequence[Mapping[str, Any]]:
        return _load_jsonl(
            pilot_root / "workload_stats.jsonl", name="workload statistics"
        )

    def load_reachability() -> Sequence[Mapping[str, Any]]:
        _, rows = _validate_reachability_artifacts(
            summary_path=summary_path,
            rows_path=rows_path,
            catalog_hash=catalog.catalog_hash,
            expected_ids=expected_ids,
            parse_rows=True,
        )
        assert rows is not None
        return rows

    return execute_grailqa_semantic_paper_run(
        output_root=output,
        request=request,
        admission=admission,
        authority=authority,
        question_rows=questions,
        expected_ids=expected_ids,
        catalog=catalog,
        provider=provider,
        references_loader=load_references,
        workloads_loader=load_workloads,
        reachability_loader=load_reachability,
        execution_environment=environment,
    )


def check_grailqa_semantic_paper_run(
    **kwargs: Any,
) -> dict[str, Any]:
    """Perform the pre-model gate without parsing gold-derived rows."""

    request = _load_json(kwargs["request_path"], name="execution request")
    admission = _load_json(
        kwargs["admission_path"], name="preexecution admission"
    )
    authority = _load_json(kwargs["authority_path"], name="execution authority")
    validated = _validate_run_inputs_without_opening_gold(
        request=request,
        admission=admission,
        authority=authority,
        repo_root=_regular_directory(kwargs["repo_root"], name="repo_root"),
        protocol_path=_regular_file(kwargs["protocol_path"], name="semantic protocol"),
        author_selection_path=_regular_file(
            kwargs["author_selection_path"], name="author selection"
        ),
        catalog_root=_regular_directory(
            kwargs["catalog_root"], name="pilot150 catalog"
        ),
        reachability_summary_path=_regular_file(
            kwargs["reachability_summary_path"], name="reachability summary"
        ),
        reachability_rows_path=_regular_file(
            kwargs["reachability_rows_path"], name="reachability rows"
        ),
    )
    request = validated[0]
    return {
        "schema_version": "m13e4-grailqa-semantic-paper-run-readiness-v1",
        "ready": True,
        "run_id": request["run_id"],
        "runner_commit": request["runner_commit"],
        "question_count": 150,
        "gold_content_parsed": False,
        "llm_calls_made": 0,
        "backend_calls_made": 0,
        "paper_result": False,
    }


def _common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL_PATH))
    parser.add_argument("--author-selection", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--catalog-root", required=True)
    parser.add_argument("--reachability-summary", required=True)
    parser.add_argument("--reachability-rows", required=True)
    parser.add_argument("--admission", required=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    request_parser = commands.add_parser("request")
    _common_paths(request_parser)
    request_parser.add_argument("--run-id", required=True)
    request_parser.add_argument("--output", required=True)
    authority_parser = commands.add_parser("authorize")
    authority_parser.add_argument("--request", required=True)
    authority_parser.add_argument("--admission", required=True)
    authority_parser.add_argument("--authority-source-id", required=True)
    authority_parser.add_argument(
        "--decision",
        required=True,
        choices=("authorize_exact_150_query_semantic_execution",),
    )
    authority_parser.add_argument("--output", required=True)
    check_parser = commands.add_parser("check")
    _common_paths(check_parser)
    check_parser.add_argument("--request", required=True)
    check_parser.add_argument("--authority", required=True)
    run_parser = commands.add_parser("run")
    _common_paths(run_parser)
    run_parser.add_argument("--request", required=True)
    run_parser.add_argument("--authority", required=True)
    run_parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "request":
            value = build_grailqa_semantic_execution_request(
                protocol_path=args.protocol,
                author_selection_path=args.author_selection,
                repo_root=args.repo_root,
                catalog_root=args.catalog_root,
                reachability_summary_path=args.reachability_summary,
                reachability_rows_path=args.reachability_rows,
                preexecution_admission_path=args.admission,
                run_id=args.run_id,
            )
            _write_json_exclusive(Path(args.output), value)
        elif args.command == "authorize":
            value = build_grailqa_semantic_execution_authority(
                execution_request=_load_json(args.request, name="execution request"),
                preexecution_admission=_load_json(
                    args.admission, name="preexecution admission"
                ),
                authority_source_id=args.authority_source_id,
                decision=args.decision,
            )
            _write_json_exclusive(Path(args.output), value)
        elif args.command == "check":
            value = check_grailqa_semantic_paper_run(
                request_path=args.request,
                admission_path=args.admission,
                authority_path=args.authority,
                protocol_path=args.protocol,
                author_selection_path=args.author_selection,
                repo_root=args.repo_root,
                catalog_root=args.catalog_root,
                reachability_summary_path=args.reachability_summary,
                reachability_rows_path=args.reachability_rows,
            )
        else:
            value = run_grailqa_semantic_paper(
                request_path=args.request,
                admission_path=args.admission,
                authority_path=args.authority,
                protocol_path=args.protocol,
                author_selection_path=args.author_selection,
                repo_root=args.repo_root,
                catalog_root=args.catalog_root,
                reachability_summary_path=args.reachability_summary,
                reachability_rows_path=args.reachability_rows,
                output_root=args.output,
            )
    except (FileExistsError, OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps({"status": "success", **value}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
