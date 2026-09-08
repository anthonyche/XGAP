"""Independent read-only audit of one GrailQA 150-query semantic run.

This module intentionally does not import the producer runner.  It validates
the authority chain, all 150 sealed inference states, the post-seal outcome
ledger, provider-call accounting, and the source-run identity without making
model, catalog, ontology-service, or backend calls.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash


AUDIT_SCHEMA_VERSION = "m13e4-grailqa-semantic-paper-run-evidence-audit-v1"
EXECUTION_REQUEST_SCHEMA_VERSION = (
    "m13e4-grailqa-semantic-execution-request-v1"
)
EXECUTION_AUTHORITY_SCHEMA_VERSION = (
    "m13e4-grailqa-semantic-execution-authority-v1"
)
INFERENCE_SEAL_SCHEMA_VERSION = "m13e4-grailqa-semantic-inference-seal-v1"
RUN_MANIFEST_SCHEMA_VERSION = "m13e4-grailqa-semantic-paper-run-v1"
RUN_STATUS_SCHEMA_VERSION = "m13e4-grailqa-semantic-paper-run-status-v1"
QUERY_OUTCOME_SCHEMA_VERSION = "m13e4-grailqa-semantic-query-outcome-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_FORBIDDEN_INFERENCE_KEYS = frozenset(
    {
        "gold_answers",
        "gold_answer",
        "gold_logical_form",
        "gold_alignments",
        "gold_alignment",
        "gold_entity_annotation",
        "gold_relation_annotation",
        "evaluation_labels",
        "reference_interpretation",
        "reference_interpretations",
        "canonical_gold_plan",
        "canonical_logical_plan",
        "ontology_slots",
        "answer_column",
        "answer_path_position",
        "q",
        "a",
        "a_recommended",
    }
)


class GrailQASemanticPaperRunEvidenceError(ValueError):
    """Raised when a run package cannot be read safely."""


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular_file(path: Path, *, root: Path, name: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise GrailQASemanticPaperRunEvidenceError(
            f"{name} must be a regular non-symbolic-link file"
        )
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise GrailQASemanticPaperRunEvidenceError(
            f"{name} escapes the run root"
        ) from exc
    return resolved


def _load_json(path: Path, *, root: Path, name: str) -> dict[str, Any]:
    source = _regular_file(path, root=root, name=name)
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise GrailQASemanticPaperRunEvidenceError(f"{name} is not an object")
    return dict(value)


def _load_jsonl(path: Path, *, root: Path, name: str) -> list[dict[str, Any]]:
    source = _regular_file(path, root=root, name=name)
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        source.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line:
            continue
        value = json.loads(line)
        if not isinstance(value, Mapping):
            raise GrailQASemanticPaperRunEvidenceError(
                f"{name} line {line_number} is not an object"
            )
        rows.append(dict(value))
    return rows


def _tree_snapshot(root: Path) -> dict[str, tuple[int, str]]:
    snapshot: dict[str, tuple[int, str]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise GrailQASemanticPaperRunEvidenceError(
                f"run tree contains symbolic link: {path.relative_to(root)}"
            )
        if path.is_file():
            snapshot[path.relative_to(root).as_posix()] = (
                path.stat().st_size,
                _file_sha256(path),
            )
    return snapshot


def _self_hash(value: Mapping[str, Any], field: str) -> str:
    return content_hash({key: item for key, item in value.items() if key != field})


def _contains_forbidden_inference_key(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().casefold()
            if (
                normalized in _FORBIDDEN_INFERENCE_KEYS
                or normalized.startswith("gold_")
            ):
                return True
            if _contains_forbidden_inference_key(child):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_forbidden_inference_key(item) for item in value)
    return False


def _parse_time(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def audit_grailqa_semantic_paper_run(
    *, run_root: str | Path, expected_commit: str
) -> dict[str, Any]:
    """Audit a successful run without changing its evidence tree."""

    root = Path(run_root).resolve()
    if root.is_symlink() or not root.is_dir():
        raise GrailQASemanticPaperRunEvidenceError(
            "run_root must be a non-symbolic-link directory"
        )
    if _COMMIT.fullmatch(expected_commit) is None:
        raise GrailQASemanticPaperRunEvidenceError(
            "expected_commit must be exact 40-hex"
        )
    before = _tree_snapshot(root)
    checks: list[dict[str, Any]] = []

    def check(check_id: str, expected: Any, observed: Any) -> None:
        passed = expected == observed
        checks.append(
            {
                "check_id": check_id,
                "passed": passed,
                "detail": (
                    None
                    if passed
                    else {"expected": expected, "observed": observed}
                ),
            }
        )

    request = _load_json(
        root / "control/execution_request.json",
        root=root,
        name="execution request",
    )
    authority = _load_json(
        root / "control/execution_authority.json",
        root=root,
        name="execution authority",
    )
    seal = _load_json(
        root / "inference/inference_seal.json",
        root=root,
        name="inference seal",
    )
    manifest = _load_json(root / "run_manifest.json", root=root, name="manifest")
    status = _load_json(root / "run_status.json", root=root, name="run status")
    outcomes_path = root / "evaluation/query_outcomes.jsonl"
    outcomes = _load_jsonl(
        outcomes_path, root=root, name="query outcome ledger"
    )

    check("request.schema", EXECUTION_REQUEST_SCHEMA_VERSION, request.get("schema_version"))
    check(
        "request.self_hash",
        _self_hash(request, "execution_request_sha256"),
        request.get("execution_request_sha256"),
    )
    check("request.authorized", False, request.get("full_150_execution_authorized"))
    check("request.paper_result", False, request.get("paper_result"))
    check("request.runner_commit", expected_commit, request.get("runner_commit"))

    check(
        "authority.schema",
        EXECUTION_AUTHORITY_SCHEMA_VERSION,
        authority.get("schema_version"),
    )
    check(
        "authority.self_hash",
        _self_hash(authority, "execution_authority_sha256"),
        authority.get("execution_authority_sha256"),
    )
    check(
        "authority.request_binding",
        request.get("execution_request_sha256"),
        authority.get("execution_request_sha256"),
    )
    check(
        "authority.decision",
        "authorize_exact_150_query_semantic_execution",
        authority.get("decision"),
    )
    check("authority.authorized", True, authority.get("full_150_execution_authorized"))
    check("authority.single_run", True, authority.get("single_run_only"))
    check("authority.paper_result", False, authority.get("paper_result"))
    check(
        "authority.scope",
        {
            "query_count": 150,
            "maximum_external_calls": 300,
            "maximum_repair_calls_per_query": 1,
            "automatic_retries": 0,
            "backend_execution": False,
        },
        authority.get("authorized_scope"),
    )

    check("seal.schema", INFERENCE_SEAL_SCHEMA_VERSION, seal.get("schema_version"))
    check(
        "seal.self_hash",
        _self_hash(seal, "inference_seal_sha256"),
        seal.get("inference_seal_sha256"),
    )
    check("seal.question_count", 150, seal.get("question_count"))
    check("seal.all_states", True, seal.get("all_query_states_present"))
    check("seal.gold_closed", False, seal.get("gold_artifacts_opened"))
    check("seal.automatic_retries", 0, seal.get("automatic_retries"))
    check("seal.backend_calls", 0, seal.get("backend_calls"))
    check("seal.native_query", False, seal.get("native_query_text_emitted"))
    check(
        "seal.request_binding",
        request.get("execution_request_sha256"),
        seal.get("execution_request_sha256"),
    )
    check(
        "seal.authority_binding",
        authority.get("execution_authority_sha256"),
        seal.get("execution_authority_sha256"),
    )

    state_records = seal.get("query_state_files")
    if not isinstance(state_records, list):
        state_records = []
    check("states.record_count", 150, len(state_records))
    state_ids: list[str] = []
    state_hashes_match = True
    no_gold_leakage = True
    external_calls = 0
    repair_calls = 0
    provider_bounds_hold = True
    state_paths: list[str] = []
    for record_value in state_records:
        if not isinstance(record_value, Mapping):
            state_hashes_match = False
            continue
        record = dict(record_value)
        question_id = str(record.get("question_id", ""))
        expected_relative = f"inference/query-state/{question_id}.json"
        relative = str(record.get("path", ""))
        if (
            _SAFE_ID.fullmatch(question_id) is None
            or relative != expected_relative
            or _SHA256.fullmatch(str(record.get("sha256", ""))) is None
        ):
            state_hashes_match = False
            continue
        try:
            state_path = _regular_file(
                root / relative, root=root, name=f"state {question_id}"
            )
            state = _load_json(
                state_path, root=root, name=f"state {question_id}"
            )
        except Exception:  # noqa: BLE001 - summarized by the failed check.
            state_hashes_match = False
            continue
        state_ids.append(question_id)
        state_paths.append(relative)
        state_hashes_match &= _file_sha256(state_path) == record["sha256"]
        question = state.get("question")
        state_hashes_match &= (
            isinstance(question, Mapping)
            and str(question.get("question_id")) == question_id
        )
        no_gold_leakage &= not _contains_forbidden_inference_key(state)
        requests = state.get("request_records")
        repairs = state.get("repair_calls")
        if (
            not isinstance(requests, list)
            or isinstance(repairs, bool)
            or not isinstance(repairs, int)
        ):
            provider_bounds_hold = False
            continue
        calls = len(requests)
        external_calls += calls
        repair_calls += repairs
        provider_bounds_hold &= (
            calls <= 2 and 0 <= repairs <= 1 and repairs <= calls
        )
    population = request.get("population")
    expected_population_hash = (
        population.get("question_ids_sha256")
        if isinstance(population, Mapping)
        else None
    )
    check(
        "states.exact_population",
        (150, 150, expected_population_hash),
        (len(state_ids), len(set(state_ids)), content_hash(state_ids)),
    )
    check("states.hashes", True, state_hashes_match)
    check("states.no_gold_leakage", True, no_gold_leakage)
    check("states.provider_bounds", True, provider_bounds_hold)
    check("states.aggregate_external_calls_bound", True, external_calls <= 300)
    check("states.aggregate_repair_calls_bound", True, repair_calls <= 150)
    check("seal.external_calls", external_calls, seal.get("provider_external_calls"))
    check("seal.repair_calls", repair_calls, seal.get("provider_repair_calls"))

    outcome_ids: list[str] = []
    outcomes_valid = True
    outcome_external_calls = 0
    outcome_repair_calls = 0
    for row in outcomes:
        question_id = str(row.get("question_id", ""))
        provider = row.get("provider")
        candidates = row.get("candidates")
        if (
            row.get("schema_version") != QUERY_OUTCOME_SCHEMA_VERSION
            or _SAFE_ID.fullmatch(question_id) is None
            or not isinstance(provider, Mapping)
            or not isinstance(candidates, list)
            or len(candidates) > 3
        ):
            outcomes_valid = False
            continue
        calls = provider.get("external_calls")
        repairs = provider.get("repair_calls")
        if (
            isinstance(calls, bool)
            or not isinstance(calls, int)
            or isinstance(repairs, bool)
            or not isinstance(repairs, int)
            or calls not in {0, 1, 2}
            or repairs not in {0, 1}
            or repairs > calls
        ):
            outcomes_valid = False
            continue
        outcome_ids.append(question_id)
        outcome_external_calls += calls
        outcome_repair_calls += repairs
    check("outcomes.schema_and_bounds", True, outcomes_valid)
    check(
        "outcomes.exact_population",
        (150, 150, state_ids),
        (len(outcome_ids), len(set(outcome_ids)), outcome_ids),
    )
    check("outcomes.external_calls", external_calls, outcome_external_calls)
    check("outcomes.repair_calls", repair_calls, outcome_repair_calls)

    check("manifest.schema", RUN_MANIFEST_SCHEMA_VERSION, manifest.get("schema_version"))
    check("manifest.status", "success", manifest.get("status"))
    check("manifest.runner_commit", expected_commit, manifest.get("runner_commit"))
    check(
        "manifest.self_hash",
        _self_hash(manifest, "run_manifest_sha256"),
        manifest.get("run_manifest_sha256"),
    )
    check(
        "manifest.request_binding",
        request.get("execution_request_sha256"),
        manifest.get("execution_request_sha256"),
    )
    check(
        "manifest.authority_binding",
        authority.get("execution_authority_sha256"),
        manifest.get("execution_authority_sha256"),
    )
    check(
        "manifest.seal_binding",
        seal.get("inference_seal_sha256"),
        manifest.get("inference_seal_sha256"),
    )
    ledger_sha256 = _file_sha256(outcomes_path)
    check("manifest.ledger_binding", ledger_sha256, manifest.get("outcome_ledger_sha256"))
    check("manifest.question_count", 150, manifest.get("question_count"))
    check("manifest.external_calls", external_calls, manifest.get("provider_external_calls"))
    check("manifest.repair_calls", repair_calls, manifest.get("provider_repair_calls"))
    check("manifest.automatic_retries", 0, manifest.get("automatic_retries"))
    check("manifest.backend_calls", 0, manifest.get("backend_calls"))
    check("manifest.native_query", False, manifest.get("native_query_text_emitted"))
    check("manifest.selection_uses_gold", False, manifest.get("selection_uses_gold"))
    check("manifest.failures_retained", True, manifest.get("failures_retained"))
    check("manifest.paper_result", False, manifest.get("paper_result"))

    started = _parse_time(manifest.get("started_at"))
    sealed = _parse_time(seal.get("sealed_at"))
    gold_opened = _parse_time(manifest.get("gold_opened_at"))
    ended = _parse_time(manifest.get("ended_at"))
    check(
        "phase_order",
        True,
        bool(
            started
            and sealed
            and gold_opened
            and ended
            and started <= sealed <= gold_opened <= ended
            and manifest.get("inference_sealed_at") == seal.get("sealed_at")
            and manifest.get("inference_seal_written_before_gold_open") is True
            and manifest.get("gold_opened_after_all_inference") is True
        ),
    )
    source_body = {
        "run_id": request.get("run_id"),
        "execution_request_sha256": request.get("execution_request_sha256"),
        "execution_authority_sha256": authority.get("execution_authority_sha256"),
        "inference_seal_sha256": seal.get("inference_seal_sha256"),
        "inference_sealed_at": seal.get("sealed_at"),
        "gold_opened_at": manifest.get("gold_opened_at"),
        "outcome_ledger_sha256": ledger_sha256,
    }
    source_run_sha256 = content_hash(source_body)
    check("manifest.source_run_identity", source_run_sha256, manifest.get("source_run_sha256"))

    check("status.schema", RUN_STATUS_SCHEMA_VERSION, status.get("schema_version"))
    check("status.success", "success", status.get("status"))
    check("status.run_id", request.get("run_id"), status.get("run_id"))
    check("status.source_run_identity", source_run_sha256, status.get("source_run_sha256"))
    check("status.paper_result", False, status.get("paper_result"))

    expected_files = {
        "control/execution_request.json",
        "control/execution_authority.json",
        "inference/inference_seal.json",
        "evaluation/query_outcomes.jsonl",
        "run_manifest.json",
        "run_status.json",
        *state_paths,
    }
    check("run_tree.file_set", sorted(expected_files), sorted(before))
    after = _tree_snapshot(root)
    check("run_tree.non_mutating_audit", before, after)
    failed = [item["check_id"] for item in checks if not item["passed"]]
    body: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "audited_at": datetime.now().astimezone().isoformat(),
        "run_root": str(root),
        "expected_commit": expected_commit,
        "source_run_sha256": manifest.get("source_run_sha256"),
        "check_count": len(checks),
        "failed_check_ids": failed,
        "checks": checks,
        "run_tree_mutated": before != after,
        "external_call_counts": {
            "llm_calls": external_calls,
            "repair_calls": repair_calls,
            "backend_calls": 0,
            "ontology_service_calls": 0,
        },
        "claim_boundary": {
            "independent_run_reconstruction": True,
            "contains_new_measurements": False,
            "promotes_to_paper_result": False,
            "paper_result": False,
        },
        "success": not failed,
        "paper_result": False,
    }
    return {**body, "audit_sha256": content_hash(body)}


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"audit output exists: {path}")
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        audit = audit_grailqa_semantic_paper_run(
            run_root=args.run_root,
            expected_commit=args.expected_commit,
        )
        _write_json_exclusive(Path(args.output), audit)
    except (FileExistsError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps({"status": "success", **audit}, sort_keys=True))
    return 0 if audit["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
