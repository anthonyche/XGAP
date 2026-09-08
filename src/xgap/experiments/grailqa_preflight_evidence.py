"""Independent read-only evidence audit for one CWRU GrailQA preflight run."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.cwru_vllm import (
    CWRUVLLMContract,
    RUN_ENVIRONMENT_SCHEMA_VERSION,
)
from xgap.experiments.grailqa_preflight import (
    GrailQAPreflightSpec,
    QUERY_LOCAL_ARTIFACT_PROFILE,
    QUERY_LOCAL_REACHABILITY_SCHEMA_VERSION,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.interpretation_contract import (
    STAGE_AWARE_FAILURE_TAXONOMY,
    semantic_deviation_distribution,
)
from xgap.experiments.relation_endpoints import RELATION_ENDPOINT_CONTRACT_VERSION


AUDIT_SCHEMA_VERSION = "m13e3b5-grailqa-preflight-evidence-audit-v1"
RESULT_RELATIVE_ROOT = Path("results/grailqa-semantic-preflight-v2")
RESULT_FILES = (
    "readiness.json",
    "run_manifest.json",
    "retrieval.jsonl",
    "llm_requests.jsonl",
    "llm_responses.jsonl",
    "validated_candidates.jsonl",
    "component_match.jsonl",
    "semantic_scores.jsonl",
    "failures.jsonl",
    "metrics.json",
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def audit_grailqa_preflight_run(
    *,
    run_root: str | Path,
    repo_root: str | Path,
    expected_commit: str,
    spec_path: str | Path = (
        "experiments/specs/grailqa_semantic_preflight_v2_cwru_qwen3_32b.json"
    ),
) -> dict[str, Any]:
    """Reconstruct a completed preflight without modifying its run tree."""

    root = Path(run_root).resolve()
    repo = Path(repo_root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"GrailQA preflight run root does not exist: {root}")
    if not _COMMIT.fullmatch(expected_commit):
        raise ValueError("expected_commit must be an exact 40-hex commit")
    before = _tree_snapshot(root)
    checks: list[dict[str, Any]] = []

    def check(check_id: str, passed: bool, detail: Any = None) -> None:
        checks.append(
            {"check_id": check_id, "passed": bool(passed), "detail": detail}
        )

    def load_json(relative: str | Path) -> dict[str, Any]:
        path = root / relative
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, Mapping):
                raise ValueError("root is not an object")
        except Exception as error:  # noqa: BLE001 - the audit records all defects.
            check(f"artifact.{Path(relative).as_posix()}", False, str(error))
            return {}
        check(f"artifact.{Path(relative).as_posix()}", True, _sha256_file(path))
        return dict(value)

    def load_jsonl(relative: str | Path) -> list[dict[str, Any]]:
        path = root / relative
        rows: list[dict[str, Any]] = []
        try:
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if not line:
                    continue
                value = json.loads(line)
                if not isinstance(value, Mapping):
                    raise ValueError(f"line {line_number} is not an object")
                rows.append(dict(value))
        except Exception as error:  # noqa: BLE001
            check(f"artifact.{Path(relative).as_posix()}", False, str(error))
            return []
        check(
            f"artifact.{Path(relative).as_posix()}",
            True,
            {"rows": len(rows), "sha256": _sha256_file(path)},
        )
        return rows

    status = load_json("run_status.json")
    inventory = load_json("artifact_inventory.json")
    environment = load_json("cwru_environment.json")
    smoke = load_json("vllm_structured_smoke.json")
    outer_readiness = load_json("preflight_readiness.json")
    result = RESULT_RELATIVE_ROOT
    readiness = load_json(result / "readiness.json")
    manifest = load_json(result / "run_manifest.json")
    metrics = load_json(result / "metrics.json")
    retrieval = load_jsonl(result / "retrieval.jsonl")
    requests = load_jsonl(result / "llm_requests.jsonl")
    responses = load_jsonl(result / "llm_responses.jsonl")
    candidates = load_jsonl(result / "validated_candidates.jsonl")
    components = load_jsonl(result / "component_match.jsonl")
    semantic = load_jsonl(result / "semantic_scores.jsonl")
    failures = load_jsonl(result / "failures.jsonl")

    spec_file = Path(spec_path)
    if not spec_file.is_absolute():
        spec_file = repo / spec_file
    spec = GrailQAPreflightSpec.load(spec_file)
    expected_ids = tuple(spec.question_ids)
    expected_id_set = set(expected_ids)

    check("outer.schema", status.get("schema_version") == "m13e2-cwru-run-status-v1")
    check("outer.success", status.get("status") == "success")
    check("outer.exit_code", status.get("exit_code") == 0)
    check(
        "outer.artifact_count",
        status.get("artifact_count") == len(inventory.get("files", ())),
    )
    _audit_inventory(root, inventory, check)

    check("smoke.schema_valid", smoke.get("schema_valid") is True)
    check("smoke.secret_free", smoke.get("secrets_persisted") is False)
    check(
        "environment.schema",
        environment.get("schema_version") == RUN_ENVIRONMENT_SCHEMA_VERSION,
    )
    environment_git = _object(environment.get("git"))
    check("environment.git_commit", environment_git.get("commit") == expected_commit)
    check("environment.git_clean", environment_git.get("clean") is True)
    environment_gpu = _object(environment.get("gpu"))
    check("environment.gpu_available", environment_gpu.get("status") == "available")
    check("environment.h100", "H100" in str(environment_gpu.get("model", "")))
    environment_slurm = _object(environment.get("slurm"))
    check("environment.slurm_job", bool(str(environment_slurm.get("job_id") or "")))
    environment_experiment = _object(environment.get("experiment"))
    check(
        "environment.spec_sha256",
        environment_experiment.get("spec_sha256") == _sha256_file(spec_file),
    )
    check(
        "environment.spec_freeze_hash",
        environment_experiment.get("spec_freeze_hash") == spec.data["freeze_hash"],
    )
    check(
        "environment.model_bundle_hash",
        environment_experiment.get("model_bundle_hash")
        == spec.data["model_bundle_hash"],
    )
    contract = CWRUVLLMContract.load(repo / str(spec.data["deployment_contract"]))
    environment_contract = _object(environment.get("environment_contract"))
    check(
        "environment.contract_hash",
        environment_contract.get("hash") == contract.contract_hash,
    )
    check("environment.secret_free", environment.get("secrets_persisted") is False)
    check("environment.no_credential_values", not _contains_secret_key(environment))
    model_bundle = ModelBundle.load(repo / str(spec.data["model_bundle_root"]))
    check("bundle.hash", model_bundle.bundle_hash == spec.data["model_bundle_hash"])
    check(
        "bundle.prompt_hash",
        model_bundle.prompt.prompt_hash == manifest.get("prompt_hash"),
    )
    check("bundle.repair_bound", model_bundle.config.max_repair_calls == 1)
    candidate_schema = _object(
        _object(_object(model_bundle.structured_schema).get("properties")).get(
            "candidates"
        )
    )
    check(
        "bundle.candidate_cardinality",
        candidate_schema.get("minItems") == 1
        and candidate_schema.get("maxItems") == spec.data["candidate_cap"] == 3,
    )

    check("readiness.identical", readiness == outer_readiness)
    check("readiness.ready", readiness.get("ready") is True)
    check(
        "readiness.profile",
        readiness.get("artifact_profile") == QUERY_LOCAL_ARTIFACT_PROFILE,
    )
    profile_contract = _object(readiness.get("artifact_profile_contract"))
    check(
        "readiness.question_count",
        profile_contract.get("question_count") == len(expected_ids),
    )
    check(
        "readiness.prompt_bound",
        readiness.get("prompt_candidates_per_slot") == 4,
    )
    check(
        "readiness.endpoint_contract",
        readiness.get("relation_endpoint_contract_version")
        == RELATION_ENDPOINT_CONTRACT_VERSION,
    )
    check(
        "readiness.checks",
        bool(readiness.get("checks"))
        and all(
            _object(item).get("status") == "pass"
            for item in readiness.get("checks", ())
        ),
    )
    reachability = _audit_reachability(readiness, expected_id_set, check)

    check(
        "manifest.schema",
        manifest.get("schema_version") == "m13e3b5-preflight-run-manifest-v3",
    )
    check(
        "manifest.spec_sha256",
        manifest.get("spec_sha256") == _sha256_file(spec_file),
    )
    check(
        "manifest.spec_freeze_hash",
        manifest.get("spec_freeze_hash") == spec.data["freeze_hash"],
    )
    check(
        "manifest.catalog_hash",
        manifest.get("catalog_hash")
        == _readiness_check_detail(readiness, "catalog_v2"),
    )
    check(
        "manifest.model_bundle_hash",
        manifest.get("model_bundle_hash") == spec.data["model_bundle_hash"],
    )
    check("manifest.provider", manifest.get("provider") == spec.data["provider"])
    check("manifest.model", manifest.get("model") == spec.data["model"])
    check("manifest.question_count", manifest.get("question_count") == len(expected_ids))
    check("manifest.no_backend_execution", manifest.get("backend_execution") is False)
    check("manifest.secret_free", manifest.get("secrets_persisted") is False)
    check(
        "manifest.environment_exact",
        manifest.get("execution_environment") == environment,
    )
    inference_artifacts = _object(manifest.get("inference_artifacts"))
    check(
        "manifest.artifact_profile",
        inference_artifacts.get("profile") == QUERY_LOCAL_ARTIFACT_PROFILE,
    )
    check(
        "manifest.reachability_hash",
        inference_artifacts.get("reachability_audit_hash")
        == readiness.get("reachability_audit_hash"),
    )
    check(
        "manifest.prompt_bound",
        inference_artifacts.get("prompt_candidates_per_slot") == 4,
    )
    check(
        "manifest.endpoint_contract",
        inference_artifacts.get("relation_endpoint_contract_version")
        == RELATION_ENDPOINT_CONTRACT_VERSION,
    )
    check(
        "manifest.prompt_hash",
        manifest.get("prompt_hash") == environment_experiment.get("prompt_hash"),
    )

    retrieval_ids = tuple(str(row.get("question_id", "")) for row in retrieval)
    check(
        "queries.retrieval_exact",
        len(retrieval_ids) == len(expected_ids)
        and set(retrieval_ids) == expected_id_set
        and len(set(retrieval_ids)) == len(retrieval_ids),
    )
    check("queries.execution_order", retrieval_ids == expected_ids)
    response_ids = tuple(str(row.get("task_id", "")) for row in responses)
    check(
        "provider.response_ids",
        all(item in expected_id_set for item in response_ids)
        and len(response_ids) == len(set(response_ids)),
    )
    request_ids = tuple(str(row.get("task_id", "")) for row in requests)
    check("provider.request_ids", all(item in expected_id_set for item in request_ids))
    _audit_provider_protocol(requests, responses, spec, check)

    candidate_pairs = tuple(
        (str(row.get("question_id", "")), str(row.get("candidate_id", "")))
        for row in candidates
    )
    check(
        "candidates.ids",
        all(qid in expected_id_set and cid for qid, cid in candidate_pairs)
        and len(candidate_pairs) == len(set(candidate_pairs)),
    )
    candidate_counts = Counter(qid for qid, _ in candidate_pairs)
    check(
        "candidates.cap",
        all(
            1 <= count <= int(spec.data["candidate_cap"])
            for count in candidate_counts.values()
        ),
    )
    component_pairs = tuple(
        (str(row.get("question_id", "")), str(row.get("candidate_id", "")))
        for row in components
    )
    check(
        "components.exact_candidate_set",
        Counter(component_pairs) == Counter(candidate_pairs),
    )
    semantic_pairs = tuple(
        (str(row.get("question_id", "")), str(row.get("candidate_id", "")))
        for row in semantic
    )
    check(
        "semantic.candidate_subset",
        set(semantic_pairs).issubset(set(candidate_pairs))
        and len(semantic_pairs) == len(set(semantic_pairs)),
    )
    failure_ids = tuple(str(row.get("question_id", "")) for row in failures)
    check(
        "failures.ids",
        all(item in expected_id_set for item in failure_ids)
        and len(failure_ids) == len(set(failure_ids)),
    )
    check(
        "failures.taxonomy",
        all(
            row.get("category") in STAGE_AWARE_FAILURE_TAXONOMY
            for row in failures
        ),
    )

    reconstructed = _recompute_metrics(
        expected_ids=expected_ids,
        responses=responses,
        candidates=candidates,
        components=components,
        failures=failures,
        reachability=reachability,
        epsilon_values=tuple(float(value) for value in spec.data["epsilon_values"]),
    )
    for field, expected_value in reconstructed.items():
        check(
            f"metrics.{field}",
            metrics.get(field) == expected_value,
            {"expected": expected_value, "observed": metrics.get(field)},
        )
    check("metrics.schema", metrics.get("schema_version") == "m13e1-preflight-metrics-v2")
    check(
        "metrics.catalog_availability",
        metrics.get("catalog_availability") == readiness.get("catalog_coverage"),
    )
    check(
        "metrics.prompt_reachability",
        metrics.get("prompt_reachability") == readiness.get("prompt_reachability"),
    )
    matched_ids = {
        str(row.get("question_id"))
        for row in candidates
        if row.get("normalized_reference_match") is True
    }
    check(
        "outcomes.complete",
        matched_ids.isdisjoint(set(failure_ids))
        and matched_ids | set(failure_ids) == expected_id_set,
    )

    after = _tree_snapshot(root)
    check("run_tree.not_mutated", before == after)
    failed = [item["check_id"] for item in checks if not item["passed"]]
    provider_successes = sum(
        row.get("validation_status") == "schema_valid" for row in responses
    )
    diagnostic = {
        "provider_success_count": provider_successes,
        "provider_failure_count": len(expected_ids) - provider_successes,
        "candidate_bearing_query_count": len(candidate_counts),
        "matched_query_count": len(matched_ids),
        "candidate_recall_is_unconfounded_by_provider_failure": (
            provider_successes == len(expected_ids)
        ),
    }
    audit = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_root": str(root),
        "expected_commit": expected_commit,
        "success": not failed,
        "check_count": len(checks),
        "failed_check_ids": failed,
        "run_tree_mutated": before != after,
        "diagnostic": diagnostic,
        "claim_boundary": {
            "development_preflight_only": True,
            "paper_result": False,
            "full_150_run_authorized": False,
            "backend_execution": False,
            "jointly_reachable_subset_reported_separately": True,
        },
        "checks": checks,
    }
    audit["audit_sha256"] = content_hash(audit)
    return audit


def _audit_inventory(root: Path, inventory: Mapping[str, Any], check: Any) -> None:
    rows = inventory.get("files")
    if not isinstance(rows, list):
        check("inventory.schema", False, "files must be a list")
        return
    check("inventory.schema", inventory.get("schema_version") == "m13e2-artifact-inventory-v1")
    indexed = {
        str(row.get("path")): row
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("path"), str)
    }
    check("inventory.unique_paths", len(indexed) == len(rows))
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path.name not in {"artifact_inventory.json", "run_status.json"}
    }
    check(
        "inventory.path_set",
        set(indexed) == actual,
        {
            "missing": sorted(actual - set(indexed)),
            "unexpected": sorted(set(indexed) - actual),
        },
    )
    mismatches: list[str] = []
    # cleanup prints one final line after inventory publication, so job.log is
    # intentionally excluded from content identity while still requiring its path.
    for relative, row in indexed.items():
        if relative == "job.log":
            continue
        path = root / relative
        if (
            not path.is_file()
            or path.stat().st_size != row.get("size_bytes")
            or _sha256_file(path) != row.get("sha256")
        ):
            mismatches.append(relative)
    check("inventory.static_content", not mismatches, mismatches)
    required = {(RESULT_RELATIVE_ROOT / name).as_posix() for name in RESULT_FILES}
    check("inventory.result_files", required.issubset(indexed), sorted(required - set(indexed)))


def _audit_reachability(
    readiness: Mapping[str, Any], expected_ids: set[str], check: Any
) -> dict[str, dict[str, Any]]:
    summary_path = Path(str(readiness.get("reachability_summary_path", "")))
    rows_path = Path(str(readiness.get("reachability_rows_path", "")))
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        rows = _read_jsonl_absolute(rows_path)
    except Exception as error:  # noqa: BLE001
        check("reachability.available", False, str(error))
        return {}
    check("reachability.available", True)
    check(
        "reachability.schema",
        summary.get("schema_version") == QUERY_LOCAL_REACHABILITY_SCHEMA_VERSION,
    )
    expected_audit_hash = summary.get("audit_hash")
    payload = {key: value for key, value in summary.items() if key != "audit_hash"}
    check(
        "reachability.audit_hash",
        content_hash(payload)
        == expected_audit_hash
        == readiness.get("reachability_audit_hash"),
    )
    check(
        "reachability.catalog_hash",
        summary.get("catalog_hash")
        == _readiness_check_detail(readiness, "catalog_v2"),
    )
    hashes = _object(summary.get("artifact_hashes"))
    check(
        "reachability.rows_hash",
        hashes.get("reachability.jsonl") == _sha256_file(rows_path),
    )
    by_id = {str(row.get("question_id", "")): row for row in rows}
    check(
        "reachability.question_set",
        len(by_id) == len(rows) and set(by_id) == expected_ids,
    )
    return by_id


def _audit_provider_protocol(
    requests: Sequence[Mapping[str, Any]],
    responses: Sequence[Mapping[str, Any]],
    spec: GrailQAPreflightSpec,
    check: Any,
) -> None:
    by_task: dict[str, list[Mapping[str, Any]]] = {}
    for row in requests:
        by_task.setdefault(str(row.get("task_id", "")), []).append(row)
    response_by_task = {str(row.get("task_id", "")): row for row in responses}
    defects: list[str] = []
    cardinality_defects: list[str] = []
    for task_id, response in response_by_task.items():
        task_requests = sorted(
            by_task.get(task_id, ()),
            key=lambda row: int(row.get("call_index", 0)),
        )
        repair_calls = int(response.get("repair_calls", -1))
        generation_calls = int(response.get("generation_calls", -1))
        expected_calls = generation_calls + repair_calls
        if len(task_requests) != expected_calls or not 0 <= repair_calls <= 1:
            defects.append(task_id)
            continue
        if [row.get("call_index") for row in task_requests] != list(
            range(1, expected_calls + 1)
        ):
            defects.append(task_id)
        if task_requests and task_requests[0].get("call_kind") != "generation":
            defects.append(task_id)
        if any(row.get("call_kind") != "repair" for row in task_requests[1:]):
            defects.append(task_id)
        if response.get("validation_status") == "schema_valid":
            structured = _object(response.get("structured_response"))
            values = structured.get("candidates")
            if not isinstance(values, list) or not 1 <= len(values) <= int(
                spec.data["candidate_cap"]
            ):
                cardinality_defects.append(task_id)
    orphan_requests = sorted(set(by_task) - set(response_by_task))
    check(
        "provider.call_ledger",
        not defects and not orphan_requests,
        {"defects": sorted(set(defects)), "orphan_requests": orphan_requests},
    )
    check(
        "provider.repair_bound",
        all(int(row.get("repair_calls", -1)) in {0, 1} for row in responses),
    )
    check("provider.response_candidate_cardinality", not cardinality_defects, cardinality_defects)
    check("provider.call_bound", len(requests) <= len(spec.question_ids) * 2, len(requests))
    check(
        "provider.secret_free",
        not _contains_secret_key(
            {"requests": list(requests), "responses": list(responses)}
        ),
    )


def _recompute_metrics(
    *,
    expected_ids: Sequence[str],
    responses: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
    components: Sequence[Mapping[str, Any]],
    failures: Sequence[Mapping[str, Any]],
    reachability: Mapping[str, Mapping[str, Any]],
    epsilon_values: Sequence[float],
) -> dict[str, Any]:
    total = len(expected_ids)
    response_by_id = {str(row.get("task_id", "")): row for row in responses}
    candidate_ids = {str(row.get("question_id", "")) for row in candidates}
    matched_ids = {
        str(row.get("question_id", ""))
        for row in candidates
        if row.get("normalized_reference_match") is True
    }
    match_fields: tuple[str, ...] = ()
    if components:
        matches = components[0].get("matches")
        if isinstance(matches, Mapping):
            match_fields = tuple(matches)
    component_accuracy = {
        field: sum(
            bool(_object(row.get("matches")).get(field)) for row in components
        )
        / len(components)
        for field in match_fields
    }
    candidates_by_id: dict[str, list[Mapping[str, Any]]] = {}
    for row in candidates:
        candidates_by_id.setdefault(str(row.get("question_id", "")), []).append(row)
    joint_ids = {
        question_id
        for question_id, row in reachability.items()
        if bool(
            _object(_object(row.get("deployed_prompt")).get("joint")).get("reachable")
        )
    }
    joint_count = len(joint_ids)
    provider_success = {
        qid
        for qid, row in response_by_id.items()
        if row.get("validation_status") == "schema_valid"
    }
    return {
        "query_count": total,
        "provider_success_rate": len(provider_success) / total if total else None,
        "structured_valid_rate": len(candidate_ids) / total if total else None,
        "candidate_recall": len(matched_ids) / total if total else None,
        "jointly_reachable_subset": {
            "schema_version": "m13e3b5-jointly-reachable-subset-v1",
            "question_count": joint_count,
            "unreachable_question_count": total - joint_count,
            "prompt_reachability_ceiling": joint_count / total if total else None,
            "provider_success_rate": (
                len(provider_success & joint_ids) / joint_count if joint_count else None
            ),
            "structured_valid_rate": (
                len(candidate_ids & joint_ids) / joint_count if joint_count else None
            ),
            "candidate_recall": (
                len(matched_ids & joint_ids) / joint_count if joint_count else None
            ),
            "matched_question_count": len(matched_ids & joint_ids),
        },
        "component_accuracy": component_accuracy,
        "full_normalized_interpretation_accuracy": component_accuracy.get(
            "full_normalized_interpretation"
        ),
        "c_sem": semantic_deviation_distribution(candidates),
        "feasible_coverage": {
            str(epsilon): (
                sum(
                    any(
                        row.get("semantic_deviation") is not None
                        and float(row["semantic_deviation"]) <= epsilon
                        for row in candidates_by_id.get(question_id, ())
                    )
                    for question_id in expected_ids
                )
                / total
                if total
                else None
            )
            for epsilon in epsilon_values
        },
        "failure_taxonomy": {
            name: Counter(row.get("category") for row in failures).get(name, 0)
            for name in STAGE_AWARE_FAILURE_TAXONOMY
        },
    }


def _contains_secret_key(value: object) -> bool:
    forbidden = {"api_key", "authorization", "password", "secret", "access_token"}
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, Mapping):
            for key, child in current.items():
                if str(key).casefold() in forbidden:
                    return True
                stack.append(child)
        elif isinstance(current, (list, tuple)):
            stack.extend(current)
    return False


def _readiness_check_detail(
    readiness: Mapping[str, Any], check_name: str
) -> Any:
    for item in readiness.get("checks", ()):
        row = _object(item)
        if row.get("name") == check_name and row.get("status") == "pass":
            return row.get("detail")
    return None


def _object(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _read_jsonl_absolute(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line:
            continue
        value = json.loads(line)
        if not isinstance(value, Mapping):
            raise ValueError(f"reachability line {line_number} is not an object")
        rows.append(dict(value))
    return rows


def _tree_snapshot(root: Path) -> dict[str, tuple[int, str]]:
    return {
        path.relative_to(root).as_posix(): (path.stat().st_size, _sha256_file(path))
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument(
        "--spec",
        default="experiments/specs/grailqa_semantic_preflight_v2_cwru_qwen3_32b.json",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    root = Path(args.run_root).resolve()
    output = Path(args.output).resolve()
    if output == root or root in output.parents:
        raise ValueError("Audit output must be outside the immutable source run tree.")
    audit = audit_grailqa_preflight_run(
        run_root=root,
        repo_root=args.repo_root,
        expected_commit=args.expected_commit,
        spec_path=args.spec,
    )
    _write_json(output, audit)
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 0 if audit["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
